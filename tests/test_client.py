"""验证真实 HTTP 异步协议与无歧义资源选择。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import rqamsh.client as client_module
from rqamsh.client import Client
from rqamsh.errors import HarnessError

# 目录端点的集合路径：其余目录路径都是逐项详情。
_CATALOG_COLLECTIONS = ("products", "product_groups", "products/asset_units")

# 没有登记路由时集合端点的空响应；详情路径未登记按 404（读不到即不进目录）处理。
_CATALOG_EMPTY = {"products": {"products": []}, "product_groups": {"product_groups": []}, "products/asset_units": []}


class CatalogRoutes:
    """目录响应表：按请求路径匹配，使断言不依赖并发请求的到达顺序。"""

    def __init__(self, routes):
        """保存路径到 (状态码, 载荷) 的映射。"""
        self.routes = dict(routes)


def catalog_routes(products=(), groups=(), units=(), denied=(), overrides=None):
    """构造目录响应表：列表与逐项详情由同一份数据生成，按路径匹配。

    详情路由只为列表里出现的资源登记，因此「目录详情」与 `products/{x}` 形态的业务端点不会互相截获。
    denied 里的资源详情返回 403，用于验证「读不到详情即不进目录」；
    overrides 里的资源详情返回给定 (状态码, 载荷)，用于验证错误语义与抛出顺序（含 404）、或给某条详情换一份载荷。
    """
    routes = {
        "products": (200, {"products": [dict(row) for row in products]}),
        "product_groups": (200, {"product_groups": [dict(row) for row in groups]}),
        "products/asset_units": (200, list(units)),
    }
    override = dict(overrides or {})
    for collection, rows in (("products", products), ("product_groups", groups)):
        for row in rows:
            identifier = str(row.get("id", row.get("_id", "")))
            if identifier in override:
                routes[f"{collection}/{identifier}"] = override[identifier]
            elif identifier in denied:
                routes[f"{collection}/{identifier}"] = (403, {"message": "无权访问"})
            else:
                routes[f"{collection}/{identifier}"] = (200, row)
    return CatalogRoutes(routes)


def catalog_response(state, method, path):
    """目录端点的响应：三个集合端点按路径取登记值或空集，逐项详情只认已登记的路径。

    `products/{x}` 形态里既有目录详情、也有业务端点（例如 `products/custodian_events:get_latest_custodian_event`），
    只有登记过路由的路径才当目录详情；未登记的路径一律留给业务脚本队列，避免截获业务请求。
    """
    if method != "GET":
        return None
    routes = state["catalog"]
    if routes is not None and path in routes.routes:
        return routes.routes[path]
    if path in _CATALOG_EMPTY:
        return 200, _CATALOG_EMPTY[path]
    return None


def hold_on(predicate, barrier):
    """返回一个在满足条件的目录路径上会合的钩子，用来证明这些请求确实同时在途。"""

    def hold(path):
        """满足条件时等待同批并发请求，让并发窗口固定下来。"""
        if predicate(path):
            barrier.wait()

    return hold


def collection_hits(state):
    """统计本次测试里各目录集合端点被请求的次数（只算读取请求）。"""
    paths = [request[1] for request in state["requests"] if request[0] == "GET"]
    return {name: paths.count(f"/api/rqams/v2/{name}") for name in _CATALOG_COLLECTIONS}


@pytest.fixture
def service():
    """启动隔离 HTTP 服务，记录请求并按测试给定脚本响应。

    目录端点（列举与逐项详情）按 `catalog_routes` 登记的路径匹配，其余请求按脚本顺序返回：
    并发请求的到达顺序不可依赖，顺序脚本只留给串行的业务请求。
    """
    state = {
        "responses": [],
        "catalog": None,
        "requests": [],
        "hold": None,
        "hold_broken": False,
        "in_flight": 0,
        "peak_in_flight": 0,
        "lock": threading.Lock(),
    }

    class Handler(BaseHTTPRequestHandler):
        """处理隔离服务请求。"""

        def _enter(self):
            """登记在途请求数，供并发上限断言使用。"""
            with state["lock"]:
                state["in_flight"] += 1
                state["peak_in_flight"] = max(state["peak_in_flight"], state["in_flight"])

        def _leave(self):
            """退出在途登记。"""
            with state["lock"]:
                state["in_flight"] -= 1

        def _respond(self):
            """记录请求并返回脚本响应；目录端点按路径匹配，其余按脚本顺序。"""
            size = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(size)
            state["requests"].append((self.command, self.path, body, dict(self.headers)))
            prefix = "/api/rqams/v2/"
            relative = self.path.split("?", 1)[0]
            relative = relative[len(prefix):] if relative.startswith(prefix) else None
            routed = catalog_response(state, self.command, relative) if relative is not None else None
            hold = state["hold"]
            if hold is not None and routed is not None:
                try:
                    hold(relative)
                except threading.BrokenBarrierError:
                    state["hold_broken"] = True
            if routed is None:
                with state["lock"]:
                    status, payload = state["responses"].pop(0)
            else:
                status, payload = routed
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream" if isinstance(payload, bytes) else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve(self):
            """登记在途请求、返回脚本响应，再退出登记。"""
            self._enter()
            try:
                self._respond()
            finally:
                self._leave()

        def do_GET(self):
            """读取请求并返回脚本响应。"""
            self._serve()

        def do_POST(self):
            """处理写请求。"""
            self._serve()

        def do_PUT(self):
            """处理整体覆盖写请求。"""
            self._serve()

        def do_PATCH(self):
            """处理局部覆盖写请求。"""
            self._serve()

        def do_DELETE(self):
            """处理删除请求。"""
            self._serve()

        def log_message(self, *args):
            """隔离测试日志，避免写入业务输出。"""
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with Client(f"http://127.0.0.1:{server.server_port}", "012345678901234567890123", cookies={"sid": "test"}, poll_interval=0.001) as client:
        yield client, state
    server.shutdown()
    server.server_close()
    thread.join()


def test_task_poll_never_repeats_write(service):
    """任务提交后只能带 task_id GET，不能重发写入体。"""
    client, state = service
    state["responses"] = [(202, {"task_id": "task-a"}), (202, {"progress": 0.5}), (200, {"answer": 42})]
    assert client.call("POST", "upload", json={"entry": 1}) == {"answer": 42}
    assert [item[0] for item in state["requests"]] == ["POST", "GET", "GET"]
    assert all("task_id=task-a" in item[1] and not item[2] for item in state["requests"][1:])


def test_legacy_failure_retains_diagnostics(service):
    """HTTP 200 的旧协议 FAIL 不得被当作成功。"""
    client, state = service
    state["responses"] = [(200, {"task_id": "old-task"}), (200, {"status": "FAIL", "message": "解析失败"})]
    with pytest.raises(HarnessError) as error:
        client.call("POST", "upload", legacy_task=True)
    assert error.value.code == "task_failed"
    assert error.value.details["task_id"] == "old-task"


def test_read_not_ready_requeries(service):
    """无 task_id 的未就绪查询能够取得最终业务结果。"""
    client, state = service
    state["responses"] = [(202, {"message": "computing"}), (200, {"total_equity": 100})]
    assert client.call("GET", "balance") == {"total_equity": 100}


def test_write_without_task_is_not_replayed(service):
    """写请求无任务句柄时不能盲目重复提交。"""
    client, state = service
    state["responses"] = [(202, {"message": "not ready"})]
    with pytest.raises(HarnessError) as error:
        client.call("POST", "upload", json={"amount": 1})
    assert error.value.code == "pending_without_task"
    assert len(state["requests"]) == 1


def test_name_ambiguity_is_not_silently_resolved(monkeypatch):
    """跨产品与产品组同名必须返回全部候选。"""
    from rqamsh.client import ResourceRef

    with Client("http://localhost:21015", "012345678901234567890123", cookies={"sid": "test"}) as client:
        monkeypatch.setattr(client, "resource_catalog", lambda: [ResourceRef("product", "p1", "同名"), ResourceRef("product_group", "g1", "同名")])
        with pytest.raises(HarnessError) as error:
            client.resolve("同名", {"product", "product_group"})
        assert error.value.code == "ambiguous_resource"
        assert {item["id"] for item in error.value.details["candidates"]} == {"p1", "g1"}
        assert client.resolve("g1", {"product_group"}).path == "product_groups/g1"


def test_side_effecting_get_without_task_is_not_replayed(service):
    """旧删除接口虽用 GET，未就绪无任务句柄也不能重放。"""
    client, state = service
    state["responses"] = [(202, {"message": "not ready"})]
    with pytest.raises(HarnessError) as error:
        client.call("GET", "delete-by-date", no_replay=True)
    assert error.value.code == "pending_without_task"
    assert len(state["requests"]) == 1


def test_catalog_visibility_comes_from_detail_readability(service):
    """目录可见性只看详情能否读到：读得到就进目录，读不到（403 或 404）就跳过，不额外查权限端点。"""
    client, state = service
    product = {"id": "p1", "name": "shared", "user_id": 2}
    forbidden = {"id": "p2", "name": "forbidden", "user_id": 3}
    missing = {"id": "p3", "name": "missing", "user_id": 4}
    state["catalog"] = catalog_routes(
        [product, forbidden, missing], denied=["p2"], overrides={"p3": (404, {"message": "资源不存在"})}
    )
    assert [(ref.type, ref.id) for ref in client.resource_catalog()] == [("product", "p1")]
    assert not any(request[1].endswith("/permissions") for request in state["requests"])


def test_forbidden_response_keeps_permission_denied_code(service):
    """服务端或网关拒绝时保留 permission_denied 错误码，并原样带上其提示文案。"""
    client, state = service
    state["responses"] = [(403, {"message_type": "error", "message": "该接口至少需要读取导入数据权限"})]
    with pytest.raises(HarnessError) as error:
        client.call("GET", "products/p1/balance")
    assert error.value.code == "permission_denied"
    assert error.value.status == 403
    assert "该接口至少需要读取导入数据权限" in str(error.value)


def test_poll_timeout_preserves_task_handle(service):
    """等待超时保留句柄，不声称服务端任务已失败。"""
    client, state = service
    client.wait_timeout = 0.05
    client.poll_interval = 0.1
    state["responses"] = [(202, {"task_id": "slow-task"})]
    with pytest.raises(HarnessError) as error:
        client.call("POST", "upload", json={"entry": 1})
    assert error.value.code == "wait_timeout"
    assert error.value.details["task_id"] == "slow-task"
    assert len(state["requests"]) == 1


def test_partial_failure_inside_success_keeps_import_results():
    """旧任务SUCCESS仅代表执行完成，内部导入错误仍须暴露。"""
    result = {"status": "SUCCESS", "data": [{"id": "kept"}, {"err_msg": "无效流水"}]}
    with pytest.raises(HarnessError) as error:
        Client.partial_failure(result)
    assert error.value.code == "partial_failure"
    assert error.value.details["results"]["data"][0] == {"id": "kept"}


def test_product_creation_warnings_preserve_created_id():
    """初始化估值失败可能已经创建产品，应保留ID而非鼓励重复创建。"""
    result = {"product_id": "created-product", "err_msgs": ["估值初始化失败"]}
    with pytest.raises(HarnessError) as error:
        Client.partial_failure(result)
    assert error.value.details["results"]["product_id"] == "created-product"


def test_shared_resource_write_is_sent_without_local_gating(service):
    """客户端不做权限判断：他人产品的删除请求照发，越级由服务端或网关拒绝。"""
    client, state = service
    product = {"id": "p1", "name": "shared", "user_id": 2}
    state["catalog"] = catalog_routes([product])
    state["responses"] = [(200, {"deleted_count": 1})]
    assert client.products.delete("shared") == {"deleted_count": 1}
    assert state["requests"][-1][:2] == ("DELETE", "/api/rqams/v2/products/p1")


@pytest.mark.parametrize("resource", [None, "", 123])
def test_invalid_resource_is_rejected_before_catalog_request(service, resource):
    """非法资源选择器必须在取目录前被拒，不能先打一轮目录请求。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.products.get(resource)
    assert error.value.code == "invalid_resource"
    assert state["requests"] == []


def test_slow_stream_cannot_bypass_total_deadline():
    """持续滴流不能通过重置read inactivity timeout无限延长等待。"""
    import time

    class SlowHandler(BaseHTTPRequestHandler):
        """逐字节返回有限JSON，模拟持续活跃的慢服务。"""

        def do_GET(self):
            """即使每个字节间隔小于read timeout，也必须被总时限停止。"""
            payload = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            for byte in payload:
                try:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
                time.sleep(0.1)

        def log_message(self, *args):
            """测试服务不写业务日志。"""
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with Client(f"http://127.0.0.1:{server.server_port}", "012345678901234567890123", cookies={"sid": "test"}, wait_timeout=0.2) as client:
            started = time.monotonic()
            with pytest.raises(HarnessError) as error:
                client.call("GET", "slow")
            assert error.value.code == "wait_timeout"
            assert time.monotonic() - started < 0.8
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_download_failure_cleans_only_created_file(service, tmp_path, monkeypatch):
    """磁盘失败时清理本次残缺文件，同时保留已取得任务句柄。"""
    from pathlib import Path

    client, state = service
    state["responses"] = [(200, {"task_id": "export-1"}), (200, b"spreadsheet")]
    target = tmp_path / "export.xlsx"
    original_open = Path.open

    class FullDisk:
        """模拟写盘失败，不替代客户端错误处理。"""

        def __init__(self, stream):
            """保存实际创建的文件。"""
            self.stream = stream

        def fileno(self):
            """提供本次创建文件的真实身份。"""
            return self.stream.fileno()

        def write(self, chunk):
            """写入部分字节后模拟磁盘空间不足。"""
            self.stream.write(chunk[:2])
            raise OSError("disk full")

        def close(self):
            """关闭本次实际文件。"""
            self.stream.close()
            raise OSError("close failed after disk full")

    def limited_open(path, *args, **kwargs):
        """仅将目标下载文件置于模拟磁盘故障中。"""
        stream = original_open(path, *args, **kwargs)
        return FullDisk(stream) if path == target else stream

    monkeypatch.setattr(Path, "open", limited_open)
    with pytest.raises(HarnessError) as error:
        client.call("GET", "export", legacy_task=True, download=target)
    assert error.value.code == "download_failed"
    assert error.value.details["task_id"] == "export-1"
    assert error.value.details["cleanup_errors"] == ["close failed after disk full"]
    assert not target.exists()


def test_existing_download_is_not_consumed_or_overwritten(service, tmp_path):
    """已有目标文件时必须在消费一次性服务端导出前拒绝。"""
    client, state = service
    target = tmp_path / "existing.xlsx"
    target.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        client.call("GET", "export", download=target)
    assert target.read_bytes() == b"keep"
    assert state["requests"] == []


def test_partial_file_writes_preserve_all_download_bytes(service, tmp_path, monkeypatch):
    """底层短写不应被误当成完整下载成功。"""
    from pathlib import Path

    client, state = service
    state["responses"] = [(200, b"complete-download")]
    target = tmp_path / "partial.xlsx"
    original_open = Path.open

    class ShortWriter:
        """一次仅写两字节，模拟合法RawIO短写。"""

        def __init__(self, stream):
            """持有实际文件，不伪造写入结果。"""
            self.stream = stream

        def __getattr__(self, name):
            """其余IO行为委托实际文件。"""
            return getattr(self.stream, name)

        def write(self, content):
            """仅写前两个字节并返回真实写入字节数。"""
            return self.stream.write(content[:2])

    def short_open(path, *args, **kwargs):
        """仅对本次输出文件的创建施加短写。"""
        stream = original_open(path, *args, **kwargs)
        return ShortWriter(stream) if path == target and args and args[0] == "xb" else stream

    monkeypatch.setattr(Path, "open", short_open)
    result = client.call("GET", "export", download=target)
    assert target.read_bytes() == b"complete-download"
    assert result["size"] == len(b"complete-download")


def test_collection_action_path_is_not_an_external_scheme(service):
    """集合动作中的冒号必须留在本服务路径，不得被误判为scheme。"""
    client, state = service
    state["responses"] = [(200, {"exists": True})]
    assert client.products.name_exists("test-product") == {"exists": True}
    assert state["requests"][0][1] == "/api/rqams/v2/products:name_exists?name=test-product"


@pytest.mark.parametrize("path", ["https://example.com/products", "//example.com/products", "../products"])
def test_external_or_parent_paths_never_send_a_request(service, path):
    """允许集合动作不能允许绝对地址或父级路径逃逸。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.call("GET", path)
    assert error.value.code == "invalid_path"
    assert state["requests"] == []


def test_catalog_is_reused_within_one_client(service):
    """同一客户端在缓存窗口内复用同一份目录：多次解析只列举一次，条目与顺序不变。"""
    client, state = service
    group = {"id": "g1", "name": "组", "user_id": 1}
    units = [{"product_id": "p1", "asset_units": [{"id": "u1", "symbol": "600000.SH"}]}]
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}], [group], units)
    assert [ref.id for ref in client.resolve_many(["p1", "g1"], {"product", "product_group"})] == ["p1", "g1"]
    assert client.resolve("产品", {"product"}).id == "p1"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 1)
    assert [ref.type for ref in client.resource_catalog()] == ["product", "product_group", "asset_unit"]


def test_write_request_invalidates_catalog(service):
    """任何写入请求之后目录缓存失效：下一次解析重新列举，避免沿用过期的资源集合。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}])
    state["responses"] = [(200, {"id": "created"})]
    assert client.resolve("p1", {"product"}).id == "p1"
    assert client.call("POST", "products", json={"name": "新产品"}) == {"id": "created"}
    assert client.resolve("p1", {"product"}).id == "p1"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 2)


def test_read_only_batch_post_keeps_catalog(service):
    """只读的批量查询即使走 POST 也不作废目录：批量日报之后不必重新解析一遍目录。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}])
    state["responses"] = [(200, {"p1": {"date": "2026-10-12"}}), (200, {"p1": {"date": "2026-10-13"}})]
    assert client.balances.previous_summaries(["p1"]) == {"p1": {"date": "2026-10-12"}}
    assert client.resolve("p1", {"product"}).id == "p1"
    assert client.balances.previous_summaries(["p1"]) == {"p1": {"date": "2026-10-13"}}
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 1)


def test_attribution_task_path_keeps_catalog(service):
    """归因任务的提交与删除挂在产品路径下，但增删的是任务记录：目录缓存不失效。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}])
    state["responses"] = [(200, {"id": "a1"}), (200, {"deleted": True})]
    assert client.resolve("p1", {"product"}).id == "p1"
    assert client.call("POST", f"products/{'a' * 24}/performance_attributions", json={}) == {"id": "a1"}
    assert client.call("DELETE", f"products/{'a' * 24}/performance_attributions/{'b' * 24}") == {"deleted": True}
    assert client.resolve("p1", {"product"}).id == "p1"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 1)


def test_unlisted_product_write_still_invalidates_catalog(service):
    """产品路径下的其他写入仍使目录失效：白名单不放大到未登记的非资源集合。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}])
    state["responses"] = [(200, {"ok": True})]
    assert client.resolve("p1", {"product"}).id == "p1"
    assert client.call("POST", f"products/{'a' * 24}/trades", json={}) == {"ok": True}
    assert client.resolve("p1", {"product"}).id == "p1"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 2)


def test_workspace_switch_invalidates_catalog(service):
    """切换空间后目录缓存失效：重新列举，并且请求头已经指向新空间。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}])
    assert client.resolve("p1", {"product"}).id == "p1"
    client.use_workspace("f" * 24)
    assert client.resolve("p1", {"product"}).id == "p1"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 2)
    assert state["requests"][-1][3]["X-AMS-Workspace"] == "f" * 24


def test_catalog_expires_after_ttl(service, monkeypatch):
    """缓存超过窗口期后重新列举，不会永久沿用同一份目录。"""
    real_monotonic = client_module.monotonic
    clock = {"offset": 0.0}
    monkeypatch.setattr(client_module, "monotonic", lambda: real_monotonic() + clock["offset"])
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}])
    assert client.resolve("p1", {"product"}).id == "p1"
    clock["offset"] += client_module._CATALOG_TTL_SECONDS - 1
    assert client.resolve("p1", {"product"}).id == "p1"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 1)
    clock["offset"] += 2
    assert client.resolve("p1", {"product"}).id == "p1"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 2)


def test_catalog_miss_rebuilds_once_before_reporting_missing(service):
    """解析不到资源时强制重建一次目录；仍找不到才报不存在，且每次未命中只重建一次。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "旧目录"}])
    with pytest.raises(HarnessError) as error:
        client.resolve("p9", {"product"})
    assert error.value.code == "resource_not_found"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 1)
    state["catalog"] = catalog_routes([{"id": "p1", "name": "旧目录"}, {"id": "p9", "name": "刚授权"}])
    assert client.resolve("p9", {"product"}).id == "p9"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 2)
    with pytest.raises(HarnessError) as error:
        client.resolve("never", {"product"})
    assert error.value.code == "resource_not_found"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 3)


def test_resolve_many_rebuilds_once_on_miss(service):
    """批量解析同样只在「用了缓存且报不存在」时重建一次，成功时去重保序。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "旧目录"}])
    assert [ref.id for ref in client.resolve_many(["p1"], {"product"})] == ["p1"]
    with pytest.raises(HarnessError) as error:
        client.resolve_many(["p1", "p9"], {"product"})
    assert error.value.code == "resource_not_found"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 2)
    state["catalog"] = catalog_routes([{"id": "p1", "name": "旧目录"}, {"id": "p9", "name": "刚授权"}])
    assert [ref.id for ref in client.resolve_many(["p9", "p1", "p9"], {"product"})] == ["p9", "p1"]
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 3)


def test_ambiguous_resource_is_not_rebuilt_away(service):
    """歧义与类型不支持不触发重建：它们不是「资源还没进目录」。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "同名"}], [{"id": "g1", "name": "同名"}])
    assert client.resolve("p1", {"product"}).id == "p1"
    with pytest.raises(HarnessError) as error:
        client.resolve("同名", {"product", "product_group"})
    assert error.value.code == "ambiguous_resource"
    with pytest.raises(HarnessError) as error:
        client.resolve("g1", {"product"})
    assert error.value.code == "unsupported_resource"
    assert collection_hits(state) == dict.fromkeys(_CATALOG_COLLECTIONS, 1)


def test_catalog_collections_are_requested_concurrently(service):
    """目录的三个集合请求同时发出，不串行等待。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "产品"}])
    state["hold"] = hold_on(lambda path: path in set(_CATALOG_COLLECTIONS), threading.Barrier(3, timeout=1))
    assert [ref.id for ref in client.resource_catalog()] == ["p1"]
    assert state["hold_broken"] is False
    assert state["peak_in_flight"] <= client_module._CATALOG_CONCURRENCY


def test_catalog_details_run_with_bounded_concurrency(service, monkeypatch):
    """逐项详情按受控并发拉取：确实并发、不超过上限，条目顺序仍与集合顺序一致。"""
    monkeypatch.setattr(client_module, "_CATALOG_CONCURRENCY", 4)
    client, state = service
    products = [{"id": f"p{index}", "name": f"产品{index}"} for index in range(12)]
    state["catalog"] = catalog_routes(products)
    state["hold"] = hold_on(lambda path: path.startswith("products/p"), threading.Barrier(4, timeout=1))
    refs = client.resource_catalog()
    assert state["hold_broken"] is False
    assert state["peak_in_flight"] <= 4
    assert [ref.id for ref in refs] == [f"p{index}" for index in range(12)]


def test_catalog_detail_errors_follow_collection_order(service):
    """并发拉详情时多个错误按集合顺序抛出第一个，同一环境下的报错可复现。"""
    client, state = service
    products = [{"id": f"p{index}", "name": f"产品{index}"} for index in range(5)]
    state["catalog"] = catalog_routes(products, overrides={"p2": (500, {"message": "p2 故障"}), "p4": (500, {"message": "p4 故障"})})
    with pytest.raises(HarnessError) as error:
        client.resource_catalog()
    assert error.value.code == "http_error"
    assert "p2 故障" in str(error.value)
