"""资产单元配置及所属持仓单管理。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _segment


class AssetUnits(_Resource):
    """产品所属资产单元；读取复用真实批量目录，写入使用归属产品路径。"""

    def list(self, resource: str | None = None) -> list[dict[str, Any]]:
        """列出可访问资产单元，不调用不存在的产品内资产单元 GET。

        Args:
            resource: 可选归属产品唯一 ID 或名称；省略列出当前工作空间可访问资产单元。
        Returns:
            目录中原始资产单元对象组成的列表，包含 id、product_id、symbol 等字段。
        """
        product_id = self._client.resolve(resource, {"product"}).id if resource is not None else None
        return [
            dict(ref.data) for ref in self._client.resource_catalog()
            if ref.type == "asset_unit" and (product_id is None or ref.parent_id == product_id)
        ]

    def get(self, resource: str) -> dict[str, Any]:
        """从可访问目录读取单个资产单元，不虚构单条 GET 端点。

        Args:
            resource: 资产单元唯一 ID 或名称（symbol），不是归属产品名称。
        Returns:
            目录中的完整资产单元 JSON，含归属产品字段。
        """
        return dict(self._client.resolve(resource, {"asset_unit"}).data)

    def create(
        self, resource: str, order_book_id: str, symbol: str, start_date: str, bound_position: bool,
        *, asset_class: str = "asset_unit",
    ) -> Any:
        """在产品下创建资产单元并由服务端提交重算。

        Args:
            resource: 归属产品唯一 ID 或名称，须支持交易流水数据源。
            order_book_id: 资产单元代码。
            symbol: 资产单元名称。
            start_date: 起始日期 YYYY-MM-DD。
            bound_position: 是否绑定持仓，必须显式指定布尔值。
            asset_class: 资产类别，默认 asset_unit。
        Returns:
            原始 insert_id、effect_count。
        """
        return self._client.call("POST", self._path(resource, {"product"}) + "/asset_units", json={
            "order_book_id": order_book_id, "symbol": symbol, "start_date": start_date,
            "bound_position": bound_position, "asset_class": asset_class,
        })

    def update(self, resource: str, data: dict[str, Any]) -> Any:
        """修改资产单元，自动解析归属产品并提交重算。

        Args:
            resource: 资产单元唯一 ID 或名称，不是产品名称。
            data: 修改字段 JSON，可含 asset_class、symbol、order_book_id、start_date、bound_position。
        Returns:
            服务端原始 effect_count。
        """
        return self._client.call("PATCH", self._path(resource, {"asset_unit"}), json=data)


class PositionsStatements(_Resource):
    """资产单元持仓单文件导入及管理。"""

    def list(
        self, resource: str, *, start_date: str | None = None, end_date: str | None = None, is_detail: bool = False,
    ) -> Any:
        """读取资产单元持仓单，自动解析归属产品。

        Args:
            resource: 资产单元唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略不限制起始日期。
            end_date: YYYY-MM-DD；省略不限制截止日期。
            is_detail: 是否返回 positions；默认 false，false 时不发送该参数。
        Returns:
            原始列表，含 positions_statement_id、date、file_name，以及可选 positions。
        """
        params: dict[str, Any] = {"start_date": start_date, "end_date": end_date}
        if is_detail:
            params["is_detail"] = True
        return self._client.call("GET", self._path(resource, {"asset_unit"}) + "/positions_statement", params=params)

    def upload(
        self, resource: str, file_path: str, *, broker: str = "ricequant",
        prefer_fill_fund_exchange_suffix: bool = True,
    ) -> Any:
        """上传一个资产单元持仓单文件并等待旧版任务协议完成。

        Args:
            resource: 资产单元唯一 ID 或名称；归属产品自动解析。
            file_path: 本地持仓单文件路径。
            broker: 持仓单通道类型，默认 ricequant。
            prefer_fill_fund_exchange_suffix: 默认 true 自动补基金场内后缀；false 使用 v2。
        Returns:
            原始任务终态 JSON；失败或逐项错误抛异常，不自动重传文件。
        """
        suffix = ":upload_positions_statement" if prefer_fill_fund_exchange_suffix else ":upload_positions_statement_v2"
        result = self._client.call(
            "POST", self._path(resource, {"asset_unit"}) + suffix, data={"broker": broker},
            file_path=file_path, legacy_task=True,
        )
        self._client.partial_failure(result)
        return result

    def delete(self, resource: str, positions_statement_ids: list[str]) -> Any:
        """按记录 ID 删除资产单元持仓单，归属产品自动解析。

        Args:
            resource: 资产单元唯一 ID 或名称。
            positions_statement_ids: 非空持仓单记录 ID 数组。
        Returns:
            服务端原始 effect_count；删除不可撤销。
        """
        _nonempty(positions_statement_ids, "positions_statement_ids")
        return self._client.call(
            "DELETE", self._path(resource, {"asset_unit"}) + "/positions_statement", json=positions_statement_ids,
        )

    def download(self, resource: str, positions_statement_id: str, output: str) -> Any:
        """下载一份资产单元持仓单的源文件。

        Args:
            resource: 资产单元唯一 ID 或名称。
            positions_statement_id: list 返回的持仓单 ID，必须属于该资产单元。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在。
        Returns:
            客户端下载元数据；不依服务端文件名选择本地路径。
        """
        requested = _segment(positions_statement_id)
        path = self._path(resource, {"asset_unit"}) + "/positions_statement"
        records = self._client.call("GET", path)
        matched = next((item for item in records if str(item.get("positions_statement_id")) == requested), None)
        if matched is None:
            raise HarnessError("resource_not_found", "持仓单不存在或不属于目标资产单元", status=404)
        return self._client.call("GET", f"{path}/{requested}/src_file", download=output)

    def latest(self) -> Any:
        """读取工作空间内各产品资产单元的最新持仓单状态。

        Returns:
            服务端原始数组，每项含 product_id、product_name 与 positions_statement_items；
            items 含 asset_unit_name、asset_unit_id 与 update_time（未上传时为「未上传持仓单」）；
            只保留当前身份在目录中可见的资产单元，无剩余项的产品被丢弃。
        """
        rows = self._client.call("GET", "products/asset_units/positions_statement:get_latest")
        visible = {ref.id for ref in self._client.resource_catalog() if ref.type == "asset_unit"}
        result = []
        for row in rows:
            items = [item for item in row.get("positions_statement_items", []) if str(item.get("asset_unit_id")) in visible]
            if items:
                result.append({**row, "positions_statement_items": items})
        return result
