"""模拟交易统一模板：创建、配置读取、信号上传与模板路由。"""

import json
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def _form(state, path_fragment):
    """读取最近一次匹配路径的 POST urlencoded 表单体并解析。"""
    request = next(item for item in reversed(state["requests"]) if item[0] == "POST" and path_fragment in item[1])
    return {key: values[0] for key, values in parse_qs(request[2].decode()).items()}


def _product():
    """返回一个可被目录解析的模拟交易产品。"""
    return {
        "id": "p1", "name": "2026行情", "label": "paper_trading",
        "benchmark": {"type": "index", "id": "000300.XSHG"},
        "start_date": "2026-01-05",
    }


def _equity_config():
    """返回一条权益类多头策略模板配置。"""
    return {
        "_id": "pt1", "product_id": "p1", "strategy_model": "equity_long",
        "algo": "open", "init_amount": 10000000.0, "commission_rate": 0.0002,
    }


def _conventional_config():
    """返回一条通用策略模板通道配置。"""
    return {
        "_id": "ch1", "product_id": "p1", "init_amount": 5000000.0,
        "stock_min_fee": 5.0, "stock_commission_rate": 0.0002,
        "loan_rate": 0.08, "margin_rate": 0.5,
    }


def test_create_equity_long_uses_form_and_polls(service):
    """权益类多头策略模板创建只提交该模板参数，并按 task_id 等待终态。"""
    client, state = service
    state["responses"] = [
        (202, {"task_id": "t1"}),
        (200, {"status": "SUCCESS", "progress": 1, "data": {"product_id": "p1", "paper_trading_id": "pt1"}}),
    ]
    result = client.paper_trading.create(
        "equity_long", name="2026行情", benchmark="index,000300.XSHG",
        start_date="2026-01-05", init_amount=10000000, algo="vwap",
        start_time="09:30", end_time="09:35", commission_rate=0.0002,
    )
    assert result == {
        "template": "equity_long", "product_id": "p1", "paper_trading_id": "pt1",
    }
    submit = next(item for item in state["requests"] if item[0] == "POST")
    assert submit[1] == "/api/rqams/v2/products/paper_trading_v2"
    form = _form(state, "products/paper_trading_v2")
    assert form["strategy_model"] == "equity_long"
    assert form["algo"] == "vwap"
    assert form["start_time"] == "09:30" and form["end_time"] == "09:35"
    assert "strategy_category" not in form


def test_create_conventional_requires_category_and_rejects_equity_fields(service):
    """通用策略模板走独立入口，必须带策略分类和四项基础费率。"""
    client, state = service
    state["responses"] = [(200, {"status": "SUCCESS", "data": {"product_id": "p2", "channel_id": "ch2"}})]
    result = client.paper_trading.create(
        "conventional", name="通用策略", benchmark="index,000905.XSHG",
        start_date="2026-02-02", init_amount=5000000, strategy_category="stock_long",
        stock_min_fee=5, stock_commission_rate=0.0002, loan_rate=0.08, margin_rate=0.5,
    )
    assert result["template"] == "conventional" and result["channel_id"] == "ch2"
    submit = next(item for item in state["requests"] if item[0] == "POST")
    assert submit[1] == "/api/rqams/v2/products/paper_trading_v2:create_conventional"
    form = _form(state, "create_conventional")
    assert form["strategy_category"] == "stock_long"
    assert form["stock_min_fee"] == "5.0"
    assert "algo" not in form

    with pytest.raises(HarnessError) as error:
        client.paper_trading.create(
            "conventional", name="通用策略", benchmark="index,000905.XSHG",
            start_date="2026-02-02", init_amount=5000000, strategy_category="stock_long",
            stock_min_fee=5, stock_commission_rate=0.0002, loan_rate=0.08, margin_rate=0.5,
            algo="open",
        )
    assert error.value.code == "invalid_argument"


def test_get_routes_template_without_exposing_versions(service):
    """配置读取按产品返回 template；没有配置的产品不能伪装成模拟交易。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    state["responses"] = [(200, [_equity_config()]), (200, [])]
    result = client.paper_trading.get("2026行情")
    assert result["template"] == "equity_long"
    assert result["product_id"] == "p1"
    assert result["config"]["_id"] == "pt1"

    state["responses"] = [(200, []), (200, [_conventional_config()])]
    result = client.paper_trading.get("2026行情")
    assert result["template"] == "conventional"
    assert result["config"]["_id"] == "ch1"

    state["responses"] = [(200, []), (200, [])]
    with pytest.raises(HarnessError) as error:
        client.paper_trading.get("2026行情")
    assert error.value.code == "paper_trading_config_not_found"


def test_upload_signals_equity_uses_file_session_and_batch_upload(service, tmp_path):
    """权益类多头策略模板先上传文件会话，再提交一次批量信号任务，不按单文件重复提交。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    state["responses"] = [
        (200, [_equity_config()]), (200, []),
        (200, {"file_session_id": "s1"}),
        (200, {"uploaded_count": 1}),
        (202, {"task_id": "u1"}),
        (200, {"status": "SUCCESS", "progress": 1, "data": {"2026-01-05.csv": {"new_id": "sig1"}}}),
    ]
    path = tmp_path / "2026-01-05.csv"
    path.write_text("order_book_id,target_weight\n000001.XSHE,0.5\n", encoding="utf-8")
    result = client.paper_trading.upload_signals("2026行情", [str(path)])
    assert result["template"] == "equity_long" and result["file_session_id"] == "s1"
    paths = [item[1] for item in state["requests"] if item[0] == "POST"]
    assert "/api/rqams/v2/file_upload_sessions" in paths
    assert "/api/rqams/v2/file_upload_sessions/s1/files" in [item.split("?")[0] for item in paths]
    assert any("paper_trading_v2/signals:batch_upload" in item for item in paths)
    assert "2026-01-05.csv" in next(item[2].decode() for item in state["requests"] if "s1/files" in item[1])


def test_upload_signals_conventional_posts_files_in_batches(service, tmp_path):
    """通用策略模板按通道批量提交文件，文件名随 multipart 上传。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    state["responses"] = [
        (200, []), (200, [_conventional_config()]),
        (202, {"task_id": "u2"}),
        (200, {"status": "SUCCESS", "progress": 1, "data": {}}),
    ]
    path = tmp_path / "2026-01-05.csv"
    path.write_text("order_book_id,target_weight\n000001.XSHE,0.5\n", encoding="utf-8")
    result = client.paper_trading.upload_signals("2026行情", [str(path)])
    assert result["template"] == "conventional" and result["channel_id"] == "ch1"
    submit = next(item for item in state["requests"] if item[0] == "POST")
    assert submit[1] == "/api/rqams/v2/products/p1/paper_trading_channels/ch1/batch_paper_trading_file"
    assert "2026-01-05.csv" in submit[2].decode()


def _signal_file(tmp_path, name):
    """生成一个本地信号文件；内容不参与客户端校验，只证明上传读取了该路径。"""
    path = tmp_path / name
    path.write_text("order_book_id,target_weight\n000001.XSHE,0.5\n", encoding="utf-8")
    return str(path)


def test_upload_signals_equity_all_files_failed_raises_with_complete_result(service, tmp_path):
    """权益模板全部文件失败时抛 partial_failure，保留完整公开包装和失败文件名映射，不重传。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    names = ["2026-01-05.csv", "2026-01-06.csv"]
    failed = {names[0]: "文件缺少 target_weight 列", names[1]: "同一文件存在重复合约"}
    payload = {"status": "SUCCESS", "progress": 1, "data": {name: {"err_msg": reason} for name, reason in failed.items()}}
    state["responses"] = [
        (200, [_equity_config()]), (200, []),
        (200, {"file_session_id": "s1"}),
        (200, {"uploaded_count": 2}),
        (202, {"task_id": "u1"}),
        (200, payload),
    ]
    paths = [_signal_file(tmp_path, name) for name in names]
    with pytest.raises(HarnessError) as error:
        client.paper_trading.upload_signals("2026行情", paths)
    assert error.value.code == "partial_failure"
    assert error.value.details["results"] == {
        "template": "equity_long", "product_id": "p1", "file_session_id": "s1", "result": payload,
    }
    assert error.value.details["failed_files"] == failed
    assert sum(request[0] == "POST" and "signals:batch_upload" in request[1] for request in state["requests"]) == 1


def test_upload_signals_equity_partial_failure_keeps_successes(service, tmp_path):
    """权益模板部分文件失败时仍抛 partial_failure，成功文件的逐文件结果保留在异常详情中。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    names = ["2026-01-05.csv", "2026-01-06.csv"]
    payload = {
        "status": "SUCCESS", "progress": 1,
        "data": {names[0]: {"new_id": "sig1"}, names[1]: {"err_msg": "缺少 target_weight 列"}},
    }
    state["responses"] = [
        (200, [_equity_config()]), (200, []),
        (200, {"file_session_id": "s1"}),
        (200, {"uploaded_count": 2}),
        (202, {"task_id": "u1"}),
        (200, payload),
    ]
    paths = [_signal_file(tmp_path, name) for name in names]
    with pytest.raises(HarnessError) as error:
        client.paper_trading.upload_signals("2026行情", paths)
    assert error.value.code == "partial_failure"
    assert error.value.details["results"]["result"]["data"][names[0]] == {"new_id": "sig1"}
    assert error.value.details["failed_files"] == {names[1]: "缺少 target_weight 列"}


def test_upload_signals_conventional_all_files_failed_raises_with_batches(service, tmp_path):
    """通用模板全部文件失败时抛 partial_failure，保留已提交批次和逐文件失败原因。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    names = ["2026-01-05.csv", "2026-01-06.csv"]
    failed = {names[0]: "无法识别文件形态", names[1]: "非 open 算法缺少执行时间"}
    payload = {"status": "SUCCESS", "progress": 1, "data": {name: {"err_msg": reason} for name, reason in failed.items()}}
    state["responses"] = [
        (200, []), (200, [_conventional_config()]),
        (202, {"task_id": "u2"}),
        (200, payload),
    ]
    paths = [_signal_file(tmp_path, name) for name in names]
    with pytest.raises(HarnessError) as error:
        client.paper_trading.upload_signals("2026行情", paths)
    assert error.value.code == "partial_failure"
    assert error.value.details["results"] == {
        "template": "conventional", "product_id": "p1", "channel_id": "ch1", "batches": [payload],
    }
    assert error.value.details["failed_files"] == failed


def test_upload_signals_conventional_stops_after_failing_first_batch(service, tmp_path):
    """通用模板超过 50 个文件时，首批出现失败即停止，保留成功文件与失败文件结果。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    names = (
        [f"2026-01-{day:02d}.csv" for day in range(1, 32)]
        + [f"2026-02-{day:02d}.csv" for day in range(1, 29)]
        + ["2026-03-02.csv"]
    )
    first_batch = {
        "status": "SUCCESS", "progress": 1,
        "data": {
            names[0]: {"new_id": "sig-ok-1"},
            names[1]: {"err_msg": "同一文件存在重复合约"},
            names[2]: {"new_id": "sig-ok-2"},
        },
    }
    state["responses"] = [
        (200, []), (200, [_conventional_config()]),
        (202, {"task_id": "u2"}),
        (200, first_batch),
        (200, {"status": "SUCCESS", "progress": 1, "data": {names[50]: {"new_id": "sig-ok-3"}}}),
    ]
    paths = [_signal_file(tmp_path, name) for name in names]
    with pytest.raises(HarnessError) as error:
        client.paper_trading.upload_signals("2026行情", paths)
    assert error.value.code == "partial_failure"
    assert error.value.details["failed_files"] == {names[1]: "同一文件存在重复合约"}
    results = error.value.details["results"]
    assert results["template"] == "conventional" and results["product_id"] == "p1"
    assert results["channel_id"] == "ch1" and results["batches"] == [first_batch]
    submits = [request[1] for request in state["requests"] if request[0] == "POST" and "batch_paper_trading_file" in request[1]]
    assert len(submits) == 1
    assert names[49] in state["requests"][-2][2].decode()
    assert names[50] not in state["requests"][-2][2].decode()


def test_signals_and_recompute_route_by_template(service):
    """信号查询、删除和重算都按模板选择路由，应用层无需知道底层版本。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    state["responses"] = [(200, [_equity_config()]), (200, [])]
    state["responses"].append((200, [{"_id": "sig1"}]))
    assert client.paper_trading.list_signals("2026行情", start_date="2026-01-05") == [{"_id": "sig1"}]
    assert state["requests"][-1][1].endswith("/paper_trading_v2/signals?start_date=2026-01-05")

    state["responses"] = [(200, []), (200, [_conventional_config()])]
    state["responses"].append((202, {"task_id": "d1"}))
    state["responses"].append((200, {"status": "SUCCESS", "data": {"effect_count": 1}}))
    result = client.paper_trading.delete_signals("2026行情", start_date="2026-01-05")
    assert result == {"template": "conventional", "status": "SUCCESS", "data": {"effect_count": 1}}
    assert state["requests"][-2][0] == "DELETE"
    assert state["requests"][-2][1].endswith("/paper_trading_channels/paper_trading_signals")

    state["responses"] = [(200, [_equity_config()]), (200, [])]
    state["responses"].append((202, {"task_id": "r1"}))
    state["responses"].append((200, {"status": "SUCCESS"}))
    assert client.paper_trading.recompute("2026行情", date="2026-01-05")["status"] == "SUCCESS"
    assert state["requests"][-1][1].endswith("/paper_trading_v2:recompute?task_id=r1")

    state["responses"] = [(200, []), (200, [_conventional_config()])]
    state["responses"].append((202, {"task_id": "r2"}))
    state["responses"].append((200, {"status": "SUCCESS"}))
    assert client.paper_trading.recompute("2026行情", date="2026-01-05")["status"] == "SUCCESS"
    assert state["requests"][-2][1].endswith("/paper_trading_channels/ch1:async_recompute")
    assert state["requests"][-1][1].endswith(":async_recompute?task_id=r2")


@pytest.mark.parametrize("template", ["equity_long", "conventional"])
@pytest.mark.parametrize("kwargs", [{}, {"date": None}, {"date": "2026-01-05"}])
def test_recompute_optional_date_matches_server_contract(service, template, kwargs):
    """全量重算不发送空日期，指定起始日仍保留日期条件。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    configs = (
        ([_equity_config()], []) if template == "equity_long"
        else ([], [_conventional_config()])
    )
    state["responses"] = [
        (200, configs[0]), (200, configs[1]),
        (202, {"task_id": "recompute-task"}),
        (200, {"status": "SUCCESS", "data": {"recomputed": True}}),
    ]

    result = client.paper_trading.recompute("2026行情", **kwargs)

    submit = next(request for request in state["requests"] if request[0] == "POST")
    body = json.loads(submit[2])
    if kwargs.get("date") is None:
        assert body == {}
    else:
        assert body == {"date": "2026-01-05"}
    assert result == {"status": "SUCCESS", "data": {"recomputed": True}}


def test_delete_single_conventional_signal_uses_channel_route(service):
    """通用策略模板的单条删除也走通道路径，并等待异步任务结束。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])
    state["responses"] = [
        (200, []), (200, [_conventional_config()]),
        (202, {"task_id": "d2"}),
        (200, {"status": "SUCCESS", "data": {"effect_count": 1}}),
    ]
    result = client.paper_trading.delete_signals("2026行情", signal_ids=["sig1"])
    assert result["template"] == "conventional"
    assert result["results"] == [{"status": "SUCCESS", "data": {"effect_count": 1}}]
    assert state["requests"][-2][1].endswith("/paper_trading_channels/paper_trading_signals/sig1")


def test_delete_signals_omits_absent_date_conditions(service):
    """按 ID 或单侧日期删除只发送实际提供的条件，不把 null 写进请求体。"""
    client, state = service
    state["catalog"] = catalog_routes(products=[_product()])

    state["responses"] = [
        (200, [_equity_config()]), (200, []),
        (202, {"task_id": "d3"}), (200, {"status": "SUCCESS"}),
    ]
    client.paper_trading.delete_signals("2026行情", signal_ids=["sig1", "sig2"])
    assert json.loads(state["requests"][-2][2].decode()) == {"signal_ids": ["sig1", "sig2"]}

    state["responses"] = [
        (200, [_equity_config()]), (200, []),
        (202, {"task_id": "d4"}), (200, {"status": "SUCCESS"}),
    ]
    client.paper_trading.delete_signals("2026行情", end_date="2026-01-05")
    assert json.loads(state["requests"][-2][2].decode()) == {"end_date": "2026-01-05"}

    state["responses"] = [
        (200, []), (200, [_conventional_config()]),
        (202, {"task_id": "d5"}), (200, {"status": "SUCCESS", "data": {}}),
    ]
    client.paper_trading.delete_signals("2026行情", start_date="2026-01-05")
    assert json.loads(state["requests"][-2][2].decode()) == {"start_date": "2026-01-05"}
