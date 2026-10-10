"""验证会话注入（cookie / session）与本地连接配置校验的契约。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from rqamsh.cli import main
from rqamsh.client import Client
from rqamsh.errors import HarnessError

WORKSPACE = "0123456789abcdef01234567"


@pytest.fixture
def endpoint():
    """启动隔离 HTTP 服务，记录请求头并按测试给定脚本响应。"""
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
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _respond

        def log_message(self, *args):
            """隔离测试日志，避免写入业务输出。"""
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_cookies_are_sent_without_user_header(endpoint):
    """注入 cookie 时请求带会话，且不发送 X-AMS-User。"""
    url, state = endpoint
    payload = {"data": [{"id": WORKSPACE, "name": "样例空间"}]}
    state["responses"] = [(200, payload)]
    with Client(url, workspace_id=WORKSPACE, cookies={"sid": "abc", "theme": "dark"}) as client:
        assert client.workspaces.list() == payload
    _, path, _, headers = state["requests"][-1]
    assert path == "/api/user/v1/workspaces"
    assert headers["Cookie"] == "sid=abc; theme=dark"
    assert headers["X-AMS-Workspace"] == WORKSPACE
    assert "X-AMS-User" not in headers


def test_session_contributes_only_cookies(endpoint):
    """session 只复制 cookie，连接池与自定义请求头不随之接管。"""
    url, state = endpoint
    source = requests.Session()
    source.cookies.set("sid", "xyz")
    source.headers.update({"X-AMS-User": "999", "X-Injected": "1"})
    state["responses"] = [(200, {"data": []})]
    try:
        with Client(url, workspace_id=WORKSPACE, session=source) as client:
            assert client.session is not source
            assert client.session.cookies.get("sid") == "xyz"
            assert "X-Injected" not in client.session.headers
            assert "X-AMS-User" not in client.session.headers
            client.workspaces.list()
    finally:
        source.close()
    assert state["requests"][-1][3]["Cookie"] == "sid=xyz"


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({}, "必须通过 session 或 cookies 注入已认证会话"),
        ({"session": requests.Session(), "cookies": {"sid": "a"}}, "session 与 cookies 只能提供其一"),
        ({"cookies": 3}, "cookies 必须为名称到值的映射"),
        ({"session": object()}, "session 必须为 requests.Session"),
    ],
)
def test_invalid_identity_configuration_is_rejected(kwargs, message):
    """缺失身份、类型错误与互斥参数都在本地拒绝。"""
    with pytest.raises(HarnessError) as error:
        Client("http://127.0.0.1:1", workspace_id=WORKSPACE, **kwargs)
    assert error.value.code == "invalid_config"
    assert message in str(error.value)


def test_cli_sends_repeated_cookies(endpoint, capsys):
    """CLI 的 --cookie 可重复，身份按注入的令牌确定。"""
    url, state = endpoint
    payload = {"data": [{"id": WORKSPACE, "name": "样例空间"}]}
    state["responses"] = [(200, payload)]
    code = main(["--base-url", url, "--workspace-id", WORKSPACE, "--cookie", "sid=abc", "--cookie", "theme=dark", "workspaces", "list"])
    assert code == 0
    assert json.loads(capsys.readouterr().out) == payload
    headers = state["requests"][-1][3]
    assert headers["Cookie"] == "sid=abc; theme=dark"
    assert "X-AMS-User" not in headers


def test_cli_reads_cookie_from_environment(endpoint, capsys, monkeypatch):
    """RQAMSH_COOKIE 可代替 --cookie，多值以分号分隔。"""
    monkeypatch.setenv("RQAMSH_COOKIE", "sid=env; theme=light")
    url, state = endpoint
    state["responses"] = [(200, {"data": []})]
    assert main(["--base-url", url, "--workspace-id", WORKSPACE, "workspaces", "list"]) == 0
    capsys.readouterr()
    assert state["requests"][-1][3]["Cookie"] == "sid=env; theme=light"


def test_cli_rejects_malformed_cookie(endpoint, capsys):
    """缺等号的 cookie 以 invalid_config 失败，且不发请求。"""
    url, state = endpoint
    assert main(["--base-url", url, "--workspace-id", WORKSPACE, "--cookie", "broken", "workspaces", "list"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_config"
    assert state["requests"] == []


def test_cli_requires_base_url_and_identity(endpoint, capsys, monkeypatch):
    """缺 base_url 或缺身份都在本地拒绝，且不发请求；缺 workspace_id 不算错。"""
    monkeypatch.delenv("RQAMSH_BASE_URL", raising=False)
    monkeypatch.delenv("RQAMSH_COOKIE", raising=False)
    url, state = endpoint
    assert main(["--cookie", "sid=abc", "workspaces", "list"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_config"
    assert main(["--base-url", url, "workspaces", "list"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_config"
    assert state["requests"] == []


def test_workspace_defaults_to_first_listed(endpoint):
    """省略 workspace_id 时不预设分区：首次业务调用先列举并选中第一个，之后沿用该分区。"""
    url, state = endpoint
    listing = {"data": [{"id": WORKSPACE, "name": "样例空间"}]}
    state["responses"] = [
        (200, listing),
        (200, {"products": []}), (200, {"product_groups": []}), (200, []),
        (200, {"products": [], "total": 0, "permissions": []}),
    ]
    with Client(url, cookies={"sid": "abc"}) as client:
        assert client.workspace_id is None
        client.products.list()
        assert state["requests"][0][:2] == ("GET", "/api/user/v1/workspaces")
        assert "X-AMS-Workspace" not in state["requests"][0][3]
        assert client.workspace_id == WORKSPACE
        assert state["requests"][-1][3]["X-AMS-Workspace"] == WORKSPACE
        requests_before = len(state["requests"])
        state["responses"] = [
            (200, {"products": []}), (200, {"product_groups": []}), (200, []),
            (200, {"products": [], "total": 0, "permissions": []}),
        ]
        client.products.list()
        assert client.workspace_id == WORKSPACE
        assert state["requests"][requests_before][:2] == ("GET", "/api/rqams/v2/products")


def test_default_workspace_requires_visible_space(endpoint):
    """列举为空时不给默认分区，业务调用报错，也不把请求发到未知分区。"""
    url, state = endpoint
    state["responses"] = [(200, {"data": []})]
    with Client(url, cookies={"sid": "abc"}) as client:
        with pytest.raises(HarnessError) as error:
            client.products.list()
    assert error.value.code == "resource_not_found"
    assert [item[1] for item in state["requests"]] == ["/api/user/v1/workspaces"]


def test_cli_defaults_to_first_workspace(endpoint, capsys, monkeypatch):
    """CLI 不带 --workspace-id：列举与业务调用都成功，业务调用前自动选中第一个空间。"""
    monkeypatch.delenv("RQAMSH_WORKSPACE_ID", raising=False)
    url, state = endpoint
    listing = {"data": [{"id": WORKSPACE, "name": "样例空间"}]}
    state["responses"] = [(200, listing)]
    assert main(["--base-url", url, "--cookie", "sid=abc", "workspaces", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == listing
    assert "X-AMS-Workspace" not in state["requests"][-1][3]
    state["responses"] = [
        (200, listing),
        (200, {"products": []}), (200, {"product_groups": []}), (200, []),
        (200, {"products": [], "total": 0, "permissions": []}),
    ]
    assert main(["--base-url", url, "--cookie", "sid=abc", "products", "list"]) == 0
    capsys.readouterr()
    assert state["requests"][-1][3]["X-AMS-Workspace"] == WORKSPACE


def test_catalog_is_not_filtered_locally(endpoint):
    """目录不做本地归属过滤：他人的资源也能解析，可见性交给服务端与网关。"""
    url, state = endpoint
    state["responses"] = [
        (200, {"products": [{"id": "p1", "name": "他人产品", "user_id": 999}]}),
        (200, {"id": "p1", "name": "他人产品", "user_id": 999}),
        (200, {"product_groups": []}),
        (200, []),
    ]
    with Client(url, workspace_id=WORKSPACE, cookies={"sid": "abc"}) as client:
        assert client.resolve("他人产品", {"product"}).id == "p1"
    assert all("/permissions" not in item[1] for item in state["requests"])
