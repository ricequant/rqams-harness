"""导入凭证块的来源枚举、可见性过滤与独占下载。"""

import pytest

from test_client import catalog_routes, service
from rqamsh.errors import HarnessError


def test_latest_sends_source_and_filters_visible_products(service):
    """工作空间级凭证查询必须带展示名与 filter，并过滤不可见产品。"""
    client, state = service
    rows = [{"product_id": "p1", "product_name": "own"}, {"product_id": "p2", "product_name": "hidden"}]
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, rows)]
    assert client.confirmations.latest("CustodianEvents") == [rows[0]]
    confirmations = [request[1] for request in state["requests"] if "/confirmations" in request[1]]
    assert confirmations[0].endswith("/confirmations?source=CustodianEvents&filter=latest")


def test_list_passes_unit_and_date_filters(service):
    """凭证列表必须透传资产单元与日期过滤。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, {"items": [], "total": 0})]
    client.confirmations.list("own", asset_unit_id="u1", start_date="2026-08-01", end_date="2026-08-31")
    assert state["requests"][-1][1].endswith("/confirmations?asset_unit_id=u1&start_date=2026-08-01&end_date=2026-08-31")


def test_get_passes_status_and_paging(service):
    """明细查询必须透传 status 与分页参数。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, {"items": [], "total": 0})]
    client.confirmations.get("own", "c1", status="failed", offset=10, limit=5)
    assert state["requests"][-1][1].endswith("/confirmations/c1?status=failed&offset=10&limit=5")


def test_download_refuses_existing_output_before_request(service, tmp_path):
    """已有目标文件时零请求失败，不消费一次性源文件且不改动原文件。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    target = tmp_path / "confirmation.xlsx"
    target.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        client.confirmations.download("own", "c1", str(target))
    assert target.read_bytes() == b"existing"
    assert not any("/src_file" in request[1] for request in state["requests"])


def test_download_writes_file_and_returns_metadata(service, tmp_path):
    """下载成功后返回路径与大小，且不向调用方返回二进制内容。"""
    client, state = service
    state["catalog"] = catalog_routes([{"id": "p1", "name": "own", "user_id": 1}])
    state["responses"] = [(200, b"source-file-bytes")]
    target = tmp_path / "confirmation.xlsx"
    result = client.confirmations.download("own", "c1", str(target))
    assert result["size"] == len(b"source-file-bytes") and target.read_bytes() == b"source-file-bytes"
    assert state["requests"][-1][1].endswith("/confirmations/c1/src_file")
