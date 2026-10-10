"""对账状态与差异、人工标记，以及估值表覆盖的自动对账。"""

from __future__ import annotations

from datetime import date as Date
from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty


_DIFF_FIELDS = ("positions", "prices", "payable", "receivable", "cash", "shares_payable", "net_asset")


def _iso_date(value: str) -> str:
    """严格校验 YYYY-MM-DD；未来、封账与起始日限制由服务端按路由校验。"""
    if isinstance(value, bool) or not isinstance(value, str):
        raise HarnessError("invalid_argument", "date 必须为 YYYY-MM-DD")
    try:
        parsed = Date.fromisoformat(value)
    except ValueError as exc:
        raise HarnessError("invalid_argument", "date 必须为 YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise HarnessError("invalid_argument", "date 必须为 YYYY-MM-DD")
    return value


def _diff_fields(fields: list[str]) -> list[str]:
    """校验差异分组：非空、取值合法、去重并保持首现顺序。"""
    _nonempty(fields, "fields")
    ordered: list[str] = []
    for field in fields:
        if field not in _DIFF_FIELDS:
            raise HarnessError("invalid_argument", f"fields 仅接受：{'、'.join(_DIFF_FIELDS)}")
        if field not in ordered:
            ordered.append(field)
    return ordered


class Reconciliation(_Resource):
    """对账状态、差异与人工标记；自动对账写入或撤销估值表覆盖并提交重算。"""

    def list(self, resources: list[str], *, start_date: str, end_date: str) -> Any:
        """批量查询多个产品的区间对账状态。

        Args:
            resources: 非空产品 ID 或名称数组；一次目录快照解析，去重保持首现顺序。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
        Returns:
            原始数组，每个产品一项 {product_id, product_name, reconciliation_list}；
            日期集合为区间交易日历与已导入报告日期的并集。
        """
        start_date = _iso_date(start_date)
        end_date = _iso_date(end_date)
        refs = self._batch_refs(resources, {"product"})
        return self._client.call("POST", "products:batch_get_reconciliation_list", json={
            "start_date": start_date, "end_date": end_date,
            "product_ids": [ref.id for ref in refs],
        })

    def diff(self, resource: str, *, date: str, fields: list[str]) -> Any:
        """按差异分组比较产品某日的 AMS 结果与当日估值表。

        Args:
            resource: 产品唯一 ID 或名称。
            date: 对账日期 YYYY-MM-DD。
            fields: 非空差异分组数组；重复项去重并保持首现顺序。
        Returns:
            原始对象，按请求顺序给出各分组差异行；仅“交易流水 & 估值表”数据源且当日有估值表时可用，否则服务端报错。
        """
        date = _iso_date(date)
        fields = _diff_fields(fields)
        return self._client.call(
            "POST", self._path(resource, {"product"}) + ":get_reconciliation_diff",
            json={"date": date, "fields": fields},
        )

    def asset_unit_diff(self, resource: str, *, date: str) -> Any:
        """比较资产单元某日的 AMS 持仓与已导入持仓单。

        Args:
            resource: 资产单元唯一 ID 或名称。
            date: 对账日期 YYYY-MM-DD。
        Returns:
            差异行数组，含 asset_class、direction、order_book_id、symbol、quantity；拆分或送股场景可带 warnings，当日无 AMS 头寸时为空数组。
        """
        date = _iso_date(date)
        return self._client.call(
            "POST", self._path(resource, {"asset_unit"}) + ":get_reconciliation_diff",
            json={"date": date},
        )

    def positions_statement(self, resource: str, *, date: str) -> Any:
        """判断资产单元某日 AMS 持仓与已导入持仓单的数量是否一致。

        Args:
            resource: 资产单元唯一 ID 或名称。
            date: 对账日期 YYYY-MM-DD。
        Returns:
            {is_consistence: bool}；历史日期要求该资产单元已有头寸，未来日期被服务端拒绝。
        """
        date = _iso_date(date)
        return self._client.call(
            "GET", self._path(resource, {"asset_unit"}) + ":reconciliation_positions_statement",
            params={"date": date},
        )

    def mark(self, resource: str, *, date: str, done: bool | None = None, description: str | None = None) -> Any:
        """写入产品某日的人工对账标记。

        Args:
            resource: 产品唯一 ID 或名称。
            date: 对账日期 YYYY-MM-DD。
            done: 是否完成对账；省略时不写该字段。
            description: 备注；省略时不写该字段。
        Returns:
            原始 {effect_count}；只写对账标记，不触发重算。
        """
        date = _iso_date(date)
        if done is None and description is None:
            raise HarnessError("invalid_argument", "mark 至少需要 done 或 description")
        if done is not None and not isinstance(done, bool):
            raise HarnessError("invalid_argument", "done 必须为布尔值或省略")
        if description is not None and not isinstance(description, str):
            raise HarnessError("invalid_argument", "description 必须为字符串或省略")
        body: dict[str, Any] = {"date": date}
        if done is not None:
            body["done"] = done
        if description is not None:
            body["description"] = description
        return self._client.call("POST", self._path(resource, {"product"}) + ":reconciliation", json=body)

    def auto(self, resource: str, *, date: str) -> Any:
        """用当日估值表写入估值表覆盖并提交重算。

        Args:
            resource: 产品唯一 ID 或名称。
            date: 对账日期 YYYY-MM-DD。
        Returns:
            空响应；返回只表示覆盖已写入且计算已提交，不代表计算完成。
        """
        date = _iso_date(date)
        return self._client.call(
            "POST", self._path(resource, {"product"}) + ":auto_reconciliation", json={"date": date},
        )

    def undo_auto(self, resource: str, *, date: str) -> Any:
        """撤销产品某日的自动对账覆盖并提交重算。

        Args:
            resource: 产品唯一 ID 或名称。
            date: 对账日期 YYYY-MM-DD。
        Returns:
            原始 {effect_count}；0 只表示本次未删除到覆盖记录。
        """
        date = _iso_date(date)
        return self._client.call(
            "POST", self._path(resource, {"product"}) + ":undo_auto_reconciliation", json={"date": date},
        )