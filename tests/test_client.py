"""验证真实 HTTP 异步协议与无歧义资源选择。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from rqamsh.client import Client
from rqamsh.errors import HarnessError


@pytest.fixture
def service():
    """启动隔离 HTTP 服务，记录请求并按测试给定脚本响应。"""
    state = {"responses": [], "requests": []}

    class Handler(BaseHTTPRequestHandler):
        """处理隔离服务请求。"""

        def _respond(self):
            """记录请求并返回脚本响应。"""
            size = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(size)
            state["requests"].append((self.command, self.path, body, dict(self.headers)))
            status, payload = state["responses"].pop(0)
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream" if isinstance(payload, bytes) else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            """读取请求并返回脚本响应。"""
            self._respond()

        def do_POST(self):
            """处理写请求。"""
            self._respond()

        def do_PUT(self):
            """处理整体覆盖写请求。"""
            self._respond()

        def do_PATCH(self):
            """处理局部覆盖写请求。"""
            self._respond()

        def do_DELETE(self):
            """处理删除请求。"""
            self._respond()

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
    """目录可见性只看详情能否读到：读得到就进目录，读不到（403/404）就跳过，不额外查权限端点。"""
    client, state = service
    product = {"id": "p1", "name": "shared", "user_id": 2}
    state["responses"] = [
        (200, {"products": [product, {"id": "p2", "name": "hidden", "user_id": 3}]}),
        (200, product),
        (403, {"message": "无权访问"}),
        (200, {"product_groups": []}),
        (200, []),
    ]
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
    state["responses"] = [
        (200, {"products": [product]}),
        (200, product), (200, {"product_groups": []}), (200, []),
        (200, {"deleted_count": 1}),
    ]
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
