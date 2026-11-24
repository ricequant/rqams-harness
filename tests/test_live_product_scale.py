"""规模案例等待截止、错误终态与诊断交付的行为回归。"""

import importlib.util
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError
from rqamsh.resources import balances as balance_module
from rqamsh.transport import cap_request_deadline

DEMO = Path(__file__).resolve().parents[1] / "docs" / "demo"
SPEC = importlib.util.spec_from_file_location("scale_case_wait", DEMO / "live-product-scale" / "run.py")
SCALE = importlib.util.module_from_spec(SPEC)
IMPORT_PATH = sys.path[:]
try:
    SPEC.loader.exec_module(SCALE)
finally:
    sys.path[:] = IMPORT_PATH


class ScaleContext:
    """隔离案例业务编排，真实 SDK 的协议另用本机 HTTP 烟测验证。"""

    def __init__(self, batch_error=False, remaining=80):
        """准备一只已就绪和一只缺项产品。"""
        self.args = SimpleNamespace(deadline=90, include_settled_reference=False)
        self.data = {"sections": {}, "problems": []}
        self.batches = 0
        self.remaining_seconds = remaining
        self.batch_error = batch_error
        self.client = SimpleNamespace(timeout=30, wait_timeout=300, _resources={})
        self.client.products = SimpleNamespace(list=self.products, compute_state=self.compute_state)
        self.client.balances = SimpleNamespace(get=self.balances)
        self.client.market_data = SimpleNamespace(trading_dates=self.trading_dates)

    def remaining(self):
        """返回可控的整体剩余预算。"""
        return self.remaining_seconds

    def checkpoint(self):
        """不写正式文件，编排结果直接保留在 data。"""
        return None

    def problem(self, section, message):
        """登记交付缺口，不把部分结果当全量。"""
        self.data["problems"].append({"section": section, "message": message})

    def call(self, label, function):
        """隔离状态查询及业务调用，保留非预期异常供测试失败。"""
        return function()

    def parallel(self, jobs):
        """串行重放独立只读，避免时序影响业务断言。"""
        return {key: self.call(key, function) for key, function in jobs.items()}

    def products(self, **kwargs):
        """返回两只可见实盘产品。"""
        return {"products": [{"id": identifier, "name": identifier, "label": "live"}
                             for identifier in ("ready", "pending")]}

    def compute_state(self, resource):
        """历史任务正常不等于实时产物已就绪。"""
        return {"state": "normal", "execution_id": "execution-original"}

    def trading_dates(self, **kwargs):
        """给出本次查询日，不参与修补返回日期。"""
        return [kwargs["end_date"]]

    def snapshot(self, equity):
        """构造日期和资产负债可核验的正常金额。"""
        return {"date": "2026-11-09", "total_equity": equity,
                "total_assets": equity, "total_liabilities": 0,
                "update_time": "2026-11-09 14:00:00"}

    def balances(self, resource, **kwargs):
        """返回 SDK 最终截面；不接受额外的单读或批量重查。"""
        assert resource == ["ready", "pending"]
        self.batches += 1
        assert self.batches == 1
        message = "估值输入缺失" if self.batch_error else "本次等待时限内未获取到实时头寸"
        result = {"ready": self.snapshot(100), "error_messages": {"pending": message},
                  "pending_valuation": []}
        if not self.batch_error:
            result['batch_wait'] = {'timed_out_ids': ['pending'], 'message': message}
        return result


def test_batch_timeout_preserves_partial_and_diagnostics():
    """SDK 截止诊断不计为后台错误，报告给出缺口与状态证据。"""
    ctx = ScaleContext()
    SCALE.collect(ctx)
    sections = ctx.data["sections"]
    assert sections["coverage"]["ready"] == 1
    assert sections["totals"]["equity_sum"] is None
    row = next(row for row in sections["rows"] if row["id"] == "pending")
    assert row["status"] == "pending"
    assert sections["coverage"]["error"] == 0
    assert row["detail"]["compute_state"]["response"]["execution_id"] == "execution-original"
    assert "本次等待时限内未获取到实时头寸" in SCALE.render(ctx.data)
    assert row["detail"]["next_steps"]
    assert ctx.batches == 1


def test_batch_explicit_failure_cannot_be_overwritten_by_single_success():
    """明确批量失败保留为终态，不能单读覆盖成就绪。"""
    ctx = ScaleContext(batch_error=True)
    SCALE.collect(ctx)
    sections = ctx.data["sections"]
    assert sections["coverage"]["ready"] == 1
    assert sections["coverage"]["error"] == 1
    assert sections["totals"]["equity_sum"] is None
    row = next(row for row in sections["rows"] if row["id"] == "pending")
    assert row["detail"]["error"] == "估值输入缺失"


def test_server_error_with_timeout_text_is_not_an_sdk_timeout(service, monkeypatch):
    """文案相同的逐项错误与 SDK 截止缺项按来源区分。"""
    ctx = ScaleContext()
    client, state = service
    ctx.client.balances = client.balances
    client.wait_timeout = 1
    state["catalog"] = catalog_routes([{"id": i} for i in ("ready", "pending")])
    message = "本次等待时限内未获取到实时头寸"
    state["responses"] = [(200, {"error_messages": {"ready": message}})]
    monkeypatch.setattr(balance_module, "sleep", lambda _: None)
    SCALE.collect(ctx)
    rows = {row["id"]: row for row in ctx.data["sections"]["rows"]}
    assert rows["ready"]["status"] == "error"
    assert rows["pending"]["status"] == "pending"


def test_report_totals_use_one_sdk_batch_round(service, monkeypatch):
    """走真实 SDK 和 HTTP，首轮的 100 元不能混进最终报告。"""
    ctx = ScaleContext()
    client, state = service
    ctx.client.balances = client.balances
    state["catalog"] = catalog_routes([{"id": i, "name": i} for i in ("ready", "pending")])
    state["responses"] = [(200, {"ready": ctx.snapshot(100)}),
                          (200, {"ready": ctx.snapshot(120), "pending": ctx.snapshot(200)})]
    monkeypatch.setattr(balance_module, "sleep", lambda _: None)
    SCALE.collect(ctx)
    sections = ctx.data["sections"]
    assert sections["coverage"]["complete"]
    assert sections["totals"]["equity_sum"] == 320
    assert [request[0] for request in state["requests"] if request[1].endswith("asset_snapshot_summary")] == ["POST", "POST"]


def test_queued_query_does_not_restart_exhausted_budget(service):
    """真实请求排队后预算已耗尽时不得发起第二次查询，共享连接仍可用。"""
    client, state = service
    state['catalog'] = catalog_routes(products=[{'id': 'p1', 'name': 'p1'}])
    entered, release = threading.Event(), threading.Event()

    def hold_detail(path):
        """暂停首项请求，让第二项真实进入线程池队列。"""
        if path == 'products/p1':
            entered.set()
            assert release.wait(5)

    state['hold'] = hold_detail
    ctx = ScaleContext()
    ctx.client = client

    def query(bounded):
        """经真实 SDK 发起独立只读查询。"""
        return {'response': bounded.call('GET', 'products/p1')}

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(SCALE._probe, ctx, query)
        second = pool.submit(SCALE._probe, ctx, query)
        try:
            assert entered.wait(5)
            ctx.remaining_seconds = 0
        finally:
            release.set()
        assert first.result()['response']['id'] == 'p1'
        assert second.result()['skipped']
    assert len(state['requests']) == 1
    assert client.call('GET', 'products/p1')['id'] == 'p1'


def test_batch_wait_leaves_budget_for_requested_settled_reference(monkeypatch):
    """批量耗尽分配预算后，仍读取独立结算参考，不用参考金额补实时。"""
    ctx = ScaleContext(remaining=170)
    ctx.args.include_settled_reference = True
    clock = [100.0]
    monkeypatch.setattr(SCALE, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    ctx.remaining = lambda: max(0.0, 270 - clock[0])

    def wait_for_batch(resource, **kwargs):
        """模拟批量 SDK 等到分配的截止后交付部分截面。"""
        clock[0] = cap_request_deadline(270)
        assert clock[0] - 100 >= 120  # 诊断预算不能重复占用批量等待时间。
        return ctx.balances(resource, **kwargs)

    def reference(resource):
        """模拟得到两个产品的上一交易日参考。"""
        return {identifier: ctx.snapshot(200) for identifier in resource}

    def status(_):
        """模拟最后一项计算状态查询耗尽诊断预算。"""
        clock[0] = cap_request_deadline(270)
        raise HarnessError('wait_timeout', '状态查询未完成')

    ctx.client.balances = SimpleNamespace(get=wait_for_batch, previous_summaries=reference)
    ctx.client.products.compute_state = status
    SCALE.collect(ctx)
    sections = ctx.data['sections']
    assert len(sections['settled_reference']['rows']) == 2
    assert sections['coverage']['ready'] == 1
    assert sections['totals']['equity_sum'] is None
    assert ctx.remaining() > 0


def test_optional_settled_reference_preserves_short_realtime_budget(monkeypatch):
    """短预算下先完成实时读取，不能因勾选结算参考而失去首轮截面。"""
    ctx = ScaleContext(remaining=17)
    ctx.args.include_settled_reference = True
    monkeypatch.setattr(SCALE.time, 'monotonic', lambda: 100.0)

    def read_batch(resource, **kwargs):
        """把至少一秒的首轮读取视为完成，并保留批次级任务诊断。"""
        assert cap_request_deadline(117.0) >= 101.0
        result = ctx.balances(resource, **kwargs)
        result['batch_wait']['task_id'] = 'round2'
        return result

    ctx.client.balances.get = read_batch
    ctx.remaining = lambda: 17.0 if not ctx.batches else 9.0
    SCALE.collect(ctx)
    assert ctx.data['sections']['coverage']['ready'] == 1
    assert 'round2' in SCALE.render(ctx.data)


def test_sdk_resource_resolution_and_batch_share_one_deadline(service, monkeypatch):
    """批量解析耗尽预算后不能另起业务请求或改变客户端配置。"""
    from rqamsh import client as client_module

    client, state = service
    state['catalog'] = catalog_routes(products=[{'id': 'p1', 'name': 'p1'}])
    original_timeout = client.wait_timeout
    clock = [time.monotonic()]
    monkeypatch.setattr(balance_module, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(client_module, 'monotonic', lambda: clock[0])

    def slow_listing(path):
        """解析阶段推进本项时钟，确定性耗尽预算而不依赖网络超时竞态。"""
        if path == 'products':
            clock[0] += 20

    state['hold'] = slow_listing
    state['responses'] = [(200, {'date': '2026-11-09', 'total_equity': 250})]
    with SCALE.request_deadline(clock[0] + 10), pytest.raises(HarnessError) as error:
        client.balances.get(['p1'], fields=list(SCALE.FIELDS))
    assert error.value.code == 'wait_timeout'
    assert not any('/asset_snapshot_summary' in request[1] for request in state['requests'])
    assert client.wait_timeout == original_timeout


@pytest.mark.parametrize('payload', [
    {'date': None, 'total_equity': 200},
    {'date': '2026-11-09', 'total_equity': None},
    {'date': '2026-11-09', 'total_equity': float('nan')},
])
def test_batch_incomplete_200_never_becomes_complete(payload):
    """200 但缺日期或金额时交付缺口，不补值或继续外层重试。"""
    ctx = ScaleContext()

    def incomplete(resource, **kwargs):
        """第二只已返回但字段不足，不能标为就绪或续查。"""
        assert resource == ["ready", "pending"]
        ctx.batches += 1
        return {"ready": ctx.snapshot(100), "pending": payload}

    ctx.client.balances.get = incomplete
    SCALE.collect(ctx)
    assert ctx.data['sections']['coverage']['missing_fields'] == 1
    assert ctx.data['sections']['totals']['equity_sum'] is None
    assert ctx.batches == 1


def test_network_failure_during_status_diagnosis_reaches_report():
    """状态补查失败不把实时缺项改成产品失败，报告保留原因。"""
    ctx = ScaleContext()

    def broken_status(_):
        """模拟状态查询连接断开。"""
        raise HarnessError('transport_error', 'connection reset')

    ctx.client.products.compute_state = broken_status
    SCALE.collect(ctx)
    row = next(row for row in ctx.data['sections']['rows'] if row['id'] == 'pending')
    assert row['status'] == 'pending'
    report = SCALE.render(ctx.data)
    assert 'connection reset' in report
    assert row['detail']['compute_state']['error']['code'] == 'transport_error'
    assert '## 排查方案' in report
    assert ctx.batches == 1
