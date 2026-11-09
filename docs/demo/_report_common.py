"""两个案例专用的报告运行器：独占输出、逐步证据、采集及渲染总截止。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time


def atomic_json(path, data):
    """用同目录唯一临时文件发布完整JSON，不使用共享的固定临时文件名。"""
    text = json.dumps(data, ensure_ascii=False, allow_nan=False, default=str, indent=2)
    descriptor, temporary = tempfile.mkstemp(prefix='.report-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ReportContext:
    """同一次报告复用唯一客户端，并保留每个调用的证据与缺口。"""

    def __init__(self, args, checkpoint, started):
        """初始化本次进程数据，令牌只用于请求与脱敏。"""
        self.args, self.path, self.started = args, checkpoint, started
        self.expires = started + args.deadline - min(2, args.deadline / 10)
        self.lock = threading.RLock()
        self.token = os.environ.get('RQAMSH_TOKEN', '')
        self.client = None
        self.data = {'state': 'running', 'sections': {}, 'raw': {}, 'steps': [], 'problems': [],
                     'requested_at': datetime.now(timezone(timedelta(hours=8))).isoformat()}
        self.checkpoint()

    def remaining(self):
        """返回本次总预算扣除收尾预留的剩余秒数。"""
        return max(0, self.expires - time.monotonic())

    def clean(self, value):
        """递归脱敏并将非有限数值保留为不可用，不把缺失转成零。"""
        if isinstance(value, str):
            text = value.replace(self.token, '<redacted>') if self.token else value
            text = re.sub(r'(?i)Bearer\s+[^\s"\'<>]+', 'Bearer <redacted>', text)
            return re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1<redacted>@', text)
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {str(key): self.clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item) for item in value]
        return value

    def checkpoint(self):
        """将可恢复的当前结果原子落盘，父进程截止后仍能使用。"""
        with self.lock:
            atomic_json(self.path, self.clean(self.data))

    def problem(self, section, message):
        """登记真实缺口并立即保存。"""
        with self.lock:
            item = {'section': section, 'message': self.clean(str(message))}
            if item not in self.data['problems']:
                self.data['problems'].append(item)
            self.checkpoint()

    def call(self, label, function):
        """执行一次调用，失败返回None但保留类型、诊断与耗时。"""
        if not self.remaining():
            self.problem(label, '已达到本次报告截止时间')
            return None
        started = time.monotonic()
        step = {'operation': label, 'started_seconds': round(started - self.started, 4)}
        try:
            result = function()
        except Exception as exc:
            step.update(state='failed', error=self.clean(str(exc)), error_type=type(exc).__name__)
            if hasattr(exc, 'code'):
                step.update(code=exc.code, status=exc.status, details=self.clean(exc.details))
            self.problem(label, step['error'])
            return None
        else:
            step['state'] = 'complete'
            with self.lock:
                self.data['raw'][label] = self.clean(result)
            return result
        finally:
            with self.lock:
                step['seconds'] = round(time.monotonic() - started, 4)
                self.data['steps'].append(step)
                self.checkpoint()

    def parallel(self, jobs):
        """至多五路执行独立只读，每个结果使用各自标签保存。"""
        with ThreadPoolExecutor(max_workers=min(5, max(1, len(jobs)))) as pool:
            futures = {key: pool.submit(self.call, key, fn) for key, fn in jobs.items()}
            return {key: future.result() for key, future in futures.items()}


def fallback_report(data):
    """执行异常时只展示已取得内容，不假称完整报告。"""
    lines = ['# 业务报告未完整生成', '', '以下仅为已取得数据，不能作为完整结果。', '']
    lines += [f'- {item["section"]}：{item["message"]}' for item in data.get('problems', [])]
    return '\n'.join(lines + ['', '## 已取得业务结果', '', '```json',
                             json.dumps(data.get('sections', {}), ensure_ascii=False, default=str, indent=2), '```'])


def load_checkpoint(path):
    """读取最后完整快照；从未启动时给出有明确诊断的失败结构。"""
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'state': 'failed', 'sections': {}, 'raw': {}, 'steps': [], 'problems': []}


def status_report(report, data):
    """从同一终态生成状态段，避免报告和证据使用不同状态。"""
    lines = [report, '', '## 本次执行状态', '', f'- 结果：`{data["state"]}`。']
    lines += [f'- 缺口 `{item["section"]}`：{item["message"]}' for item in data['problems']]
    return '\n'.join(lines) + '\n'


def check_owned(args, target=None):
    """发布前核对本次独占创建文件身份，拒绝截断被他人替换的路径。"""
    expected = json.loads(os.environ['_RQAMSH_DEMO_OWNED'])
    for path in ((target,) if target is not None else (args.output, args.evidence)):
        stat = path.stat()
        if [stat.st_dev, stat.st_ino] != expected[str(path.resolve())]:
            raise FileExistsError('本次输出路径已被其他运行替换，停止发布')


def write_evidence(args, data):
    """只向本次已拥有的证据文件写入，保持文件身份以便监督进程核验。"""
    check_owned(args, args.evidence)
    text = json.dumps(data, ensure_ascii=False, allow_nan=False, default=str, indent=2)
    with args.evidence.open('w', encoding='utf-8') as handle:
        handle.write(text)


def publish(args, data, report, started):
    """发布本次已独占的输出；证据序列化和文件写入均在受控采集进程内。"""
    check_owned(args)
    args.output.write_text(status_report(report, data), encoding='utf-8')
    write_evidence(args, data)
    data['timing']['wall_seconds'] = round(time.monotonic() - started, 4)
    data['timing']['within_deadline'] = data['timing']['wall_seconds'] <= args.deadline
    if not data['timing']['within_deadline']:
        data['state'] = 'timeout'
        data['problems'].append({'section': 'deadline', 'message': '报告发布超过总截止时间'})
    footer = (f'\n- 报告与证据生成墙钟：{data["timing"]["wall_seconds"]:.3f} 秒'
              f'（限时 {args.deadline:g} 秒；进程退出后由外部控制器复核总墙钟）。\n')
    check_owned(args)
    args.output.write_text(status_report(report, data) + footer, encoding='utf-8')
    write_evidence(args, data)


def worker(args, collect, render, path, started):
    """在同一个可终止子进程内完成鉴权、采集、渲染、序列化和正式输出。"""
    context = ReportContext(args, path, started)
    try:
        import rqamsh
        remaining = context.remaining()
        if not remaining:
            raise TimeoutError('启动已耗尽整体预算')
        context.client = rqamsh.init(base_url=args.base_url, workspace_id=args.workspace_id,
                                     token=context.token or None, timeout=min(30, remaining),
                                     wait_timeout=max(.01, remaining), poll_interval=1)
        authorization = context.client.session.headers.get('Authorization', '')
        if authorization.startswith('Bearer '):
            context.token = authorization[7:]
        result = collect(context)
        if isinstance(result, dict) and result is not context.data:
            context.data.update(result)
        context.data['state'] = 'partial' if context.data['problems'] else 'complete'
    except BaseException as exc:
        context.data['state'] = 'timeout' if isinstance(exc, TimeoutError) else 'failed'
        context.problem('collector', f'{type(exc).__name__}: {exc}')
    finally:
        if context.client is not None:
            try:
                import rqamsh
                rqamsh.close()
            except Exception as exc:
                context.data['state'] = 'failed'
                context.problem('close', f'{type(exc).__name__}: {exc}')
        context.data['collection_seconds'] = round(time.monotonic() - started, 4)
        context.checkpoint()
    try:
        report = render(context.data)
    except BaseException as exc:
        context.data['state'] = 'failed'
        context.problem('render', f'{type(exc).__name__}: {exc}')
        report = fallback_report(context.data)
    context.data['render_seconds'] = round(time.monotonic() - started - context.data['collection_seconds'], 4)
    context.data['timing'] = {'deadline_seconds': args.deadline,
                              'scope': '本次命令鉴权/解析、接口等待、加工、完整报告及JSON生成'}
    context.checkpoint()
    try:
        publish(args, context.clean(context.data), context.clean(report), started)
        context.data['published'] = True
    except BaseException as exc:
        context.data['state'] = 'failed'
        context.problem('publish', f'{type(exc).__name__}: {exc}')
    context.checkpoint()
    return 0 if context.data['state'] in {'complete', 'partial'} else 1


def launch(collect, render, configure):
    """独占输出后监督一轮完整执行，超时或异常仍保留可读终态证据。"""
    started = time.monotonic()
    parser = argparse.ArgumentParser(description='一次生成完整业务报告和JSON证据。')
    parser.add_argument('--base-url')
    parser.add_argument('--workspace-id')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--deadline', type=float, default=180)
    configure(parser)
    args = parser.parse_args()
    if not math.isfinite(args.deadline) or args.deadline < 1:
        parser.error('--deadline 必须是不小于1的有限秒数')
    checkpoint = os.environ.get('_RQAMSH_DEMO_CHECKPOINT')
    if checkpoint:
        raise SystemExit(worker(args, collect, render, Path(checkpoint),
                                float(os.environ['_RQAMSH_DEMO_STARTED'])))
    if args.output.resolve() == args.evidence.resolve():
        parser.error('报告与证据必须使用不同路径')
    owned = set()
    identities = {}
    try:
        for target in (args.evidence, args.output):
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as handle:
                handle.write('')
                stat = os.fstat(handle.fileno())
                identities[str(target.resolve())] = [stat.st_dev, stat.st_ino]
            owned.add(target)
    except OSError as exc:
        if args.evidence in owned:
            failed = load_checkpoint(Path('__no_checkpoint__'))
            failed['problems'].append({'section': 'output', 'message': f'{type(exc).__name__}: {exc}'})
            os.environ['_RQAMSH_DEMO_OWNED'] = json.dumps(identities)
            write_evidence(args, failed)
        parser.error('输出已存在或不可写；未覆盖任何原有文件')
    os.environ['_RQAMSH_DEMO_OWNED'] = json.dumps(identities)
    try:
        temporary = tempfile.TemporaryDirectory(prefix='rqamsh-report-')
    except OSError as exc:
        data = {'state': 'failed', 'sections': {}, 'raw': {}, 'steps': [],
                'problems': [{'section': 'startup', 'message': type(exc).__name__}]}
        check_owned(args)
        args.output.write_text(status_report(fallback_report(data), data), encoding='utf-8')
        write_evidence(args, data)
        raise
    with temporary as folder:
        partial = Path(folder) / 'checkpoint.json'
        process, expired, error = None, False, None
        environment = {**os.environ, '_RQAMSH_DEMO_CHECKPOINT': str(partial),
                       '_RQAMSH_DEMO_STARTED': str(started), 'PYTHONIOENCODING': 'utf-8'}
        try:
            process = subprocess.Popen([sys.executable, *sys.argv], env=environment,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            process.wait(timeout=max(.01, args.deadline - (time.monotonic() - started)
                                     - min(2, args.deadline / 10)))
        except subprocess.TimeoutExpired:
            expired = True
        except BaseException as exc:
            error = f'{type(exc).__name__}: 报告进程未正常完成'
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
        data = load_checkpoint(partial)
        okay = (not expired and error is None and process is not None
                and process.returncode == 0 and data.get('published'))
        if not okay:
            data['state'] = 'timeout' if expired else 'failed'
            message = '整体截止已到，未完整返回；以下仅为已取得数据' if expired else error or '子进程未完整发布报告'
            data['problems'].append({'section': 'process', 'message': message})
            data['timing'] = {'deadline_seconds': args.deadline, 'wall_seconds': round(time.monotonic() - started, 4),
                              'within_deadline': time.monotonic() - started <= args.deadline}
            try:
                check_owned(args)
                args.output.write_text(status_report(fallback_report(data), data), encoding='utf-8')
                write_evidence(args, data)
            except OSError as exc:
                # 报告目标失效时仍尝试保留证据；若磁盘完全不可写则明确向调用方报告。
                data['state'] = 'failed'
                data['problems'].append({'section': 'publish', 'message': type(exc).__name__})
                try:
                    write_evidence(args, data)
                except OSError:
                    print(json.dumps({'state': 'failed', 'error': '输出不可写，无法持久化诊断'}), file=sys.stderr)
                raise
        else:
            data = json.loads(args.evidence.read_text(encoding='utf-8'))
    observed_wall = round(time.monotonic() - started, 4)
    if observed_wall > args.deadline:
        data['state'] = 'timeout'
        data['timing'].update(wall_seconds=observed_wall, within_deadline=False)
        data['problems'].append({'section': 'deadline', 'message': '监督进程最终观测超过整体截止'})
        try:
            check_owned(args, args.output)
            args.output.write_text(status_report(fallback_report(data), data), encoding='utf-8')
        except OSError as exc:
            data['problems'].append({'section': 'timeout-publish', 'message': type(exc).__name__})
            write_evidence(args, data)
            raise
        write_evidence(args, data)
    print(json.dumps({'state': data['state'], 'report': str(args.output), 'evidence': str(args.evidence),
                      'timing': {**data['timing'], 'process_wall_seconds': observed_wall,
                                 'within_deadline': observed_wall <= args.deadline}}, ensure_ascii=False))
    raise SystemExit(0 if data['state'] == 'complete' else 2 if data['state'] == 'partial' else 1)
