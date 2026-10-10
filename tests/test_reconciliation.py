"""对账块的批量解析、参数校验与写入边界。"""

import json

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def _catalog(product_rows, units=()):
    """按目录构建顺序生成产品列表、逐个详情、组与单元响应。"""
    responses = [(200, {"products": list(product_rows)})]
    responses.extend((200, row) for row in product_rows)
    responses.extend([(200, {"product_groups": []}), (200, list(units))])
    return responses


def _asset_unit_catalog(units):
    """单个自有产品挂给定资产单元，覆盖单元路径解析所需的完整目录快照。"""
    return _catalog([{"id": "p1", "name": "产品一", "user_id": 1}],
                    [{"product_id": "p1", "asset_units": list(units)}])


def test_batch_list_uses_one_catalog_snapshot(service):
    """多产品只构建一次目录，重复输入去重并保持首现顺序。"""
    client, state = service
    rows = [{"id": "p1", "name": "一号", "user_id": 1}, {"id": "p2", "name": "二号", "user_id": 1}]
    state["responses"] = _catalog(rows) + [(200, [{"product_id": "p1"}, {"product_id": "p2"}])]
    result = client.reconciliation.list(["一号", "p2", "p1"], start_date="2026-08-01", end_date="2026-08-31")
    assert result == [{"product_id": "p1"}, {"product_id": "p2"}]
    gets = [request[1] for request in state["requests"] if request[0] == "GET"]
    assert gets == [
        "/api/rqams/v2/products", "/api/rqams/v2/products/p1", "/api/rqams/v2/products/p2",
        "/api/rqams/v2/product_groups", "/api/rqams/v2/products/asset_units",
    ]
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert posts[0][1] == "/api/rqams/v2/products:batch_get_reconciliation_list"
    assert json.loads(posts[0][2]) == {"start_date": "2026-08-01", "end_date": "2026-08-31", "product_ids": ["p1", "p2"]}


def test_batch_list_rejects_bad_input_before_request(service):
    """空数组、非法日期与未知资源不得触发请求或半批写入。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.reconciliation.list([], start_date="2026-08-01", end_date="2026-08-31")
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.reconciliation.list(["一号"], start_date="20260801", end_date="2026-08-31")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []
    state["responses"] = _catalog([{"id": "p1", "name": "一号", "user_id": 1}])
    with pytest.raises(HarnessError) as error:
        client.reconciliation.list(["一号", "未接入产品"], start_date="2026-08-01", end_date="2026-08-31")
    assert error.value.code == "resource_not_found"
    assert all(request[0] == "GET" for request in state["requests"])


def test_batch_list_rejects_ambiguous_name(service):
    """名称歧义必须报候选，不得去重后静默选中其一。"""
    client, state = service
    rows = [{"id": "p1", "name": "重名", "user_id": 1}, {"id": "p2", "name": "重名", "user_id": 1}]
    state["responses"] = _catalog(rows)
    with pytest.raises(HarnessError) as error:
        client.reconciliation.list(["重名"], start_date="2026-08-01", end_date="2026-08-31")
    assert error.value.code == "ambiguous_resource"
    assert error.value.details["candidates"] == [
        {"type": "product", "id": "p1", "name": "重名", "parent_id": None},
        {"type": "product", "id": "p2", "name": "重名", "parent_id": None},
    ]
    assert all(request[0] == "GET" for request in state["requests"])


def test_diff_validates_and_dedupes_fields(service):
    """差异分组必须合法且去重保序，非法输入不触发资源解析。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.reconciliation.diff("一号", date="2026-08-31", fields=["total_equity"])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []
    state["responses"] = _catalog([{"id": "p1", "name": "一号", "user_id": 1}]) + [(200, {"positions": []})]
    assert client.reconciliation.diff("一号", date="2026-08-31", fields=["positions", "net_asset", "positions"]) == {"positions": []}
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert posts[0][1] == "/api/rqams/v2/products/p1:get_reconciliation_diff"
    assert json.loads(posts[0][2]) == {"date": "2026-08-31", "fields": ["positions", "net_asset"]}


def test_mark_requires_field_and_omits_unset_keys(service):
    """标记接口至少一个字段，且未提供的键不得写入请求体。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.reconciliation.mark("一号", date="2026-08-31")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []
    state["responses"] = _catalog([{"id": "p1", "name": "一号", "user_id": 1}]) + [(200, {"effect_count": 1})]
    assert client.reconciliation.mark("一号", date="2026-08-31", description="托管差异已确认") == {"effect_count": 1}
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert posts[0][1] == "/api/rqams/v2/products/p1:reconciliation"
    assert json.loads(posts[0][2]) == {"date": "2026-08-31", "description": "托管差异已确认"}


def test_auto_write_without_task_is_not_replayed(service):
    """自动对账写入遇 202 无任务句柄时必须报错且不重发。"""
    client, state = service
    state["responses"] = _catalog([{"id": "p1", "name": "一号", "user_id": 1}]) + [(202, {"message": "computing"})]
    with pytest.raises(HarnessError) as error:
        client.reconciliation.auto("一号", date="2026-08-31")
    assert error.value.code == "pending_without_task"
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert [request[1] for request in posts] == ["/api/rqams/v2/products/p1:auto_reconciliation"]


def test_asset_unit_diff_posts_date_to_unit_path(service):
    """资产单元差异走嵌套单元路径，体只带日期，差异行按原结构透传。"""
    client, state = service
    rows = [{"asset_class": "stock", "direction": "long", "order_book_id": "002673.XSHE",
             "symbol": "西部证券", "quantity": {"ams": 1000, "valuation_report": 900}}]
    state["responses"] = _asset_unit_catalog([{"id": "u1", "symbol": "单元一"}]) + [(200, rows)]
    assert client.reconciliation.asset_unit_diff("单元一", date="2026-08-31") == rows
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert posts[-1][1] == "/api/rqams/v2/products/p1/asset_units/u1:get_reconciliation_diff"
    assert json.loads(posts[-1][2]) == {"date": "2026-08-31"}


def test_positions_statement_gets_unit_path_with_date_query(service):
    """持仓单核对是带 date query 的 GET，布尔一致性结果必须原样返回。"""
    client, state = service
    state["responses"] = _asset_unit_catalog([{"id": "u1", "symbol": "单元一"}]) + [(200, {"is_consistence": False})]
    assert client.reconciliation.positions_statement("单元一", date="2026-08-31") == {"is_consistence": False}
    request = state["requests"][-1]
    assert request[0] == "GET"
    assert request[1] == (
        "/api/rqams/v2/products/p1/asset_units/u1:reconciliation_positions_statement?date=2026-08-31"
    )


def test_undo_auto_posts_date_to_product_action(service):
    """撤销自动对账是产品路径的 POST，effect_count 为 0 也要如实返回而非当成失败。"""
    client, state = service
    state["responses"] = _catalog([{"id": "p1", "name": "一号", "user_id": 1}]) + [(200, {"effect_count": 0})]
    assert client.reconciliation.undo_auto("一号", date="2026-08-31") == {"effect_count": 0}
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert posts[-1][1] == "/api/rqams/v2/products/p1:undo_auto_reconciliation"
    assert json.loads(posts[-1][2]) == {"date": "2026-08-31"}


@pytest.mark.parametrize(
    "method, resource",
    [("asset_unit_diff", "单元一"), ("positions_statement", "单元一"), ("undo_auto", "一号")],
)
def test_reconciliation_ops_reject_bad_date_before_request(service, method, resource):
    """非严格 YYYY-MM-DD 日期必须在取目录前本地拒绝，不得发出任何请求。"""
    client, state = service
    for bad_date in ("20260831", "2026-13-01", True):
        with pytest.raises(HarnessError) as error:
            getattr(client.reconciliation, method)(resource, date=bad_date)
        assert error.value.code == "invalid_argument"
    assert state["requests"] == []