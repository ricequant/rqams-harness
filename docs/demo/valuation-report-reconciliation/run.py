"""估值报告对账：结构化导入、精确更正、下载源 CSV 核对与按日期删除。

本脚本只操作来源日志记录的自有产品与报告。上传前先读同日报告；覆盖必须显式给出
``--replace-dates``，不做无条件覆盖。下载后用标准库解析 CSV 并核对日期、净资产、
份额与单位净值，不以文件非空代替业务检查。凭据只从 ``RQAMSH_TOKEN`` 读取。
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import re
from pathlib import Path
import sys
import time
import zipfile

import rqamsh
from rqamsh.errors import HarnessError


def claim_output(path: Path, conflicts: list[Path | None] = ()) -> object:
    """在任何业务请求前独占创建证据文件，拒绝覆盖历史或与输入同路径。"""
    target = Path(path).resolve()
    for item in conflicts:
        if item is not None and Path(item).resolve() == target:
            raise HarnessError("invalid_argument", "--output 不得与 journal 或输入文件相同")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        return target.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise HarnessError("invalid_argument", "--output 已存在；拒绝覆盖历史证据") from exc


def emit_evidence(handle, evidence: dict) -> None:
    """把终态证据写入已独占持有的证据句柄。"""
    handle.seek(0)
    handle.truncate()
    json.dump(evidence, handle, ensure_ascii=False, indent=2, default=str)
    handle.flush()


def now() -> str:
    """返回带时区的当前时间字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_error(exc: Exception) -> dict:
    """只保留可定位的错误类型、错误码与 HTTP 状态，不复制服务端正文。"""
    return {
        "type": type(exc).__name__,
        "code": getattr(exc, "code", None),
        "status": getattr(exc, "status", None),
    }


def load_journal(path: Path, base_url: str, workspace_id: str) -> dict:
    """读取并核对来源日志；缺失时初始化空结构。"""
    if not path.exists():
        return {"base_url": base_url, "workspace_id": workspace_id, "products": [],
                "reports": [], "events": []}
    journal = json.loads(path.read_text(encoding="utf-8"))
    if journal.get("base_url") != base_url or journal.get("workspace_id") != workspace_id:
        raise HarnessError("invalid_argument", "来源日志的部署或空间与本次连接不一致")
    journal.setdefault("products", [])
    journal.setdefault("reports", [])
    journal.setdefault("events", [])
    return journal


def save_journal(path: Path, journal: dict) -> None:
    """原子写入来源日志。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def owned_product(journal: dict, product_id: str, name: str) -> dict:
    """确认产品来自本日志记录。"""
    for row in journal.get("products", []):
        if (row.get("id") == product_id and row.get("name") == name
                and row.get("status", "verified") == "verified"):
            return row
    raise HarnessError("invalid_argument", "目标产品不是该来源日志记录的自有资源")


def append_report(journal: dict, product_id: str, date: str, report_id: str) -> None:
    """把本次实际写入的报告记录到来源日志。"""
    for row in journal.setdefault("reports", []):
        if row.get("product_id") == product_id and row.get("date") == date:
            row["valuation_report_id"] = report_id
            return
    journal["reports"].append({"product_id": product_id, "date": date,
                               "valuation_report_id": report_id})


def report_rows(client, product: str, start: str, end: str) -> list:
    """读取指定区间的报告元数据。"""
    result = client.valuation_reports.list(product, start_date=start, end_date=end)
    return result if isinstance(result, list) else []


def validate_report(data: dict) -> None:
    """在上传前校验结构化报告必填业务字段。"""
    required = ("date", "total_equity", "units", "unit_net_value", "positions")
    missing = [key for key in required if key not in data]
    if missing:
        raise HarnessError("invalid_argument", f"报告缺少必填字段：{missing}")
    if not isinstance(data["positions"], list) or not data["positions"]:
        raise HarnessError("invalid_argument", "报告 positions 必须为非空数组")


def sha256_file(path: Path) -> str:
    """计算本地文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_numbers(path: Path) -> list[float]:
    """提取 CSV 或 XLSX 内部的数值单元，用于内容核对。"""
    values: list[float] = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith(".xml"):
                    continue
                text = archive.read(name).decode("utf-8", errors="replace")
                for match in re.finditer(
                        r"<(?:v|t)(?: [^>]*)?>(-?[0-9]+(?:\.[0-9]+)?)</(?:v|t)>", text):
                    try:
                        values.append(float(match.group(1)))
                    except ValueError:
                        continue
    else:
        text = path.read_bytes().decode("utf-8", errors="replace").replace(",", "")
        for match in re.finditer(r"(?<![A-Za-z0-9.-])-?[0-9]+(?:\.[0-9]+)?", text):
            try:
                values.append(float(match.group(0)))
            except ValueError:
                continue
    return values


def content_text(path: Path) -> str:
    """返回 CSV 文本或 XLSX 内全部 XML 文本，供日期核对。"""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return "\n".join(
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist() if name.endswith(".xml")
            )
    return path.read_bytes().decode("utf-8-sig", errors="replace")


def same_value(actual, expected, tolerance: float) -> bool:
    """比较业务数值；期望或实际为 None 时只有同为 None 才算相等。"""
    if expected is None:
        return actual is None
    if actual is None:
        return False
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (TypeError, ValueError):
        return False


def balance_matches(row, date: str, equity, nav) -> bool:
    """日期、净资产与单位净值同时匹配才视为替换完成。"""
    return (isinstance(row, dict) and row.get("date") == date
            and same_value(row.get("total_equity"), equity, 1e-6)
            and same_value(row.get("unit_net_value"), nav, 1e-9))


def balance_row(payload) -> object:
    """兼容任务包装：状态成功时读取 data 中的头寸对象。"""
    if isinstance(payload, dict) and str(payload.get("status", "")).lower() == "success" \
            and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload


def numeric_cells(rows: list[list[str]]) -> list[float]:
    """收集 CSV 中可解析的数值单元。"""
    values = []
    for row in rows:
        for cell in row:
            try:
                values.append(float(cell.replace(",", "").strip()))
            except (TypeError, ValueError):
                continue
    return values


def main() -> int:
    """执行估值报告子命令并写入终态证据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm", required=True, help="目标产品名称")
    parser.add_argument("--product", required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    upload = sub.add_parser("upload", help="批量上传结构化报告")
    upload.add_argument("--reports-dir", type=Path, required=True)
    upload.add_argument("--replace-dates", nargs="+")
    upload.add_argument("--is-overwrite", action="store_true")
    upload.add_argument("--wait-seconds", type=float, default=90)
    replace = sub.add_parser("replace", help="按白名单替换某日错误报告")
    replace.add_argument("--date", required=True)
    replace.add_argument("--data", type=Path, required=True)
    replace.add_argument("--wait-seconds", type=float, default=90)
    download = sub.add_parser("download-csv", help="下载结构化报告的源 CSV 并核对内容")
    download.add_argument("--date", required=True)
    download.add_argument("--file", type=Path, required=True)
    download.add_argument("--expect-data", type=Path, required=True)
    file_upload = sub.add_parser("file-upload", help="上传受支持估值文件并核对下载源文件")
    file_upload.add_argument("--file", type=Path, required=True)
    file_upload.add_argument("--download", type=Path, required=True)
    file_upload.add_argument("--expect-date", required=True)
    file_upload.add_argument("--expect-equity", type=float, required=True)
    file_upload.add_argument("--expect-units", type=float, required=True)
    file_upload.add_argument("--expect-unit-net-value", type=float, required=True)
    delete = sub.add_parser("delete", help="按日期删除自有报告")
    delete.add_argument("--dates", nargs="+", required=True)
    read = sub.add_parser("list", help="列出报告元数据")
    read.add_argument("--start-date")
    read.add_argument("--end-date")
    args = parser.parse_args()

    token = os.environ.get("RQAMSH_TOKEN")
    evidence = {
        "state": "running", "task": "valuation-report-reconciliation", "action": args.action,
        "base_url": args.base_url, "workspace_id": args.workspace_id,
        "confirm": args.confirm, "product": args.product,
        "client_version": rqamsh.__version__, "started_at": now(), "steps": [], "writes": 0,
    }
    try:
        output_handle = claim_output(
            args.output, [args.journal, getattr(args, "data", None),
                          getattr(args, "file", None), getattr(args, "expect_data", None),
                          getattr(args, "download", None)])
    except HarnessError as exc:
        print(json.dumps({"state": "failed", "diagnostic": safe_error(exc),
                          "output": str(args.output)}, ensure_ascii=False))
        return 1
    if not token:
        evidence["state"] = "blocked"
        evidence["diagnostic"] = "RQAMSH_TOKEN_missing"
        evidence["finished_at"] = now()
        emit_evidence(output_handle, evidence)
        output_handle.close()
        print(json.dumps({"state": "blocked", "diagnostic": "RQAMSH_TOKEN_missing",
                          "output": str(args.output)}, ensure_ascii=False))
        return 2
    journal = None
    try:
        journal = load_journal(args.journal, args.base_url, args.workspace_id)
        rqamsh.init(args.base_url, args.workspace_id, token=token,
                    timeout=120, wait_timeout=600)
        client = rqamsh
        try:
            owned_product(journal, args.product, args.confirm)
            product = client.products.get(args.product)
            if product.get("name") != args.confirm:
                raise HarnessError("invalid_argument", "读回产品名称与 --confirm 不一致")
            evidence["data_source"] = product.get("data_source")

            if args.action == "upload":
                files = sorted(args.reports_dir.glob("*.json"))
                if not files:
                    raise HarnessError("invalid_argument", "reports-dir 下没有 JSON 报告")
                allowed_replace = set(args.replace_dates or [])
                for path in files:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        raise HarnessError("invalid_argument", f"{path} 不是报告对象")
                    validate_report(data)
                    date = data["date"]
                    existing = report_rows(client, args.product, date, date)
                    if existing and not (allowed_replace and date in allowed_replace) and not args.is_overwrite:
                        raise HarnessError("invalid_argument",
                                           f"{date} 已有报告；覆盖必须显式使用 --replace-dates")
                    result = client.valuation_reports.upload(
                        args.product, data=data,
                        replace_dates=[date] if allowed_replace and date in allowed_replace else None,
                        is_overwrite=args.is_overwrite,
                    )
                    evidence["writes"] += 1
                    if result.get("date") != date or not result.get("valuation_report_id"):
                        raise HarnessError("invalid_response", f"{date} 上传返回日期或报告 ID 不一致")
                    metas = report_rows(client, args.product, date, date)
                    if not any(row.get("date") == date for row in metas):
                        raise HarnessError("invalid_response", f"{date} 上传后列表不可见")
                    append_report(journal, args.product, date, result["valuation_report_id"])
                    journal["events"].append({"at": now(), "script": "valuation-report-reconciliation",
                                              "action": "upload", "product_id": args.product,
                                              "date": date})
                    save_journal(args.journal, journal)
                    evidence["steps"].append({
                        "step": "upload", "date": date,
                        "effect_count": result.get("effect_count"),
                        "is_modified": result.get("is_modified"),
                        "valuation_report_id": result.get("valuation_report_id"),
                        "existing_before": len(existing),
                    })
                evidence["state"] = "passed"

            elif args.action == "replace":
                data = json.loads(args.data.read_text(encoding="utf-8"))
                validate_report(data)
                if data["date"] != args.date:
                    raise HarnessError("invalid_argument", "--date 与报告文件日期不一致")
                before_meta = [
                    {key: row.get(key) for key in (
                        "date", "valuation_report_id", "source", "valuation_level")}
                    for row in report_rows(client, args.product, args.date, args.date)
                ]
                before_balance = balance_row(client.balances.get(
                    args.product, date=args.date,
                    fields=["date", "total_equity", "unit_net_value"],
                ))
                result = client.valuation_reports.upload(
                    args.product, data=data, replace_dates=[args.date],
                )
                evidence["writes"] += 1
                if result.get("date") != args.date or not result.get("valuation_report_id"):
                    raise HarnessError("invalid_response", "替换返回日期或报告 ID 不一致")
                append_report(journal, args.product, args.date, result["valuation_report_id"])
                save_journal(args.journal, journal)
                deadline = time.monotonic() + args.wait_seconds
                after_balance = None
                attempts = []
                expected_equity = data.get("total_equity")
                expected_nav = data.get("unit_net_value")
                while time.monotonic() <= deadline:
                    try:
                        after_balance = balance_row(client.balances.get(
                            args.product, date=args.date,
                            fields=["date", "total_equity", "unit_net_value"],
                        ))
                        attempts.append({
                            "date": after_balance.get("date"),
                            "total_equity": after_balance.get("total_equity"),
                            "unit_net_value": after_balance.get("unit_net_value"),
                        })
                        if balance_matches(after_balance, args.date,
                                           expected_equity, expected_nav):
                            break
                    except Exception as exc:  # noqa: BLE001 - 等待读数，保留类型
                        attempts.append({"error": type(exc).__name__, "code": getattr(exc, "code", None)})
                    time.sleep(2)
                matched = balance_matches(after_balance, args.date,
                                          expected_equity, expected_nav)
                evidence["steps"].append({
                    "step": "replace", "date": args.date,
                    "effect_count": result.get("effect_count"),
                    "is_modified": result.get("is_modified"),
                    "before_meta": before_meta,
                    "before_balance": before_balance,
                    "requested": {key: data[key] for key in ("total_equity", "units", "unit_net_value")},
                    "after_balance": after_balance,
                    "attempts": attempts,
                })
                evidence["state"] = "passed" if matched else "failed"
                if not matched:
                    evidence["diagnostic"] = "替换后头寸净值未在等待期内达到请求值"

            elif args.action == "download-csv":
                metas = [row for row in report_rows(client, args.product, args.date, args.date)
                         if row.get("date") == args.date]
                if not metas:
                    raise HarnessError("invalid_argument", f"{args.date} 没有可见报告")
                report_id = metas[-1]["valuation_report_id"]
                args.file.parent.mkdir(parents=True, exist_ok=True)
                download_meta = client.valuation_reports.download(args.product, report_id, str(args.file))
                raw = args.file.read_bytes()
                text = raw.decode("utf-8-sig", errors="replace")
                rows = list(csv.reader(io.StringIO(text)))
                expected = json.loads(args.expect_data.read_text(encoding="utf-8"))
                flat_text = text.replace(",", "")
                values = numeric_cells(rows)
                checks = {
                    "date_present": expected["date"] in text,
                    "total_equity_present": any(
                        abs(value - float(expected["total_equity"])) <= 1e-6 for value in values),
                    "units_present": any(abs(value - float(expected["units"])) <= 1e-6 for value in values),
                    "unit_net_value_present": any(
                        abs(value - float(expected["unit_net_value"])) <= 1e-9 for value in values),
                }
                evidence["steps"].append({
                    "step": "download_csv", "date": args.date,
                    "valuation_report_id": report_id,
                    "download": download_meta, "size": len(raw),
                    "header": rows[0][:12] if rows else [],
                    "row_count": len(rows), "checks": checks,
                    "contains_date": expected["date"] in flat_text,
                })
                evidence["state"] = "passed" if all(checks.values()) and len(raw) > 0 else "failed"
                if not all(checks.values()):
                    evidence["diagnostic"] = "下载 CSV 未包含预期日期或业务数值"

            elif args.action == "file-upload":
                source_path = args.file
                if not source_path.is_file():
                    raise HarnessError("invalid_argument", "上传文件不存在")
                if source_path.suffix.lower() not in {".xls", ".xlsx"}:
                    raise HarnessError("invalid_argument", "文件入口只接受 .xls/.xlsx 估值文件")
                source_hash = sha256_file(source_path)
                result = client.valuation_reports.upload(
                    args.product, file_path=str(source_path),
                )
                evidence["writes"] += 1
                if result.get("date") != args.expect_date or not result.get("valuation_report_id"):
                    raise HarnessError("invalid_response", "文件上传返回日期或报告 ID 与预期不一致")
                metas = report_rows(client, args.product, args.expect_date, args.expect_date)
                report_meta = [
                    {key: row.get(key) for key in (
                        "date", "valuation_report_id", "source", "valuation_level")}
                    for row in metas if row.get("date") == args.expect_date
                ]
                if not report_meta:
                    raise HarnessError("invalid_response", "文件上传后列表不可见")
                hash_rows = client.products.uploaded_file_hashes(
                    [args.product], "valuation_report")
                hash_list = []
                for row in hash_rows:
                    if str(row.get("product_id")) == args.product:
                        hash_list = list(row.get("hash_list") or [])
                args.download.parent.mkdir(parents=True, exist_ok=True)
                download_meta = client.valuation_reports.download(
                    args.product, result["valuation_report_id"], str(args.download))
                downloaded_hash = sha256_file(args.download)
                same_bytes = source_hash == downloaded_hash
                text = content_text(args.download)
                numbers = content_numbers(args.download)
                content_checks = {
                    "date_present": args.expect_date in text
                                    or args.expect_date.replace("-", "") in text,
                    "total_equity_present": any(
                        abs(value - args.expect_equity) <= 1e-6 for value in numbers),
                    "units_present": any(
                        abs(value - args.expect_units) <= 1e-6 for value in numbers),
                    "unit_net_value_present": any(
                        abs(value - args.expect_unit_net_value) <= 1e-9 for value in numbers),
                }
                append_report(journal, args.product, args.expect_date,
                              result["valuation_report_id"])
                journal["events"].append({"at": now(), "script": "valuation-report-reconciliation",
                                          "action": "file_upload", "product_id": args.product,
                                          "date": args.expect_date})
                save_journal(args.journal, journal)
                evidence["steps"].append({
                    "step": "file_upload", "date": args.expect_date,
                    "effect_count": result.get("effect_count"),
                    "valuation_report_id": result.get("valuation_report_id"),
                    "report_meta": report_meta,
                    "source_sha256": source_hash,
                    "downloaded_sha256": downloaded_hash,
                    "server_hash_list": hash_list,
                    "same_bytes": same_bytes,
                    "content_checks": content_checks,
                    "download": download_meta,
                })
                business_content = all(content_checks.values())
                both_required = same_bytes and business_content
                evidence["steps"][-1]["business_content_ok"] = business_content
                evidence["steps"][-1]["both_required"] = True
                evidence["state"] = "passed" if both_required else "failed"
                if evidence["state"] != "passed":
                    evidence["diagnostic"] = "下载源文件字节或业务内容至少一项未通过"

            elif args.action == "delete":
                dates = list(dict.fromkeys(args.dates))
                journal_ids = {}
                for row in journal.get("reports", []):
                    if row.get("product_id") == args.product and row.get("date"):
                        journal_ids.setdefault(row["date"], set()).add(
                            str(row.get("valuation_report_id")))
                before = {}
                owned_ids = {}
                for date in dates:
                    rows = report_rows(client, args.product, date, date)
                    current_ids = {str(row.get("valuation_report_id")) for row in rows
                                   if row.get("date") == date and row.get("valuation_report_id")}
                    known_ids = journal_ids.get(date, set())
                    if not current_ids:
                        raise HarnessError("invalid_argument", f"{date} 当前没有可删除报告")
                    if not current_ids.issubset(known_ids):
                        raise HarnessError(
                            "invalid_argument",
                            f"{date} 当前报告 ID 不属于该日志记录的自有报告")
                    before[date] = rows
                    owned_ids[date] = sorted(current_ids)
                result = client.valuation_reports.delete(args.product, dates)
                evidence["writes"] += 1
                after = {date: len(report_rows(client, args.product, date, date)) for date in dates}
                expected = sum(1 for date in dates if before[date])
                evidence["steps"].append({
                    "step": "delete", "dates": dates, "effect_count": result.get("effect_count"),
                    "expected": expected, "before_counts": {d: len(v) for d, v in before.items()},
                    "after_counts": after, "owned_report_ids": owned_ids,
                })
                evidence["state"] = "passed" if not any(after.values()) else "failed"
                if any(after.values()):
                    evidence["diagnostic"] = "删除后仍有报告可见"
                journal["events"].append({"at": now(), "script": "valuation-report-reconciliation",
                                          "action": "delete", "product_id": args.product,
                                          "dates": dates})
                save_journal(args.journal, journal)

            else:
                rows = report_rows(client, args.product, args.start_date or product.get("start_date"),
                                   args.end_date or datetime.now(timezone.utc).date().isoformat())
                evidence["steps"].append({"step": "list", "rows": [
                    {key: row.get(key) for key in (
                        "date", "valuation_report_id", "source", "valuation_level")}
                    for row in rows
                ]})
                evidence["state"] = "passed"
        finally:
            rqamsh.close()
    except KeyboardInterrupt:
        evidence["state"] = "blocked"
        evidence["diagnostic"] = "interrupted"
    except Exception as exc:  # noqa: BLE001 - 终态必须落盘且不含凭据
        evidence["state"] = "failed"
        evidence["diagnostic"] = safe_error(exc)
    finally:
        rqamsh.close()
        evidence["finished_at"] = now()
        emit_evidence(output_handle, evidence)
        output_handle.close()
    print(json.dumps({"state": evidence["state"], "task": evidence["task"],
                      "action": evidence["action"], "output": str(args.output)}, ensure_ascii=False))
    return {"passed": 0, "blocked": 2}.get(evidence["state"], 1)


if __name__ == "__main__":
    sys.exit(main())
