"""验证成员空间发现、明确选择与跨空间状态边界。"""

import pytest

from test_client import catalog_routes, service
from rqamsh.client import Client
from rqamsh.errors import HarnessError
from rqamsh.settings import load_settings, save_settings


A = "012345678901234567890123"
B = "abcdefabcdefabcdefabcdef"
ROWS = [
    {"id": A, "name": "团队 A", "admin": 1, "users": [1, 2]},
    {"id": B, "name": "团队 B", "admin": 2, "users": [2]},
]


def test_discovery_does_not_change_selected_workspace(service):
    """成员发现不带当前空间头，列举不会切换现有业务分区。"""
    client, state = service
    state["responses"] = [(200, {"data": ROWS})]
    selected = client.workspace_id
    assert client.workspaces.list() == {"data": ROWS}
    assert state["requests"][-1][:2] == ("GET", "/api/user/v1/workspaces")
    assert "X-AMS-Workspace" not in state["requests"][-1][3]
    assert client.workspace_id == selected
    assert client.session.headers["X-AMS-Workspace"] == selected


@pytest.mark.parametrize("payload", [
    {}, {"data": None}, {"data": {}}, {"data": [None]},
    {"data": [{"id": "not-an-id"}]}, {"data": [{"name": "无 ID"}]},
    {"data": [ROWS[0], ROWS[0]]},
])
def test_malformed_membership_cannot_change_routing(service, payload):
    """不完整、重复或非法成员记录不成为可选路由。"""
    client, state = service
    selected = client.workspace_id
    state["responses"] = [(200, payload)]
    with pytest.raises(HarnessError) as error:
        client.workspaces.list()
    assert error.value.code == "invalid_response"
    assert client.workspace_id == selected


@pytest.mark.parametrize("status", [401, 403, 503])
def test_discovery_preserves_upstream_errors(service, status):
    """身份、权限与依赖故障保持原始状态，不回退旧上下文或改选空间。"""
    client, state = service
    state["responses"] = [(status, {"error_code": "UPSTREAM_REJECTED"})]
    selected = client.workspace_id
    with pytest.raises(HarnessError) as error:
        client.workspaces.list()
    assert error.value.status == status
    assert error.value.details["response"]["error_code"] == "UPSTREAM_REJECTED"
    assert client.workspace_id == selected
    assert len(state["requests"]) == 1


def test_member_switch_invalidates_space_specific_details(service):
    """同一 PAT 切换 A/B/A 后同名产品按新空间解析，不复用另一空间详情。"""
    client, state = service
    state["responses"] = [(200, {"data": ROWS})]
    client.workspaces.use(workspace=A)
    state["catalog"] = catalog_routes([{"id": "product-a", "name": "同名产品"}])
    assert client.resolve("同名产品", {"product"}).id == "product-a"
    state["responses"] = [(200, {"data": ROWS})]
    client.workspaces.use(workspace=B)
    state["catalog"] = catalog_routes([{"id": "product-b", "name": "同名产品"}])
    assert client.resolve("同名产品", {"product"}).id == "product-b"
    assert client.session.headers["X-AMS-Workspace"] == B
    state["responses"] = [(200, {"data": ROWS})]
    client.workspaces.use(workspace=A)
    state["catalog"] = catalog_routes([{"id": "product-a", "name": "同名产品"}])
    assert client.resolve("同名产品", {"product"}).id == "product-a"
    assert client.session.headers["X-AMS-Workspace"] == A


def test_nonmember_selection_keeps_routing_and_caches(service):
    """非成员选择失败后已有空间和已核验详情仍可继续使用。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "原产品"}])
    assert client.resolve("原产品", {"product"}).id == "p1"
    selected = client.workspace_id
    state["responses"] = [(200, {"data": [ROWS[0]]})]
    with pytest.raises(HarnessError) as error:
        client.workspaces.use(workspace=B)
    assert error.value.code == "resource_not_found"
    assert client.workspace_id == selected
    assert client.session.headers["X-AMS-Workspace"] == selected
    count = len(state["requests"])
    assert client.resolve("原产品", {"product"}).id == "p1"
    assert len(state["requests"]) == count


def test_use_requires_id_not_ambiguous_name(service):
    """空间名称不作为选择键，避免同名团队被误选。"""
    client, state = service
    state["responses"] = [(200, {"data": ROWS})]
    with pytest.raises(HarnessError) as error:
        client.workspaces.use(workspace="团队 A")
    assert error.value.code == "resource_not_found"


def test_use_rejects_empty_selector_without_request(service):
    """空选择器本地拒绝，不发成员或业务请求。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.workspaces.use(workspace="")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_use_workspace_rejects_bad_id(service):
    """低层路由入口拒绝形状非法的空间 ID。"""
    client, _ = service
    with pytest.raises(HarnessError) as error:
        client.use_workspace("not-an-id")
    assert error.value.code == "invalid_config"


def test_injected_pat_selection_cannot_rewrite_saved_identity(service, tmp_path):
    """临时 PAT 可以切成员空间，但不能改写另一个保存身份的最后空间。"""
    original, state = service
    base = original.base_url.removesuffix("/api/rqams/v2")
    settings = tmp_path / "saved.json"
    save_settings("saved-token", A, base_url=base, path=settings)
    state["responses"] = [(200, {"data": ROWS})]
    with Client(base_url=base, token="injected-token", settings_path=settings) as client:
        assert client.workspace_id is None
        client.workspaces.use(workspace=B)
        assert client.workspace_id == B
    assert load_settings(settings)["workspace_id"] == A
    assert load_settings(settings)["token"] == "saved-token"


def test_saved_identity_remembers_successful_member_choice(service, tmp_path):
    """保存身份在明确选中成员后记忆空间，拒绝的选择不改设置。"""
    original, state = service
    base = original.base_url.removesuffix("/api/rqams/v2")
    settings = tmp_path / "saved.json"
    save_settings("saved-token", A, base_url=base, path=settings)
    with Client(base_url=base, settings_path=settings) as client:
        state["responses"] = [(200, {"data": ROWS})]
        client.workspaces.use(workspace=B)
        assert load_settings(settings)["workspace_id"] == B
        state["responses"] = [(200, {"data": [ROWS[1]]})]
        with pytest.raises(HarnessError):
            client.workspaces.use(workspace=A)
        assert client.workspace_id == B
        assert load_settings(settings)["workspace_id"] == B


def test_settings_failure_keeps_active_workspace(service, tmp_path, monkeypatch):
    """持久化选择失败时，客户端不能暗中切到用户认为未选中的空间。"""
    original, state = service
    base = original.base_url.removesuffix("/api/rqams/v2")
    settings = tmp_path / "saved.json"
    save_settings("saved-token", A, base_url=base, path=settings)

    def reject_save(*args, **kwargs):
        """模拟设置文件无写权限。"""
        raise PermissionError("设置文件只读")

    with Client(base_url=base, settings_path=settings) as client:
        state["responses"] = [(200, {"data": ROWS})]
        monkeypatch.setattr("rqamsh.client.remember_workspace", reject_save)
        with pytest.raises(PermissionError):
            client.workspaces.use(workspace=B)
        assert client.workspace_id == A
        assert client.session.headers["X-AMS-Workspace"] == A
        assert load_settings(settings)["workspace_id"] == A


@pytest.mark.parametrize("saved_identity", [False, True])
def test_first_member_default_preserves_identity_settings(service, tmp_path, saved_identity):
    """首项自动选择只记忆保存身份的空间，不改写临时令牌背后的原设置。"""
    original, state = service
    base = original.base_url.removesuffix("/api/rqams/v2")
    settings = tmp_path / "saved.json"
    save_settings("saved-token", None if saved_identity else A, base_url=base, path=settings)
    state["responses"] = [(200, {"data": [ROWS[1], ROWS[0]]})]
    state["catalog"] = catalog_routes()
    token = None if saved_identity else "injected-token"
    with Client(base_url=base, token=token, settings_path=settings) as client:
        client.products.list()
        assert client.workspace_id == B
        assert state["requests"][-1][3]["X-AMS-Workspace"] == B
    saved = load_settings(settings)
    assert saved["token"] == "saved-token"
    assert saved["workspace_id"] == (B if saved_identity else A)
    if saved_identity:
        before = len(state["requests"])
        with Client(base_url=base, settings_path=settings) as client:
            client.products.list()
            assert client.workspace_id == B
        assert all("/api/user/" not in request[1] for request in state["requests"][before:])
