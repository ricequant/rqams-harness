"""流水删除的两种模式与上传的三条输入通道。"""

import json

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def _own_product():
    """登记当前用户自有产品的目录路由：逐项详情由列表项派生。"""
    return catalog_routes(products=[{"id": "p1", "name": "own", "user_id": 1}])


def test_delete_by_date_uses_async_get(service):
    """按日期删除走带写副作用的 GET，并等待任务终态。"""
    client, state = service
    state["catalog"] = _own_product()
    state["responses"] = [(200, {"status": "SUCCESS", "deleted": 3})]
    result = client.trades.delete("own", start_date="2026-01-01", end_date="2026-01-31", sources=["open_api"])
    assert result == {"status": "SUCCESS", "deleted": 3}
    request = state["requests"][-1]
    assert request[0] == "GET"
    assert request[1].startswith("/api/rqams/v2/products/p1/trades:batch_delete_by_date?")
    assert "start_date=2026-01-01" in request[1] and "end_date=2026-01-31" in request[1] and "sources=open_api" in request[1]


def test_delete_by_ids_uses_batch_delete(service):
    """显式给 trade_ids 时按记录 ID 同步批量删除，不携带日期参数。"""
    client, state = service
    state["catalog"] = _own_product()
    state["responses"] = [(200, {"effect_count": 2})]
    result = client.trades.delete("own", trade_ids=["id-1", "id-2"])
    assert result == {"effect_count": 2}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/products/p1/trades:batch_delete")
    assert request[2] == b'["id-1", "id-2"]'


def test_delete_rejects_mixed_or_empty_ids_before_request(service):
    """两种模式混用或空 ID 数组必须在任何请求前拒绝。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.trades.delete("own", trade_ids=["id-1"], start_date="2026-01-01")
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.trades.delete("own", trade_ids=[], is_query_assistant=True)
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.trades.delete("own", trade_ids=[])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_upload_adds_open_api_source(service):
    """结构化上传补 open_api 来源并命中 batch_insert。"""
    client, state = service
    state["catalog"] = _own_product()
    state["responses"] = [(200, {"results": []})]
    client.trades.upload("own", [{"foreign_id": "one", "quantity": 1}])
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/products/p1/trades:batch_insert")
    assert request[2] == b'[{"source": "open_api", "foreign_id": "one", "quantity": 1}]'


def test_upload_intraday_file_switches_route_by_suffix_flag(service, tmp_path):
    """日内文件上传携带 account 表单，并按后缀补全开关切换 v1/v2 路由。"""
    client, state = service
    source = tmp_path / "intraday.xlsx"
    source.write_bytes(b"xlsx-bytes")
    state["catalog"] = _own_product()
    state["responses"] = [(200, {"results": []})]
    client.trades.upload_intraday_file("own", str(source), "测试账户")
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/products/p1:upload_intraday_trade_file")
    assert b'name="account"' in request[2] and "测试账户".encode() in request[2]
    state["responses"] = [(200, {"results": []})]
    client.trades.upload_intraday_file("own", str(source), "测试账户", prefer_fill_fund_exchange_suffix=False)
    assert state["requests"][-1][1] == "/api/rqams/v2/products/p1/trades:upload_intraday_file_v2"


def test_upload_intraday_file_requires_account_before_request(service, tmp_path):
    """缺账户名时不得读取文件或发出请求。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.trades.upload_intraday_file("own", str(tmp_path / "missing.xlsx"), "")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_auto_balance_override_posts_body_and_returns_effect_count(service):
    """自动权益编辑按请求体原样提交，并透传 effect_count。"""
    client, state = service
    body = {
        "asset_class": "stock", "transaction_type": "dividend_payment", "trading_date": "2026-08-31",
        "order_book_id": "600000.XSHG", "update": {"settlement_amount": 1000.0, "remarks": "手工补录"},
    }
    state["catalog"] = _own_product()
    state["responses"] = [(200, {"effect_count": 1})]
    assert client.trades.create_auto_balance_override("own", body) == {"effect_count": 1}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/products/p1/trades:auto-balance-override")
    assert json.loads(request[2]) == body


def test_auto_balance_override_delete_uses_record_id(service):
    """删除按记录 ID 走子路径；非法 ID 在请求前失败。"""
    client, state = service
    state["catalog"] = _own_product()
    state["responses"] = [(200, {"effect_count": 0})]
    assert client.trades.delete_auto_balance_override("own", "ov-1") == {"effect_count": 0}
    assert (state["requests"][-1][0], state["requests"][-1][1]) == (
        "DELETE", "/api/rqams/v2/products/p1/trades:auto-balance-override/ov-1"
    )
    state["requests"].clear()
    with pytest.raises(HarnessError) as error:
        client.trades.delete_auto_balance_override("own", "../escape")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_upload_settlement_file_switches_route_by_suffix_flag(service, tmp_path):
    """结算文件上传带 account 与可选资产单元表单，按后缀补全开关切换 v1/v2 路由并等待旧任务终态。"""
    client, state = service
    source = tmp_path / "settlement.xlsx"
    source.write_bytes(b"settlement-bytes")
    done = {"status": "SUCCESS", "progress": 1,
            "data": {"effect_count": 2, "err_msg": [], "confirmation_id": "conf-1"}}
    state["catalog"] = _own_product()
    # v1 轮询是 products/{名字} 形态的业务 GET，走业务队列；v2 路径同样如此。
    state["responses"] = [(200, {"task_id": "settle-1"}), (200, done)]
    assert client.trades.upload_settlement_file("own", str(source), "测试账户", asset_unit_id="au-1") == done
    submit, poll = state["requests"][-2], state["requests"][-1]
    assert (submit[0], submit[1]) == ("POST", "/api/rqams/v2/products/p1:upload_settlement_trade_file")
    assert b'name="account"' in submit[2] and "测试账户".encode() in submit[2]
    assert b'name="asset_unit_id"' in submit[2] and b"au-1" in submit[2]
    assert b"settlement-bytes" in submit[2]
    assert poll[0] == "GET" and "task_id=settle-1" in poll[1] and poll[2] == b""
    # 同一客户端复用同一份目录路由；写入作废缓存后由它重建，队列只留业务响应。
    state["responses"] = [(200, {"task_id": "settle-2"}), (200, done)]
    client.trades.upload_settlement_file("own", str(source), "测试账户", prefer_fill_fund_exchange_suffix=False)
    assert state["requests"][-2][1] == "/api/rqams/v2/products/p1/trades:upload_settlement_file_v2"


def test_upload_settlement_file_requires_account_before_request(service, tmp_path):
    """缺账户名时不得读取文件或发出请求。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.trades.upload_settlement_file("own", str(tmp_path / "missing.xlsx"), "")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_upload_settlement_file_reports_item_errors_after_task_success(service, tmp_path):
    """任务 SUCCESS 只代表执行完成，data.err_msg 非空仍抛 partial_failure 并保留结果。"""
    client, state = service
    source = tmp_path / "settlement.xlsx"
    source.write_bytes(b"settlement-bytes")
    done = {"status": "SUCCESS", "progress": 1,
            "data": {"effect_count": 1, "err_msg": [{"line_num": 4, "msg": "账户与产品配置不一致"}],
                     "confirmation_id": ""}}
    state["catalog"] = _own_product()
    # v1 轮询是 products/{名字} 形态的业务 GET，与提交响应一起按序出队。
    state["responses"] = [(200, {"task_id": "settle-3"}), (200, done)]
    with pytest.raises(HarnessError) as error:
        client.trades.upload_settlement_file("own", str(source), "测试账户")
    assert error.value.code == "partial_failure"
    assert error.value.details["results"] == done