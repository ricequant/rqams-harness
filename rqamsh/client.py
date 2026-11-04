"""同步 HTTP 传输、异步等待及工作空间内资源解析。"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from contextlib import ExitStack, contextmanager
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import quote, urlsplit, urlunsplit
import math
import os

import requests

from .errors import HarnessError
from .settings import load_settings, remember_workspace, settings_path as default_settings_path
from .transport import DeadlineAdapter, request_deadline


# 资源目录的复用窗口：同一客户端在这段时间内不重复列举产品、产品组与资产单元。
# 索引及详情共用 5 分钟窗口；周期等配置也会影响业务路由，重建时不能留下旧详情。
_CATALOG_TTL_SECONDS = 300.0

# 目录逐项详情的并发上限：与 requests 对每个主机的默认连接池大小一致，避免请求在池上排队。
_CATALOG_CONCURRENCY = 10

# 只读的查询端点：它们用 POST 传参但只读数据、不改变资源集合，因此不作废目录缓存。
# 白名单按保守方向维护——漏登记只会多一次目录重建，错登记才会留下过期目录，
# 所以只登记能确认只读的端点（例如标记对账的 products/<id>:reconciliation 属写入，不要放进来）。
_CATALOG_NEUTRAL_PATHS = frozenset({
    "asset_snapshot_summary",
    "balance:get_previous_summary",
    "products/balance:query_field_existed_earliest_date",
    "products/balance:query_field_existed_earliest_dates_by_product",
    "products:batch_get_reconciliation_list",
    "products:get_uploaded_files_hash",
})

# 非资源集合上的写入端点：挂在产品路径下，但增删的是任务记录而不是产品、组或资产单元，
# 改不到目录内容，因此同样不作废缓存（归因任务的提交与删除）。
_CATALOG_NEUTRAL_WRITES = (("products", "performance_attributions"), ("product_groups", "performance_attributions"))

# 地址与令牌常从文件读入，带 Windows 行尾回车或首尾空白：不处理会让地址解析失败、
# 或让 Authorization 头变成非法请求头（requests 直接抛错），所以建连时统一去掉。
_WRAPPING_WHITESPACE = " \t\r\n\v\f"

# 未显式提供地址时连接线上 AMS；私有化部署必须用 base_url/RQAMSH_BASE_URL 覆盖。
DEFAULT_BASE_URL = "https://www.ricequant.com"


def _without_wrapping_whitespace(value):
    """去掉字符串首尾空白与行尾回车；非字符串原样返回。"""
    return value.strip(_WRAPPING_WHITESPACE) if isinstance(value, str) else value


def _normalized_token(token):
    """校验并清理 Bearer 令牌；空值、非字符串或内部换行在本地拒绝。"""
    if not isinstance(token, str) or not token.strip(_WRAPPING_WHITESPACE):
        raise HarnessError("invalid_config", "必须提供非空 token（Bearer 令牌）")
    value = _without_wrapping_whitespace(token)
    if any(char in value for char in "\r\n"):
        raise HarnessError("invalid_config", "token 不能包含换行")
    return value


def _normalized_base_url(value):
    """规范化部署 API 根地址，用于请求和保存身份的部署绑定比较。"""
    if not isinstance(value, str):
        raise HarnessError("invalid_config", "base_url 必须为 HTTP(S) 地址字符串")
    try:
        parsed = urlsplit(_without_wrapping_whitespace(value))
        port = parsed.port
    except ValueError as exc:
        raise HarnessError("invalid_config", "base_url 必须为合法 HTTP(S) 地址") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment:
        raise HarnessError("invalid_config", "base_url 必须为不带身份、查询和片段的 HTTP(S) 地址")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != default_port:
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/rqams/v2"):
        path += "/api/rqams/v2"
    return urlunsplit((parsed.scheme, host, path, "", ""))


def _catalog_neutral(path) -> bool:
    """判断一次非 GET 调用会不会改到目录内容；改不到就不作废缓存。

    只认两类：按路径登记的只读查询（`_CATALOG_NEUTRAL_PATHS`），以及挂在资源路径下、
    增删任务记录的非资源集合写入（`_CATALOG_NEUTRAL_WRITES`，末段为集合名，可再带一个记录 ID）。
    其余写请求一律作废，宁可多重建一次，也不留过期目录。
    """
    tail = path.strip("/")
    if tail in _CATALOG_NEUTRAL_PATHS:
        return True
    parts = tail.split("/")
    if len(parts) in (3, 4):
        return (parts[0], parts[2]) in _CATALOG_NEUTRAL_WRITES
    return False


def _wait_message(payload) -> str:
    """等待超时的错误文案：带上服务端最后一次返回的提示，便于区分未就绪与任务仍在运行。"""
    hint = payload.get("message") if isinstance(payload, dict) else None
    base = "等待超时；服务端任务可能仍在运行，请勿重复提交"
    return f"{base}（服务端最后返回：{hint}）" if hint else base


@dataclass(frozen=True)
class ResourceRef:
    """已解析的资源；parent_id 用于依附产品的资产单元。"""

    type: str
    id: str
    name: str
    parent_id: str | None = None
    data: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def path(self):
        """返回唯一资源的相对 API 路径。"""
        identifier = quote(self.id, safe="")
        if self.type == "asset_unit":
            return f"products/{quote(self.parent_id, safe='')}/asset_units/{identifier}"
        collection = {"product": "products", "product_group": "product_groups"}[self.type]
        return f"{collection}/{identifier}"

    def to_dict(self):
        """返回公开候选信息，不携带完整产品数据。"""
        return {"type": self.type, "id": self.id, "name": self.name, "parent_id": self.parent_id}


class Client:
    """连接 AMS：Bearer PAT 确定用户身份；未指定空间时默认成员列表首项。"""

    def __init__(self, base_url=None, workspace_id=None, *, token=None, timeout=60, wait_timeout=300, poll_interval=1, settings_path=None):
        """创建客户端；地址、令牌、工作空间或超时非法时抛 HarnessError。

        地址省略时先查设置文件，再使用线上默认地址；私有化部署必须显式传入或保存自己的地址。
        身份优先使用显式 token；省略时读取用户目录的设置文件（可用 RQAMSH_SETTINGS 覆盖），
        仅在保存的部署地址与目标部署相同时复用该身份和 workspace_id；无地址绑定或换部署时报错。
        登录流程见 ``rqamsh.auth.login``。
        """
        target = Path(settings_path).expanduser() if settings_path is not None else default_settings_path()
        needs_settings = token is None or base_url is None
        settings = load_settings(target) if needs_settings else {}
        used_saved_token = token is None
        explicit_workspace = workspace_id is not None
        if base_url is None:
            base_url = settings.get("base_url") or DEFAULT_BASE_URL
        if token is None:
            token = settings.get("token")
        root = _normalized_base_url(base_url)
        if token is None:
            raise HarnessError("invalid_config", "未找到 token；先运行 rqamsh auth 或设置 RQAMSH_TOKEN")
        token = _normalized_token(token)
        if used_saved_token:
            saved_address = settings.get("base_url")
            if saved_address is None or _normalized_base_url(saved_address) != root:
                raise HarnessError("invalid_config", "保存的 token 未绑定当前部署；请运行 rqamsh auth 或显式提供该部署的 token")
            if workspace_id is None:
                workspace_id = settings.get("workspace_id")
        if workspace_id is not None and (not isinstance(workspace_id, str) or len(workspace_id) != 24 or any(c not in "0123456789abcdefABCDEF" for c in workspace_id)):
            raise HarnessError("invalid_config", "workspace_id 必须为 24 位十六进制 ID")
        for name, value in (("timeout", timeout), ("wait_timeout", wait_timeout), ("poll_interval", poll_interval)):
            if not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise HarnessError("invalid_config", f"{name} 必须为正有限数值")
        self.base_url = root
        self.user_base = root.removesuffix("/api/rqams/v2") + "/api/user"
        self.timeout, self.wait_timeout, self.poll_interval = timeout, wait_timeout, poll_interval
        self.workspace_id = workspace_id.lower() if workspace_id else None
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.mount("http://", DeadlineAdapter())
        self.session.mount("https://", DeadlineAdapter())
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if self.workspace_id is not None:
            headers["X-AMS-Workspace"] = self.workspace_id
        self.session.headers.update(headers)
        self._closed = False
        self._resources = {}
        self._settings_path = target
        self._remember_settings = bool(used_saved_token and settings.get("token"))
        if self._remember_settings and explicit_workspace:
            remember_workspace(self.workspace_id, path=self._settings_path)
        # (workspace_id, 抓取时刻, 目录条目)；切换空间与写入请求都会让它失效。
        self._catalog_cache = None
        # 轻量索引只含集合列表项，用于按 ID/名称定位；命中后才读该资源详情。
        # 单资源解析不再为整个空间逐项拉详情，避免上百个资源时把解析放大成上百条请求。
        self._catalog_index_cache = None
        # 已核验可读的详情缓存；键为 (type, parent_id, id)。
        self._resource_detail_cache = {}

    def __getattr__(self, name):
        """懒加载功能块，未知名称抛 AttributeError。"""
        from .resources import RESOURCE_CLASSES
        if name not in RESOURCE_CLASSES:
            raise AttributeError(name)
        if name not in self._resources:
            self._resources[name] = RESOURCE_CLASSES[name](self)
        return self._resources[name]

    def close(self):
        """关闭连接池，可重复调用。"""
        self.session.close()
        self._closed = True

    def __enter__(self):
        """返回当前客户端用于 with 生命周期。"""
        return self

    def __exit__(self, *args):
        """无论业务成功或失败都关闭连接。"""
        self.close()

    @staticmethod
    def _params(params):
        """转换 query 的布尔和列表，同时保留空字符串、零与 False。"""
        result = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                value = str(value).lower()
            elif isinstance(value, (list, tuple)):
                value = ",".join(str(item) for item in value)
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            result[key] = value
        return result

    @staticmethod
    @contextmanager
    def _download_target(path, diagnostics):
        """提前独占输出文件；仅清理本调用实际创建的失败文件。"""
        target = Path(path)
        stream = target.open("xb", buffering=0)
        owned = os.fstat(stream.fileno())
        try:
            yield stream
            stream.close()
        except BaseException as original:
            cleanup_errors = []
            try:
                stream.close()
            except OSError as close_error:
                cleanup_errors.append(str(close_error))
            try:
                current = target.stat()
                if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                    target.unlink()
            except FileNotFoundError:
                cleanup_errors.append("下载文件在清理前已消失")
            except OSError as unlink_error:
                cleanup_errors.append(str(unlink_error))
            if cleanup_errors:
                diagnostics["cleanup_errors"] = cleanup_errors
            if isinstance(original, OSError):
                raise HarnessError("download_failed", str(original), details=diagnostics) from original
            raise

    @staticmethod
    def _save_download(response, stream, deadline, diagnostics):
        """分块写入文件；读写失败保留任务诊断，禁止重放一次性下载。"""
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if monotonic() >= deadline:
                    raise HarnessError("wait_timeout", "下载总等待超时", details=diagnostics)
                remaining = memoryview(chunk)
                while remaining:
                    if monotonic() >= deadline:
                        raise HarnessError("wait_timeout", "下载写入总等待超时", details=diagnostics)
                    written = stream.write(remaining)
                    if not written:
                        raise OSError("下载文件未写入任何字节")
                    size += written
                    remaining = remaining[written:]
            stream.flush()
        except (OSError, requests.RequestException) as exc:
            code = "wait_timeout" if monotonic() >= deadline else "download_failed"
            raise HarnessError(code, str(exc), details=diagnostics) from exc
        return {"path": str(Path(stream.name).resolve()), "size": size}

    def call(self, method, path, *, params=None, json=None, data=None, file_path=None, file_paths=None, file_field=None, legacy_task=False, no_replay=False, download=None, base=None, select_workspace=True, headers=None):
        """执行相对端点并有界等待；异常保留任务 ID，不自动重放不明写入。base 可指向业务前缀之外的接口前缀。

        file_path 用于单文件（默认表单字段 file）；file_paths 用于多文件（默认表单字段 files）。
        两者不能同时提供，文件句柄在本调用结束前保持打开。
        """
        if self._closed:
            raise HarnessError("client_closed", "客户端已关闭")
        if self.workspace_id is None and select_workspace:
            self._select_default_workspace()
        # 路径始终拼接在固定base_url后；集合动作的冒号不是URL scheme。
        if path.startswith(("/", "\\")) or "://" in path or ".." in path.split("/") or "?" in path or "#" in path:
            raise HarnessError("invalid_path", "仅允许本服务内的相对 API 路径")
        url = (base or self.base_url) + "/" + path
        method = method.upper()
        query = self._params(params)
        deadline = monotonic() + self.wait_timeout
        task_id = None
        payload = None
        original_method = method
        if original_method != "GET" and not _catalog_neutral(path):
            # 写请求可能改变资源集合：进入调用即作废目录缓存，成功与失败后都由下一次解析重建。
            # 只读的批量查询与不改资源集合的任务端点（见 _CATALOG_NEUTRAL_PATHS/_CATALOG_NEUTRAL_WRITES）不动缓存。
            self._clear_catalogs()
        diagnostics = {"url": url, "task_id": task_id, "response": payload}
        with ExitStack() as stack:
            destination = stack.enter_context(self._download_target(download, diagnostics)) if download is not None else None
            files = None
            if file_path is not None and file_paths is not None:
                raise HarnessError("invalid_argument", "file_path 与 file_paths 不能同时提供")
            if file_path is not None:
                field = file_field or "file"
                stream = stack.enter_context(open(file_path, "rb"))
                files = {field: (Path(file_path).name, stream)}
            elif file_paths is not None:
                if not isinstance(file_paths, (list, tuple)) or not file_paths:
                    raise HarnessError("invalid_argument", "file_paths 必须为非空文件路径数组")
                field = file_field or "files"
                files = []
                for path in file_paths:
                    if not isinstance(path, (str, os.PathLike)):
                        raise HarnessError("invalid_argument", "file_paths 的元素必须为文件路径")
                    stream = stack.enter_context(open(path, "rb"))
                    files.append((field, (Path(path).name, stream)))
            while True:
                remaining = deadline - monotonic()
                diagnostics.update(task_id=task_id, response=payload)
                if remaining <= 0:
                    raise HarnessError("wait_timeout", _wait_message(payload), details=diagnostics)
                try:
                    with request_deadline(deadline):
                        response = self.session.request(method, url, params=query, json=json, data=data, files=files, headers=headers,
                                                        timeout=min(self.timeout, remaining), allow_redirects=False,
                                                        stream=download is not None)
                except requests.RequestException as exc:
                    code = "wait_timeout" if monotonic() >= deadline else "transport_error"
                    raise HarnessError(code, str(exc), details=diagnostics) from exc
                try:
                    if monotonic() >= deadline:
                        raise HarnessError("wait_timeout", "请求总等待超时", details=diagnostics)
                    content_type = response.headers.get("Content-Type", "").lower()
                    if download is not None and response.status_code == 200 and "json" not in content_type:
                        if not any(kind in content_type for kind in ("octet-stream", "excel", "spreadsheet", "csv", "pdf", "zip")):
                            raise HarnessError("invalid_download", "下载接口未返回受支持的文件类型", details=diagnostics)
                        return self._save_download(response, destination, deadline, diagnostics)
                    try:
                        payload = response.json() if response.content else None
                    except requests.exceptions.JSONDecodeError:
                        payload = {"message": response.text[:4096]}
                        if response.ok and response.status_code != 202:
                            raise HarnessError("invalid_response", "预期 JSON，但服务返回非 JSON 内容", status=response.status_code, details=payload)
                    except requests.RequestException as exc:
                        code = "wait_timeout" if monotonic() >= deadline else "transport_error"
                        raise HarnessError(code, str(exc), details=diagnostics) from exc
                    diagnostics.update(task_id=task_id, response=payload)
                    if not 200 <= response.status_code < 300:
                        message = payload.get("message", response.reason) if isinstance(payload, dict) else response.reason
                        # 403 恒为权限拒绝（网关按逐路由规则或服务端资源校验），保持既有错误码。
                        code = "permission_denied" if response.status_code == 403 else "http_error"
                        raise HarnessError(code, str(message), status=response.status_code, details=diagnostics)
                    task_status = payload.get("status") if isinstance(payload, dict) else None
                    if (legacy_task or no_replay or task_id) and task_status in {"FAIL", "FAILURE", "failed", "error", "REVOKED"}:
                        raise HarnessError("task_failed", payload.get("message", "服务端任务失败"), status=response.status_code, details=diagnostics)
                    accepted = response.status_code == 202
                    legacy_pending = legacy_task and isinstance(payload, dict) and bool(payload.get("task_id")) and task_status not in {"SUCCESS", "success"}
                    doing = (legacy_task or no_replay or task_id) and task_status in {"DOING", "PENDING", "STARTED", "PROGRESS", "running", "computing"}
                    if not (accepted or legacy_pending or doing):
                        if download is not None:
                            raise HarnessError("invalid_download", "下载接口未返回文件", details=diagnostics)
                        return payload
                    new_task_id = payload.get("task_id") if isinstance(payload, dict) else None
                    if new_task_id:
                        task_id = str(new_task_id)
                    if task_id:
                        query["task_id"] = task_id
                        method = "GET"
                        json = data = files = None
                    elif original_method != "GET" or no_replay:
                        raise HarnessError("pending_without_task", "写请求尚未完成且无 task_id；为避免重复写入不重试", status=202, details=diagnostics)
                    retry_after = response.headers.get("Retry-After", "")
                    interval = self.poll_interval
                    try:
                        hinted = float(retry_after)
                        if math.isfinite(hinted) and hinted > 0:
                            interval = hinted
                    except ValueError:
                        interval = self.poll_interval
                finally:
                    response.close()
                sleep(max(0, min(interval, deadline - monotonic())))

    def resource_catalog(self):
        """读取当前工作空间的产品、组和资产单元；同一客户端在缓存窗口内复用同一份目录。

        可见性由服务端与网关决定：只把能读到详情的资源放进目录，不比较读取级别，
        越级调用交由它们拒绝。缓存是同一客户端 5 分钟内的视图：任何写入请求与切换空间都会让它失效
        （只读的批量查询即使走 POST 也不失效），解析不到资源时会强制重建一次再判定。
        并发身份各持一个客户端实例，因此缓存不加锁。
        """
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        return self._rebuild_catalog()

    def _cached_catalog(self):
        """返回当前空间的未过期目录；没有可用缓存时返回 None。"""
        cache = self._catalog_cache
        if cache is None:
            return None
        workspace_id, fetched_at, refs = cache
        if workspace_id != self.workspace_id or monotonic() - fetched_at > _CATALOG_TTL_SECONDS:
            return None
        return refs

    def _rebuild_catalog(self):
        """淘汰旧详情后重建目录，避免新目录继续暴露旧配置或已撤销的访问。"""
        self._clear_catalogs()
        refs = self._build_catalog()
        self._catalog_cache = (self.workspace_id, monotonic(), refs)
        return refs

    def _clear_catalogs(self):
        """清空目录、轻量索引与详情缓存；写入、切换空间或目录过期后调用。"""
        self._catalog_cache = None
        self._catalog_index_cache = None
        self._resource_detail_cache.clear()

    def _cached_catalog_index(self):
        """返回当前空间的未过期轻量索引；没有可用缓存时返回 None。"""
        cache = self._catalog_index_cache
        if cache is None:
            return None
        workspace_id, fetched_at, refs = cache
        if workspace_id != self.workspace_id or monotonic() - fetched_at > _CATALOG_TTL_SECONDS:
            return None
        return refs

    def _rebuild_catalog_index(self):
        """同步淘汰目录和详情后重建索引，不为旧详情延长缓存寿命。"""
        self._clear_catalogs()
        refs = self._build_catalog_index()
        self._catalog_index_cache = (self.workspace_id, monotonic(), refs)
        return refs

    def _catalog_index_snapshot(self):
        """返回轻量索引与它是否直接来自缓存，供解析失败时判断能否只重建重试。"""
        cached = self._cached_catalog_index()
        if cached is not None:
            return cached, True
        return self._rebuild_catalog_index(), False

    def _build_catalog_index(self):
        """只列集合，不逐项拉详情；用于按 ID/名称定位单个或少量资源。

        单资源解析不应为整个空间付出逐项详情请求；命中后再由 ``_fetch_detail``
        核验该资源详情是否可读。目录列表与资产单元仍按集合顺序组装。
        """
        if self.workspace_id is None:
            self._select_default_workspace()
        refs = []
        product_ids = set()
        with ThreadPoolExecutor(max_workers=3) as pool:
            listings = {
                path: pool.submit(self.call, "GET", path)
                for path in ("products", "product_groups", "products/asset_units")
            }
            for collection, kind in (("products", "product"), ("product_groups", "product_group")):
                for identifier, item in self._catalog_entries(listings[collection].result(), collection):
                    refs.append(ResourceRef(kind, identifier, item.get("name", ""), data=item))
                    if kind == "product":
                        product_ids.add(identifier)
            units = listings["products/asset_units"].result()
        for product in units:
            parent = str(product["product_id"])
            if parent not in product_ids:
                continue
            for unit in product.get("asset_units", []):
                refs.append(ResourceRef("asset_unit", str(unit.get("id", unit.get("_id"))), unit.get("symbol", ""), parent, unit))
        return refs

    def _fetch_detail(self, ref):
        """读取并缓存单个资源详情；403/404 表示读不到，返回 None。

        产品与产品组走详情端点；资产单元没有详情端点，集合返回的就是完整记录。
        其他错误原样抛出，保持与目录构建相同的失败语义。
        """
        key = (ref.type, ref.parent_id, ref.id)
        if key in self._resource_detail_cache:
            return self._resource_detail_cache[key]
        if ref.type == "asset_unit":
            return ref.data
        collection = "products" if ref.type == "product" else "product_groups"
        try:
            detail = self.call("GET", f"{collection}/{quote(ref.id, safe='')}")
        except HarnessError as exc:
            if exc.status in {403, 404}:
                return None
            raise
        self._resource_detail_cache[key] = detail
        return detail

    def _build_catalog(self):
        """重建完整目录：先取轻量索引，再按集合顺序核验每个资源的详情。

        详情读取失败按可见性语义处理：403/404 视为读不到而跳过，其他错误原样抛出；
        并发下多个错误同时出现时按资源在集合中的顺序抛出第一个，保证同一环境下报错可复现。
        """
        index = self._build_catalog_index()
        # 完整目录已经包含这份索引：顺手写入索引缓存，后续单资源解析不必再列一次集合。
        self._catalog_index_cache = (self.workspace_id, monotonic(), index)
        refs = []
        with ThreadPoolExecutor(max_workers=_CATALOG_CONCURRENCY) as pool:
            pending = [
                (ref, pool.submit(self._fetch_detail, ref) if ref.type != "asset_unit" else None)
                for ref in index
            ]
            for ref, future in pending:
                if future is None:
                    refs.append(ref)
                    continue
                detail = future.result()
                if detail is None:
                    continue
                self._resource_detail_cache[(ref.type, ref.parent_id, ref.id)] = detail
                refs.append(ResourceRef(ref.type, ref.id, detail.get("name", ref.name), ref.parent_id, detail))
        return refs

    @staticmethod
    def _catalog_entries(response, collection):
        """把集合响应拆成 (ID, 列表项) 序列；列表项缺 ID 时报错。"""
        entries = []
        for item in response.get(collection, []):
            identifier = str(item.get("id", item.get("_id", "")))
            if not identifier:
                raise HarnessError("invalid_response", "资源列表缺少 ID", details=item)
            entries.append((identifier, item))
        return entries

    @staticmethod
    def _checked(resource):
        """验证单个资源选择器为非空字符串。"""
        if not isinstance(resource, str) or not resource:
            raise HarnessError("invalid_resource", "resource 必须为非空 ID 或名称字符串")
        return resource

    def _match_visible(self, catalog, resource, allowed):
        """在轻量索引中匹配资源，并只对候选项读取详情核验可见性。

        详情 403/404 的候选项视为读不到：全部读不到时报不存在，仍有多个可读时报歧义，
        只有一个可读时再校验资源类型。这样单个资源解析只需一次详情请求，而不是全空间逐项请求。
        """
        matches = [ref for ref in catalog if resource in {ref.id, ref.name}]
        if not matches:
            raise HarnessError("resource_not_found", "资源不存在或不可访问", status=404, details={"resource": resource})
        visible = []
        for ref in matches:
            detail = self._fetch_detail(ref)
            if detail is None:
                continue
            visible.append(ResourceRef(ref.type, ref.id, detail.get("name", ref.name), ref.parent_id, detail))
        if not visible:
            raise HarnessError("resource_not_found", "资源不存在或不可访问", status=404, details={"resource": resource})
        if len(visible) > 1:
            raise HarnessError("ambiguous_resource", "资源存在歧义，请使用候选项 ID", status=400, details={"resource": resource, "candidates": [ref.to_dict() for ref in visible]})
        ref = visible[0]
        if ref.type not in allowed:
            raise HarnessError("unsupported_resource", "此操作不支持目标资源类型", status=400, details={"resource": ref.to_dict(), "allowed": sorted(allowed)})
        return ref

    def resolve(self, resource, allowed):
        """按 ID 或精确名称选择唯一资源；歧义和类型不支持时抛结构化错误。"""
        checked = self._checked(resource)
        catalog, cached = self._catalog_index_snapshot()
        try:
            return self._match_visible(catalog, checked, allowed)
        except HarnessError as exc:
            if not cached or exc.code != "resource_not_found":
                raise
        # 刚被授权的资源可能还没进缓存索引：强制重建一次再判定，仍找不到才报不存在。
        return self._match_visible(self._rebuild_catalog_index(), checked, allowed)

    def resolve_many(self, resources, allowed):
        """在单个轻量索引快照上逐项解析多个资源并去重，保持首次出现顺序。"""
        if not isinstance(resources, list) or not resources:
            raise HarnessError("invalid_argument", "resources 必须为非空资源数组")
        checked = [self._checked(resource) for resource in resources]
        catalog, cached = self._catalog_index_snapshot()
        try:
            return self._match_many_visible(catalog, checked, allowed)
        except HarnessError as exc:
            if not cached or exc.code != "resource_not_found":
                raise
        return self._match_many_visible(self._rebuild_catalog_index(), checked, allowed)

    def _match_many_visible(self, catalog, checked, allowed):
        """逐项匹配并只读取命中项的详情，去重后保持首次出现顺序。"""
        refs, seen = [], set()
        for resource in checked:
            ref = self._match_visible(catalog, resource, allowed)
            key = (ref.type, ref.parent_id, ref.id)
            if key not in seen:
                seen.add(key)
                refs.append(ref)
        return refs

    def _select_default_workspace(self):
        """按服务端原顺序选中首个成员空间；没有成员空间时停止业务请求。"""
        rows = self.workspaces.list()["data"]
        if not rows:
            raise HarnessError("resource_not_found", "当前用户没有可用的成员工作空间")
        self.use_workspace(rows[0]["id"])
        return self.workspace_id

    def use_workspace(self, workspace_id):
        """把后续请求切到指定工作空间：同时更新身份属性与请求头，不改变用户身份。

        切换后作废目录缓存，后续解析按新空间的资源重建。
        """
        if not isinstance(workspace_id, str) or len(workspace_id) != 24 or any(c not in "0123456789abcdefABCDEF" for c in workspace_id):
            raise HarnessError("invalid_config", "workspace_id 必须为 24 位十六进制 ID")
        selected = workspace_id.lower()
        if self._remember_settings:
            remember_workspace(selected, path=self._settings_path)
        self.workspace_id = selected
        self.session.headers["X-AMS-Workspace"] = self.workspace_id
        self._clear_catalogs()
        return self.workspace_id

    @staticmethod
    def partial_failure(result, message="部分或全部数据导入失败；请检查逐项结果，勿全量重复上传"):
        """批量写入存在失败项时抛错并保留成功及失败记录；message 由调用块给出该块的措辞。"""
        pending = [result]
        failed = []
        while pending:
            row = pending.pop()
            if isinstance(row, list):
                pending.extend(row)
            elif isinstance(row, dict):
                if any(row.get(key) for key in ("err", "err_msg", "err_msgs", "failed", "error_messages")) or row.get("status") in {"FAIL", "failed"}:
                    failed.append(row)
                if "data" in row:
                    pending.append(row["data"])
        if failed:
            raise HarnessError("partial_failure", message, details={"results": result, "failed": failed})
        return result
