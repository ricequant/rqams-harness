"""产品估值报告管理与文件导入导出。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _segment


class ValuationReports(_Resource):
    """产品估值报告管理，结构化数据与文件导入统一使用 upload。"""

    def list(self, resource: str, *, start_date: str | None = None, end_date: str | None = None) -> Any:
        """列出产品已导入估值报告元数据。

        Args:
            resource: 产品唯一 ID 或名称。
            start_date: YYYY-MM-DD；省略使用产品起始日，并受交易起始日限制。
            end_date: YYYY-MM-DD；省略为今日。
        Returns:
            原始列表，每项含 date、file_name、valuation_report_id、source。
        """
        return self._client.call("GET", self._path(resource, {"product"}) + "/valuation_reports", params={
            "start_date": start_date, "end_date": end_date,
        })

    def missing_dates(self, resource: str) -> Any:
        """列出产品自起始日（受交易起始日限制）到最近结算日之间缺失估值表的交易日。

        Args:
            resource: 产品唯一 ID 或名称。
        Returns:
            服务端原始 YYYY-MM-DD 数组；由集合差集生成，不保证按日期升序。
        """
        return self._client.call(
            "GET", self._path(resource, {"product"}) + "/valuation_reports:missing_dates",
        )

    def upload(
        self, resource: str, data: dict[str, Any] | None = None, *, file_path: str | None = None,
        replace_dates: list[str] | None = None, is_overwrite: bool = False, source: str = "open_api",
    ) -> Any:
        """上传一个结构化估值报告或一个估值文件，二者互斥。

        Args:
            resource: 产品唯一 ID 或名称，须支持估值报告数据源。
            data: 报告 JSON，必含 date、total_equity、units、unit_net_value、positions。
            file_path: 本地估值文件路径，与 data 互斥。
            replace_dates: 允许覆盖已有报告的 YYYY-MM-DD 数组。
            is_overwrite: 是否无条件允许覆盖同日报告，默认 false。
            source: 报告来源枚举，默认 open_api。
        Returns:
            原始 err_msg、confirmation_id、effect_count、valuation_report_id、date、
            is_modified；非空 err_msg 抛部分失败异常，完整结果保留。
        """
        if (data is None) == (file_path is None):
            raise HarnessError("invalid_argument", "data 与 file_path 必须且只能提供一个")
        path = self._path(resource, {"product"}) + "/valuation_reports"
        options: dict[str, Any] = {
            "is_overwrite": "true" if is_overwrite else "false", "source": source,
        }
        if replace_dates is not None:
            options["replace_dates"] = replace_dates
        if data is not None:
            result = self._client.call("POST", path, json={**options, "valuation_report": data})
        else:
            result = self._client.call("POST", path, data=options, file_path=file_path)
        self._client.partial_failure(result)
        return result

    def delete(self, resource: str, dates: list[str]) -> Any:
        """按日期删除估值报告、元数据和自动覆盖余额，并触发必要重算。

        Args:
            resource: 产品唯一 ID 或名称。
            dates: 非空 YYYY-MM-DD 数组，不是估值报告 ID。
        Returns:
            服务端原始 effect_count；删除不可撤销。
        """
        _nonempty(dates, "dates")
        return self._client.call(
            "POST", self._path(resource, {"product"}) + "/valuation_reports:batch_delete", json={"dates": dates},
        )

    def download(self, resource: str, valuation_report_id: str, output: str) -> Any:
        """下载指定估值报告的源文件。

        Args:
            resource: 归属产品唯一 ID 或名称。
            valuation_report_id: list 返回的估值报告 ID。
            output: 必填本地输出文件路径。
        Returns:
            客户端下载元数据；不依服务端文件名选择本地路径。
        """
        path = self._path(resource, {"product"}) + "/valuation_reports"
        requested = _segment(valuation_report_id)
        reports = self._client.call("GET", path)
        matched = next((item for item in reports if str(item.get("valuation_report_id")) == requested), None)
        if matched is None:
            raise HarnessError("resource_not_found", "估值报告不存在或不属于目标产品", status=404)
        identifier = _segment(str(matched["valuation_report_id"]))
        return self._client.call("GET", path + f"/{identifier}/src_file", download=output)
