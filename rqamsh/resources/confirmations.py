"""导入凭证：流水、托管事件、持仓单与估值表的导入结果追查。"""

from __future__ import annotations

from typing import Any

from ._base import _Resource, _segment


class Confirmations(_Resource):
    """导入凭证：按产品查询导入批次明细，或按来源查询工作空间最新导入状态。"""

    def list(
        self, resource: str, *, asset_unit_id: str | None = None,
        start_date: str | None = None, end_date: str | None = None,
    ) -> Any:
        """列出产品导入凭证。

        Args:
            resource: 产品唯一 ID 或名称。
            asset_unit_id: 可选资产单元 ID，用于只看该单元的导入批次。
            start_date: YYYY-MM-DD；省略不设下界。
            end_date: YYYY-MM-DD；省略不设上界。
        Returns:
            服务端原始对象，含 items 数组与 total；每项含来源、时间与解析/登记条数统计。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/confirmations",
            params={"asset_unit_id": asset_unit_id, "start_date": start_date, "end_date": end_date},
        )

    def get(
        self, resource: str, confirmation_id: str, *,
        status: str = "all", offset: int | None = None, limit: int | None = None,
    ) -> Any:
        """读取一份导入凭证的明细。

        Args:
            resource: 产品唯一 ID 或名称。
            confirmation_id: list 返回的凭证 ID。
            status: all、succeeded 或 failed，默认 all；决定 items 只含全部、成功或失败项。
            offset: 跳过条数；省略由服务端按 0 处理。
            limit: 返回条数上限；省略由服务端按全部处理。
        Returns:
            服务端原始对象，含统计、items 与 src_file 元信息；源文件内容用 download 取得。
        """
        path = self._path(resource, {"product"}) + f"/confirmations/{_segment(confirmation_id)}"
        return self._client.call("GET", path, params={"status": status, "offset": offset, "limit": limit})

    def latest(self, source: str) -> Any:
        """读取工作空间内各产品按来源的最新导入状态。

        Args:
            source: 凭证来源展示名，取 OpenAPI、IntraDayTrades、ValuationForm、EODTrades、
                CustodianEvents、PositionsStatement、PositionsSheet 之一。
        Returns:
            服务端原始数组，每项含 product_id、product_name 与来源对应的账户级或托管级状态；
            只保留当前身份在目录中可见的产品。
        """
        rows = self._client.call("GET", "confirmations", params={"source": source, "filter": "latest"})
        visible = {ref.id for ref in self._client.resource_catalog() if ref.type == "product"}
        return [row for row in rows if row.get("product_id") in visible]

    def download(self, resource: str, confirmation_id: str, output: str) -> Any:
        """下载一份导入凭证的源文件。

        Args:
            resource: 归属产品唯一 ID 或名称。
            confirmation_id: list 返回的凭证 ID，必须属于该产品。
            output: 必填本地输出文件路径，父目录须存在且目标文件不得已存在。
        Returns:
            客户端下载元数据；不依服务端文件名选择本地路径。
        """
        path = self._path(resource, {"product"}) + f"/confirmations/{_segment(confirmation_id)}/src_file"
        return self._client.call("GET", path, download=output)
