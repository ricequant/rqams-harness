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

    def __init__(self, single_error=None, batch_error=False, remaining=80):
        """准备一只已就绪和一只缺项产品，并记录对外可见的业务结果。"""
        self.args = SimpleNamespace(deadline=90, include_settled_reference=False)
        self.data = {"sections": {}, "problems": []}
        self.batches = 0
        self.single_reads = []
        self.remaining_seconds = remaining
        self.single_error = single_error
        self.batch_error = batch_error
        self.client = SimpleNamespace(timeout=30, wait_timeout=300, _resources={}, _resource_detail_cache={})
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
        """首轮缺项，后续批量可返回全量，用于捕获不允许的重新等待。"""
        if isinstance(resource, list):
            self.batches += 1
            if self.batches > 1:
                return {identifier: self.snapshot(100) for identifier in resource}
            result = {"ready": self.snapshot(100)}
            if self.batch_error:
                result["error_messages"] = {"pending": "估值输入缺失"}
            else:
                result["pending_valuation"] = ["pending"]
            return result
        self.single_reads.append(resource)
        if self.single_error:
            raise self.single_error
        return self.snapshot(200)


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    """只加速旧编排外层 sleep，不改变 SDK 协议或调用结局。"""
    monkeypatch.setattr(SCALE, "time", SimpleNamespace(monotonic=time.monotonic, sleep=lambda _: None))


def test_summary_timeout_preserves_partial_and_diagnostics():
    """单读已超时不能再批量重试变成全量，且必须交付错误详情。"""
    details = {"task_id": "original-task", "response": {"message": "snapshot pending"}}
    ctx = ScaleContext(HarnessError("wait_timeout", "等待超时", details=details))
    SCALE.collect(ctx)
    sections = ctx.data["sections"]
    assert sections["coverage"]["ready"] == 1
    assert sections["totals"]["equity_sum"] is None
    row = next(row for row in sections["rows"] if row["id"] == "pending")
    assert row["status"] == "pending"
    assert row["detail"]["single_read"]["error"]["details"] == details
    assert row["detail"]["single_read"]["seconds"] >= 0
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
    assert "pending" not in ctx.single_reads


def test_single_summary_success_merges_same_day_amounts():
    """后续单读成功可补入同日小计，不覆盖首轮已取得值。"""
    ctx = ScaleContext()
    SCALE.collect(ctx)
    sections = ctx.data["sections"]
    assert sections["coverage"]["complete"]
    assert sections["totals"]["equity_sum"] == 300
    assert sections["coverage"]["batch_rows"] == 1
    assert sections["coverage"]["single_rows"] == 1


def test_insufficient_budget_is_not_a_product_failure():
    """剩余预算不足跳过单读，应报告未充分等待，而非产品失败。"""
    ctx = ScaleContext(remaining=1)
    SCALE.collect(ctx)
    row = next(row for row in ctx.data["sections"]["rows"] if row["id"] == "pending")
    assert row["status"] == "pending"
    assert row["detail"]["single_read"]["skipped"]
    assert row["detail"]["next_steps"]
    assert not ctx.single_reads
    assert ctx.batches == 1


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
            ctx.remaining_seconds = SCALE.DIAGNOSIS_RESERVE
        finally:
            release.set()
        assert first.result()['response']['id'] == 'p1'
        assert second.result()['skipped']
    assert len(state['requests']) == 1
    assert client.call('GET', 'products/p1')['id'] == 'p1'


def test_sdk_summary_202_then_success_preserves_result(service):
    """真实 SDK 内部处理 202，成功产物保留业务日期与净资产。"""
    client, state = service
    state['catalog'] = catalog_routes(products=[{'id': 'p1', 'name': 'p1'}])
    state['responses'] = [(202, {'message': '实时产物准备中'}), (200, {
        'date': '2026-11-09', 'total_equity': 250, 'update_time': '2026-11-09 15:00:00'})]
    ctx = ScaleContext()
    ctx.client = client
    result = SCALE._probe(ctx, lambda bounded: {'values': bounded.balances.get('p1', fields=list(SCALE.FIELDS))})
    assert result['values']['date'] == '2026-11-09'
    assert result['values']['total_equity'] == 250
    assert client.call('GET', 'products/p1')['id'] == 'p1'


def test_sdk_resource_resolution_and_summary_share_one_deadline(service, monkeypatch):
    """资源解析耗时计入同一次等待，不能在业务调用时重新获得预算。"""
    client, state = service
    state['catalog'] = catalog_routes(products=[{'id': 'p1', 'name': 'p1'}])
    original_timeout = client.wait_timeout
    clock = [time.monotonic()]
    monkeypatch.setattr(SCALE.time, 'monotonic', lambda: clock[0])

    def slow_detail(path):
        """解析阶段推进本项时钟，确定性耗尽预算而不依赖网络超时竞态。"""
        if path == 'products/p1':
            clock[0] += 20

    state['hold'] = slow_detail
    state['responses'] = [(200, {'date': '2026-11-09', 'total_equity': 250})]
    ctx = ScaleContext(remaining=SCALE.DIAGNOSIS_RESERVE + 10)
    ctx.client = client
    result = SCALE._probe(ctx, lambda bounded: {'values': bounded.balances.get('p1', fields=list(SCALE.FIELDS))})
    assert result['error']['code'] == 'wait_timeout'
    assert not any('/asset_snapshot_summary' in request[1] for request in state['requests'])
    assert client.wait_timeout == original_timeout


@pytest.mark.parametrize('payload', [
    {'date': None, 'total_equity': 200},
    {'date': '2026-11-09', 'total_equity': None},
    {'date': '2026-11-09', 'total_equity': float('nan')},
])
def test_single_summary_incomplete_200_never_becomes_complete(payload):
    """200 但缺日期或金额时交付缺口，不补值或继续外层重试。"""
    ctx = ScaleContext()
    original = ctx.balances

    def incomplete(resource, **kwargs):
        """批量保持正常响应，单读保留缺失值。"""
        return original(resource, **kwargs) if isinstance(resource, list) else payload

    ctx.client.balances.get = incomplete
    SCALE.collect(ctx)
    assert ctx.data['sections']['coverage']['missing_fields'] == 1
    assert ctx.data['sections']['totals']['equity_sum'] is None
    assert ctx.batches == 1


def test_network_failure_and_summary_diagnostics_reach_report():
    """连接失败不归因产品计算，交付报告必须包含原因与排查路径。"""
    ctx = ScaleContext(HarnessError('transport_error', 'connection reset', details={'response': None}))
    SCALE.collect(ctx)
    row = next(row for row in ctx.data['sections']['rows'] if row['id'] == 'pending')
    assert row['status'] == 'pending'
    assert '网络' in row['detail']['next_steps'][0]
    report = SCALE.render(ctx.data)
    assert 'connection reset' in report
    assert 'transport_error' in report
    assert '## 排查方案' in report
    assert ctx.batches == 1
