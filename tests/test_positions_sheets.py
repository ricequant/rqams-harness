"""产品持仓表块的数组请求体、估值表覆盖冲突与按日期删除。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def test_upsert_always_sends_array(service):
    """单份持仓表也必须发送 JSON 数组。"""
    client, state = service
    sheet = {"date": "2026-08-31", "total_equity": 1000.0, "units": 1000.0, "unit_net_value": 1.0, "positions": []}
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [
        (200, {"inserted_expected_count": 1, "modified_expected_count": 0, "inserted_success_count": 1, "modified_success_count": 0, "error_messages": []}),
    ]
    assert client.positions_sheets.upsert("own", dict(sheet))["inserted_success_count"] == 1
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert json.loads(posts[0][2]) == [sheet]
    assert posts[0][1].endswith("/positions_sheet")


def test_upsert_surfaces_valuation_cover_conflict(service):
    """已有估值表覆盖的日期被跳过时必须抛部分失败并保留计数。"""
    client, state = service
    sheet = {"date": "2026-08-31", "total_equity": 1.0, "units": 1.0, "unit_net_value": 1.0, "positions": []}
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [
        (200, {"inserted_expected_count": 1, "modified_expected_count": 0, "inserted_success_count": 0, "modified_success_count": 0, "error_messages": ["产品own在2026-08-31已存在估值表覆盖"]}),
    ]
    with pytest.raises(HarnessError) as error:
        client.positions_sheets.upsert("own", sheet)
    assert error.value.code == "partial_failure"
    assert error.value.details["results"]["inserted_expected_count"] == 1


def test_upsert_rejects_non_mapping_before_request(service):
    """非对象输入必须在解析资源前失败。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.positions_sheets.upsert("own", ["sheet"])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_upsert_rejects_server_record_keys_before_request(service):
    """读取后原样回传的服务端记录键必须在请求前拒绝，避免写入不可变的 _id。"""
    client, state = service
    base = {"date": "2026-08-31", "total_equity": 1.0, "units": 1.0, "unit_net_value": 1.0, "positions": []}
    with_id = {**base, "_id": "6aab0000000000000000cafe"}
    with_position_id = {**base, "positions": [{"order_book_id": "CNY", "id": "6aab0000000000000000beef"}]}
    for payload in (with_id, with_position_id):
        with pytest.raises(HarnessError) as error:
            client.positions_sheets.upsert("own", payload)
        assert error.value.code == "invalid_argument"
        assert "_id" in str(error.value) or "id" in str(error.value)
    assert state["requests"] == []


def test_get_passes_date_range(service):
    """读取必须透传日期区间且不发送写请求。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, [])]
    assert client.positions_sheets.get("own", start_date="2026-08-01", end_date="2026-08-31") == []
    assert state["requests"][-1][1].endswith("/positions_sheet?start_date=2026-08-01&end_date=2026-08-31")


def test_delete_uses_dates_and_rejects_empty(service):
    """删除参数是日期数组，空数组不触发请求。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, {"effect_count": 1})]
    client.positions_sheets.delete("own", ["2026-08-31"])
    posts = [request for request in state["requests"] if request[0] == "POST"]
    assert json.loads(posts[0][2]) == ["2026-08-31"]
    assert posts[0][1].endswith("/positions_sheet:batch_delete")
    state["requests"].clear()
    with pytest.raises(HarnessError) as error:
        client.positions_sheets.delete("own", [])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []
