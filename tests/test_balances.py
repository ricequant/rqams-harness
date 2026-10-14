"""单日统一入口的日期、投影和权限边界。"""

from datetime import date, datetime, timedelta, timezone
import json

import pytest

from test_client import catalog_routes, service
from rqamsh.client import Client, ResourceRef
from rqamsh.errors import HarnessError


@pytest.fixture
def balance_client(monkeypatch):
    """模拟服务端按日期分流，避免固定响应掩盖夜盘错误。"""
    client = Client("http://localhost:9999", "012345678901234567890123", cookies={"sid": "test"})
    today = datetime.now(timezone(timedelta(hours=8))).date()
    state = {"period": "valuation_day", "kind": "product", "calls": []}

    def resolve(resource, allowed):
        """提供实时周期已核实的资源元数据。"""
        if state["kind"] not in allowed:
            raise HarnessError("unsupported_resource", "不支持该资源类型")
        return ResourceRef(state["kind"], "p1", resource, data={"realtime_period_type": state["period"], "products": state.get("members", [])})

    def call(method, path, *, params):
        """仿照后端摘要在请求日期早于夜盘归属日时读取历史。"""
        state["calls"].append((path, params))
        belong_date = today + timedelta(days=3) if state["period"] == "valuation_day" else today
        target = date.fromisoformat(params["date"]) if params.get("date") else None
        historical = target is not None and (target < belong_date if path.endswith("/balance_summary") else target < today)
        document = {"total_equity": 80 if historical else 120, "date": str(target if historical else belong_date), "positions": [{"quantity": 3}], "units": None}
        if state.get("unsettled"):
            document["date"] = str(today)
        if params.get("fields") and "excess_returns" in params["fields"]:
            document.update(benchmark_returns=0.05, excess_returns=0.02)
        if path.endswith("/balance_summary"):
            return {field: document.get(field) for field in params["fields"]}
        if params.get("include_component_weight_view"):
            # 服务端在存在错误信息时提前返回，此时任何成员都不带 product_weight；
            # 只有成员全部就绪才会补上权重。
            members = state.get("members", [])
            failed = state.get("member_error")
            skipped = state.get("member_pending")
            if failed:
                # 估值未就绪的成员被静默跳过：既不进结果，也不进 error_messages。
                return {member: document for member in members if member not in {failed, skipped}} | {
                    "error_messages": {failed: "估值失败"},
                }
            weight = round(1 / len(members), 4) if members else 0.0
            return {member: document | {"product_weight": weight} for member in members}
        return document

    monkeypatch.setattr(client, "resolve", resolve)
    monkeypatch.setattr(client, "call", call)
    yield client, state, today
    client.close()


@pytest.mark.parametrize("explicit_date", [False, True])
def test_realtime_night_period_never_selects_history(balance_client, explicit_date):
    """夜盘归属未来交易日时，当天和省略日期都必须读取实时权益。"""
    client, state, today = balance_client
    result = client.balances.get("own", date=str(today) if explicit_date else None, fields=["total_equity"])
    assert result == {"total_equity": 120}


def test_field_selection_does_not_leak_unrequested_positions(balance_client):
    """字段选择在不同底层路由上都限制输出，保留显式未知值。"""
    client, state, today = balance_client
    result = client.balances.get("own", fields=["units", "total_equity"], drilldown=False)
    assert result == {"units": None, "total_equity": 120}


def test_daytime_short_fields_use_summary_route(balance_client):
    """日盘简字段走摘要端点，实时概览走另一端点；端点选择只看参数不看权限。"""
    client, state, today = balance_client
    state.update(period="daytime")
    assert client.balances.get("own", fields=["total_equity"]) == {"total_equity": 120}
    assert state["calls"][-1][0].endswith("/balance_summary")
    assert client.balances.get("own", fields=["positions"]) == {"positions": [{"quantity": 3}]}
    assert state["calls"][-1][0].endswith("/asset_snapshot_summary")


def test_night_period_uses_realtime_overview_endpoint(balance_client):
    """夜盘用实时概览端点而非摘要端点，因此不会读到按当天日期回退的历史净值。"""
    client, state, today = balance_client
    assert client.balances.get("own", fields=["total_equity"]) == {"total_equity": 120}
    path, params = state["calls"][-1]
    assert path.endswith("/asset_snapshot_summary")
    assert "date" not in params


def test_historical_selection_preserves_requested_date(balance_client):
    """历史字段摘要不能被统一入口替换成实时结果。"""
    client, state, today = balance_client
    yesterday = str(today - timedelta(days=1))
    assert client.balances.get("own", date=yesterday, fields=["date", "total_equity"]) == {"date": yesterday, "total_equity": 80}


@pytest.mark.parametrize("arguments", [
    {"fields": []}, {"fields": ["positions.quantity"]},
    {"drilldown": False, "show_futures_sterilisation": False},
])
def test_unsupported_parameter_combinations_never_query(balance_client, arguments):
    """路由无法表达的业务参数不能被静默忽略。"""
    client, state, today = balance_client
    with pytest.raises(HarnessError) as error:
        client.balances.get("own", **arguments)
    assert error.value.code == "invalid_argument"
    assert state["calls"] == []


def test_future_date_is_not_a_realtime_alias(balance_client):
    """未来日期应明确失败，不能返回今天数据冒充指定日。"""
    client, state, today = balance_client
    with pytest.raises(HarnessError) as error:
        client.balances.get("own", date=str(today + timedelta(days=1)))
    assert error.value.code == "invalid_argument"
    assert state["calls"] == []


def test_member_view_keeps_weights_when_all_members_settle(balance_client):
    """成员全部就绪时下发权重，且两个诊断键都为空。"""
    client, state, today = balance_client
    state["kind"] = "product_group"
    state["members"] = ["p1", "p2"]
    result = client.balances.get("own", fields=["total_equity"], include_component_weight_view=True)
    assert result == {
        "p1": {"total_equity": 120, "product_weight": 0.5},
        "p2": {"total_equity": 120, "product_weight": 0.5},
        "error_messages": {},
        "pending_valuation": [],
    }


def test_member_view_reports_errors_without_weights(balance_client):
    """存在失败成员时服务端不计算权重，本次响应任何成员都不带 product_weight。"""
    client, state, today = balance_client
    state["kind"] = "product_group"
    state["members"] = ["p1", "p2"]
    state["member_error"] = "p2"
    result = client.balances.get("own", fields=["total_equity"], include_component_weight_view=True)
    assert result == {
        "p1": {"total_equity": 120},
        "error_messages": {"p2": "估值失败"},
        "pending_valuation": [],
    }
    assert "product_weight" not in result["p1"]


def test_member_view_drops_weights_when_a_member_is_missing(balance_client):
    """成员未就绪时权重同样不得下发：残缺成员集合上的权重会被误读为完整权重。"""
    client, state, today = balance_client
    state["kind"] = "product_group"
    state["members"] = ["p1", "p2", "p3"]
    state["member_error"] = "p2"
    state["member_pending"] = "p3"
    result = client.balances.get("own", fields=["total_equity"], include_component_weight_view=True)
    assert result == {
        "p1": {"total_equity": 120},
        "error_messages": {"p2": "估值失败"},
        "pending_valuation": ["p3"],
    }
    assert "product_weight" not in result["p1"]


def test_history_does_not_mislabel_unsettled_realtime(balance_client):
    """后端把未结算的历史日回退到实时截面时，不得冒充该日估值。"""
    client, state, today = balance_client
    state["unsettled"] = True
    with pytest.raises(HarnessError) as error:
        client.balances.get("own", date=str(today - timedelta(days=1)), fields=["total_equity"])
    assert error.value.code == "historical_date_mismatch"
    assert error.value.details["actual_date"] == str(today)


def test_historical_custom_benchmark_cannot_be_silently_ignored(balance_client):
    """历史持仓路由不传自定义基准给持仓计算，必须拒绝该组合。"""
    client, state, today = balance_client
    with pytest.raises(HarnessError) as error:
        client.balances.get("own", date=str(today - timedelta(days=1)), benchmark_id="000300.XSHG")
    assert error.value.code == "invalid_argument"
    assert state["calls"] == []


@pytest.mark.parametrize("historical", [False, True])
def test_benchmark_returns_can_be_selected_independently(balance_client, historical):
    """对外字段选择不能要求调用方猜测基准收益的底层计算触发字段。"""
    client, state, today = balance_client
    result = client.balances.get(
        "own", date=str(today - timedelta(days=1)) if historical else None,
        fields=["benchmark_returns"], benchmark_id="000300.XSHG",
    )
    assert result == {"benchmark_returns": 0.05}


def test_previous_summary_hits_product_and_group_routes(service):
    """上一交易日概览对产品与产品组各走自己的概览端点，且不带日期参数。"""
    client, state = service
    product = {"id": "p1", "name": "own", "user_id": 1}
    group = {"id": "g1", "name": "组合", "user_id": 1}
    state["catalog"] = catalog_routes([product], [group])
    state["responses"] = [(200, {"total_equity": 100, "benchmark_returns": 0.01}), (200, {"total_equity": 300})]
    assert client.balances.previous_summary("own") == {"total_equity": 100, "benchmark_returns": 0.01}
    assert client.balances.previous_summary("组合") == {"total_equity": 300}
    overview = [item for item in state["requests"] if "get_previous_summary" in item[1]]
    assert [item[1] for item in overview] == [
        "/api/rqams/v2/products/p1/balance:get_previous_summary",
        "/api/rqams/v2/product_groups/g1/balance:get_previous_summary",
    ]


def test_previous_summaries_resolves_ids_and_passes_error_messages(service):
    """批量概览提交解析后的 ID，并原样保留未就位与失败诊断。"""
    client, state = service
    product = {"id": "p1", "name": "own", "user_id": 1}
    state["catalog"] = catalog_routes([product])
    state["responses"] = [
        (200, {"p1": {"total_equity": 100}, "error_messages": {"p2": "估值未就位"}}),
    ]
    result = client.balances.previous_summaries(["own"])
    assert result == {"p1": {"total_equity": 100}, "error_messages": {"p2": "估值未就位"}}
    request = state["requests"][-1]
    assert (request[0], request[1]) == ("POST", "/api/rqams/v2/balance:get_previous_summary")
    assert json.loads(request[2]) == {"product_or_group_ids": ["p1"]}


def test_export_file_writes_bytes_and_rejects_existing_target(service, tmp_path):
    """持仓全景导出落盘返回字节数；目标已存在时不消费一次性导出。"""
    client, state = service
    product = {"id": "p1", "name": "own", "user_id": 1}
    target = tmp_path / "balance.xlsx"
    state["catalog"] = catalog_routes([product])
    state["responses"] = [(200, b"xlsx-bytes")]
    assert client.balances.export_file("own", str(target)) == {"path": str(target.resolve()), "size": 10}
    assert target.read_bytes() == b"xlsx-bytes"
    assert state["requests"][-1][1] == "/api/rqams/v2/products/p1/balance_file"
    state["requests"].clear()
    with pytest.raises(FileExistsError):
        client.balances.export_file("own", str(target))
    assert all("balance_file" not in item[1] for item in state["requests"])


def test_export_file_rejects_future_date_before_request(service, tmp_path):
    """未来日期不是实时别名，必须在请求前失败。"""
    client, state = service
    tomorrow = (datetime.now(timezone(timedelta(hours=8))).date() + timedelta(days=1)).isoformat()
    with pytest.raises(HarnessError) as error:
        client.balances.export_file("own", str(tmp_path / "b.xlsx"), date=tomorrow)
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def _post_body(state):
    """返回最近一次 POST 请求的 JSON 体。"""
    raw = [item for item in state["requests"] if item[0] == "POST"][-1][2]
    return json.loads(raw)


def test_batch_get_posts_ids_and_marks_pending_valuation(service):
    """批量分支走独立端点、体里只带资源数组并显式标注未就绪项。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "a", "user_id": 1},
                                       {"id": "p2", "name": "b", "user_id": 1}])
    state["responses"] = [
        (200, {"p1": {"total_equity": 120}, "error_messages": {"p2": "估值失败"}}),
    ]
    result = client.balances.get(["a", "b"])
    assert result == {
        "p1": {"total_equity": 120}, "error_messages": {"p2": "估值失败"}, "pending_valuation": [],
    }
    assert state["requests"][-1][1].endswith("/asset_snapshot_summary")
    assert _post_body(state) == {"product_or_group_ids": ["p1", "p2"]}

    state["responses"] = [(200, {"p1": {"total_equity": 120}})]
    result = client.balances.get(["a", "b"])
    assert result["pending_valuation"] == ["p2"] and result["error_messages"] == {}


def test_batch_get_rejects_single_resource_only_parameters(service):
    """批量端点不读这些参数，传入必须报错而不是被静默丢弃。"""
    client, state = service
    for kwargs in ({"date": "2026-01-01"}, {"classifier": "stock"}, {"benchmark_id": "000300.XSHG"},
                   {"drilldown": False}, {"show_futures_sterilisation": False},
                   {"include_component_weight_view": True}):
        with pytest.raises(HarnessError) as error:
            client.balances.get(["a"], **kwargs)
        assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_export_snapshot_single_resource_is_synchronous(service, tmp_path):
    """单资源实时监控导出同步落盘；上一交易日口径只属于多资源端点。"""
    client, state = service
    target = tmp_path / "snapshot.xlsx"
    state["catalog"] = catalog_routes([{"id": "p1", "name": "a", "user_id": 1}])
    state["responses"] = [(200, b"snap-bytes")]
    result = client.balances.export_snapshot("a", str(target), classifier="stock")
    assert result["size"] == len(b"snap-bytes") and target.read_bytes() == b"snap-bytes"
    assert "classifier=stock" in state["requests"][-1][1]

    with pytest.raises(HarnessError) as error:
        client.balances.export_snapshot("a", str(tmp_path / "other.xlsx"), previous_trading_day=True)
    assert error.value.code == "invalid_argument"


def test_export_snapshot_multiple_resources_split_ids_and_wait(service, tmp_path):
    """多资源导出按类型拆分 ID、走概览文件端点并在任务终态后落盘。"""
    client, state = service
    target = tmp_path / "overview.xlsx"
    state["catalog"] = catalog_routes([{"id": "p1", "name": "a", "user_id": 1}],
                                      [{"id": "g1", "name": "grp", "user_id": 1}])
    state["responses"] = [
        (202, {"task_id": "t1"}), (200, b"overview-bytes"),
    ]
    result = client.balances.export_snapshot(["a", "grp"], str(target), previous_trading_day=True)
    assert result["size"] == len(b"overview-bytes") and target.read_bytes() == b"overview-bytes"
    query = state["requests"][-2][1]
    assert "product_ids=p1" in query and "product_group_ids=g1" in query and "previous_trading_day=true" in query

    with pytest.raises(HarnessError) as error:
        client.balances.export_snapshot(["a", "grp"], str(tmp_path / "x.xlsx"), classifier="stock")
    assert error.value.code == "invalid_argument"


def test_series_realtime_branch_requires_clean_parameters(service):
    """盘中序列由省略截止日期触发，冲突参数与基准错配必须报错。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "a", "user_id": 1}])
    state["responses"] = [(200, {"asset_series": []})]
    assert client.balances.series("a", benchmark_id="000905.XSHG") == {"asset_series": []}
    assert state["requests"][-1][1].endswith("/realtime_asset_series?benchmark_id=000905.XSHG")

    with pytest.raises(HarnessError) as error:
        client.balances.series("a", start_date="2026-01-01")
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.balances.series("a", position_fields=["weight"])
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.balances.series("a", start_date="2026-01-01", end_date="2026-02-01", benchmark_id="000300.XSHG")
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.balances.series("a", end_date="2026-02-01")
    assert error.value.code == "invalid_argument"


def test_field_earliest_dates_only_accept_products(service):
    """字段最早日期端点只查产品；组 ID 会被服务端静默查空，必须在本地拒绝。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "a", "user_id": 1}],
                                      [{"id": "g1", "name": "grp", "user_id": 1}])
    state["responses"] = [
        (200, [{"product_id": "p1", "earliest_date": "2020-01-02"}]),
    ]
    assert client.balances.field_earliest_dates(["a"]) == [{"product_id": "p1", "earliest_date": "2020-01-02"}]
    assert _post_body(state) == {"product_ids": ["p1"], "field": "unit_net_value"}
    assert state["requests"][-1][1].endswith("/products/balance:query_field_existed_earliest_dates_by_product")

    with pytest.raises(HarnessError) as error:
        client.balances.field_earliest_date(["grp"])
    assert error.value.code == "unsupported_resource"
