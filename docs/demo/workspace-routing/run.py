"""确认 PAT 成员空间、默认首项和同令牌切换后的资源归属。"""

import argparse
import json
import os
from pathlib import Path

import rqamsh


def inspect_products(workspace_id=None):
    """读取当前分区可见产品并逐个核对其所属空间，不推断写权限。"""
    result = rqamsh.products.list(fields=["id", "workspace_id"])
    rows = result["products"]
    if result["total"] != len(rows):
        raise ValueError("可见产品总数与列表不一致")
    if workspace_id is not None and any(row.get("workspace_id") != workspace_id for row in rows):
        raise ValueError("返回产品不属于所选工作空间")
    return {"workspace_id": workspace_id, "visible_products": len(rows),
            "returned_workspace_ids": sorted({row.get("workspace_id") for row in rows})}


def main():
    """验证两个已知成员空间；不探测非成员空间，不保存个人身份。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--other-workspace-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("RQAMSH_TOKEN")
    if args.workspace_id == args.other_workspace_id:
        parser.error("两个目标必须是不同成员空间")
    evidence = {"state": "failed", "writes": 0, "steps": []}
    try:
        if not token:
            raise rqamsh.HarnessError("invalid_config", "缺少 RQAMSH_TOKEN")
        client = rqamsh.init(base_url=args.base_url, token=token, timeout=20, wait_timeout=60)
        members = rqamsh.workspaces.list()["data"]
        ids = [row["id"] for row in members]
        if not ids:
            raise ValueError("当前身份没有成员空间")
        if args.workspace_id not in ids or args.other_workspace_id not in ids:
            raise ValueError("目标未同时出现在当前成员列表，停止而不探测非成员空间")
        evidence["member_count"] = len(ids)
        automatic_member_first = []

        def observe_automatic_members(response, **kwargs):
            """记录实际自动发现所用响应的首项，而非上一次列表的顺序。"""
            if response.url.split("?", 1)[0].endswith("/api/user/v1/workspaces") and response.status_code == 200:
                data = response.json().get("data")
                if isinstance(data, list) and data:
                    automatic_member_first.append(data[0].get("id"))

        client.session.hooks["response"].append(observe_automatic_members)
        # 注入令牌不继承保存空间；自动首项不按名称、ID 或权益重新排序。
        try:
            default_result = inspect_products()
        except rqamsh.HarnessError as exc:
            if exc.status != 403:
                raise
            # 首项被拒绝不自动遍历成员；后续只验证用户明确给出的两个目标。
            default_result = {"status": 403, "code": exc.code, "automatic_fallback": False}
        if len(automatic_member_first) != 1 or client.workspace_id != automatic_member_first[0]:
            raise ValueError("自动空间不是实际发现响应的首项")
        default_result["workspace_id"] = client.workspace_id
        if any(space != client.workspace_id for space in default_result.get("returned_workspace_ids", [])):
            raise ValueError("自动首项返回产品的空间不符")
        evidence["steps"].append({"operation": "automatic_first", **default_result})
        for workspace in (args.workspace_id, args.other_workspace_id, args.workspace_id):
            selected = rqamsh.workspaces.use(workspace=workspace)
            if selected["id"] != workspace or client.workspace_id != workspace:
                raise ValueError("选中结果或当前路由不匹配")
            evidence["steps"].append({"operation": "select_and_read", **inspect_products(workspace)})
        # 显式空间优先级用新连接验证，不依赖上一次进程的默认选择。
        client = rqamsh.init(base_url=args.base_url, workspace_id=args.workspace_id,
                             token=token, timeout=20, wait_timeout=60)
        explicit_result = inspect_products(args.workspace_id)
        if client.workspace_id != args.workspace_id:
            raise ValueError("显式空间未生效")
        evidence["steps"].append({"operation": "explicit_space", **explicit_result})
        evidence["state"] = "passed"
        evidence["nonmember_access"] = "未探测；须由管理员建立成员关系与权益，改请求头不增加授权"
    except (KeyboardInterrupt, SystemExit) as exc:
        evidence["diagnostic"] = {"type": type(exc).__name__, "code": "interrupted"}
    except Exception as exc:
        evidence["diagnostic"] = {"type": type(exc).__name__, "code": getattr(exc, "code", None),
                                  "status": getattr(exc, "status", None)}
    finally:
        rqamsh.close()
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, ensure_ascii=False, indent=2)
    print(json.dumps(evidence, ensure_ascii=False))
    return 0 if evidence["state"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
