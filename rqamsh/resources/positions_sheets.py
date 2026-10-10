"""产品持仓表：产品级持仓截面的读取、按日期覆盖写入与删除。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty


class PositionsSheets(_Resource):
    """产品持仓表：按日期维护的产品级持仓截面，与资产单元持仓单不是同一对象。"""

    def get(self, resource: str, *, start_date: str | None = None, end_date: str | None = None) -> Any:
        """读取产品持仓表。

        Args:
            resource: 产品唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略不设下界。
            end_date: YYYY-MM-DD；省略不设上界。
        Returns:
            服务端原始持仓表数组，每项含 date、total_equity、units、unit_net_value 与 positions。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/positions_sheet",
            params={"start_date": start_date, "end_date": end_date},
        )

    def upsert(self, resource: str, data: dict[str, Any] | list[dict[str, Any]]) -> Any:
        """按日期新增或覆盖产品持仓表。

        Args:
            resource: 产品唯一 ID 或名称。
            data: 单份持仓表对象或其数组；每项必含 date、total_equity、units、unit_net_value、positions。
        Returns:
            服务端原始 inserted_expected_count、modified_expected_count、inserted_success_count、
            modified_success_count 与 error_messages；当日已有估值表覆盖的日期被跳过并进入
            error_messages，同时抛部分失败异常。成功写入的日期会另外生成来源为 PositionsSheet 的
            导入凭证，可用 confirmations.latest('PositionsSheet') 核对。
        """
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            raise HarnessError("invalid_argument", "data 必须为持仓表对象或其数组")
        _nonempty(items, "data")
        if not all(isinstance(item, dict) for item in items):
            raise HarnessError("invalid_argument", "data 数组元素必须为持仓表对象")
        for item in items:
            if "_id" in item or "id" in item:
                raise HarnessError(
                    "invalid_argument",
                    "持仓表不接受服务端记录键 id/_id；读取返回的 _id 只用于识别，请移除后重新提交",
                )
            positions = item.get("positions")
            if isinstance(positions, list) and any(
                isinstance(position, dict) and ("_id" in position or "id" in position) for position in positions
            ):
                raise HarnessError(
                    "invalid_argument",
                    "持仓明细不接受服务端记录键 id/_id；读取返回的 _id 只用于识别，请移除后重新提交",
                )
        result = self._client.call(
            "POST", self._path(resource, {"product"}) + "/positions_sheet", json=items,
        )
        self._client.partial_failure(result)
        return result

    def delete(self, resource: str, dates: list[str]) -> Any:
        """按日期批量删除产品持仓表并触发必要重算。

        Args:
            resource: 产品唯一 ID 或名称。
            dates: 非空 YYYY-MM-DD 数组，不是持仓表记录 ID。
        Returns:
            服务端原始 effect_count；删除不可撤销。
        """
        _nonempty(dates, "dates")
        return self._client.call(
            "POST", self._path(resource, {"product"}) + "/positions_sheet:batch_delete", json=dates,
        )
