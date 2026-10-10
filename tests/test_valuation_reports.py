"""估值报告块补齐：缺失日期查询。"""

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def _own_product():
    """返回当前用户对自身产品的目录响应序列。"""
    product = {"id": "p1", "name": "own", "user_id": 1}
    return [(200, {"products": [product]}), (200, product), (200, {"product_groups": []}), (200, [])]


def test_missing_dates_returns_server_list_unsorted(service):
    """缺表日期原样返回，不排序也不补全。"""
    client, state = service
    payload = ["2026-08-31", "2026-08-27"]
    state["responses"] = _own_product() + [(200, payload)]
    assert client.valuation_reports.missing_dates("own") == payload
    assert state["requests"][-1][1] == "/api/rqams/v2/products/p1/valuation_reports:missing_dates"
