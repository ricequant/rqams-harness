"""产品托管事件：权益、费用与科目调整的录入、修改、删除与文件导入。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _segment


class CustodianEvents(_Resource):
    """托管事件：影响净值的权益、费用与科目调整输入，不包含份额事件。"""

    def list(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None,
        custodian_event_type: str | None = None, adjust_target: str | None = None,
        offset: int | None = None, limit: int | None = None,
    ) -> Any:
        """列出产品托管事件。

        Args:
            resource: 产品唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略不设下界。
            end_date: YYYY-MM-DD；省略不设上界。
            custodian_event_type: 托管事件类型枚举，取值见 docs/fields/custodian_events.md。
            adjust_target: 科目调整目标资产类别；省略返回全部调整目标。
            offset: 跳过条数；省略由服务端按 0 处理。
            limit: 返回条数上限；省略由服务端按全部处理。
        Returns:
            服务端原始对象，含 custodian_events 数组与 total；列表不含产品 ID 字段。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/custodian_events",
            params={
                "start_date": start_date, "end_date": end_date,
                "custodian_event_type": custodian_event_type, "adjust_target": adjust_target,
                "offset": offset, "limit": limit,
            },
        )

    def latest(self) -> Any:
        """读取工作空间内各产品的最新托管事件日期。

        Returns:
            产品 ID 到最新日期字符串的映射，只保留当前身份在目录中可见的产品。
        """
        latest = self._client.call("GET", "products/custodian_events:get_latest_custodian_event")
        visible = {ref.id for ref in self._client.resource_catalog() if ref.type == "product"}
        return {product_id: value for product_id, value in latest.items() if product_id in visible}

    def create(self, resource: str, data: dict[str, Any] | list[dict[str, Any]]) -> Any:
        """新增一个或多个托管事件，统一走服务端批量插入。

        Args:
            resource: 产品唯一 ID 或名称。
            data: 单个事件对象或其数组；每项必含 custodian_event_type 与 date。
        Returns:
            服务端原始 effect_count；服务端批量接口不返回新记录 ID，用 list 按日期区间取回。
        """
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            raise HarnessError("invalid_argument", "data 必须为事件对象或其数组")
        _nonempty(items, "data")
        if not all(isinstance(item, dict) for item in items):
            raise HarnessError("invalid_argument", "data 数组元素必须为事件对象")
        result = self._client.call(
            "POST", self._path(resource, {"product"}) + "/custodian_events:batch_insert", json=items,
        )
        self._client.partial_failure(result)
        return result

    def update(self, resource: str, custodian_event_id: str, data: dict[str, Any]) -> Any:
        """按事件 ID 整体覆盖修改一个托管事件。

        Args:
            resource: 产品唯一 ID 或名称。
            custodian_event_id: list 返回的事件 ID。
            data: 事件字段；服务端要求 custodian_event_type 与 date 必填，未提供的字段按新事件形态覆盖。
        Returns:
            服务端原始 effect_count。
        """
        path = self._path(resource, {"product"}) + f"/custodian_events/{_segment(custodian_event_id)}"
        return self._client.call("PUT", path, json=data)

    def delete(self, resource: str, custodian_event_ids: list[str]) -> Any:
        """按事件 ID 批量删除托管事件并触发必要重算。

        Args:
            resource: 产品唯一 ID 或名称。
            custodian_event_ids: 非空事件 ID 数组。
        Returns:
            服务端原始 effect_count；删除不可撤销。
        """
        _nonempty(custodian_event_ids, "custodian_event_ids")
        return self._client.call(
            "POST", self._path(resource, {"product"}) + "/custodian_events:batch_delete",
            json=custodian_event_ids,
        )

    def upload_file(self, resources: list[str], file_path: str) -> Any:
        """导入一份托管事件文件，按产品归属写入并生成导入凭证。

        Args:
            resources: 非空产品 ID/名称数组；服务端按 form 的 product_ids 归属事件。
            file_path: 本地托管事件文件路径。
        Returns:
            服务端原始 effect_count、err_msg 与 confirmation_ids；err_msg 非空时抛部分失败异常。
        """
        refs = self._batch_refs(resources, {"product"})
        result = self._client.call(
            "POST", "upload_custodian_event_file",
            data={"product_ids": ",".join(ref.id for ref in refs)}, file_path=file_path,
        )
        self._client.partial_failure(result)
        return result
