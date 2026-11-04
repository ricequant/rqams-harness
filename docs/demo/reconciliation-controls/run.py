"""对账控制：缺件与差异核对、人工标记，以及估值表自动对账的采用和撤销。

脚本在专用测试空间完成一次真实业务闭环：直接从创建起使用
「交易流水 & 估值表」数据源、关闭自动覆盖、份额策略设为手动、账户留空 →
上传开始日全现金估值报告并显式自动对账，建立基线 → 导入报告日构造型报告并确认只保存
未采用 → 核对缺件与分组差异 → 只对报告日写入人工标记 → 采用该日自动对账并等待新执行 →
撤销并核对恢复 → 只删除本次开始日与报告日两份报告，再删除本次产品。
所有写入均记录在只增日志中：先写意图再调用，创建与删除范围只包含本次返回的资源；
写入异常不重放，未返回结果的创建不按名称认领。凭据只从 ``RQAMSH_TOKEN`` 读取。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import time
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import rqamsh
from rqamsh.errors import HarnessError


NAME_PREFIX = "harness-demo-20261102-reconciliation-"
NAME_PATTERN = re.compile(r"^harness-demo-20261102-reconciliation-[0-9a-f]{8}$")
STRATEGY_CATEGORY = "stock_long"
DIFF_FIELDS = ["positions", "prices", "payable", "receivable", "cash", "shares_payable", "net_asset"]
AMOUNT_TOLERANCE = 1e-6
CASH_ASSET_CLASSES = {
    "current_deposit", "reservation_deposit", "refundable_deposit",
    "securities_settlement_accounts", "cash_debt",
}
REPORT_DEFAULT = {
    "date": "2026-10-28",
    "total_equity": 1001000.0,
    "units": 1000000.0,
    "unit_net_value": 1.001,
    "acc_unit_net_value": 1.001,
    "positions": [
        {
            "order_book_id": "CNY",
            "symbol": "活期存款",
            "asset_class": "current_deposit",
            "direction": "long",
            "market_value": 1001000.0,
        }
    ],
}


def create_payload(name: str, start_date: str) -> dict:
    """构造从创建起即为混合数据源、无账户、手动份额的精确产品载荷。"""
    return {
        "name": name,
        "data_source": "trade_and_valuation_report",
        "auto_overwrite": False,
        "unit_policy": "manual",
        "label": "paper",
        "start_date": start_date,
        "investment_category": "equity",
        "strategy_category": STRATEGY_CATEGORY,
        "benchmark": {"type": "index", "id": "000300.XSHG"},
        "calendar": "exchange",
        "accounts": [],
    }


def baseline_report(date_text: str, amount: float) -> dict:
    """构造开始日全现金估值报告；份额与净资产同额、净值为 1。"""
    return {
        "date": date_text,
        "total_equity": float(amount),
        "units": float(amount),
        "unit_net_value": 1.0,
        "acc_unit_net_value": 1.0,
        "positions": [
            {
                "order_book_id": "CNY",
                "symbol": "活期存款",
                "asset_class": "current_deposit",
                "direction": "long",
                "market_value": float(amount),
            }
        ],
    }


class GuardError(ValueError):
    """表示命令行参数或构造输入不满足本任务的前置护栏。"""


class JournalUnavailable(RuntimeError):
    """表示只增日志无法继续持久化，必须停止后续业务写入。"""


class StageError(RuntimeError):
    """表示某个阶段以失败或阻塞终态结束，并携带脱敏诊断。"""

    def __init__(self, state: str, stage: str, message: str, detail: dict | None = None):
        """保存阶段终态与允许公开的诊断。"""
        super().__init__(message)
        self.state = state
        self.stage = stage
        self.message = message
        self.detail = detail or {}

    def as_dict(self) -> dict:
        """返回可写入证据文件的终态描述，不包含服务端正文或凭据。"""
        return {"state": self.state, "stage": self.stage, "message": self.message, "detail": self.detail}


def now_text() -> str:
    """返回带时区的当前时间字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_error(exc: Exception) -> dict:
    """只保留可定位的错误类型、错误码与 HTTP 状态，不复制服务端正文。"""
    return {
        "type": type(exc).__name__,
        "code": getattr(exc, "code", None),
        "status": getattr(exc, "status", None),
    }


def unwrap(payload):
    """展开任务包装，返回业务文档本体；已是业务文档时原样返回。"""
    if isinstance(payload, dict) and str(payload.get("status", "")).lower() in {"success", "succeeded"} \
            and isinstance(payload.get("data"), (dict, list)):
        return payload["data"]
    return payload


def number(value):
    """把响应数值转换为浮点数；布尔、空值与不可解析值返回 None，不当成零。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def close_enough(left, right, tolerance: float = AMOUNT_TOLERANCE) -> bool:
    """判断两个数值是否在绝对容差内一致；任一缺失都不视为一致。"""
    if left is None or right is None:
        return False
    return abs(left - right) <= max(tolerance, abs(right) * 1e-9)


def normalize_direction(value):
    """把多空方向统一为 long/short；无法识别的取值原样返回小写文本。"""
    mapping = {"long": "long", "多头": "long", "short": "short", "空头": "short"}
    if value is None:
        return None
    return mapping.get(str(value).strip().lower(), str(value).strip().lower())


def parse_iso_date(value: str, label: str) -> Date:
    """严格解析 YYYY-MM-DD，拒绝其他格式或非规范日期。"""
    if not isinstance(value, str):
        raise GuardError(f"{label} 必须为 YYYY-MM-DD")
    try:
        parsed = Date.fromisoformat(value)
    except ValueError as exc:
        raise GuardError(f"{label} 必须为 YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise GuardError(f"{label} 必须为规范 YYYY-MM-DD")
    return parsed


def load_report(args) -> dict:
    """读取或复制构造型报告，并校验字段、日期、净值与持仓形状。"""
    if args.report_json is not None:
        try:
            data = json.loads(args.report_json.read_text(encoding="utf-8"))
        except OSError as exc:
            raise GuardError(f"无法读取报告文件：{exc}") from exc
        except json.JSONDecodeError as exc:
            raise GuardError("报告文件不是合法 JSON") from exc
    else:
        data = json.loads(json.dumps(REPORT_DEFAULT))
    if not isinstance(data, dict):
        raise GuardError("报告必须是 JSON 对象")
    required = ("date", "total_equity", "units", "unit_net_value", "positions")
    missing = [key for key in required if key not in data]
    if missing:
        raise GuardError(f"报告缺少必填字段：{missing}")
    if data["date"] != args.report_date:
        raise GuardError("报告日期与 --report-date 不一致")
    for key in ("total_equity", "units", "unit_net_value", "acc_unit_net_value"):
        if key in data and number(data[key]) is None:
            raise GuardError(f"报告字段 {key} 必须为数值")
    equity, units, nav = number(data["total_equity"]), number(data["units"]), number(data["unit_net_value"])
    if equity is None or equity <= 0 or units is None or units <= 0:
        raise GuardError("报告净资产与份额必须为正数")
    if not close_enough(equity / units, nav, 1e-6):
        raise GuardError("报告净资产÷份额与单位净值不一致，拒绝带着矛盾输入运行")
    positions = data["positions"]
    if not isinstance(positions, list) or not positions:
        raise GuardError("报告 positions 必须为非空数组")
    for index, row in enumerate(positions):
        if not isinstance(row, dict):
            raise GuardError(f"报告 positions[{index}] 必须是对象")
        for key in ("order_book_id", "symbol", "asset_class", "direction", "market_value"):
            if key not in row:
                raise GuardError(f"报告 positions[{index}] 缺少 {key}")
        if number(row.get("market_value")) is None:
            raise GuardError(f"报告 positions[{index}].market_value 必须为数值")
        asset_class = str(row.get("asset_class"))
        if asset_class in CASH_ASSET_CLASSES or asset_class.startswith("virtual_"):
            continue
        if "quantity" not in row or "cost_price" not in row:
            raise GuardError(f"报告 positions[{index}] 非类现金持仓必须给出 quantity 与 cost_price 键")
    return data


def verify_arguments(args) -> dict:
    """校验目标、日期、路径与写入开关，返回通过校验的构造型报告。"""
    if not NAME_PATTERN.match(args.name):
        raise GuardError(f"--name 必须形如 {NAME_PREFIX}<8 位十六进制>")
    if args.confirm != args.name:
        raise GuardError("--confirm 必须与 --name 完全一致")
    if not args.allow_writes and not args.check:
        raise GuardError("真实写入必须显式传入 --allow-writes")
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname \
            or parsed.username is not None or parsed.query or parsed.fragment:
        raise GuardError("--base-url 必须是不带身份、查询和片段的 HTTP(S) 地址")
    if not re.fullmatch(r"[0-9a-fA-F]{24}", args.workspace_id or ""):
        raise GuardError("--workspace-id 必须为 24 位十六进制 ID")
    if args.journal == args.report:
        raise GuardError("--journal 与 --report 必须是不同路径")
    for path, label in ((args.journal, "--journal"), (args.report, "--report")):
        if Path(path).exists():
            raise GuardError(f"{label} 已存在；本脚本只新建证据文件，不覆盖旧文件")
    if args.wait_seconds <= 0 or args.poll_seconds <= 0:
        raise GuardError("--wait-seconds 与 --poll-seconds 必须为正数")
    if args.poll_seconds > args.wait_seconds:
        raise GuardError("--poll-seconds 不能大于 --wait-seconds")
    if args.init_amount <= 0:
        raise GuardError("--init-amount 必须为正数")
    start = parse_iso_date(args.start_date, "--start-date")
    report_date = parse_iso_date(args.report_date, "--report-date")
    range_end = parse_iso_date(args.range_end, "--range-end")
    if start >= report_date:
        raise GuardError("--start-date 必须早于 --report-date；V3 需要两份不同日期的报告")
    if report_date + timedelta(days=1) > range_end:
        raise GuardError("--range-end 必须至少覆盖报告日的次日，供恢复核对")
    report = load_report(args)
    if report_date > range_end:
        raise GuardError("--report-date 必须落在核对区间内")
    return report


def report_sha256(report: dict) -> str:
    """计算构造型报告的规范化 SHA-256，用于证据一致性核对。"""
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def script_sha256() -> str:
    """计算本脚本自身 SHA-256；读取失败时返回 None，不伪造。"""
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    except OSError:
        return None


class Journal:
    """只增 JSONL 运行日志：独占创建、每条落盘并 fsync，失败后不再接受写入。"""

    def __init__(self, path: Path, run_id: str, header: dict):
        """独占创建本次运行日志并立即落盘运行头。"""
        self.path = path
        self.run_id = run_id
        self.broken = False
        self.handle = path.open("x", encoding="utf-8", newline="\n")
        try:
            self.write("journal", "created", state="running", detail=header)
        except BaseException:
            self._raw_terminal("blocked", {"state": "blocked", "stage": "setup"})
            try:
                self.handle.close()
            except OSError:
                pass
            raise

    def write(self, stage: str, event: str, *, state: str, detail=None) -> None:
        """追加一条日志并立即同步到磁盘；已损坏时不再尝试写入。"""
        if self.broken:
            raise JournalUnavailable("日志此前已写入失败")
        record = {"ts": now_text(), "run_id": self.run_id, "stage": stage, "event": event,
                  "state": state, "detail": detail}
        line = json.dumps(record, ensure_ascii=False, default=str)
        try:
            self.handle.write(line + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except (OSError, ValueError) as exc:
            self.broken = True
            raise JournalUnavailable(str(exc)) from exc

    def try_write(self, stage: str, event: str, *, state: str, detail=None) -> None:
        """尽力追加日志；日志不可写时不覆盖原异常。"""
        try:
            self.write(stage, event, state=state, detail=detail)
        except (JournalUnavailable, ValueError):
            return

    def _raw_terminal(self, state: str, detail: dict) -> bool:
        """仅通过本次独占创建的句柄追加终态行；句柄不可用时不按路径重开。"""
        record = {"ts": now_text(), "run_id": self.run_id, "stage": "finalize",
                  "event": "terminal", "state": state, "detail": detail}
        try:
            self.handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())
            return True
        except (OSError, ValueError, AttributeError):
            return False

    def terminal(self, state: str, detail: dict) -> bool:
        """尽力写入终态记录并返回是否落盘；日志损坏时只用本次句柄追加。"""
        if not self.broken:
            try:
                self.write("finalize", "terminal", state=state, detail=detail)
                return True
            except JournalUnavailable:
                pass
        return self._raw_terminal(state, detail)

    def close(self) -> None:
        """刷新并关闭日志句柄，已损坏时也不让关闭阻塞收尾。"""
        try:
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except OSError:
            pass
        try:
            self.handle.close()
        except OSError:
            pass


class Evidence:
    """独占创建的 JSON 证据文件：同一句柄内反复补写当前终态，不触碰其他文件。"""

    def __init__(self, path: Path, initial: dict):
        """独占创建证据文件并写入初始状态。"""
        self.path = path
        self.handle = path.open("x", encoding="utf-8", newline="\n")
        try:
            self.write(initial)
        except BaseException:
            try:
                self.handle.close()
            except OSError:
                pass
            raise

    def write(self, document: dict) -> None:
        """重写本次运行的证据文档并同步到磁盘。"""
        text = json.dumps(document, ensure_ascii=False, indent=2, default=str)
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(text + "\n")
        self.handle.flush()
        os.fsync(self.handle.fileno())

    def close(self) -> None:
        """刷新并关闭证据句柄。"""
        try:
            self.handle.flush()
            os.fsync(self.handle.fileno())
        except OSError:
            pass
        try:
            self.handle.close()
        except OSError:
            pass


class ReconciliationControls:
    """执行对账控制演示的一次完整真实运行。"""

    def __init__(self, args, report: dict, run_id: str):
        """初始化本次对账运行、所有权和清理状态。"""
        self.args = args
        self.report = report
        self.run_id = run_id
        self.started = datetime.now(timezone.utc)
        self.state = "running"
        self.current_stage = "setup"
        self.steps: list[dict] = []
        self.checks: list[dict] = []
        self.created = {"products": [], "reports": [], "marks": [], "auto": [], "undo": []}
        self.product_id = None
        self.report_id = None
        self.report_server_date = None
        self.report_saved = False
        self.baseline_report = baseline_report(args.start_date, args.init_amount)
        self.baseline_report_id = None
        self.baseline_report_server_date = None
        self.baseline_report_saved = False
        self.pre_executions: dict = {}
        self.create_attempted = False
        self.create_unknown = False
        self.journal_broken = False
        self.interrupted = False
        self.workspace_name = None
        self.initial_config = {}
        self.cleanup: dict = {}
        self.cleanup_storage_error = None
        self.finalize_error = None
        self.downloads: list[dict] = []
        self.failure = None
        self.demo_sha256 = script_sha256()
        self.report_digest = report_sha256(report)
        self.journal: Journal | None = None
        self.evidence: Evidence | None = None
        self.cleanup_started = False

    # ------------------------------------------------------------------ 证据

    def document(self) -> dict:
        """汇总当前运行的脱敏证据文档。"""
        finished = datetime.now(timezone.utc)
        return {
            "run_id": self.run_id,
            "state": self.state,
            "base_url": self.args.base_url,
            "workspace_id": self.args.workspace_id,
            "workspace_name": self.workspace_name,
            "name": self.args.name,
            "create_attempted": self.create_attempted,
            "create_unknown": self.create_unknown,
            "started_at": self.started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "seconds": round((finished - self.started).total_seconds(), 3),
            "client_version": getattr(rqamsh, "__version__", None),
            "demo_sha256": self.demo_sha256,
            "report_sha256": self.report_digest,
            "constructed_input": {
                "create_payload": create_payload(self.args.name, self.args.start_date),
                "baseline_report": self.baseline_report,
                "write_dates": [self.args.start_date, self.args.report_date],
                "diff_fields": DIFF_FIELDS,
                "mark": {"date": self.args.report_date, "done": True,
                         "description": self.args.description},
                "report": self.report,
            },
            "created": self.created,
            "product_id": self.product_id,
            "report_id": self.report_id,
            "report_server_date": self.report_server_date,
            "baseline_report_id": self.baseline_report_id,
            "baseline_report_server_date": self.baseline_report_server_date,
            "pre_executions": self.pre_executions,
            "initial_config": self.initial_config,
            "steps": self.steps,
            "checks": self.checks,
            "cleanup": self.cleanup,
            "cleanup_storage_error": self.cleanup_storage_error,
            "finalize_error": self.finalize_error,
            "downloads": self.downloads,
            "failure": self.failure,
            "artifacts": {"journal": str(self.args.journal), "report": str(self.args.report)},
        }

    def persist(self) -> None:
        """把当前证据写入本次独占创建的证据文件；写盘失败按存储错误停止后续写入。"""
        if self.evidence is None:
            return
        try:
            self.evidence.write(self.document())
        except (OSError, ValueError) as exc:
            raise JournalUnavailable(f"证据文件写入失败：{type(exc).__name__}") from exc

    def record_step(self, stage: str, detail: dict) -> None:
        """记录一个已完成阶段，并立即持久化日志与证据。"""
        self.current_stage = stage
        self.steps.append({"stage": stage, "state": "passed", "ok": True, "detail": detail})
        self.journal.write(stage, "step_done", state="passed", detail=detail)
        self.persist()

    def ensure(self, condition: bool, *, name: str, expected, actual, state: str = "failed",
               message: str | None = None) -> None:
        """登记并断言一项业务核对；不满足时以失败或阻塞终态停止。"""
        self.checks.append({"check": name, "ok": bool(condition),
                            "expected": expected, "actual": actual})
        if not condition:
            raise StageError(state, self.current_stage, message or f"核对未通过：{name}",
                             {"expected": expected, "actual": actual})

    # -------------------------------------------------------------- 调用封装

    def fetch(self, stage: str, label: str, call):
        """执行只读调用并记录意图与结果；失败按阻塞处理。"""
        self.current_stage = stage
        self.journal.write(stage, "read_intent", state="running", detail={"label": label})
        try:
            result = call()
        except HarnessError as exc:
            error = safe_error(exc)
            self.journal.try_write(stage, "read_failed", state="failed",
                                   detail={"label": label, **error})
            raise StageError("blocked", stage, f"读取失败：{label}", {"error": error}) from exc
        self.journal.write(stage, "read_done", state="passed", detail={"label": label})
        return result

    def write_action(self, stage: str, label: str, call, detail: dict | None = None):
        """先写意图再执行一次业务写入；异常不重放，按阻塞终止该阶段。"""
        self.current_stage = stage
        self.journal.write(stage, "write_intent", state="running",
                           detail={"label": label, **(detail or {})})
        try:
            return call()
        except KeyboardInterrupt:
            self.journal.try_write(stage, "write_interrupted", state="failed",
                                   detail={"label": label})
            raise
        except HarnessError as exc:
            error = safe_error(exc)
            ambiguous = error["code"] in {"transport_error", "wait_timeout", "pending_without_task"} \
                or (isinstance(error["status"], int) and error["status"] >= 500)
            self.journal.try_write(stage, "write_failed", state="failed",
                                   detail={"label": label, "ambiguous": ambiguous, **error})
            raise StageError("blocked", stage, "业务写入失败；按约定不重放", {
                "label": label, "ambiguous": ambiguous, "error": error,
            }) from exc

    def wait_normal(self, stage: str) -> dict:
        """有界等待 normal；仅 running/pending 重读，error/failed 等终态立即阻塞。"""
        self.current_stage = stage
        deadline = time.monotonic() + self.args.wait_seconds
        polls: list[dict] = []
        while True:
            try:
                payload = rqamsh.products.compute_state(self.product_id)
            except HarnessError as exc:
                error = safe_error(exc)
                self.journal.try_write(stage, "compute_failed", state="blocked", detail=error)
                raise StageError("blocked", stage, "读取计算状态失败", {"error": error}) from exc
            document = unwrap(payload) if isinstance(payload, dict) else {}
            state = document.get("state")
            execution_id = document.get("execution_id")
            normalized = str(state).strip().lower() if state is not None else ""
            polls.append({"at": now_text(), "state": state,
                          "execution_id": execution_id})
            retryable = normalized in {"running", "pending", "computing"}
            self.journal.write(stage, "compute_poll",
                               state="running" if retryable else "blocked",
                               detail=polls[-1])
            if normalized == "normal":
                self.journal.try_write(stage, "compute_normal", state="passed",
                                       detail={"polls": len(polls), "last": polls[-1]})
                return {"polls": len(polls), "last": polls[-1], "history": polls[-5:]}
            if not retryable:
                detail = {"state": state, "execution_id": execution_id,
                          "polls": len(polls), "history": polls[-5:]}
                self.journal.write(stage, "compute_terminal", state="blocked", detail=detail)
                raise StageError("blocked", stage,
                                 "计算状态进入非 running/pending 终态；不重放写入", detail)
            if time.monotonic() >= deadline:
                detail = {"polls": len(polls), "history": polls[-5:]}
                self.journal.write(stage, "compute_timeout", state="blocked", detail=detail)
                raise StageError("blocked", stage, "计算状态未在等待期限内到达 normal；不重放写入",
                                 detail)
            time.sleep(self.args.poll_seconds)

    def capture_execution(self, stage: str) -> dict:
        """在任何写入前读取并保存计算执行 ID；启动期 error 只记录，不当作写入阻断。"""
        self.current_stage = stage
        try:
            payload = rqamsh.products.compute_state(self.product_id)
        except HarnessError as exc:
            error = safe_error(exc)
            self.journal.try_write(stage, "compute_pre_failed", state="blocked", detail=error)
            raise StageError("blocked", stage, "写入前无法读取计算执行 ID；不写以免混淆新旧结果",
                             {"error": error}) from exc
        document = unwrap(payload) if isinstance(payload, dict) else None
        if not isinstance(document, dict) \
                or "state" not in document or "execution_id" not in document:
            self.journal.try_write(stage, "compute_pre_incomplete", state="blocked",
                                   detail={"response_type": type(document).__name__,
                                           "has_state": isinstance(document, dict)
                                           and "state" in document,
                                           "has_execution_id": isinstance(document, dict)
                                           and "execution_id" in document})
            raise StageError("blocked", stage,
                             "写入前计算状态缺少 state/execution_id 字段；无法区分新旧执行，不写入")
        detail = {"state": document.get("state"),
                  "execution_id": document.get("execution_id"),
                  "has_execution_id": True,
                  "at": now_text()}
        self.pre_executions[stage] = detail
        self.journal.write(stage, "compute_pre", state="passed", detail=detail)
        return detail

    def wait_new_execution(self, stage: str, previous: dict) -> dict:
        """只读等待新 execution_id；同 ID 的旧 error 不算新任务结果，新 ID error 立即停。"""
        self.current_stage = stage
        previous_id = previous.get("execution_id") if isinstance(previous, dict) else None
        deadline = time.monotonic() + self.args.wait_seconds
        polls: list[dict] = []
        while True:
            try:
                payload = rqamsh.products.compute_state(self.product_id)
            except HarnessError as exc:
                error = safe_error(exc)
                self.journal.try_write(stage, "compute_failed", state="blocked", detail=error)
                raise StageError("blocked", stage, "读取计算状态失败", {"error": error}) from exc
            document = unwrap(payload) if isinstance(payload, dict) else {}
            state = document.get("state")
            execution_id = document.get("execution_id")
            normalized = str(state).strip().lower() if state is not None else ""
            polls.append({"at": now_text(), "state": state, "execution_id": execution_id})
            is_new = execution_id is not None and (
                previous_id is None or str(execution_id) != str(previous_id)
            )
            retryable = normalized in {"running", "pending", "computing"}
            self.journal.write(stage, "compute_poll",
                               state="running" if (not is_new or retryable) else "blocked",
                               detail={**polls[-1], "is_new": is_new,
                                       "previous_execution_id": previous_id})
            if is_new and not normalized:
                detail = {"state": state, "execution_id": execution_id,
                          "polls": len(polls), "history": polls[-5:],
                          "previous_execution_id": previous_id}
                self.journal.write(stage, "compute_incomplete", state="blocked", detail=detail)
                raise StageError("blocked", stage, "新计算执行缺少 state 字段；不推断结果", detail)
            if is_new and normalized == "normal":
                detail = {"state": state, "execution_id": execution_id,
                          "polls": len(polls), "history": polls[-5:],
                          "previous_execution_id": previous_id}
                self.journal.try_write(stage, "compute_new_normal", state="passed", detail=detail)
                return detail
            if is_new and not retryable:
                detail = {"state": state, "execution_id": execution_id,
                          "polls": len(polls), "history": polls[-5:],
                          "previous_execution_id": previous_id}
                self.journal.write(stage, "compute_new_terminal", state="blocked", detail=detail)
                raise StageError("blocked", stage,
                                 "新计算执行进入非 running/pending 终态；不重放写入", detail)
            if time.monotonic() >= deadline:
                detail = {"polls": len(polls), "history": polls[-5:],
                          "previous_execution_id": previous_id,
                          "last_execution_id": execution_id}
                self.journal.write(stage, "compute_timeout", state="blocked", detail=detail)
                raise StageError("blocked", stage, "未在等待期限内观察到新计算执行；不重放写入",
                                 detail)
            time.sleep(self.args.poll_seconds)

    # ------------------------------------------------------------ 数据提取

    @staticmethod
    def position_map(document: dict) -> dict:
        """把头寸报表的持仓数组或字典统一成 order_book_id 到持仓字段的映射。"""
        rows = document.get("positions")
        if isinstance(rows, dict):
            rows = list(rows.values())
        result = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            code = row.get("order_book_id")
            if code is None:
                continue
            result[str(code)] = {
                "asset_class": row.get("asset_class"),
                "direction": normalize_direction(row.get("direction")),
                "quantity": number(row.get("quantity")),
                "market_value": number(row.get("market_value")),
                "fair_value": number(row.get("fair_value")),
            }
        return result

    @staticmethod
    def total_fields(document: dict) -> dict:
        """提取指定日头寸报表的顶层金额、份额与日期字段，不补缺失值。"""
        return {
            "date": document.get("date"),
            "total_equity": number(document.get("total_equity")),
            "units": number(document.get("units")),
            "unit_net_value": number(document.get("unit_net_value")),
            "acc_unit_net_value": number(document.get("acc_unit_net_value")),
            "total_assets": number(document.get("total_assets")),
            "total_liabilities": number(document.get("total_liabilities")),
        }

    def read_balance(self, stage: str, date_text: str) -> dict:
        """读取产品指定日头寸并核对服务端返回日期与请求日期一致。"""
        payload = self.fetch(stage, f"balances.get {date_text}",
                             lambda: rqamsh.balances.get(self.product_id, date=date_text))
        document = unwrap(payload)
        if not isinstance(document, dict):
            raise StageError("failed", stage, "头寸报表不是对象", {"actual_type": type(document).__name__})
        totals = self.total_fields(document)
        totals["positions"] = self.position_map(document)
        self.ensure(totals["date"] == date_text, name=f"{stage}.date", expected=date_text,
                    actual=totals["date"], message="服务端返回日期与请求日期不一致；不使用其他日期替代")
        return totals

    def check_balance(self, stage: str, date_text: str, *, equity: float, units: float,
                      nav: float, acc: float, cash: float) -> dict:
        """读取并核对指定日净资产、份额、净值与唯一现金科目持仓。"""
        totals = self.read_balance(stage, date_text)
        positions = totals["positions"]
        self.ensure(close_enough(totals["total_equity"], equity), name=f"{stage}.total_equity",
                    expected=equity, actual=totals["total_equity"])
        self.ensure(close_enough(totals["units"], units), name=f"{stage}.units",
                    expected=units, actual=totals["units"])
        self.ensure(close_enough(totals["unit_net_value"], nav), name=f"{stage}.unit_net_value",
                    expected=nav, actual=totals["unit_net_value"])
        self.ensure(close_enough(totals["acc_unit_net_value"], acc),
                    name=f"{stage}.acc_unit_net_value", expected=acc,
                    actual=totals["acc_unit_net_value"])
        self.ensure(set(positions) == {"CNY"}, name=f"{stage}.positions.keys",
                    expected=["CNY"], actual=sorted(positions))
        position = positions.get("CNY") or {}
        self.ensure(position.get("asset_class") == "current_deposit",
                    name=f"{stage}.positions.asset_class", expected="current_deposit",
                    actual=position.get("asset_class"))
        self.ensure(position.get("direction") == "long", name=f"{stage}.positions.direction",
                    expected="long", actual=position.get("direction"))
        self.ensure(close_enough(position.get("quantity"), cash),
                    name=f"{stage}.positions.quantity", expected=cash, actual=position.get("quantity"))
        self.ensure(close_enough(position.get("market_value"), cash),
                    name=f"{stage}.positions.market_value", expected=cash,
                    actual=position.get("market_value"))
        return totals

    def read_report_rows(self, stage: str, start: str, end: str) -> list:
        """读取报告元数据列表并整理为数组；日期范围由调用方固定。"""
        payload = self.fetch(stage, f"valuation_reports.list {start}..{end}",
                             lambda: rqamsh.valuation_reports.list(
                                 self.product_id, start_date=start, end_date=end))
        document = unwrap(payload)
        return document if isinstance(document, list) else []

    def read_reconciliation(self, stage: str, start: str, end: str) -> dict:
        """读取产品区间对账状态，返回按日期索引的日项与产品名。"""
        payload = self.fetch(stage, f"reconciliation.list {start}..{end}",
                             lambda: rqamsh.reconciliation.list(
                                 [self.product_id], start_date=start, end_date=end))
        document = unwrap(payload)
        self.ensure(isinstance(document, list) and len(document) == 1,
                    name=f"{stage}.shape", expected="单产品数组", actual=type(document).__name__)
        item = document[0]
        self.ensure(item.get("product_id") == self.product_id, name=f"{stage}.product_id",
                    expected=self.product_id, actual=item.get("product_id"))
        entries = {}
        for row in item.get("reconciliation_list") or []:
            if isinstance(row, dict) and row.get("date"):
                entries[str(row["date"])] = row
        self.ensure(bool(entries), name=f"{stage}.entries", expected="非空日度对账项",
                    actual=len(entries))
        return {"product_name": item.get("product_name"), "entries": entries}

    def read_diff(self, stage: str, date_text: str) -> dict:
        """读取某日全部差异分组，并核对返回包含请求的每个分组。"""
        payload = self.fetch(stage, f"reconciliation.diff {date_text}",
                             lambda: rqamsh.reconciliation.diff(
                                 self.product_id, date=date_text, fields=DIFF_FIELDS))
        document = unwrap(payload)
        self.ensure(isinstance(document, dict), name=f"{stage}.shape", expected="分组对象",
                    actual=type(document).__name__)
        self.ensure(set(document) == set(DIFF_FIELDS), name=f"{stage}.fields",
                    expected=DIFF_FIELDS, actual=sorted(document))
        return document

    @staticmethod
    def diff_pairs(group: str, row: dict) -> list[dict]:
        """把一行差异里的两侧数值展开为可比较对，保留分组与行标识。"""
        pairs = []
        identity = row.get("order_book_id") or row.get("key") or row.get("product_share") or ""
        for field in ("quantity", "price"):
            node = row.get(field)
            if isinstance(node, dict) and "ams" in node and "valuation_report" in node:
                pairs.append({"group": group, "identity": str(identity), "field": field,
                              "ams": number(node.get("ams")),
                              "valuation_report": number(node.get("valuation_report"))})
        if "ams" in row and "valuation_report" in row:
            pairs.append({"group": group, "identity": str(identity), "field": "amount",
                          "ams": number(row.get("ams")),
                          "valuation_report": number(row.get("valuation_report"))})
        return pairs

    def diff_pairs_all(self, diff: dict) -> list[dict]:
        """展开所有分组行为两侧数值对，供一致性与预期差异核对。"""
        pairs = []
        for group, rows in diff.items():
            for row in rows or []:
                if isinstance(row, dict):
                    pairs.extend(self.diff_pairs(group, row))
        return pairs

    def find_pair(self, pairs: list[dict], group: str, identity: str, field: str) -> dict:
        """按分组、标识与字段定位唯一两侧数值对，找不到时明确失败。"""
        matched = [pair for pair in pairs if pair["group"] == group
                   and pair["identity"] == identity and pair["field"] == field]
        self.ensure(len(matched) == 1, name=f"diff.{group}.{identity}.{field}.exists",
                    expected=1, actual=len(matched))
        return matched[0]

    def check_diff_expected(self, stage: str, diff: dict, *, report_total: float, report_units: float,
                            report_nav: float, report_acc: float, baseline: float,
                            baseline_nav: float) -> dict:
        """核对采用报告前的预期差异：现金、净资产、份额与净值两侧来源各自成立。"""
        pairs = self.diff_pairs_all(diff)
        cash = self.find_pair(pairs, "cash", "current_deposit", "amount")
        self.ensure(close_enough(cash["ams"], baseline), name=f"{stage}.cash.ams",
                    expected=baseline, actual=cash["ams"])
        self.ensure(close_enough(cash["valuation_report"], report_total),
                    name=f"{stage}.cash.valuation_report", expected=report_total,
                    actual=cash["valuation_report"])
        equity = self.find_pair(pairs, "net_asset", "total_equity", "amount")
        self.ensure(close_enough(equity["ams"], baseline), name=f"{stage}.equity.ams",
                    expected=baseline, actual=equity["ams"])
        self.ensure(close_enough(equity["valuation_report"], report_total),
                    name=f"{stage}.equity.valuation_report", expected=report_total,
                    actual=equity["valuation_report"])
        units = self.find_pair(pairs, "net_asset", "units", "amount")
        self.ensure(close_enough(units["ams"], report_units) and close_enough(
            units["valuation_report"], report_units), name=f"{stage}.units.both",
            expected=report_units, actual=[units["ams"], units["valuation_report"]])
        nav = self.find_pair(pairs, "net_asset", "unit_net_value", "amount")
        self.ensure(close_enough(nav["ams"], baseline_nav), name=f"{stage}.nav.ams",
                    expected=baseline_nav, actual=nav["ams"])
        self.ensure(close_enough(nav["valuation_report"], report_nav),
                    name=f"{stage}.nav.valuation_report", expected=report_nav,
                    actual=nav["valuation_report"])
        acc = self.find_pair(pairs, "net_asset", "acc_unit_net_value", "amount")
        self.ensure(close_enough(acc["ams"], baseline_nav), name=f"{stage}.acc.ams",
                    expected=baseline_nav, actual=acc["ams"])
        self.ensure(close_enough(acc["valuation_report"], report_acc),
                    name=f"{stage}.acc.valuation_report", expected=report_acc,
                    actual=acc["valuation_report"])
        self.ensure(diff.get("positions") == [] and diff.get("prices") == [],
                    name=f"{stage}.cash_not_in_positions", expected={"positions": [], "prices": []},
                    actual={"positions": len(diff.get("positions") or []),
                            "prices": len(diff.get("prices") or [])},
                    message="只有现金类持仓时，持仓与价格分组应为空；现金差异在 cash 分组核对")
        return {"pairs": pairs, "groups": {name: len(rows or []) for name, rows in diff.items()}}

    def check_diff_equal(self, stage: str, diff: dict, *, report_total: float,
                         report_units: float, report_nav: float, report_acc: float) -> dict:
        """核对采用报告后两侧完全一致，且关键分组命中报告值。"""
        pairs = self.diff_pairs_all(diff)
        mismatched = [pair for pair in pairs
                      if not close_enough(pair["ams"], pair["valuation_report"])]
        self.ensure(not mismatched, name=f"{stage}.all_pairs_equal", expected=[],
                    actual=mismatched[:10])
        cash = self.find_pair(pairs, "cash", "current_deposit", "amount")
        self.ensure(close_enough(cash["ams"], report_total) and close_enough(
            cash["valuation_report"], report_total), name=f"{stage}.cash.both",
            expected=report_total, actual=[cash["ams"], cash["valuation_report"]])
        equity = self.find_pair(pairs, "net_asset", "total_equity", "amount")
        self.ensure(close_enough(equity["ams"], report_total) and close_enough(
            equity["valuation_report"], report_total), name=f"{stage}.equity.both",
            expected=report_total, actual=[equity["ams"], equity["valuation_report"]])
        units = self.find_pair(pairs, "net_asset", "units", "amount")
        self.ensure(close_enough(units["ams"], report_units) and close_enough(
            units["valuation_report"], report_units), name=f"{stage}.units.both",
            expected=report_units, actual=[units["ams"], units["valuation_report"]])
        nav = self.find_pair(pairs, "net_asset", "unit_net_value", "amount")
        self.ensure(close_enough(nav["ams"], report_nav) and close_enough(
            nav["valuation_report"], report_nav), name=f"{stage}.nav.both",
            expected=report_nav, actual=[nav["ams"], nav["valuation_report"]])
        acc = self.find_pair(pairs, "net_asset", "acc_unit_net_value", "amount")
        self.ensure(close_enough(acc["ams"], report_acc) and close_enough(
            acc["valuation_report"], report_acc), name=f"{stage}.acc.both",
            expected=report_acc, actual=[acc["ams"], acc["valuation_report"]])
        return {"pairs": pairs, "groups": {name: len(rows or []) for name, rows in diff.items()}}

    def check_lack(self, stage: str, entries: dict, date_text: str, expected_type,
                   *, with_report: bool) -> dict:
        """核对指定日缺件分类与报告存在性；无缺件时必须是空对象，不是数值零。"""
        entry = entries.get(date_text)
        self.ensure(entry is not None, name=f"{stage}.{date_text}.present", expected=True,
                    actual=False, message="对账日项缺失；不推断该日状态")
        lack = entry.get("lack")
        if expected_type is None:
            self.ensure(isinstance(lack, dict) and lack == {},
                        name=f"{stage}.{date_text}.lack", expected={}, actual=lack)
        else:
            self.ensure(isinstance(lack, dict) and lack.get("type") == expected_type,
                        name=f"{stage}.{date_text}.lack", expected={"type": expected_type},
                        actual=lack)
        self.ensure(("unit_net_value" in entry) == with_report,
                    name=f"{stage}.{date_text}.report_visible", expected=with_report,
                    actual="unit_net_value" in entry)
        return entry

    # ---------------------------------------------------------------- 各阶段

    def step_target(self) -> None:
        """确认目标工作空间属于当前身份，并记录空间名称。"""
        payload = self.fetch("preflight_target", "workspaces.list", lambda: rqamsh.workspaces.list())
        document = unwrap(payload)
        rows = document.get("data") if isinstance(document, dict) else document
        self.ensure(isinstance(rows, list), name="preflight_target.members", expected="数组",
                    actual=type(rows).__name__, state="blocked")
        matched = [row for row in rows if isinstance(row, dict) and row.get("id") == self.args.workspace_id]
        self.ensure(len(matched) == 1, name="preflight_target.workspace",
                    expected=self.args.workspace_id, actual=[row.get("id") for row in matched],
                    state="blocked", message="目标工作空间不在当前身份的成员列表中")
        self.workspace_name = matched[0].get("name")
        self.ensure(bool(self.workspace_name), name="preflight_target.workspace_name",
                    expected="非空名称", actual=self.workspace_name, state="blocked")
        self.record_step("preflight_target", {
            "workspace_id": self.args.workspace_id,
            "workspace_name": self.workspace_name,
            "member_count": len(rows),
        })

    def step_name_free(self) -> None:
        """确认专用产品名称当前未被占用；已占用时阻塞而不是挑同名产品。"""
        payload = self.fetch("preflight_name", "products.name_exists",
                             lambda: rqamsh.products.name_exists(name=self.args.name))
        document = unwrap(payload)
        exists = document.get("exists") if isinstance(document, dict) else None
        self.ensure(exists is False, name="preflight_name.exists", expected=False, actual=exists,
                    state="blocked", message="产品名称已被占用；不自动认领同名产品")
        self.record_step("preflight_name", {"name": self.args.name, "exists": exists})

    def probe_name_candidate(self) -> dict:
        """创建结果不明时只读探测同名候选，仅登记待核验，不当作自有资源。"""
        evidence = {"checked": False, "name_exists": None, "candidate_ids": []}
        try:
            payload = rqamsh.products.name_exists(name=self.args.name)
            document = unwrap(payload)
            evidence["checked"] = True
            evidence["name_exists"] = document.get("exists") if isinstance(document, dict) else None
            if evidence["name_exists"]:
                listing = unwrap(rqamsh.products.list(fields=["id", "name"]))
                products = listing.get("products") if isinstance(listing, dict) else listing
                evidence["candidate_ids"] = [row.get("id") for row in products or []
                                             if isinstance(row, dict)
                                             and row.get("name") == self.args.name]
        except HarnessError as exc:
            evidence["error"] = safe_error(exc)
        return evidence

    def step_create(self) -> None:
        """用混合数据源载荷直接创建产品；不创建模拟交易、不补造账户。"""
        payload = create_payload(self.args.name, self.args.start_date)
        self.current_stage = "create_product"
        self.journal.write("create_product", "write_intent", state="running", detail={
            "label": "products.create mixed/no-accounts/manual",
            "payload": payload,
        })
        self.create_attempted = True
        self.create_unknown = True
        try:
            result = rqamsh.products.create(payload)
        except HarnessError as exc:
            error = safe_error(exc)
            self.create_unknown = (
                error["code"] in {"transport_error", "wait_timeout", "pending_without_task"}
                or error["status"] is None
                or (isinstance(error["status"], int) and error["status"] >= 500)
            )
            candidate = self.probe_name_candidate()
            self.journal.try_write("create_product", "write_failed", state="blocked", detail={
                "error": error, "candidate": candidate, "ambiguous": True,
            })
            raise StageError("blocked", "create_product",
                             "创建产品失败；按约定不重放，同名候选只登记不认领",
                             {"error": error, "candidate": candidate}) from exc
        document = unwrap(result) if isinstance(result, dict) else {}
        product_id = document.get("product_id") or document.get("id")
        self.ensure(bool(product_id), name="create_product.product_id", expected="非空产品 ID",
                    actual=product_id, state="blocked",
                    message="创建返回缺少 product_id，不把未返回结果当作已创建")
        self.product_id = str(product_id)
        self.create_unknown = False
        record = {
            "product_id": self.product_id,
            "data_source": document.get("data_source"),
            "accounts": document.get("accounts"),
        }
        self.created["products"].append(record)
        self.journal.write("create_product", "created", state="passed", detail=record)
        self.record_step("create_product", record)

    def step_create_readback(self) -> None:
        """读回产品配置，确认混合来源、关闭覆盖、手动份额、空账户与开始日。"""
        payload = self.fetch("readback_product", "products.get",
                             lambda: rqamsh.products.get(self.product_id))
        product = unwrap(payload)
        self.ensure(isinstance(product, dict), name="readback_product.shape", expected="对象",
                    actual=type(product).__name__)
        self.ensure(product.get("name") == self.args.name, name="readback_product.name",
                    expected=self.args.name, actual=product.get("name"))
        self.ensure(product.get("start_date") == self.args.start_date,
                    name="readback_product.start_date", expected=self.args.start_date,
                    actual=product.get("start_date"))
        self.ensure(product.get("label") == "paper", name="readback_product.label",
                    expected="paper", actual=product.get("label"), state="blocked",
                    message="产品标签不是 paper；不把模拟交易标签当作本路线前提")
        self.ensure(product.get("data_source") == "trade_and_valuation_report",
                    name="readback_product.data_source", expected="trade_and_valuation_report",
                    actual=product.get("data_source"), state="blocked",
                    message="创建后的数据源不是混合来源；后续只读报告的假设不成立")
        self.ensure(product.get("unit_policy") == "manual", name="readback_product.unit_policy",
                    expected="manual", actual=product.get("unit_policy"), state="blocked",
                    message="份额策略不是 manual；持仓表建立份额的前提不成立")
        self.ensure(product.get("auto_overwrite") is False, name="readback_product.auto_overwrite",
                    expected=False, actual=product.get("auto_overwrite"), state="blocked",
                    message="自动覆盖未关闭；报告保存即采用的假设不成立")
        self.ensure(product.get("calendar") == "exchange", name="readback_product.calendar",
                    expected="exchange", actual=product.get("calendar"), state="blocked",
                    message="估值日历不是 exchange；日期口径与构造输入不一致")
        self.ensure(product.get("investment_category") == "equity",
                    name="readback_product.investment_category", expected="equity",
                    actual=product.get("investment_category"))
        self.ensure(product.get("strategy_category") == STRATEGY_CATEGORY,
                    name="readback_product.strategy_category", expected=STRATEGY_CATEGORY,
                    actual=product.get("strategy_category"))
        benchmark = product.get("benchmark")
        benchmark_id = benchmark.get("id") if isinstance(benchmark, dict) else None
        self.ensure(benchmark_id == "000300.XSHG", name="readback_product.benchmark",
                    expected="000300.XSHG", actual=benchmark_id, state="blocked",
                    message="基准不是沪深 300；构造基线与报告口径不一致")
        accounts = product.get("accounts")
        self.ensure(accounts in (None, []), name="readback_product.accounts_empty",
                    expected=[], actual=accounts, state="blocked",
                    message="创建返回了账户；本路线要求账户为空且不由脚本补造")
        self.initial_config = {
            "data_source": product.get("data_source"),
            "auto_overwrite": product.get("auto_overwrite"),
            "unit_policy": product.get("unit_policy"),
            "label": product.get("label"),
            "benchmark": benchmark,
            "calendar": product.get("calendar"),
            "investment_category": product.get("investment_category"),
            "strategy_category": product.get("strategy_category"),
            "start_date": product.get("start_date"),
            "accounts_count": len(accounts or []),
        }
        self.record_step("readback_config", {
            "product": {"id": product.get("id"), "name": product.get("name"),
                        "start_date": product.get("start_date"), "label": product.get("label")},
            "initial_config": self.initial_config,
        })

    def step_baseline(self) -> None:
        """先上传开始日全现金报告并显式 auto，建立估值表覆盖基线；不先等计算。"""
        self.current_stage = "baseline_report"
        pre_upload = self.capture_execution("baseline_upload_pre")
        self.baseline_report_saved = True
        response = self.write_action(
            "baseline_upload", f"valuation_reports.upload {self.args.start_date}",
            lambda: rqamsh.valuation_reports.upload(self.product_id, data=self.baseline_report),
            detail={"date": self.args.start_date,
                    "pre_execution_id": pre_upload.get("execution_id")},
        )
        document = unwrap(response) if isinstance(response, dict) else {}
        baseline_id = document.get("valuation_report_id")
        server_date = document.get("date")
        self.baseline_report_server_date = server_date
        if baseline_id:
            self.baseline_report_id = str(baseline_id)
        record = {"role": "baseline", "date": self.args.start_date,
                  "response_date": server_date,
                  "valuation_report_id": self.baseline_report_id,
                  "is_modified": document.get("is_modified"),
                  "effect_count": document.get("effect_count"),
                  "confirmation_id": document.get("confirmation_id")}
        if self.baseline_report_id:
            self.created["reports"].append(record)
            self.journal.try_write("baseline_upload", "returned", state="passed", detail=record)
        self.ensure(server_date == self.args.start_date, name="baseline_upload.date",
                    expected=self.args.start_date, actual=server_date)
        self.ensure(bool(baseline_id), name="baseline_upload.id", expected="非空报告 ID",
                    actual=baseline_id, state="blocked",
                    message="开始日报告上传缺少 ID；无法证明归属，不继续 auto")
        self.journal.write("baseline_upload", "created", state="passed", detail=record)
        rows = self.read_report_rows("baseline_upload_readback", self.args.start_date,
                                     self.args.start_date)
        matched = [row for row in rows if row.get("date") == self.args.start_date]
        self.ensure(len(matched) == 1
                    and str(matched[0].get("valuation_report_id")) == self.baseline_report_id,
                    name="baseline_upload_readback.record", expected=self.baseline_report_id,
                    actual=[(row.get("date"), row.get("valuation_report_id")) for row in rows])

        pre_auto = self.capture_execution("baseline_auto_pre")
        auto_result = self.write_action(
            "baseline_auto", f"reconciliation.auto {self.args.start_date}",
            lambda: rqamsh.reconciliation.auto(self.product_id, date=self.args.start_date),
            detail={"date": self.args.start_date,
                    "pre_execution_id": pre_auto.get("execution_id")},
        )
        auto_document = unwrap(auto_result) if isinstance(auto_result, dict) else {}
        auto_effect = auto_document.get("effect_count") if isinstance(auto_document, dict) else None
        auto_record = {"role": "baseline", "date": self.args.start_date,
                       "effect_count": auto_effect,
                       "response_type": type(unwrap(auto_result)).__name__}
        self.created["auto"].append(auto_record)
        self.journal.write("baseline_auto", "write_done", state="passed", detail=auto_record)
        compute = self.wait_new_execution("baseline_auto_compute", pre_auto)
        balances = []
        for date_text in self.dates_in_range():
            balance = self.check_balance(
                f"baseline_balance_{date_text}", date_text,
                equity=self.args.init_amount, units=self.args.init_amount, nav=1.0, acc=1.0,
                cash=self.args.init_amount,
            )
            balances.append({"date": balance["date"], "total_equity": balance["total_equity"],
                             "units": balance["units"], "unit_net_value": balance["unit_net_value"],
                             "acc_unit_net_value": balance["acc_unit_net_value"],
                             "positions": balance["positions"]})
        listing = self.read_reconciliation("baseline_list", self.args.start_date,
                                           self.args.range_end)
        entry = self.check_lack("baseline_list", listing["entries"], self.args.start_date,
                                None, with_report=True)
        self.ensure(entry.get("auto_reconciled") is True, name="baseline_list.auto_reconciled",
                    expected=True, actual=entry.get("auto_reconciled"))
        self.ensure(entry.get("done") is True, name="baseline_list.done",
                    expected=True, actual=entry.get("done"))
        self.record_step("baseline", {
            "report": record,
            "auto": auto_record,
            "compute": compute,
            "balances": balances,
            "list": {"date": entry.get("date"), "done": entry.get("done"),
                     "auto_reconciled": entry.get("auto_reconciled"),
                     "lack": entry.get("lack")},
        })

    def step_upload(self) -> None:
        """导入构造型估值报告，读回日期与记录 ID，并确认产品仍未采用报告。"""
        pre_upload = self.capture_execution("target_upload_pre")
        self.report_saved = True
        response = self.write_action(
            "upload_report", f"valuation_reports.upload {self.args.report_date}",
            lambda: rqamsh.valuation_reports.upload(self.product_id, data=self.report),
            detail={"date": self.args.report_date,
                    "pre_execution_id": pre_upload.get("execution_id")},
        )
        document = unwrap(response) if isinstance(response, dict) else {}
        report_id = document.get("valuation_report_id")
        server_date = document.get("date")
        self.report_server_date = server_date
        if report_id:
            self.report_id = str(report_id)
        record = {"role": "target", "date": self.args.report_date, "response_date": server_date,
                  "valuation_report_id": self.report_id,
                  "is_modified": document.get("is_modified"),
                  "effect_count": document.get("effect_count"),
                  "confirmation_id": document.get("confirmation_id")}
        if self.report_id:
            self.created["reports"].append(record)
            self.journal.try_write("upload_report", "returned", state="passed", detail=record)
        self.ensure(server_date == self.args.report_date, name="upload_report.date",
                    expected=self.args.report_date, actual=server_date)
        self.ensure(bool(report_id), name="upload_report.id", expected="非空报告 ID",
                    actual=report_id, state="blocked",
                    message="上传返回缺少报告 ID；无法证明子记录归属，不按请求日期删除")
        self.journal.write("upload_report", "created", state="passed", detail=record)
        rows = self.read_report_rows("upload_readback", self.args.report_date, self.args.report_date)
        matched = [row for row in rows if row.get("date") == self.args.report_date]
        self.ensure(len(matched) == 1 and str(matched[0].get("valuation_report_id")) == self.report_id,
                    name="upload_readback.record", expected=self.report_id,
                    actual=[(row.get("date"), row.get("valuation_report_id")) for row in rows])
        if self.args.download_dir is not None:
            self.try_download(matched[0])
        product_payload = self.fetch("upload_config", "products.get 采纳设置",
                                     lambda: rqamsh.products.get(self.product_id))
        product = unwrap(product_payload)
        self.ensure(product.get("auto_overwrite") is False, name="upload_config.auto_overwrite",
                    expected=False, actual=product.get("auto_overwrite"))
        self.record_step("upload_report", {
            "upload": record,
            "list": [{"date": row.get("date"), "valuation_report_id": row.get("valuation_report_id"),
                      "source": row.get("source"), "valuation_level": row.get("valuation_level")}
                     for row in rows],
        })

    def try_download(self, row: dict) -> None:
        """尽力下载本次报告的源文件；不可用时记录原因，不用它代替业务核对。"""
        self.args.download_dir.mkdir(parents=True, exist_ok=True)
        target = self.args.download_dir / f"reconciliation-{self.args.report_date}-{self.report_id}.bin"
        try:
            meta = rqamsh.valuation_reports.download(self.product_id, self.report_id, str(target))
            self.downloads.append({"date": self.args.report_date, "path": str(target),
                                   "state": "downloaded", "bytes": target.stat().st_size,
                                   "meta": meta if isinstance(meta, (str, int, float)) else None})
        except HarnessError as exc:
            self.downloads.append({"date": self.args.report_date, "path": str(target),
                                   "state": "unavailable", "error": safe_error(exc)})

    def step_pre_auto(self) -> None:
        """核对报告已保存但未采用：基准日与次日头寸不变，差异与缺件分类准确。"""
        self.wait_normal("pre_auto_compute")
        first = self.check_balance(
            "pre_auto_balance_report_date", self.args.report_date,
            equity=self.args.init_amount, units=self.args.init_amount, nav=1.0, acc=1.0,
            cash=self.args.init_amount,
        )
        second_date = (Date.fromisoformat(self.args.report_date) + timedelta(days=1)).isoformat()
        second = self.check_balance(
            "pre_auto_balance_next_date", second_date,
            equity=self.args.init_amount, units=self.args.init_amount, nav=1.0, acc=1.0,
            cash=self.args.init_amount,
        )
        listing = self.read_reconciliation("pre_auto_list", self.args.start_date,
                                           self.args.range_end)
        entries = listing["entries"]
        observed = sorted(entries)
        self.ensure(all(self.args.start_date <= day <= self.args.range_end for day in observed),
                    name="pre_auto_list.dates_within_range",
                    expected=[self.args.start_date, self.args.range_end], actual=observed,
                    message="对账列表返回区间外日期，拒绝当作本区间结果")
        if (self.args.start_date, self.args.range_end) == ("2026-10-26", "2026-10-30"):
            expected_dates = self.dates_in_range()
            self.ensure(observed == expected_dates, name="pre_auto_list.dates",
                        expected=expected_dates, actual=observed,
                        message="默认核对区间的日期集合与对账列表不一致")
        else:
            expected_dates = observed
            self.ensure(self.args.report_date in entries,
                        name="pre_auto_list.report_date_present", expected=True, actual=False)
        baseline_entry = self.check_lack("pre_auto_baseline_list", entries,
                                         self.args.start_date, None, with_report=True)
        self.ensure(baseline_entry.get("auto_reconciled") is True,
                    name="pre_auto_baseline_list.auto_reconciled", expected=True,
                    actual=baseline_entry.get("auto_reconciled"),
                    message="开始日基线必须仍为自动对账覆盖状态")
        self.ensure(baseline_entry.get("done") is True,
                    name="pre_auto_baseline_list.done", expected=True,
                    actual=baseline_entry.get("done"))
        report_entry = self.check_lack("pre_auto_list", entries, self.args.report_date, None,
                                       with_report=True)
        self.ensure(report_entry.get("done") is False and report_entry.get("auto_reconciled") is False,
                    name="pre_auto_list.report_date.flags", expected={"done": False, "auto_reconciled": False},
                    actual={"done": report_entry.get("done"),
                            "auto_reconciled": report_entry.get("auto_reconciled")})
        nav_pair = report_entry.get("unit_net_value") or {}
        acc_pair = report_entry.get("acc_unit_net_value") or {}
        report_equity = number(self.report.get("total_equity"))
        report_units = number(self.report.get("units"))
        report_nav = number(self.report.get("unit_net_value"))
        report_acc = number(self.report.get("acc_unit_net_value"))
        self.ensure(close_enough(number(nav_pair.get("ams")), 1.0)
                    and close_enough(number(nav_pair.get("valuation_report")), report_nav),
                    name="pre_auto_list.unit_net_value", expected=[1.0, report_nav],
                    actual=[number(nav_pair.get("ams")), number(nav_pair.get("valuation_report"))])
        self.ensure(close_enough(number(acc_pair.get("ams")), 1.0)
                    and close_enough(number(acc_pair.get("valuation_report")), report_acc),
                    name="pre_auto_list.acc_unit_net_value", expected=[1.0, report_acc],
                    actual=[number(acc_pair.get("ams")), number(acc_pair.get("valuation_report"))])
        for date_text in expected_dates:
            if date_text in {self.args.report_date, self.args.start_date}:
                continue
            entry = self.check_lack("pre_auto_list", entries, date_text, "none", with_report=False)
            self.ensure(entry.get("done") is False, name=f"pre_auto_list.{date_text}.done",
                        expected=False, actual=entry.get("done"))
        diff = self.read_diff("pre_auto_diff", self.args.report_date)
        diff_detail = self.check_diff_expected(
            "pre_auto_diff", diff, report_total=report_equity, report_units=report_units,
            report_nav=report_nav, report_acc=report_acc, baseline=self.args.init_amount,
            baseline_nav=1.0)
        self.record_step("pre_auto", {
            "report_balance": {"date": first["date"], "total_equity": first["total_equity"],
                               "units": first["units"], "unit_net_value": first["unit_net_value"],
                               "positions": first["positions"]},
            "next_balance": {"date": second["date"], "total_equity": second["total_equity"],
                             "units": second["units"], "unit_net_value": second["unit_net_value"]},
            "list": {date_text: {"done": entry.get("done"),
                                 "auto_reconciled": entry.get("auto_reconciled"),
                                 "lack": entry.get("lack"),
                                 "has_unit_net_value": "unit_net_value" in entry}
                     for date_text, entry in sorted(entries.items())},
            "diff": diff,
            "diff_groups": diff_detail["groups"],
        })

    def step_mark(self) -> None:
        """只对报告日写入人工完成标记并读回；effect_count 为 0 也可能只是新建。"""
        pre_mark = self.capture_execution("mark_pre")
        payload = self.write_action(
            "mark_report_date", f"reconciliation.mark {self.args.report_date}",
            lambda: rqamsh.reconciliation.mark(
                self.product_id, date=self.args.report_date, done=True,
                description=self.args.description,
            ),
            detail={"date": self.args.report_date, "done": True,
                    "pre_execution_id": pre_mark.get("execution_id")},
        )
        receipt = unwrap(payload)
        effect = receipt.get("effect_count") if isinstance(receipt, dict) else None
        self.created["marks"].append({"date": self.args.report_date, "effect_count": effect})
        listing = self.read_reconciliation("mark_readback", self.args.report_date,
                                           self.args.report_date)
        entry = self.check_lack("mark_readback", listing["entries"], self.args.report_date,
                                None, with_report=True)
        self.ensure(entry.get("done") is True, name="mark_readback.done", expected=True,
                    actual=entry.get("done"))
        self.ensure(entry.get("description") == self.args.description,
                    name="mark_readback.description", expected=self.args.description,
                    actual=entry.get("description"))
        self.ensure(entry.get("auto_reconciled") is False, name="mark_readback.auto_reconciled",
                    expected=False, actual=entry.get("auto_reconciled"))
        self.record_step("mark", {
            "effect_count": effect,
            "effect_count_note": "0 只表示本次新建标记，不证明状态未变",
            "readback": {"date": entry.get("date"), "done": entry.get("done"),
                         "description": entry.get("description"),
                         "auto_reconciled": entry.get("auto_reconciled")},
        })

    def step_auto(self) -> None:
        """只对报告日采用自动对账，等待新执行重算后核对报告日与次日头寸、状态和差异。"""
        pre_auto = self.capture_execution("target_auto_pre")
        call_result = self.write_action(
            "auto_report_date", f"reconciliation.auto {self.args.report_date}",
            lambda: rqamsh.reconciliation.auto(self.product_id, date=self.args.report_date),
            detail={"date": self.args.report_date,
                    "pre_execution_id": pre_auto.get("execution_id")},
        )
        response = unwrap(call_result)
        self.created["auto"].append({"role": "target", "date": self.args.report_date,
                                     "effect_count": response.get("effect_count") if isinstance(response, dict) else None,
                                     "response": response if isinstance(response, (str, int, float, bool)) else None})
        self.journal.write("auto_report_date", "write_done", state="passed",
                           detail={"date": self.args.report_date,
                                   "response": response if isinstance(response, (str, int, float, bool)) else None})
        compute = self.wait_new_execution("auto_compute", pre_auto)
        report_equity = number(self.report.get("total_equity"))
        report_units = number(self.report.get("units"))
        report_nav = number(self.report.get("unit_net_value"))
        report_acc = number(self.report.get("acc_unit_net_value"))
        report_cash = None
        for row in self.report.get("positions") or []:
            if str(row.get("order_book_id")) == "CNY":
                report_cash = number(row.get("market_value"))
        self.ensure(report_cash is not None, name="auto.report_cash", expected="CNY 现金持仓",
                    actual=None, state="blocked")
        report_date = self.args.report_date
        next_date = (Date.fromisoformat(report_date) + timedelta(days=1)).isoformat()
        first = self.check_balance("auto_balance_report_date", report_date, equity=report_equity,
                                   units=report_units, nav=report_nav, acc=report_acc,
                                   cash=report_cash)
        second = self.check_balance("auto_balance_next_date", next_date, equity=report_equity,
                                    units=report_units, nav=report_nav, acc=report_acc,
                                    cash=report_cash)
        listing = self.read_reconciliation("auto_list", self.args.start_date, self.args.range_end)
        entry = self.check_lack("auto_list", listing["entries"], report_date, None,
                                with_report=True)
        self.ensure(entry.get("auto_reconciled") is True, name="auto_list.auto_reconciled",
                    expected=True, actual=entry.get("auto_reconciled"))
        self.ensure(entry.get("done") is True, name="auto_list.done", expected=True,
                    actual=entry.get("done"))
        nav_pair = entry.get("unit_net_value") or {}
        acc_pair = entry.get("acc_unit_net_value") or {}
        self.ensure(close_enough(number(nav_pair.get("ams")), report_nav)
                    and close_enough(number(nav_pair.get("valuation_report")), report_nav),
                    name="auto_list.unit_net_value", expected=report_nav,
                    actual=[number(nav_pair.get("ams")), number(nav_pair.get("valuation_report"))])
        self.ensure(close_enough(number(acc_pair.get("ams")), report_acc)
                    and close_enough(number(acc_pair.get("valuation_report")), report_acc),
                    name="auto_list.acc_unit_net_value", expected=report_acc,
                    actual=[number(acc_pair.get("ams")), number(acc_pair.get("valuation_report"))])
        diff = self.read_diff("auto_diff", report_date)
        diff_detail = self.check_diff_equal("auto_diff", diff, report_total=report_equity,
                                           report_units=report_units, report_nav=report_nav,
                                           report_acc=report_acc)
        self.record_step("auto", {
            "compute": compute,
            "report_balance": {"date": first["date"], "total_equity": first["total_equity"],
                               "units": first["units"], "unit_net_value": first["unit_net_value"],
                               "acc_unit_net_value": first["acc_unit_net_value"],
                               "positions": first["positions"]},
            "next_balance": {"date": second["date"], "total_equity": second["total_equity"],
                             "units": second["units"], "unit_net_value": second["unit_net_value"]},
            "list": {"date": entry.get("date"), "done": entry.get("done"),
                     "auto_reconciled": entry.get("auto_reconciled"), "lack": entry.get("lack"),
                     "unit_net_value": entry.get("unit_net_value"),
                     "acc_unit_net_value": entry.get("acc_unit_net_value")},
            "diff": diff,
            "diff_groups": diff_detail["groups"],
        })

    def step_undo(self) -> None:
        """只撤销报告日自动对账，等待重算后核对恢复金额与 done 复位。"""
        pre_undo = self.capture_execution("undo_pre")
        payload = self.write_action(
            "undo_report_date", f"reconciliation.undo_auto {self.args.report_date}",
            lambda: rqamsh.reconciliation.undo_auto(self.product_id, date=self.args.report_date),
            detail={"date": self.args.report_date,
                    "pre_execution_id": pre_undo.get("execution_id")},
        )
        receipt = unwrap(payload)
        effect = receipt.get("effect_count") if isinstance(receipt, dict) else None
        self.created["undo"].append({"role": "target", "date": self.args.report_date,
                                     "effect_count": effect})
        self.journal.write("undo_report_date", "write_done", state="passed",
                           detail={"date": self.args.report_date, "effect_count": effect})
        compute = self.wait_new_execution("undo_compute", pre_undo)
        report_date = self.args.report_date
        next_date = (Date.fromisoformat(report_date) + timedelta(days=1)).isoformat()
        first = self.check_balance("undo_balance_report_date", report_date,
                                   equity=self.args.init_amount, units=self.args.init_amount,
                                   nav=1.0, acc=1.0, cash=self.args.init_amount)
        second = self.check_balance("undo_balance_next_date", next_date,
                                    equity=self.args.init_amount, units=self.args.init_amount,
                                    nav=1.0, acc=1.0, cash=self.args.init_amount)
        listing = self.read_reconciliation("undo_list", self.args.start_date, self.args.range_end)
        baseline_entry = self.check_lack("undo_baseline_list", listing["entries"],
                                         self.args.start_date, None, with_report=True)
        self.ensure(baseline_entry.get("auto_reconciled") is True,
                    name="undo_baseline_list.auto_reconciled", expected=True,
                    actual=baseline_entry.get("auto_reconciled"),
                    message="撤销报告日覆盖不应撤销开始日基线")
        self.ensure(baseline_entry.get("done") is True, name="undo_baseline_list.done",
                    expected=True, actual=baseline_entry.get("done"))
        entry = self.check_lack("undo_list", listing["entries"], report_date, None,
                                with_report=True)
        self.ensure(entry.get("auto_reconciled") is False, name="undo_list.auto_reconciled",
                    expected=False, actual=entry.get("auto_reconciled"))
        self.ensure(entry.get("done") is False, name="undo_list.done_reset", expected=False,
                    actual=entry.get("done"),
                    message="撤销自动对账应把该日 done 复位为 false，包括此前人工标记")
        report_nav = number(self.report.get("unit_net_value"))
        nav_pair = entry.get("unit_net_value") or {}
        self.ensure(close_enough(number(nav_pair.get("ams")), 1.0)
                    and close_enough(number(nav_pair.get("valuation_report")), report_nav),
                    name="undo_list.unit_net_value", expected=[1.0, report_nav],
                    actual=[number(nav_pair.get("ams")), number(nav_pair.get("valuation_report"))])
        rows = self.read_report_rows("undo_report_readback", report_date, report_date)
        self.ensure(any(row.get("date") == report_date
                        and str(row.get("valuation_report_id")) == self.report_id for row in rows),
                    name="undo_report_readback.present", expected=self.report_id,
                    actual=[row.get("valuation_report_id") for row in rows],
                    message="undo_auto 只撤销覆盖输入，不应删除报告本身")
        diff = self.read_diff("undo_diff", report_date)
        diff_detail = self.check_diff_expected(
            "undo_diff", diff, report_total=number(self.report.get("total_equity")),
            report_units=number(self.report.get("units")), report_nav=report_nav,
            report_acc=number(self.report.get("acc_unit_net_value")),
            baseline=self.args.init_amount, baseline_nav=1.0)
        self.record_step("undo", {
            "effect_count": effect,
            "effect_count_note": "删除条数不代表金额已恢复，恢复以头寸报表为准",
            "compute": compute,
            "report_balance": {"date": first["date"], "total_equity": first["total_equity"],
                               "units": first["units"], "unit_net_value": first["unit_net_value"],
                               "positions": first["positions"]},
            "next_balance": {"date": second["date"], "total_equity": second["total_equity"],
                             "units": second["units"], "unit_net_value": second["unit_net_value"]},
            "list": {"date": entry.get("date"), "done": entry.get("done"),
                     "auto_reconciled": entry.get("auto_reconciled"),
                     "unit_net_value": entry.get("unit_net_value")},
            "diff": diff,
            "diff_groups": diff_detail["groups"],
        })

    def dates_in_range(self) -> list[str]:
        """按核对区间枚举自然日，仅用于与对账日集合比较，不替代交易日判断。"""
        start = Date.fromisoformat(self.args.start_date)
        end = Date.fromisoformat(self.args.range_end)
        return [(start + timedelta(days=offset)).isoformat()
                for offset in range((end - start).days + 1)]

    # ---------------------------------------------------------------- 清理

    def product_visible(self):
        """只读判断产品是否仍可解析；无法判断时返回 None，不当作已删除。"""
        try:
            rqamsh.products.get(self.product_id)
            return True
        except HarnessError as exc:
            error = safe_error(exc)
            if error["code"] in {"resource_not_found", "not_found"} or error["status"] == 404:
                return False
            return None

    def cleanup_report(self, summary: dict, *, key: str, role: str, date_text: str,
                       report_id: str | None, server_date: str | None, saved: bool) -> None:
        """只删除可证明归属的本次报告；删除前核对当前 ID、日期与父产品。"""
        state = {"role": role, "date": date_text, "state": "pending"}
        if not saved:
            state["state"] = "not_created"
            summary[key] = state
            return
        if self.journal_broken:
            state["reason"] = "journal_unavailable"
            summary[key] = state
            return
        if not report_id or not server_date:
            state["reason"] = "child_id_unverified"
            summary[key] = state
            return
        if server_date != date_text:
            state["reason"] = "server_date_mismatch"
            state["server_date"] = server_date
            summary[key] = state
            return
        stage = f"cleanup_{key}"
        try:
            self.journal.write(stage, "write_intent", state="running",
                               detail={"label": f"valuation_reports.delete {date_text}",
                                       "role": role, "report_id": report_id})
        except JournalUnavailable:
            self.journal_broken = True
            state["reason"] = "journal_unavailable"
            summary[key] = state
            return
        try:
            rows = rqamsh.valuation_reports.list(self.product_id,
                                                 start_date=date_text, end_date=date_text)
            document = unwrap(rows)
            rows = document if isinstance(document, list) else []
        except Exception as exc:  # noqa: BLE001 - 删除前读回失败就不删除
            state["reason"] = "read_failed_before_delete"
            state["error"] = safe_error(exc)
            summary[key] = state
            self.journal.try_write(stage, "write_aborted", state="pending", detail=state)
            return
        matches = [row for row in rows
                   if isinstance(row, dict) and row.get("date") == date_text]
        ours = [row for row in matches
                if str(row.get("valuation_report_id")) == report_id]
        parent = ours[0].get("product_id") if ours else None
        if len(matches) != 1 or len(ours) != 1 or parent not in (None, self.product_id):
            state["reason"] = "current_child_mismatch"
            state["current_ids"] = [row.get("valuation_report_id") for row in matches]
            state["current_parent"] = parent
            summary[key] = state
            self.journal.try_write(stage, "write_aborted", state="pending", detail=state)
            return
        try:
            result = rqamsh.valuation_reports.delete(self.product_id, [date_text])
            receipt = unwrap(result)
            state["effect_count"] = receipt.get("effect_count") if isinstance(receipt, dict) else None
        except Exception as exc:  # noqa: BLE001 - 删除请求结果不明，保留 pending
            state["reason"] = "delete_failed"
            state["error"] = safe_error(exc)
            summary[key] = state
            self.journal.try_write(stage, "write_aborted", state="pending", detail=state)
            return
        try:
            rows = rqamsh.valuation_reports.list(self.product_id,
                                                 start_date=date_text, end_date=date_text)
            document = unwrap(rows)
            rows = document if isinstance(document, list) else []
            remaining = [row for row in rows
                         if isinstance(row, dict) and row.get("date") == date_text
                         and str(row.get("valuation_report_id")) == report_id]
            state["remaining"] = len(remaining)
            state["other_records_on_date"] = len([
                row for row in rows
                if isinstance(row, dict) and row.get("date") == date_text
                and str(row.get("valuation_report_id")) != report_id
            ])
            if remaining:
                state["reason"] = "record_still_present"
            else:
                state["state"] = "deleted"
        except Exception as exc:  # noqa: BLE001 - 删除后读回失败不能确认清理
            state["reason"] = "read_failed_after_delete"
            state["error"] = safe_error(exc)
        summary[key] = state
        self.journal.try_write(stage, "write_done", state=state.get("state", "pending"),
                               detail=state)

    def cleanup_product(self, summary: dict) -> None:
        """只删除本次创建返回的产品 ID；创建不明时保留 pending，不按名称认领。"""
        state = {"product_id": self.product_id, "state": "pending"}
        if not self.product_id:
            if self.create_unknown:
                state["reason"] = "create_result_unknown"
                state["candidate_only"] = True
            else:
                state["state"] = "not_created"
            summary["product"] = state
            return
        if self.journal_broken:
            state["reason"] = "journal_unavailable"
            summary["product"] = state
            return
        try:
            self.journal.write("cleanup_product", "write_intent", state="running",
                               detail={"label": "products.delete",
                                       "product_id": self.product_id})
        except JournalUnavailable:
            self.journal_broken = True
            state["reason"] = "journal_unavailable"
            summary["product"] = state
            return
        try:
            result = rqamsh.products.delete(self.product_id)
            receipt = unwrap(result)
            state["route"] = "products.delete"
            state["result"] = {"effect_count": receipt.get("effect_count")
                               if isinstance(receipt, dict) else None}
        except Exception as exc:  # noqa: BLE001 - 删除失败保留待清理，不重试
            state["reason"] = "delete_failed"
            state["error"] = safe_error(exc)
        visible = self.product_visible()
        state["visible"] = visible
        if visible is False:
            state["state"] = "deleted"
        elif state.get("state") != "pending":
            state["state"] = "pending"
        summary["product"] = state
        self.journal.try_write("cleanup_product", "write_done", state=state["state"], detail=state)

    def safe_persist(self) -> None:
        """尽力持久化证据；任何存储或中断失败都转为日志失败标志，不抛原始异常。"""
        try:
            self.persist()
        except BaseException:
            self.journal_broken = True

    def safe_cleanup(self) -> None:
        """独立执行清理；任何未预期异常都保留 pending，不向调用方抛 traceback。"""
        try:
            self.cleanup_resources(after_failure=True)
        except BaseException as exc:  # noqa: BLE001
            self.journal.try_write("cleanup", "cleanup_aborted", state="failed",
                                   detail=safe_error(exc))

    def cleanup_resources(self, *, after_failure: bool) -> None:
        """按已确认归属清理子记录与产品；日志失败或归属不明时一律保留 pending。"""
        if getattr(self, "cleanup_started", False):
            return
        self.cleanup_started = True
        self.current_stage = "cleanup"
        summary: dict = {
            "target_report": ({"state": "pending", "reason": "not_started"}
                              if self.report_saved else {"state": "not_created"}),
            "baseline_report": ({"state": "pending", "reason": "not_started"}
                                if self.baseline_report_saved else {"state": "not_created"}),
            "product": ({"state": "pending", "reason": "create_result_unknown"}
                        if self.create_unknown and not self.product_id else
                        {"state": "pending", "reason": "not_started"}
                        if self.product_id else {"state": "not_created"}),
        }
        storage_error = None
        previous = None
        try:
            previous = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (AttributeError, OSError, ValueError):
            previous = None
        try:
            for key, method in (
                ("target_report", lambda summary: self.cleanup_report(
                    summary, key="target_report", role="target",
                    date_text=self.args.report_date, report_id=self.report_id,
                    server_date=self.report_server_date, saved=self.report_saved)),
                ("baseline_report", lambda summary: self.cleanup_report(
                    summary, key="baseline_report", role="baseline",
                    date_text=self.args.start_date,
                    report_id=self.baseline_report_id,
                    server_date=self.baseline_report_server_date,
                    saved=self.baseline_report_saved)),
                ("product", self.cleanup_product),
            ):
                if self.journal is not None and self.journal.broken:
                    self.journal_broken = True
                if self.journal_broken:
                    if summary[key].get("reason") == "not_started":
                        summary[key]["reason"] = "journal_unavailable"
                    continue
                try:
                    method(summary)
                except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001
                    summary[key] = {"state": "pending", "reason": "cleanup_exception",
                                    "error": safe_error(exc)}
                    self.journal.try_write(key, "write_aborted", state="pending",
                                           detail=summary[key])
                if self.journal is not None and self.journal.broken:
                    self.journal_broken = True
                if self.journal_broken and summary[key].get("reason") == "not_started":
                    summary[key]["reason"] = "journal_unavailable"
            if self.journal_broken:
                for key in ("target_report", "baseline_report", "product"):
                    if summary[key].get("reason") == "not_started":
                        summary[key]["reason"] = "journal_unavailable"
            self.cleanup = summary
            if self.journal is not None and self.journal.broken:
                self.journal_broken = True
            if self.journal_broken:
                storage_error = {"type": "JournalUnavailable", "code": "journal_unavailable",
                                 "status": None}
            self.cleanup_storage_error = storage_error
            try:
                self.persist()
            except BaseException as exc:  # noqa: BLE001 - 存储失败必须进入终态
                storage_error = safe_error(exc)
                self.cleanup_storage_error = storage_error
                self.journal_broken = True
        finally:
            if previous is not None:
                try:
                    signal.signal(signal.SIGINT, previous)
                except (OSError, ValueError):
                    pass
        complete = storage_error is None \
            and summary["target_report"]["state"] in {"deleted", "not_created", "absent"} \
            and summary["baseline_report"]["state"] in {"deleted", "not_created", "absent"} \
            and summary["product"]["state"] in {"deleted", "not_created"}
        self.journal.try_write("cleanup", "summary",
                               state="passed" if complete else "pending", detail=summary)
        if self.journal is not None and self.journal.broken:
            self.journal_broken = True
            if self.cleanup_storage_error is None:
                self.cleanup_storage_error = {"type": "JournalUnavailable",
                                              "code": "journal_unavailable", "status": None}
                storage_error = self.cleanup_storage_error
            complete = False
        if not complete and not after_failure:
            raise StageError("failed", "cleanup",
                             "清理未全部确认或终态存储失败，不能标记完成",
                             {"cleanup": summary,
                              "storage_error": self.cleanup_storage_error})

    def run(self) -> str:
        """按固定顺序执行各阶段，始终尝试清理并写入终态证据。"""
        token = os.environ.get("RQAMSH_TOKEN", "").strip()
        if not token:
            self.state = "blocked"
            self.failure = {"state": "blocked", "stage": "credentials",
                            "message": "环境变量 RQAMSH_TOKEN 为空", "detail": {}}
            self.finalize()
            return self.state
        try:
            self.journal = Journal(self.args.journal, self.run_id, {
                "name": self.args.name,
                "base_url": self.args.base_url,
                "workspace_id": self.args.workspace_id,
                "report_date": self.args.report_date,
                "demo_sha256": self.demo_sha256,
                "report_sha256": self.report_digest,
            })
            self.evidence = Evidence(self.args.report, self.document())
        except (OSError, JournalUnavailable) as exc:
            self.state = "blocked"
            self.failure = {"state": "blocked", "stage": "setup",
                            "message": "日志或证据文件无法独占创建",
                            "detail": safe_error(exc)}
            self.finalize()
            return self.state
        except KeyboardInterrupt:
            self.state = "failed"
            self.failure = {"state": "failed", "stage": "setup",
                            "message": "启动阶段收到中断；未发起业务写入", "detail": {}}
            self.finalize()
            return self.state
        try:
            try:
                rqamsh.init(self.args.base_url, self.args.workspace_id, token=token)
                self.step_target()
                self.step_name_free()
                self.step_create()
                self.step_create_readback()
                self.step_baseline()
                self.step_upload()
                self.step_pre_auto()
                self.step_mark()
                self.step_auto()
                self.step_undo()
                self.cleanup_resources(after_failure=False)
                self.state = "passed"
            except StageError as exc:
                self.state = exc.state
                self.failure = exc.as_dict()
                self.steps.append({"stage": exc.stage, "state": exc.state, "ok": False,
                                   "detail": exc.detail})
                self.journal.try_write(exc.stage, "stage_failed", state=exc.state,
                                       detail=exc.as_dict())
                self.safe_persist()
                self.safe_cleanup()
            except KeyboardInterrupt:
                previous = None
                try:
                    previous = signal.getsignal(signal.SIGINT)
                    signal.signal(signal.SIGINT, signal.SIG_IGN)
                except (AttributeError, OSError, ValueError):
                    previous = None
                try:
                    self.interrupted = True
                    self.state = "failed"
                    self.failure = {"state": "failed", "stage": self.current_stage,
                                    "message": "收到中断；停止后续业务写入，仅清理已确认归属的资源",
                                    "detail": {}}
                    self.steps.append({"stage": self.current_stage, "state": "failed",
                                       "ok": False, "detail": self.failure["detail"]})
                    self.journal.try_write(self.current_stage, "request_interrupted",
                                           state="failed", detail={"stage": self.current_stage})
                    self.journal.try_write("interrupt", "terminal", state="failed",
                                           detail={"stage": self.current_stage})
                    self.safe_persist()
                    self.safe_cleanup()
                finally:
                    if previous is not None:
                        try:
                            signal.signal(signal.SIGINT, previous)
                        except (OSError, ValueError):
                            pass
            except JournalUnavailable as exc:
                self.journal_broken = True
                self.state = "blocked"
                self.failure = {"state": "blocked", "stage": self.current_stage,
                                "message": "任务日志写入失败；停止后续业务写入",
                                "detail": {"journal_error": str(exc)}}
                self.steps.append({"stage": self.current_stage, "state": "blocked", "ok": False,
                                   "detail": self.failure["detail"]})
                self.safe_cleanup()
            except Exception as exc:  # noqa: BLE001 - 任何未预期异常都必须落失败终态
                self.state = "failed"
                self.failure = {"state": "failed", "stage": self.current_stage,
                                "message": "未预期异常；停止后续业务写入并清理已知资源",
                                "detail": safe_error(exc)}
                self.steps.append({"stage": self.current_stage, "state": "failed", "ok": False,
                                   "detail": self.failure["detail"]})
                self.journal.try_write(self.current_stage, "unexpected_error", state="failed",
                                       detail=self.failure["detail"])
                self.safe_persist()
                self.safe_cleanup()
        finally:
            try:
                rqamsh.close()
            except BaseException:
                pass
            final = {"evidence": False, "journal": False}
            try:
                final = self.write_terminal()
            except BaseException:
                pass
            if not (final.get("evidence") and final.get("journal")):
                self.finalize_error = final
            if self.state == "passed" and not (
                    final.get("evidence") and final.get("journal")):
                self.state = "failed"
                self.failure = {"state": "failed", "stage": "finalize",
                                "message": "终态证据或日志写入失败，不能标记通过",
                                "detail": final}
                self.steps.append({"stage": "finalize", "state": "failed", "ok": False,
                                   "detail": final})
                try:
                    retry = self.write_terminal()
                except BaseException:
                    retry = {"evidence": False, "journal": False}
                if not (retry.get("evidence") and retry.get("journal")):
                    self.finalize_error = retry
            try:
                self.close_outputs()
            except BaseException:
                pass
        return self.state

    def write_terminal(self) -> dict:
        """写入终态证据与日志但不关闭句柄，返回 evidence/journal 是否落盘。"""
        result = {"evidence": False, "journal": False}
        previous = None
        try:
            previous = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (AttributeError, OSError, ValueError):
            previous = None
        try:
            try:
                self.persist()
                result["evidence"] = True
            except BaseException:
                pass
            if self.journal is not None:
                try:
                    result["journal"] = bool(self.journal.terminal(self.state, {
                        "state": self.state,
                        "product_id": self.product_id,
                        "report_id": self.report_id,
                        "baseline_report_id": self.baseline_report_id,
                        "cleanup": self.cleanup,
                    }))
                except BaseException:
                    result["journal"] = False
        finally:
            if previous is not None:
                try:
                    signal.signal(signal.SIGINT, previous)
                except (OSError, ValueError):
                    pass
        return result

    def close_outputs(self) -> None:
        """独立关闭日志与证据句柄；任一步失败都不阻止另一项关闭。"""
        if self.journal is not None:
            try:
                self.journal.close()
            except BaseException:
                pass
        if self.evidence is not None:
            try:
                self.evidence.close()
            except BaseException:
                pass

    def finalize(self) -> dict:
        """写入终态并关闭句柄；用于输出初始化失败等无后续重试的收尾。"""
        result = self.write_terminal()
        self.close_outputs()
        return result

    def stdout(self) -> dict:
        """整理命令行输出，只包含状态与本次已知资源 ID。"""
        return {
            "state": self.state,
            "run_id": self.run_id,
            "name": self.args.name,
            "product_id": self.product_id,
            "report_id": self.report_id,
            "baseline_report_id": self.baseline_report_id,
            "journal": str(self.args.journal),
            "report": str(self.args.report),
            "cleanup": self.cleanup,
            "cleanup_storage_error": self.cleanup_storage_error,
            "finalize_error": self.finalize_error,
            "failure": self.failure,
        }


def build_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--base-url", required=True, help="测试部署 API 根地址")
    parser.add_argument("--workspace-id", required=True, help="专用测试工作空间 ID")
    parser.add_argument("--name", required=True, help=f"专用产品名称，形如 {NAME_PREFIX}<8 位十六进制>")
    parser.add_argument("--confirm", required=True, help="写入确认，必须与 --name 完全一致")
    parser.add_argument("--journal", type=Path, required=True, help="只增 JSONL 运行日志路径（必须不存在）")
    parser.add_argument("--report", type=Path, required=True, help="JSON 证据路径（必须不存在）")
    parser.add_argument("--start-date", default="2026-10-26", help="产品开始日期，也是基线报告日期；必须早于报告日")
    parser.add_argument("--report-date", default="2026-10-28", help="目标报告与对账日期；与开始日必须是两个不同日期")
    parser.add_argument("--range-end", default="2026-10-30", help="对账状态核对区间截止日")
    parser.add_argument("--init-amount", type=float, default=1000000.0, help="基线现金与份额金额")
    parser.add_argument("--description", default="构造测试已核对", help="人工对账标记备注")
    parser.add_argument("--report-json", type=Path, help="可选的构造型报告 JSON；省略使用内置构造输入")
    parser.add_argument("--download-dir", type=Path, help="可选下载目录；只读下载失败不阻断业务")
    parser.add_argument("--wait-seconds", type=float, default=300.0, help="单次计算状态等待上限")
    parser.add_argument("--poll-seconds", type=float, default=5.0, help="计算状态轮询间隔")
    parser.add_argument("--allow-writes", action="store_true", help="确认执行真实写入与清理")
    parser.add_argument("--check", action="store_true", help="只校验参数与构造输入，不连接服务")
    return parser


def main(argv=None) -> int:
    """解析参数、执行一次运行并输出脱敏终态摘要。"""
    args = build_parser().parse_args(argv)
    try:
        report = verify_arguments(args)
    except GuardError as exc:
        print(json.dumps({"state": "invalid", "message": str(exc)}, ensure_ascii=False))
        return 2
    if args.check:
        print(json.dumps({"state": "checked", "name": args.name,
                          "create_payload": create_payload(args.name, args.start_date),
                          "baseline_report": baseline_report(args.start_date, args.init_amount),
                          "report_date": args.report_date, "report": report},
                         ensure_ascii=False))
        return 0
    run_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
    demo = ReconciliationControls(args, report, run_id)
    try:
        demo.args.journal.parent.mkdir(parents=True, exist_ok=True)
        demo.args.report.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(json.dumps({"state": "invalid", "message": "证据目录不可创建",
                          "error": safe_error(exc)}, ensure_ascii=False))
        return 2
    try:
        state = demo.run()
    except KeyboardInterrupt:
        print(json.dumps({"state": "failed", "message": "收到中断；未能完成收尾",
                          "product_id": demo.product_id, "report_id": demo.report_id},
                         ensure_ascii=False))
        return 130
    print(json.dumps(demo.stdout(), ensure_ascii=False, default=str))
    return {"passed": 0, "failed": 1, "blocked": 2}.get(state, 1)


if __name__ == "__main__":
    sys.exit(main())
