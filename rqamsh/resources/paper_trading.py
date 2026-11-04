"""模拟交易：按模板创建产品、上传信号并读取模板配置。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _segment, _text


_TEMPLATES = frozenset({"equity_long", "conventional"})
_ALGOS = frozenset({"open", "vwap", "twap"})
_STRATEGY_CATEGORIES = frozenset({
    "index_enhanced", "equity_market_neutral", "stock_long", "commodity_trading_advisor",
    "mixed", "long_short_stock", "stock_leverage_neutral", "stock_leverage_long_short", "unconventionality",
})
_UPLOAD_BATCH_SIZE = 50


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    """校验数值参数，拒绝布尔值和非有限值，并按需校验下界。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value in (float("inf"), float("-inf")):
        raise HarnessError("invalid_argument", f"{name} 必须为数值")
    if minimum is not None and value < minimum:
        raise HarnessError("invalid_argument", f"{name} 不能小于 {minimum:g}")
    return float(value)


def _integer(value: Any, name: str, *, minimum: int | None = None) -> int:
    """校验整数参数，拒绝布尔值和浮点值。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise HarnessError("invalid_argument", f"{name} 必须为整数")
    if minimum is not None and value < minimum:
        raise HarnessError("invalid_argument", f"{name} 不能小于 {minimum}")
    return value


def _time_value(value: Any, name: str) -> str:
    """校验 HH:MM 时间；分钟必须是 5 的倍数，与服务端算法执行约束一致。"""
    text = _text(value, name)
    try:
        hour_text, minute_text = text.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (TypeError, ValueError):
        raise HarnessError("invalid_argument", f"{name} 必须为 HH:MM") from None
    if not hour_text.isdigit() or not minute_text.isdigit() or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise HarnessError("invalid_argument", f"{name} 必须为 HH:MM")
    if minute % 5:
        raise HarnessError("invalid_argument", f"{name} 的分钟必须为 5 的倍数")
    return f"{hour:02d}:{minute:02d}"


def _benchmark(value: Any) -> str:
    """校验基准写法，服务端按逗号拆成类型和代码。"""
    text = _text(value, "benchmark")
    if "," not in text:
        raise HarnessError("invalid_argument", "benchmark 必须为 type,id")
    benchmark_type, benchmark_id = (part.strip() for part in text.split(",", 1))
    if benchmark_type not in {"index", "customized_index"} or not benchmark_id:
        raise HarnessError("invalid_argument", "benchmark 类型必须为 index 或 customized_index，且代码不能为空")
    return f"{benchmark_type},{benchmark_id}"


def _form(data: dict[str, Any]) -> dict[str, str]:
    """把表单值转为字符串；multipart/form 的服务端 schema 以字符串接收数字。"""
    result = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = str(value).lower()
        result[key] = str(value)
    return result


def _config_id(config: dict[str, Any]) -> str:
    """读取模板配置记录 ID，兼容服务端 _id 和已展开的 ID 字段。"""
    value = config.get("channel_id") or config.get("paper_trading_id") or config.get("_id")
    if not value:
        raise HarnessError("invalid_response", "模拟交易配置缺少记录 ID")
    return _segment(str(value))


def _file_failures(result: Any) -> dict[str, Any]:
    """从上传任务终态的 data 中收集逐文件失败，返回文件名到该文件 err_msg 的映射。

    真实服务端的逐文件结果直接挂在 data 下：键为文件名，值为含 new_id 的成功记录或含
    err_msg 的失败记录；通用 partial_failure 不遍历这类动态键，因此由本块显式检查。
    """
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, dict):
        return {}
    return {
        str(name): row["err_msg"]
        for name, row in data.items()
        if isinstance(row, dict) and row.get("err_msg")
    }


class PaperTrading(_Resource):
    """统一模拟交易模板入口；不向调用方暴露底层版本差异。"""

    def create(
        self, template: str, *, name: str, benchmark: str, start_date: str, init_amount: float,
        algo: str | None = None, strategy_category: str | None = None,
        stock_min_fee: float | None = None, stock_commission_rate: float | None = None,
        loan_rate: float | None = None, margin_rate: float | None = None,
        futures_float_rate: float | None = None, futures_float_amount: float | None = None,
        slippage_rate: float | None = None, slippage_ticks: int | None = None,
        start_time: str | None = None, end_time: str | None = None,
        commission_rate: float | None = None, min_fee: float | None = None,
        tag_ids: list[str] | None = None, description: str | None = None,
    ) -> Any:
        """按模板创建模拟交易产品，并等待创建任务结束。

        Args:
            template: 模板类型，equity_long（权益类多头策略）或 conventional（通用策略）。
            name: 产品名称。
            benchmark: 基准，格式 type,id；type 为 index 或 customized_index。
            start_date: 产品开始日期 YYYY-MM-DD。
            init_amount: 初始资金，非负数值。
            algo: equity_long 必填，open、vwap 或 twap。
            strategy_category: conventional 必填；股票多头用 stock_long，其他取值见文档。
            stock_min_fee、stock_commission_rate、loan_rate、margin_rate: conventional 必填。
            futures_float_rate、futures_float_amount: conventional 可选，二者互斥。
            slippage_rate、slippage_ticks: 两种模板都可选，二者互斥。
            start_time、end_time: equity_long 的 vwap/twap 必填，HH:MM。
            commission_rate、min_fee: equity_long 可选佣金参数。
            tag_ids: 可选标签 ID 数组。
            description: 可选说明。
        Returns:
            创建任务结果；含 template、product_id，以及 paper_trading_id 或 channel_id。
            服务端任务失败时抛 HarnessError，不自动重放创建。
        """
        chosen = _text(template, "template")
        if chosen not in _TEMPLATES:
            raise HarnessError("invalid_argument", "template 必须为 equity_long 或 conventional")
        product_name = _text(name, "name")
        benchmark_text = _benchmark(benchmark)
        start_date_text = _text(start_date, "start_date")
        amount = _number(init_amount, "init_amount", minimum=0)
        if futures_float_rate is not None and futures_float_amount is not None:
            raise HarnessError("invalid_argument", "futures_float_rate 与 futures_float_amount 只能二选一")
        if slippage_rate is not None and slippage_ticks is not None:
            raise HarnessError("invalid_argument", "slippage_rate 与 slippage_ticks 只能二选一")

        if tag_ids is not None:
            if not isinstance(tag_ids, list) or not tag_ids or any(not isinstance(item, str) or not item for item in tag_ids):
                raise HarnessError("invalid_argument", "tag_ids 必须为非空字符串数组")
        common: dict[str, Any] = {
            "name": product_name, "benchmark": benchmark_text, "start_date": start_date_text,
            "init_amount": amount, "tag_ids": ",".join(tag_ids) if tag_ids else None,
            "description": description,
        }
        if description is not None and not isinstance(description, str):
            raise HarnessError("invalid_argument", "description 必须为字符串")
        if slippage_rate is not None:
            common["slippage_rate"] = _number(slippage_rate, "slippage_rate", minimum=0)
        if slippage_ticks is not None:
            common["slippage_ticks"] = _integer(slippage_ticks, "slippage_ticks", minimum=0)

        if chosen == "equity_long":
            for field, value in (
                ("strategy_category", strategy_category), ("stock_min_fee", stock_min_fee),
                ("stock_commission_rate", stock_commission_rate), ("loan_rate", loan_rate),
                ("margin_rate", margin_rate), ("futures_float_rate", futures_float_rate),
                ("futures_float_amount", futures_float_amount),
            ):
                if value is not None:
                    raise HarnessError("invalid_argument", f"{field} 只属于 conventional 模板")
            algorithm = _text(algo, "algo")
            if algorithm not in _ALGOS:
                raise HarnessError("invalid_argument", "algo 必须为 open、vwap 或 twap")
            common["strategy_model"] = "equity_long"
            common["algo"] = algorithm
            if algorithm == "open":
                if start_time is not None or end_time is not None:
                    raise HarnessError("invalid_argument", "open 算法不接受 start_time 与 end_time")
            else:
                start = _time_value(start_time, "start_time")
                end = _time_value(end_time, "end_time")
                if start >= end:
                    raise HarnessError("invalid_argument", "start_time 必须早于 end_time")
                common["start_time"], common["end_time"] = start, end
            if commission_rate is not None:
                common["commission_rate"] = _number(commission_rate, "commission_rate", minimum=0)
            if min_fee is not None:
                common["min_fee"] = _number(min_fee, "min_fee", minimum=0)
            endpoint = "products/paper_trading_v2"
        else:
            for field, value in (
                ("algo", algo), ("start_time", start_time), ("end_time", end_time),
                ("commission_rate", commission_rate), ("min_fee", min_fee),
            ):
                if value is not None:
                    raise HarnessError("invalid_argument", f"{field} 只属于 equity_long 模板")
            if strategy_category is None:
                raise HarnessError("invalid_argument", "conventional 模板必须提供 strategy_category")
            category = _text(strategy_category, "strategy_category")
            if category not in _STRATEGY_CATEGORIES:
                raise HarnessError("invalid_argument", "strategy_category 不是支持的策略分类")
            common["strategy_category"] = category
            for field, value in (
                ("stock_min_fee", stock_min_fee), ("stock_commission_rate", stock_commission_rate),
                ("loan_rate", loan_rate), ("margin_rate", margin_rate),
            ):
                if value is None:
                    raise HarnessError("invalid_argument", f"conventional 模板必须提供 {field}")
                common[field] = _number(value, field, minimum=0)
            if futures_float_rate is not None:
                common["futures_float_rate"] = _number(futures_float_rate, "futures_float_rate", minimum=0)
            if futures_float_amount is not None:
                common["futures_float_amount"] = _number(futures_float_amount, "futures_float_amount", minimum=0)
            endpoint = "products/paper_trading_v2:create_conventional"

        payload = self._client.call("POST", endpoint, data=_form(common))
        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if isinstance(data, dict):
            return {**data, "template": chosen}
        return payload

    def get(self, resource: str) -> dict[str, Any]:
        """读取一个已配置模拟交易产品的模板和策略配置。

        Args:
            resource: 模拟交易产品 ID 或名称。
        Returns:
            含 template、product_id、product 与 config 的对象；产品没有模拟交易配置时抛
            paper_trading_config_not_found，不把普通产品壳当作模拟交易。
        """
        ref = self._client.resolve(resource, {"product"})
        product = self._client.call("GET", f"products/{ref.id}")
        if product.get("label") != "paper_trading":
            raise HarnessError("not_paper_trading", "目标产品不是模拟交易产品")
        v2 = {str(row.get("product_id") or row.get("_id")): row for row in self._client.call("GET", "products:list_paper_trading_v2")}
        channels = {
            str(row.get("product_id") or row.get("_id")): row
            for row in self._client.call("GET", "products:list_paper_trading_channels")
        }
        equity_config, conventional_config = v2.get(ref.id), channels.get(ref.id)
        if equity_config is not None and conventional_config is not None:
            raise HarnessError("ambiguous_paper_trading_template", "产品同时存在两种模拟交易配置，拒绝猜测模板")
        if equity_config is not None:
            config, template = equity_config, "equity_long"
        elif conventional_config is not None:
            config, template = conventional_config, "conventional"
        else:
            raise HarnessError("paper_trading_config_not_found", "产品没有模拟交易配置；请使用模拟交易创建操作")
        return {
            "template": template,
            "product_id": ref.id,
            "product": product,
            "config": config,
        }

    def list(self) -> list[dict[str, Any]]:
        """列出当前空间内已配置的模拟交易产品。

        Returns:
            产品记录数组；每项含 template、product_id、product 和 config。同一产品只出现一次。
        """
        products = self._client.call("GET", "products", params={"fields": ["id", "name", "label", "benchmark", "start_date"]})
        product_map = {
            str(row.get("id", row.get("_id"))): row
            for row in products.get("products", [])
            if row.get("label") == "paper_trading"
        }
        v2 = {str(row.get("product_id") or row.get("_id")): row for row in self._client.call("GET", "products:list_paper_trading_v2")}
        channels = {
            str(row.get("product_id") or row.get("_id")): row
            for row in self._client.call("GET", "products:list_paper_trading_channels")
        }
        result = []
        for product_id, product in product_map.items():
            if product_id in v2 and product_id in channels:
                raise HarnessError("ambiguous_paper_trading_template", f"产品 {product_id} 同时存在两种模拟交易配置")
            config = v2.get(product_id) or channels.get(product_id)
            if config is not None:
                result.append({
                    "template": "equity_long" if product_id in v2 else "conventional",
                    "product_id": product_id,
                    "product": product,
                    "config": config,
                })
        return sorted(result, key=lambda row: (str(row["product"].get("name", "")), row["product_id"]))

    def upload_signals(self, resource: str, file_paths: list[str]) -> Any:
        """按产品模板上传模拟交易信号文件，并等待每个上传任务结束。

        Args:
            resource: 模拟交易产品 ID 或名称。
            file_paths: 非空本地文件路径数组；equity_long 使用目标权重单，
                conventional 接受交易单、目标数量单和目标权重单；文件内容由服务端校验。
        Returns:
            equity_long 返回 file_session_id 与最终任务结果；conventional 返回逐批结果数组。
            任一文件 err_msg 非空时抛 partial_failure：details.results 保留完整返回包装，
            details.failed_files 是失败文件名到 err_msg 的映射。不自动重传已成功文件；
            conventional 在首个含失败文件的批次后停止，后续文件未提交，也不出现在批次结果中。
        """
        paths = self._paths(file_paths)
        record = self.get(resource)
        product_id = record["product_id"]
        template = record["template"]
        if template == "equity_long":
            session = self._client.call("POST", "file_upload_sessions")
            session_id = session.get("file_session_id") if isinstance(session, dict) else None
            if not isinstance(session_id, str) or not session_id:
                raise HarnessError("invalid_response", "文件会话未返回 file_session_id", details={"response": session})
            for start in range(0, len(paths), _UPLOAD_BATCH_SIZE):
                self._client.call(
                    "POST", f"file_upload_sessions/{session_id}/files",
                    file_paths=paths[start:start + _UPLOAD_BATCH_SIZE], file_field="files",
                )
            result = self._client.call(
                "POST", f"products/{product_id}/paper_trading_v2/signals:batch_upload",
                data={"file_session_id": session_id},
            )
            upload_result = {"template": template, "product_id": product_id, "file_session_id": session_id, "result": result}
            failed = _file_failures(result)
            if failed:
                raise HarnessError(
                    "partial_failure",
                    "部分或全部信号文件上传失败；已成功文件不会重传，请按逐文件错误修正后仅重试失败文件",
                    details={"results": upload_result, "failed_files": failed},
                )
            return upload_result

        channel_id = _config_id(record["config"])
        batches: list[Any] = []
        failed_files: dict[str, Any] = {}
        for start in range(0, len(paths), _UPLOAD_BATCH_SIZE):
            batch = self._client.call(
                "POST", f"products/{product_id}/paper_trading_channels/{channel_id}/batch_paper_trading_file",
                file_paths=paths[start:start + _UPLOAD_BATCH_SIZE], file_field="files",
            )
            batches.append(batch)
            failed_files.update(_file_failures(batch))
            if failed_files:
                break
        upload_result = {"template": template, "product_id": product_id, "channel_id": channel_id, "batches": batches}
        if failed_files:
            raise HarnessError(
                "partial_failure",
                "部分或全部信号文件上传失败；已成功文件不会重传，失败批次之后的文件尚未提交，"
                "请修复失败文件后另行提交未上传文件",
                details={"results": upload_result, "failed_files": failed_files},
            )
        return upload_result

    def list_signals(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None,
        fields: str | None = None,
    ) -> Any:
        """读取模拟交易信号列表，按产品模板选择对应查询。

        Args:
            resource: 模拟交易产品 ID 或名称。
            start_date: 可选开始日期 YYYY-MM-DD。
            end_date: 可选结束日期 YYYY-MM-DD。
            fields: 可选逗号串字段；只支持 equity_long 模板。
        Returns:
            服务端原始信号数组，含日期、文件名和状态。
        """
        record = self.get(resource)
        product_id = record["product_id"]
        if record["template"] == "equity_long":
            return self._client.call("GET", f"products/{product_id}/paper_trading_v2/signals", params={
                "start_date": start_date, "end_date": end_date, "fields": fields,
            })
        if fields is not None:
            raise HarnessError("invalid_argument", "conventional 模板不支持 fields 过滤")
        return self._client.call("GET", f"products/{product_id}/paper_trading_signals", params={
            "start_date": start_date, "end_date": end_date,
        })

    def delete_signals(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None,
        signal_ids: list[str] | None = None,
    ) -> Any:
        """按日期或信号 ID 删除模拟交易信号；删除不可撤销。

        Args:
            resource: 模拟交易产品 ID 或名称。
            start_date: 按日期范围删除时的起始日。
            end_date: 按日期范围删除时的截止日。
            signal_ids: 按信号 ID 删除；与日期范围至少提供一个。
        Returns:
            equity_long 返回任务终态；conventional 按信号 ID 删除时返回逐项任务终态，
            按日期删除时返回批量任务终态。请求体只包含实际提供的条件，未提供的日期
            不写成 null；删除不可撤销。
        """
        if signal_ids is not None:
            if not isinstance(signal_ids, list) or not signal_ids:
                raise HarnessError("invalid_argument", "signal_ids 必须为非空数组")
            for signal_id in signal_ids:
                _segment(signal_id)
        if signal_ids is None and start_date is None and end_date is None:
            raise HarnessError("invalid_argument", "start_date、end_date、signal_ids 至少提供一个")
        record = self.get(resource)
        product_id = record["product_id"]
        body = {key: value for key, value in (("start_date", start_date), ("end_date", end_date)) if value is not None}
        if record["template"] == "equity_long":
            if signal_ids is not None:
                body["signal_ids"] = signal_ids
            return self._client.call("DELETE", f"products/{product_id}/paper_trading_v2/signals:async_delete", json=body)
        if signal_ids is not None:
            results = [
                self._client.call(
                    "DELETE",
                    f"products/{product_id}/paper_trading_channels/paper_trading_signals/{_segment(signal_id)}",
                )
                for signal_id in signal_ids
            ]
            return {"template": "conventional", "results": results}
        result = self._client.call(
            "DELETE", f"products/{product_id}/paper_trading_channels/paper_trading_signals", json=body,
        )
        return {"template": "conventional", **result} if isinstance(result, dict) else result

    def recompute(self, resource: str, *, date: str | None = None) -> Any:
        """按产品模板提交模拟交易重算，不表示撮合或估值已完成。

        Args:
            resource: 模拟交易产品 ID 或名称。
            date: 可选重算起始日 YYYY-MM-DD；省略时重算全部信号。
        Returns:
            equity_long 与 conventional 都返回异步任务终态；任务成功不表示撮合或估值已完成。
        """
        if date is not None:
            _text(date, "date")
        body = {} if date is None else {"date": date}
        record = self.get(resource)
        product_id = record["product_id"]
        if record["template"] == "equity_long":
            return self._client.call("POST", f"products/{product_id}/paper_trading_v2:recompute", json=body)
        channel_id = _config_id(record["config"])
        return self._client.call(
            "POST", f"products/{product_id}/paper_trading_channels/{channel_id}:async_recompute", json=body,
        )

    def delete(self, resource: str) -> Any:
        """删除模拟交易产品及其模拟交易配置；删除不可撤销。

        Args:
            resource: 模拟交易产品 ID 或名称。
        Returns:
            异步任务终态；不自动重发删除。
        """
        record = self.get(resource)
        product_id = record["product_id"]
        suffix = "paper_trading_v2" if record["template"] == "equity_long" else "paper_trading_v2_conventional"
        result = self._client.call("DELETE", f"products/{product_id}/{suffix}")
        return {"template": record["template"], **result} if isinstance(result, dict) else result

    @staticmethod
    def _paths(file_paths: list[str]) -> list[str]:
        """校验本地文件路径数组存在且为普通文件，避免把目录或空批次发给服务端。"""
        if not isinstance(file_paths, list) or not file_paths:
            raise HarnessError("invalid_argument", "file_paths 必须为非空文件路径数组")
        paths = []
        for path in file_paths:
            if not isinstance(path, (str, Path)):
                raise HarnessError("invalid_argument", "file_paths 的元素必须为文件路径")
            candidate = Path(path)
            if not candidate.is_file():
                raise HarnessError("invalid_argument", f"文件不存在或不是普通文件：{candidate}")
            paths.append(str(candidate))
        return paths
