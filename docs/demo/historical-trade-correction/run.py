"""D12 历史流水更正：建立流水基线、精确更正并核对后续估值。

流程：创建专用模拟产品 → 只读留底 → 导入两笔构造且费用为 0 的 open_api 买入 →
读回更正前头寸 → 只更正第一笔的数量与价格 → 读回更正后头寸与计算状态 →
核对更正日前后差异 → 按创建返回的产品 ID 清理专用产品。

凭据只从环境变量读取，不打印、不写入证据文件。脚本要求显式测试目标、确认口令与
不可覆盖的运行记录文件；不自动重试任何写操作；异常、中断和清理失败都落终态。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import rqamsh
from rqamsh.errors import HarnessError

TOKEN_ENV = "RQAMSH_TOKEN"
BASE_ENV = "RQAMSH_BASE_URL"
WORKSPACE_ENV = "RQAMSH_WORKSPACE_ID"

CONFIRM_TOKEN = "create-upload-update-delete"
NAME_PREFIX = "harness-demo-"
NAME_MARKER = "correction"

START_DATE = "2026-10-26"
TRADE_DATE = "2026-10-28"
BALANCE_DATES = ("2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30")
EARLIER_DATES = ("2026-10-26", "2026-10-27")
LATER_DATES = ("2026-10-28", "2026-10-29", "2026-10-30")

BENCHMARK = "index,000300.XSHG"
INIT_AMOUNT = 1_000_000.0
STRATEGY_CATEGORY = "stock_long"

TARGET_ORDER_BOOK_ID = "000001.XSHE"
OTHER_ORDER_BOOK_ID = "600519.XSHG"
TARGET_TRADE = {
    "datetime": "2026-10-28 10:00:00",
    "transaction_type": "buy",
    "order_book_id": TARGET_ORDER_BOOK_ID,
    "asset_class": "stock",
    "price": 10.0,
    "quantity": 100.0,
    "commission": 0.0,
    "tax": 0.0,
    "other_fees": 0.0,
}
OTHER_TRADE = {
    "datetime": "2026-10-28 10:05:00",
    "transaction_type": "buy",
    "order_book_id": OTHER_ORDER_BOOK_ID,
    "asset_class": "stock",
    "price": 1000.0,
    "quantity": 100.0,
    "commission": 0.0,
    "tax": 0.0,
    "other_fees": 0.0,
}
CORRECTION = {"quantity": 120.0, "price": 11.0}

TARGET_ALLOWED_CHANGES = ("quantity", "price")
TARGET_MAINTENANCE_FIELDS = ("inserted_datetime",)
SERVER_DERIVED_FIELDS = ("estimated_delta_cash",)

TOLERANCE = 0.02
NAV_TOLERANCE = "0.000000001"
BEIJING = dt.timezone(dt.timedelta(hours=8))
CREATE_WINDOW_BEFORE = dt.timedelta(minutes=5)
CREATE_WINDOW_AFTER = dt.timedelta(minutes=10)

CASH_ASSET_CLASSES = (
    "current_deposit",
    "reservation_deposit",
    "refundable_deposit",
    "securities_settlement_accounts",
    "dividend_receivable",
    "other_interest_receivable",
    "subscription_receivable",
    "other_receivable",
    "other_asset",
    "reverse_repo_accrued_interest",
    "money_market_fund",
)


class PersistenceError(Exception):
    """运行记录写入失败；业务必须停止后续写，但清理与标准输出仍需独立完成。"""


class Journal:
    """独占创建的追加式运行记录；每个事件立即落盘，不覆盖既有文件。"""

    def __init__(self, path: str):
        """以排他方式打开记录文件；已存在时拒绝启动。"""
        self.path = Path(path)
        self._handle = self.path.open("x", encoding="utf-8")
        self._closed = False
        self.failed = False

    def record(self, event: str, **fields: object) -> None:
        """追加事件并强制落盘；任何失败都标记记录不可用并抛持久化错误。"""
        if self._closed or self.failed:
            raise PersistenceError("journal_unavailable")
        payload = {
            "at": dt.datetime.now(BEIJING).isoformat(),
            "event": event,
            **fields,
        }
        try:
            self._handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
            self._handle.flush()
            os.fsync(self._handle.fileno())
        except (KeyboardInterrupt, SystemExit):
            self.failed = True
            raise
        except BaseException:
            self.failed = True
            raise PersistenceError("journal_write_failed") from None

    def try_record(self, event: str, **fields: object) -> str:
        """终态阶段尽力写入；返回 ok/interrupted/failed，绝不向外抛异常。"""
        try:
            self.record(event, **fields)
            return "ok"
        except (KeyboardInterrupt, SystemExit):
            return "interrupted"
        except BaseException:
            return "failed"

    def close(self) -> None:
        """关闭运行记录文件。"""
        if not self._closed:
            self._closed = True
            self._handle.close()


def required_env(name: str) -> str:
    """读取必填环境变量；缺失时抛结构化错误，不回退到保存的设置文件。"""
    value = os.environ.get(name, "").strip()
    if not value:
        raise HarnessError("missing_env", f"缺少环境变量 {name}")
    return value


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析显式测试目标、专用产品名称、确认口令与证据文件路径。"""
    parser = argparse.ArgumentParser(description="D12 历史流水更正完整演示")
    parser.add_argument("--product-name", required=True, help="本次专用的模拟产品名称，必须唯一")
    parser.add_argument(
        "--expected-base-url",
        required=True,
        help="显式声明的测试部署地址，必须与环境变量完全一致",
    )
    parser.add_argument(
        "--expected-workspace-id",
        required=True,
        help="显式声明的测试空间 ID，必须与环境变量完全一致且为当前令牌成员空间",
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"写入确认口令，必须为 {CONFIRM_TOKEN}",
    )
    parser.add_argument(
        "--evidence-out",
        required=True,
        help="终态报告路径；文件已存在时拒绝运行",
    )
    parser.add_argument(
        "--journal",
        required=True,
        help="追加式运行记录路径；必须先创建且不能覆盖",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=300,
        help="等待估值状态的总体上限秒数，默认 300",
    )
    return parser.parse_args(argv)


def now_beijing() -> dt.datetime:
    """返回北京时间当前时刻，用于创建时间窗口与记录时间戳。"""
    return dt.datetime.now(BEIJING)


def parse_beijing_time(value: object) -> dt.datetime | None:
    """把服务端的本地时间文本按北京时间解析；缺失或不可解析时返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BEIJING)
    return parsed


def decimal_text(value: object) -> str | None:
    """把数值转成十进制字符串；null 保持 None，不补零。"""
    if value is None:
        return None
    return str(Decimal(str(value)))


def close_enough(left: object, right: object, tolerance: str = "0.000000001") -> bool:
    """按十进制容差比较两个数值；同为 null 视为一致，单侧 null 不是 0。"""
    if left is None or right is None:
        return left is None and right is None
    limit = Decimal(tolerance)
    return abs(Decimal(str(left)) - Decimal(str(right))) <= limit


def values_equal(left: object, right: object) -> bool:
    """比较两个记录字段：数值用十进制容差，其余按原值严格比较。"""
    numeric = (int, float) 
    left_numeric = isinstance(left, numeric) and not isinstance(left, bool)
    right_numeric = isinstance(right, numeric) and not isinstance(right, bool)
    if left_numeric and right_numeric:
        return close_enough(left, right)
    if left is None or right is None:
        return left is None and right is None
    return left == right


def record_diff(before: dict, after: dict, *, allowed: tuple[str, ...] = (), ignored: tuple[str, ...] = ()) -> dict:
    """比较两条流水记录的完整字段集合，返回未授权变化；缺键也算变化。"""
    changes = {}
    for key in sorted(set(before) | set(after)):
        if key in allowed or key in ignored:
            continue
        if not values_equal(before.get(key), after.get(key)):
            changes[key] = {"before": safe_value(before.get(key)), "after": safe_value(after.get(key))}
    return changes


SAFE_DIAGNOSTIC_KEYS = ("task_id", "execution_id", "last_state", "last_error_code")
TRADE_PROJECTION = (
    "datetime",
    "trading_date",
    "transaction_type",
    "order_book_id",
    "asset_class",
    "source",
    "price",
    "quantity",
    "commission",
    "tax",
    "other_fees",
    "exchange_rate",
    "currency",
    "foreign_id",
    "account",
    "estimated_delta_cash",
    "_id",
    "id",
)


def safe_error(exc: BaseException) -> dict:
    """把异常收敛为类型、错误码和 HTTP 状态，不保留原始消息、details 或堆栈。"""
    error = {"type": type(exc).__name__}
    code = getattr(exc, "code", None)
    status = getattr(exc, "status", None)
    if isinstance(code, str):
        error["code"] = code[:80]
    if isinstance(status, int):
        error["status"] = status
    diagnostics = getattr(exc, "safe_diagnostics", None)
    if isinstance(diagnostics, dict):
        selected = {key: diagnostics[key] for key in SAFE_DIAGNOSTIC_KEYS if key in diagnostics}
        if selected:
            error["diagnostics"] = selected
    return error


def safe_value(value: object) -> object:
    """把单个字段值裁剪为可公开原样记录的类型；服务文本截断到 200 字符。"""
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def project_trade(record: dict) -> dict:
    """只保留任务需要的流水业务字段，不复制服务端整份记录。"""
    return {field: safe_value(record.get(field)) for field in TRADE_PROJECTION if field in record}


def project_created(created: dict) -> dict:
    """只保留创建回执中的模板与资源 ID。"""
    return {
        "template": created.get("template"),
        "product_id": created.get("product_id"),
        "channel_id": created.get("channel_id"),
        "paper_trading_id": created.get("paper_trading_id"),
    }


def project_upload_result(result: object) -> object:
    """只保留逐项导入的记录 ID 与是否存在错误，不复制服务端错误正文。"""
    if not isinstance(result, list):
        return {"type": type(result).__name__}
    projected = []
    for item in result:
        if not isinstance(item, dict):
            projected.append({"type": type(item).__name__})
            continue
        projected.append(
            {
                "id": item.get("id"),
                "has_error": bool(item.get("err_msg") or item.get("error")),
            }
        )
    return projected


def project_delete_result(result: object) -> object:
    """只保留删除任务的终态与影响条数，不复制任务原始负载。"""
    if not isinstance(result, dict):
        return {"type": type(result).__name__}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "status": safe_value(result.get("status")),
        "effect_count": data.get("effect_count"),
        "template": safe_value(result.get("template")),
    }


def project_ownership(record: dict) -> dict:
    """只保留所有权判断所需的模板、产品子集与配置 ID。"""
    product = record.get("product") or {}
    config = record.get("config") or {}
    return {
        "template": record.get("template"),
        "product": {
            key: product.get(key)
            for key in ("id", "name", "start_date", "label", "create_time", "workspace_id")
            if key in product
        },
        "config": {"_id": config.get("_id"), "channel_id": config.get("channel_id"), "product_id": config.get("product_id")},
    }


def connect(base_url: str, workspace_id: str, token: str, wait_seconds: int) -> None:
    """初始化模块级客户端；令牌只来自环境变量，不写日志也不进 argv。"""
    rqamsh.init(
        base_url=base_url,
        workspace_id=workspace_id,
        token=token,
        timeout=60,
        wait_timeout=max(60, wait_seconds),
        poll_interval=1,
    )


def verify_target(args: argparse.Namespace) -> dict:
    """核对显式测试目标：地址一致、空间为成员空间、专用名称未被占用。"""
    base_url = required_env(BASE_ENV).rstrip("/")
    workspace_id = required_env(WORKSPACE_ENV)
    expected_base = args.expected_base_url.strip().rstrip("/")
    expected_workspace = args.expected_workspace_id.strip()
    if args.confirm != CONFIRM_TOKEN:
        raise HarnessError("invalid_confirmation", f"确认口令必须为 {CONFIRM_TOKEN}")
    if base_url != expected_base:
        raise HarnessError("target_mismatch", f"{BASE_ENV} 与 --expected-base-url 不一致，拒绝写入")
    if workspace_id != expected_workspace:
        raise HarnessError("target_mismatch", f"{WORKSPACE_ENV} 与 --expected-workspace-id 不一致，拒绝写入")
    name = args.product_name.strip()
    if not name.startswith(NAME_PREFIX) or NAME_MARKER not in name:
        raise HarnessError(
            "invalid_product_name",
            f"专用测试产品名称必须以 {NAME_PREFIX} 开头并包含 {NAME_MARKER}",
        )
    spaces = rqamsh.workspaces.list().get("data", [])
    matched = [item for item in spaces if str(item.get("id")) == workspace_id]
    if not matched:
        raise HarnessError("workspace_not_member", "当前令牌不是该空间的成员，拒绝写入")
    papers = rqamsh.paper_trading.list()
    if any(str(item.get("product", {}).get("name")) == name for item in papers):
        raise HarnessError("product_name_in_use", "同名模拟产品已存在，拒绝重复运行")
    exists = rqamsh.products.name_exists(name=name)
    if isinstance(exists, dict) and exists.get("exists") is True:
        raise HarnessError("product_name_in_use", "服务端报告产品名称已存在，拒绝创建")
    return {
        "base_url": base_url,
        "workspace_id": workspace_id,
        "workspace_name": matched[0].get("name"),
        "product_name": name,
        "paper_trading_count": len(papers),
    }


def create_product(name: str) -> dict:
    """按通用策略模板创建专用模拟产品；费用参数显式构造为 0，不是未知默认值。"""
    return rqamsh.paper_trading.create(
        template="conventional",
        name=name,
        benchmark=BENCHMARK,
        start_date=START_DATE,
        init_amount=INIT_AMOUNT,
        strategy_category=STRATEGY_CATEGORY,
        stock_min_fee=0.0,
        stock_commission_rate=0.0,
        loan_rate=0.0,
        margin_rate=0.0,
    )


def read_product(product_id: str) -> dict:
    """读取模拟产品的模板与配置，用于创建回执核对和清理前的所有权证明。"""
    return rqamsh.paper_trading.get(product_id)


def trading_account(record: dict) -> str:
    """从产品配置中取出非托管交易账户名称；无法唯一确定时拒绝猜测。"""
    accounts = record.get("product", {}).get("accounts") or []
    candidates = [item for item in accounts if not item.get("is_custodian")]
    names = [str(item.get("name")) for item in candidates if item.get("name")]
    if len(names) != 1:
        raise HarnessError(
            "account_not_determined",
            f"产品配置中无法唯一确定交易账户，候选数 {len(names)}",
        )
    return names[0]


def discover_candidates(name: str) -> list[dict]:
    """按名称只读发现同名的模拟产品候选；只用于待核实记录，不授权删除。"""
    candidates = []
    for item in rqamsh.paper_trading.list():
        product = item.get("product") or {}
        if str(product.get("name")) != name:
            continue
        candidates.append(
            {
                "product_id": str(item.get("product_id")),
                "template": item.get("template"),
                "start_date": product.get("start_date"),
                "create_time": product.get("create_time"),
                "workspace_id": product.get("workspace_id"),
            }
        )
    return candidates


def project_compute_state(state: object) -> dict:
    """只保留计算状态的 state 与 execution_id，并做类型筛选。"""
    if not isinstance(state, dict):
        return {"state": None}
    projected = {}
    value = state.get("state")
    if isinstance(value, str):
        projected["state"] = value[:80]
    else:
        projected["state"] = None
    execution_id = state.get("execution_id")
    if isinstance(execution_id, int) and not isinstance(execution_id, bool):
        projected["execution_id"] = execution_id
    elif isinstance(execution_id, str):
        projected["execution_id"] = execution_id[:64]
    return projected


def compute_state(product_id: str) -> dict:
    """读取一次产品计算状态，仅返回安全投影。"""
    return project_compute_state(rqamsh.products.compute_state(resource=product_id))


def wait_normal(product_id: str, deadline: float) -> dict:
    """在总体截止时间内等待计算状态为 normal，只重查状态，不重发写请求。"""
    last: dict = {}
    while time.monotonic() < deadline:
        last = compute_state(product_id)
        if str(last.get("state")) == "normal":
            return last
        time.sleep(3)
    error = HarnessError("compute_state_timeout", "等待计算状态 normal 超时")
    error.safe_diagnostics = {"last_state": last.get("state"), "execution_id": last.get("execution_id")}
    raise error


def cash_from_positions(positions: dict) -> object:
    """按现金类持仓市值合计派生现金金额；无现金类持仓时返回 None，不补零。"""
    total = None
    for position in positions.values():
        if position.get("asset_class") not in CASH_ASSET_CLASSES:
            continue
        value = position.get("market_value")
        if value is None:
            continue
        total = Decimal(str(value)) if total is None else total + Decimal(str(value))
    return None if total is None else float(total)


def balance_snapshot(product_id: str, business_date: str, deadline: float) -> dict:
    """读取某日完整头寸报表；实际业务日期必须等于请求日期，未就绪时等待后重读。"""
    last_error: str | None = None
    while True:
        try:
            report = rqamsh.balances.get(product_id, date=business_date)
            break
        except HarnessError as exc:
            last_error = f"{exc.code}: {exc}"
            if time.monotonic() >= deadline:
                raise HarnessError(
                    "balance_unready",
                    f"{business_date} 头寸报表未就绪：{last_error}",
                ) from exc
            if str(compute_state(product_id).get("state")) == "normal":
                raise
            time.sleep(3)
    actual_date = report.get("date")
    if str(actual_date) != business_date:
        raise HarnessError(
            "balance_date_mismatch",
            f"请求 {business_date} 的头寸报表实际业务日期为 {actual_date}",
            details={"requested": business_date, "actual": actual_date},
        )
    positions = {}
    for item in report.get("positions") or []:
        key = str(item.get("order_book_id") or "")
        positions[key] = {
            "asset_class": item.get("asset_class"),
            "quantity": item.get("quantity"),
            "fair_value": item.get("fair_value"),
            "market_value": item.get("market_value"),
        }
    return {
        "date": actual_date,
        "cash": report.get("cash"),
        "cash_from_positions": cash_from_positions(positions),
        "total_equity": report.get("total_equity"),
        "units": report.get("units"),
        "unit_net_value": report.get("unit_net_value"),
        "positions": positions,
    }


def capture_balances(product_id: str, dates: tuple[str, ...], deadline: float) -> dict:
    """按日期逐日读取头寸报表，返回可按请求日期比较的摘要。"""
    result = {}
    for business_date in dates:
        result[business_date] = balance_snapshot(product_id, business_date, deadline)
    return result


def list_trades(product_id: str) -> dict:
    """读取目标日的全部流水，用于导入前查重与导入后读回。"""
    return rqamsh.trades.list(product_id, start_date=TRADE_DATE, end_date=TRADE_DATE)


def trade_records(listing: dict) -> list[dict]:
    """从流水查询结果中取出流水数组，兼容空结果。"""
    rows = listing.get("trades") if isinstance(listing, dict) else None
    return rows if isinstance(rows, list) else []


def record_id(trade: dict) -> str | None:
    """读取流水记录主键，兼容 get 记录的 `_id` 与写入结果的 `id`。"""
    for key in ("_id", "id"):
        value = trade.get(key)
        if value:
            return str(value)
    return None


def upload_trades(product_id: str, account: str, foreign_ids: dict[str, str]) -> list:
    """导入两笔构造买入；一次性提交，失败不重传。"""
    data = []
    for template, key in ((TARGET_TRADE, "target"), (OTHER_TRADE, "other")):
        item = dict(template)
        item["account"] = account
        item["foreign_id"] = foreign_ids[key]
        data.append(item)
    return rqamsh.trades.upload(product_id, data)


def read_trade(product_id: str, trade_id: str) -> dict:
    """按记录 ID 读取单条流水，不使用外部流水号代替主键。"""
    return rqamsh.trades.get(product_id, trade_id)


def correct_target_trade(product_id: str, trade_id: str) -> dict:
    """只提交目标流水的数量与价格，不改变交易类型、来源、日期或账户。"""
    return rqamsh.trades.update(product_id, trade_id, data=dict(CORRECTION))


def same_datetime(left: object, right: object) -> bool:
    """比较两个成交时间文本，容忍空格/T 分隔与零秒写法差异。"""
    def normalize(value: object) -> str | None:
        """把时间文本规范为秒级 ISO 形式；无法解析时原样返回。"""
        text = str(value or "").strip().replace(" ", "T", 1)
        if not text:
            return None
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return text
        return parsed.replace(microsecond=0).isoformat()

    return normalize(left) == normalize(right)


def add_check(checks: list[dict], name: str, passed: bool, detail: object = None) -> None:
    """记录一条业务验收结论；detail 只放可公开的摘要。"""
    checks.append({"check": name, "passed": bool(passed), "detail": detail})


def record_step(steps: list[dict], name: str, state: str, started: float, detail: object = None) -> None:
    """记录一步的终态与耗时；异常和中断分支同样落终态，不留进行中。"""
    steps.append(
        {
            "step": name,
            "state": state,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "detail": detail,
        }
    )


def position_quantity(balances: dict, business_date: str, order_book_id: str) -> object:
    """读取某日某标的的持仓数量；没有该持仓时返回 None，不补零。"""
    position = balances.get(business_date, {}).get("positions", {}).get(order_book_id)
    return None if position is None else position.get("quantity")


def position_fair_value(balances: dict, business_date: str, order_book_id: str) -> object:
    """读取某日某标的的实际估值价格，用于解释净资产差异。"""
    position = balances.get(business_date, {}).get("positions", {}).get(order_book_id)
    return None if position is None else position.get("fair_value")


def same_positions(left: dict, right: dict) -> bool:
    """比较两套持仓摘要的键集合与数量、估值价、市值。"""
    if set(left) != set(right):
        return False
    for key, position in left.items():
        other = right[key]
        for field in ("quantity", "fair_value", "market_value"):
            if not close_enough(position.get(field), other.get(field)):
                return False
        if position.get("asset_class") != other.get("asset_class"):
            return False
    return True


def same_balance_day(left: dict, right: dict, fields: tuple[str, ...]) -> list[str]:
    """比较同一业务日两套摘要的指定字段与持仓，返回不一致的字段名。"""
    mismatched = []
    for field in fields:
        if not close_enough(left.get(field), right.get(field)):
            mismatched.append(field)
    if left.get("date") != right.get("date"):
        mismatched.append("date")
    if not same_positions(left.get("positions") or {}, right.get("positions") or {}):
        mismatched.append("positions")
    return mismatched


def ownership_proof(
    record: dict,
    product_id: str,
    channel_id: str,
    product_name: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> tuple[bool, list[str], dict]:
    """证明读回产品就是本次创建回执的对象：ID、名称、空间、时间窗口与配置 ID。"""
    product = record.get("product") or {}
    config = record.get("config") or {}
    failures = []
    if str(product.get("id")) != product_id:
        failures.append("product_id")
    if str(product.get("name")) != product_name:
        failures.append("name")
    if str(product.get("start_date")) != START_DATE:
        failures.append("start_date")
    if str(product.get("label")) != "paper_trading":
        failures.append("label")
    if record.get("template") != "conventional":
        failures.append("template")
    workspace_id = required_env(WORKSPACE_ENV)
    if str(product.get("workspace_id")) != workspace_id:
        failures.append("workspace_id")
    create_time = parse_beijing_time(product.get("create_time"))
    time_proven = create_time is not None and window_start <= create_time <= window_end
    config_ids = {str(value) for value in (config.get("_id"), config.get("channel_id")) if value}
    channel_proven = bool(channel_id) and channel_id in config_ids
    warnings = []
    if not time_proven:
        warnings.append("create_time_missing_or_out_of_window")
    if not channel_proven:
        warnings.append("channel_id_missing_or_not_matched")
    if not config.get("product_id"):
        warnings.append("config_product_id_missing")
    elif str(config.get("product_id")) != product_id:
        failures.append("config_product_id")
    if not time_proven and not channel_proven:
        failures.append("no_creation_provenance")
    evidence = {
        "product_id": product_id,
        "channel_id": channel_id,
        "config_ids": sorted(config_ids),
        "product_create_time": product.get("create_time"),
        "product_workspace_id": product.get("workspace_id"),
        "product_user_id": product.get("user_id"),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "time_proven": time_proven,
        "channel_proven": channel_proven,
        "template": record.get("template"),
        "user_binding": "create_receipt_only_no_whoami",
        "mismatched": failures,
        "warnings": warnings,
    }
    return not failures, failures, evidence


def delete_owned_product(
    product_id: str,
    channel_id: str,
    product_name: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> dict:
    """先只读证明所有权，再按创建回执的产品 ID 删除并核对列表。"""
    proof_record = read_product(product_id)
    proven, failures, evidence = ownership_proof(
        proof_record, product_id, channel_id, product_name, window_start, window_end
    )
    if not proven:
        return {
            "state": "pending_verification",
            "reason": "所有权证据不足，未执行删除",
            "product_id": product_id,
            "ownership": evidence,
            "mismatched": failures,
        }
    result = rqamsh.paper_trading.delete(product_id)
    remaining = [
        item for item in rqamsh.paper_trading.list() if str(item.get("product_id")) == product_id
    ]
    if remaining:
        return {
            "state": "failed",
            "reason": "delete_result_still_visible",
            "product_id": product_id,
            "delete_result": project_delete_result(result),
            "ownership": evidence,
        }
    return {
        "state": "passed",
        "product_id": product_id,
        "delete_result": project_delete_result(result),
        "ownership": evidence,
        "visible_after_delete": False,
    }


def build_report(name: str) -> dict:
    """构造报告骨架；目标与构造输入先落盘，便于异常时仍有可追溯记录。"""
    return {
        "task": "D12 历史流水更正（historical-trade-correction）",
        "mode": "real-test-deployment",
        "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target": {
            "base_url": os.environ.get(BASE_ENV, ""),
            "workspace_id": os.environ.get(WORKSPACE_ENV, ""),
            "product_name": name,
            "start_date": START_DATE,
            "balance_dates": list(BALANCE_DATES),
        },
        "constructed_input": {
            "template": "conventional",
            "strategy_category": STRATEGY_CATEGORY,
            "init_amount": INIT_AMOUNT,
            "benchmark": BENCHMARK,
            "fees": {"commission": 0.0, "tax": 0.0, "other_fees": 0.0},
            "trades": [TARGET_TRADE, OTHER_TRADE],
            "correction": {"order_book_id": TARGET_ORDER_BOOK_ID, "fields": dict(CORRECTION)},
        },
        "steps": [],
        "checks": [],
        "created": None,
        "create_attempted": False,
        "create_result_unknown": False,
        "trades": {},
        "balances": {},
        "performance": {},
        "cleanup": {"state": "not_started"},
        "persistence": {"journal": "ok", "evidence": "pending"},
        "stage_reached": "start",
        "verification_completed": False,
    }


def check_units_and_nav(snapshots: dict, label: str) -> dict:
    """核对每个业务日的份额有效且单位净值等于净资产÷份额。"""
    detail = {}
    for business_date, row in snapshots.items():
        units = row.get("units")
        equity = row.get("total_equity")
        nav = row.get("unit_net_value")
        passed = units is not None and Decimal(str(units)) != 0 and nav is not None and equity is not None
        expected_nav = None
        if passed:
            expected_nav = Decimal(str(equity)) / Decimal(str(units))
            passed = close_enough(nav, expected_nav, NAV_TOLERANCE)
        detail[business_date] = {
            "units": units,
            "total_equity": equity,
            "unit_net_value": nav,
            "expected_unit_net_value": decimal_text(expected_nav),
            "passed": passed,
        }
    return detail


def series_by_date(series: object) -> dict:
    """把区间序列整理为日期到顶层数值的映射，保留原始日期键。"""
    if not isinstance(series, list):
        return {}
    rows = {}
    for row in series:
        if isinstance(row, dict) and row.get("date"):
            rows[str(row.get("date"))] = row
    return rows


def write_evidence(handle, report: dict) -> str | None:
    """把终态报告写入独占文件；返回 None 或受控失败/中断标记。"""
    try:
        handle.write(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        handle.flush()
        os.fsync(handle.fileno())
        return None
    except (KeyboardInterrupt, SystemExit):
        return "interrupted"
    except BaseException:  # noqa: BLE001 - 证据写入失败也不能阻断标准输出
        return "evidence_write_failed"


def main(argv: list[str] | None = None) -> int:
    """执行创建、导入、更正、读回验收与清理；成功需完整流程与全部验收通过。"""
    args = parse_args(argv)
    name = args.product_name.strip()

    try:
        journal = Journal(args.journal)
    except BaseException as exc:  # noqa: BLE001 - 记录文件冲突必须拒绝且不写业务数据
        print(
            json.dumps(
                {
                    "outcome": "blocked",
                    "diagnostic": "journal_file_unavailable",
                    "error": {"type": type(exc).__name__, "stage": "journal_open"},
                },
                ensure_ascii=False,
            )
        )
        return 2
    try:
        evidence_handle = Path(args.evidence_out).open("x", encoding="utf-8")
    except BaseException as exc:  # noqa: BLE001 - 证据文件冲突必须拒绝且不写业务数据
        journal.close()
        print(
            json.dumps(
                {
                    "outcome": "blocked",
                    "diagnostic": "evidence_file_unavailable",
                    "error": {"type": type(exc).__name__, "stage": "evidence_open"},
                },
                ensure_ascii=False,
            )
        )
        return 2

    report = build_report(name)
    run_started = time.perf_counter()
    deadline = time.monotonic() + max(60, args.wait_seconds)
    window_start = now_beijing() - CREATE_WINDOW_BEFORE
    window_end = now_beijing() + CREATE_WINDOW_AFTER
    product_id: str | None = None
    channel_id = ""
    foreign_ids = {"target": f"{name}-buy-target", "other": f"{name}-buy-other"}
    report["foreign_ids"] = foreign_ids
    missing_env = [item for item in (BASE_ENV, WORKSPACE_ENV, TOKEN_ENV) if not os.environ.get(item, "").strip()]
    stage = "preflight"
    try:
        if missing_env:
            report["stage_reached"] = "preflight"
            report["diagnostic"] = "RQAMSH_TOKEN_missing" if TOKEN_ENV in missing_env else f"{missing_env[0]}_missing"
            error = HarnessError("missing_env", "缺少运行环境变量")
            error.safe_diagnostics = {"missing": missing_env}
            raise error
        stage = "target"
        journal.record(
            "run_start",
            product_name=name,
            base_url=os.environ.get(BASE_ENV, ""),
            workspace_id=os.environ.get(WORKSPACE_ENV, ""),
            confirmation=args.confirm,
            balance_dates=list(BALANCE_DATES),
            constructed_input=report["constructed_input"],
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
        )
        connect(required_env(BASE_ENV), required_env(WORKSPACE_ENV), required_env(TOKEN_ENV), args.wait_seconds)
        started = time.perf_counter()
        target = verify_target(args)
        record_step(report["steps"], "核对显式测试目标与专用名称", "passed", started, target)
        report["target"].update(target)
        journal.record("target_verified", target=target)

        stage = "create"
        report["stage_reached"] = stage
        report["create_attempted"] = True
        journal.record("product_create_submitted", product_name=name)
        started = time.perf_counter()
        try:
            created = create_product(name)
        except BaseException as exc:
            report["create_result_unknown"] = True
            report["create_error"] = safe_error(exc)
            try:
                journal.record("product_create_failed", error=report["create_error"])
                journal.record("cleanup_pending", reason="create_result_unknown", product_name=name)
            except BaseException:
                report["persistence"]["journal"] = "failed"
            raise
        # 先保存回执与 ID 到内存，再做可能失败的持久化。
        report["created"] = project_created(created)
        product_id = str(created.get("product_id") or "") or None
        channel_id = str(created.get("channel_id") or "")
        record_step(report["steps"], "创建专用模拟产品", "passed", started, report["created"])
        journal.record("product_create_returned", created=report["created"])
        if not product_id:
            report["create_result_unknown"] = True
            journal.record("product_create_returned_without_id", created=report["created"])
            journal.record("cleanup_pending", reason="create_result_unknown", product_name=name)
            raise HarnessError("missing_product_id", "创建回执缺少 product_id，按结果未知处理")
        journal.record("product_owned_id", product_id=product_id, channel_id=channel_id)

        stage = "readback"
        report["stage_reached"] = stage
        started = time.perf_counter()
        record = read_product(product_id)
        account = trading_account(record)
        proven, ownership_failures, ownership_evidence = ownership_proof(
            record, product_id, channel_id, name, window_start, window_end
        )
        report["ownership"] = ownership_evidence
        journal.record(
            "ownership_readback",
            record=project_ownership(record),
            proof=ownership_evidence,
        )
        record_step(
            report["steps"],
            "读回产品模板、名称、起始日与交易账户",
            "passed",
            started,
            {
                "template": record.get("template"),
                "product": {
                    "id": (record.get("product") or {}).get("id"),
                    "name": (record.get("product") or {}).get("name"),
                    "start_date": (record.get("product") or {}).get("start_date"),
                    "label": (record.get("product") or {}).get("label"),
                    "create_time": (record.get("product") or {}).get("create_time"),
                    "workspace_id": (record.get("product") or {}).get("workspace_id"),
                },
                "config_ids": {
                    "_id": (record.get("config") or {}).get("_id"),
                    "channel_id": (record.get("config") or {}).get("channel_id"),
                },
                "account": account,
            },
        )
        add_check(
            report["checks"],
            "创建返回产品 ID 与通用策略模板",
            bool(product_id) and created.get("template") == "conventional" and bool(channel_id),
            {"product_id": product_id, "channel_id": channel_id},
        )
        add_check(
            report["checks"],
            "读回产品名称、起始日、模板、空间与创建关联一致",
            proven,
            ownership_evidence,
        )
        if not proven:
            raise HarnessError(
                "ownership_not_proven",
                "创建回执与读回产品的归属条件不成立，停止后续流水写入",
            )

        stage = "precheck"
        report["stage_reached"] = stage
        started = time.perf_counter()
        existing = trade_records(list_trades(product_id))
        collisions = [row for row in existing if str(row.get("foreign_id")) in set(foreign_ids.values())]
        if existing or collisions:
            raise HarnessError(
                "prior_trades_present",
                "目标日已有流水或同名外部流水号，拒绝重放写入",
                details={"count": len(existing), "collisions": len(collisions)},
            )
        journal.record("trades_target_empty", checked_date=TRADE_DATE)
        record_step(report["steps"], "导入前确认目标日无流水、外部流水号未占用", "passed", started)

        stage = "baseline"
        report["stage_reached"] = stage
        started = time.perf_counter()
        baseline = capture_balances(product_id, BALANCE_DATES, deadline)
        journal.record("balances_baseline", balances=baseline)
        record_step(
            report["steps"],
            "读取导入前逐日头寸",
            "passed",
            started,
            {day: {"total_equity": row["total_equity"], "cash": row["cash"]} for day, row in baseline.items()},
        )

        stage = "upload"
        report["stage_reached"] = stage
        started = time.perf_counter()
        upload_result = upload_trades(product_id, account, foreign_ids)
        journal.record("trades_upload_result", result=project_upload_result(upload_result))
        record_step(report["steps"], "导入两笔构造买入流水", "passed", started, project_upload_result(upload_result))
        if not isinstance(upload_result, list) or len(upload_result) != 2:
            raise HarnessError("upload_result_shape", "导入结果不是两项数组，停止后续写入")
        trade_ids = {}
        for key, item in zip(("target", "other"), upload_result):
            if not isinstance(item, dict) or not item.get("id"):
                raise HarnessError("upload_item_failed", "导入逐项结果缺少记录 ID", details={"item": item})
            if item.get("err_msg") or item.get("error"):
                raise HarnessError("upload_item_failed", "导入逐项结果含错误", details={"item": item})
            trade_ids[key] = str(item["id"])
        report["trades"]["ids"] = trade_ids
        journal.record("trades_owned_ids", ids=trade_ids)
        add_check(report["checks"], "两笔流水逐项导入结果无错误", True, {"ids": trade_ids})

        stage = "readback_upload"
        report["stage_reached"] = stage
        started = time.perf_counter()
        target_before = read_trade(product_id, trade_ids["target"])
        other_before = read_trade(product_id, trade_ids["other"])
        report["trades"]["before_update"] = {"target": project_trade(target_before), "other": project_trade(other_before)}
        journal.record("trades_readback_before_update", target=project_trade(target_before), other=project_trade(other_before))
        record_step(report["steps"], "按记录 ID 读回两笔导入流水", "passed", started)
        add_check(
            report["checks"],
            "读回流水字段与构造输入一致且来源为 open_api",
            all(
                close_enough(row.get("quantity"), template["quantity"])
                and close_enough(row.get("price"), template["price"])
                and row.get("order_book_id") == template["order_book_id"]
                and same_datetime(row.get("datetime"), template["datetime"])
                and close_enough(row.get("commission"), 0)
                and close_enough(row.get("tax"), 0)
                and close_enough(row.get("other_fees"), 0)
                and row.get("source") == "open_api"
                and row.get("account") == account
                for row, template in ((target_before, TARGET_TRADE), (other_before, OTHER_TRADE))
            ),
            {
                "target": {k: target_before.get(k) for k in ("quantity", "price", "source", "account")},
                "other": {k: other_before.get(k) for k in ("quantity", "price", "source", "account")},
            },
        )

        if not (
            close_enough(target_before.get("quantity"), TARGET_TRADE["quantity"])
            and close_enough(target_before.get("price"), TARGET_TRADE["price"])
            and target_before.get("source") == "open_api"
        ):
            raise HarnessError(
                "unexpected_baseline_record",
                "更正前记录不等于构造基线，拒绝提交修改以免重复更正",
                details={"target_before": target_before},
            )

        stage = "wait_upload"
        report["stage_reached"] = stage
        started = time.perf_counter()
        state_after_upload = wait_normal(product_id, deadline)
        journal.record("compute_state_after_upload", state=state_after_upload)
        record_step(report["steps"], "等待导入后计算状态", "passed", started, state_after_upload)

        stage = "before_update"
        report["stage_reached"] = stage
        started = time.perf_counter()
        before_update = capture_balances(product_id, BALANCE_DATES, deadline)
        report["balances"]["before_update"] = before_update
        journal.record("balances_before_update", balances=before_update)
        record_step(report["steps"], "读取更正前逐日头寸", "passed", started)

        stage = "update"
        report["stage_reached"] = stage
        started = time.perf_counter()
        journal.record("trade_update_submitted", trade_id=trade_ids["target"], data=dict(CORRECTION))
        try:
            update_result = correct_target_trade(product_id, trade_ids["target"])
        except BaseException as exc:
            journal.record("trade_update_failed", trade_id=trade_ids["target"], error=safe_error(exc))
            raise
        projected_update = {
            "effect_count": update_result.get("effect_count"),
            "updated": project_trade(update_result.get("updated") or {}),
        }
        journal.record("trade_update_result", result=projected_update)
        record_step(report["steps"], "只更正目标流水数量与价格", "passed", started, projected_update)

        stage = "readback_update"
        report["stage_reached"] = stage
        started = time.perf_counter()
        target_after = read_trade(product_id, trade_ids["target"])
        other_after = read_trade(product_id, trade_ids["other"])
        listing_after = list_trades(product_id)
        after_rows = trade_records(listing_after)
        listing_ids = {record_id(row) for row in after_rows}
        report["trades"]["after_update"] = {"target": project_trade(target_after), "other": project_trade(other_after)}
        report["trades"]["listing_after_update"] = {
            "total": listing_after.get("total"),
            "ids": sorted(value for value in listing_ids if value),
        }
        journal.record(
            "trades_readback_after_update",
            target=project_trade(target_after),
            other=project_trade(other_after),
            listing_ids=sorted(value for value in listing_ids if value),
        )
        record_step(report["steps"], "读回更正后流水与当日流水清单", "passed", started)

        target_changes = record_diff(
            target_before,
            target_after,
            allowed=TARGET_ALLOWED_CHANGES + TARGET_MAINTENANCE_FIELDS,
            ignored=SERVER_DERIVED_FIELDS,
        )
        other_changes = record_diff(other_before, other_after)
        expected_delta_cash = -(
            CORRECTION["quantity"] * CORRECTION["price"]
            + TARGET_TRADE["commission"]
            + TARGET_TRADE["tax"]
            + TARGET_TRADE["other_fees"]
        )
        add_check(
            report["checks"],
            "更正回执 effect_count 为 1 且返回更新后记录",
            close_enough(update_result.get("effect_count"), 1)
            and close_enough((update_result.get("updated") or {}).get("quantity"), CORRECTION["quantity"])
            and close_enough((update_result.get("updated") or {}).get("price"), CORRECTION["price"]),
            {
                "effect_count": update_result.get("effect_count"),
                "updated": {
                    k: (update_result.get("updated") or {}).get(k)
                    for k in ("quantity", "price", "estimated_delta_cash")
                },
            },
        )
        add_check(
            report["checks"],
            "目标流水读回只有数量与价格按授权变化",
            not target_changes
            and close_enough(target_after.get("quantity"), CORRECTION["quantity"])
            and close_enough(target_after.get("price"), CORRECTION["price"]),
            {
                "unauthorized_changes": target_changes,
                "target_record_id": record_id(target_after),
                "other_record_id": record_id(other_after),
            },
        )
        add_check(
            report["checks"],
            "目标流水的服务端派生现金变动等于构造成交额",
            close_enough(target_after.get("estimated_delta_cash"), expected_delta_cash),
            {
                "estimated_delta_cash": target_after.get("estimated_delta_cash"),
                "expected": decimal_text(expected_delta_cash),
            },
        )
        add_check(
            report["checks"],
            "另一笔流水完整记录（含记录 ID）在更正前后未变",
            not other_changes
            and record_id(other_before) == record_id(other_after)
            and record_id(other_before) == trade_ids["other"],
            {"changes": other_changes, "record_id": record_id(other_before)},
        )
        add_check(
            report["checks"],
            "当日流水清单恰为本次两条记录",
            listing_after.get("total") == 2
            and listing_ids == {trade_ids["target"], trade_ids["other"]},
            {"total": listing_after.get("total"), "ids": sorted(value for value in listing_ids if value)},
        )

        stage = "wait_update"
        report["stage_reached"] = stage
        started = time.perf_counter()
        state_after_update = wait_normal(product_id, deadline)
        journal.record("compute_state_after_update", state=state_after_update)
        record_step(report["steps"], "等待更正后计算状态", "passed", started, state_after_update)

        stage = "after_update"
        report["stage_reached"] = stage
        started = time.perf_counter()
        after_update = capture_balances(product_id, BALANCE_DATES, deadline)
        report["balances"]["baseline"] = baseline
        report["balances"]["after_update"] = after_update
        journal.record("balances_after_update", balances=after_update)
        record_step(report["steps"], "读取更正后逐日头寸", "passed", started)

        stage = "series"
        report["stage_reached"] = stage
        started = time.perf_counter()
        series = rqamsh.balances.series(
            product_id, start_date=BALANCE_DATES[0], end_date=BALANCE_DATES[-1]
        )
        rows_by_date = series_by_date(series)
        series_summary = {
            "date": {row.get("date"): row.get("total_equity") for row in series}
            if isinstance(series, list)
            else None,
            "dates": sorted(rows_by_date),
        }
        report["balances"]["series"] = series_summary
        journal.record("balances_series", series=series_summary)
        record_step(report["steps"], "读取更正后逐日序列作为交叉核对", "passed", started, series_summary)
        report["performance"] = {
            "per_day_get_count": len(BALANCE_DATES),
            "series_count": 1,
            "series_rows": len(series) if isinstance(series, list) else None,
        }

        stage = "verify"
        report["stage_reached"] = stage
        started = time.perf_counter()
        checks = report["checks"]

        earlier_mismatch = {
            day: same_balance_day(baseline[day], after_update[day], ("total_equity", "cash_from_positions", "units", "unit_net_value"))
            for day in EARLIER_DATES
        }
        add_check(
            checks,
            "更正日之前的日期完全未变",
            all(not items for items in earlier_mismatch.values()),
            {day: (items or "一致") for day, items in earlier_mismatch.items()},
        )

        target_qty_ok = all(
            close_enough(position_quantity(after_update, day, TARGET_ORDER_BOOK_ID), CORRECTION["quantity"])
            for day in LATER_DATES
        )
        other_qty_ok = all(
            close_enough(position_quantity(after_update, day, OTHER_ORDER_BOOK_ID), OTHER_TRADE["quantity"])
            for day in LATER_DATES
        )
        add_check(
            checks,
            "更正日及之后持仓数量等于两笔构造数量",
            target_qty_ok and other_qty_ok,
            {
                day: {
                    TARGET_ORDER_BOOK_ID: position_quantity(after_update, day, TARGET_ORDER_BOOK_ID),
                    OTHER_ORDER_BOOK_ID: position_quantity(after_update, day, OTHER_ORDER_BOOK_ID),
                }
                for day in LATER_DATES
            },
        )

        expected_cash_delta = -(
            CORRECTION["quantity"] * CORRECTION["price"] + OTHER_TRADE["quantity"] * OTHER_TRADE["price"]
        )
        cash_delta = None
        if (
            after_update[TRADE_DATE]["cash_from_positions"] is not None
            and after_update["2026-10-27"]["cash_from_positions"] is not None
        ):
            cash_delta = Decimal(str(after_update[TRADE_DATE]["cash_from_positions"])) - Decimal(
                str(after_update["2026-10-27"]["cash_from_positions"])
            )
        add_check(
            checks,
            "更正日现金类持仓变动等于两笔构造成交额",
            cash_delta is not None and close_enough(cash_delta, expected_cash_delta),
            {
                "actual_cash_delta": decimal_text(cash_delta),
                "expected_cash_delta": decimal_text(expected_cash_delta),
                "cash_before": after_update["2026-10-27"]["cash_from_positions"],
                "cash_after": after_update[TRADE_DATE]["cash_from_positions"],
                "top_level_cash_field": after_update[TRADE_DATE]["cash"],
            },
        )

        fair_value_trade_day = position_fair_value(after_update, TRADE_DATE, TARGET_ORDER_BOOK_ID)
        extra_quantity = Decimal(str(CORRECTION["quantity"])) - Decimal(str(TARGET_TRADE["quantity"]))
        extra_cash = Decimal(str(CORRECTION["quantity"])) * Decimal(str(CORRECTION["price"])) - Decimal(
            str(TARGET_TRADE["quantity"])
        ) * Decimal(str(TARGET_TRADE["price"]))
        expected_equity_delta = None
        actual_equity_delta = None
        if fair_value_trade_day is not None:
            expected_equity_delta = extra_quantity * Decimal(str(fair_value_trade_day)) - extra_cash
            actual_equity_delta = Decimal(str(after_update[TRADE_DATE]["total_equity"])) - Decimal(
                str(before_update[TRADE_DATE]["total_equity"])
            )
        add_check(
            checks,
            "更正日净资产变动等于多买数量×实际估值价减低付现金差额",
            actual_equity_delta is not None
            and close_enough(actual_equity_delta, expected_equity_delta, str(TOLERANCE)),
            {
                "actual_equity_delta": decimal_text(actual_equity_delta),
                "expected_equity_delta": decimal_text(expected_equity_delta),
                "extra_quantity": decimal_text(extra_quantity),
                "extra_cash": decimal_text(extra_cash),
                "actual_fair_value": fair_value_trade_day,
            },
        )

        other_position_unchanged = {
            day: same_positions(
                {OTHER_ORDER_BOOK_ID: before_update[day]["positions"].get(OTHER_ORDER_BOOK_ID, {})},
                {OTHER_ORDER_BOOK_ID: after_update[day]["positions"].get(OTHER_ORDER_BOOK_ID, {})},
            )
            for day in LATER_DATES
        }
        add_check(
            checks,
            "另一笔流水的持仓在更正前后未变",
            all(other_position_unchanged.values())
            and all(position_quantity(after_update, day, OTHER_ORDER_BOOK_ID) is not None for day in LATER_DATES),
            {
                day: {
                    "quantity": position_quantity(after_update, day, OTHER_ORDER_BOOK_ID),
                    "fair_value": position_fair_value(after_update, day, OTHER_ORDER_BOOK_ID),
                }
                for day in LATER_DATES
            },
        )

        later_deltas = {}
        later_ok = True
        for previous, current in (("2026-10-28", "2026-10-29"), ("2026-10-29", "2026-10-30")):
            expected = Decimal("0")
            missing = []
            for order_book_id in (TARGET_ORDER_BOOK_ID, OTHER_ORDER_BOOK_ID):
                fv_previous = position_fair_value(after_update, previous, order_book_id)
                fv_current = position_fair_value(after_update, current, order_book_id)
                quantity = position_quantity(after_update, current, order_book_id)
                if fv_previous is None or fv_current is None or quantity is None:
                    missing.append(order_book_id)
                    continue
                expected += Decimal(str(quantity)) * (Decimal(str(fv_current)) - Decimal(str(fv_previous)))
            actual = Decimal(str(after_update[current]["total_equity"])) - Decimal(
                str(after_update[previous]["total_equity"])
            )
            passed = not missing and close_enough(actual, expected, str(TOLERANCE))
            later_ok = later_ok and passed
            later_deltas[f"{previous}->{current}"] = {
                "actual_equity_delta": decimal_text(actual),
                "expected_from_actual_prices": decimal_text(expected),
                "missing_positions": missing,
                "passed": passed,
            }
        add_check(checks, "后续两日净资产变化可由实际估值价解释", later_ok, later_deltas)

        nav_before = check_units_and_nav(before_update, "before_update")
        nav_after = check_units_and_nav(after_update, "after_update")
        baseline_units = baseline[BALANCE_DATES[0]].get("units")
        units_stable = all(
            close_enough(row.get("units"), baseline_units)
            for snapshots in (before_update, after_update)
            for row in snapshots.values()
        )
        add_check(
            checks,
            "更正前后各日单位净值等于净资产÷份额且份额未变",
            all(item["passed"] for item in nav_before.values())
            and all(item["passed"] for item in nav_after.values())
            and units_stable,
            {"before_update": nav_before, "after_update": nav_after, "baseline_units": baseline_units},
        )

        series_dates = set(rows_by_date)
        series_mismatch = {}
        for day in BALANCE_DATES:
            row = rows_by_date.get(day)
            if row is None:
                series_mismatch[day] = "missing"
                continue
            if not close_enough(row.get("total_equity"), after_update[day]["total_equity"], str(TOLERANCE)):
                series_mismatch[day] = {
                    "series": row.get("total_equity"),
                    "per_day_get": after_update[day]["total_equity"],
                }
        add_check(
            checks,
            "区间序列包含全部请求日期且逐日净资产与逐日读取一致",
            isinstance(series, list)
            and series_dates == set(BALANCE_DATES)
            and not series_mismatch,
            {
                "series_dates": sorted(series_dates),
                "requested_dates": list(BALANCE_DATES),
                "mismatch": series_mismatch,
            },
        )

        add_check(
            checks,
            "更正后计算状态为 normal",
            str(state_after_update.get("state")) == "normal",
            state_after_update,
        )
        report["verification_completed"] = True
        journal.record("checks_completed", checks=checks)
        record_step(report["steps"], "执行业务验收比较", "passed", started)
        stage = "done"
        report["stage_reached"] = stage
    except KeyboardInterrupt:
        report["diagnostic"] = "interrupted"
        report["error"] = {"stage": stage, "type": "KeyboardInterrupt"}
        if journal.try_record("interrupted", stage=stage) != "ok":
            report["persistence"]["journal"] = "failed"
        record_step(report["steps"], f"中断于 {stage}", "failed", run_started, {"stage": stage, "type": "KeyboardInterrupt"})
    except SystemExit:
        report["diagnostic"] = "interrupted"
        report["error"] = {"stage": stage, "type": "SystemExit"}
        if journal.try_record("interrupted", stage=stage) != "ok":
            report["persistence"]["journal"] = "failed"
        record_step(report["steps"], f"中断于 {stage}", "failed", run_started, {"stage": stage, "type": "SystemExit"})
    except PersistenceError:
        report["persistence"]["journal"] = "failed"
        report["diagnostic"] = "persistence_failed"
        report["error"] = {"stage": stage, "type": "PersistenceError"}
        record_step(report["steps"], f"运行记录失败，停止于 {stage}", "failed", run_started, report["error"])
    except HarnessError as exc:
        report["error"] = {"stage": stage, **safe_error(exc)}
        if journal.try_record("failed", stage=stage, error=report["error"]) != "ok":
            report["persistence"]["journal"] = "failed"
        record_step(report["steps"], f"异常终止于 {stage}", "failed", run_started, report["error"])
    except BaseException as exc:  # noqa: BLE001 - 未预期异常必须落终态证据
        report["error"] = {"stage": stage, **safe_error(exc)}
        if journal.try_record("failed", stage=stage, error=report["error"]) != "ok":
            report["persistence"]["journal"] = "failed"
        record_step(report["steps"], f"异常终止于 {stage}", "failed", run_started, report["error"])
    finally:
        # 1. 只读诊断：用户中断必须使终态为 blocked，不能被普通读取失败吞掉。
        if product_id:
            try:
                listing = list_trades(product_id)
                report["trades"]["after_exception"] = [
                    {"record_id": record_id(row), "foreign_id": row.get("foreign_id"), "quantity": row.get("quantity"), "price": row.get("price")}
                    for row in trade_records(listing)
                ]
            except (KeyboardInterrupt, SystemExit) as read_exc:
                report["trades"]["after_exception"] = {"read_error": "interrupted"}
                report["diagnostic"] = "interrupted"
                report["error"] = report.get("error") or {
                    "stage": "final_readback",
                    "type": type(read_exc).__name__,
                }
            except BaseException as read_exc:  # noqa: BLE001 - 普通诊断读取失败只留类型
                report["trades"]["after_exception"] = {"read_error": type(read_exc).__name__}

        # 2. 清理与最终持久化彼此独立；journal 失败不阻断清理、关闭或 stdout。
        status = journal.try_record("cleanup_start", product_id=product_id, create_attempted=report["create_attempted"])
        if status != "ok":
            report["persistence"]["journal"] = "failed"
            if status == "interrupted":
                report["diagnostic"] = "interrupted"
        if report["create_attempted"] and not product_id:
            status = journal.try_record("cleanup_pending", reason="create_result_unknown", product_name=name)
            if status != "ok":
                report["persistence"]["journal"] = "failed"
                if status == "interrupted":
                    report["diagnostic"] = "interrupted"
        try:
            if product_id:
                started = time.perf_counter()
                report["cleanup"] = delete_owned_product(
                    product_id, channel_id, name, window_start, window_end
                )
                cleanup_state = report["cleanup"].get("state", "failed")
                record_step(report["steps"], "清理本次创建的专用产品", cleanup_state, started, report["cleanup"])
            elif report["create_attempted"]:
                candidates = discover_candidates(name)
                report["cleanup"] = {
                    "state": "pending_verification",
                    "reason": "创建结果未知或回执缺少 ID，只做只读候选发现，不授权删除",
                    "product_name": name,
                    "candidates": candidates,
                    "candidate_count": len(candidates),
                }
                record_step(report["steps"], "记录待核实的创建结果", "pending_verification", time.perf_counter(), report["cleanup"])
            else:
                report["cleanup"] = {"state": "not_needed", "reason": "创建请求未提交"}
        except (KeyboardInterrupt, SystemExit) as cleanup_stop:
            report["cleanup"] = {
                "state": "failed",
                "reason": "cleanup_interrupted",
                "product_id": product_id,
                "error": {"type": type(cleanup_stop).__name__},
            }
            report["error"] = report.get("error") or {
                "stage": "cleanup",
                "type": type(cleanup_stop).__name__,
            }
            report["diagnostic"] = "interrupted"
            record_step(report["steps"], "清理期间中断", "failed", run_started, report["cleanup"])
        except BaseException as exc:  # noqa: BLE001 - 清理失败必须保留待清理对象
            report["cleanup"] = {
                "state": "failed",
                "reason": "cleanup_failed",
                "product_id": product_id,
                "error": safe_error(exc),
            }
            record_step(report["steps"], "清理失败", "failed", run_started, report["cleanup"])
        status = journal.try_record("cleanup_result", cleanup=report["cleanup"])
        if status != "ok":
            report["persistence"]["journal"] = "failed"
            if status == "interrupted":
                report["diagnostic"] = "interrupted"

        try:
            rqamsh.close()
        except BaseException as exc:  # noqa: BLE001 - 关闭失败不应阻断终态证据
            report["close_error"] = safe_error(exc)
        report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()

        checks = report["checks"]
        body_passed = bool(checks) and all(item["passed"] for item in checks)
        cleanup_ok = report["cleanup"].get("state") in ("passed", "not_needed")
        completed = (
            report["stage_reached"] == "done"
            and report["verification_completed"]
            and body_passed
            and cleanup_ok
            and "error" not in report
            and report["persistence"]["journal"] == "ok"
        )
        if report.get("diagnostic") == "interrupted":
            report["outcome"] = "blocked"
        elif "error" in report:
            report["outcome"] = "failed" if report["create_attempted"] else "blocked"
        elif completed:
            report["outcome"] = "passed"
        else:
            report["outcome"] = "failed"

        # 3. 准备事件先落盘；最终结论在证据写入后以独立提交事件记录。
        status = journal.try_record(
            "run_prepared",
            outcome=report["outcome"],
            stage=report["stage_reached"],
            cleanup=report["cleanup"],
            persistence=report["persistence"],
        )
        if status != "ok":
            report["persistence"]["journal"] = "failed"
            if status == "interrupted":
                report["diagnostic"] = "interrupted"
                report["outcome"] = "blocked"
            elif report["outcome"] == "passed":
                report["outcome"] = "failed"

        # 正常写入的报告本身就是终态；失败/中断由 run_final 与 stdout 更正。
        report["persistence"]["evidence"] = "ok"
        persistence = write_evidence(evidence_handle, report)
        report["persistence"]["evidence"] = persistence or "ok"
        if persistence == "interrupted":
            report["diagnostic"] = "interrupted"
            report["error"] = report.get("error") or {"stage": "evidence_write", "type": "KeyboardInterrupt"}
            report["outcome"] = "blocked"
        elif persistence and report["outcome"] == "passed":
            report["diagnostic"] = "evidence_write_failed"
            report["outcome"] = "failed"

        final_status = journal.try_record(
            "run_final",
            outcome=report["outcome"],
            stage=report["stage_reached"],
            cleanup=report["cleanup"],
            persistence=report["persistence"],
            diagnostic=report.get("diagnostic"),
        )
        if final_status != "ok":
            report["persistence"]["journal"] = "failed"
            if final_status == "interrupted":
                report["diagnostic"] = "interrupted"
                report["outcome"] = "blocked"
            elif report["outcome"] == "passed":
                report["outcome"] = "failed"
            # 已写证据可能早于最终提交失败，尽力用受控结论原位重写。
            try:
                evidence_handle.seek(0)
                evidence_handle.truncate()
                rewrite = write_evidence(evidence_handle, report)
                report["persistence"]["evidence"] = rewrite or "ok"
                if rewrite == "interrupted":
                    report["diagnostic"] = "interrupted"
                    report["outcome"] = "blocked"
                elif rewrite and report["outcome"] == "passed":
                    report["outcome"] = "failed"
            except BaseException:
                report["persistence"]["evidence"] = "rewrite_failed"

        # 4. 关闭动作独立兜底，最后的标准输出不依赖上述任何一步。
        try:
            evidence_handle.close()
        except BaseException:
            report["persistence"]["evidence"] = "close_failed"
        try:
            journal.close()
        except BaseException:
            report["persistence"]["journal"] = "close_failed"
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))

    if report["outcome"] == "passed":
        return 0
    if report["outcome"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
