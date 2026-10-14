"""自定义标的公允价：归属核验、全量替换与文件上传、通用公允价写入与空批次边界。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def _own_product():
    """登记当前用户自有产品的目录路由：逐项详情由列表项派生。"""
    return catalog_routes(products=[{"id": "p1", "name": "own", "user_id": 1}])


def _own_instrument(client, state, instrument_id="ci-1"):
    """登记自有自定义标的的归属产品目录，并返回标的列表响应（写入前先核验归属）。"""
    instrument = {
        "id": instrument_id, "workspace_id": client.workspace_id, "product_id": "p1",
        "asset_class": "stock", "order_book_id": "CUSTOM1", "symbol": "自制标的",
    }
    state["catalog"] = _own_product()
    return [(200, {"customized_instruments": [instrument]})]


def test_insert_fairvalues_posts_array_and_returns_created_ids(service):
    """公允价按数组提交，返回本轮新增记录 ID。"""
    client, state = service
    rows = [{"order_book_id": "CUSTOM1", "asset_class": "stock", "date": "2026-08-31", "symbol": "自制标的", "value": 12.5}]
    state["catalog"] = _own_product()
    state["responses"] = [(200, ["fv-1"])]
    assert client.custom_instruments.insert_fairvalues("own", rows) == ["fv-1"]
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/products/p1/fair_values:batch_insert")
    assert json.loads(request[2]) == rows


def test_insert_fairvalues_rejects_empty_batch(service):
    """空数组在任何请求前失败。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.custom_instruments.insert_fairvalues("own", [])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_replace_fairvalues_posts_full_history_and_returns_effect_count(service):
    """全量替换按完整价格数组提交，原样返回 effect_count。"""
    client, state = service
    rows = [{"date": "2026-08-29", "value": 12.5}, {"date": "2026-08-31", "value": 13.0}]
    state["responses"] = _own_instrument(client, state) + [(200, {"effect_count": 1})]
    assert client.custom_instruments.replace_fairvalues("ci-1", rows) == {"effect_count": 1}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/customized_instruments/ci-1/fair_value")
    assert json.loads(request[2]) == rows


def test_replace_fairvalues_empty_array_is_sent_as_explicit_clear(service):
    """空数组是显式清空语义，必须照发而不是被本地非空校验拦下。"""
    client, state = service
    state["responses"] = _own_instrument(client, state) + [(200, {"effect_count": 1})]
    assert client.custom_instruments.replace_fairvalues("ci-1", []) == {"effect_count": 1}
    assert state["requests"][-1][2] == b"[]"


def test_replace_fairvalues_partial_failure_keeps_complete_results(service):
    """服务端逐项 err_msg 非空时抛 partial_failure，并保留完整结果供定位失败项。"""
    client, state = service
    result = {"effect_count": 1, "err_msg": ["第2条价格日期重复：2026-08-30"]}
    state["responses"] = _own_instrument(client, state) + [(200, result)]
    with pytest.raises(HarnessError) as error:
        client.custom_instruments.replace_fairvalues("ci-1", [{"date": "2026-08-30", "value": 1.0}])
    assert error.value.code == "partial_failure"
    assert error.value.details["results"] == result
    assert state["requests"][-1][1] == "/api/rqams/v2/customized_instruments/ci-1/fair_value"


def test_replace_fairvalues_rejects_unknown_instrument_before_write(service):
    """标的不在当前空间时在写入前拒绝，不发出任何替换请求。"""
    client, state = service
    state["responses"] = [(200, {"customized_instruments": []})]
    with pytest.raises(HarnessError) as error:
        client.custom_instruments.replace_fairvalues("ci-9", [{"date": "2026-08-31", "value": 1.0}])
    assert error.value.code == "resource_not_found"
    assert len(state["requests"]) == 1


def test_upload_fairvalue_posts_original_file(service, tmp_path):
    """公允价文件按原文件上传（不解析内容、不换汇），返回 effect_count。"""
    client, state = service
    source = tmp_path / "fair_values.xlsx"
    source.write_bytes(b"fair-price-bytes")
    state["responses"] = _own_instrument(client, state) + [(200, {"effect_count": 1})]
    assert client.custom_instruments.upload_fairvalue("ci-1", str(source)) == {"effect_count": 1}
    request = state["requests"][-1]
    assert (request[0], request[1]) == (
        "POST", "/api/rqams/v2/customized_instruments/ci-1:upload_fair_price_file"
    )
    assert b'name="file"' in request[2] and b'filename="fair_values.xlsx"' in request[2]
    assert b"fair-price-bytes" in request[2]
