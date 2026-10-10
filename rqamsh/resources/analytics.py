"""净值与收益指标、持仓分析、业绩归因、组合对比与交易分析。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _selector, _text


# 持仓分析汇总文件的模板名，服务端按枚举直接校验。
_HOLDINGS_TEMPLATES = frozenset({"equity", "convertible", "futures", "option"})


class Analytics(_Resource):
    """读取持仓分析、业绩归因、组合对比与交易分析结果。

    计算全部由服务端任务完成：同步操作直接返回结果，带任务的操作首发后
    在同一路由轮询直至终态；失败抛 task_failed，等待超时抛 wait_timeout，
    响应原样返回且不把缺失补成零。净值与收益指标（indicators/series/win_rate/
    long_short_returns/download_series_file，原 indicators 块）沿用服务端口径，
    客户端不重算。
    """

    # 净值与收益指标（原 indicators 块，2026-09-21 合并）。

    def indicators(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None,
        benchmark: str | None = None, extra_indicators: list[str] | None = None,
    ) -> Any:
        """计算产品或产品组区间指标。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略使用资源起始日。
            end_date: YYYY-MM-DD；省略使用最近结算日，且受产品到期日限制。
            benchmark: 可选基准，格式为“类型,代码”。
            extra_indicators: 额外指标名称数组。
        Returns:
            原始收益风险指标 JSON；空组或无有效交易日会失败。
        """
        return self._client.call("GET", self._path(resource, {"product", "product_group"}) + "/indicators", params={
            "start_date": start_date, "end_date": end_date, "benchmark": benchmark,
            "extra_indicators": extra_indicators,
        })

    def series(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None,
        indicators: list[str] | None = None,
    ) -> Any:
        """读取产品或产品组指标时序。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略等于截止日期，并受资源起始日限制。
            end_date: YYYY-MM-DD；省略为今日，且受到期日限制。
            indicators: 指标名数组，省略使用服务端默认集合。
        Returns:
            服务端原始指标时序 JSON。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/indicators_series",
            params={"start_date": start_date, "end_date": end_date, "indicators": indicators},
        )

    def download_series_file(
        self, resource: str, output: str, *, start_date: str | None = None,
        end_date: str | None = None, indicators: list[str] | None = None,
    ) -> Any:
        """导出产品或产品组的指标时序 Excel，含日、周、月度胜率工作表。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在。
            start_date: YYYY-MM-DD；省略使用截止日期。
            end_date: YYYY-MM-DD；省略为今日，且受到期日限制。
            indicators: 指标名数组，省略使用服务端默认集合。
        Returns:
            客户端下载元数据；不依服务端文件名选择本地路径。
        """
        path = self._path(resource, {"product", "product_group"}) + "/indicators_series_file"
        return self._client.call("GET", path, params={
            "start_date": start_date, "end_date": end_date, "indicators": indicators,
        }, download=output)

    def win_rate(self, resource: str, *, start_date: str | None = None, end_date: str | None = None) -> Any:
        """读取产品或产品组区间胜率。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略使用资源起始日。
            end_date: YYYY-MM-DD；省略为今日，且受到期日限制。
        Returns:
            服务端原始胜率 JSON，口径见业务指标文档。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/win_rate",
            params={"start_date": start_date, "end_date": end_date},
        )

    def long_short_returns(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None,
    ) -> Any:
        """等待产品多空收益拆解任务；不支持产品组。

        Args:
            resource: 产品唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略使用产品起始日。
            end_date: YYYY-MM-DD；省略使用最近结算日。
        Returns:
            保留服务端任务终态 JSON；失败或超时抛 HarnessError。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/long_short_dismantle_returns",
            params={"start_date": start_date, "end_date": end_date}, legacy_task=True,
        )

    # A 组：持仓与暴露。

    def asset_weight(
        self, resource: str, *, start_date: str, end_date: str, classifiers: str | list[str],
    ) -> Any:
        """读取产品或产品组区间内指定分类的资产权重。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
            classifiers: 资产分类，逗号串或字符串数组；至少一个合法分类值。
        Returns:
            服务端原始权重结果；非法分类值由服务端拒绝。
        """
        # 校验先于资源解析：非法入参不应触发目录请求。
        selected = _selector(classifiers, "classifiers")
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/asset_weigh_view",
            params={"start_date": start_date, "end_date": end_date, "classifiers": selected},
        )

    def equity_holdings(
        self, resource: str, *, start_date: str, end_date: str, industry_classifier: str = "sws",
        split_long_short: bool = False, include_component_weight_view: bool = False,
    ) -> Any:
        """分析区间内股票持仓的行业分布与明细。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
            industry_classifier: 行业分类标准，默认 sws。
            split_long_short: 是否拆分多空持仓。
            include_component_weight_view: 仅产品组可用，返回成员产品权重视图。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        ref = self._client.resolve(resource, {"product", "product_group"})
        if include_component_weight_view and ref.type != "product_group":
            raise HarnessError("invalid_argument", "成员产品权重视图仅产品组可用")
        return self._client.call(
            "GET", ref.path + "/holdings_analysis/equity",
            params={
                "start_date": start_date, "end_date": end_date,
                "industry_classifier": industry_classifier, "split_long_short": split_long_short,
                "include_component_weight_view": include_component_weight_view,
            }, legacy_task=True,
        )

    def convertible_holdings(self, resource: str, *, start_date: str, end_date: str) -> Any:
        """分析区间内可转债持仓明细。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/holdings_analysis/convertible",
            params={"start_date": start_date, "end_date": end_date}, legacy_task=True,
        )

    def convertible_positions(self, resource: str, *, start_date: str, end_date: str) -> Any:
        """分析截止日可转债持仓及对应正股敞口。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD，用于确定区间起点。
            end_date: 截止日期 YYYY-MM-DD，服务端按该日读取持仓。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/holdings_analysis/convertible_positions",
            params={"start_date": start_date, "end_date": end_date}, legacy_task=True,
        )

    def futures_holdings(
        self, resource: str, *, start_date: str, end_date: str, average_total_turnover: int = 2,
        total_turnover_ranking: int = 3,
    ) -> Any:
        """分析区间内期货持仓、成交额排名与平均成交额。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD。
            average_total_turnover: 平均成交额阈值，单位十亿，服务端原样使用该量纲。
            total_turnover_ranking: 成交额排名名次。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/holdings_analysis/futures",
            params={
                "start_date": start_date, "end_date": end_date,
                "average_total_turnover": average_total_turnover,
                "total_turnover_ranking": total_turnover_ranking,
            }, legacy_task=True,
        )

    def option_holdings(self, resource: str, *, start_date: str, end_date: str) -> Any:
        """分析区间内期权持仓明细。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD。
            end_date: 截止日期 YYYY-MM-DD；服务端不接受晚于今天的日期。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/holdings_analysis/option",
            params={"start_date": start_date, "end_date": end_date}, legacy_task=True,
        )

    def holdings_summary_file(
        self, resource: str, output: str, template: str, *, start_date: str, end_date: str,
        benchmark: str | None = None, industry_classifier: str | None = None,
        split_long_short: bool | None = None,
    ) -> Any:
        """导出持仓分析汇总 Excel。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在；任务终态后才写入。
            template: 必填分析模板，取 equity、convertible、futures、option 之一；服务端不接受其他值。
            start_date: 必填起始日期 YYYY-MM-DD；服务端该端点无默认区间。
            end_date: 必填截止日期 YYYY-MM-DD，不能晚于今天。
            benchmark: 可选基准纯 ID，如 000300.XSHG；省略时服务端使用 000300.XSHG。
            industry_classifier: 行业分类标准。
            split_long_short: 是否拆分多空持仓。
        Returns:
            客户端下载元数据；服务端失败或超时抛 HarnessError。
        """
        if template not in _HOLDINGS_TEMPLATES:
            raise HarnessError("invalid_argument", "template 必须为 equity、convertible、futures 或 option")
        if benchmark is not None:
            _text(benchmark, "benchmark")
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/analysis_summary_file",
            params={
                "start_date": start_date, "end_date": end_date, "benchmark": benchmark,
                "industry_classifier": industry_classifier, "split_long_short": split_long_short,
                "template": template,
            }, legacy_task=True, download=output,
        )

    # B 组：业绩归因。

    def create_attribution(
        self, resource: str, *, start_date: str, end_date: str, benchmark: str, template: str | None = None,
        industry_standard: str | None = None, drilldown: bool = False,
        only_returns_decomposition: bool = False, need_market_value_weights: bool = False,
    ) -> Any:
        """提交产品或产品组业绩归因任务并返回归因 ID。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD，区间内必须含产品交易日历交易日。
            end_date: 截止日期 YYYY-MM-DD。
            benchmark: 基准，格式为“类型,ID”，如 index,000300.XSHG。
            template: 归因模板；与 only_returns_decomposition 至少提供一个。
            industry_standard: 行业分类标准。
            drilldown: 是否穿透到持仓层。
            only_returns_decomposition: 仅做收益拆解，不选模板。
            need_market_value_weights: 是否输出市值权重。
        Returns:
            服务端返回的任务标识对象；用 attribution 查询结果。
        """
        _text(benchmark, "benchmark")
        if "," not in benchmark:
            raise HarnessError("invalid_argument", "benchmark 必须为“类型,ID”格式")
        if template is None and not only_returns_decomposition:
            raise HarnessError("invalid_argument", "template 与 only_returns_decomposition 至少需要提供一个")
        body: dict[str, Any] = {
            "start_date": start_date, "end_date": end_date, "benchmark": benchmark,
            "drilldown": drilldown, "only_returns_decomposition": only_returns_decomposition,
            "need_market_value_weights": need_market_value_weights,
        }
        # 服务端对这些键声明了具体类型，null 会被schema拒绝；省略才走服务端默认值。
        if template is not None:
            body["template"] = template
        if industry_standard is not None:
            body["industry_standard"] = industry_standard
        return self._client.call(
            "POST", self._path(resource, {"product", "product_group"}) + "/performance_attributions",
            json=body,
        )

    def attribution(self, resource: str, attribution_id: str) -> Any:
        """查询业绩归因任务结果。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            attribution_id: create_attribution 返回的归因 ID。
        Returns:
            服务端任务终态结果；运行中会在同一路由轮询，失败或超时抛 HarnessError。
        """
        return self._client.call(
            "GET",
            self._path(resource, {"product", "product_group"})
            + f"/performance_attributions/{self._id(attribution_id)}",
            legacy_task=True,
        )

    def delete_attribution(self, resource: str, attribution_id: str) -> Any:
        """删除业绩归因任务及其结果，服务端同时终止仍在运行的计算。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            attribution_id: create_attribution 返回的归因 ID。
        Returns:
            服务端原始响应；结果不存在时服务端视为已删除。
        """
        return self._client.call(
            "DELETE",
            self._path(resource, {"product", "product_group"})
            + f"/performance_attributions/{self._id(attribution_id)}",
        )

    def export_attribution(self, resource: str, attribution_id: str, output: str) -> Any:
        """导出业绩归因结果 Excel。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            attribution_id: create_attribution 返回的归因 ID。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在；任务终态后才写入。
        Returns:
            客户端下载元数据；服务端失败或超时抛 HarnessError。
        """
        return self._client.call(
            "GET",
            self._path(resource, {"product", "product_group"})
            + f"/performance_attributions/{self._id(attribution_id)}/attribution_file",
            legacy_task=True, download=output,
        )

    def realtime_risk_attribution(
        self, resource: str, *, template: str = "equity/factor", benchmark: str | None = None,
        factor_industry_standard: str | None = None, brinson_industry_standard: str | None = None,
        drilldown: bool = False,
    ) -> Any:
        """读取产品实时风险归因。

        Args:
            resource: 产品唯一 ID 或名称。
            template: 归因模板，默认 equity/factor；服务端只接受 equity/factor 与 equity/factor_v2，Brinson 结果在同一次任务内一并计算。
            benchmark: 可选基准，格式为“类型,ID”；省略使用产品基准。
            factor_industry_standard: 因子模板的行业分类标准。
            brinson_industry_standard: Brinson 模板的行业分类标准。
            drilldown: 是否穿透到持仓层。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/realtime_risk_attributions",
            params={
                "template": template, "benchmark": benchmark,
                "factor_industry_standard": factor_industry_standard,
                "brinson_industry_standard": brinson_industry_standard, "drilldown": drilldown,
            }, legacy_task=True,
        )

    def realtime_factor_exposure(self, resource: str, *, template: str) -> Any:
        """读取产品实时因子暴露时序。

        Args:
            resource: 产品唯一 ID 或名称。
            template: 因子暴露模板名，取 equity/factor 或 equity/factor_v2；其他值由服务端拒绝。
        Returns:
            服务端原始因子暴露时序 JSON；持仓无股票或暴露度未就绪时返回区间信息而非数值。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/realtime_pa_factor_exposure_series",
            params={"template": template},
        )

    # C 组：组合对比（服务端 product_group_overview 族，仅封装 V2 端点；V1 系列未封装）。

    def group_indicators(self, resources: list[str], *, end_date: str, start_date: str | None = None) -> Any:
        """计算多个产品/产品组的产品组层区间业绩指标。

        Args:
            resources: 非空产品或产品组 ID 或名称数组，服务端按数组顺序返回。
            end_date: 截止日期 YYYY-MM-DD。
            start_date: 起始日期 YYYY-MM-DD；省略等于截止日期。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", "product_group_overview/indicators_v2",
            params=self._overview_params(resources, end_date, start_date), legacy_task=True,
        )

    def group_returns(
        self, resources: list[str], *, end_date: str, start_date: str | None = None, benchmark: str | None = None,
    ) -> Any:
        """计算多个产品/产品组的回报趋势。

        Args:
            resources: 非空产品或产品组 ID 或名称数组。
            end_date: 截止日期 YYYY-MM-DD。
            start_date: 起始日期 YYYY-MM-DD；省略等于截止日期。
            benchmark: 基准纯 ID；省略时服务端使用 000300.XSHG。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "POST", "product_group_overview/returns_v2",
            json=self._overview_params(resources, end_date, start_date, benchmark), legacy_task=True,
        )

    def group_capital_size(
        self, resources: list[str], *, end_date: str, start_date: str | None = None,
    ) -> Any:
        """计算多个产品/产品组的资产规模走势。

        Args:
            resources: 非空产品或产品组 ID 或名称数组。
            end_date: 截止日期 YYYY-MM-DD。
            start_date: 起始日期 YYYY-MM-DD；省略等于截止日期。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "POST", "product_group_overview/asset_capital_size_v2",
            json=self._overview_params(resources, end_date, start_date), legacy_task=True,
        )

    def group_allocation(self, resources: list[str], *, end_date: str) -> Any:
        """计算多个产品/产品组的资产配置权重。

        Args:
            resources: 非空产品或产品组 ID 或名称数组。
            end_date: 截止日期 YYYY-MM-DD；服务端固定按该日读取，不接受起始日期。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "POST", "product_group_overview/asset_allocation_v2",
            json=self._overview_params(resources, end_date, None), legacy_task=True,
        )

    def group_excess_correlation(
        self, resources: list[str], *, end_date: str, start_date: str | None = None, benchmark: str | None = None,
    ) -> Any:
        """计算多个产品/产品组的超额收益相关性矩阵。

        Args:
            resources: 非空产品或产品组 ID 或名称数组。
            end_date: 截止日期 YYYY-MM-DD。
            start_date: 起始日期 YYYY-MM-DD；省略等于截止日期。
            benchmark: 基准纯 ID；省略时服务端使用 000300.XSHG。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "POST", "product_group_overview/excess_returns_correlation_v2",
            json=self._overview_params(resources, end_date, start_date, benchmark), legacy_task=True,
        )

    def group_returns_correlation(
        self, resources: list[str], *, end_date: str, start_date: str | None = None,
    ) -> Any:
        """计算多个产品/产品组的收益相关性矩阵。

        Args:
            resources: 非空产品或产品组 ID 或名称数组。
            end_date: 截止日期 YYYY-MM-DD。
            start_date: 起始日期 YYYY-MM-DD；省略等于截止日期。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "POST", "product_group_overview/returns_correlation_v2",
            json=self._overview_params(resources, end_date, start_date), legacy_task=True,
        )

    def group_overview_file(
        self, resources: list[str], output: str, *, end_date: str, start_date: str | None = None,
        benchmark: str | None = None,
    ) -> Any:
        """导出多个产品/产品组的组合全景 Excel。

        Args:
            resources: 非空产品或产品组 ID 或名称数组。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在；任务终态后才写入。
            end_date: 截止日期 YYYY-MM-DD。
            start_date: 起始日期 YYYY-MM-DD；省略等于截止日期。
            benchmark: 基准纯 ID；省略时服务端使用 000300.XSHG。
        Returns:
            客户端下载元数据；服务端失败或超时抛 HarnessError。
        """
        return self._client.call(
            "POST", "product_group_overview_file_v2",
            json=self._overview_params(resources, end_date, start_date, benchmark),
            legacy_task=True, download=output,
        )

    def weekly_report(
        self, resources: list[str], *, end_date: str | None = None, start_date_mode: str | None = None,
    ) -> Any:
        """计算多个产品/产品组的周度报告数据。

        Args:
            resources: 非空产品或产品组 ID 或名称数组，服务端按策略类别分入市场中性
                与指数增强两组。
            end_date: 报告截止日 YYYY-MM-DD；省略由服务端按今日处理。
            start_date_mode: 起始日口径，`trading_start_date`（默认）取产品交易起始日，
                `start_date` 取产品成立日；省略由服务端按 `trading_start_date` 处理。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）；业务结果在 data 内，
            含 market_neutral、index_enhanced、start_date、end_date 与 index_returns。
        """
        if start_date_mode is not None and start_date_mode not in {"trading_start_date", "start_date"}:
            raise HarnessError("invalid_argument", "start_date_mode 必须为 trading_start_date 或 start_date")
        _nonempty(resources, "resources")
        params: dict[str, Any] = {
            "product_or_group_ids": ",".join(
                ref.id for ref in self._batch_refs(resources, {"product", "product_group"})
            ),
        }
        if end_date is not None:
            params["end_date"] = end_date
        if start_date_mode is not None:
            params["start_date_mode"] = start_date_mode
        return self._client.call(
            "GET", "product_group_overview/weekly_report", params=params, legacy_task=True,
        )

    def weekly_net_value_report(
        self, resource: str, output: str, *, start_date: str | None = None, end_date: str | None = None,
    ) -> Any:
        """导出产品或产品组的周度净值报告 Excel。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在；任务终态后才写入。
            start_date: 起始日期 YYYY-MM-DD；省略使用资源成立日。
            end_date: 截止日期 YYYY-MM-DD；省略为今日。
        Returns:
            客户端下载元数据；服务端失败或超时抛 HarnessError。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/weekly_net_value_report",
            params={"start_date": start_date, "end_date": end_date}, legacy_task=True, download=output,
        )

    # D 组：交易分析。

    def trading_analysis(self, resource: str, *, start_date: str | None = None, end_date: str | None = None) -> Any:
        """分析产品或产品组区间交易流水。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD；省略使用服务端默认区间。
            end_date: 截止日期 YYYY-MM-DD；省略使用服务端默认区间。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/trading_analysis_list",
            params={"start_date": start_date, "end_date": end_date}, legacy_task=True,
        )

    def single_trading_analysis(
        self, resource: str, order_book_id: str, *, start_date: str | None = None, end_date: str | None = None,
        asset_class: str | None = None, direction: str | None = None,
    ) -> Any:
        """分析产品或产品组指定标的的交易明细。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            order_book_id: 必填标的代码，如 600000.XSHG。
            start_date: 起始日期 YYYY-MM-DD；省略使用服务端默认区间。
            end_date: 截止日期 YYYY-MM-DD；省略使用服务端默认区间。
            asset_class: 资产类别过滤。
            direction: 买卖方向过滤。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        target = _text(order_book_id, "order_book_id")
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/single_trading_analysis",
            params={
                "order_book_id": target,
                "start_date": start_date, "end_date": end_date,
                "asset_class": asset_class, "direction": direction,
            }, legacy_task=True,
        )

    def algo_trading_performance(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None,
        algo_type: str | None = None, algo_name: str | None = None, algo_time_span: str | None = None,
        display_mode: str | None = None,
    ) -> Any:
        """分析产品或产品组的算法单绩效。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 起始日期 YYYY-MM-DD；省略使用服务端默认区间。
            end_date: 截止日期 YYYY-MM-DD；省略使用服务端默认区间。
            algo_type: 算法类型过滤。
            algo_name: 算法名称过滤。
            algo_time_span: 算法时间段过滤。
            display_mode: 展示模式。
        Returns:
            服务端任务终态结果（首发 202 与 task_id，随后轮询）。
        """
        return self._client.call(
            "GET", self._path(resource, {"product", "product_group"}) + "/algo_trading_performance",
            params={
                "start_date": start_date, "end_date": end_date, "algo_type": algo_type,
                "algo_name": algo_name, "algo_time_span": algo_time_span, "display_mode": display_mode,
            }, legacy_task=True,
        )

    # 内部辅助。

    def _overview_params(
        self, resources: list[str], end_date: str, start_date: str | None, benchmark: str | None = None,
    ) -> dict[str, Any]:
        """构建 v2 组合全景参数：资源解析为逗号串，日期与基准省略时交给服务端默认值。

        请求体不经查询串过滤，因此省略的参数必须整键缺席：服务端用 `dict.get(键, 默认值)`
        取默认值，键存在但为 null 会走到日期解析失败。
        """
        _nonempty(resources, "resources")
        params: dict[str, Any] = {
            "product_or_group_ids": ",".join(
                ref.id for ref in self._batch_refs(resources, {"product", "product_group"})
            ),
            "end_date": end_date,
        }
        if start_date is not None:
            params["start_date"] = start_date
        if benchmark is not None:
            params["benchmark"] = benchmark
        return params

    @staticmethod
    def _id(value: str) -> str:
        """校验归因 ID 为非空字符串，作为路径段拼接。"""
        return _text(value, "attribution_id")
