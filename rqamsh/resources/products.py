"""产品与产品组的配置、生命周期和重算。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _text


class Products(_Resource):
    """产品配置、生命周期及重算提交操作。"""

    def list(
        self, *, fields: list[str] | None = None, sources: list[str] | None = None,
        member_user_id: int | None = None,
    ) -> Any:
        """查询当前工作空间中当前用户可访问的产品。

        Args:
            fields: 返回字段列表；省略使用服务端默认字段，始终保留 id 用于可见性过滤。
            sources: 产品 data_source 枚举列表，不是流水来源。
            member_user_id: 按指定成员获分享的产品筛选，不突破当前用户可见范围。
        Returns:
            含 products 和 total 的对象，仅保留已核验可访问的产品。
        """
        permitted = {ref.id for ref in self._client.resource_catalog() if ref.type == "product"}
        requested_fields = list(dict.fromkeys([*fields, "id"])) if fields else None
        result = self._client.call("GET", "products", params={
            "fields": requested_fields, "sources": sources, "member_user_id": member_user_id,
        })
        products = [item for item in result["products"] if str(item.get("id", item.get("_id"))) in permitted]
        return {**result, "products": products, "total": len(products)}

    def get(self, resource: str) -> Any:
        """读取产品完整配置。

        Args:
            resource: 当前工作空间可访问产品的唯一 ID 或名称。
        Returns:
            服务端产品 JSON；产品组及资产单元不支持。
        """
        return self._client.call("GET", self._path(resource, {"product"}))

    def create(self, data: dict[str, Any]) -> Any:
        """创建产品，服务端按数据源校验配置并可能初始化估值。

        Args:
            data: 产品 JSON；必含 data_source、name、investment_category、
                strategy_category、benchmark、calendar，其他必填字段依数据源而定。
        Returns:
            原始 product_id、err_msgs 等创建结果，不修改输入对象。
        """
        result = self._client.call("POST", "products", json=data)
        self._client.partial_failure(result)
        return result

    def update(self, resource: str, data: dict[str, Any]) -> Any:
        """局部修改产品；影响估值的字段由服务端触发重算。

        Args:
            resource: 产品唯一 ID 或名称。
            data: 需修改的产品字段；未提供字段保持不变，显式 null 按服务端处理。
        Returns:
            服务端 effect_count 等原始修改结果。
        """
        return self._client.call("PATCH", self._path(resource, {"product"}), json=data)

    def delete(self, resource: str) -> Any:
        """删除指定产品及服务端关联业务数据，此操作不可撤销。

        Args:
            resource: 待删除产品的唯一 ID 或名称。
        Returns:
            服务端 effect_count 等原始删除结果。
        """
        return self._client.call("DELETE", self._path(resource, {"product"}))

    def recompute(self, resource: str, *, start_date: str | None = None) -> Any:
        """提交一个产品的重算，不表示估值已完成。

        Args:
            resource: 产品唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略从产品起始日重算。
        Returns:
            服务端 submit_recompute_count；可用 compute_state 查询状态。
        """
        ref = self._client.resolve(resource, {"product"})
        body: dict[str, Any] = {"product_ids": [ref.id]}
        if start_date is not None:
            body["start_date"] = start_date
        return self._client.call("POST", "products:recompute", json=body)

    def compute_state(self, resource: str) -> Any:
        """读取产品估值任务状态，不自动等待业务重算完成。

        Args:
            resource: 产品唯一 ID 或名称。
        Returns:
            原始 state 与 execution_id。
        """
        return self._client.call("GET", self._path(resource, {"product"}) + "/compute_state")

    def name_exists(self, name: str) -> Any:
        """按产品名称查询是否已存在，不替代资源消歧或权限检查。

        Args:
            name: 要检查的产品名称。
        Returns:
            服务端原始对象，含布尔字段 exists。
        """
        return self._client.call("GET", "products:name_exists", params={"name": name})

    def enable_shares(
        self, resource: str, shares: dict[str, Any],
        custodian_events: dict[str, Any], unit_events: dict[str, Any],
    ) -> Any:
        """把未封账的历史产品转换为分类份额产品，并等待异步任务结束。

        Args:
            resource: 产品唯一 ID 或名称。
            shares: 份额名到份额设置的映射；每项必含 effective_date，可含
                management_fee、performance_pay、subscription_fee、redemption_fee。
            custodian_events: 原托管事件 ID 到「份额名 → 金额」的归属映射。
            unit_events: 原份额事件 ID 到「份额名 → 份额」的归属映射。
        Returns:
            服务端任务终态 JSON；任务失败抛 HarnessError，不自动重发写入体。
        """
        return self._client.call("POST", self._path(resource, {"product"}) + ":enable_shares", json={
            "shares": shares, "custodian_events": custodian_events, "unit_events": unit_events,
        })

    def field_exists(
        self, *, name: str | None = None, full_name: str | None = None,
        account_name: str | None = None, fund_code: str | None = None,
    ) -> Any:
        """检查产品名称、全称、账号名称或基金代码是否已被占用。

        Args:
            name: 产品名称。
            full_name: 产品全称。
            account_name: 账号名称；服务端通用检查路由把字段名映射错为 accounts_name，
                本操作改走检查 accounts.name 的专用路由，避免恒为 false 的结论。
            fund_code: 基金代码。
        Returns:
            服务端原始对象，含布尔字段 exists；四个参数必须且只能提供一个。
        """
        provided = {
            field: value for field, value in (
                ("name", name), ("full_name", full_name), ("account_name", account_name), ("fund_code", fund_code),
            ) if value is not None
        }
        if len(provided) != 1:
            raise HarnessError("invalid_argument", "name、full_name、account_name、fund_code 必须且只能提供一个")
        field, value = next(iter(provided.items()))
        if not isinstance(value, str) or not value:
            raise HarnessError("invalid_argument", f"{field} 必须为非空字符串")
        endpoint = "products:account_name_exists" if field == "account_name" else "products:is_field_exists"
        return self._client.call("GET", endpoint, params={field: value})

    def valuation_report_missing_dates(self) -> Any:
        """列出各产品自封账日（未封账取交易起始日）以来缺失估值表的交易日数量。

        Returns:
            服务端原始数组，每项含 product_id、product_name、product_full_name、
            missing_date_count 与 newest_valuation_report_date；只保留当前身份可见的产品。
        """
        rows = self._client.call("GET", "products:valuation_report_missing_date")
        visible = {ref.id for ref in self._client.resource_catalog() if ref.type == "product"}
        return [row for row in rows if str(row.get("product_id")) in visible]

    def uploaded_file_hashes(self, product_ids: list[str], file_type: str) -> Any:
        """按产品查询已上传文件的哈希，用于判断本地文件是否已上传。

        Args:
            product_ids: 非空产品 ID 或名称数组。
            file_type: valuation_report、paper_trading 或 trade。
        Returns:
            服务端原始数组，每项含 product_id 与 hash_list；三类都会为请求到的产品
            返回条目，hash_list 为空数组表示该类型没有已上传哈希；只有估值报告类型
            会排除非估值报告数据源产品。
        """
        if file_type not in {"valuation_report", "paper_trading", "trade"}:
            raise HarnessError("invalid_argument", "file_type 必须为 valuation_report、paper_trading 或 trade")
        # 网关对该路由不校验资源级别，这里只要求产品可见。
        refs = self._batch_refs(product_ids, {"product"})
        return self._client.call("POST", "products:get_uploaded_files_hash", json={
            "product_ids": [ref.id for ref in refs], "file_type": file_type,
        })

    def set_closing_entry(self, resource: str, closing_date: str) -> Any:
        """设置产品封账日；只更新字段，不触发重算。

        Args:
            resource: 产品唯一 ID 或名称。
            closing_date: YYYY-MM-DD；不得晚于今天、早于产品起始日或晚于到期日。
        Returns:
            空响应，客户端得到 None。
        """
        return self._client.call(
            "PUT", self._path(resource, {"product"}) + "/closing_entry",
            json={"closing_date": closing_date},
        )

    def clear_closing_entry(self, resource: str) -> Any:
        """解除产品封账，并从产品起始日提交一次重算。

        Args:
            resource: 产品唯一 ID 或名称。
        Returns:
            空响应，客户端得到 None；提交重算不表示估值已完成。
        """
        return self._client.call("DELETE", self._path(resource, {"product"}) + "/closing_entry")

    def create_example(self) -> Any:
        """创建一个范例产品，并等待异步任务结束。

        Returns:
            服务端任务终态 JSON，含 status、progress 与 data；任务失败抛 HarnessError。
        """
        return self._client.call("GET", "products:create_example")


class ProductGroups(_Resource):
    """产品组自身的配置与重算，不向成员广播写入操作。"""

    def list(self) -> Any:
        """列出当前用户可访问的产品组；返回含 product_groups 的对象。"""
        return {"product_groups": [
            dict(ref.data) for ref in self._client.resource_catalog() if ref.type == "product_group"
        ]}

    def get(self, resource: str) -> Any:
        """读取产品组配置。

        Args:
            resource: 产品组唯一 ID 或名称。
        Returns:
            服务端产品组 JSON，包含成员、权重和日期配置。
        """
        return self._client.call("GET", self._path(resource, {"product_group"}))

    def create(self, data: dict[str, Any]) -> Any:
        """创建产品组，服务端校验成员权限并在配置有效时提交组重算。

        Args:
            data: 产品组 JSON；必含 name、report_name、product_ids、benchmark、
                description、label、start_date、trading_start_date；成员使用产品 ID。
        Returns:
            原始 product_group_id 等结果。
        """
        return self._client.call("POST", "product_groups", json=data)

    def update(self, resource: str, data: dict[str, Any]) -> Any:
        """修改产品组；成员变化会重算权限，计算配置变化可能触发组重算。

        Args:
            resource: 产品组唯一 ID 或名称。
            data: 需修改字段；product_weights 为空时须同时提供 product_ids。
        Returns:
            服务端原始 effect_count 等结果。
        """
        return self._client.call("PATCH", self._path(resource, {"product_group"}), json=data)

    def delete(self, resource: str) -> Any:
        """删除产品组及其权限，不删除成员产品。

        Args:
            resource: 产品组唯一 ID 或名称。
        Returns:
            服务端原始 effect_count 等结果。
        """
        return self._client.call("DELETE", self._path(resource, {"product_group"}))

    def recompute(self, resource: str) -> Any:
        """从组起始日提交产品组自身重算，不逐个重算成员。

        Args:
            resource: 产品组唯一 ID 或名称。
        Returns:
            原始 submit_recompute_count；提交成功不表示计算完成。
        """
        ref = self._client.resolve(resource, {"product_group"})
        return self._client.call("POST", "product_groups:recompute", json={"product_group_ids": [ref.id]})
