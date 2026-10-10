"""验证依附资源归属和不可逆操作边界。"""

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def test_instruments_cross_workspace_batch_never_writes(service):
    """混入其他空间标的ID时不能先删除合法子集。"""
    client, state = service
    state["responses"] = [(200, {"customized_instruments": [{"id": "own", "workspace_id": client.workspace_id, "user_id": 1}], "total": 1})]
    with pytest.raises(HarnessError) as error:
        client.custom_instruments.delete(["own", "foreign"])
    assert error.value.code == "resource_not_found"
    assert all(request[0] == "GET" for request in state["requests"])


def test_report_from_another_product_cannot_be_downloaded(service, tmp_path):
    """仅有合法产品路径不足以证明报告归属，必须匹配该产品实际列表。"""
    client, state = service
    product = {"id": "p1", "name": "own", "user_id": 1}
    state["responses"] = [
        (200, {"products": [product]}), (200, product),
        (200, {"product_groups": []}), (200, []),
        (200, [{"valuation_report_id": "owned-report", "date": "2026-09-01"}]),
    ]
    output = tmp_path / "foreign.xlsx"
    with pytest.raises(HarnessError) as error:
        client.valuation_reports.download("own", "foreign-report", str(output))
    assert error.value.code == "resource_not_found"
    assert not output.exists()
    assert not any("/src_file" in request[1] for request in state["requests"])


def test_shared_product_write_is_not_gated_locally(service):
    """客户端不预判权限：他人产品的写入也直接发出，由服务端或网关裁定。"""
    client, state = service
    product = {"id": "p1", "name": "shared", "user_id": 2}
    state["responses"] = [
        (200, {"products": [product]}),
        (200, product), (200, {"product_groups": []}), (200, []),
        (200, {"effect_count": 1, "confirmation_ids": []}),
    ]
    assert client.trades.upload("shared", [{"foreign_id": "one"}]) == {"effect_count": 1, "confirmation_ids": []}
    assert state["requests"][-1][0] == "POST"


def test_blank_balance_classifier_never_queries_valuation(service):
    """空白分类不能静默退回默认分类，且应在请求估值前失败。"""
    client, state = service
    product = {"id": "p1", "name": "own", "user_id": 1}
    state["responses"] = [
        (200, {"products": [product]}), (200, product),
        (200, {"product_groups": []}), (200, []),
        (200, {"total_equity": 100, "positions": []}),
    ]
    with pytest.raises(HarnessError) as error:
        client.balances.get("own", classifier="  ")
    assert error.value.code == "invalid_argument"
    assert state["requests"] == []


def test_shared_product_realtime_read_uses_overview_endpoint(service):
    """他人产品的实时读取直接发出，走实时概览端点，分支只看参数不看权限。"""
    client, state = service
    product = {"id": "p1", "name": "shared", "user_id": 2}
    state["responses"] = [
        (200, {"products": [product]}),
        (200, product), (200, {"product_groups": []}), (200, []),
        (200, {"total_equity": 100, "positions": []}),
    ]
    assert client.balances.get("shared") == {"total_equity": 100, "positions": []}
    assert "/asset_snapshot_summary?" in state["requests"][-1][1]


def test_historical_read_uses_full_balance_endpoint(service):
    """历史完整报表走完整 balance 端点，不按调用方权限改判分支。"""
    client, state = service
    product = {"id": "p1", "name": "shared", "user_id": 2}
    state["responses"] = [
        (200, {"products": [product]}),
        (200, product), (200, {"product_groups": []}), (200, []),
        (200, {"total_equity": 80, "positions": []}),
    ]
    assert client.balances.get("shared", date="2024-01-02", fields=["positions", "total_equity"]) == {"total_equity": 80, "positions": []}
    assert "/balance?" in state["requests"][-1][1]
