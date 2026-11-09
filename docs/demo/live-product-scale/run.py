"""实盘产品规模一次快照：全量 label=live 清单、实时净资产与逐只缺口诊断。

只读演示：不创建、修改或删除任何业务数据。金额按人民币头寸口径展示，缺失保留为空、
不补零；不同业务日只给分组小计，不跨日相加。凭据只从运行环境或已保存的同一部署
身份取得，脚本不读取任何内部凭据文件。
"""

from __future__ import annotations

import math
import sys
import time
from copy import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _report_common import launch  # noqa: E402
from rqamsh.errors import HarnessError  # noqa: E402

BEIJING = timezone(timedelta(hours=8))
FIELDS = ['date', 'total_equity', 'total_assets', 'total_liabilities', 'update_time']
SCALE_FIELDS = ('date', 'total_equity', 'total_assets', 'total_liabilities')
AMOUNT_FIELDS = frozenset({'total_equity', 'total_assets', 'total_liabilities'})
TOLERANCE = 0.01
CALENDAR_DAYS = 14
DIAGNOSIS_RESERVE = 30.0
SETTLED_RESERVE = 45.0
MISSING = object()

STATUS_TEXT = {'ok': '就绪', 'missing_fields': '缺字段', 'error': '明确错误',
               'pending': '截止时未就绪', 'batch_failed': '批量失败',
               'unreconciled': '对账不一致'}
SOURCE_TEXT = {'batch': '批量截面', 'single_read': '单读回收'}
STATE_TEXT = {'complete': '完整（全部请求的实盘产品都有可用业务日期与有限净资产）',
              'partial': '部分（已取得结果按原样保留，缺口逐项列明）',
              'failed': '失败（采集未完成，缺口见文末）',
              'timeout': '超时（到达硬截止，以下仅为已落盘部分）',
              'running': '运行中（证据未达到终态）'}


def _finite(value):
    """判断是否为可用于金额判定的有限数值；布尔值不算金额。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fmt(value):
    """统一单元格格式：金额两位小数，null 与未返回分开，缺失绝不当 0。"""
    if value is MISSING:
        return '未返回'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return _clip(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f'{value:,.2f}' if math.isfinite(value) else '非有限值'
    text = ' '.join(str(value).split())
    return text.replace('|', '\\|') if text else '（空）'


def _clip(value, limit=400):
    """压缩空白并截断长文本，避免证据与表格无限膨胀。"""
    text = ' '.join(str(value).split())
    return text if len(text) <= limit else text[:limit] + '…'


def _field(values, key):
    """展示单个字段：区分未返回、null 与具体数值；金额字段统一两位小数与千分位。"""
    value = values.get(key, MISSING)
    if key in AMOUNT_FIELDS and isinstance(value, int) and not isinstance(value, bool):
        return f'{value:,.2f}'
    return _fmt(value)


def _extract(document):
    """取出本次请求的顶层字段，保留「未返回」与 null 的差别。"""
    if not isinstance(document, dict):
        return {}, list(FIELDS)
    return ({key: document[key] for key in FIELDS if key in document},
            [key for key in FIELDS if key not in document])


def _batch(ctx, sections, state, identifiers, label):
    """提交一轮批量实时截面，吸收返回并把请求差集记入证据。"""
    started = time.monotonic()
    result = ctx.call(label, lambda: ctx.client.balances.get(list(identifiers), fields=list(FIELDS)))
    record = {'label': label, 'requested': len(identifiers), 'error': None, 'returned': [],
              'errors': {}, 'pending': [], 'unaccounted': [], 'anomalies': [],
              'consistent': False, 'seconds': round(time.monotonic() - started, 3)}
    sections['batch']['attempts'].append(record)
    if not isinstance(result, dict):
        record['error'] = '批量截面未返回资源映射'
        return record
    returned = [str(key) for key in result if key not in {'error_messages', 'pending_valuation'}]
    raw_errors = result.get('error_messages')
    errors = {str(key): _clip(value) for key, value in raw_errors.items()} \
        if isinstance(raw_errors, dict) else {}
    raw_pending = result.get('pending_valuation')
    pending = [str(item) for item in raw_pending] if isinstance(raw_pending, list) else []
    requested = [str(item) for item in identifiers]
    requested_set = set(requested)
    unaccounted = [item for item in requested
                   if item not in returned and item not in errors and item not in pending]
    anomalies = []
    if unaccounted:
        anomalies.append(f"未解释差集 {len(unaccounted)} 项：{', '.join(unaccounted[:10])}")
    if [item for item in returned if item in errors]:
        anomalies.append('返回项同时出现在明确错误中')
    if [item for item in returned if item in pending]:
        anomalies.append('返回项同时出现在未就绪中')
    if [item for item in errors if item in pending]:
        anomalies.append('明确错误项同时出现在未就绪中')
    if [item for item in [*errors, *pending] if item not in requested_set]:
        anomalies.append('错误或未就绪项不属于本次请求')
    if [item for item in returned if item not in requested_set]:
        anomalies.append('返回项不属于本次请求')
    if len(set(returned)) != len(returned) or len(set(pending)) != len(pending):
        anomalies.append('返回或未就绪项存在重复 ID')
    record.update({'returned': returned, 'errors': errors, 'pending': pending,
                   'unaccounted': unaccounted, 'anomalies': anomalies,
                   'consistent': not anomalies})
    for identifier in returned:
        if identifier not in requested_set:
            continue
        values, missing = _extract(result.get(identifier))
        state['values'][identifier] = values
        state['missing'][identifier] = missing
        state['source'][identifier] = 'batch'
        state['errors'].pop(identifier, None)
    for identifier, message in errors.items():
        if identifier in requested_set and identifier not in state['values']:
            state['errors'][identifier] = message
    state['pending'] = [item for item in identifiers
                        if item not in state['values'] and item not in state['errors']]
    return record


def _universe(ctx, sections):
    """读取可见产品，严格按 label=live 取唯一 ID，不按产品状态或金额筛选。"""
    section = {'source': "products.list(fields=['id','name','label','product_state'])",
               'requested_ids': [], 'by_id': {}}
    sections['universe'] = section
    result = ctx.call('products.list', lambda: ctx.client.products.list(
        fields=['id', 'name', 'label', 'product_state']))
    if not isinstance(result, dict) or not isinstance(result.get('products'), list):
        section['error'] = '产品清单未返回数组'
        ctx.problem('universe', '产品清单未返回数组，无法确定实盘范围')
        return section
    rows = [row for row in result['products'] if isinstance(row, dict)]
    live = [row for row in rows if row.get('label') == 'live' and row.get('id')]
    unlabeled = [str(row['id']) for row in rows if row.get('id') and row.get('label') is None]
    section.update({
        'visible_total': result.get('total', len(rows)),
        'excluded_count': sum(1 for row in rows if row.get('label') not in (None, 'live')),
        'unlabeled_count': len(unlabeled), 'unlabeled_sample': unlabeled[:20],
        'live_count': len({str(row['id']) for row in live}),
        'requested_ids': list(dict.fromkeys(str(row['id']) for row in live)),
    })
    for row in reversed(live):
        section['by_id'][str(row['id'])] = {'name': row.get('name'),
                                            'product_state': row.get('product_state')}
    if unlabeled:
        ctx.problem('universe', f'{len(unlabeled)} 只产品未返回 label，无法确认实盘口径，未纳入范围')
    if not section['requested_ids']:
        section['note'] = '当前空间没有 label=live 的可见产品；本次没有规模数据，不是 0 元'
    return section


def _latest_day(ctx, sections, today):
    """按北京时间当天读交易所日历，给出最新可用交易日参照。"""
    start = (today - timedelta(days=CALENDAR_DAYS)).isoformat()
    dates = ctx.call('market_data.trading_dates', lambda: ctx.client.market_data.trading_dates(
        type='exchange', start_date=start, end_date=today.isoformat()))
    days = sorted({str(item) for item in dates if isinstance(item, str) and item}) \
        if isinstance(dates, list) else []
    sections['calendar'] = {'today_beijing': today.isoformat(), 'window': [start, today.isoformat()],
                            'latest_trading_day': days[-1] if days else None}
    if not days:
        sections['calendar']['error'] = '交易所日历未返回可用交易日'
        ctx.problem('calendar', '交易所日历未返回可用交易日，最新可用交易日无法核对')
        return None
    return days[-1]


def _probe(ctx, call):
    """按启动时剩余预算等待一次，隔离超时配置并保留原始诊断。"""
    budget = min(ctx.client.wait_timeout, max(0.0, ctx.remaining() - DIAGNOSIS_RESERVE))
    if not budget:
        return {'skipped': '剩余预算不足，未执行本次查询',
                'seconds': 0.0, 'wait_budget_seconds': 0.0}
    client = copy(ctx.client)
    client._resources = {}
    client._resource_detail_cache = dict(ctx.client._resource_detail_cache)
    client.timeout = min(ctx.client.timeout, budget)
    client.wait_timeout = budget
    started = time.monotonic()
    deadline = started + budget

    def bounded_call(method, path, **kwargs):
        """资源解析与结果查询共享截止，不为每个底层调用重置预算。"""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HarnessError('wait_timeout', '本次单产品查询等待预算已耗尽')
        request_client = copy(client)
        request_client.wait_timeout = min(budget, remaining)
        request_client.timeout = min(ctx.client.timeout, remaining)
        return type(client).call(request_client, method, path, **kwargs)

    client.call = bounded_call
    try:
        result = call(client)
    except Exception as exc:
        result = {'error': {'message': _clip(str(exc)),
                            'code': getattr(exc, 'code', None),
                            'status': getattr(exc, 'status', None),
                            'details': getattr(exc, 'details', None)}}
    result.update(seconds=round(time.monotonic() - started, 3),
                  wait_budget_seconds=round(budget, 3))
    return result


def _diagnose(ctx, targets, state, identifiers):
    """缺项只做一次单产品自动等待和状态查询，结束后保留结果与诊断。"""
    jobs = {}
    for identifier in targets:
        jobs[f'state:{identifier}'] = (
            lambda item=identifier: _probe(
                ctx, lambda client: {'response': client.products.compute_state(item)}))
        jobs[f'read:{identifier}'] = (
            lambda item=identifier: _probe(
                ctx, lambda client: {'values': _extract(
                    client.balances.get(item, fields=list(FIELDS)))[0]}))
    results = ctx.parallel(jobs)
    for identifier in targets:
        detail = {'compute_state': results.get(f'state:{identifier}'),
                  'single_read': results.get(f'read:{identifier}')}
        if identifier in state['errors']:
            detail['batch_error'] = state['errors'][identifier]
        single = detail['single_read']
        values = single.get('values') if isinstance(single, dict) else None
        error = single.get('error') if isinstance(single, dict) else None
        if isinstance(values, dict):
            state['values'][identifier] = values
            state['missing'][identifier] = [key for key in FIELDS if key not in values]
            state['source'][identifier] = 'single_read'
            date = values.get('date')
            ready = isinstance(date, str) and bool(date.strip()) and _finite(values.get('total_equity'))
            detail['outcome'] = ('单产品同口径读取取得可用业务日期与有限净资产' if ready
                                 else '单产品已返回，但缺可用业务日期或有限净资产，停止重复查询')
        elif isinstance(error, dict):
            detail['outcome'] = _clip(error.get('message'))
            # 超时和连接失败仅结束本次采集，不认定服务端计算失败，也不再外层重试。
            if error.get('code') not in ('transport_error', 'wait_timeout'):
                state['errors'][identifier] = _clip(error.get('message'))
        elif isinstance(single, dict):
            detail['outcome'] = _clip(single.get('skipped') or '未取得结果')
        state['detail'][identifier] = detail
    state['pending'] = [item for item in identifiers
                        if item not in state['values'] and item not in state['errors']]


def _next_steps(status, detail):
    """根据实际停止原因给出只读排查路径，不推断故障根因或自动重算。"""
    if status == 'ok':
        return []
    single = detail.get('single_read') or {}
    error = single.get('error') or {}
    compute = (detail.get('compute_state') or {}).get('response')
    compute = compute if isinstance(compute, dict) else {}
    if single.get('skipped'):
        return ['本次剩余预算不足，未充分等待；重新查询同一产品实时结果，不能据此认定产品异常。']
    if error.get('code') == 'transport_error':
        return ['先核对目标部署的网络连通性与错误详情；连接失败不能认定产品计算异常。']
    if status == 'batch_failed':
        return ['保留批量错误原文，按其提示核对连接、权限或请求；本次不拆成逐只查询碰运气。']
    if status == 'missing_fields':
        return ['核对本次返回字段和业务日期；缺失或 null 不补零，不用其他日期的结果替代。',
                '若持续缺字段，向管理员提供产品 ID、查询时间、字段投影与原始响应。']
    if compute.get('state') == 'computing':
        return ['查看原历史估值任务进度并保留 execution_id，不重复提交重算。']
    if compute.get('state') == 'normal' and status == 'pending':
        return ['历史估值状态正常但实时结果仍未取得；请管理员检查实时产物准备链路及其依赖输入。',
                '提供产品 ID、查询时间、等待耗时与最后响应；超时不代表服务端失败或取消。']
    return ['保留错误原文与执行标识，按提示核对产品起止日期、最近导入和必要输入，不凭超时认定配置错误。',
            '持续无法取得结果时将产品 ID、查询时间及诊断详情交管理员排查；补输入、改配置或重算须另行授权。']


def _row(identifier, meta, state, latest):
    """构造逐只记录：区分就绪、缺字段与未取得，保留结构化诊断。"""
    detail = dict(state['detail'].get(identifier) or {})
    source = state['source'].get(identifier)
    if identifier in state['values']:
        values = state['values'][identifier]
        missing = state['missing'].get(identifier) or []
        date = values.get('date')
        date_ok = isinstance(date, str) and bool(date.strip())
        equity_ok = _finite(values.get('total_equity'))
        identity = None
        if equity_ok and _finite(values.get('total_assets')) \
                and _finite(values.get('total_liabilities')):
            identity = values['total_assets'] - values['total_liabilities'] - values['total_equity']
        detail['identity_diff'] = identity
        status = 'ok' if (date_ok and equity_ok) else 'missing_fields'
    else:
        values, missing, date, status = {}, list(FIELDS), None, 'unreconciled'
        if identifier in state['errors']:
            status, detail['error'] = 'error', state['errors'][identifier]
        elif state.get('batch_failed'):
            status = 'batch_failed'
        elif identifier in state['pending']:
            status = 'pending'
    detail['next_steps'] = _next_steps(status, detail)
    return {'id': identifier, 'name': meta.get('name'),
            'product_state': meta.get('product_state'), 'date': date, 'values': values,
            'missing': missing, 'source': source, 'status': status, 'detail': detail}


def _aggregate(identifiers, rows, latest):
    """按业务日期分组小计，并判定能否称同日全量总额。"""
    buckets, undated = {}, []
    for row in rows:
        equity = row['values'].get('total_equity')
        if not _finite(equity):
            continue
        if not (isinstance(row['date'], str) and row['date']):
            undated.append({'id': row['id'], 'equity': equity})
            continue
        bucket = buckets.setdefault(row['date'], {'ids': [], 'sum': 0.0, 'assets': 0,
                                                  'liabilities': 0, 'identity': 0,
                                                  'non_positive': 0})
        bucket['ids'].append(row['id'])
        bucket['sum'] += equity
        bucket['assets'] += _finite(row['values'].get('total_assets'))
        bucket['liabilities'] += _finite(row['values'].get('total_liabilities'))
        bucket['non_positive'] += equity <= 0
        diff = row['detail'].get('identity_diff')
        bucket['identity'] += _finite(diff) and abs(diff) > TOLERANCE
    groups = []
    for date in sorted(buckets, key=lambda value: (value is None, value or '')):
        bucket, count = buckets[date], len(buckets[date]['ids'])
        notes = []
        if bucket['assets'] != count or bucket['liabilities'] != count:
            notes.append(f"资产负债覆盖 {min(bucket['assets'], bucket['liabilities'])}/{count}，"
                         '恒等式仅逐只核验')
        if bucket['non_positive']:
            notes.append(f"含零或负净资产 {bucket['non_positive']} 只")
        groups.append({'date': date, 'rows': count, 'equity_sum': round(bucket['sum'], 2),
                       'assets_covered': bucket['assets'],
                       'liabilities_covered': bucket['liabilities'],
                       'identity_mismatch': bucket['identity'],
                       'note': '；'.join(notes) or None})
    ready = sum(1 for row in rows if row['status'] == 'ok')
    coverage = {'requested': len(identifiers), 'ready': ready,
                'batch_rows': sum(1 for row in rows
                                  if row['status'] == 'ok' and row['source'] == 'batch'),
                'single_rows': sum(1 for row in rows
                                   if row['status'] == 'ok' and row['source'] == 'single_read'),
                'complete': bool(identifiers) and ready == len(identifiers)}
    for status in ('error', 'pending', 'batch_failed', 'missing_fields', 'unreconciled'):
        coverage[status] = sum(1 for row in rows if row['status'] == status)
    dates = [group['date'] for group in groups if group['date']]
    same_day = coverage['complete'] and len(dates) == 1
    totals = {'same_day': same_day, 'dates': dates, 'latest_trading_day': latest,
              'equity_sum': groups[0]['equity_sum'] if same_day else None,
              'latest_match': (dates[0] == latest) if same_day and latest else None,
              'undated': {'ids': [item['id'] for item in undated],
                          'equity_sum': round(sum((item['equity'] for item in undated), 0.0), 2)},
              'non_positive': [row['id'] for row in rows
                               if _finite(row['values'].get('total_equity'))
                               and row['values']['total_equity'] <= 0],
              'identity_mismatch': [row['id'] for row in rows
                                    if _finite(row['detail'].get('identity_diff'))
                                    and abs(row['detail']['identity_diff']) > TOLERANCE]}
    return groups, coverage, totals


def _summary(sections):
    """最多三条重点摘要；缺数据时直接说明缺口而不是给结论。"""
    universe = sections.get('universe') or {}
    coverage = sections.get('coverage') or {}
    totals = sections.get('totals') or {}
    requested = coverage.get('requested', 0)
    if not requested:
        if universe.get('error'):
            return ['未取得实盘清单：本次范围无法确定，规模数据为空（缺失不等于 0 元）。']
        return ['当前空间没有 label=live 的可见产品；本次没有规模数据，不是 0 元。']
    items = [f"范围：可见 {universe.get('visible_total', '未返回')} 只产品中 label=live "
             f"{universe.get('live_count', requested)} 只，按产品 ID 去重后全部纳入，"
             '未按封账、到期、零值或负值筛选。',
             f"就绪 {coverage['ready']}/{requested}（批量 {coverage['batch_rows']}、"
             f"单读回收 {coverage['single_rows']}）；明确错误 {coverage['error']}、"
             f"截止时未就绪 {coverage['pending']}、批量失败 {coverage['batch_failed']}、"
             f"对账不一致 {coverage['unreconciled']}。"]
    if totals.get('same_day'):
        items.append(f"全部就绪项同为业务日 {totals['dates'][0]}，净资产合计 "
                     f"{_fmt(totals.get('equity_sum'))} 元（人民币头寸口径），"
                     '可称该业务日实盘总额，范围仅限当前空间可见产品。')
    else:
        items.append(f"不能称同日全量总额：就绪 {coverage['ready']}/{requested}、"
                     f"业务日 {len(totals.get('dates') or [])} 个，按业务日期分组小计，不跨日相加。")
    return items[:3]


def _register_gaps(ctx, sections):
    """把真实缺口登记为问题，让终态反映缺项而不是把缺值写成零。"""
    coverage = sections.get('coverage') or {}
    labels = {'error': '返回明确错误，已停止等待', 'pending': '本次单产品读取结束仍未就绪，排查方案见逐项诊断',
              'batch_failed': '因批量整体失败没有逐只结果',
              'missing_fields': '已返回记录但缺可用业务日期或有限净资产',
              'unreconciled': '未返回且未列入错误或未就绪，对账不一致'}
    for status, text in labels.items():
        if coverage.get(status):
            ctx.problem('coverage', f"{coverage[status]} 只产品{text}")
    for attempt in sections['batch']['attempts']:
        if attempt['anomalies']:
            ctx.problem('batch', f"{attempt['label']} 请求与返回差集不一致："
                                 + '；'.join(attempt['anomalies']))
            break


def collect(ctx):
    """先批量采集，再由 SDK 自动等待缺项单产品，结束后交付诊断。"""
    sections, stages = ctx.data['sections'], []
    sections['meta'] = {
        'requested_at_beijing': datetime.now(BEIJING).isoformat(timespec='seconds'),
        'deadline_seconds': getattr(ctx.args, 'deadline', None),
        'fields': list(FIELDS),
        'include_settled_reference': bool(getattr(ctx.args, 'include_settled_reference', False)),
        'money_unit': '人民币头寸口径（元）；未核验产品记账币种与汇率设置',
    }
    sections['stages'] = stages
    started = time.monotonic()
    latest = _latest_day(ctx, sections, datetime.now(BEIJING).date())
    stages.append({'stage': '交易日历核对', 'seconds': round(time.monotonic() - started, 3)})
    started = time.monotonic()
    universe = _universe(ctx, sections)
    stages.append({'stage': '实盘清单', 'seconds': round(time.monotonic() - started, 3)})
    identifiers = universe['requested_ids']
    state = {'values': {}, 'missing': {}, 'source': {}, 'errors': {}, 'pending': [],
             'batch_failed': False, 'detail': {}}

    def publish():
        """按当前状态重建逐只清单与小计判定，并立即原子落盘。"""
        rows = [_row(item, universe['by_id'].get(item) or {}, state, latest)
                for item in identifiers]
        groups, coverage, totals = _aggregate(identifiers, rows, latest)
        sections.update({'rows': rows, 'groups': groups, 'coverage': coverage,
                         'totals': totals})
        sections['summary'] = _summary(sections)
        ctx.checkpoint()

    if not identifiers:
        publish()
        return None
    sections['batch'] = {'fields': list(FIELDS), 'attempts': []}
    started = time.monotonic()
    record = _batch(ctx, sections, state, identifiers, 'balances.batch-realtime')
    stages.append({'stage': '批量实时截面', 'seconds': round(time.monotonic() - started, 3)})
    if record['error'] and not state['errors']:
        # 批量整体失败：保留原文，不逐只重复同一请求，也不把缺项写成 0。
        state['batch_failed'] = True
        publish()
        _register_gaps(ctx, sections)
        return None
    publish()
    if getattr(ctx.args, 'include_settled_reference', False):
        started = time.monotonic()
        _settled(ctx, sections, identifiers, universe)
        stages.append({'stage': '最近结算参考', 'seconds': round(time.monotonic() - started, 3)})
        ctx.checkpoint()
    targets = [item for item in identifiers
               if item not in state['values'] and item not in state['errors']]
    if targets:
        started = time.monotonic()
        _diagnose(ctx, targets, state, identifiers)
        stages.append({'stage': '缺项单产品自动等待与诊断', 'seconds': round(time.monotonic() - started, 3)})
        publish()
    publish()
    _register_gaps(ctx, sections)
    return None


def _settled(ctx, sections, identifiers, universe):
    """另读上一交易日概览作为最近结算参考，单独成表、不并入实时小计。"""
    section = {'enabled': True, 'note': '概览日期由服务端上一交易日规则决定；不并入实时小计'}
    sections['settled_reference'] = section
    if ctx.remaining() < SETTLED_RESERVE:
        section['skipped'] = '剩余预算不足，未读取最近结算参考'
        ctx.problem('settled', section['skipped'])
        return
    result = ctx.call('balances.previous_summaries',
                      lambda: ctx.client.balances.previous_summaries(list(identifiers)))
    if not isinstance(result, dict):
        section['error'] = '上一交易日概览未返回资源映射'
        return
    raw_errors = result.get('error_messages')
    errors = {str(key): _clip(value) for key, value in raw_errors.items()} \
        if isinstance(raw_errors, dict) else {}
    rows = []
    for identifier in identifiers:
        if identifier not in result:
            continue
        values, missing = _extract(result[identifier])
        rows.append({'id': identifier, 'name': (universe['by_id'].get(identifier) or {}).get('name'),
                     'values': values, 'missing': missing,
                     'status': 'ok' if _finite(values.get('total_equity')) else 'missing_fields'})
    unavailable = [item for item in identifiers
                   if item not in {row['id'] for row in rows} and item not in errors]
    section.update({'requested': len(identifiers), 'rows': rows, 'errors': errors,
                    'unavailable': unavailable})
    if errors or unavailable:
        ctx.problem('settled', f"上一交易日概览：明确错误 {len(errors)} 项、未就位 "
                               f"{len(unavailable)} 项")


def _table(headers, rows):
    """拼出 Markdown 表格行，单元格文本由调用方格式化。"""
    return ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)] + [
        '| ' + ' | '.join(row) + ' |' for row in rows]


def _diagnosis(row, latest):
    """把结构化诊断拼成一段可读说明，不把未就绪说成零或已删除。"""
    values, detail, status = row['values'], row['detail'], row['status']
    parts = []
    if status == 'error':
        parts = ['服务端原文：' + _clip(detail.get('error')),
                 '明确错误：已停止对该项的等待']
    elif status == 'batch_failed':
        parts = ['批量请求整体失败，没有逐只结果；原文见对账章节']
    elif status == 'pending':
        parts = ['本次单产品读取结束仍未取得结果；已停止外层重试，不能据此认定服务端失败']
    elif status == 'unreconciled':
        parts = ['既未返回也未列入错误或未就绪；批量对账不一致']
    else:
        date = values.get('date')
        if not isinstance(date, str) or not date:
            parts.append('未返回可用业务日期，不能据此确认业务归属日')
        elif isinstance(latest, str) and date < latest:
            parts.append(f'业务日期早于交易所日历最新交易日 {latest}，按返回值记录')
        elif isinstance(latest, str) and date > latest:
            parts.append('业务日期晚于交易所日历最新交易日（夜盘可能归属下一交易日），按返回值记录')
        diff = detail.get('identity_diff')
        if not _finite(diff):
            parts.append('总资产/总负债/净资产未同时返回，恒等式未核验')
        elif abs(diff) > TOLERANCE:
            parts.append(f'总资产−总负债−净资产={diff:,.2f}，超过 {TOLERANCE} 容差')
        if not _finite(values.get('total_equity')):
            parts.append('净资产为 null、未返回或非有限值，不计入规模小计')
    scale_missing = [field for field in row['missing'] if field in SCALE_FIELDS]
    if scale_missing and status in {'ok', 'missing_fields'}:
        parts.append('规模字段未返回：' + '、'.join(scale_missing))
    if detail.get('outcome'):
        parts.append(detail['outcome'])
    if row['source'] == 'single_read' and detail.get('batch_error'):
        parts.append('批量阶段曾报错：' + _clip(detail['batch_error']))
    single = detail.get('single_read')
    if isinstance(single, dict):
        parts.append('单产品查询耗时 {} 秒，等待预算 {} 秒'.format(
            _fmt(single.get('seconds', MISSING)), _fmt(single.get('wait_budget_seconds', MISSING))))
        error = single.get('error')
        if isinstance(error, dict):
            parts.append('查询错误码：' + _fmt(error.get('code', MISSING)))
            diagnostics = error.get('details')
            if isinstance(diagnostics, dict):
                parts.append('最后诊断：' + _clip(diagnostics))
    compute = detail.get('compute_state')
    if isinstance(compute, dict):
        response = compute.get('response')
        if isinstance(response, dict):
            parts.append('计算状态：state={}，execution_id={}'.format(
                _fmt(response.get('state', MISSING)),
                _fmt(response.get('execution_id', MISSING))))
        elif isinstance(compute.get('error'), dict):
            parts.append('计算状态查询失败：' + _clip(compute['error'].get('message')))
        elif compute.get('error'):
            parts.append('计算状态查询失败：' + _clip(compute['error']))
        elif compute.get('skipped'):
            parts.append('计算状态：' + _clip(compute['skipped']))
    return _fmt('；'.join(part for part in parts if part)) if parts else '—'


def _render_reconcile(sections):
    """列每轮请求差集、错误原文与不一致项。"""
    batch = sections.get('batch') if isinstance(sections.get('batch'), dict) else {}
    attempts = batch.get('attempts') if isinstance(batch.get('attempts'), list) else []
    lines = ['## 请求与返回对账', '']
    if not attempts:
        lines.extend([f"- 未完成批量对账：{_fmt(batch.get('error') or '未提交批量请求')}", ''])
        return lines
    table = [[_fmt(item.get('label')), _fmt(item.get('requested')),
              _fmt(len(item.get('returned') or [])), _fmt(len(item.get('errors') or {})),
              _fmt(len(item.get('pending') or [])), _fmt(len(item.get('unaccounted') or [])),
              '一致' if item.get('consistent') else '不一致', _fmt(item.get('seconds'))]
             for item in attempts]
    lines.extend(_table(['轮次', '请求', '返回', '明确错误', '未就绪', '未解释差集', '核对', '秒'], table))
    lines.append('')
    errors = {}
    for item in attempts:
        if isinstance(item.get('errors'), dict):
            errors.update(item['errors'])
    if errors:
        lines.extend(['明确错误原文（仅保留服务端原文，未据此判断产品配置或权限）：', ''])
        lines.extend(f'- `{_fmt(identifier)}`：{_fmt(message)}' for identifier, message in errors.items())
        lines.append('')
    issues = [f"{item.get('label')}：{'；'.join(item['anomalies'])}"
              for item in attempts if item.get('anomalies')]
    failed = [item.get('label') for item in attempts if item.get('error')]
    if failed:
        issues.append('未取得资源映射的轮次：' + '、'.join(_fmt(item) for item in failed))
    lines.append('- 差集核对：' + ('；'.join(issues) if issues
                               else '请求 = 返回 + 明确错误 + 未就绪，无未解释项。'))
    lines.append('')
    return lines


def _render_scale(sections):
    """逐只清单、按日小计与同日总额判定。"""
    rows = sections.get('rows') if isinstance(sections.get('rows'), list) else []
    groups = sections.get('groups') if isinstance(sections.get('groups'), list) else []
    coverage = sections.get('coverage') or {}
    totals = sections.get('totals') or {}
    latest = (sections.get('calendar') or {}).get('latest_trading_day')
    lines = ['## 逐只清单', '']
    if not rows:
        lines.extend(['- 未取得逐只清单：本次没有实盘范围或清单未返回。', ''])
    else:
        table = [[_fmt(row['name']), _fmt(row['id']), _field(row['values'], 'date'),
                  _field(row['values'], 'total_equity'), _field(row['values'], 'total_assets'),
                  _field(row['values'], 'total_liabilities'), _field(row['values'], 'update_time'),
                  _fmt(row['product_state'] or '未返回'),
                  SOURCE_TEXT.get(row['source'], '未取得'),
                  STATUS_TEXT.get(row['status'], _fmt(row['status'])),
                  _diagnosis(row, latest)] for row in rows]
        lines.extend(_table(['产品', '产品 ID', '业务日期', '净资产（元）', '总资产（元）',
                             '总负债（元）', '报表重算时间', '产品状态', '来源', '状态', '诊断'],
                            table))
        lines.extend(['', '- 未返回字段与 `null` 都不是 0；`update_time` 是报表重算时间，'
                          '业务日期为当天也不证明价格或结算输入齐全。', ''])
    lines.extend(['## 按业务日期分组小计', ''])
    if not groups:
        lines.extend(['- 没有可分组小计的净资产金额；缺值不按 0 计入。', ''])
    else:
        lines.extend(_table(['业务日期', '产品数', '净资产小计（元）', '资产负债覆盖',
                             '恒等式不一致', '说明'],
                            [[_fmt(group['date'] or '日期未返回'), _fmt(group['rows']),
                              _fmt(group['equity_sum']),
                              _fmt(f"{group['assets_covered']}/{group['rows']}"),
                              _fmt(group['identity_mismatch']), _fmt(group['note'] or '—')]
                             for group in groups]))
        lines.extend(['', '- 分组小计只覆盖该日已取得有限净资产的产品；不同业务日不能相加。', ''])
    undated = (totals.get('undated') or {}).get('ids') or []
    if undated:
        lines.extend([f"- 有有限净资产但无可核验业务日的记录 {len(undated)} 只（"
                      f"{', '.join(map(str, undated[:10]))}）；金额 "
                      f"{_fmt((totals.get('undated') or {}).get('equity_sum'))} 元单列，"
                      '不进入按日小计与同日总额。', ''])
    lines.extend(['## 覆盖与总额判定', ''])
    if not coverage:
        lines.extend(['- 未取得覆盖计数：无法判定本次范围与总额。', ''])
        return lines
    lines.append(f"- 请求（label=live，按 ID 去重）：{coverage['requested']} 只；"
                 f"有可用业务日期与有限净资产 {coverage['ready']} 只"
                 f"（批量 {coverage['batch_rows']}、单读回收 {coverage['single_rows']}）")
    lines.append(f"- 明确错误 {coverage['error']}、截止时未就绪 {coverage['pending']}、"
                 f"批量失败 {coverage['batch_failed']}、缺字段 {coverage['missing_fields']}、"
                 f"对账不一致 {coverage['unreconciled']}")
    dates = totals.get('dates') or []
    lines.append(f"- 就绪项业务日期：{_fmt(', '.join(dates) or '没有可用日期')}"
                 f"；交易所日历最新交易日参照：{_fmt(latest or '未取得')}")
    if totals.get('same_day'):
        lines.append(f"- 结论：全部请求同日 {dates[0]} 且金额完整，可称该业务日实盘总额，"
                     f"净资产 {_fmt(totals.get('equity_sum'))} 元。")
        if totals.get('latest_match') is False:
            lines.append('- 该业务日不是交易所日历最新交易日，不能称为「最新交易日总额」。')
    else:
        reason = (f"就绪 {coverage['ready']}/{coverage['requested']} 未覆盖全部请求"
                  if not coverage['complete'] else '')
        if len(dates) != 1:
            reason = '；'.join(filter(None, [reason, f"就绪项分属 {len(dates)} 个业务日"]))
        lines.append(f"- 结论：不可称同日全量总额（{_fmt(reason or '缺少同日完整金额')}）；"
                     '只采用按日期分组小计，不跨日相加。')
    if totals.get('non_positive'):
        lines.append(f"- 零或负净资产产品 {len(totals['non_positive'])} 只，按原值保留并计入小计。")
    if totals.get('identity_mismatch'):
        lines.append(f"- 总资产−总负债−净资产超过 {TOLERANCE} 容差的产品 "
                     f"{len(totals['identity_mismatch'])} 只；按原值记录，不改写金额。")
    lines.append('')
    return lines


def _render_tail(sections):
    """最近结算参考、阶段耗时与缺口，配合文末执行状态核对。"""
    lines = []
    settled = sections.get('settled_reference')
    if isinstance(settled, dict) and settled.get('enabled'):
        lines.extend(['## 最近结算参考（上一交易日概览）', ''])
        if settled.get('skipped') or settled.get('error'):
            lines.extend([f"- 未取得：{_fmt(settled.get('skipped') or settled.get('error'))}", ''])
        else:
            lines.extend(_table(['产品', '产品 ID', '概览业务日期', '净资产（元）', '总资产（元）',
                                 '总负债（元）', '状态'],
                                [[_fmt(row['name']), _fmt(row['id']),
                                  _field(row['values'], 'date'),
                                  _field(row['values'], 'total_equity'),
                                  _field(row['values'], 'total_assets'),
                                  _field(row['values'], 'total_liabilities'),
                                  STATUS_TEXT.get(row['status'], _fmt(row['status']))]
                                 for row in settled.get('rows') or []]))
            for identifier, message in (settled.get('errors') or {}).items():
                lines.append(f"- 明确错误 `{_fmt(identifier)}`：{_fmt(message)}")
            if settled.get('unavailable'):
                lines.append(f"- 上一交易日概览未就位 {len(settled['unavailable'])} 只："
                             + ', '.join(_fmt(item) for item in settled['unavailable'][:10]))
            lines.extend(['', '- 本表与实时截面不是同一时点，不并入实时小计、不与实时金额相加。', ''])
    stages = sections.get('stages') if isinstance(sections.get('stages'), list) else []
    if stages:
        lines.extend(['## 阶段耗时', ''])
        lines.extend(_table(['阶段', '秒'],
                            [[_fmt(item.get('stage')), _fmt(item.get('seconds'))] for item in stages]))
        lines.append('')
    gaps = []
    universe, batch = sections.get('universe') or {}, sections.get('batch') or {}
    if universe.get('error'):
        gaps.append(f"实盘清单：{universe['error']}")
    if universe.get('unlabeled_count'):
        gaps.append(f"实盘清单：{universe['unlabeled_count']} 只产品未返回 label，未纳入范围")
    if (sections.get('calendar') or {}).get('error'):
        gaps.append(f"交易日历：{sections['calendar']['error']}")
    for item in batch.get('attempts') or []:
        if item.get('error'):
            gaps.append(f"批量请求 `{item.get('label')}`：{_clip(item['error'])}")
    rows = sections.get('rows') if isinstance(sections.get('rows'), list) else []
    for status in ('error', 'pending', 'batch_failed', 'missing_fields', 'unreconciled'):
        items = [row['id'] for row in rows if row['status'] == status]
        if items:
            gaps.append(f"{STATUS_TEXT[status]} {len(items)} 只：{', '.join(map(str, items[:10]))}")
    if (sections.get('settled_reference') or {}).get('skipped'):
        gaps.append('最近结算参考：' + sections['settled_reference']['skipped'])
    if gaps:
        lines.extend(['## 缺口', ''])
        lines.extend(f'- {_fmt(gap)}' for gap in gaps)
        lines.extend(['', '- 缺口按服务端返回值与本次实际范围记录；未修改日历、账户或估值输入，'
                          '也不据此推断用户配置有误。', ''])
    plans = [row for row in rows if row['detail'].get('next_steps')]
    if plans:
        lines.extend(['## 排查方案', ''])
        for row in plans:
            lines.append(f"- {_fmt(row['name'])}（`{_fmt(row['id'])}`）：")
            lines.extend(f'- {_fmt(step)}' for step in row['detail']['next_steps'])
        lines.extend(['', '- 已取得结果按原样保留；不自动重算、补输入或修改配置。', ''])
    return lines


def render(data):
    """渲染中文 Markdown；没有业务数据时也输出完整缺口报告。"""
    data = data if isinstance(data, dict) else {}
    sections = data.get('sections') if isinstance(data.get('sections'), dict) else {}
    meta = sections.get('meta') if isinstance(sections.get('meta'), dict) else {}
    state = str(data.get('state') or 'unknown')
    lines = ['# 实盘产品规模快照', '', f'- 运行状态：{STATE_TEXT.get(state, state)}']
    if meta.get('requested_at_beijing'):
        lines.append(f"- 生成时间（北京时间）：{_fmt(meta['requested_at_beijing'])}")
    if meta.get('collection_seconds') is not None:
        lines.append(f"- 采集进程耗时：{_fmt(meta['collection_seconds'])} 秒（不含报告输出）")
    lines.extend(['', '## 重点摘要', ''])
    summary = sections.get('summary') if isinstance(sections.get('summary'), list) else []
    if summary:
        lines.extend(f'- {_fmt(item)}' for item in summary[:3])
    else:
        lines.append('- 本次未取得业务摘要：范围、覆盖与缺口见下方章节。')
    lines.extend(['', '## 业务口径与边界', '',
                  f"- 范围：{_fmt((sections.get('universe') or {}).get('source') or '未取得产品清单')}；"
                  '只取 label 严格等于 live 的产品并按产品 ID 去重，'
                  '不按 product_state、封账、到期或金额正负筛选。',
                  '- 字段：批量实时截面请求 `date`、`total_equity`、`total_assets`、'
                  '`total_liabilities`、`update_time`；规模验收只看实际业务日期与有限净资产。',
                  '- 未请求 `units`、`unit_net_value`：缺份额与净值不改变规模判定，'
                  '也不能据此判断份额或净值是否就绪。',
                  '- 缺失不等于零：`null` 与未返回字段保留为空，零和负值按原值保留。',
                  '- 业务日以返回的 `date` 为准，请求日期不赋值；交易所日历只作最新交易日参照，'
                  '产品业务日按自身日历确定；报错项保留错误原文，'
                  '脚本不凭单条错误认定配置根因，也不自动改日历、账户或产品配置。',
                  '- `update_time` 是头寸报表重算时间，不是行情 tick；业务日期为当天'
                  '也不证明价格或结算价输入齐全。',
                  '- 同日总额仅当全部请求产品同日且都有有限净资产时成立；否则只给分组小计。',
                  f"- 金额单位：{_fmt(meta.get('money_unit') or '人民币头寸口径（元）')}。"])
    if (sections.get('settled_reference') or {}).get('enabled'):
        lines.append('- 最近结算参考为上一交易日概览，单独成表，不并入实时小计。')
    if meta.get('deadline_seconds') is not None:
        lines.append(f"- 时间边界：整条命令限时 {_fmt(meta['deadline_seconds'])} 秒，"
                     '到达硬截止即停止采集，只保留已落盘结果。')
    lines.append('')
    lines.extend(_render_reconcile(sections))
    lines.extend(_render_scale(sections))
    lines.extend(_render_tail(sections))
    lines.append('> 本报告为只读演示：脚本未创建、修改或删除任何业务数据。错误信息为服务端原文，'
                 '本报告不据此判断产品配置、权限或用户操作有误。')
    return '\n'.join(lines).rstrip() + '\n'


def configure(parser):
    """补充本案例可选参数：另行读取最近结算参考。"""
    parser.add_argument('--include-settled-reference', action='store_true',
                        help='额外读取上一交易日概览作为最近结算参考；单独成表，不并入实时小计')


if __name__ == '__main__':
    launch(collect, render, configure)
