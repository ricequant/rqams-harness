"""标签：调用方私有的组织信息，用于给产品与产品组分组标注。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _text


class Tags(_Resource):
    """标签的查询、创建更新与删除操作。"""

    def list(self) -> Any:
        """列出当前用户与工作空间的标签及其绑定的产品、产品组。

        Returns:
            服务端原始标签数组；标签与绑定关系都只属于调用方本人，Harness 不再过滤。
        """
        return self._client.call("GET", "product_tags")

    def upsert(self, tags: list[dict[str, Any]]) -> Any:
        """批量创建或更新标签，并整体替换其产品、产品组绑定。

        Args:
            tags: 非空标签数组；元素可含 tag_id（更新）、name、description、
                product_ids、product_group_ids。省略 tag_id 表示按名称创建。
                产品与产品组绑定必须是 ID；服务端逐项处理，单项失败不影响其余项。
        Returns:
            服务端原始响应，含 effect_count 与逐项 detail；存在失败项时抛
            partial_failure 并携带 detail，不重复提交成功的项。
        """
        _nonempty(tags, "tags")
        for tag in tags:
            if not isinstance(tag, dict):
                raise HarnessError("invalid_argument", "tags 的元素必须为对象")
        result = self._client.call("POST", "product_tags", json=tags)
        failed = [row for row in result.get("detail", []) if isinstance(row, dict) and row.get("success") is False]
        if failed:
            raise HarnessError(
                "partial_failure", "部分标签未处理成功；请按 detail 修正后仅重试失败项",
                details={"results": result, "failed": failed},
            )
        return result

    def delete(self, tag_ids: list[str]) -> Any:
        """批量删除标签及其绑定关系。

        Args:
            tag_ids: 非空标签 ID 数组；请求体为裸数组，不接受对象包装。
        Returns:
            服务端原始响应，含 effect_count；不存在的 ID 不计入删除数。
        """
        _nonempty(tag_ids, "tag_ids")
        for tag_id in tag_ids:
            _text(tag_id, "tag_ids")
        return self._client.call("DELETE", "product_tags", json=tag_ids)
