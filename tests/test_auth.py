"""验证用户级 PAT 注入、成员空间选择与部署绑定。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_client import catalog_response, catalog_routes
from rqamsh.cli import main
from rqamsh.client import Client, DEFAULT_BASE_URL
from rqamsh.errors import HarnessError
from rqamsh.settings import load_settings, save_settings

WORKSPACE = "0123456789abcdef01234567"


@pytest.fixture
def endpoint():
    """启动隔离 HTTP 服务，记录请求头并按测试给定脚本响应。

    目录端点（列举与逐项详情）按 `catalog_routes` 登记的路径匹配，其余请求按脚本顺序返回：
    并发请求的到达顺序不可依赖，顺序脚本只留给串行的业务请求。
    """
    state = {"responses": [], "catalog": None, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        """处理隔离服务请求。"""

        def _respond(self):
            """记录请求并返回脚本响应；目录端点按路径匹配，其余按脚本顺序。"""
            size = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(size)
            state["requests"].append((self.command, self.path, body, dict(self.headers)))
            prefix = "/api/rqams/v2/"
            relative = self.path.split("?", 1)[0]
            relative = relative[len(prefix):] if relative.startswith(prefix) else None
            routed = catalog_response(state, self.command, relative) if relative is not None else None
            if routed is None:
                status, payload = state["responses"].pop(0)
            else:
                status, payload = routed
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


def test_token_is_sent_as_bearer_without_cookie(endpoint):
    """令牌以 Authorization: Bearer 发送；不再注入 Cookie 或用户头。"""
    url, state = endpoint
    state["catalog"] = catalog_routes()
    with Client(url, workspace_id=WORKSPACE, token="abc") as client:
        client.products.list()
    headers = state["requests"][-1][3]
    assert headers["Authorization"] == "Bearer abc"
    assert headers["X-AMS-Workspace"] == WORKSPACE
    assert "Cookie" not in headers
    assert "X-AMS-User" not in headers


@pytest.mark.parametrize(
    "token,message",
    [
        (None, "未找到 token"),
        ("", "必须提供非空 token"),
        (" \r\n", "必须提供非空 token"),
        (3, "必须提供非空 token"),
        ("abc\r\ndef", "不能包含换行"),
    ],
)
def test_invalid_token_is_rejected_locally(token, message, tmp_path):
    """缺失、类型错误与内部换行都在建连前拒绝，不发出请求。"""
    with pytest.raises(HarnessError) as error:
        Client("http://127.0.0.1:1", workspace_id=WORKSPACE, token=token, settings_path=tmp_path / "missing.json")
    assert error.value.code == "invalid_config"
    assert message in str(error.value)


def test_line_endings_in_address_and_token_are_ignored(endpoint):
    """从文件读到的地址与令牌带 Windows 行尾回车时仍能建连，请求头里不带回车。"""
    url, state = endpoint
    state["catalog"] = catalog_routes()
    with Client(url + "\r\n", workspace_id=WORKSPACE, token="abc\r\n") as client:
        assert client.base_url == f"{url}/api/rqams/v2"
        client.products.list()
    headers = state["requests"][-1][3]
    assert headers["Authorization"] == "Bearer abc"


@pytest.mark.parametrize("saved_address", [
    None, "https://other.example.com", "https://127.0.0.1", "http://127.0.0.1:1", "{url}/private",
])
def test_saved_token_cannot_be_reused_for_another_deployment(endpoint, tmp_path, saved_address):
    """保存身份缺少部署绑定或地址不匹配时，在发出请求前拒绝复用。"""
    url, state = endpoint
    target = tmp_path / "settings.json"
    if saved_address is not None:
        saved_address = saved_address.format(url=url)
    save_settings("private-token", WORKSPACE, base_url=saved_address, path=target)
    with pytest.raises(HarnessError) as error:
        with Client(url, settings_path=target) as client:
            client.workspaces.list()
    assert error.value.code == "invalid_config"
    assert "private-token" not in str(error.value)
    assert state["requests"] == []
    assert load_settings(target)["workspace_id"] == WORKSPACE


def test_saved_token_accepts_equivalent_api_address(endpoint, tmp_path):
    """尾斜线和 API 后缀不同不应把同一部署误判为另一个部署。"""
    url, state = endpoint
    target = tmp_path / "settings.json"
    save_settings("saved-token", WORKSPACE, base_url=url + "/", path=target)
    state["responses"] = [(200, {"data": [{"id": WORKSPACE}]})]
    with Client(url + "/api/rqams/v2/", settings_path=target) as client:
        assert client.workspaces.list() == {"data": [{"id": WORKSPACE}]}
    assert state["requests"][0][3]["Authorization"] == "Bearer saved-token"


@pytest.mark.parametrize("explicit_address", [False, True])
def test_cli_address_selection_overrides_saved_deployment(endpoint, capsys, monkeypatch, tmp_path, explicit_address):
    """环境变量覆盖保存地址，显式地址覆盖环境变量，显式令牌不沿用旧空间。"""
    url, state = endpoint
    target = tmp_path / "settings.json"
    save_settings("old-token", "f" * 24, base_url="http://127.0.0.1:1", path=target)
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    monkeypatch.setenv("RQAMSH_BASE_URL", "http://127.0.0.1:1" if explicit_address else url)
    monkeypatch.setenv("RQAMSH_TOKEN", "current-token")
    monkeypatch.delenv("RQAMSH_WORKSPACE_ID", raising=False)
    state["responses"] = [(200, {"data": [{"id": WORKSPACE}]})]
    args = ["--base-url", url] if explicit_address else []
    assert main([*args, "workspaces", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["data"][0]["id"] == WORKSPACE
    assert state["requests"][0][3]["Authorization"] == "Bearer current-token"
    assert "X-AMS-Workspace" not in state["requests"][0][3]
    assert load_settings(target)["workspace_id"] == "f" * 24


def test_cli_sends_token(endpoint, capsys):
    """CLI 的 --token 注入 Bearer 令牌。"""
    url, state = endpoint
    state["catalog"] = catalog_routes()
    code = main(["--base-url", url, "--workspace-id", WORKSPACE, "--token", "abc", "products", "list"])
    assert code == 0
    capsys.readouterr()
    headers = state["requests"][-1][3]
    assert headers["Authorization"] == "Bearer abc"
    assert "Cookie" not in headers


def test_cli_reads_token_from_environment(endpoint, capsys, monkeypatch):
    """RQAMSH_TOKEN 可代替 --token。"""
    monkeypatch.setenv("RQAMSH_TOKEN", "env-token")
    url, state = endpoint
    state["catalog"] = catalog_routes()
    assert main(["--base-url", url, "--workspace-id", WORKSPACE, "products", "list"]) == 0
    capsys.readouterr()
    assert state["requests"][-1][3]["Authorization"] == "Bearer env-token"


def test_cli_reads_token_from_file(endpoint, capsys, tmp_path):
    """--token @文件 读取令牌并去掉行尾，不把令牌写进输出。"""
    token_file = tmp_path / "agentkey"
    token_file.write_text("file-token\r\n", encoding="utf-8-sig")
    url, state = endpoint
    state["catalog"] = catalog_routes()
    code = main(["--base-url", url, "--workspace-id", WORKSPACE, "--token", f"@{token_file}", "products", "list"])
    assert code == 0
    assert "file-token" not in capsys.readouterr().out
    assert state["requests"][-1][3]["Authorization"] == "Bearer file-token"


def test_cli_rejects_missing_token_file(endpoint, capsys):
    """token 文件不存在时以 invalid_config 失败，且不发请求。"""
    url, state = endpoint
    assert main(["--base-url", url, "--workspace-id", WORKSPACE, "--token", "@missing-agentkey", "products", "list"]) == 1
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_config"
    assert state["requests"] == []


def test_cli_requires_token(endpoint, capsys, monkeypatch, tmp_path):
    """关闭自动登录时，缺 token 在本地拒绝且不发请求。"""
    monkeypatch.delenv("RQAMSH_BASE_URL", raising=False)
    monkeypatch.delenv("RQAMSH_TOKEN", raising=False)
    monkeypatch.setenv("RQAMSH_AUTO_LOGIN", "0")
    monkeypatch.setenv("RQAMSH_SETTINGS", str(tmp_path / "missing.json"))
    url, state = endpoint
    assert main(["--base-url", url, "workspaces", "list"]) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "invalid_config"
    assert "rqamsh auth" in error["message"]
    assert state["requests"] == []


def test_cli_uses_saved_settings(endpoint, capsys, monkeypatch, tmp_path):
    """CLI 省略令牌和空间时从 rqamsh_settings.json 自动登录。"""
    from rqamsh.settings import save_settings

    url, state = endpoint
    target = tmp_path / "rqamsh_settings.json"
    save_settings("saved-token", WORKSPACE, base_url=url, path=target)
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    state["catalog"] = catalog_routes()
    state["responses"] = [(200, {"products": [], "total": 0, "permissions": []})]
    assert main(["products", "list"]) == 0
    assert state["requests"][-1][3]["Authorization"] == "Bearer saved-token"
    assert state["requests"][-1][3]["X-AMS-Workspace"] == WORKSPACE
    capsys.readouterr()


def test_auth_command_emits_settings_without_token(monkeypatch, capsys, tmp_path):
    """rqamsh auth 只输出设置路径和空间，不回显令牌。"""
    target = tmp_path / "rqamsh_settings.json"
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    seen = {}

    def fake_login(base_url, **kwargs):
        """模拟浏览器登录成功，记录调用参数。"""
        seen["base_url"] = base_url
        seen["kwargs"] = kwargs
        return {"settings": str(target), "base_url": base_url, "workspace_id": WORKSPACE, "opened": True}

    monkeypatch.setattr("rqamsh.cli.login", fake_login)
    assert main(["auth"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "ok", "settings": str(target), "base_url": DEFAULT_BASE_URL, "workspace_id": WORKSPACE}
    assert seen["base_url"] == DEFAULT_BASE_URL
    assert seen["kwargs"]["settings_path"] == target


def test_business_command_auto_logs_in(endpoint, capsys, monkeypatch, tmp_path):
    """首次业务命令缺设置时自动登录，登录完成后继续原请求。"""
    from rqamsh.settings import save_settings

    url, state = endpoint
    target = tmp_path / "rqamsh_settings.json"
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    seen = {}

    def fake_login(base_url, workspace_id=None, settings_path=None, **kwargs):
        """模拟浏览器登录成功并写入设置。"""
        seen["base_url"] = base_url
        save_settings("auto-token", WORKSPACE, base_url=base_url, path=settings_path)
        return {"settings": str(settings_path), "base_url": base_url, "workspace_id": WORKSPACE, "opened": False}

    monkeypatch.setattr("rqamsh.cli.login", fake_login)
    state["responses"] = [(200, {"data": [{"id": WORKSPACE}]})]
    assert main(["--base-url", url, "workspaces", "list"]) == 0
    assert seen["base_url"] == url
    assert json.loads(capsys.readouterr().out)["data"][0]["id"] == WORKSPACE
    assert state["requests"][0][3]["Authorization"] == "Bearer auto-token"


def test_cli_workspace_use_updates_settings(endpoint, capsys, monkeypatch, tmp_path):
    """CLI 切换空间后把最后空间写回设置文件。"""
    from rqamsh.settings import save_settings

    url, state = endpoint
    target = tmp_path / "rqamsh_settings.json"
    save_settings("saved-token", WORKSPACE, base_url=url, path=target)
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    state["responses"] = [(200, {"data": [{"id": WORKSPACE}]})]
    assert main(["workspaces", "use", "--workspace", WORKSPACE]) == 0
    assert load_settings(target)["workspace_id"] == WORKSPACE
    capsys.readouterr()


def test_auth_can_overwrite_broken_settings(monkeypatch, capsys, tmp_path):
    """设置文件损坏时登录仍可启动并覆盖它。"""
    target = tmp_path / "rqamsh_settings.json"
    target.write_text("{broken", encoding="utf-8")
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    monkeypatch.setattr("rqamsh.cli.login", lambda base_url, **kwargs: {"settings": str(target), "base_url": base_url, "workspace_id": WORKSPACE, "opened": False})
    assert main(["auth"]) == 0
    assert json.loads(capsys.readouterr().out)["workspace_id"] == WORKSPACE


def test_bare_cli_starts_login(monkeypatch, capsys, tmp_path):
    """直接运行 rqamsh 无子命令时进入本机登录。"""
    target = tmp_path / "rqamsh_settings.json"
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    monkeypatch.setattr("rqamsh.cli.login", lambda base_url, **kwargs: {"settings": str(target), "base_url": base_url, "workspace_id": WORKSPACE, "opened": False})
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["workspace_id"] == WORKSPACE


@pytest.mark.parametrize("members", [
    [{"id": WORKSPACE}],
    [{"id": "f" * 24, "name": "Z团队"}, {"id": WORKSPACE, "name": "A团队"}],
])
def test_workspace_defaults_to_first_membership(endpoint, members):
    """未指定空间时按服务端原序选首项，后续业务请求复用该目标。"""
    url, state = endpoint
    state["catalog"] = catalog_routes()
    state["responses"] = [
        (200, {"data": members}),
        (200, {"products": [], "total": 0, "permissions": []}),
    ]
    with Client(url, token="abc") as client:
        assert client.workspace_id is None
        client.products.list()
        assert state["requests"][0][:2] == ("GET", "/api/user/v1/workspaces")
        assert "X-AMS-Workspace" not in state["requests"][0][3]
        assert client.workspace_id == members[0]["id"]
        assert state["requests"][-1][3]["X-AMS-Workspace"] == members[0]["id"]
        requests_before = len(state["requests"])
        client.products.list()
        assert state["requests"][requests_before][:2] == ("GET", "/api/rqams/v2/products")


def test_no_membership_does_not_dispatch_business(endpoint):
    """没有成员空间时不发送业务读取，也不伪造目标空间。"""
    url, state = endpoint
    state["responses"] = [(200, {"data": []})]
    with Client(url, token="abc") as client:
        with pytest.raises(HarnessError) as error:
            client.products.list()
        assert client.workspace_id is None
    assert error.value.code == "resource_not_found"
    assert [item[1] for item in state["requests"]] == ["/api/user/v1/workspaces"]


def test_first_membership_permission_error_does_not_switch_workspace(endpoint):
    """默认首项被拒绝时保留原错误与分区，不改选另一个成员空间。"""
    url, state = endpoint
    state["responses"] = [
        (200, {"data": [{"id": "f" * 24}, {"id": WORKSPACE}]}),
    ]
    state["catalog"] = catalog_routes()
    state["catalog"].routes["products"] = (403, {"message": "首个空间没有 AMS 权益"})
    with Client(url, token="abc") as client:
        with pytest.raises(HarnessError) as error:
            client.call("GET", "products")
        assert error.value.status == 403
        assert client.workspace_id == "f" * 24
        assert state["requests"][-1][3]["X-AMS-Workspace"] == "f" * 24
    assert [item[1] for item in state["requests"]] == [
        "/api/user/v1/workspaces", "/api/rqams/v2/products",
    ]


def test_discovery_preserves_private_deployment_prefix(endpoint):
    """用户 API 与 AMS 共用 origin 和部署路径，不把 PAT 发往根路径的其他应用。"""
    url, state = endpoint
    state["responses"] = [(200, {"data": [{"id": WORKSPACE}]})]
    with Client(url + "/private/api/rqams/v2", workspace_id=WORKSPACE, token="abc") as client:
        assert client.workspaces.list() == {"data": [{"id": WORKSPACE}]}
    assert state["requests"][-1][:2] == ("GET", "/private/api/user/v1/workspaces")
    assert "X-AMS-Workspace" not in state["requests"][-1][3]


def test_catalog_is_not_filtered_locally(endpoint):
    """目录不做本地归属过滤：他人的资源也能解析，可见性交给服务端与网关。"""
    url, state = endpoint
    state["catalog"] = catalog_routes([{"id": "p1", "name": "他人产品", "user_id": 999}])
    with Client(url, workspace_id=WORKSPACE, token="abc") as client:
        assert client.resolve("他人产品", {"product"}).id == "p1"
    assert all("/permissions" not in item[1] for item in state["requests"])
