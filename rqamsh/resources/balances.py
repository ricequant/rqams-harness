"""产品与产品组的单日头寸报表及历史时序。"""

from __future__ import annotations

from datetime import date as Date, datetime, timedelta, timezone
from typing import Any

from rqamsh.errors import HarnessError
from ._base import _Resource, _nonempty, _text


def _flat_position(classifier: str | None) -> bool:
    """未指定分类时平铺；显式分类必须是非空字符串。"""
    if classifier is None:
        return True
    if not isinstance(classifier, str) or not classifier.strip():
        raise HarnessError("invalid_argument", "classifier 必须为非空分类字符串，平铺时请省略")
    return False


# 批量实时概览与成员视图的诊断键，投影时原样保留。
_DIAGNOSTIC_KEYS = frozenset({"error_messages", "pending_valuation"})

# 这些字段直接存储在头寸报表中，不需要分类、穿透或额外指标计算。
_SUMMARY_FIELDS = frozenset({
    "date", "total_equity", "total_assets", "total_liabilities", "units",
    "unit_net_value", "acc_unit_net_value", "adjusted_net_value", "daily_pnl",
    "daily_returns", "acc_unit_dividend",
})


def _split_ids(refs) -> tuple[str, str]:
    """按资源类型拆分已解析引用，返回产品与产品组的 ID 逗号串。"""
    products = [ref.id for ref in refs if ref.type == "product"]
    groups = [ref.id for ref in refs if ref.type == "product_group"]
    return ",".join(products), ",".join(groups)


def _query_date(value: str | None) -> tuple[str, bool]:
    """按北京时间区分实时与历史；未来日期不能充当实时查询别名。"""
    today = datetime.now(timezone(timedelta(hours=8))).date()
    if value is None:
        return today.isoformat(), True
    try:
        target = Date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HarnessError("invalid_argument", "date 必须为 YYYY-MM-DD") from exc
    if target.isoformat() != value or target > today:
        raise HarnessError("invalid_argument", "date 必须为 YYYY-MM-DD，且不能晚于北京时间当天")
    return value, target == today


def _select_fields(result: Any, fields: list[str] | None, members: bool) -> Any:
    """统一顶层字段投影，保留任务包装、成员权重及不完整结果诊断。"""
    if fields is None:
        return result
    if not isinstance(result, dict):
        raise HarnessError("invalid_response", "头寸报表应返回 JSON 对象", details=result)
    if result.get("status") in {"SUCCESS", "success"} and isinstance(result.get("data"), dict):
        return result | {"data": _select_fields(result["data"], fields, members)}
    if members:
        # 成员缺失时不得回填权重：服务端可能返回不完整成员集合，权重会被误读。
        pending = result.get("pending_valuation") or []
        projected = {}
        for key, value in result.items():
            if key in _DIAGNOSTIC_KEYS:
                projected[key] = value
                continue
            member = _select_fields(value, fields, False)
            if "product_weight" in value and not pending:
                member["product_weight"] = value["product_weight"]
            projected[key] = member
        return projected
    return {field: result[field] for field in fields if field in result}


class Balances(_Resource):
    """统一查询产品或产品组的实时、历史头寸报表及报表时序。"""

    def get(
        self, resource_or_resources: str | list[str], *, date: str | None = None,
        fields: list[str] | None = None, classifier: str | None = None,
        show_futures_sterilisation: bool = True, benchmark_id: str | None = None,
        drilldown: bool = True, include_component_weight_view: bool = False,
    ) -> Any:
        """按日期及业务参数查询头寸；单资源与多资源共用一个参数，由类型区分。

        Args:
            resource_or_resources: 产品或产品组唯一 ID 或名称；传入数组时按批量实时
                概览查询多个资源，返回资源 ID 到概览的映射，并附带 pending_valuation
                与 error_messages。批量形态不支持 date、classifier、benchmark_id、
                drilldown=False、关闭期货冲销项或成员权重视图，传入即报错而非忽略。
            date: YYYY-MM-DD；省略或北京时间当天取实时，过去日期取历史，未来拒绝。
            fields: 非空顶层返回字段列表；省略返回完整报表及持仓，不接受嵌套路径。
            classifier: 省略时持仓平铺；非空分类口径返回含 children 的分类树。
            show_futures_sterilisation: 展示期货冲销项；False 不支持同时不穿透、
                自定义实时基准或成员视图，因为底层无对应路由。
            benchmark_id: 统一使用基准纯 ID；省略使用产品或组的基准。
                历史自定义基准仅支持顶层收益字段，不支持同时返回持仓。
            drilldown: 是否穿透，默认 True；历史查询不支持 False。
            include_component_weight_view: 实时产品组成员视图，保留成员 ID、权重及错误；
                存在 pending_valuation 时不返回成员权重。
        Returns:
            完整报表或所选顶层字段；成员视图与批量查询为 ID 到报表的映射。
            保留服务端返回的业务日期、null、缺字段与任务包装，不把缺失补成零。
            实时归属日由服务端监控周期决定，夜盘不一定等于请求当天。
            实时分支即实时头寸明细口径：省略日期且 show_futures_sterilisation=False 时
            服务端直接读取实时快照，返回完整截面（含 share_values 与应付份额子持仓），
            是服务端前端持仓视图的超集，未做展示层裁剪。
            批量实时查询可能触发服务端对估值未就绪产品的补算，属服务端既有副作用。
        """
        if not isinstance(resource_or_resources, str):
            return self._batch_snapshot(
                resource_or_resources, fields=fields, date=date, classifier=classifier,
                show_futures_sterilisation=show_futures_sterilisation, benchmark_id=benchmark_id,
                drilldown=drilldown, include_component_weight_view=include_component_weight_view,
            )
        query_date, realtime = _query_date(date)
        flat_position = _flat_position(classifier)
        if fields is not None:
            _nonempty(fields, "fields")
            if any(not isinstance(field, str) or not field.isidentifier() for field in fields):
                raise HarnessError("invalid_argument", "fields 仅接受顶层字段名；持仓使用 positions，不使用 positions.quantity")
        if benchmark_id is not None and (
            not isinstance(benchmark_id, str) or not benchmark_id.strip() or "," in benchmark_id
        ):
            raise HarnessError("invalid_argument", "benchmark_id 必须为非空基准纯 ID，不包含类型前缀")
        if not realtime and (not drilldown or include_component_weight_view):
            raise HarnessError("invalid_argument", "历史查询不支持 drilldown=False 或成员权重视图")
        if not realtime and benchmark_id is not None and (
            fields is None or "positions" in fields or "daily_pnls" in fields
        ):
            raise HarnessError("invalid_argument", "历史自定义基准仅支持顶层收益字段查询，不能同时返回持仓")
        if realtime and not show_futures_sterilisation and (
            not drilldown or benchmark_id is not None or include_component_weight_view
        ):
            raise HarnessError("invalid_argument", "不展示期货冲销项时，实时查询不支持不穿透、自定义基准或成员视图")

        allowed = {"product_group"} if include_component_weight_view else {"product", "product_group"}
        ref = self._client.resolve(resource_or_resources, allowed)
        # 夜盘可能归属未来交易日，摘要端点传今天会误选历史；未知周期也不推断。
        use_summary = (
            ref.type == "product" and fields is not None and set(fields) <= _SUMMARY_FIELDS
            and classifier is None and drilldown and show_futures_sterilisation
            and benchmark_id is None
            and (not realtime or ref.data.get("realtime_period_type") == "daytime")
        )
        # 部分服务端会把未结算的历史日期回退为实时，保留日期用于核对后再投影。
        query_fields = fields
        if not realtime and fields is not None and "date" not in fields:
            query_fields = [*fields, "date"]
        # 两个完整查询端点仅由 excess_returns 触发基准收益计算。
        if query_fields is not None and "benchmark_returns" in query_fields and "excess_returns" not in query_fields:
            query_fields = [*query_fields, "excess_returns"]
        if use_summary:
            endpoint = "balance_summary"
            params = {"date": query_date, "fields": query_fields}
        elif realtime and show_futures_sterilisation:
            endpoint = "asset_snapshot_summary"
            params = {
                "fields": query_fields, "classifier": classifier, "flat_position": flat_position,
                "drilldown": drilldown, "include_component_weight_view": include_component_weight_view,
                # 该服务端端点只读取逗号后的 ID；前缀不参与基准类型解析。
                "benchmark": f",{benchmark_id}" if benchmark_id is not None else None,
            }
        else:
            endpoint = "balance"
            params = {
                "date": None if realtime else query_date, "fields": query_fields,
                "classifier": classifier, "flat_position": flat_position,
                "show_futures_sterilisation": show_futures_sterilisation, "benchmark_id": benchmark_id,
            }
        result = self._client.call("GET", f"{ref.path}/{endpoint}", params=params)
        if not realtime and isinstance(result, dict):
            document = result.get("data") if result.get("status") in {"SUCCESS", "success"} else result
            actual_date = document.get("date") if isinstance(document, dict) else None
            if actual_date is not None and actual_date != query_date:
                raise HarnessError(
                    "historical_date_mismatch", "服务端未返回指定历史日头寸，不能用实时或其他日期结果替代",
                    details={"requested_date": query_date, "actual_date": actual_date, "response": result},
                )
        if include_component_weight_view and isinstance(result, dict):
            self._mark_pending(result, ref.data.get("products") or [])
        return _select_fields(result, fields, include_component_weight_view)

    def series(
        self, resource: str, start_date: str | None = None, end_date: str | None = None,
        *, position_fields: list[str] | None = None, benchmark_id: str | None = None,
    ) -> Any:
        """查询产品或产品组余额时序；历史与盘中序列由是否给出截止日期区分。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD；盘中序列不接受该参数。
            end_date: 截止日期 YYYY-MM-DD；省略时读取盘中实时序列，此时 start_date 与
                position_fields 必须省略，benchmark_id 仅盘中序列可用。
            position_fields: 额外头寸字段名，无需 positions. 前缀；仅历史序列支持。
            benchmark_id: 盘中序列使用的基准纯 ID；省略时服务端使用 000300.XSHG。
        Returns:
            服务端原始余额或资产序列数组；盘中序列未就绪时由服务端返回业务错误。
        """
        # 校验先于资源解析：形态冲突不应触发目录请求。
        if end_date is None:
            if start_date is not None or position_fields is not None:
                raise HarnessError("invalid_argument", "盘中序列不接受 start_date 与 position_fields")
            path = self._path(resource, {"product", "product_group"})
            return self._client.call(
                "GET", path + "/realtime_asset_series", params={"benchmark_id": benchmark_id},
            )
        if start_date is None:
            raise HarnessError("invalid_argument", "历史序列必须同时提供 start_date 与 end_date")
        if benchmark_id is not None:
            raise HarnessError("invalid_argument", "benchmark_id 仅盘中序列可用")
        path = self._path(resource, {"product", "product_group"})
        return self._client.call(
            "GET", path + "/balance_series",
            params={"start_date": start_date, "end_date": end_date, "position_fields": position_fields},
        )

    def previous_summary(self, resource: str) -> Any:
        """读取产品或产品组上一交易日的头寸概览。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
        Returns:
            不含 positions 的概览，附带 benchmark_returns 与 excess_returns；
            交易日期由服务端按上一交易日决定，本操作不接受指定日期。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/balance:get_previous_summary",
        )

    def previous_summaries(self, product_or_group_ids: list[str]) -> Any:
        """批量读取多个产品或产品组上一交易日的头寸概览。

        Args:
            product_or_group_ids: 非空产品或产品组 ID 或名称数组。
        Returns:
            服务端原始对象，键为资源 ID；估值未就位的资源不出现，其他失败项收在
            error_messages 下，不阻塞其余资源。
        """
        refs = self._batch_refs(product_or_group_ids, {"product", "product_group"})
        return self._client.call("POST", "balance:get_previous_summary", json={
            "product_or_group_ids": [ref.id for ref in refs],
        })

    def export_file(self, resource: str, output: str, *, date: str | None = None) -> Any:
        """导出产品或产品组的持仓全景 Excel。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在。
            date: YYYY-MM-DD；省略取今日实时截面，不能晚于北京时间当天。
        Returns:
            客户端下载元数据；不依服务端文件名选择本地路径，产品已到期时服务端返回错误。
        """
        params = {} if date is None else {"date": _query_date(date)[0]}
        path = self._path(resource, {"product", "product_group"}) + "/balance_file"
        return self._client.call("GET", path, params=params, download=output)

    def export_snapshot(
        self, resource_or_resources: str | list[str], output: str, *, classifier: str | None = None,
        previous_trading_day: bool | None = None,
    ) -> Any:
        """导出实时监控工作簿；单资源与多资源共用一个参数，由类型区分。

        Args:
            resource_or_resources: 产品或产品组唯一 ID 或名称；数组表示多资源概览。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在；
                多资源导出在任务终态后才写入。
            classifier: 仅单资源可用，实时持仓分类口径；多资源端点不读取该参数，
                传入抛错而非忽略。
            previous_trading_day: 仅多资源可用，按上一交易日口径导出，省略为今日。
        Returns:
            客户端下载元数据；单资源同步返回，多资源等待服务端任务完成。
        """
        if isinstance(resource_or_resources, str):
            if previous_trading_day is not None:
                raise HarnessError("invalid_argument", "previous_trading_day 仅多资源导出可用")
            return self._client.call(
                "GET", self._path(resource_or_resources, {"product", "product_group"}) + "/asset_snapshot_file",
                params={"classifier": classifier}, download=output,
            )
        if classifier is not None:
            raise HarnessError("invalid_argument", "classifier 仅单资源导出可用")
        refs = self._batch_refs(resource_or_resources, {"product", "product_group"})
        products, groups = _split_ids(refs)
        return self._client.call("GET", "asset_snapshot_overview_file", params={
            "product_ids": products, "product_group_ids": groups,
            "previous_trading_day": previous_trading_day,
        }, legacy_task=True, download=output)

    def field_earliest_date(self, resources: list[str], *, field: str = "unit_net_value") -> Any:
        """查询多个产品上指定字段存在的最早日期。

        Args:
            resources: 非空产品 ID 或名称数组；该端点只接受产品，不含产品组。
            field: 字段名，默认 unit_net_value。
        Returns:
            服务端原始响应，含 earliest_date；多个产品合并计算同一最早日期。
        """
        target = _text(field, "field")
        refs = self._batch_refs(resources, {"product"})
        return self._client.call("POST", "products/balance:query_field_existed_earliest_date", json={
            "product_ids": [ref.id for ref in refs], "field": target,
        })

    def field_earliest_dates(self, resources: list[str], *, field: str = "unit_net_value") -> Any:
        """按产品查询指定字段存在的最早日期。

        Args:
            resources: 非空产品 ID 或名称数组；该端点只接受产品，不含产品组。
            field: 字段名，默认 unit_net_value。
        Returns:
            服务端原始数组，每项含 product_id 与 earliest_date；无数据时为 null。
        """
        target = _text(field, "field")
        refs = self._batch_refs(resources, {"product"})
        return self._client.call("POST", "products/balance:query_field_existed_earliest_dates_by_product", json={
            "product_ids": [ref.id for ref in refs], "field": target,
        })

    def _batch_snapshot(
        self, resources: list[str], *, fields: list[str] | None, date: str | None, classifier: str | None,
        show_futures_sterilisation: bool, benchmark_id: str | None, drilldown: bool,
        include_component_weight_view: bool,
    ) -> Any:
        """批量实时概览：服务端端点只接受资源标识与字段，其余参数不得静默丢弃。"""
        for value, name in ((date, "date"), (classifier, "classifier"), (benchmark_id, "benchmark_id")):
            if value is not None:
                raise HarnessError("invalid_argument", f"批量查询不支持 {name}")
        if not drilldown or include_component_weight_view or not show_futures_sterilisation:
            raise HarnessError("invalid_argument", "批量查询不支持不穿透、成员权重视图或关闭期货冲销项")
        if fields is not None:
            _nonempty(fields, "fields")
            if any(not isinstance(field, str) or not field.isidentifier() for field in fields):
                raise HarnessError("invalid_argument", "fields 仅接受顶层字段名；持仓使用 positions，不使用 positions.quantity")
        refs = self._batch_refs(resources, {"product", "product_group"})
        body = {"product_or_group_ids": [ref.id for ref in refs]}
        if fields is not None:
            body["fields"] = fields
        result = self._client.call("POST", "asset_snapshot_summary", json=body)
        if not isinstance(result, dict):
            raise HarnessError("invalid_response", "批量实时概览应返回 JSON 对象", details=result)
        self._mark_pending(result, [ref.id for ref in refs])
        return result

    def _mark_pending(self, result: dict, members: list) -> None:
        """显式标注未就绪项：缺失项可能已被服务端触发补算，但不回填任何值。

        产品组成员在产品组详情里是完整文档，这里统一取 ID；服务端响应本身不含
        `pending_valuation`，该键完全由 Harness 依据「请求的成员未出现在结果中」推导。
        """
        errors = result.get("error_messages") or {}
        result["error_messages"] = errors
        result["pending_valuation"] = [
            member_id for member_id in (self._member_id(member) for member in members)
            if member_id and member_id not in result and member_id not in errors
        ]

    @staticmethod
    def _member_id(member: Any) -> str | None:
        """把成员条目归一化为 ID：产品组详情里成员是完整文档。"""
        if isinstance(member, dict):
            identifier = member.get("id") or member.get("_id")
            return str(identifier) if identifier else None
        return str(member) if member else None
