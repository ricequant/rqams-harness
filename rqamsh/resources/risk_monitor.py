"""风险预警条款、实时预警与行情看板类监控数据。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _selector, _text


_DASHBOARD_FIELDS = frozenset({"minbar", "daily"})


def _dashboard_params(fields: str, start_date: str | None, end_date: str | None) -> dict[str, Any]:
    """校验看板类接口的公共参数：分时不看日期，日度历史必须显式给区间。"""
    chosen = _text(fields, "fields")
    parts = [part.strip() for part in chosen.split(",") if part.strip()]
    if not parts or set(parts) - _DASHBOARD_FIELDS:
        raise HarnessError("invalid_argument", "fields 只能取 minbar、daily 的组合")
    if "daily" in parts and (start_date is None or end_date is None):
        raise HarnessError("invalid_argument", "fields 含 daily 时必须同时提供 start_date 与 end_date")
    return {"fields": ",".join(parts), "start_date": start_date, "end_date": end_date}


class RiskMonitor(_Resource):
    """维护风险预警条款并读取实时预警与看板类监控数据。

    条款与预警结果由服务端按当前用户和回测空间隔离：只返回本用户在本空间
    创建或可见的内容，Harness 不再二次过滤，也不补全服务端未返回的产品名。
    """

    def clauses(
        self, *, product_ids: list[str] | None = None, group_ids: list[str] | None = None,
        start_date: str | None = None, end_date: str | None = None, levels: list[int] | None = None,
    ) -> Any:
        """查询本人创建的风险预警条款。

        Args:
            product_ids: 可选产品 ID 或名称数组，按产品过滤条款；数组会解析为 ID。
            group_ids: 可选产品组 ID 或名称数组，按产品组过滤条款；数组会解析为 ID。
            start_date: 可选创建起始日期 YYYY-MM-DD。
            end_date: 可选创建截止日期 YYYY-MM-DD。
            levels: 可选预警等级数组；线上参数名为 level，序列化为逗号串。
        Returns:
            条款数组，服务端已在条目内附带触发状态；不含其他用户创建的条款。
        """
        products = self._ids(product_ids, "product_ids", {"product"}) if product_ids is not None else None
        groups = self._ids(group_ids, "group_ids", {"product_group"}) if group_ids is not None else None
        return self._client.call("GET", "risk_clauses", params={
            "product_ids": products, "group_ids": groups,
            "start_date": start_date, "end_date": end_date,
            "level": levels,
        })

    def create_clauses(self, clauses: list[dict[str, Any]]) -> Any:
        """批量创建风险预警条款。

        Args:
            clauses: 非空条款数组；每项必含 level、indicator_type、indicator、
                crontab_expression，并在 target_ids 中给出 products 或 product_groups；
                非 st、非违规公告的指标还需 operation 与 value；level 为 3 及以上时
                必须提供 warning_urls。服务端逐项校验，任一项非法时整批失败。
        Returns:
            服务端原始响应，含 inserted_count；条款归属当前用户与回测空间。
        """
        _nonempty(clauses, "clauses")
        for clause in clauses:
            if not isinstance(clause, dict):
                raise HarnessError("invalid_argument", "clauses 的元素必须为对象")
        return self._client.call("POST", "risk_clauses", json=clauses)

    def update_clause(self, clause_id: str, data: dict[str, Any]) -> Any:
        """更新单条风险预警条款。

        Args:
            clause_id: 条款 ID。
            data: 非空部分字段对象，与服务端条款定义一致；服务端会把字段合并到现有条款后
                整体校验，因此不能提交自相矛盾的局部字段组合。
        Returns:
            服务端原始响应，含 effect_count；条款不存在时服务端返回 404。
        """
        if not isinstance(data, dict) or not data:
            raise HarnessError("invalid_argument", "data 必须为非空条款字段对象")
        return self._client.call("PATCH", f"risk_clauses/{_text(clause_id, 'clause_id')}", json=data)

    def delete_clauses(self, clause_ids: list[str]) -> Any:
        """批量删除风险预警条款。

        Args:
            clause_ids: 非空条款 ID 数组。
        Returns:
            服务端原始响应，含 deleted_count；不存在的 ID 不计入删除数。
        """
        _nonempty(clause_ids, "clause_ids")
        for clause_id in clause_ids:
            _text(clause_id, "clause_ids")
        return self._client.call("POST", "risk_clauses:batch_delete", json=clause_ids)

    def realtime_warnings(self) -> Any:
        """读取当前用户与回测空间的实时风险预警。

        Returns:
            服务端原始预警结果；只包含预警消息、条款 ID 与资源 ID，不含产品名称，
            Harness 不臆造名称也不按目录过滤。
        """
        return self._client.call("GET", "risk_clauses:get_realtime_risk_warnings")

    def illegal_announcements(self) -> Any:
        """读取违规（负面）公告标的列表。

        Returns:
            服务端任务终态结果；首次调用触发服务端任务并原地重复查询直到完成，
            不返回 task_id。失败抛 task_failed，等待超时抛 wait_timeout。
        """
        return self._client.call("GET", "illegal_announcement", legacy_task=True)

    def vix(
        self, index_ids: str | list[str], *, fields: str = "minbar,daily",
        start_date: str | None = None, end_date: str | None = None,
    ) -> Any:
        """读取 VIX 等波动率指数数据。

        Args:
            index_ids: 必填指数代码，逗号串或字符串数组。
            fields: 数据形态，minbar（当日分时）与 daily（日度历史）的组合，默认 minbar,daily。
            start_date: 起始日期 YYYY-MM-DD；fields 含 daily 时必填。
            end_date: 截止日期 YYYY-MM-DD；fields 含 daily 时必填。
        Returns:
            服务端原始指数序列数据，按 fields 分键返回。
        """
        selector = _selector(index_ids, "index_ids")
        params = {"index_ids": selector, **_dashboard_params(fields, start_date, end_date)}
        return self._client.call("GET", "vix", params=params)

    def margin_balance(self, *, start_date: str, end_date: str) -> Any:
        """读取两融余额数据。

        Args:
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
        Returns:
            服务端原始两融余额数据。
        """
        return self._client.call(
            "GET", "margin_balance", params={"start_date": start_date, "end_date": end_date},
        )

    def etf_shares(self, etf_id: str, *, start_date: str, end_date: str) -> Any:
        """读取单只 ETF 的份额数据。

        Args:
            etf_id: 必填 ETF 代码。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
        Returns:
            服务端原始 ETF 份额数据。
        """
        return self._client.call("GET", "etf_shares", params={
            "etf_id": _text(etf_id, "etf_id"), "start_date": start_date, "end_date": end_date,
        })

    def etf_premium_rate(
        self, etf_ids: str | list[str], *, fields: str = "minbar,daily",
        start_date: str | None = None, end_date: str | None = None,
    ) -> Any:
        """读取 ETF 折溢价率数据。

        Args:
            etf_ids: 必填 ETF 代码，逗号串或字符串数组。
            fields: 数据形态，minbar（当日分时）与 daily（日度历史）的组合，默认 minbar,daily。
            start_date: 起始日期 YYYY-MM-DD；fields 含 daily 时必填。
            end_date: 截止日期 YYYY-MM-DD；fields 含 daily 时必填。
        Returns:
            服务端原始折溢价率数据，按 fields 分键返回。
        """
        selector = _selector(etf_ids, "etf_ids")
        params = {"etf_ids": selector, **_dashboard_params(fields, start_date, end_date)}
        return self._client.call("GET", "etf_premium_rate", params=params)

    def goodwill_ratio(self, board_types: str | list[str], *, start_date: str, end_date: str) -> Any:
        """读取板块商誉占比数据。

        Args:
            board_types: 必填板块类型，逗号串或字符串数组。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
        Returns:
            服务端原始商誉占比数据。
        """
        return self._client.call("GET", "goodwill_ratio", params={
            "board_types": _selector(board_types, "board_types"),
            "start_date": start_date, "end_date": end_date,
        })

    def _ids(self, resources: list[str], name: str, allowed: set[str]) -> str:
        """把产品/产品组选择器解析为 ID 逗号串，复用同一个目录快照。"""
        _nonempty(resources, name)
        return ",".join(ref.id for ref in self._batch_refs(resources, allowed))
