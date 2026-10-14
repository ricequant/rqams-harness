"""份额事件块的客户端折算、部分失败与自动事件保留。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def _catalog(product_rows):
    """登记产品目录路由：逐项详情由列表项派生。"""
    return catalog_routes(products=product_rows)


def test_create_converts_units_into_batch_fields(service):
    """申购与赎回必须折算为服务端批量字段，且不发送 units 与 unit_event_type。"""
    client, state = service
    # 两次解析共用一个客户端与一份目录路由；两次写入各取一条业务响应。
    state["catalog"] = _catalog([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, {"effect_count": 1}), (200, {"effect_count": 1})]
    client.unit_events.create("own", {"unit_event_type": "subscription", "date": "2026-08-31", "units": 5.0, "product_share": "A"})
    client.unit_events.create("own", {"unit_event_type": "redemption", "date": "2026-08-31", "units": 2.0})
    bodies = [json.loads(request[2]) for request in state["requests"] if request[0] == "POST"]
    assert bodies[0] == [{"date": "2026-08-31", "product_share": "A", "subscription_units": 5.0, "redemption_units": None}]
    assert bodies[1] == [{"date": "2026-08-31", "subscription_units": None, "redemption_units": 2.0}]
    assert all(request[1].endswith("/unit_events:batch_insert") for request in state["requests"] if request[0] == "POST")


def test_create_rejects_missing_or_unknown_type_before_request(service):
    """缺字段或非法类型在取目录前失败。"""
    client, state = service
    for data in ({"date": "2026-08-31", "units": 1.0}, {"unit_event_type": "transfer", "date": "2026-08-31", "units": 1.0}):
        with pytest.raises(HarnessError) as error:
            client.unit_events.create("own", data)
        assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_create_raises_partial_failure_with_server_diagnostics(service):
    """服务端逐项 err_msg 必须抛部分失败并保留完整结果。"""
    client, state = service
    state["catalog"] = _catalog([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [
        (200, {"effect_count": 1, "err_msg": ["第2个事件解析失败: 份额事件必须指定申购/赎回份额"]}),
    ]
    with pytest.raises(HarnessError) as error:
        client.unit_events.create("own", [{"unit_event_type": "subscription", "date": "2026-08-31", "units": 1.0}])
    assert error.value.code == "partial_failure"
    assert error.value.details["results"]["effect_count"] == 1


def test_update_requires_both_unit_fields(service):
    """更新必须同时给出申购与赎回字段，否则零请求失败。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.unit_events.update("own", "e1", {"subscription_units": 1.0})
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_delete_uses_event_ids_and_rejects_empty(service):
    """删除走批量路由且拒绝空数组。"""
    client, state = service
    state["catalog"] = _catalog([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, {"effect_count": 1})]
    assert client.unit_events.delete("own", ["e1"]) == {"effect_count": 1}
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert posts[0][1].endswith("/unit_events:batch_delete") and json.loads(posts[0][2]) == ["e1"]
    state["requests"].clear()
    with pytest.raises(HarnessError) as error:
        client.unit_events.delete("own", [])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_list_keeps_auto_events(service):
    """自动事件不得被客户端静默过滤。"""
    client, state = service
    payload = {
        "daily_units": [
            {"id": "a1", "date": "2026-08-31", "source": "auto"},
            {"id": "m1", "date": "2026-08-31", "source": "manual"},
        ],
        "unit_changes": [],
    }
    state["catalog"] = _catalog([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, payload)]
    assert client.unit_events.list("own") == payload
