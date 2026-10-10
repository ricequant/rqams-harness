"""市场数据块：基准收益、行情日历、标的检索与自定义基准维护。"""

import json

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def _query(state):
    """返回最近一次请求的查询串。"""
    return state["requests"][-1][1]


def _post_body(state):
    """返回最近一次 POST 请求的 JSON 体。"""
    raw = [item for item in state["requests"] if item[0] == "POST"][-1][2]
    return json.loads(raw)


def test_benchmark_returns_never_sends_false_for_include_customized(service):
    """服务端按字符串真值判断该开关，下发 false 会被当成真并混入自定义基准。"""
    client, state = service
    state["responses"] = [(200, [])]
    client.market_data.benchmark_returns()
    assert "include_customized" not in _query(state)

    state["responses"] = [(200, [])]
    client.market_data.benchmark_returns(benchmark_ids=["000300.XSHG"], include_customized=True)
    query = _query(state)
    assert "include_customized=true" in query and "benchmark_ids=000300.XSHG" in query


def test_benchmarks_rule_without_leading_slash_is_reachable(service):
    """该路由的服务端 rule 没有前导斜杠，客户端拼接方式必须兼容。"""
    client, state = service
    state["responses"] = [(200, [{"order_book_id": "000300.XSHG"}])]
    assert client.market_data.benchmarks() == [{"order_book_id": "000300.XSHG"}]
    assert state["requests"][-1][1] == "/api/rqams/v2/benchmarks"


def test_realtime_benchmark_returns_omits_absent_benchmark(service):
    """省略基准时不下发空参数，由服务端返回全部内置基准。"""
    client, state = service
    state["responses"] = [(200, {})]
    client.market_data.realtime_benchmark_returns()
    assert "benchmark_id" not in _query(state)


def test_customized_benchmark_create_validates_type_payload(service):
    """复合基准必须带权重、固定数值必须带非负利率，缺一即本地拒绝。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.market_data.create_customized_benchmark("组合A", "composite")
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.market_data.create_customized_benchmark("利率A", "fixed_rates", rates=-0.01)
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.market_data.create_customized_benchmark("未知", "unknown", rates=0.02)
    assert error.value.code == "invalid_argument"

    state["responses"] = [(200, {"name": "利率A"})]
    client.market_data.create_customized_benchmark("利率A", "fixed_rates", rates=0.0)
    assert _post_body(state) == {"name": "利率A", "type": "fixed_rates", "rates": 0.0}


def test_customized_benchmark_update_and_delete_use_item_path(service):
    """整体更新是 PUT、删除是 DELETE，都指向单个基准路径。"""
    client, state = service
    state["responses"] = [(200, {"modified": 1})]
    client.market_data.update_customized_benchmark(
        "cb1", "组合A", "composite",
        weights=[{"start_date": "2026-01-01",
                  "weights": [{"order_book_id": "000300.XSHG", "weight": 1.0}]}],
    )
    assert state["requests"][-1][0] == "PUT" and state["requests"][-1][1].endswith("/customized_benchmarks/cb1")

    state["responses"] = [(200, {"deleted_count": 1})]
    client.market_data.delete_customized_benchmark("cb1")
    assert state["requests"][-1][0] == "DELETE"


def test_composite_weights_require_components(service):
    """复合基准的每个权重块都必须给出非空成分与代码、数值权重，否则必然被服务端拒绝。"""
    client, state = service
    for weights in ([{"start_date": "2026-01-01", "weights": []}],
                    [{"start_date": "2026-01-01", "weights": [{"weight": 1.0}]}],
                    [{"start_date": "2026-01-01", "weights": [{"order_book_id": "000300.XSHG"}]}]):
        with pytest.raises(HarnessError) as error:
            client.market_data.create_customized_benchmark("组合A", "composite", weights=weights)
        assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_trading_dates_rejects_unknown_calendar_type(service):
    """服务端只接受 exchange，其他取值会得到空数组，本地提前拒绝以免误读为无交易日。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.market_data.trading_dates("product")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []

    state["responses"] = [(200, ["2026-01-05"])]
    assert client.market_data.trading_dates("exchange") == ["2026-01-05"]
    assert "type=exchange" in _query(state)


def test_realtime_quotes_serializes_ids_and_rejects_empty(service):
    """行情接口只接受逗号串代码，数组需序列化，空串会变成无效请求。"""
    client, state = service
    state["responses"] = [(200, [{"order_book_id": "600000.XSHG"}])]
    client.market_data.realtime_quotes(["600000.XSHG", "000001.XSHE"])
    assert "order_book_ids=600000.XSHG%2C000001.XSHE" in _query(state)

    with pytest.raises(HarnessError) as error:
        client.market_data.realtime_quotes([])
    assert error.value.code == "invalid_argument"


def test_instruments_default_limit_is_applied(service):
    """标的检索带默认条数上限，避免无意拉取超大数据集。"""
    client, state = service
    state["responses"] = [(200, [])]
    client.market_data.instruments(q="茅台")
    query = _query(state)
    assert "limit=20" in query and "instrument_type" not in query


def test_index_futures_basis_passes_optional_switches(service):
    """可选的复权与字段参数只在提供时下发。"""
    client, state = service
    state["responses"] = [(200, [])]
    client.market_data.index_futures_basis()
    assert "dividend_adjusted" not in _query(state)

    state["responses"] = [(200, [])]
    client.market_data.index_futures_basis(dividend_adjusted=False, fields="basis")
    query = _query(state)
    assert "dividend_adjusted=false" in query and "fields=basis" in query


def test_customized_benchmarks_lists_without_params(service):
    """自定义基准列表是无参数 GET，复合权重与固定利率定义都按服务端结构透传。"""
    client, state = service
    payload = [
        {"name": "组合A", "type": "composite", "workspace_id": "012345678901234567890123",
         "user_id": 100001, "remarks": "", "id": "cb1",
         "weights": [{"id": "w1", "customized_benchmark_id": "cb1", "start_date": "2026-01-01",
                      "weights": [{"order_book_id": "000300.XSHG", "weight": 1.0}]}]},
        {"name": "利率A", "type": "fixed_rates", "workspace_id": "012345678901234567890123",
         "user_id": 100001, "remarks": "", "id": "cb2", "rates": 0},
    ]
    state["responses"] = [(200, payload)]
    assert client.market_data.customized_benchmarks() == payload
    assert state["requests"][-1][0] == "GET"
    assert state["requests"][-1][1] == "/api/rqams/v2/customized_benchmarks"
    assert state["requests"][-1][2] == b""
