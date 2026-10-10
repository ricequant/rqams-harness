"""风险监控块：条款维护、实时预警与看板类监控数据。"""

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


def test_clauses_sends_singular_level_and_resolved_ids(service):
    """预警等级线上参数名是单数 level；产品筛选必须下发解析后的 ID 逗号串。"""
    client, state = service
    state["responses"] = [
        (200, {"products": [{"id": "p1", "name": "own", "user_id": 1}]}),
        (200, {"id": "p1", "name": "own", "user_id": 1}),
        (200, {"product_groups": []}),
        (200, []),
        (200, []),
    ]
    assert client.risk_monitor.clauses(product_ids=["own"], levels=[1, 3]) == []
    query = _query(state)
    assert "level=1%2C3" in query
    assert "product_ids=p1" in query
    assert "levels=" not in query


def test_clauses_rejects_empty_selector(service):
    """空选择器必须本地拒绝，不能退化成「不过滤」。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.risk_monitor.clauses(product_ids=[])
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_create_clauses_posts_bare_array(service):
    """条款创建体是裸数组且逐项校验，空批次与非法元素都要提前拦截。"""
    client, state = service
    state["responses"] = [(200, {"inserted_count": 1})]
    clause = {"level": 1, "indicator": "st", "target_ids": {"products": ["p1"]}}
    assert client.risk_monitor.create_clauses([clause]) == {"inserted_count": 1}
    assert _post_body(state) == [clause]

    with pytest.raises(HarnessError) as error:
        client.risk_monitor.create_clauses([])
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.risk_monitor.create_clauses(["not-a-clause"])
    assert error.value.code == "invalid_argument"


def test_update_clause_uses_patch_and_rejects_empty_payload(service):
    """条款更新是 PATCH；空对象不会产生任何变更，必须在本地拒绝。"""
    client, state = service
    state["responses"] = [(200, {"effect_count": 1})]
    assert client.risk_monitor.update_clause("c1", {"level": 2}) == {"effect_count": 1}
    assert state["requests"][-1][0] == "PATCH"
    assert state["requests"][-1][1].endswith("/risk_clauses/c1")

    with pytest.raises(HarnessError) as error:
        client.risk_monitor.update_clause("c1", {})
    assert error.value.code == "invalid_argument"


def test_delete_clauses_posts_bare_id_array(service):
    """批量删除体是字符串裸数组，不接受对象包装。"""
    client, state = service
    state["responses"] = [(200, {"deleted_count": 2})]
    assert client.risk_monitor.delete_clauses(["c1", "c2"]) == {"deleted_count": 2}
    assert _post_body(state) == ["c1", "c2"]

    with pytest.raises(HarnessError) as error:
        client.risk_monitor.delete_clauses([])
    assert error.value.code == "invalid_argument"


def test_realtime_warnings_returns_server_payload_without_extra_requests(service):
    """实时预警已按用户隔离，Harness 不得再取目录或过滤字段。"""
    client, state = service
    payload = {"warning_msgs": ["超限"], "warning_clause_ids": ["c1"], "warning_resource_ids": ["p1"]}
    state["responses"] = [(200, payload)]
    assert client.risk_monitor.realtime_warnings() == payload
    assert len(state["requests"]) == 1


def test_illegal_announcements_repeats_read_until_terminal(service):
    """该接口无 task_id，首次 202 后必须在同一路由重复读取直到终态。"""
    client, state = service
    state["responses"] = [(202, {"status": "DOING", "progress": 0}), (200, {"status": "SUCCESS", "obids": []})]
    assert client.risk_monitor.illegal_announcements()["status"] == "SUCCESS"
    assert [item[0] for item in state["requests"]] == ["GET", "GET"]
    assert state["requests"][-1][1] == state["requests"][0][1]


@pytest.mark.parametrize(
    "method, kwargs, expected",
    [
        ("vix", {"index_ids": ["000001.XSHG", "000300.XSHG"], "fields": "minbar"},
         "index_ids=000001.XSHG%2C000300.XSHG"),
        ("etf_premium_rate", {"etf_ids": "510300.XSHG", "fields": "minbar"}, "etf_ids=510300.XSHG"),
        ("goodwill_ratio", {"board_types": ["all"], "start_date": "2026-01-01", "end_date": "2026-02-01"},
         "board_types=all"),
    ],
)
def test_monitor_series_serialize_selectors(service, method, kwargs, expected):
    """逗号串参数既能接受数组也接受字符串，数组按顺序序列化。"""
    client, state = service
    state["responses"] = [(200, [])]
    assert getattr(client.risk_monitor, method)(**kwargs) == []
    assert expected in _query(state)


def test_dashboard_daily_fields_require_dates(service):
    """日度历史必须显式给区间：服务端在 fields 含 daily 时解析空日期会直接失败。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.risk_monitor.vix(["000300.XSHG"])
    assert error.value.code == "invalid_argument"

    state["responses"] = [(200, {"daily": []})]
    assert client.risk_monitor.vix(["000300.XSHG"], start_date="2026-01-01", end_date="2026-02-01") == {"daily": []}
    query = _query(state)
    assert "fields=minbar%2Cdaily" in query and "start_date=2026-01-01" in query

    with pytest.raises(HarnessError) as error:
        client.risk_monitor.etf_premium_rate("510300.XSHG", fields="hourly")
    assert error.value.code == "invalid_argument"


def test_monitor_series_reject_empty_selectors(service):
    """空标签或空串会退化成全量或空查询，必须本地拒绝。"""
    client, state = service
    for method, kwargs in (("vix", {"index_ids": ""}), ("etf_premium_rate", {"etf_ids": []}),
                           ("goodwill_ratio", {"board_types": [], "start_date": "2026-01-01",
                                               "end_date": "2026-02-01"})):
        with pytest.raises(HarnessError) as error:
            getattr(client.risk_monitor, method)(**kwargs)
        assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_etf_shares_and_margin_balance_require_dates(service):
    """两个接口的服务端契约都要求区间，缺省时不能发出空日期。"""
    client, state = service
    state["responses"] = [(200, {})]
    assert client.risk_monitor.etf_shares("510300.XSHG", start_date="2026-01-01", end_date="2026-02-01") == {}
    query = _query(state)
    assert "etf_id=510300.XSHG" in query and "start_date=2026-01-01" in query


def test_margin_balance_sends_only_date_range(service):
    """两融余额是无选择器的裸数组序列，请求只带日期区间且返回原样透传。"""
    client, state = service
    rows = [{"date": "2026-09-01", "margin_balance": 2628538590190, "margin_ratio": 0.029478389450366554}]
    state["responses"] = [(200, rows)]
    assert client.risk_monitor.margin_balance(start_date="2026-09-01", end_date="2026-09-02") == rows
    request = state["requests"][-1]
    assert request[0] == "GET"
    assert request[1] == "/api/rqams/v2/margin_balance?start_date=2026-09-01&end_date=2026-09-02"


def test_goodwill_ratio_sends_board_types_and_range(service):
    """商誉占比按请求板块返回对应键，请求必须下发板块逗号串与日期区间。"""
    client, state = service
    rows = [{"date": "2026-09-01", "GEM": 0.0123, "KSH": 0.0045}]
    state["responses"] = [(200, rows)]
    assert client.risk_monitor.goodwill_ratio(
        ["GEM", "KSH"], start_date="2026-08-01", end_date="2026-09-01",
    ) == rows
    request = state["requests"][-1]
    assert request[0] == "GET"
    assert request[1] == (
        "/api/rqams/v2/goodwill_ratio?board_types=GEM%2CKSH&start_date=2026-08-01&end_date=2026-09-01"
    )

    state["responses"] = [(200, [{"date": "2026-09-01", "KSH": 0.0045}])]
    assert client.risk_monitor.goodwill_ratio(
        "KSH", start_date="2026-08-01", end_date="2026-09-01",
    ) == [{"date": "2026-09-01", "KSH": 0.0045}]
    assert _query(state).endswith(
        "/goodwill_ratio?board_types=KSH&start_date=2026-08-01&end_date=2026-09-01"
    )
