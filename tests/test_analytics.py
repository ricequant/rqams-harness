"""分析块：持仓暴露、业绩归因、组合对比与交易分析的参数与任务协议。"""

import json

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def _catalog(products=(), groups=()):
    """按目录构建顺序生成响应：产品列表、逐个详情、组列表、逐个组详情、资产单元。"""
    rows = [(200, {"products": [dict(row) for row in products]})]
    rows.extend((200, dict(row)) for row in products)
    rows.append((200, {"product_groups": [dict(row) for row in groups]}))
    rows.extend((200, dict(row)) for row in groups)
    rows.append((200, []))
    return rows


_OWN_PRODUCT = {"id": "p1", "name": "own", "user_id": 1}
_OWN_GROUP = {"id": "g1", "name": "group", "user_id": 1}


def _query(state):
    """返回最近一次请求的查询串参数。"""
    return state["requests"][-1][1]


def _post_body(state):
    """返回最近一次 POST 请求的 JSON 体；轮询 GET 不携带请求体。"""
    raw = [item for item in state["requests"] if item[0] == "POST"][-1][2]
    return json.loads(raw)


def _weekly_submit(state):
    """返回周报首发请求路径：带 task_id 的轮询请求要排除。"""
    return next(item[1] for item in state["requests"] if "weekly_report?" in item[1] and "task_id" not in item[1])


def test_schema_exposes_analytics_blocks_with_full_operation_counts():
    """工作空间与权限块独立后块数为 19；30 个分析/指标操作必须全部注册，缺一个都会改变对外能力面。"""
    from rqamsh.cli import schema

    blocks = schema()
    assert len(blocks) == 19
    # 块级断言：2026-09-21 并入的 indicators 块不存在（与 analytics.indicators 操作名无关）。
    assert "indicators" not in blocks
    assert len(blocks["analytics"]) == 30
    assert len(blocks["tags"]) == 3
    assert len(blocks["products"]) == 15
    assert {"indicators", "series", "win_rate", "long_short_returns", "download_series_file"} <= set(blocks["analytics"])
    assert {"weekly_report", "weekly_net_value_report"} <= set(blocks["analytics"])
    assert "get" not in blocks["analytics"]
    assert len(blocks["permissions"]) == 4
    assert len(blocks["risk_monitor"]) == 11
    assert len(blocks["market_data"]) == 11
    assert sum(len(ops) for ops in blocks.values()) == 146


def test_indicators_sends_range_benchmark_and_extra_indicators(service):
    """原 analytics.get：区间指标打产品指标端点，基准与额外指标按逗号串下发。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [(200, {"daily_risk": {"sharpe": 1.0}})]
    assert client.analytics.indicators(
        "own", start_date="2026-01-01", end_date="2026-02-01",
        benchmark="INDEX,000300.XSHG", extra_indicators=["annual_risk", "returns_summary"],
    ) == {"daily_risk": {"sharpe": 1.0}}
    path = _query(state)
    assert path.startswith("/api/rqams/v2/products/p1/indicators?")
    assert "start_date=2026-01-01" in path and "end_date=2026-02-01" in path
    assert "benchmark=INDEX%2C000300.XSHG" in path
    assert "extra_indicators=annual_risk%2Creturns_summary" in path


def test_indicators_resolves_product_groups(service):
    """原 analytics.get：产品组走组端点，同一参数形状。"""
    client, state = service
    state["responses"] = _catalog([], [_OWN_GROUP]) + [(200, {"daily_risk": {}})]
    assert client.analytics.indicators("group") == {"daily_risk": {}}
    assert _query(state) == "/api/rqams/v2/product_groups/g1/indicators"


def test_asset_weight_serializes_classifiers_and_rejects_empty(service):
    """分类数组按逗号串下发；空分类必须在本地拒绝而不是发出空筛选。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [(200, {"weights": []})]
    assert client.analytics.asset_weight("own", start_date="2026-01-01", end_date="2026-02-01",
                                         classifiers=["stock", "fund"]) == {"weights": []}
    assert "classifiers=stock%2Cfund" in _query(state)
    with pytest.raises(HarnessError) as error:
        client.analytics.asset_weight("own", start_date="2026-01-01", end_date="2026-02-01", classifiers=[])
    assert error.value.code == "invalid_argument"


def test_equity_holdings_rejects_member_view_for_product(service):
    """成员权重视图仅产品组可用，产品上传入必须报错而不是被服务端忽略。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT])
    with pytest.raises(HarnessError) as error:
        client.analytics.equity_holdings("own", start_date="2026-01-01", end_date="2026-02-01",
                                         include_component_weight_view=True)
    assert error.value.code == "invalid_argument"

    state["responses"] = _catalog(groups=[_OWN_GROUP]) + [
        (202, {"task_id": "t1"}), (200, {"status": "SUCCESS", "result": {"industry": []}}),
    ]
    assert client.analytics.equity_holdings("group", start_date="2026-01-01", end_date="2026-02-01",
                                            include_component_weight_view=True)["status"] == "SUCCESS"
    assert "include_component_weight_view=true" in _query(state)


def test_holdings_view_defaults_are_not_confused_with_missing_dates(service):
    """可选参数省略时不得下发空值，否则服务端按空字符串解析失败。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "t2"}), (200, {"status": "SUCCESS"}),
    ]
    client.analytics.convertible_holdings("own", start_date="2026-01-01", end_date="2026-02-01")
    assert "start_date=2026-01-01" in _query(state)


def test_holdings_summary_file_requires_template_and_dates(service, tmp_path):
    """枚举模板与区间是服务端硬要求，本地缺省会直接变成 400。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.analytics.holdings_summary_file("own", str(tmp_path / "a.xlsx"), "industry",
                                               start_date="2026-01-01", end_date="2026-02-01")
    assert error.value.code == "invalid_argument"

    target = tmp_path / "holdings.xlsx"
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "t3"}), (200, b"xlsx-bytes"),
    ]
    result = client.analytics.holdings_summary_file(
        "own", str(target), "equity", start_date="2026-01-01", end_date="2026-02-01",
    )
    assert result["size"] == len(b"xlsx-bytes")
    assert target.read_bytes() == b"xlsx-bytes"
    assert "template=equity" in _query(state)


def test_create_attribution_omits_absent_keys_and_requires_template_or_decomposition(service):
    """服务端对可选键做类型校验，省略必须整键缺席；无模板又不做收益拆解时提前报错。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT])
    with pytest.raises(HarnessError) as error:
        client.analytics.create_attribution("own", start_date="2026-01-01", end_date="2026-02-01",
                                            benchmark="index,000300.XSHG")
    assert error.value.code == "invalid_argument"
    with pytest.raises(HarnessError) as error:
        client.analytics.create_attribution("own", start_date="2026-01-01", end_date="2026-02-01",
                                            benchmark="000300.XSHG", template="brinson")
    assert error.value.code == "invalid_argument"

    state["responses"] = _catalog([_OWN_PRODUCT]) + [(200, {"id": "att1"})]
    assert client.analytics.create_attribution(
        "own", start_date="2026-01-01", end_date="2026-02-01", benchmark="index,000300.XSHG", template="brinson",
    ) == {"id": "att1"}
    body = _post_body(state)
    assert "industry_standard" not in body and "only_returns_decomposition" in body


def test_attribution_polls_without_resubmitting_computation(service):
    """归因查询以归因 ID 轮询，运行中不得重新提交计算任务。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (200, {"status": "DOING", "progress": 0.5}), (200, {"status": "SUCCESS", "result": {"x": 1}}),
    ]
    assert client.analytics.attribution("own", "att1")["status"] == "SUCCESS"
    methods = [item[0] for item in state["requests"][-2:]]
    assert methods == ["GET", "GET"]
    assert state["requests"][-1][1].endswith("/performance_attributions/att1")


def test_group_overview_post_omits_defaulted_keys(service):
    """组合全景请求体省略参数时键必须缺席，否则服务端取到 null 会解析失败。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "g1"}), (200, {"status": "SUCCESS", "data": []}),
    ]
    client.analytics.group_capital_size(["own"], end_date="2026-02-01")
    body = _post_body(state)
    assert body == {"product_or_group_ids": "p1", "end_date": "2026-02-01"}

    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "g2"}), (200, {"status": "SUCCESS", "data": []}),
    ]
    client.analytics.group_returns(["own"], end_date="2026-02-01", start_date="2026-01-01", benchmark="000905.XSHG")
    assert _post_body(state) == {
        "product_or_group_ids": "p1", "end_date": "2026-02-01",
        "start_date": "2026-01-01", "benchmark": "000905.XSHG",
    }


def test_group_indicators_starts_with_get_and_deduplicates_resources(service):
    """指标视图以 GET 启动并按逗号串传资源；重复资源只应出现一次。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "g3"}), (200, {"status": "SUCCESS"}),
    ]
    client.analytics.group_indicators(["own", "own"], end_date="2026-02-01")
    assert state["requests"][-2][0] == "GET" and state["requests"][-1][0] == "GET"
    assert "product_or_group_ids=p1" in _query(state)
    assert "start_date" not in _query(state)


def test_group_overview_file_waits_for_task_then_writes_file(service, tmp_path):
    """组合全景导出在任务终态后才落盘，运行中的 JSON 进度不得写入文件。"""
    client, state = service
    target = tmp_path / "overview.xlsx"
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "g4"}), (200, {"status": "DOING"}), (200, b"overview-bytes"),
    ]
    result = client.analytics.group_overview_file(["own"], str(target), end_date="2026-02-01")
    assert result["size"] == len(b"overview-bytes")
    assert target.read_bytes() == b"overview-bytes"


def test_weekly_report_deduplicates_resources_and_omits_default_keys(service):
    """周报按 GET 提交成员并集，end_date 与 start_date_mode 省略时不下发该键。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT], [_OWN_GROUP]) + [
        (202, {"task_id": "w1"}), (200, {"status": "SUCCESS", "progress": 1, "data": {"market_neutral": []}}),
    ]
    assert client.analytics.weekly_report(["own", "group", "own"], end_date="2026-09-30")["data"] == {"market_neutral": []}
    submit = _weekly_submit(state)
    assert submit == "/api/rqams/v2/product_group_overview/weekly_report?product_or_group_ids=p1%2Cg1&end_date=2026-09-30"
    assert "start_date_mode" not in submit


def test_weekly_report_rejects_unknown_start_date_mode_before_catalog(service):
    """起始日口径只接受两个服务端取值，非法值在取目录前拒绝。"""
    client, state = service
    with pytest.raises(HarnessError) as error:
        client.analytics.weekly_report(["own"], start_date_mode="成立日")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_weekly_report_passes_start_date_mode_and_surfaces_failure(service):
    """显式口径随查询串下发；任务失败终态抛 task_failed 而不是等超时。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "w2"}), (200, {"status": "FAIL", "message": "Weekly Report task_id(w2) failed"}),
    ]
    with pytest.raises(HarnessError) as error:
        client.analytics.weekly_report(["own"], start_date_mode="start_date")
    assert error.value.code == "task_failed"
    assert "start_date_mode=start_date" in _weekly_submit(state)


def test_weekly_net_value_report_waits_for_task_then_writes_file(service, tmp_path):
    """周度净值报告在任务终态后才落盘，运行中的 JSON 进度不得写入文件。"""
    client, state = service
    target = tmp_path / "weekly.xlsx"
    state["responses"] = _catalog([_OWN_PRODUCT], [_OWN_GROUP]) + [
        (202, {"task_id": "w3"}), (200, {"status": "DOING"}), (200, b"weekly-bytes"),
    ]
    result = client.analytics.weekly_net_value_report("group", str(target), end_date="2026-09-30")
    assert result["size"] == len(b"weekly-bytes")
    assert target.read_bytes() == b"weekly-bytes"
    assert state["requests"][-1][1].startswith("/api/rqams/v2/product_groups/g1/weekly_net_value_report?")


def test_single_trading_analysis_requires_order_book_id(service):
    """标的缺失时本地拒绝，避免服务端按空代码返回全量或报错。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT])
    with pytest.raises(HarnessError) as error:
        client.analytics.single_trading_analysis("own", "  ")
    assert error.value.code == "invalid_argument"

    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "t4"}), (200, {"status": "SUCCESS"}),
    ]
    client.analytics.single_trading_analysis("own", "600000.XSHG", direction="buy")
    assert "order_book_id=600000.XSHG" in _query(state) and "direction=buy" in _query(state)


def test_trading_analysis_passes_optional_filters(service):
    """交易分析的可选过滤参数只在提供时下发。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "t5"}), (200, {"status": "SUCCESS"}),
    ]
    client.analytics.algo_trading_performance("own", algo_type="twap")
    query = _query(state)
    assert "algo_type=twap" in query and "algo_name" not in query


def _indicator_catalog():
    """指标导出用例的目录响应：先产品目录，再产品组目录与成员，最后单元列表。"""
    product = {"id": "p1", "name": "own", "user_id": 1}
    return [(200, {"products": [product]}), (200, product), (200, {"product_groups": []}), (200, [])]


def test_analytics_download_series_file_passes_dates_and_writes_bytes(service, tmp_path):
    """原 indicators.download_series_file：导出带区间与指标参数，落盘返回字节数。"""
    client, state = service
    target = tmp_path / "series.xlsx"
    state["responses"] = _indicator_catalog() + [(200, b"series-bytes")]
    result = client.analytics.download_series_file(
        "own", str(target), start_date="2026-01-01", end_date="2026-08-31", indicators=["daily_returns"],
    )
    assert result == {"path": str(target.resolve()), "size": 12}
    assert target.read_bytes() == b"series-bytes"
    request = state["requests"][-1]
    assert request[1].startswith("/api/rqams/v2/products/p1/indicators_series_file?")
    assert "start_date=2026-01-01" in request[1] and "end_date=2026-08-31" in request[1]
    assert "indicators=daily_returns" in request[1]


def test_analytics_download_series_file_supports_product_groups(service, tmp_path):
    """原 indicators.download_series_file：产品组走组端点，导出与产品同实现。"""
    client, state = service
    group = {"id": "g1", "name": "组合", "user_id": 1}
    state["responses"] = [
        (200, {"products": []}), (200, {"product_groups": [group]}), (200, group), (200, []), (200, b"bytes"),
    ]
    client.analytics.download_series_file("组合", str(tmp_path / "g.xlsx"))
    assert state["requests"][-1][1] == "/api/rqams/v2/product_groups/g1/indicators_series_file"


def test_convertible_positions_polls_holdings_endpoint(service):
    """可转债持仓与其余持仓视图同协议：首发 GET 拿 task_id，随后带 task_id GET 轮询且不重发查询体。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "cp1"}),
        (200, {"status": "SUCCESS", "progress": 1, "data": {"date": "2026-09-30", "positions": []}}),
    ]
    result = client.analytics.convertible_positions("own", start_date="2026-09-01", end_date="2026-09-30")
    assert result["data"]["positions"] == []
    submit = state["requests"][-2]
    assert submit[0] == "GET"
    assert submit[1].startswith("/api/rqams/v2/products/p1/holdings_analysis/convertible_positions?")
    assert "start_date=2026-09-01" in submit[1] and "end_date=2026-09-30" in submit[1]
    assert "task_id" not in submit[1]
    assert state["requests"][-1][1].endswith("task_id=cp1") and not state["requests"][-1][2]


def test_delete_attribution_returns_none_for_empty_response(service):
    """删除归因的成功响应体为空，客户端必须返回 None 而不是把空体当成 JSON 解析失败。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [(200, b"")]
    assert client.analytics.delete_attribution("own", "att1") is None
    assert state["requests"][-1][:2] == ("DELETE", "/api/rqams/v2/products/p1/performance_attributions/att1")


def test_export_attribution_waits_for_task_then_writes_file(service, tmp_path):
    """归因导出在任务终态后才落盘，轮询必须复用同一导出路径并带 task_id。"""
    client, state = service
    target = tmp_path / "attribution.xlsx"
    state["responses"] = _catalog([_OWN_PRODUCT]) + [(202, {"task_id": "e1"}), (200, b"attribution-bytes")]
    result = client.analytics.export_attribution("own", "att1", str(target))
    assert result == {"path": str(target.resolve()), "size": len(b"attribution-bytes")}
    assert target.read_bytes() == b"attribution-bytes"
    submit = state["requests"][-2]
    assert submit[:2] == ("GET", "/api/rqams/v2/products/p1/performance_attributions/att1/attribution_file")
    assert state["requests"][-1][1] == "/api/rqams/v2/products/p1/performance_attributions/att1/attribution_file?task_id=e1"


def test_futures_holdings_sends_turnover_defaults(service):
    """期货持仓的成交额阈值与排名有客户端默认值，且显式入参必须覆盖默认而不改变端点。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "f1"}),
        (200, {
            "status": "SUCCESS", "progress": 1,
            "data": {
                "industry_distribution": [{"industry_name": "银行", "long": 1.0, "net": 0.5, "short": 0.5}],
                "commodity_distribution": [{"long": 1.0, "net": 0.0, "short": 1.0, "underlying_symbol": "CU"}],
                "inactive_variety": [], "inactive_contract": [],
                "start_date": "2026-09-01", "end_date": "2026-09-30",
            },
        }),
    ]
    result = client.analytics.futures_holdings("own", start_date="2026-09-01", end_date="2026-09-30")
    assert result["data"]["inactive_variety"] == []
    submit = state["requests"][-2][1]
    assert submit.startswith("/api/rqams/v2/products/p1/holdings_analysis/futures?")
    assert "average_total_turnover=2" in submit and "total_turnover_ranking=3" in submit

    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "f2"}), (200, {"status": "SUCCESS"}),
    ]
    client.analytics.futures_holdings("own", start_date="2026-09-01", end_date="2026-09-30",
                                      average_total_turnover=5, total_turnover_ranking=10)
    override = state["requests"][-2][1]
    assert "average_total_turnover=5" in override and "total_turnover_ranking=10" in override


def test_group_allocation_posts_asset_allocation_body(service):
    """资产配置只接受截止日，请求体与其它 v2 组合全景端点同形状，空键必须缺席。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "ga1"}),
        (200, {"status": "SUCCESS", "progress": 1, "data": {"现金": {"活期存款": 12.5}, "股票": {"主板": 87.5}}}),
    ]
    assert client.analytics.group_allocation(["own"], end_date="2026-09-30")["data"] == {
        "现金": {"活期存款": 12.5}, "股票": {"主板": 87.5},
    }
    assert state["requests"][-2][:2] == ("POST", "/api/rqams/v2/product_group_overview/asset_allocation_v2")
    assert _post_body(state) == {"product_or_group_ids": "p1", "end_date": "2026-09-30"}


def test_group_excess_correlation_omits_absent_benchmark_and_start_date(service):
    """超额相关性省略起始日与基准时整键缺席（服务端取默认值），显式提供时才下发。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "ec1"}), (200, {"status": "SUCCESS", "progress": 1, "data": {}}),
    ]
    client.analytics.group_excess_correlation(["own"], end_date="2026-09-30")
    assert state["requests"][-2][:2] == ("POST", "/api/rqams/v2/product_group_overview/excess_returns_correlation_v2")
    assert _post_body(state) == {"product_or_group_ids": "p1", "end_date": "2026-09-30"}

    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "ec2"}), (200, {"status": "SUCCESS", "data": {}}),
    ]
    client.analytics.group_excess_correlation(
        ["own"], end_date="2026-09-30", start_date="2026-09-01", benchmark="000905.XSHG",
    )
    assert _post_body(state) == {
        "product_or_group_ids": "p1", "end_date": "2026-09-30",
        "start_date": "2026-09-01", "benchmark": "000905.XSHG",
    }


def test_group_returns_correlation_posts_correlation_matrix(service):
    """收益相关性打独立矩阵端点，起始日提供时随请求体下发。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "rc1"}), (200, {"status": "SUCCESS", "progress": 1, "data": {}}),
    ]
    client.analytics.group_returns_correlation(["own"], end_date="2026-09-30", start_date="2026-09-01")
    assert state["requests"][-2][:2] == ("POST", "/api/rqams/v2/product_group_overview/returns_correlation_v2")
    assert _post_body(state) == {
        "product_or_group_ids": "p1", "end_date": "2026-09-30", "start_date": "2026-09-01",
    }


def test_long_short_returns_omits_absent_dates(service):
    """多空收益拆解不支持产品组，省略日期时不得下发空参数，否则服务端日期解析失败。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "ls1"}),
        (200, {
            "status": "SUCCESS", "progress": 1,
            "data": {
                "long_short_dismantle_returns_series": {"daily": [], "monthly": [], "weekly": []},
                "monthly_long_short_dismantle_returns": [{
                    "basis_returns": 0.1, "children": [], "date": "2026-09-30",
                    "long_excess_returns": 0.2, "portfolio_returns": 0.3,
                }],
            },
        }),
    ]
    result = client.analytics.long_short_returns("own")
    assert result["data"]["monthly_long_short_dismantle_returns"][0]["date"] == "2026-09-30"
    submit = state["requests"][-2]
    assert submit[:2] == ("GET", "/api/rqams/v2/products/p1/long_short_dismantle_returns")
    assert "start_date" not in submit[1] and "end_date" not in submit[1]
    assert state["requests"][-1][1].endswith("task_id=ls1")

    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "ls2"}), (200, {"status": "SUCCESS", "data": {}}),
    ]
    client.analytics.long_short_returns("own", start_date="2026-09-01", end_date="2026-09-30")
    explicit = state["requests"][-2][1]
    assert "start_date=2026-09-01" in explicit and "end_date=2026-09-30" in explicit


def test_option_holdings_polls_option_endpoint(service):
    """期权持仓沿用持仓视图的异步协议，端点固定为 holdings_analysis/option。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "op1"}),
        (200, {
            "status": "SUCCESS", "progress": 1,
            "data": {"greeks": {}, "series_greeks": [], "underlying_series_greeks": []},
        }),
    ]
    result = client.analytics.option_holdings("own", start_date="2026-09-01", end_date="2026-09-30")
    assert result["data"] == {"greeks": {}, "series_greeks": [], "underlying_series_greeks": []}
    submit = state["requests"][-2]
    assert submit[0] == "GET"
    assert submit[1].startswith("/api/rqams/v2/products/p1/holdings_analysis/option?")
    assert "start_date=2026-09-01" in submit[1] and "end_date=2026-09-30" in submit[1]
    assert state["requests"][-1][1].endswith("task_id=op1")


def test_realtime_factor_exposure_requires_template_and_returns_series(service):
    """实时因子暴露是同步原始 JSON（无任务轮询），template 必填且原样下发到查询串。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [(
        200,
        {
            "exposure_series": [{"datetime": "2026-10-08 09:30:00", "beta": 0.5, "momentum": 0.1, "size": -0.2}],
            "start": "2026-10-08 09:30:00", "end": "2026-10-08 15:00:00",
        },
    )]
    result = client.analytics.realtime_factor_exposure("own", template="equity/factor")
    assert result["exposure_series"][0]["beta"] == 0.5
    assert result["start"] == "2026-10-08 09:30:00"
    assert len(state["requests"]) == 5
    assert _query(state) == "/api/rqams/v2/products/p1/realtime_pa_factor_exposure_series?template=equity%2Ffactor"


def test_realtime_risk_attribution_defaults_template_and_returns_attribution(service):
    """实时风险归因默认 template=equity/factor 首发，终态 data.attribution 含 brinson 与因子归因。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "rr1"}),
        (200, {
            "status": "SUCCESS", "progress": 1,
            "data": {"attribution": {"brinson": {"industry": []}, "factor_attribution": {"beta": 0.5}}},
        }),
    ]
    result = client.analytics.realtime_risk_attribution("own")
    assert result["data"]["attribution"] == {"brinson": {"industry": []}, "factor_attribution": {"beta": 0.5}}
    submit = state["requests"][-2]
    assert submit[0] == "GET"
    assert submit[1].startswith("/api/rqams/v2/products/p1/realtime_risk_attributions?")
    assert "template=equity%2Ffactor" in submit[1] and "drilldown=false" in submit[1]
    assert state["requests"][-1][1].endswith("task_id=rr1")


def test_trading_analysis_polls_list_endpoint(service):
    """交易分析打流水列表端点，首发带区间，轮询只带 task_id。"""
    client, state = service
    state["responses"] = _catalog([_OWN_PRODUCT]) + [
        (202, {"task_id": "ta1"}),
        (200, {
            "status": "SUCCESS", "progress": 1,
            "data": [{
                "asset_category": "stock", "asset_class": "equity", "date": "2026-09-30",
                "direction": "buy", "order_book_id": "600000.XSHG", "period_pnl": 1.5, "symbol": "浦发银行",
            }],
        }),
    ]
    result = client.analytics.trading_analysis("own", start_date="2026-09-01", end_date="2026-09-30")
    assert result["data"][0]["order_book_id"] == "600000.XSHG"
    submit = state["requests"][-2]
    assert submit[0] == "GET"
    assert submit[1].startswith("/api/rqams/v2/products/p1/trading_analysis_list?")
    assert "start_date=2026-09-01" in submit[1] and "end_date=2026-09-30" in submit[1]
    assert state["requests"][-1][1].endswith("task_id=ta1") and not state["requests"][-1][2]


def test_win_rate_returns_raw_json_without_task(service):
    """胜率是同步原始 JSON（含日/周/月胜率与收益序列），不得被当成任务终态去轮询。"""
    client, state = service
    payload = {
        "daily_win_rate": [{"abs_win_rate": 0.6, "children": [], "date": "2026-09-30", "excess_win_rate": 0.1}],
        "weekly_win_rate": [{"abs_win_rate": 0.55, "children": [], "date": "2026-09-26", "excess_win_rate": 0.05}],
        "monthly_win_rate": [{"abs_win_rate": 0.5, "date": "2026-09-30", "excess_win_rate": 0.0}],
        "returns_series": [{"benchmark_returns": 0.01, "daily_returns": 0.02, "date": "2026-09-30"}],
    }
    state["responses"] = _catalog([_OWN_PRODUCT]) + [(200, payload)]
    assert client.analytics.win_rate("own", start_date="2026-01-01", end_date="2026-09-30") == payload
    assert len(state["requests"]) == 5
    assert _query(state) == "/api/rqams/v2/products/p1/win_rate?start_date=2026-01-01&end_date=2026-09-30"
