"""执行真实 CLI 子进程，验证输入和错误输出契约。"""

import json
import os
from pathlib import Path
import subprocess
import sys

from test_client import catalog_routes, service


def test_cli_docs_export_is_offline_and_preserves_skill(tmp_path):
    """离线发现并同步当前包文档；保留技能正文，相同修订无需重装。"""
    skill = tmp_path / "rqamsh"
    skill.mkdir()
    entry = skill / "SKILL.md"
    entry.write_text("existing skill", encoding="utf-8")
    command = [sys.executable, "-m", "rqamsh", "--token", "@missing", "docs"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    original = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env)
    assert original.returncode == 0, original.stderr
    source = Path(json.loads(original.stdout)["path"])
    assert (source / "index.md").is_file()
    sync = [*command, "--skill-dir", str(skill)]
    exported = subprocess.run(sync, capture_output=True, text=True, encoding="utf-8", env=env)
    assert exported.returncode == 0, exported.stderr
    result = json.loads(exported.stdout)
    target = Path(result["path"])
    assert target.is_relative_to(skill)
    example = "demo/valuation-report-reconciliation/inputs/valuation-2026-09-25.xlsx"
    assert (target / example).read_bytes() == (source / example).read_bytes()
    again = subprocess.run(sync, capture_output=True, text=True, encoding="utf-8", env=env)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout) == result
    assert entry.read_text(encoding="utf-8") == "existing skill"

    altered = target / "index.md"
    altered.write_text("unexpected local edit", encoding="utf-8")
    conflict = subprocess.run(sync, capture_output=True, text=True, encoding="utf-8", env=env)
    assert conflict.returncode != 0
    assert conflict.stdout == ""
    assert json.loads(conflict.stderr)["error"] == "docs_cache_conflict"
    assert altered.read_text(encoding="utf-8") == "unexpected local edit"


def test_cli_failure_is_json_on_stderr():
    """未知参数不得污染stdout或打印traceback。"""
    result = subprocess.run([sys.executable, "-m", "rqamsh", "products", "get", "--unknown"], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"] == "invalid_arguments"


def test_cli_json_input_partial_failure_preserves_successes(service, tmp_path):
    """真实CLI从UTF-8文件导入流水，部分失败返回可恢复结果及非零退出。"""
    client, state = service
    product = {"id": "p1", "name": "量化一号", "user_id": 1}
    state["catalog"] = catalog_routes([product])
    state["responses"] = [
        (200, [{"trade_id": "saved"}, {"err_msg": "不支持的资产"}]),
    ]
    source = tmp_path / "流水.json"
    source.write_text('[{"foreign_id": "one"}, {"foreign_id": "two"}]', encoding="utf-8")
    result = subprocess.run([
        sys.executable, "-m", "rqamsh", "--base-url", client.base_url, "--token", "test",
        "--workspace-id", client.workspace_id, "trades", "upload", "--resource", "量化一号",
        "--input", str(source),
    ], capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode != 0
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["error"] == "partial_failure"
    assert error["details"]["results"][0]["trade_id"] == "saved"
    assert [request[0] for request in state["requests"]].count("POST") == 1


def test_cli_parses_json_array_for_union_string_parameters(service):
    """通配参数既可传逗号串也可传 JSON 数组，数组必须解析而不是按字符拼接。"""
    client, state = service
    product = {"id": "p1", "name": "量化一号", "user_id": 1}
    state["catalog"] = catalog_routes([product])
    state["responses"] = [
        (200, {"weights": []}),
    ]
    result = subprocess.run([
        sys.executable, "-m", "rqamsh", "--base-url", client.base_url, "--token", "test",
        "--workspace-id", client.workspace_id, "analytics", "asset-weight",
        "--resource", "量化一号", "--start-date", "2026-01-01", "--end-date", "2026-02-01",
        "--classifiers", '["stock","fund"]',
    ], capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0, result.stderr
    assert "classifiers=stock%2Cfund" in state["requests"][-1][1]
