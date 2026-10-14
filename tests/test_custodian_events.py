"""托管事件块的批量入口、权限边界与工作空间级可见性。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def test_create_sends_identical_batch_body_for_dict_and_list(service):
    """单条与数组必须走同一批量路由且请求体一致。"""
    client, state = service
    item = {"custodian_event_type": "product_dividend_paid", "date": "2026-08-31", "amount": 1000.0}
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, {"effect_count": 1}), (200, {"effect_count": 1})]
    assert client.custodian_events.create("own", dict(item)) == {"effect_count": 1}
    assert client.custodian_events.create("own", [dict(item)]) == {"effect_count": 1}
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert [json.loads(request[2]) for request in posts] == [[item], [item]]
    assert all(request[1].endswith("/custodian_events:batch_insert") for request in posts)


def test_update_path_and_delete_batch(service):
    """更新按事件 ID，删除按 ID 数组，路径不得写成单条删除。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, {"effect_count": 1}), (200, {"effect_count": 2})]
    client.custodian_events.update("own", "e1", {"custodian_event_type": "redemption_paid", "date": "2026-08-31"})
    client.custodian_events.delete("own", ["e1", "e2"])
    puts = [request for request in state["requests"] if request[0] == "PUT"]
    assert puts[0][1].endswith("/custodian_events/e1")
    assert json.loads(puts[0][2]) == {"custodian_event_type": "redemption_paid", "date": "2026-08-31"}
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert posts[0][1].endswith("/custodian_events:batch_delete")
    assert json.loads(posts[0][2]) == ["e1", "e2"]


def test_invalid_inputs_never_send_request(service):
    """非对象输入与空批次必须在解析资源前失败。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.custodian_events.create("own", ["x"])
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.custodian_events.delete("own", [])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_product_group_target_is_rejected_before_write(service):
    """四块都不支持产品组，类型不符必须在发出写请求前失败。"""
    client, state = service
    group = {"id": "g1", "name": "组合", "user_id": 1}
    state["catalog"] = catalog_routes(groups=[group])
    with pytest.raises(HarnessError) as error:
        client.custodian_events.create("组合", {"custodian_event_type": "product_dividend_paid", "date": "2026-08-31"})
    assert error.value.code == "unsupported_resource"
    assert not any(request[0] == "POST" for request in state["requests"])


def test_create_pending_without_task_is_not_replayed(service):
    """写入返回 202 且无 task_id 时必须报错且不重发写入体。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(202, {"progress": 0.1})]
    with pytest.raises(HarnessError) as error:
        client.custodian_events.create("own", {"custodian_event_type": "product_dividend_paid", "date": "2026-08-31"})
    assert error.value.code == "pending_without_task"
    assert [request[0] for request in state["requests"]].count("POST") == 1


def test_upload_file_joins_product_ids_and_keeps_confirmations(service, tmp_path):
    """导入请求按逗号拼接 product_ids，返回的凭证 ID 原样保留。"""
    client, state = service
    products = [{"id": "p1", "name": "own", "user_id": 1}, {"id": "p2", "name": "own2", "user_id": 1}]
    state["catalog"] = catalog_routes(products)
    state["responses"] = [(200, {"effect_count": 3, "err_msg": [], "confirmation_ids": ["c1"]})]
    source = tmp_path / "events.xlsx"
    source.write_bytes(b"xlsx")
    result = client.custodian_events.upload_file(["own", "own2"], str(source))
    assert result["confirmation_ids"] == ["c1"]
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert b'name="product_ids"' in posts[0][2] and b"p1,p2" in posts[0][2]


def test_upload_file_surfaces_parse_errors(service, tmp_path):
    """文件导入的逐行错误必须抛部分失败并保留完整结果。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [
        (200, {"effect_count": 1, "err_msg": ["第2行日期格式错误"], "confirmation_ids": ["c1"]}),
    ]
    source = tmp_path / "events.xlsx"
    source.write_bytes(b"xlsx")
    with pytest.raises(HarnessError) as error:
        client.custodian_events.upload_file(["own"], str(source))
    assert error.value.code == "partial_failure"
    assert error.value.details["results"]["confirmation_ids"] == ["c1"]


def test_latest_filters_products_outside_catalog(service):
    """工作空间级最新日期只能返回当前身份可见的产品。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    # 该接口路径形如 products/{名字}，但属于业务读取：未登记的详情路径按业务请求走按序队列。
    state["responses"] = [(200, {"p1": "2026-08-31", "p2": "2026-08-30"})]
    assert client.custodian_events.latest() == {"p1": "2026-08-31"}
