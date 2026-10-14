"""权限块：授权明细读取、授权与调整级别、撤销与批量授权的参数与失败协议。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


_OWN_PRODUCT = {"id": "p1", "name": "own", "user_id": 1}
_OWN_GROUP = {"id": "g1", "name": "group", "user_id": 1}
_GRANT_ROW = {
    "resource_id": "p1", "resource_type": "product", "permission": "write", "user_id": 1,
    "workspace_id": "012345678901234567890123", "shared_by": 1, "id": "perm-1",
}


def _body(state, method="POST"):
    """返回最近一次指定方法的请求 JSON 体。"""
    raw = [item for item in state["requests"] if item[0] == method][-1][2]
    return json.loads(raw)


def test_list_permissions_reads_grant_rows(service):
    """授权明细按资源路径读取，返回服务端原始授权行数组。"""
    client, state = service
    state["catalog"] = catalog_routes([_OWN_PRODUCT])
    state["responses"] = [(200, [dict(_GRANT_ROW)])]
    assert client.permissions.list("own") == [_GRANT_ROW]
    assert state["requests"][-1][:2] == ("GET", "/api/rqams/v2/products/p1/permissions")


@pytest.mark.parametrize(
    "entries",
    [
        [{"user_id": 2}],
        [{"user_id": 2, "permission": "owner"}],
        [{"user_id": 0, "permission": "write"}],
        [{"user_id": True, "permission": "write"}],
        [{"user_id": 2, "permission": "write", "is_owner": True}],
        [{"user_id": 2, "permission": "write", "permission_id": ""}],
        [],
    ],
)
def test_grant_rejects_malformed_entries_before_any_request(service, entries):
    """授权项缺字段、级别不在枚举内或带多余键时本地拒绝，不先打一轮目录请求。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.permissions.grant("own", entries)
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_grant_posts_entries_and_raises_on_item_errors(service):
    """授权按数组提交；服务端逐项返回原因时抛部分失败并保留完整结果。"""
    client, state = service
    state["catalog"] = catalog_routes([_OWN_PRODUCT])
    state["responses"] = [
        (200, {"effect_count": 1, "error_messages": [
            {"resource_id": "p1", "user_id": 9, "err_msg": "您所操作的用户没有使用该工作空间的权限"},
        ]}),
    ]
    with pytest.raises(HarnessError) as error:
        client.permissions.grant("own", [{"user_id": 2, "permission": "read_net_value"}, {"user_id": 9, "permission": "write"}])
    assert error.value.code == "partial_failure"
    assert error.value.details["results"]["effect_count"] == 1
    assert state["requests"][-1][:2] == ("POST", "/api/rqams/v2/products/p1/permissions")
    assert _body(state) == [{"user_id": 2, "permission": "read_net_value"}, {"user_id": 9, "permission": "write"}]


def test_grant_returns_effect_count_when_all_entries_succeed(service):
    """全部成功时不抛错，原样返回 effect_count。"""
    client, state = service
    state["catalog"] = catalog_routes([_OWN_PRODUCT])
    state["responses"] = [(200, {"effect_count": 2, "error_messages": []})]
    assert client.permissions.grant("own", [{"user_id": 2, "permission": "write"}]) == {
        "effect_count": 2, "error_messages": [],
    }


def test_grant_many_rejects_mixed_resource_types(service):
    """批量授权按资源类型分路由，混批在本地拒绝而不是拆成两次请求。"""
    client, state = service
    state["catalog"] = catalog_routes([_OWN_PRODUCT], [_OWN_GROUP])
    with pytest.raises(HarnessError) as error:
        client.permissions.grant_many(["own", "group"], [{"user_id": 2, "permission": "write"}])
    assert error.value.code == "invalid_argument"
    assert all(request[0] == "GET" for request in state["requests"])


def test_grant_many_posts_same_type_batch_without_permission_id(service):
    """同类型批量授权提交资源 ID 数组与授权项；批量形态不接受 permission_id。"""
    client, state = service
    state["catalog"] = catalog_routes([_OWN_PRODUCT], [_OWN_GROUP])
    state["responses"] = [(200, {"effect_count": 1, "error_messages": []})]
    assert client.permissions.grant_many(["own"], [{"user_id": 2, "permission": "read_position"}]) == {
        "effect_count": 1, "error_messages": [],
    }
    assert state["requests"][-1][:2] == ("POST", "/api/rqams/v2/products/permissions")
    assert _body(state) == {"resource_ids": ["p1"], "perm_info_list": [{"user_id": 2, "permission": "read_position"}]}

    with pytest.raises(HarnessError) as error:
        client.permissions.grant_many(
            ["own"], [{"user_id": 2, "permission": "write", "permission_id": "perm-1"}],
        )
    assert error.value.code == "invalid_argument"


def test_revoke_sends_bare_permission_id_array(service):
    """撤销按裸数组提交授权行 ID；空数组或空字符串在本地拒绝。"""
    client, state = service
    state["catalog"] = catalog_routes([_OWN_PRODUCT], [_OWN_GROUP])
    state["responses"] = [(200, {"effect_count": 1})]
    assert client.permissions.revoke("group", ["perm-1"]) == {"effect_count": 1}
    assert state["requests"][-1][:2] == ("DELETE", "/api/rqams/v2/product_groups/g1/permissions")
    assert _body(state, "DELETE") == ["perm-1"]

    for ids in ([], [""]):
        with pytest.raises(HarnessError) as error:
            client.permissions.revoke("group", ids)
        assert error.value.code == "invalid_argument"
