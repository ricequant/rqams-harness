"""单产品业务简报：净值、收益、持仓、暴露、风险与完整性的只读报告。

净值、当日收益、前十与资产/行业暴露取同一次当前快照；本自然周收益与风险取服务端
``analytics.indicators``；风格取实时因子暴露；昨日风格只在提供已有归因 ID 时读取。
不创建归因、不改业务数据，缺口逐项登记，不以昨日数据冒充当天。
"""

from __future__ import annotations

import math
import sys
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _report_common import launch

BEIJING = timezone(timedelta(hours=8))
SNAPSHOT_FIELDS = [
    "date", "positions", "total_assets", "total_liabilities", "total_equity", "units",
    "unit_net_value", "acc_unit_net_value", "daily_returns", "daily_pnl",
    "benchmark_returns", "excess_returns", "update_time",
]
NAV_FIELDS = [
    "total_assets", "total_liabilities", "total_equity", "units", "unit_net_value",
    "acc_unit_net_value", "daily_returns", "daily_pnl", "benchmark_returns", "excess_returns",
]
RISK_FIELDS = [
    ("annual_volatility", "年化波动率", True),
    ("max_drawdown", "最大回撤", True),
    ("beta", "Beta（观测值，不作因果）", False),
    ("sharpe", "夏普比率", False),
    ("annual_tracking_error", "年化跟踪误差", True),
    ("information_ratio", "信息比率", False),
    ("total_returns", "区间累计收益", True),
    ("geometric_excess_max_drawdown", "几何超额最大回撤", True),
]


def configure(parser):
    """注册本案例的业务参数；公共参数由 _report_common 提供。"""
    parser.add_argument("--resource", required=True, help="单产品 ID 或名称")
    parser.add_argument("--attribution-id", default=None,
                        help="可选：已存在的历史归因 ID，只读取其真实 T-1 因子暴露行")
    parser.add_argument("--risk-days", type=int, default=30, help="风险窗口自然日数，默认 30")
    parser.add_argument("--as-of", default=None, help="可选：目标业务日期 YYYY-MM-DD；省略读实时")


def collect(ctx):
    """按目标、当前快照、日期、并发读取、整理的顺序采集，并分阶段落盘。"""
    args, data = ctx.args, ctx.data
    for key, default in (("sections", {}), ("problems", []), ("raw", {}), ("steps", [])):
        data.setdefault(key, default)
    sections = data["sections"]
    clock = datetime.now(BEIJING)
    today = clock.date().isoformat()
    requested = (getattr(args, "as_of", None) or "").strip() or None
    attribution_id = (getattr(args, "attribution_id", None) or "").strip() or None
    historical = bool(requested and requested < today)
    sections["meta"] = {"clock": clock.isoformat(timespec="seconds"), "requested": requested,
                        "attribution_id": attribution_id}
    if requested:
        try:
            Date.fromisoformat(requested)
        except ValueError:
            ctx.problem("参数", f"--as-of {requested} 不是 YYYY-MM-DD")
            raise ValueError("--as-of 参数不是有效日期") from None
        if requested > today:
            ctx.problem("参数", f"--as-of {requested} 晚于北京时间今天 {today}")
            raise ValueError("--as-of 不允许未来日期")

    product = ctx.call("products.get", lambda: ctx.client.products.get(args.resource))
    if not isinstance(product, dict) or not product.get("id"):
        ctx.checkpoint()
        raise RuntimeError("无法解析目标产品；本案例只支持单产品")
    product_id = str(product["id"])
    benchmark = product.get("benchmark") if isinstance(product.get("benchmark"), dict) else {}
    benchmark_arg = (f"{benchmark.get('type')},{benchmark.get('id')}"
                     if benchmark.get("type") and benchmark.get("id") else None)
    sections["product"] = {key: product.get(key) for key in (
        "name", "id", "label", "data_source", "calendar", "product_state",
        "strategy_category", "investment_category", "benchmark")}
    ctx.checkpoint()

    snap = ctx.call("balances.get(current)", lambda: ctx.client.balances.get(
        product_id, date=requested, fields=list(SNAPSHOT_FIELDS)))
    if not isinstance(snap, dict):
        ctx.checkpoint()
        raise RuntimeError("未能读取当前或目标日完整快照")
    actual_date = _iso(snap.get("date"))
    if actual_date is None:
        raise RuntimeError("快照没有可解析的业务日期")
    if requested and actual_date != requested:
        ctx.problem("日期", f"请求日期 {requested} 与实际业务日期 {actual_date} 不一致")
    sections["nav"] = _nav_view(snap)
    ctx.checkpoint()

    missing = [name for name in ("total_equity", "unit_net_value", "daily_returns", "update_time")
               if snap.get(name) is None]
    if not isinstance(snap.get("positions"), list):
        missing.append("positions")
        ctx.problem("持仓", "单次快照未返回 positions；不重读或拼接摘要，前十与暴露按缺口处理")
    if missing:
        ctx.problem("完整性", "当前快照缺少字段：" + "、".join(missing))
    update_time = snap.get("update_time") if isinstance(snap.get("update_time"), str) else None
    if update_time and _iso(update_time) != actual_date:
        ctx.problem("完整性", f"update_time={update_time} 不属于业务日期 {actual_date}")

    target = requested or today
    days = ctx.call("market_data.trading_dates", lambda: ctx.client.market_data.trading_dates(
        "exchange", start_date=_shift(actual_date, -45), end_date=target))
    trading = sorted(day for day in (days or []) if isinstance(day, str) and _iso(day))
    up_to_target = [day for day in trading if day <= target]
    expected = up_to_target[-1] if up_to_target else None
    earlier = [day for day in trading if day < actual_date]
    calendar_previous = earlier[-1] if earlier else None
    if expected is None:
        ctx.problem("日期", f"交易所日历未返回截至 {target} 的交易日，无法核验预期最新交易日")
    elif expected != actual_date:
        ctx.problem("日期", f"实际业务日期 {actual_date} 不是截至 {target} 的最近交易日 {expected}")

    previous = None if historical else ctx.call(
        "balances.previous_summary", lambda: ctx.client.balances.previous_summary(product_id))
    prev_date = _iso(previous.get("date")) if isinstance(previous, dict) else None
    prev_source = "balances.previous_summary"
    if not historical and prev_date is None:
        ctx.problem("昨日概览", "上一交易日概览未返回，改用交易所日历定位昨日完整持仓")
    if historical or prev_date is None or prev_date >= actual_date:
        prev_date, prev_source = calendar_previous, (
            "exchange calendar（as-of 历史模式）" if historical else "exchange calendar fallback")
        if prev_date is None:
            ctx.problem("日期", "无法确定上一交易日，昨日持仓与变化不可用")
    elif calendar_previous and prev_date != calendar_previous:
        ctx.problem("日期", f"上一交易日概览 {prev_date} 与交易所日历 {calendar_previous} 不一致")

    week_monday = _monday(actual_date)
    risk_days = max(2, int(getattr(args, "risk_days", 30) or 30))
    if risk_days != int(getattr(args, "risk_days", 30) or 30):
        ctx.problem("参数", f"--risk-days 小于 2，风险窗口按 2 个自然日计算")
    risk_start = _shift(actual_date, -risk_days)
    sections["dates"] = {
        "actual": actual_date, "expected": expected, "target": target,
        "verified": bool(expected) and product.get("calendar") == "exchange",
        "calendar": product.get("calendar"), "previous": prev_date,
        "previous_source": prev_source, "week_monday": week_monday,
        "risk_start": risk_start, "risk_end": actual_date, "risk_days": risk_days,
        "update_time": update_time, "missing": missing, "historical": historical,
    }
    ctx.checkpoint()

    jobs = {}
    if prev_date:
        jobs["balances.get(previous)"] = lambda: ctx.client.balances.get(
            product_id, date=prev_date, fields=list(SNAPSHOT_FIELDS))
    jobs["indicators.week"] = lambda: ctx.client.analytics.indicators(
        product_id, start_date=week_monday, end_date=actual_date, benchmark=benchmark_arg,
        extra_indicators=["returns_summary", "asset_series"])
    jobs["indicators.risk"] = lambda: ctx.client.analytics.indicators(
        product_id, start_date=risk_start, end_date=actual_date, benchmark=benchmark_arg,
        extra_indicators=["asset_series"])
    jobs["realtime_factor_exposure"] = lambda: ctx.client.analytics.realtime_factor_exposure(
        product_id, template="equity/factor")
    if attribution_id:
        jobs["attribution"] = lambda: ctx.client.analytics.attribution(product_id, attribution_id)
    results = ctx.parallel(jobs) or {}
    ctx.checkpoint()

    prev_report = results.get("balances.get(previous)")
    prev_positions = prev_report.get("positions") if isinstance(prev_report, dict) else None
    prev_comparable = (isinstance(prev_report, dict) and prev_date is not None
                       and _iso(prev_report.get("date")) == prev_date
                       and isinstance(prev_positions, list))
    if prev_date and not prev_comparable:
        if not isinstance(prev_report, dict):
            ctx.problem("昨日持仓", f"未能读取 {prev_date} 的完整持仓")
        elif not isinstance(prev_positions, list):
            ctx.problem("昨日持仓", f"{prev_date} 的响应没有 positions 列表；"
                                    "不把缺失当空仓，本次不做昨日变化比较")
        else:
            ctx.problem("昨日持仓", f"昨日读取的业务日期 "
                                    f"{_iso(prev_report.get('date')) or '缺失'} 与预期 {prev_date} "
                                    "不一致，本次不做昨日变化比较")
    prev_nav = _nav_view(prev_report) if isinstance(prev_report, dict) else {}
    week_expected = ([day for day in trading if week_monday <= day <= actual_date]
                     if product.get("calendar") == "exchange" else None)
    sections["week"] = _week_view(results.get("indicators.week"), week_monday, actual_date,
                                  week_expected, ctx)
    sections["risk"] = _risk_view(results.get("indicators.risk"), risk_start, actual_date, ctx)
    sections["style"] = _style_view(results.get("realtime_factor_exposure"),
                                    results.get("attribution"), attribution_id, prev_date,
                                    historical, ctx)
    ctx.checkpoint()

    rows = list(_aggregate(snap.get("positions")).values())
    if not rows:
        ctx.problem("持仓", "当前快照没有可用叶子持仓")
    partial_rows = [row for row in rows
                    if row.get("market_value") is None or row.get("market_value_missing")]
    if partial_rows:
        sample = "、".join(str(row.get("order_book_id") or "未知") for row in partial_rows[:5])
        ctx.problem("持仓", f"{len(partial_rows)} 个聚合持仓键缺少市值（{sample}）："
                            "市值合计、占净值与集中度只覆盖已知金额，不完整")
    nav = _num(snap.get("total_equity"))
    prev_rows = list(_aggregate(prev_positions).values()) if prev_comparable else []
    for label, holdings_rows in (("当前", rows), ("昨日", prev_rows)):
        missing_quantity = [row for row in holdings_rows if row.get("quantity_missing")]
        if missing_quantity:
            ctx.problem("持仓", f"{label} {len(missing_quantity)} 个聚合持仓键数量缺失；"
                                "不把已知数量小计当作完整数量，也不计算其数量变化")
    holdings = _holdings(rows, prev_rows, nav, prev_nav.get("total_equity"), prev_comparable)
    for name in ("top10", "concentration", "asset_classes", "industries", "diff"):
        sections[name] = holdings[name]
    sections["summary"] = _summary_lines(sections)
    ctx.checkpoint()
    return data


def _num(value):
    """把返回值规整为有限浮点数；布尔、空值、NaN 与非数值返回 None。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(value):
    """把日期或带时间的字符串规整为 YYYY-MM-DD；无法解析返回 None。"""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return Date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def _shift(text, days):
    """按自然日平移 YYYY-MM-DD；无法解析返回 None。"""
    try:
        return (Date.fromisoformat(text) + timedelta(days=days)).isoformat()
    except (TypeError, ValueError):
        return None


def _monday(text):
    """返回该日期所在自然周的周一（YYYY-MM-DD）。"""
    try:
        day = Date.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return (day - timedelta(days=day.weekday())).isoformat()


def _key(position):
    """构造实际唯一持仓键：资产品种、代码、方向，存在账户时纳入账户。"""
    parts = [str(position.get("asset_class") or ""), str(position.get("order_book_id") or ""),
             str(position.get("direction") or "")]
    if position.get("account") not in (None, ""):
        parts.append(str(position["account"]))
    return tuple(parts)


def _aggregate(positions):
    """按唯一持仓键聚合叶子持仓，避免同键多条记录被覆盖或重复排名。"""
    rows = {}
    for position in positions or []:
        if not isinstance(position, dict) or not position.get("asset_class"):
            continue
        key = _key(position)
        row = rows.get(key)
        if row is None:
            row = rows[key] = {
                "key": key, "order_book_id": position.get("order_book_id"),
                "symbol": position.get("symbol"), "asset_class": position.get("asset_class"),
                "direction": position.get("direction"), "industry": position.get("industry"),
                "market_value": None, "quantity": None,
                "market_value_missing": 0, "quantity_missing": 0,
            }
        for name in ("market_value", "quantity"):
            value = _num(position.get(name))
            if value is None:
                row[name + "_missing"] += 1
            else:
                row[name] = (row[name] or 0.0) + value
    for row in rows.values():
        if row["quantity_missing"]:
            row["quantity"] = None
    return rows


def _rank(rows, nav):
    """按绝对市值降序排名并补占净值权重（百分数单位，渲染用 _pctp）；净资产不为正时不计算。"""
    ranked = [row for row in rows if row.get("market_value") is not None and row["market_value"] != 0]
    ranked.sort(key=lambda row: abs(row["market_value"]), reverse=True)
    for row in rows:
        row["weight_pct"] = (row["market_value"] / nav * 100
                             if row.get("market_value") is not None and nav and nav > 0 else None)
    return ranked


def _holdings(rows, prev_rows, nav, nav_prev, has_previous):
    """整理前十、集中度、资产类别、行业与昨日变化，供报告直接渲染。"""
    ranked = _rank(rows, nav)
    ranked_prev = _rank(prev_rows, nav_prev)
    previous = {row["key"]: row for row in prev_rows}
    current = {row["key"]: row for row in rows}
    prev_rank = {row["key"]: index + 1 for index, row in enumerate(ranked_prev[:10])}
    top10 = []
    for index, row in enumerate(ranked[:10]):
        old = previous.get(row["key"])
        top10.append({
            "rank": index + 1, "order_book_id": row.get("order_book_id"),
            "symbol": row.get("symbol"), "asset_class": row.get("asset_class"),
            "direction": row.get("direction"),
            "industry": row.get("industry") if row.get("asset_class") == "stock"
            and row.get("direction") == "long" else None,
            "market_value": row.get("market_value"), "weight_pct": row.get("weight_pct"),
            "quantity": row.get("quantity"), "prev_rank": prev_rank.get(row["key"]),
            "market_value_partial": bool(row.get("market_value_missing")),
            "weight_change": (row["weight_pct"] - old["weight_pct"]
                              if old and row.get("weight_pct") is not None
                              and old.get("weight_pct") is not None else None),
            "qty_change": (row["quantity"] - old["quantity"]
                           if old and row.get("quantity") is not None
                           and old.get("quantity") is not None else None),
        })
    abs_values = [abs(row["market_value"]) for row in ranked]
    top3, top10_sum, total = sum(abs_values[:3]), sum(abs_values[:10]), sum(abs_values)
    partial_rows = [row for row in rows
                    if row.get("market_value") is None or row.get("market_value_missing")]
    concentration = {
        "positions": len(ranked),
        "missing_positions": len(partial_rows),
        "complete": not partial_rows,
        "top3_nav_pct": top3 / nav * 100 if nav and nav > 0 else None,
        "top10_nav_pct": top10_sum / nav * 100 if nav and nav > 0 else None,
        "top10_share_pct": top10_sum / total * 100 if total > 0 else None,
        "nav_positive": bool(nav and nav > 0),
    }
    classes = {}
    for row in rows:
        name = row.get("asset_class") or "未知"
        bucket = classes.setdefault(name, {"asset_class": name, "count": 0, "value": None,
                                           "missing": 0})
        bucket["count"] += 1
        if row.get("market_value") is None or row.get("market_value_missing"):
            bucket["missing"] += 1
        if row.get("market_value") is not None:
            bucket["value"] = (bucket["value"] or 0.0) + row["market_value"]
    for bucket in classes.values():
        bucket["complete"] = bucket["missing"] == 0
        bucket["nav_pct"] = (bucket["value"] / nav * 100
                             if bucket["complete"] and bucket["value"] is not None
                             and nav and nav > 0 else None)
    industries = {}
    for row in rows:
        if row.get("asset_class") != "stock" or row.get("direction") != "long":
            continue
        name = row.get("industry") or "未分类"
        bucket = industries.setdefault(name, {"industry": name, "count": 0, "value": None,
                                              "missing": 0})
        bucket["count"] += 1
        if row.get("market_value") is None or row.get("market_value_missing"):
            bucket["missing"] += 1
        if row.get("market_value") is not None:
            bucket["value"] = (bucket["value"] or 0.0) + row["market_value"]
    for bucket in industries.values():
        bucket["complete"] = bucket["missing"] == 0
        bucket["nav_pct"] = (bucket["value"] / nav * 100
                             if bucket["complete"] and bucket["value"] is not None
                             and nav and nav > 0 else None)
    diff = {"available": has_previous, "new": [], "exited": [], "changes": []}
    if has_previous:
        today_top, prev_top = ranked[:10], ranked_prev[:10]
        today_keys = {row["key"] for row in today_top}
        prev_keys = {row["key"] for row in prev_top}
        today_rank = {row["key"]: index + 1 for index, row in enumerate(today_top)}
        brief = lambda row: {"symbol": row.get("symbol"), "order_book_id": row.get("order_book_id"),
                             "asset_class": row.get("asset_class"), "direction": row.get("direction")}
        diff["new"] = [brief(row) for row in today_top if row["key"] not in prev_keys]
        diff["exited"] = [brief(row) for row in prev_top if row["key"] not in today_keys]
        for key in sorted(today_keys | prev_keys):
            old, new = previous.get(key), current.get(key)
            identity = new if new is not None else old
            # 两份完整持仓中确实不存在的键是零仓；已有记录的未知字段仍是未知。
            if old is None:
                old = {"market_value": 0.0, "quantity": 0.0,
                       "weight_pct": 0.0 if nav_prev and nav_prev > 0 else None}
            if new is None:
                new = {"market_value": 0.0, "quantity": 0.0,
                       "weight_pct": 0.0 if nav and nav > 0 else None}
            rank, prior = today_rank.get(key), prev_rank.get(key)
            diff["changes"].append({
                "symbol": identity.get("symbol"), "order_book_id": identity.get("order_book_id"),
                "asset_class": identity.get("asset_class"), "direction": identity.get("direction"),
                "rank": rank, "prev_rank": prior,
                "rank_change": (prior - rank if rank is not None and prior is not None else None),
                "weight_change": (new["weight_pct"] - old["weight_pct"]
                                  if new.get("weight_pct") is not None
                                  and old.get("weight_pct") is not None else None),
                "qty_change": (new["quantity"] - old["quantity"]
                               if new.get("quantity") is not None
                               and old.get("quantity") is not None else None),
                "market_value_change": (new["market_value"] - old["market_value"]
                                        if new.get("market_value") is not None
                                        and old.get("market_value") is not None else None),
            })
        diff["changes"].sort(key=lambda row: abs(row.get("weight_change") or 0.0), reverse=True)
    return {
        "top10": top10, "concentration": concentration,
        "asset_classes": sorted(classes.values(), key=lambda bucket: abs(bucket["value"] or 0.0),
                                reverse=True),
        "industries": sorted(industries.values(), key=lambda bucket: abs(bucket["value"] or 0.0),
                             reverse=True),
        "diff": diff,
    }


def _week_view(result, start, end, expected_days, ctx):
    """整理自然周指标，核对样本日期集合、交易所交易日与同响应一致性。"""
    view = {"start": start, "end": end, "return": None, "covered_start": None,
            "covered_end": None, "rows": 0, "contains_actual": None,
            "missing_days": [], "extra_days": [],
            "expected_days": len(expected_days) if expected_days is not None else None,
            "days_checked": expected_days is not None, "start_note": None,
            "consistency": None}
    if not isinstance(result, dict):
        ctx.problem("本周收益", f"{start}..{end} 的指标未返回，无法给出本自然周实测收益")
        return view
    summary = result.get("returns_summary") if isinstance(result.get("returns_summary"), dict) else {}
    view["return"] = _num(summary.get("total"))
    block = result.get("asset_series") if isinstance(result.get("asset_series"), dict) else {}
    series = block.get("daily") if isinstance(block.get("daily"), list) else []
    dated = [( _iso(row.get("date")), row) for row in series if isinstance(row, dict)]
    dates = sorted(day for day, _ in dated if day)
    view["rows"] = len(dates)
    if dates:
        view["covered_start"], view["covered_end"] = dates[0], dates[-1]
    if view["return"] is None:
        ctx.problem("本周收益", f"指标未返回 returns_summary.total（区间 {start}..{end}）")
        return view
    if not dates:
        ctx.problem("本周收益", "指标返回了收益但 asset_series.daily 为空，无法核对日期覆盖")
        return view
    view["contains_actual"] = end in dates
    if not view["contains_actual"]:
        ctx.problem("本周收益", f"asset_series.daily 日期集合不含实际报告日 {end}；"
                                "该收益只代表样本末日及之前的实测值")
    if expected_days:
        view["missing_days"] = sorted(set(expected_days) - set(dates))[:10]
        view["extra_days"] = sorted(set(dates) - set(expected_days))[:10]
        if view["missing_days"]:
            ctx.problem("本周收益", "指标样本缺少交易所交易日：" + "、".join(view["missing_days"]))
        if view["extra_days"]:
            ctx.problem("本周收益", "指标样本含交易所日历之外的日期：" + "、".join(view["extra_days"]))
    last_cum = next((_num(row.get("cumulative_returns")) for day, row in dated
                     if day == view["covered_end"]), None)
    if last_cum is not None:
        view["consistency"] = abs(last_cum - view["return"])
        if view["consistency"] > 1e-4:
            ctx.problem("本周收益", "returns_summary.total 与同响应 asset_series 累计收益不一致")
    if expected_days is None:
        view["days_checked"] = False
        if view["covered_start"] > start:
            view["start_note"] = ("产品日历不是 exchange：交易所日历无法证明周一是否休市，"
                                  f"样本起点 {view['covered_start']} 晚于自然周 {start} 只作参照，"
                                  "不判为缺口")
    elif not expected_days:
        view["days_checked"] = False
        view["start_note"] = "交易所日历在本周区间没有交易日，无法核验样本起点"
    elif view["covered_start"] > expected_days[0]:
        ctx.problem("本周收益", f"样本起点 {view['covered_start']} 晚于本周首个应有交易日 "
                                f"{expected_days[0]}")
    return view


def _risk_view(result, start, end, ctx):
    """整理风险指标与窗口内有效收益样本；不足两个有限样本时指标不作为有效结果。"""
    view = {"start": start, "end": end, "rows": 0, "samples": 0, "valid": False,
            "first": None, "last": None, "metrics": {}, "missing_core": []}
    if not isinstance(result, dict):
        ctx.problem("风险", f"{start}..{end} 的风险指标未返回")
        return view
    daily = result.get("daily_risk") if isinstance(result.get("daily_risk"), dict) else {}
    for name, _, _ in RISK_FIELDS:
        value = _num(daily.get(name))
        if value is not None:
            view["metrics"][name] = value
    block = result.get("asset_series") if isinstance(result.get("asset_series"), dict) else {}
    series = block.get("daily") if isinstance(block.get("daily"), list) else []
    dated = {}
    for row in series:
        if not isinstance(row, dict):
            continue
        day = _iso(row.get("date"))
        if day and start <= day <= end:
            dated[day] = row
    dates = sorted(dated)
    view["rows"] = len(dates)
    view["samples"] = sum(1 for row in dated.values()
                          if _num(row.get("daily_returns")) is not None)
    if dates:
        view["first"], view["last"] = dates[0], dates[-1]
    view["missing_core"] = [name for name in ("annual_volatility", "max_drawdown")
                            if name not in view["metrics"]]
    view["valid"] = view["samples"] >= 2 and not view["missing_core"]
    if not view["metrics"]:
        ctx.problem("风险", "daily_risk 没有任何可用指标，无法报告波动或回撤")
    else:
        for name, label, _ in RISK_FIELDS:
            if name in ("annual_volatility", "max_drawdown") and name not in view["metrics"]:
                ctx.problem("风险", f"daily_risk 未返回{label}（{name}），不把它写成有效风险结果")
    if not series:
        ctx.problem("风险", "风险响应没有 asset_series.daily，无法核对样本日期与真实结束日")
    elif not dates:
        ctx.problem("风险", f"asset_series.daily 不含窗口 {start}..{end} 内的日期")
    if view["samples"] < 2:
        ctx.problem("风险", f"窗口内去重日期 {view['rows']} 个、有限 daily_returns 有效样本 "
                            f"{view['samples']} 个（要求至少 2），风险指标不可作为有效结果")
    return view


def _style_view(exposure, attribution, attribution_id, prev_date, historical, ctx):
    """整理实时风格截面；仅在给出已有归因时对齐真实 T-1 暴露行。

    实时暴露接口没有日期参数；as-of 历史模式下该截面只代表当前时点。
    """
    view = {"points": 0, "datetime": None, "series_start": None, "series_end": None,
            "values": {}, "t1": None, "note": None}
    if not isinstance(exposure, dict):
        ctx.problem("风格", "实时因子暴露未返回")
    else:
        view["series_start"], view["series_end"] = exposure.get("start"), exposure.get("end")
        series = [row for row in exposure.get("exposure_series") or [] if isinstance(row, dict)]
        view["points"] = len(series)
        if not series:
            ctx.problem("风格", "实时暴露只有区间信息；持仓可能无股票或暴露未就绪，这不是零暴露")
        else:
            latest = max(series, key=lambda row: str(row.get("datetime") or ""))
            view["datetime"] = latest.get("datetime")
            values = {name: _num(value) for name, value in latest.items() if name != "datetime"}
            view["values"] = {name: value for name, value in values.items() if value is not None}
            if not view["values"]:
                ctx.problem("风格", "实时暴露最新时点没有任何可用因子数值")
    if historical:
        ctx.problem("风格", "realtime_factor_exposure 不接受日期参数，返回的是当前时点截面，"
                            "不属于 --as-of 指定的历史业务日")
        view["note"] = "as-of 历史模式下实时风格只代表当前时点，不能当作目标业务日的截面。"
    if not attribution_id:
        view["note"] = view["note"] or "未提供 --attribution-id；本次只报告当前截面，不读取也不创建历史归因"
        return view
    if not isinstance(attribution, dict):
        ctx.problem("风格", f"已存归因 {attribution_id} 未能读取，无法比较 T-1 风格")
        return view
    record_id = str(attribution.get("_id") or attribution.get("id") or "")
    if record_id and record_id != str(attribution_id):
        ctx.problem("风格", f"归因记录 {record_id} 与请求 ID {attribution_id} 不一致")
    if attribution.get("status") != "SUCCESS":
        ctx.problem("风格", f"归因 {attribution_id} 状态为 {attribution.get('status')}，没有可比结果")
        return view
    template = attribution.get("template")
    if template != "equity/factor":
        ctx.problem("风格", f"归因 {attribution_id} 的模板 {template or '缺失'} 与实时暴露固定模板 "
                            "equity/factor 不一致，同名因子不能直接相减；本次不做 T-1 比较")
        return view
    result = attribution.get("result") if isinstance(attribution.get("result"), dict) else {}
    block = result.get("attribution") if isinstance(result.get("attribution"), dict) else {}
    rows = block.get("factor_exposure") if isinstance(block.get("factor_exposure"), list) else []
    t1 = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("data"), list):
            continue
        found = next((_num(item.get("active")) for item in row["data"]
                      if isinstance(item, dict) and _iso(item.get("date")) == prev_date), None)
        if found is not None and row.get("factor"):
            t1[str(row["factor"])] = found
    view["t1"] = {"id": record_id or attribution_id, "template": template,
                  "range": f"{_iso(attribution.get('start_date'))}..{_iso(attribution.get('end_date'))}",
                  "date": prev_date, "diffs": []}
    if not t1:
        ctx.problem("风格", f"已存归因 {attribution_id} 的 factor_exposure 不含 {prev_date} 的 "
                            "data.date 行，无法比较 T-1 风格")
        return view
    diffs = [{"factor": name, "current": current, "t1": t1[name], "change": current - t1[name]}
             for name, current in view["values"].items() if name in t1]
    diffs.sort(key=lambda row: abs(row["change"]), reverse=True)
    view["t1"]["diffs"] = diffs[:10]
    view["t1"]["common"] = len(diffs)
    return view


def _nav_view(report):
    """提取一份头寸报表的净值与收益字段，缺失保留为 None。"""
    view = {name: _num(report.get(name)) for name in NAV_FIELDS}
    view["date"] = _iso(report.get("date"))
    update_time = report.get("update_time")
    view["update_time"] = update_time if isinstance(update_time, str) else None
    return view


def _summary_lines(sections):
    """按固定优先级提取最多三条有证据的重点变化，不调用模型。"""
    lines = []
    nav = sections.get("nav") or {}
    if nav.get("daily_returns") is not None:
        text = f"当日收益 {_pct(nav['daily_returns'])}"
        if nav.get("benchmark_returns") is not None:
            text += f"，基准 {_pct(nav['benchmark_returns'])}"
        if nav.get("excess_returns") is not None:
            text += f"，超额 {_pct(nav['excess_returns'])}"
        lines.append(text + f"（业务日期 {nav.get('date') or '缺失'}，同一快照）")
    week = sections.get("week") or {}
    if week.get("return") is not None:
        lines.append(f"本自然周 {week.get('covered_start') or week.get('start')}.."
                     f"{week.get('covered_end') or week.get('end')} 累计 {_pct(week['return'])}"
                     f"（样本 {week.get('rows')} 个）")
    diff = sections.get("diff") or {}
    if diff.get("new"):
        item = diff["new"][0]
        lines.append(f"前十新进 {item.get('symbol') or item.get('order_book_id')}"
                     f"（{item.get('asset_class')}/{item.get('direction')}）")
    elif diff.get("exited"):
        item = diff["exited"][0]
        lines.append(f"前十退出 {item.get('symbol') or item.get('order_book_id')}"
                     f"（{item.get('asset_class')}/{item.get('direction')}）")
    elif diff.get("changes"):
        item = max(diff["changes"], key=lambda row: abs(row.get("weight_change") or 0.0))
        if item.get("weight_change") is not None and abs(item["weight_change"]) >= 0.01:
            lines.append(f"前十中 {item.get('symbol') or item.get('order_book_id')} 占净值变化 "
                         f"{item['weight_change']:+.2f}pp")
    style = sections.get("style") or {}
    if (style.get("t1") or {}).get("diffs"):
        item = style["t1"]["diffs"][0]
        lines.append(f"风格 {item['factor']} 相对 T-1 变化 {item['change']:+.4f}（观测值，不作因果解释）")
    elif style.get("values"):
        name, value = max(style["values"].items(), key=lambda item: abs(item[1]))
        lines.append(f"当前最大主动风格暴露为 {name} {value:+.4f}（实时截面）")
    risk = sections.get("risk") or {}
    risk_metrics = risk.get("metrics") or {}
    if (risk.get("valid") and risk_metrics.get("max_drawdown") is not None
            and risk_metrics.get("annual_volatility") is not None):
        lines.append(f"风险窗口 {risk.get('start')}..{risk.get('last') or risk.get('end')} "
                     f"最大回撤 {_pct(risk_metrics['max_drawdown'])}、"
                     f"年化波动 {_pct(risk_metrics['annual_volatility'])}")
    return lines[:3]


def _pct(value):
    """把小数比例显示为百分数；缺失返回“缺失”。"""
    number = _num(value)
    return "缺失" if number is None else f"{number * 100:.2f}%"


def _pp(value):
    """把权重数值显示为带符号百分点；缺失返回“缺失”。"""
    number = _num(value)
    return "缺失" if number is None else f"{number:+.2f}pp"


def _pctp(value):
    """显示已经是百分数单位的权重；与按小数比例乘 100 的 _pct 区分。"""
    number = _num(value)
    return "缺失" if number is None else f"{number:.2f}%"


def _money(value):
    """金额显示为千分位两位小数；缺失返回“缺失”。"""
    number = _num(value)
    return "缺失" if number is None else f"{number:,.2f}"


def _txt(value, digits=4):
    """普通数值按指定小数位显示；缺失返回“缺失”。"""
    number = _num(value)
    return "缺失" if number is None else f"{number:,.{digits}f}"


def _map(value):
    """安全返回字典；非字典按空字典处理。"""
    return value if isinstance(value, dict) else {}


def _cell(value):
    """把单元格值转成安全的 Markdown 文本。"""
    if value is None:
        return "缺失"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(headers, rows):
    """把二维单元格渲染为 Markdown 表格；无行时返回缺口提示。"""
    if not rows:
        return "无可用数据。"
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _issues(problems):
    """把框架问题列表渲染为“分区 + 文案”条目。"""
    lines = []
    for item in problems or []:
        if isinstance(item, dict):
            lines.append(f"- [{item.get('section') or '未分类'}] {item.get('message') or ''}")
        else:
            lines.append(f"- [未分类] {item}")
    return "\n".join(lines) or "无（本轮登记的缺口为空）"


def render(data):
    """渲染完整中文 Markdown 简报；即使没有业务数据也输出终态、缺口与计时。"""
    data = _map(data)
    sections = _map(data.get("sections"))
    product, dates = _map(sections.get("product")), _map(sections.get("dates"))
    nav, week = _map(sections.get("nav")), _map(sections.get("week"))
    risk, style = _map(sections.get("risk")), _map(sections.get("style"))
    concentration, diff = _map(sections.get("concentration")), _map(sections.get("diff"))
    meta, state = _map(sections.get("meta")), data.get("state") or "unknown"
    benchmark = _map(product.get("benchmark"))
    benchmark_text = (f"{benchmark.get('type')},{benchmark.get('id')}"
                      if benchmark.get("type") and benchmark.get("id") else "缺失")
    head = "\n".join([
        f"# {product.get('name') or '单产品'} 业务简报",
        f"- 状态：**{state}**（complete/partial/failed/timeout，不留 running）",
        f"- 目标：{product.get('name') or '未解析'}"
        + (f"（`{product.get('id')}`）" if product.get("id") else ""),
        f"- 属性：label={product.get('label') or '缺失'}；data_source={product.get('data_source') or '缺失'}；"
        f"策略={product.get('strategy_category') or '缺失'}；投资类别={product.get('investment_category') or '缺失'}",
        f"- 日历/基准：{product.get('calendar') or '缺失'} / {benchmark_text}",
        f"- 业务日期：{dates.get('actual') or '缺失'}；请求：{meta.get('requested') or '实时'}；"
        f"预期最新交易日：{dates.get('expected') or '未核验'}",
        f"- 生成时间（北京时间）：{meta.get('clock') or '缺失'}",
        "- 取值：净值/当日收益/前十/资产与行业暴露来自同一次当前快照；周收益与风险来自服务端指标；"
        "风格来自实时暴露；只有提供 --attribution-id 时才读取已存归因的 T-1 行。",
    ])
    summary = sections.get("summary") if isinstance(sections.get("summary"), list) else []
    summary_text = "\n".join(f"{i}. {text}" for i, text in enumerate(summary, 1)) or \
        "无可用重点变化；见下方缺口。"
    summary_section = ("## 重点变化（最多三条，确定性提取）\n" + summary_text +
                       "\n\n以上均为观测事实，不包含因果判断。")

    nav_rows = [
        ("业务日期", nav.get("date") or "缺失", "响应 date，不是请求时间"),
        ("单位净值", _txt(nav.get("unit_net_value")), "不是收益率"),
        ("累计单位净值", _txt(nav.get("acc_unit_net_value")), "累计分红口径"),
        ("净资产", _money(nav.get("total_equity")), "总资产减总负债"),
        ("当日收益", _pct(nav.get("daily_returns")), "服务端 daily_returns，不是净值环比"),
        ("当日盈亏", _money(nav.get("daily_pnl")), "金额，不是收益率"),
        ("当日基准收益", _pct(nav.get("benchmark_returns")), "同一快照"),
        ("当日超额收益", _pct(nav.get("excess_returns")), "同一快照"),
        ("更新时间", nav.get("update_time") or "缺失", "头寸报表重算时间，不是行情 tick"),
    ]
    week_checked = week.get("days_checked")
    week_missing_text = ("未核验" if week_checked is False
                         else ("、".join(week.get("missing_days") or []) or "无"))
    week_missing_note = ("无交易所日历依据，不能判缺" if week_checked is False
                         else "交易所日历应有 "
                              f"{week.get('expected_days') if week.get('expected_days') is not None else '未知'} 个")
    week_rows = [
        ("自然周收益", _pct(week.get("return")), "returns_summary.total"),
        ("请求区间", f"{week.get('start') or '缺失'}..{week.get('end') or '缺失'}", "周一至实际日期"),
        ("样本覆盖", f"{week.get('covered_start') or '缺失'}..{week.get('covered_end') or '缺失'}",
         f"样本 {week.get('rows') or 0} 个"),
        ("是否含实际报告日",
         "是" if week.get("contains_actual") else ("否" if week.get("contains_actual") is False else "缺失"),
         "asset_series.daily 日期集合检查"),
        ("缺失交易日", week_missing_text, week_missing_note),
        ("日历外样本", "、".join(week.get("extra_days") or []) or "无", "不应据此外推"),
        ("同响应一致性", ("差 %.8f" % week["consistency"]) if week.get("consistency") is not None else "缺失",
         "returns_summary.total 与期末累计收益之差"),
    ]
    nav_section = ("## 最新净值与收益\n\n" + _table(["项目", "值", "说明"], nav_rows) +
                   "\n\n### 本自然周\n\n" + _table(["项目", "值", "说明"], week_rows) +
                   (f"\n\n{week['start_note']}" if week.get("start_note") else ""))

    date_rows = [
        ("实际业务日期", dates.get("actual") or "缺失", "响应 date"),
        ("报告模式", "历史 as-of（风格截面不是该日）" if dates.get("historical") else "实时/当日", ""),
        ("预期最新交易日", dates.get("expected") or "未核验", "trading_dates(type='exchange') 截至查询日的末项"),
        ("日历查询截止日", dates.get("target") or "缺失", "实时为北京时间今天；as-of 为请求日"),
        ("预期交易日已核验", "是" if dates.get("verified") else "否",
         "仅交易所日历；非 exchange 产品不能冒充已核验"),
        ("上一交易日", dates.get("previous") or "缺失", dates.get("previous_source") or "缺失"),
        ("自然周起点", dates.get("week_monday") or "缺失", "自然周周一，不是滚动 this_week"),
        ("风险窗口", f"{dates.get('risk_start') or '缺失'}..{dates.get('risk_end') or '缺失'}",
         f"{dates.get('risk_days') or '缺失'} 个自然日；实际样本结束日见风险章节"),
        ("更新时间", dates.get("update_time") or "缺失", "日期需与业务日期一致"),
        ("缺失字段", "、".join(dates.get("missing") or []) or "无", "当前快照"),
    ]
    if dates.get("historical"):
        requested = meta.get("requested")
        date_rows.insert(1, ("as-of 请求日对比", f"请求 {requested or '缺失'} / 响应 "
                                                f"{dates.get('actual') or '缺失'}",
                             "一致" if requested == dates.get("actual") else "不一致，已登记缺口"))
    dates_section = "## 日期与完整性\n\n" + _table(["项目", "值", "说明"], date_rows)

    top_rows = []
    for raw in sections.get("top10") if isinstance(sections.get("top10"), list) else []:
        row = _map(raw)
        top_rows.append([row.get("rank"), row.get("order_book_id") or "缺失",
                         row.get("symbol") or "缺失", row.get("asset_class") or "缺失",
                         row.get("direction") or "缺失", row.get("industry") or "—",
                         _money(row.get("market_value"))
                         + ("（部分）" if row.get("market_value_partial") else ""),
                         _pctp(row.get("weight_pct")),
                         _txt(row.get("quantity"), 2), row.get("prev_rank") or "前十外"])
    top_section = ("## 前十持仓（按绝对市值）\n\n"
                   "筛选口径：全部叶子持仓按 |market_value| 降序取十，包含非股票与多空两个方向；"
                   "零市值不参与排名。占净值权重为带符号市值/净资产，净资产不为正时不计算；"
                   "行业列只对股票多头显示（A 股中信一级、港股申万一级）。\n\n"
                   + _table(["排名", "代码", "名称", "资产类别", "方向", "行业",
                             "市值", "占净值（带符号）", "数量", "昨日排名"], top_rows))

    nav_positive = concentration.get("nav_positive")
    conc_complete = concentration.get("complete")
    if not nav_positive:
        nav_note = "未取得净资产，未计算" if nav_positive is None else "净资产不为正，不计算"
    elif conc_complete is False:
        nav_note = "仅已知金额小计（partial），含缺市值持仓"
    else:
        nav_note = "仅净资产>0 时计算"
    conc_rows = [
        ("参与排名的持仓数", concentration.get("positions", "缺失"), "|市值|>0 的聚合持仓键"),
        ("缺市值持仓", concentration.get("missing_positions", "缺失"),
         "非 0 时以下比例与集中度只覆盖已知金额"),
        ("前三占净值", _pctp(concentration.get("top3_nav_pct")), nav_note),
        ("前十占净值", _pctp(concentration.get("top10_nav_pct")), nav_note),
        ("前十占全部绝对市值", _pctp(concentration.get("top10_share_pct")), "绝对市值口径"),
    ]
    asset_rows = []
    for raw in sections.get("asset_classes") or []:
        row = _map(raw)
        coverage = ("完整" if row.get("complete") is True else
                    (f"缺 {row.get('missing') or 0} 条（已知小计）"
                     if row.get("complete") is False else "缺失"))
        asset_rows.append([row.get("asset_class") or "缺失", row.get("count"),
                           _money(row.get("value")), _pctp(row.get("nav_pct")), coverage])
    conc_section = ("## 集中度与资产类别暴露\n\n" + _table(["指标", "值", "说明"], conc_rows) +
                    "\n\n### 资产类别（全部叶子持仓，含其他仓位）\n\n"
                    + _table(["资产类别", "记录数", "带符号市值", "占净值", "覆盖"], asset_rows))

    change_rows = []
    for raw in diff.get("changes") or []:
        row = _map(raw)
        rank_text = f"{row.get('rank') or '前十外'}/{row.get('prev_rank') or '前十外'}"
        if row.get("rank_change") is not None:
            rank_text += f"（{row['rank_change']:+d}）"
        change_rows.append([row.get("order_book_id") or "缺失", row.get("symbol") or "缺失",
                            row.get("asset_class") or "缺失", row.get("direction") or "缺失",
                            rank_text, _pp(row.get("weight_change")),
                            _money(row.get("market_value_change")),
                            _txt(row.get("qty_change"), 2)])
    names = lambda items: "、".join(
        f"{_map(item).get('symbol') or _map(item).get('order_book_id')}"
        f"（{_map(item).get('asset_class')}/{_map(item).get('direction')}）"
        for item in items or []) or "无"
    if diff.get("available"):
        diff_intro = (f"- 前十新进：{names(diff.get('new'))}\n"
                      f"- 前十退出：{names(diff.get('exited'))}\n"
                      "- 口径：只比较两个期末持仓键；数量不变也可能先买后卖，不能据此证明期间无交易。")
    else:
        diff_intro = ("- 昨日持仓不可用或不可比较：本次不给出前十名单、权重、数量或市值变化；"
                      "这不是“无变化”。")
    diff_section = ("## 昨日以来前十变化\n\n" + diff_intro + "\n\n"
                    + _table(["代码", "名称", "资产类别", "方向", "名次 今/昨",
                              "占净值变化", "市值变化", "数量变化"], change_rows))

    industry_rows = []
    for raw in sections.get("industries") or []:
        row = _map(raw)
        coverage = ("完整" if row.get("complete") is True else
                    (f"缺 {row.get('missing') or 0} 条（已知小计）"
                     if row.get("complete") is False else "缺失"))
        industry_rows.append([row.get("industry") or "缺失", row.get("count"),
                              _money(row.get("value")), _pctp(row.get("nav_pct")), coverage])
    industry_section = ("## 行业暴露（股票多头）\n\n"
                        + _table(["行业", "只数", "市值", "占净值", "覆盖"], industry_rows))

    style_values = _map(style.get("values"))
    style_rows = [[name, _txt(value, 4)] for name, value in
                  sorted(style_values.items(), key=lambda item: abs(_num(item[1]) or 0.0),
                         reverse=True)[:10]]
    t1 = _map(style.get("t1"))
    diff_rows = []
    for raw in t1.get("diffs") or []:
        row = _map(raw)
        diff_rows.append([row.get("factor") or "缺失", _txt(row.get("current")),
                          _txt(row.get("t1")), f"{_num(row.get('change')) or 0.0:+.4f}"])
    if t1:
        t1_meta = (f"归因 {t1.get('id')}，模板 {t1.get('template') or '缺失'}，区间 {t1.get('range')}，"
                   f"对齐日期 {t1.get('date')}，匹配因子 {t1.get('common', 0)} 个")
    elif meta.get("attribution_id"):
        t1_meta = f"已请求归因 {meta['attribution_id']}，但未取得可用 T-1 行；见缺口。"
    else:
        t1_meta = "未提供 --attribution-id，因此没有 T-1 风格比较（不是数据失败）。"
    style_note = style.get("note") or (
        f"实时序列 {style.get('series_start') or '缺失'}..{style.get('series_end') or '缺失'}，"
        f"时点数 {style.get('points') or 0}，最新时点 {style.get('datetime') or '缺失'}。"
        "暴露为持仓加权暴露减基准暴露；因子键名以实际返回为准。")
    style_section = ("## 风格与因子暴露\n\n" + style_note +
                     "\n\n### 当前实时截面（按绝对暴露降序，最多 10 项）\n\n"
                     + _table(["因子", "主动暴露"], style_rows) +
                     "\n\n### 与真实 T-1 比较\n\n" + t1_meta + "\n\n"
                     + _table(["因子", "当前", "T-1", "变化"], diff_rows))

    risk_metrics = _map(risk.get("metrics"))
    risk_valid = risk.get("valid")
    risk_rows = []
    for name, label, as_percent in RISK_FIELDS:
        value = risk_metrics.get(name)
        if name not in risk_metrics:
            status = "缺失"
        else:
            reason = "核心指标缺失" if risk.get("missing_core") else "样本不足"
            status = "已返回" if risk_valid is True else f"已返回但{reason}，不可验收"
        risk_rows.append([label, _pct(value) if as_percent else _txt(value), status])
    if risk_valid is True:
        valid_line = "- 窗口内有效收益样本满足至少 2 个；指标仍为观测值。\n"
    elif risk_valid is False:
        valid_line = ("- 有效收益样本不足 2 个或核心指标缺失：风险指标不作为有效结果，"
                      "也不进入重点变化。\n")
    else:
        valid_line = "- 风险指标未取得。\n"
    risk_section = ("## 风险窗口\n\n"
                    f"- 请求窗口：{risk.get('start') or '缺失'}..{risk.get('end') or '缺失'}\n"
                    f"- 实际样本：{risk.get('first') or '缺失'}..{risk.get('last') or '缺失'}，"
                    f"窗口内去重日期 {risk.get('rows') or 0} 个，有限 daily_returns 有效样本 "
                    f"{risk.get('samples') if risk.get('samples') is not None else 0} 个\n"
                    + valid_line + "\n"
                    + _table(["指标", "值", "状态"], risk_rows))

    step_rows, step_total = [], 0.0
    for step in [item for item in data.get("steps") or [] if isinstance(item, dict)]:
        seconds = _num(step.get("seconds"))
        if seconds is not None:
            step_total += seconds
        step_rows.append([step.get("operation") or "未命名",
                          "缺失" if seconds is None else f"{seconds:.2f}",
                          step.get("state") or "unknown"])
    steps_section = ("## 阶段计时\n\n" + _table(["阶段", "耗时（秒）", "状态"], step_rows) +
                     f"\n\n阶段耗时合计 {step_total:.2f} 秒（各项之和，不等于端到端墙钟）。")

    scope_section = ("## 来源与只读说明\n\n"
                     "- 目标解析一次；当前快照、前十与暴露来自同一响应，周收益/风险来自服务端指标。\n"
                     "- 本次不修改产品、流水、估值或持仓；不创建归因；已存归因仅按给定 ID 读取。\n"
                     "- 本报告不含令牌、认证头或凭据文件内容；数值缺失保留为“缺失”，不补零。\n"
                     "- 不同来源的同名指标不混算；变化为观测事实，不包含因果结论。")

    return "\n\n".join([
        head, summary_section, nav_section, dates_section, top_section, conc_section,
        diff_section, industry_section, style_section, risk_section,
        "## 缺口与限制\n\n" + _issues(data.get("problems")), steps_section, scope_section,
    ]) + "\n"


if __name__ == "__main__":
    launch(collect, render, configure)
