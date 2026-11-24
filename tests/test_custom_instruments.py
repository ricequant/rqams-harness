"""自定义标的公允价：归属核验、全量替换与文件上传、通用公允价写入与空批次边界。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def _instrument(client, *, instrument_id="ci-1", product_id="p1", workspace_id=None):
    """构造自定义标的记录；workspace_id 可覆盖为其他空间，用于验证归属护栏。"""
    return {
        "id": instrument_id, "workspace_id": workspace_id or client.workspace_id, "product_id": product_id,
        "asset_class": "stock", "order_book_id": "CUSTOM1", "symbol": "自制标的",
    }


def _own_product():
    """登记当前用户自有产品的目录路由，仅用于确认资源解析路径。"""
    return catalog_routes(products=[{"id": "p1", "name": "own", "user_id": 1}])


def _own_instrument(client, instrument_id="ci-1"):
    """返回当前空间自有标的和原归属产品的读取响应。"""
    return [(200, {"customized_instruments": [_instrument(client, instrument_id=instrument_id)]}),
            (200, {"id": "p1"})]


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
    state["responses"] = _own_instrument(client) + [(200, {"effect_count": 1})]
    assert client.custom_instruments.replace_fairvalues("ci-1", rows) == {"effect_count": 1}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/customized_instruments/ci-1/fair_value")
    assert json.loads(request[2]) == rows


def test_replace_fairvalues_empty_array_is_sent_as_explicit_clear(service):
    """空数组是显式清空语义，必须照发而不是被本地非空校验拦下。"""
    client, state = service
    state["responses"] = _own_instrument(client) + [(200, {"effect_count": 1})]
    assert client.custom_instruments.replace_fairvalues("ci-1", []) == {"effect_count": 1}
    assert state["requests"][-1][2] == b"[]"


def test_replace_fairvalues_partial_failure_keeps_complete_results(service):
    """服务端逐项 err_msg 非空时抛 partial_failure，并保留完整结果供定位失败项。"""
    client, state = service
    result = {"effect_count": 1, "err_msg": ["第2条价格日期重复：2026-08-30"]}
    state["responses"] = _own_instrument(client) + [(200, result)]
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
    state["responses"] = _own_instrument(client) + [(200, {"effect_count": 1})]
    assert client.custom_instruments.upload_fairvalue("ci-1", str(source)) == {"effect_count": 1}
    request = state["requests"][-1]
    assert (request[0], request[1]) == (
        "POST", "/api/rqams/v2/customized_instruments/ci-1:upload_fair_price_file"
    )
    assert b'name="file"' in request[2] and b'filename="fair_values.xlsx"' in request[2]
    assert b"fair-price-bytes" in request[2]


def test_list_filters_explicitly_denied_parent_before_pagination(service):
    """同空间但归属明确拒绝的标的不进入分页与总数。"""
    client, state = service
    rows = [
        {"id": "ci-1", "workspace_id": client.workspace_id, "product_id": "p1"},
        {"id": "ci-2", "workspace_id": client.workspace_id, "product_id": "shared"},
        {"id": "ci-3", "workspace_id": client.workspace_id},
        {"id": "ci-4", "workspace_id": "another-workspace", "product_id": "p1"},
    ]
    state["catalog"] = catalog_routes(
        products=[{"id": "p1", "name": "own", "user_id": 1}, {"id": "shared", "name": "shared", "user_id": 2}],
        denied=["shared"],
    )
    state["catalog"].routes["products"][1]["permissions"] = [
        {"product_id": "shared", "permission": "forbidden", "is_owner": False},
    ]
    state["responses"] = [(200, {"customized_instruments": rows, "total": 4})]
    assert client.custom_instruments.list(offset=1, limit=2) == {
        "customized_instruments": [rows[2]], "total": 2,
    }
    assert not any(path.endswith("/products/shared") for _, path, *_ in state["requests"])


def test_rebind_checks_original_product_before_mutating(service):
    """目标可写也不能跳过原归属的详情检查；拒绝时不发 PATCH。"""
    client, state = service
    state["catalog"] = catalog_routes(
        products=[{"id": "p1", "name": "original"}, {"id": "p2", "name": "target"}], denied=["p1"],
    )
    state["responses"] = _own_instrument(client)[:1] + [(200, {"effect_count": 1})]
    with pytest.raises(HarnessError) as error:
        client.custom_instruments.update("ci-1", resource="target")
    assert (error.value.code, error.value.status) == ("permission_denied", 403)
    assert all(method == "GET" for method, *_ in state["requests"])


def test_business_permission_denial_is_returned_as_is(service):
    """真实业务 403 原样返回权限拒绝，不重试也不被本地空间匹配改写。"""
    client, state = service
    state["responses"] = _own_instrument(client) + [(403, {"message": "无权修改该标的"})]
    with pytest.raises(HarnessError) as error:
        client.custom_instruments.replace_fairvalues("ci-1", [{"date": "2026-08-31", "value": 1.0}])
    assert (error.value.code, error.value.status, str(error.value)) == ("permission_denied", 403, "无权修改该标的")
    assert [request[0] for request in state["requests"]] == ["GET", "GET", "POST"]


@pytest.mark.parametrize("extra", ["foreign", "missing"])
def test_delete_never_writes_when_an_id_is_outside_current_workspace(service, extra):
    """其他空间同 ID 或缺失 ID 都在写入前整体拒绝，合法子集也不能先删除。"""
    client, state = service
    records = [_instrument(client)]
    if extra == "foreign":
        records.append(_instrument(client, instrument_id="ci-2", workspace_id="another-workspace"))
    state["responses"] = [(200, {"customized_instruments": records})]
    with pytest.raises(HarnessError) as error:
        client.custom_instruments.delete(["ci-1", "ci-2"])
    assert error.value.code == "resource_not_found"
    assert [request[0] for request in state["requests"]] == ["GET"]
