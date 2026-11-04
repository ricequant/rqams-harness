"""产品生命周期：在显式测试空间创建、修改并停用专用估值报告源产品。

示例为构造型测试数据；写入前必须提供与目标产品同名的 ``--confirm``，并只在
自有测试空间运行。首次 ``create`` 需要 ``--batch-id`` 建立来源日志；后续操作
必须使用同一个日志，日志中的部署、空间和资源 ID 用于核对所有权。凭据只从
``RQAMSH_TOKEN`` 环境变量读取，不写入命令参数、日志或输出文件。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

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


def load_json(path: Path) -> dict:
    """读取 JSON 对象输入。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path} 必须是非空 JSON 对象")
    return data


def load_journal(path: Path, base_url: str, workspace_id: str) -> dict:
    """读取并核对来源日志；日志不存在时返回待初始化结构。"""
    if not path.exists():
        return {"base_url": base_url, "workspace_id": workspace_id,
                "products": [], "events": []}
    journal = json.loads(path.read_text(encoding="utf-8"))
    if journal.get("base_url") != base_url or journal.get("workspace_id") != workspace_id:
        raise HarnessError("invalid_argument", "来源日志的部署或空间与本次连接不一致")
    journal.setdefault("products", [])
    journal.setdefault("events", [])
    return journal


def save_journal(path: Path, journal: dict) -> None:
    """原子写入来源日志，保留本批自有资源 ID。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def owned_product(journal: dict, product_id: str, name: str) -> dict:
    """确认产品 ID 与名称都来自本日志的创建记录。"""
    for row in journal.get("products", []):
        if (row.get("id") == product_id and row.get("name") == name
                and row.get("status", "verified") == "verified"):
            return row
    raise HarnessError("invalid_argument", "目标产品不是该来源日志记录的自有资源")


def project_product(product: dict) -> dict:
    """只保留任务验收需要的产品配置字段。"""
    keys = ("id", "name", "report_name", "data_source", "label", "investment_category",
            "strategy_category", "start_date", "trading_start_date", "calendar",
            "benchmark", "closing_date", "product_state")
    return {key: product.get(key) for key in keys}


def main() -> int:
    """按子命令执行创建、修改或停用，并写入终态证据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm", required=True,
                        help="目标产品名称；必须与配置或读回名称完全一致")
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create", help="创建产品并记录自有来源")
    create.add_argument("--config", type=Path, required=True)
    create.add_argument("--batch-id", required=True)
    update = sub.add_parser("update", help="局部修改配置")
    update.add_argument("--product", required=True)
    update.add_argument("--data", type=Path, required=True)
    delete = sub.add_parser("delete", help="停用并核对列表不可见")
    delete.add_argument("--product", required=True)
    read = sub.add_parser("get", help="读取配置")
    read.add_argument("--product", required=True)
    args = parser.parse_args()

    token = os.environ.get("RQAMSH_TOKEN")
    evidence = {
        "state": "running", "task": "product-lifecycle", "action": args.action,
        "base_url": args.base_url, "workspace_id": args.workspace_id,
        "confirm": args.confirm, "client_version": rqamsh.__version__,
        "started_at": now(), "steps": [], "writes": 0,
    }
    try:
        output_handle = claim_output(
            args.output, [args.journal, getattr(args, "config", None),
                          getattr(args, "data", None)])
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
        if journal.get("batch_id") is None:
            journal["batch_id"] = getattr(args, "batch_id", None)
        rqamsh.init(args.base_url, args.workspace_id, token=token,
                    timeout=120, wait_timeout=600)
        client = rqamsh
        try:
            if args.action == "create":
                config = load_json(args.config)
                if config.get("name") != args.confirm:
                    raise HarnessError("invalid_argument", "--confirm 必须等于配置中的产品名称")
                exists = client.products.name_exists(args.confirm).get("exists")
                evidence["steps"].append({"step": "name_exists_before", "exists": exists})
                if exists:
                    evidence["state"] = "blocked"
                    evidence["diagnostic"] = "同名产品已存在；不自动复用或改名"
                else:
                    try:
                        result = client.products.create(config)
                    except KeyboardInterrupt:
                        evidence["pending_verification"] = {
                            "state": "unknown_create_result", "name": args.confirm,
                            "reason": "interrupted_during_create",
                        }
                        journal["events"].append({
                            "at": now(), "script": "product-lifecycle",
                            "action": "create_unknown", "name": args.confirm,
                            "reason": "interrupted",
                        })
                        save_journal(args.journal, journal)
                        raise
                    except Exception as exc:  # noqa: BLE001 - 创建结果未知也要留痕
                        evidence["pending_verification"] = {
                            "state": "unknown_create_result", "name": args.confirm,
                            "error": safe_error(exc),
                        }
                        journal["events"].append({
                            "at": now(), "script": "product-lifecycle",
                            "action": "create_unknown", "name": args.confirm,
                        })
                        save_journal(args.journal, journal)
                        raise
                    if not isinstance(result, dict):
                        evidence["pending_verification"] = {
                            "state": "unknown_create_result", "name": args.confirm,
                            "reason": "non_object_response",
                        }
                        journal["events"].append({
                            "at": now(), "script": "product-lifecycle",
                            "action": "create_unknown", "name": args.confirm,
                        })
                        save_journal(args.journal, journal)
                        raise HarnessError("invalid_response", "创建结果不是对象")
                    product_id = result.get("product_id")
                    if not product_id:
                        evidence["pending_verification"] = {
                            "state": "unknown_create_result", "name": args.confirm,
                            "reason": "missing_product_id",
                        }
                        journal["events"].append({
                            "at": now(), "script": "product-lifecycle",
                            "action": "create_unknown", "name": args.confirm,
                        })
                        save_journal(args.journal, journal)
                        raise HarnessError("invalid_response", "创建结果缺少 product_id")
                    evidence["written_id"] = product_id
                    evidence["product_id"] = product_id
                    evidence["writes"] += 1
                    journal["products"].append({
                        "id": product_id, "name": args.confirm,
                        "status": "pending_verification", "provenance": "create_response",
                    })
                    journal["events"].append({
                        "at": now(), "script": "product-lifecycle",
                        "action": "create_pending_verification", "product_id": product_id,
                    })
                    save_journal(args.journal, journal)
                    try:
                        product = client.products.get(product_id)
                    except Exception as exc:  # noqa: BLE001 - 已返回 ID 但读回失败
                        evidence["pending_verification"] = {
                            "state": "returned_id_readback_failed",
                            "product_id": product_id, "name": args.confirm,
                            "error": safe_error(exc),
                        }
                        raise
                    if product.get("name") != args.confirm or product.get("id") != product_id:
                        evidence["pending_verification"] = {
                            "state": "returned_id_readback_mismatch",
                            "product_id": product_id, "name": args.confirm,
                        }
                        raise HarnessError("invalid_response", "创建后读回名称或 ID 不一致")
                    for row in journal.get("products", []):
                        if row.get("id") == product_id:
                            row["name"] = product.get("name")
                            row["status"] = "verified"
                    journal["events"].append({
                        "at": now(), "script": "product-lifecycle",
                        "action": "create_verified", "product_id": product_id,
                    })
                    save_journal(args.journal, journal)
                    evidence["steps"].append({
                        "step": "create", "product_id": product_id,
                        "err_msgs": result.get("err_msgs"),
                        "config": project_product(product),
                    })
                    evidence["product_id"] = product_id
                    evidence["state"] = "passed"
            elif args.action == "update":
                owned_product(journal, args.product, args.confirm)
                before = client.products.get(args.product)
                if before.get("name") != args.confirm:
                    raise HarnessError("invalid_argument", "读回名称与 --confirm 不一致")
                data = load_json(args.data)
                result = client.products.update(args.product, data)
                evidence["writes"] += 1
                after = client.products.get(args.product)
                mismatch = {
                    key: {"before": before.get(key), "after": after.get(key), "requested": value}
                    for key, value in data.items() if after.get(key) != value
                }
                evidence["steps"].append({
                    "step": "update", "effect_count": result.get("effect_count"),
                    "requested": data, "before": {k: before.get(k) for k in data},
                    "after": {k: after.get(k) for k in data}, "mismatch": mismatch,
                })
                if (isinstance(data.get("name"), str)
                        and after.get("id") == args.product
                        and isinstance(after.get("name"), str)
                        and after.get("name") != before.get("name")):
                    for row in journal.get("products", []):
                        if row.get("id") == args.product:
                            row["name"] = after["name"]
                            row["status"] = "verified"
                    journal["events"].append({"at": now(), "script": "product-lifecycle",
                                              "action": "rename", "product_id": args.product,
                                              "name": after["name"]})
                    save_journal(args.journal, journal)
                evidence["state"] = "passed" if not mismatch else "failed"
                if mismatch:
                    evidence["diagnostic"] = "修改后读回与请求字段不一致"
            elif args.action == "delete":
                owned_product(journal, args.product, args.confirm)
                before = client.products.get(args.product)
                if before.get("name") != args.confirm:
                    raise HarnessError("invalid_argument", "读回名称与 --confirm 不一致")
                result = client.products.delete(args.product)
                evidence["writes"] += 1
                listed = client.products.list(fields=["id", "name"]).get("products") or []
                visible = [row for row in listed if str(row.get("id")) == args.product]
                evidence["steps"].append({
                    "step": "delete", "effect_count": result.get("effect_count"),
                    "before": {"id": before.get("id"), "name": before.get("name")},
                    "visible_after": visible,
                })
                evidence["state"] = "passed" if not visible else "failed"
                if visible:
                    evidence["diagnostic"] = "删除后产品仍出现在列表"
                journal["events"].append({"at": now(), "script": "product-lifecycle",
                                          "action": "delete", "product_id": args.product})
                save_journal(args.journal, journal)
            else:
                owned_product(journal, args.product, args.confirm)
                product = client.products.get(args.product)
                evidence["steps"].append({"step": "get", "config": project_product(product)})
                evidence["state"] = "passed" if product.get("name") == args.confirm else "failed"
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
                      "action": evidence["action"], "product_id": evidence.get("product_id"),
                      "output": str(args.output)}, ensure_ascii=False))
    return {"passed": 0, "blocked": 2}.get(evidence["state"], 1)


if __name__ == "__main__":
    sys.exit(main())
