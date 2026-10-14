"""工作空间块：列举可见空间、按 ID 或名称切换，以及未登录与形状异常的处理。"""

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


_ROWS = [
    {"id": "012345678901234567890123", "name": "样例空间", "admin": 1, "capacity": 3, "ctime": "2026-01-01", "description": "样例空间", "tags": [], "users": [1, 2]},
    {"id": "abcdefabcdefabcdefabcdef", "name": "测试空间", "admin": 1, "capacity": 1, "ctime": "2026-02-01", "description": "", "tags": [], "users": [1]},
]


def test_list_reads_user_endpoint(service):
    """列举走用户接口前缀，原样返回含 data 的响应，不改写记录。"""
    client, state = service
    state["responses"] = [(200, {"data": [dict(row) for row in _ROWS]})]
    assert client.workspaces.list() == {"data": _ROWS}
    assert state["requests"][-1][:2] == ("GET", "/api/user/v1/workspaces")
    assert state["requests"][-1][3]["X-AMS-Workspace"] == "012345678901234567890123"


def test_list_maps_not_logged_in(service):
    """用户接口用 200 + code 表示未登录，必须映射为错误而不是空列表。"""
    client, state = service
    state["responses"] = [(200, {"code": 1, "message": "未登录"})]
    with pytest.raises(HarnessError) as error:
        client.workspaces.list()
    assert error.value.code == "not_logged_in"
    assert "未登录" in str(error.value)
    assert error.value.details["response"] == {"code": 1, "message": "未登录"}


@pytest.mark.parametrize(
    "workspace,expected",
    [("样例空间", "012345678901234567890123"), ("abcdefabcdefabcdefabcdef", "abcdefabcdefabcdefabcdef")],
)
def test_use_switches_by_name_or_id(service, workspace, expected):
    """按名称或 ID 切换后，身份属性与请求头同步，业务请求落到新空间。"""
    client, state = service
    state["catalog"] = catalog_routes()
    state["responses"] = [(200, {"data": [dict(row) for row in _ROWS]})]
    assert client.workspaces.use(workspace)["id"] == expected
    assert client.workspace_id == expected
    # 业务调用：目录为空；产品列表与目录集合端点同路径，该请求由目录路由返回。
    state["responses"] = [(200, {"products": [], "total": 0, "permissions": []})]
    client.products.list()
    assert state["requests"][-1][:2] == ("GET", "/api/rqams/v2/products")
    assert state["requests"][-1][3]["X-AMS-Workspace"] == expected


def test_use_rejects_unknown_workspace(service):
    """未命中的工作空间不切换，保留原分区并报资源不存在。"""
    client, state = service
    state["responses"] = [(200, {"data": [dict(row) for row in _ROWS]})]
    with pytest.raises(HarnessError) as error:
        client.workspaces.use("不存在的空间")
    assert error.value.code == "resource_not_found"
    assert client.workspace_id == "012345678901234567890123"


def test_use_rejects_ambiguous_name(service):
    """同名工作空间不猜目标，报歧义并给出候选 ID。"""
    client, state = service
    twin = [dict(_ROWS[0]), {**_ROWS[1], "name": "样例空间"}]
    state["responses"] = [(200, {"data": twin})]
    with pytest.raises(HarnessError) as error:
        client.workspaces.use("样例空间")
    assert error.value.code == "ambiguous_resource"
    assert error.value.details["candidates"] == ["012345678901234567890123", "abcdefabcdefabcdefabcdef"]


def test_use_rejects_bad_payload_shape(service):
    """用户接口返回非数组 data 时报形状错误，不静默当成空空间列表。"""
    client, state = service
    state["responses"] = [(200, {"data": {"id": "x"}})]
    with pytest.raises(HarnessError) as error:
        client.workspaces.use("样例空间")
    assert error.value.code == "invalid_response"


def test_use_rejects_empty_selector(service):
    """空选择器在本地拒绝，不发请求。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.workspaces.use("")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_use_workspace_rejects_bad_id(service):
    """客户端层的切换入口只接受 24 位十六进制 ID。"""
    client, _ = service
    with pytest.raises(HarnessError) as error:
        client.use_workspace("not-an-id")
    assert error.value.code == "invalid_config"
