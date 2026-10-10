"""产品份额事件：手工申购与赎回的录入、修改与删除。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _segment


_UNIT_EVENT_TYPES = {"subscription", "redemption"}


def _to_batch_doc(data: dict[str, Any]) -> dict[str, Any]:
    """把 unit_event_type 与 units 折算为服务端批量接口接受的申购/赎回字段。

    服务端批量插入路由只接受 subscription_units/redemption_units，不接受 units 与 unit_event_type；
    本折算镜像服务端单条路由的同一规则，其余字段（date、product_share 等）原样透传。
    """
    if not isinstance(data, dict):
        raise HarnessError("invalid_argument", "data 数组元素必须为份额事件对象")
    if "unit_event_type" not in data or "units" not in data:
        raise HarnessError("invalid_argument", "每个份额事件必须提供 unit_event_type 与 units")
    event_type = data["unit_event_type"]
    if event_type not in _UNIT_EVENT_TYPES:
        raise HarnessError("invalid_argument", "unit_event_type 只能为 subscription 或 redemption")
    doc = {key: value for key, value in data.items() if key not in {"unit_event_type", "units", "id"}}
    doc["subscription_units"] = data["units"] if event_type == "subscription" else None
    doc["redemption_units"] = data["units"] if event_type == "redemption" else None
    return doc


class UnitEvents(_Resource):
    """份额事件：手工录入的申购与赎回；自动生成事件只读。"""

    def list(self, resource: str, *, start_date: str | None = None, end_date: str | None = None) -> Any:
        """列出产品份额事件与逐日份额变动。

        Args:
            resource: 产品唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略不设下界。
            end_date: YYYY-MM-DD；省略不设上界。
        Returns:
            服务端原始对象，含 daily_units（手工项 source 为 manual，其他来源折叠为 auto）与
            unit_changes（逐日申购、赎回份额与当日 units）；自动事件不可修改或删除。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/unit_events",
            params={"start_date": start_date, "end_date": end_date},
        )

    def create(self, resource: str, data: dict[str, Any] | list[dict[str, Any]]) -> Any:
        """新增一个或多个手工份额事件，统一走服务端批量插入。

        Args:
            resource: 产品唯一 ID 或名称；估值报告数据源产品不支持录入份额。
            data: 单个事件对象或其数组；每项必含 unit_event_type（subscription 或 redemption）、date、
                units，可带 product_share。客户端把 units 折算为 subscription_units/redemption_units。
        Returns:
            服务端原始结果：有合法事件时含 effect_count，存在解析失败时含 err_msg（逐项说明第几个
            事件为何失败）。err_msg 非空时抛部分失败异常；批量接口不返回新记录 ID。
        """
        if isinstance(data, dict):
            items = [data]
        else:
            items = data
        _nonempty(items, "data")
        docs = [_to_batch_doc(item) for item in items]
        result = self._client.call(
            "POST", self._path(resource, {"product"}) + "/unit_events:batch_insert", json=docs,
        )
        self._client.partial_failure(result)
        return result

    def update(self, resource: str, unit_event_id: str, data: dict[str, Any]) -> Any:
        """修改一个手工份额事件的份额字段。

        Args:
            resource: 产品唯一 ID 或名称。
            unit_event_id: list 返回的手工事件 ID；自动事件 ID 会得到 404。
            data: 必须同时提供 subscription_units 与 redemption_units（其中一个为 null），
                可选 product_share；未提供的字段沿用原事件，日期与其他字段不因本次调用变化。
        Returns:
            服务端原始 effect_count（实际修改条数）。
        """
        if not isinstance(data, dict) or not {"subscription_units", "redemption_units"} <= set(data):
            raise HarnessError(
                "invalid_argument",
                "update 必须同时提供 subscription_units 与 redemption_units（其中一个可为 null）",
            )
        path = self._path(resource, {"product"}) + f"/unit_events/{_segment(unit_event_id)}"
        return self._client.call("PUT", path, json=data)

    def delete(self, resource: str, unit_event_ids: list[str]) -> Any:
        """按事件 ID 批量删除手工份额事件并触发必要重算。

        Args:
            resource: 产品唯一 ID 或名称。
            unit_event_ids: 非空事件 ID 数组；自动事件 ID 不会命中，返回 effect_count 为 0。
        Returns:
            服务端原始 effect_count；删除不可撤销。
        """
        _nonempty(unit_event_ids, "unit_event_ids")
        return self._client.call(
            "POST", self._path(resource, {"product"}) + "/unit_events:batch_delete",
            json=unit_event_ids,
        )
