"""资源权限：读取产品与产品组的授权明细，并授权、调整级别、撤销与批量授权。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _nonempty, _text

# 权限级别枚举；admin 由服务端拒绝，客户端不代做该判断。
_PERMISSION_LEVELS = frozenset(
    {"forbidden", "read_net_value", "read_position", "read_import_data", "write", "admin"}
)
_ENTRY_KEYS = frozenset({"user_id", "permission", "permission_id"})


def _entries(entries: list[dict[str, Any]], *, allow_permission_id: bool = True) -> list[dict[str, Any]]:
    """校验授权项数组的形状：不复制服务端业务校验，只拒绝缺失与多余字段。"""
    _nonempty(entries, "entries")
    for entry in entries:
        if not isinstance(entry, dict):
            raise HarnessError("invalid_argument", "entries 的元素必须为对象")
        unknown = sorted(set(entry) - _ENTRY_KEYS)
        if unknown:
            raise HarnessError("invalid_argument", f"entries 的元素不接受字段：{unknown}")
        user_id = entry.get("user_id")
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise HarnessError("invalid_argument", "entries[].user_id 必须为正整数用户 ID")
        if entry.get("permission") not in _PERMISSION_LEVELS:
            raise HarnessError(
                "invalid_argument",
                "entries[].permission 必须为 forbidden、read_net_value、read_position、"
                "read_import_data、write、admin 之一",
            )
        if "permission_id" in entry:
            if not allow_permission_id:
                raise HarnessError("invalid_argument", "批量授权不接受 entries[].permission_id")
            _text(entry["permission_id"], "entries[].permission_id")
    return entries


class Permissions(_Resource):
    """产品与产品组的授权明细读写。

    授权行由服务端维护：读取返回逐用户一行，写操作按服务端规则该校验
    （被授权人须在本工作空间、`admin` 级别不能通过本接口分享、被授予级别不得
    高于操作者在该资源上的级别），不符合的部分逐项返回原因。客户端只做参数
    形状校验，不比较级别，也不在本地拦截。
    """

    def list(self, resource: str) -> Any:
        """读取单个产品或产品组的授权明细。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
        Returns:
            服务端原始授权行数组；元素含 resource_id、resource_type、
            permission、user_id、workspace_id、shared_by 与 id，无授权行时为空数组。
        """
        return self._client.call("GET", self._path(resource, {"product", "product_group"}) + "/permissions")

    def grant(self, resource: str, entries: list[dict[str, Any]]) -> Any:
        """为单个产品或产品组新增或调整授权。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            entries: 非空授权项数组；元素含 user_id、permission，可含 permission_id
                以改动既有授权行的级别；省略 permission_id 时按用户新增或覆盖。
        Returns:
            服务端原始响应，含 effect_count 与逐项 error_messages；有失败项时抛
            partial_failure 并携带完整结果，已成功的授权不回滚。
        """
        payload = _entries(entries)
        return self._client.partial_failure(
            self._client.call(
                "POST", self._path(resource, {"product", "product_group"}) + "/permissions", json=payload,
            ),
            "部分授权未生效；请按逐项原因修正后只重试失败项，已生效的授权不回滚",
        )

    def grant_many(self, resources: list[str], entries: list[dict[str, Any]]) -> Any:
        """对多个同类型资源批量授权。

        Args:
            resources: 非空产品或产品组 ID 或名称数组；必须是同一类型，产品与产品组
                不能混在一批。
            entries: 非空授权项数组；元素含 user_id 与 permission，不接受 permission_id。
        Returns:
            服务端原始响应，含 effect_count 与逐项 error_messages；有失败项时抛
            partial_failure 并携带完整结果。
        """
        payload = _entries(entries, allow_permission_id=False)
        refs = self._batch_refs(resources, {"product", "product_group"})
        kinds = {ref.type for ref in refs}
        if len(kinds) > 1:
            raise HarnessError("invalid_argument", "批量授权的资源必须为同一类型，产品或产品组不混批")
        collection = "products" if kinds == {"product"} else "product_groups"
        return self._client.partial_failure(
            self._client.call(
                "POST", f"{collection}/permissions",
                json={
                    "resource_ids": [ref.id for ref in refs],
                    "perm_info_list": payload,
                },
            ),
            "部分授权未生效；请按逐项原因修正后只重试失败项，已生效的授权不回滚",
        )

    def revoke(self, resource: str, permission_ids: list[str]) -> Any:
        """撤销单个产品或产品组上指定的授权行。

        Args:
            resource: 产品或产品组唯一 ID 或名称。
            permission_ids: 非空授权行 ID 数组，取自 list 返回元素的 id；请求体为裸数组。
        Returns:
            服务端原始响应，含 effect_count；授权行不属于该资源时由服务端拒绝。
        """
        _nonempty(permission_ids, "permission_ids")
        for permission_id in permission_ids:
            _text(permission_id, "permission_ids")
        return self._client.call(
            "DELETE", self._path(resource, {"product", "product_group"}) + "/permissions",
            json=permission_ids,
        )
