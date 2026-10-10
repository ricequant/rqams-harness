"""基准、行情、交易日历、标的检索与自定义基准。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _selector, _text


class MarketData(_Resource):
    """读取基准收益、实时行情、交易日历、标的检索，并维护自定义基准。

    自定义基准（复合指数与固定数值）属当前用户与回测空间，服务端不提供分页，
    返回结果原样透出；本块不缓存也不改写单位。
    """

    def benchmark_returns(
        self, *, benchmark_ids: str | list[str] | None = None, start_date: str | None = None,
        end_date: str | None = None, calendar_type: str = "natural", include_customized: bool = False,
    ) -> Any:
        """读取基准日收益与累计收益序列。

        Args:
            benchmark_ids: 可选基准代码，逗号串或字符串数组；省略时服务端返回全部内置基准。
            start_date: 起始日期 YYYY-MM-DD；省略时服务端使用 2020-01-01。
            end_date: 截止日期 YYYY-MM-DD；省略时服务端使用当日。
            calendar_type: 日历类型，默认 natural。
            include_customized: 是否在省略 benchmark_ids 时一并返回本空间的自定义基准。
                该参数仅在为 True 时下发：服务端按字符串真值判断，下发 false 会被当成真。
        Returns:
            基准序列数组；不存在的基准由服务端以 404 拒绝。
        """
        if benchmark_ids is not None:
            _selector(benchmark_ids, "benchmark_ids")
        return self._client.call("GET", "benchmarks_returns", params={
            "benchmark_ids": benchmark_ids, "start_date": start_date, "end_date": end_date,
            "calendar_type": calendar_type, "include_customized": True if include_customized else None,
        })

    def realtime_benchmark_returns(self, *, benchmark_id: str | None = None) -> Any:
        """读取基准实时分钟收益。

        Args:
            benchmark_id: 可选基准代码；省略时服务端返回全部内置基准的实时收益。
        Returns:
            服务端原始实时收益数据。
        """
        return self._client.call(
            "GET", "realtime_benchmark_returns",
            params={"benchmark_id": benchmark_id},
        )

    def benchmarks(self) -> Any:
        """列出当前空间可用的内置与自定义基准描述。

        Returns:
            服务端原始基准描述数组，含代码、名称与起始日期。
        """
        return self._client.call("GET", "benchmarks")

    def customized_benchmarks(self) -> Any:
        """列出当前用户与回测空间的自定义基准。

        Returns:
            服务端原始自定义基准数组，含名称、类型与权重或利率定义。
        """
        return self._client.call("GET", "customized_benchmarks")

    def create_customized_benchmark(
        self, name: str, type: str, *, remarks: str | None = None,
        weights: list[dict[str, Any]] | None = None, rates: float | None = None,
    ) -> Any:
        """创建自定义基准。

        Args:
            name: 基准名称，同一回测空间内不能重复。
            type: 基准类型，composite（复合指数）或 fixed_rates（固定数值）。
            remarks: 可选备注。
            weights: 复合指数的权重数组，元素为 date、weights 定义；composite 必填。
            rates: 固定数值年化收益率，可为 0；fixed_rates 必填且不能为负。
        Returns:
            服务端原始创建结果。
        """
        self._benchmark_payload(name, type, remarks, weights, rates)
        return self._client.call(
            "POST", "customized_benchmarks",
            json=self._payload(name, type, remarks, weights, rates),
        )

    def update_customized_benchmark(
        self, customized_benchmark_id: str, name: str, type: str, *, remarks: str | None = None,
        weights: list[dict[str, Any]] | None = None, rates: float | None = None,
    ) -> Any:
        """整体更新自定义基准定义。

        Args:
            customized_benchmark_id: 自定义基准 ID。
            name: 基准名称。
            type: 基准类型，composite 或 fixed_rates。
            remarks: 可选备注。
            weights: 复合指数权重数组；composite 必填。
            rates: 固定数值年化收益率；fixed_rates 必填且不能为负。
        Returns:
            服务端原始更新结果，含 modified；基准不属于当前空间时服务端拒绝。
        """
        self._benchmark_payload(name, type, remarks, weights, rates)
        return self._client.call(
            "PUT", f"customized_benchmarks/{_text(customized_benchmark_id, 'customized_benchmark_id')}",
            json=self._payload(name, type, remarks, weights, rates),
        )

    def delete_customized_benchmark(self, customized_benchmark_id: str) -> Any:
        """删除自定义基准。

        Args:
            customized_benchmark_id: 自定义基准 ID。
        Returns:
            服务端原始删除结果；基准不属于当前空间时服务端拒绝。
        """
        return self._client.call(
            "DELETE", f"customized_benchmarks/{_text(customized_benchmark_id, 'customized_benchmark_id')}",
        )

    def instruments(
        self, *, q: str | None = None, asset_class: str | None = None,
        instrument_type: str | None = None, limit: int = 20,
    ) -> Any:
        """检索标的。

        Args:
            q: 可选关键字，匹配代码或名称。
            asset_class: 可选资产类别过滤。
            instrument_type: 可选标的类型过滤。
            limit: 返回条数上限，默认 20。
        Returns:
            服务端原始标的数组。
        """
        return self._client.call("GET", "market_data/instruments", params={
            "q": q, "asset_class": asset_class, "instrument_type": instrument_type, "limit": limit,
        })

    def trading_dates(
        self, type: str, *, start_date: str | None = None, end_date: str | None = None, fmt: str = "date",
    ) -> Any:
        """查询交易所交易日历。

        Args:
            type: 日历类型，服务端当前仅接受 exchange。
            start_date: 起始日期 YYYY-MM-DD；省略时服务端使用 2010-01-01。
            end_date: 截止日期 YYYY-MM-DD；省略时服务端使用当日。
            fmt: 日期格式，date 或 timestamp。
        Returns:
            服务端原始交易日数组；服务端对未知类型或格式返回空数组。
        """
        if type != "exchange":
            raise HarnessError("invalid_argument", "type 目前仅支持 exchange")
        return self._client.call("GET", "market_data/trading_dates", params={
            "type": type, "start_date": start_date, "end_date": end_date, "fmt": fmt,
        })

    def realtime_quotes(self, order_book_ids: str | list[str]) -> Any:
        """读取标的实时快照行情。

        Args:
            order_book_ids: 必填标的代码，逗号串或字符串数组；服务端只接受逗号串，
                数组由客户端序列化，空串被拒绝。
        Returns:
            服务端原始行情数组，含最新价与涨跌幅；服务端不校验代码存在性，
            未知代码按缺省值返回。
        """
        return self._client.call(
            "GET", "market_data/realtime_quotes",
            params={"order_book_ids": _selector(order_book_ids, "order_book_ids")},
        )

    def index_futures_basis(self, *, dividend_adjusted: bool | None = None, fields: str | None = None) -> Any:
        """读取指数期货基差数据。

        Args:
            dividend_adjusted: 是否使用分红调整后的基差。
            fields: 可选字段列表，逗号串。
        Returns:
            服务端原始基差数据。
        """
        return self._client.call("GET", "index_futures_basis", params={
            "dividend_adjusted": dividend_adjusted, "fields": fields,
        })

    @staticmethod
    def _benchmark_payload(
        name: str, type: str, remarks: str | None, weights: list[dict[str, Any]] | None, rates: float | None,
    ) -> None:
        """按服务端定义校验基准类型与必填载荷，避免把必然失败的组合发给服务端。"""
        _text(name, "name")
        if type not in {"composite", "fixed_rates"}:
            raise HarnessError("invalid_argument", "type 必须为 composite 或 fixed_rates")
        if type == "composite":
            _nonempty(weights, "weights")
            for block in weights:
                if not isinstance(block, dict):
                    raise HarnessError("invalid_argument", "weights 的元素必须为对象")
                components = block.get("weights")
                if not isinstance(components, list) or not components:
                    raise HarnessError("invalid_argument", "每个权重块必须包含非空的 weights 数组")
                for component in components:
                    if not isinstance(component, dict):
                        raise HarnessError("invalid_argument", "成分必须为对象")
                    _text(component.get("order_book_id"), "order_book_id")
                    weight = component.get("weight")
                    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                        raise HarnessError("invalid_argument", "成分权重必须为数值")
        elif rates is None:
            raise HarnessError("invalid_argument", "fixed_rates 基准必须提供 rates")
        elif isinstance(rates, bool) or not isinstance(rates, (int, float)) or rates < 0:
            raise HarnessError("invalid_argument", "rates 必须为非负数值")
        if remarks is not None:
            _text(remarks, "remarks")

    @staticmethod
    def _payload(
        name: str, type: str, remarks: str | None, weights: list[dict[str, Any]] | None, rates: float | None,
    ) -> dict[str, Any]:
        """构建基准请求体，只包含所选类型需要的键。"""
        payload: dict[str, Any] = {"name": name, "type": type}
        if remarks is not None:
            payload["remarks"] = remarks
        if type == "composite":
            payload["weights"] = weights
        else:
            payload["rates"] = rates
        return payload
