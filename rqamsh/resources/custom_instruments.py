"""自定义标的及公允价格管理。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _segment


class CustomInstruments(_Resource):
    """自定义标的与公允价格；读写先核验空间与归属产品，无归属历史标的的可写性由服务端判定。"""

    def _own(self, instrument_ids: list[str], *, write: bool = False) -> list[str]:
        """从当前空间实际记录中匹配全部 ID 并检查归属，未全部授权时不写入。

        无归属产品的历史标的没有客户端归属校验，能否修改由服务端判定。
        """
        requested = {_segment(identifier) for identifier in instrument_ids}
        response = self._client.call("GET", "customized_instruments")
        matched = {
            str(item.get("id", item.get("_id"))): item
            for item in response["customized_instruments"]
            if str(item.get("workspace_id", "")).lower() == self._client.workspace_id
            and str(item.get("id", item.get("_id"))) in requested
        }
        if set(matched) != requested:
            raise HarnessError("resource_not_found", "自定义标的不存在或不可访问", status=404)
        for item in matched.values():
            if item.get("product_id") and write:
                self._client.resolve(str(item["product_id"]), {"product"})
        return list(matched)

    def list(
        self, *, resource: str | None = None, asset_class: str | None = None,
        q: str | None = None, offset: int | None = None, limit: int | None = None,
    ) -> Any:
        """查询当前工作空间自定义标的，列表不含公允价历史。

        Args:
            resource: 可选归属产品唯一 ID 或名称；不支持产品组。
            asset_class: 场外资产类别枚举。
            q: 服务端名称或代码搜索字符串。
            offset: 分页起始偏移。
            limit: 单页数量。
        Returns:
            仅含可访问标的的 customized_instruments；total 为权限过滤后、分页前数量。
        """
        if (offset is not None and offset < 0) or (limit is not None and limit < 0):
            raise HarnessError("invalid_argument", "offset 和 limit 不能为负数")
        product_id = self._client.resolve(resource, {"product"}).id if resource is not None else None
        permitted = {ref.id for ref in self._client.resource_catalog() if ref.type == "product"}
        result = self._client.call("GET", "customized_instruments", params={
            "product_id": product_id, "asset_class": asset_class, "q": q,
        })
        instruments = [
            item for item in result["customized_instruments"]
            if str(item.get("workspace_id", "")).lower() == self._client.workspace_id
            and (not item.get("product_id") or str(item["product_id"]) in permitted)
        ]
        start = offset or 0
        page = instruments[start:start + limit] if limit else instruments[start:]
        return {**result, "customized_instruments": page, "total": len(instruments)}

    def get(self, instrument_id: str) -> Any:
        """读取自定义标的及完整公允价历史。

        Args:
            instrument_id: 自定义标的记录 ID，不是 order_book_id。
        Returns:
            服务端标的原始 JSON，包含 fair_values。
        """
        instrument_id = self._own([instrument_id])[0]
        return self._client.call("GET", f"customized_instruments/{_segment(instrument_id)}")

    def create(self, resource: str, asset_class: str, order_book_id: str, symbol: str) -> Any:
        """在指定产品下创建自定义标的。

        Args:
            resource: 归属产品唯一 ID 或名称。
            asset_class: 服务端支持的场外资产类别。
            order_book_id: 自定义资产代码。
            symbol: 资产名称。
        Returns:
            原始 customized_ins_id；同空间、产品、类别及代码重复会失败。
        """
        ref = self._client.resolve(resource, {"product"})
        return self._client.call("POST", "customized_instruments", json={
            "product_id": ref.id, "asset_class": asset_class, "order_book_id": order_book_id, "symbol": symbol,
        })

    def update(
        self, instrument_id: str, *, resource: str | None = None,
        asset_class: str | None = None, order_book_id: str | None = None, symbol: str | None = None,
    ) -> Any:
        """局部修改自定义标的基础字段，不修改价格历史。

        Args:
            instrument_id: 自定义标的记录 ID。
            resource: 新归属产品唯一 ID 或名称；省略保持不变。
            asset_class: 新资产类别；省略保持不变。
            order_book_id: 新资产代码；省略保持不变。
            symbol: 新名称；省略保持不变。
        Returns:
            服务端原始 effect_count。
        """
        instrument_id = self._own([instrument_id], write=True)[0]
        body = {key: value for key, value in {
            "asset_class": asset_class, "order_book_id": order_book_id, "symbol": symbol,
        }.items() if value is not None}
        if resource is not None:
            ref = self._client.resolve(resource, {"product"})
            body["product_id"] = ref.id
        return self._client.call("PATCH", f"customized_instruments/{_segment(instrument_id)}", json=body)

    def delete(self, instrument_ids: list[str]) -> Any:
        """批量删除自定义标的。

        Args:
            instrument_ids: 非空自定义标的记录 ID 数组，不接受资产代码。
        Returns:
            服务端原始 effect_count；具体删除约束由服务端执行。
        """
        _nonempty(instrument_ids, "instrument_ids")
        matched_ids = self._own(instrument_ids, write=True)
        return self._client.call("POST", "customized_instruments:batch_delete", json=matched_ids)

    def upload_fairvalue(self, instrument_id: str, file_path: str) -> Any:
        """上传公允价文件，覆盖文件最早日期起的全部历史价格。

        Args:
            instrument_id: 自定义标的记录 ID。
            file_path: 本地价格文件路径，按原文件上传；不做汇率换算。
        Returns:
            服务端原始 effect_count；相关产品可能被重算。
        """
        instrument_id = self._own([instrument_id], write=True)[0]
        return self._client.call(
            "POST", f"customized_instruments/{_segment(instrument_id)}:upload_fair_price_file", file_path=file_path,
        )

    def replace_fairvalues(self, instrument_id: str, data: list[dict[str, Any]]) -> Any:
        """全量替换公允价历史，空数组表示清空，遗漏日期不会保留。

        Args:
            instrument_id: 自定义标的记录 ID。
            data: 完整价格数组，每项含 date（YYYY-MM-DD）和 value（数值）。
        Returns:
            原始 effect_count；可能触发相关产品重算，不修改调用方数组。
        """
        instrument_id = self._own([instrument_id], write=True)[0]
        result = self._client.call(
            "POST", f"customized_instruments/{_segment(instrument_id)}/fair_value", json=data,
        )
        self._client.partial_failure(result)
        return result

    def insert_fairvalues(self, resource: str, data: list[dict[str, Any]]) -> Any:
        """向归属产品增量写入通用公允价，同日同标的记录被更新。

        Args:
            resource: 归属产品唯一 ID 或名称。
            data: 非空公允价数组，每项必含 order_book_id、asset_class、date、symbol 与 value；
                可选字段 field，当 field 为 fair_value 且标的为港股代码时按当日汇率折算。
        Returns:
            服务端原始新增记录 ID 数组；被更新的记录不计入，服务端判定为重复写入时返回错误。
        """
        _nonempty(data, "data")
        return self._client.call(
            "POST", self._path(resource, {"product"}) + "/fair_values:batch_insert", json=data,
        )
