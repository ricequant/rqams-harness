"""同步 HTTP 传输、异步等待及工作空间内资源解析。"""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from contextlib import ExitStack, contextmanager
from pathlib import Path
from time import monotonic, sleep
from urllib.parse import quote, urlsplit
import math
import os

import requests
from requests.cookies import RequestsCookieJar

from .errors import HarnessError
from .transport import DeadlineAdapter, request_deadline


# 资源目录的复用窗口：同一客户端在这段时间内不重复列举产品、产品组与资产单元。
# 取 5 分钟：一次重建要上百条请求、约 2~3 秒，而解析调用在长会话里分散于思考与撰写之间，
# 60 秒的窗口几乎每轮都要重建；目录陈旧只影响新建或改名资源的可见性，分钟级可接受。
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

# 地址与凭据常从文件读入，带 Windows 行尾回车或首尾空白：不处理会让地址解析失败、
# 或让 cookie 值变成非法请求头（requests 直接抛错），所以建连时统一去掉。
_WRAPPING_WHITESPACE = " \t\r\n\v\f"


def _without_wrapping_whitespace(value):
    """去掉字符串首尾空白与行尾回车；非字符串原样返回。"""
    return value.strip(_WRAPPING_WHITESPACE) if isinstance(value, str) else value


def _normalized_cookies(source):
    """把 cookie 名称与值里的首尾空白与行尾回车去掉，返回可直接更新到会话上的映射。"""
    return {_without_wrapping_whitespace(name): _without_wrapping_whitespace(value) for name, value in source.items()}


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
    """连接 AMS：地址与已认证会话必需；工作空间默认取列举结果中的第一个。"""

    def __init__(self, base_url, workspace_id=None, *, session=None, cookies=None, timeout=60, wait_timeout=300, poll_interval=1):
        """创建客户端；地址、工作空间、会话或超时非法时抛 HarnessError。

        身份只来自注入的会话：session 只复制其中的 cookie，连接池、适配器与超时仍由本客户端管理。
        省略 workspace_id 时不预设分区：首次业务调用先列举可见空间并取记录中的第一个作为默认分区，
        之后可用 workspaces.use 切换。
        """
        parsed = urlsplit(_without_wrapping_whitespace(base_url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise HarnessError("invalid_config", "base_url 必须为不带身份、查询和片段的 HTTP(S) 地址")
        if session is not None and not isinstance(session, requests.Session):
            raise HarnessError("invalid_config", "session 必须为 requests.Session")
        if session is not None and cookies is not None:
            raise HarnessError("invalid_config", "session 与 cookies 只能提供其一")
        if cookies is not None and not isinstance(cookies, (Mapping, RequestsCookieJar)):
            raise HarnessError("invalid_config", "cookies 必须为名称到值的映射或 RequestsCookieJar")
        if session is None and cookies is None:
            raise HarnessError("invalid_config", "必须通过 session 或 cookies 注入已认证会话")
        if workspace_id is not None and (not isinstance(workspace_id, str) or len(workspace_id) != 24 or any(c not in "0123456789abcdefABCDEF" for c in workspace_id)):
            raise HarnessError("invalid_config", "workspace_id 必须为 24 位十六进制 ID")
        for name, value in (("timeout", timeout), ("wait_timeout", wait_timeout), ("poll_interval", poll_interval)):
            if not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise HarnessError("invalid_config", f"{name} 必须为正有限数值")
        root = _without_wrapping_whitespace(base_url).rstrip("/")
        self.base_url = root if root.endswith("/api/rqams/v2") else root + "/api/rqams/v2"
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.user_url = self.origin + "/api/user"
        self.timeout, self.wait_timeout, self.poll_interval = timeout, wait_timeout, poll_interval
        self.workspace_id = workspace_id.lower() if workspace_id else None
        self.session = requests.Session()
        self.session.trust_env = False
        if session is not None:
            self.session.cookies.update(_normalized_cookies(session.cookies))
        elif cookies is not None:
            self.session.cookies.update(_normalized_cookies(cookies))
        self.session.mount("http://", DeadlineAdapter())
        self.session.mount("https://", DeadlineAdapter())
        headers = {"Accept": "application/json"}
        if self.workspace_id is not None:
            headers["X-AMS-Workspace"] = self.workspace_id
        self.session.headers.update(headers)
        self._closed = False
        self._resources = {}
        # (workspace_id, 抓取时刻, 目录条目)；切换空间与写入请求都会让它失效。
        self._catalog_cache = None

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

    def call(self, method, path, *, params=None, json=None, data=None, file_path=None, legacy_task=False, no_replay=False, download=None, base=None):
        """执行相对端点并有界等待；异常保留任务 ID，不自动重放不明写入。base 可指向业务前缀之外的接口前缀。"""
        if self._closed:
            raise HarnessError("client_closed", "客户端已关闭")
        if self.workspace_id is None and (base or self.base_url) != self.user_url:
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
            self._catalog_cache = None
        diagnostics = {"url": url, "task_id": task_id, "response": payload}
        with ExitStack() as stack:
            destination = stack.enter_context(self._download_target(download, diagnostics)) if download is not None else None
            files = None
            if file_path is not None:
                file = stack.enter_context(open(file_path, "rb"))
                files = {"file": (Path(file_path).name, file)}
            while True:
                remaining = deadline - monotonic()
                diagnostics.update(task_id=task_id, response=payload)
                if remaining <= 0:
                    raise HarnessError("wait_timeout", _wait_message(payload), details=diagnostics)
                try:
                    with request_deadline(deadline):
                        response = self.session.request(method, url, params=query, json=json, data=data, files=files,
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
        """重建目录并写入缓存。"""
        refs = self._build_catalog()
        self._catalog_cache = (self.workspace_id, monotonic(), refs)
        return refs

    def _catalog_snapshot(self):
        """返回目录条目与它是否直接来自缓存，供解析失败时判断能否只重建重试。"""
        cached = self._cached_catalog()
        if cached is not None:
            return cached, True
        return self.resource_catalog(), False

    def _build_catalog(self):
        """重建目录：集合请求同时发出，逐项详情按受控并发拉取，条目按集合顺序组装。

        详情读取失败按可见性语义处理：403/404 视为读不到而跳过，其他错误原样抛出；
        并发下多个错误同时出现时按资源在集合中的顺序抛出第一个，保证同一环境下报错可复现。
        """
        if self.workspace_id is None:
            self._select_default_workspace()
        refs = []
        product_ids = set()
        with ThreadPoolExecutor(max_workers=_CATALOG_CONCURRENCY) as pool:
            listings = {path: pool.submit(self.call, "GET", path) for path in ("products", "product_groups", "products/asset_units")}
            details = []
            for collection, kind in (("products", "product"), ("product_groups", "product_group")):
                entries = self._catalog_entries(listings[collection].result(), collection)
                futures = [pool.submit(self.call, "GET", f"{collection}/{quote(identifier, safe='')}") for identifier, _ in entries]
                details.append((kind, entries, futures))
            units = listings["products/asset_units"].result()
            for kind, entries, futures in details:
                for (identifier, item), future in zip(entries, futures):
                    detail = self._visible_detail(future)
                    if detail is None:
                        continue
                    refs.append(ResourceRef(kind, identifier, detail.get("name", item.get("name", "")), data=detail))
                    if kind == "product":
                        product_ids.add(identifier)
        for product in units:
            parent = str(product["product_id"])
            if parent not in product_ids:
                continue
            for unit in product.get("asset_units", []):
                refs.append(ResourceRef("asset_unit", str(unit.get("id", unit.get("_id"))), unit.get("symbol", ""), parent, unit))
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
    def _visible_detail(future):
        """取详情响应；403/404 表示读不到，返回 None，其他错误原样抛出。"""
        try:
            return future.result()
        except HarnessError as exc:
            if exc.status in {403, 404}:
                return None
            raise

    @staticmethod
    def _checked(resource):
        """验证单个资源选择器为非空字符串。"""
        if not isinstance(resource, str) or not resource:
            raise HarnessError("invalid_resource", "resource 必须为非空 ID 或名称字符串")
        return resource

    @staticmethod
    def _match(catalog, resource, allowed):
        """在已构建目录中匹配唯一资源；歧义和类型不支持时抛结构化错误。"""
        matches = [ref for ref in catalog if resource in {ref.id, ref.name}]
        if not matches:
            raise HarnessError("resource_not_found", "资源不存在或不可访问", status=404, details={"resource": resource})
        if len(matches) > 1:
            raise HarnessError("ambiguous_resource", "资源存在歧义，请使用候选项 ID", status=400, details={"resource": resource, "candidates": [ref.to_dict() for ref in matches]})
        ref = matches[0]
        if ref.type not in allowed:
            raise HarnessError("unsupported_resource", "此操作不支持目标资源类型", status=400, details={"resource": ref.to_dict(), "allowed": sorted(allowed)})
        return ref

    def resolve(self, resource, allowed):
        """按 ID 或精确名称选择唯一资源；歧义和类型不支持时抛结构化错误。"""
        checked = self._checked(resource)
        catalog, cached = self._catalog_snapshot()
        try:
            return self._match(catalog, checked, allowed)
        except HarnessError as exc:
            if not cached or exc.code != "resource_not_found":
                raise
        # 刚被授权的资源可能还没进缓存目录：强制重建一次再判定，仍找不到才报不存在。
        return self._match(self._rebuild_catalog(), checked, allowed)

    def resolve_many(self, resources, allowed):
        """在单个目录快照上逐项解析多个资源并去重，保持首次出现顺序。"""
        if not isinstance(resources, list) or not resources:
            raise HarnessError("invalid_argument", "resources 必须为非空资源数组")
        checked = [self._checked(resource) for resource in resources]
        catalog, cached = self._catalog_snapshot()
        try:
            return self._match_all(catalog, checked, allowed)
        except HarnessError as exc:
            if not cached or exc.code != "resource_not_found":
                raise
        return self._match_all(self._rebuild_catalog(), checked, allowed)

    @staticmethod
    def _match_all(catalog, checked, allowed):
        """在同一份目录上逐项匹配并去重，保持首次出现顺序。"""
        refs, seen = [], set()
        for resource in checked:
            ref = Client._match(catalog, resource, allowed)
            key = (ref.type, ref.parent_id, ref.id)
            if key not in seen:
                seen.add(key)
                refs.append(ref)
        return refs

    def _select_default_workspace(self):
        """未指定空间时取列举结果中的第一个作为默认分区，并同步请求头。

        空列表或记录缺合法 ID 时给出可核对的错误，不把业务请求发到未知分区。
        """
        payload = self.workspaces.list()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise HarnessError("invalid_response", "用户接口未返回工作空间数组")
        if not rows:
            raise HarnessError("resource_not_found", "当前身份没有可见的工作空间，无法确定默认分区", status=404)
        selected = rows[0].get("id") if isinstance(rows[0], dict) else None
        if not isinstance(selected, str) or len(selected) != 24 or any(c not in "0123456789abcdefABCDEF" for c in selected):
            raise HarnessError("invalid_response", "工作空间记录缺少合法 ID", details={"workspace": rows[0]})
        self.use_workspace(selected)
        return self.workspace_id

    def use_workspace(self, workspace_id):
        """把后续请求切到指定工作空间：同时更新身份属性与请求头，不改变用户身份。

        切换后作废目录缓存，后续解析按新空间的资源重建。
        """
        if not isinstance(workspace_id, str) or len(workspace_id) != 24 or any(c not in "0123456789abcdefABCDEF" for c in workspace_id):
            raise HarnessError("invalid_config", "workspace_id 必须为 24 位十六进制 ID")
        self.workspace_id = workspace_id.lower()
        self.session.headers["X-AMS-Workspace"] = self.workspace_id
        self._catalog_cache = None
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
