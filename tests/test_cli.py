"""执行真实 CLI 子进程，验证输入和错误输出契约。"""

import json
import subprocess
import sys

from test_client import service


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
    state["responses"] = [
        (200, {"products": [product]}), (200, product),
        (200, {"product_groups": []}), (200, []),
        (200, [{"trade_id": "saved"}, {"err_msg": "不支持的资产"}]),
    ]
    source = tmp_path / "流水.json"
    source.write_text('[{"foreign_id": "one"}, {"foreign_id": "two"}]', encoding="utf-8")
    result = subprocess.run([
        sys.executable, "-m", "rqamsh", "--base-url", client.base_url, "--cookie", "sid=test",
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
    state["responses"] = [
        (200, {"products": [product]}), (200, product),
        (200, {"product_groups": []}), (200, []),
        (200, {"weights": []}),
    ]
    result = subprocess.run([
        sys.executable, "-m", "rqamsh", "--base-url", client.base_url, "--cookie", "sid=test",
        "--workspace-id", client.workspace_id, "analytics", "asset-weight",
        "--resource", "量化一号", "--start-date", "2026-01-01", "--end-date", "2026-02-01",
        "--classifiers", '["stock","fund"]',
    ], capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    assert result.returncode == 0, result.stderr
    assert "classifiers=stock%2Cfund" in state["requests"][-1][1]
