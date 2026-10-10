"""资产单元持仓单补齐：源文件下载与工作空间级最新状态。"""

import pytest

from test_client import service
from rqamsh.errors import HarnessError


def _unit_catalog(units):
    """产品目录加资产单元列表，供资产单元级操作使用。"""
    product = {"id": "p1", "name": "own", "user_id": 1}
    return [
        (200, {"products": [product]}), (200, product), (200, {"product_groups": []}),
        (200, [{"product_id": "p1", "asset_units": units}]),
    ]


def test_download_verifies_record_then_writes_bytes(service, tmp_path):
    """下载前先确认持仓单属于该资产单元，再按独占文件落盘。"""
    client, state = service
    target = tmp_path / "statement.xlsx"
    state["responses"] = _unit_catalog([{"id": "u1", "symbol": "单元一"}]) + [
        (200, [{"positions_statement_id": "ps-1", "date": "2026-08-31", "file_name": "持仓单.xlsx"}]),
        (200, b"statement-bytes"),
    ]
    result = client.positions_statements.download("单元一", "ps-1", str(target))
    assert result == {"path": str(target.resolve()), "size": 15}
    assert target.read_bytes() == b"statement-bytes"
    assert state["requests"][-1][1].endswith("/asset_units/u1/positions_statement/ps-1/src_file")


def test_download_rejects_unknown_record_before_src_file(service, tmp_path):
    """不属于该资产单元的持仓单 ID 必须本地失败，不请求源文件。"""
    client, state = service
    state["responses"] = _unit_catalog([{"id": "u1", "symbol": "单元一"}]) + [(200, [])]
    with pytest.raises(HarnessError) as error:
        client.positions_statements.download("单元一", "ps-x", str(tmp_path / "x.xlsx"))
    assert error.value.code == "resource_not_found"
    assert all("src_file" not in item[1] for item in state["requests"])


def test_latest_filters_items_to_visible_asset_units(service):
    """工作空间级最新持仓单状态只保留目录可见资产单元，并丢弃空产品。"""
    client, state = service
    rows = [
        {"product_id": "p1", "product_name": "own", "positions_statement_items": [
            {"asset_unit_name": "单元一", "asset_unit_id": "u1", "update_time": "2026-08-31"},
            {"asset_unit_name": "隐藏单元", "asset_unit_id": "u9", "update_time": "未上传持仓单"},
        ]},
        {"product_id": "p9", "product_name": "其他", "positions_statement_items": [
            {"asset_unit_name": "他单元", "asset_unit_id": "u8", "update_time": "2026-01-01"},
        ]},
    ]
    state["responses"] = [(200, rows)] + _unit_catalog([{"id": "u1", "symbol": "单元一"}])
    assert client.positions_statements.latest() == [{
        "product_id": "p1", "product_name": "own", "positions_statement_items": [
            {"asset_unit_name": "单元一", "asset_unit_id": "u1", "update_time": "2026-08-31"},
        ],
    }]
    assert any(item[1] == "/api/rqams/v2/products/asset_units/positions_statement:get_latest" for item in state["requests"])
