"""产品交易流水读写、导入和导出。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _segment


class Trades(_Resource):
    """产品交易流水写入与产品、产品组流水查询。"""

    def list(
        self, resource: str, start_date: str, end_date: str, *, sources: list[str] | None = None,
        order_book_id: str | None = None, symbol: str | None = None,
        asset_transaction_types: list[str] | None = None, account_names: list[str] | None = None,
        asset_unit_ids: list[str] | None = None, key_words: list[str] | None = None,
        group_by: str | None = None, remarks: str | None = None, is_query_assistant: bool = False,
        offset: int | None = None, limit: int | None = None, sort_key: str | None = None,
        start_inserted_date: str | None = None, end_inserted_date: str | None = None,
        algo_names: list[str] | None = None, algo_types: list[str] | None = None,
        algo_time_span: list[str] | None = None,
    ) -> Any:
        """查询产品或产品组流水，聚合查询自动等待旧版 DOING 状态完成。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 流水起始日期 YYYY-MM-DD，包含当日。
            end_date: 流水截止日期 YYYY-MM-DD，包含当日。
            sources: 流水来源枚举数组，如 open_api、settlement_upload。
            order_book_id: 资产代码筛选。
            symbol: 资产名称筛选。
            asset_transaction_types: “交易资产类别-交易类型”数组。
            account_names: 账户名称数组。
            asset_unit_ids: 资产单元 ID 筛选数组。
            key_words: 服务端关键词数组。
            group_by: asset 或 trading_date；省略不聚合。
            remarks: 备注筛选。
            is_query_assistant: 是否查询副表，默认 false。
            offset: 分页偏移。
            limit: 单页数量。
            sort_key: “字段,1”升序或“字段,-1”降序。
            start_inserted_date: 录入起始日，与 end_inserted_date 同时提供才生效。
            end_inserted_date: 录入截止日，包含当日。
            algo_names: 算法名称数组。
            algo_types: 算法类型数组。
            algo_time_span: 算法时间段数组，按服务端格式校验。
        Returns:
            原始 trades 与 total；聚合失败抛异常，不将 FAIL 当成功。
        """
        return self._client.call("GET", self._path(resource, {"product", "product_group"}) + "/trades", params={
            "start_date": start_date, "end_date": end_date, "sources": sources,
            "order_book_id": order_book_id, "symbol": symbol, "asset_transaction_types": asset_transaction_types,
            "account_names": account_names, "asset_unit_ids": asset_unit_ids, "key_words": key_words,
            "group_by": group_by, "remarks": remarks, "is_query_assistant": is_query_assistant,
            "offset": offset, "limit": limit, "sort_key": sort_key,
            "start_inserted_date": start_inserted_date, "end_inserted_date": end_inserted_date,
            "algo_names": algo_names, "algo_types": algo_types, "algo_time_span": algo_time_span,
        }, legacy_task=True)

    def get(self, resource: str, trade_id: str) -> Any:
        """读取产品的一条流水；服务端无产品组单条流水端点。

        Args:
            resource: 归属产品唯一 ID 或名称。
            trade_id: 服务端流水记录 ID，不是 foreign_id。
        Returns:
            服务端完整流水 JSON。
        """
        return self._client.call("GET", self._path(resource, {"product"}) + f"/trades/{_segment(trade_id)}")

    def upload(self, resource: str, data: list[dict[str, Any]], *, prefer_fill_fund_exchange_suffix: bool = True) -> Any:
        """导入结构化流水数组；文件导入见 upload_intraday_file 与 upload_settlement_file。

        Args:
            resource: 目标产品唯一 ID 或名称，不支持产品组。
            data: 非空流水对象数组；缺省 source 补 open_api，已有 source 保留。
                foreign_id 按产品做 upsert；不自动拆批，不改变调用方数据。
            prefer_fill_fund_exchange_suffix: 默认 true 自动补基金场内后缀；false 使用 v2 路由。
        Returns:
            原始逐项 upsert 结果；任意部分失败抛异常并保留完整结果。
        """
        _nonempty(data, "data")
        if not all(isinstance(item, dict) for item in data):
            raise HarnessError("invalid_argument", "data 每一项必须是 JSON 对象")
        payload = [{"source": "open_api", **item} for item in data]
        endpoint = "trades:batch_insert" if prefer_fill_fund_exchange_suffix else "trades:batch_insert_v2"
        result = self._client.call("POST", self._path(resource, {"product"}) + "/" + endpoint, json=payload)
        self._client.partial_failure(result)
        return result

    def upload_intraday_file(
        self, resource: str, file_path: str, account: str, *, asset_unit_id: str | None = None,
        prefer_fill_fund_exchange_suffix: bool = True,
    ) -> Any:
        """上传一个日内流水文件并检查逐项结果。

        Args:
            resource: 目标产品唯一 ID 或名称。
            file_path: 本地日内流水文件路径。
            account: 目标账户名称，必须显式提供。
            asset_unit_id: 可选资产单元 ID。
            prefer_fill_fund_exchange_suffix: 默认 true 自动补基金场内后缀；false 使用 v2 路由。
        Returns:
            原始文件导入结果；任意部分失败抛异常并保留完整结果。
            按成功解析日期、产品、账户及可选资产单元覆盖日内/open_api 流水。
        """
        if not account:
            raise HarnessError("invalid_argument", "日内流水文件上传必须提供 account")
        path = self._path(resource, {"product"})
        path += ":upload_intraday_trade_file" if prefer_fill_fund_exchange_suffix else "/trades:upload_intraday_file_v2"
        form = {"account": account}
        if asset_unit_id is not None:
            form["asset_unit_id"] = asset_unit_id
        result = self._client.call("POST", path, data=form, file_path=file_path)
        self._client.partial_failure(result)
        return result

    def update(self, resource: str, trade_id: str, data: dict[str, Any]) -> Any:
        """修改指定产品流水，服务端校验字段并触发必要重算。

        Args:
            resource: 归属产品唯一 ID 或名称。
            trade_id: 流水记录 ID。
            data: 修改字段 JSON；支持数量、价格、费用、时间、账户、标的、备注、
                asset_unit_id 及算法字段等，不能改变交易类型或来源。
        Returns:
            原始 effect_count 与 updated 流水记录。
        """
        return self._client.call("PATCH", self._path(resource, {"product"}) + f"/trades/{_segment(trade_id)}", json=data)

    def delete(
        self, resource: str, *, trade_ids: list[str] | None = None,
        start_date: str | None = None, end_date: str | None = None,
        sources: list[str] | None = None, order_book_id: str | None = None, symbol: str | None = None,
        asset_transaction_types: list[str] | None = None, account_names: list[str] | None = None,
        asset_unit_ids: list[str] | None = None, key_words: list[str] | None = None,
        remarks: str | None = None, is_query_assistant: bool = False,
        algo_names: list[str] | None = None, algo_types: list[str] | None = None,
        algo_time_span: list[str] | None = None,
    ) -> Any:
        """删除产品流水：默认按日期与筛选条件，给出 trade_ids 时按记录 ID。

        Args:
            resource: 产品唯一 ID 或名称，不支持产品组。
            trade_ids: 可选非空流水记录 ID 数组（不是 foreign_id）；提供时按 ID 同步批量删除，
                且不能同时提供日期或筛选参数。
            start_date: 起始日 YYYY-MM-DD；省略从产品交易起始日开始，受封账限制。
            end_date: 截止日 YYYY-MM-DD；省略至今日，包含当日。
            sources: 来源枚举数组；省略不限来源。
            order_book_id: 资产代码筛选。
            symbol: 资产名称筛选。
            asset_transaction_types: “交易资产类别-交易类型”数组。
            account_names: 账户名称数组。
            asset_unit_ids: 资产单元 ID 数组。
            key_words: 关键词数组。
            remarks: 备注筛选。
            is_query_assistant: 是否删除副表流水，默认 false。
            algo_names: 算法名称数组。
            algo_types: 算法类型数组。
            algo_time_span: 算法时间段数组。
        Returns:
            按 ID 模式返回 effect_count 与删除结果；按日期模式返回任务终态结果。
            按日期模式省略全部筛选会删除整个允许日期范围，不能撤销。
        """
        if trade_ids is not None:
            if is_query_assistant or any(
                value is not None for value in (
                    start_date, end_date, sources, order_book_id, symbol, asset_transaction_types,
                    account_names, asset_unit_ids, key_words, remarks, algo_names, algo_types, algo_time_span,
                )
            ):
                raise HarnessError("invalid_argument", "trade_ids 与日期或筛选参数互斥，请只保留一种删除方式")
            _nonempty(trade_ids, "trade_ids")
            return self._client.call("POST", self._path(resource, {"product"}) + "/trades:batch_delete", json=trade_ids)
        return self._client.call("GET", self._path(resource, {"product"}) + "/trades:batch_delete_by_date", params={
            "start_date": start_date, "end_date": end_date, "sources": sources,
            "order_book_id": order_book_id, "symbol": symbol, "asset_transaction_types": asset_transaction_types,
            "account_names": account_names, "asset_unit_ids": asset_unit_ids, "key_words": key_words,
            "remarks": remarks, "is_query_assistant": is_query_assistant,
            "algo_names": algo_names, "algo_types": algo_types, "algo_time_span": algo_time_span,
        }, no_replay=True)

    def upload_settlement_file(
        self, resource: str, file_path: str, account: str, *, asset_unit_id: str | None = None,
        prefer_fill_fund_exchange_suffix: bool = True,
    ) -> Any:
        """上传一个日终结算流水文件并等待旧版任务协议完成。

        Args:
            resource: 目标产品唯一 ID 或名称。
            file_path: 本地结算流水文件路径。
            account: 目标账户名称，必须显式提供。
            asset_unit_id: 可选资产单元 ID。
            prefer_fill_fund_exchange_suffix: 默认 true 自动补基金场内后缀；false 使用 v2。
        Returns:
            服务端任务终态 JSON；部分失败抛异常。结算导入有覆盖旧流水副作用。
        """
        if not account:
            raise HarnessError("invalid_argument", "结算流水文件上传必须提供 account")
        path = self._path(resource, {"product"})
        path += ":upload_settlement_trade_file" if prefer_fill_fund_exchange_suffix else "/trades:upload_settlement_file_v2"
        form = {"account": account}
        if asset_unit_id is not None:
            form["asset_unit_id"] = asset_unit_id
        result = self._client.call("POST", path, data=form, file_path=file_path, legacy_task=True)
        self._client.partial_failure(result)
        return result

    def download(
        self, resource: str, start_date: str, end_date: str, output: str, *,
        sources: list[str] | None = None, order_book_id: str | None = None, symbol: str | None = None,
        asset_transaction_types: list[str] | None = None, account_names: list[str] | None = None,
        asset_unit_ids: list[str] | None = None, key_words: list[str] | None = None,
        group_by: str | None = None, remarks: str | None = None, is_query_assistant: bool = False,
        offset: int | None = None, limit: int | None = None, sort_key: str | None = None,
        start_inserted_date: str | None = None, end_inserted_date: str | None = None,
        algo_names: list[str] | None = None, algo_types: list[str] | None = None,
        algo_time_span: list[str] | None = None,
    ) -> Any:
        """生成并下载产品或产品组流水 Excel，等待任务后写入指定文件。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            start_date: 流水起始日 YYYY-MM-DD，包含当日。
            end_date: 流水截止日 YYYY-MM-DD，包含当日。
            output: 必填本地输出文件路径，不使用服务端文件名推导路径。
            sources: 来源枚举数组。
            order_book_id: 资产代码筛选。
            symbol: 资产名称筛选。
            asset_transaction_types: “交易资产类别-交易类型”数组。
            account_names: 账户名称数组。
            asset_unit_ids: 资产单元 ID 数组。
            key_words: 关键词数组。
            group_by: asset 或 trading_date；省略不聚合。
            remarks: 备注筛选。
            is_query_assistant: 是否查询副表，默认 false。
            offset: 分页偏移，交由服务端导出实现处理。
            limit: 数量限制，交由服务端导出实现处理。
            sort_key: “字段,1”升序或“字段,-1”降序。
            start_inserted_date: 录入起始日，须与录入截止日同时提供。
            end_inserted_date: 录入截止日，包含当日。
            algo_names: 算法名称数组。
            algo_types: 算法类型数组。
            algo_time_span: 算法时间段数组。
        Returns:
            客户端下载元数据；服务端成功时返回二进制文件而非 JSON。
        """
        return self._client.call("GET", self._path(resource, {"product", "product_group"}) + "/trades_file", params={
            "start_date": start_date, "end_date": end_date, "sources": sources,
            "order_book_id": order_book_id, "symbol": symbol, "asset_transaction_types": asset_transaction_types,
            "account_names": account_names, "asset_unit_ids": asset_unit_ids, "key_words": key_words,
            "group_by": group_by, "remarks": remarks, "is_query_assistant": is_query_assistant,
            "offset": offset, "limit": limit, "sort_key": sort_key,
            "start_inserted_date": start_inserted_date, "end_inserted_date": end_inserted_date,
            "algo_names": algo_names, "algo_types": algo_types, "algo_time_span": algo_time_span,
        }, legacy_task=True, download=output)

    def create_auto_balance_override(self, resource: str, data: dict[str, Any]) -> Any:
        """新增或覆盖一条自动权益编辑，并按除权除息日提交重算。

        Args:
            resource: 产品唯一 ID 或名称。
            data: 必含 asset_class、transaction_type、trading_date、order_book_id 与 update；
                update 的可用字段受交易类型限制（分红类 settlement_amount、remarks，
                红股类 quantity、remarks），可选 asset_unit_id 限定资产单元。
        Returns:
            服务端原始 effect_count；0 表示没有新增或修改。
        """
        return self._client.call(
            "POST", self._path(resource, {"product"}) + "/trades:auto-balance-override", json=data,
        )

    def delete_auto_balance_override(self, resource: str, override_id: str) -> Any:
        """按记录 ID 删除一条自动权益编辑。

        Args:
            resource: 产品唯一 ID 或名称。
            override_id: 自动权益编辑记录 ID，不是流水 ID。
        Returns:
            服务端原始 effect_count；记录不存在时为 0。
        """
        identifier = _segment(override_id)
        return self._client.call(
            "DELETE", self._path(resource, {"product"}) + f"/trades:auto-balance-override/{identifier}",
        )
