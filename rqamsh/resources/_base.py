"""资源路径、资源类型校验与输入校验的公共实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import HarnessError

if TYPE_CHECKING:
    from ..client import Client, ResourceRef


def _segment(value: str) -> str:
    """验证记录 ID 为单个相对路径段，拒绝路径和查询注入。"""
    if not isinstance(value, str) or not value or value in {".", ".."} or any(
        char in value for char in "/\\?#%"
    ):
        raise HarnessError("invalid_argument", "记录 ID 必须是非空的单个路径段")
    return value


def _nonempty(values: list[Any], name: str) -> None:
    """拒绝空批次，避免服务端空集合计算异常或隐式扩大范围。"""
    if not isinstance(values, list) or not values:
        raise HarnessError("invalid_argument", f"{name} 必须是非空 JSON 数组")


def _text(value: str, name: str) -> str:
    """校验必填文本参数为非空字符串，拒绝缺省与空白。"""
    if not isinstance(value, str) or not value.strip():
        raise HarnessError("invalid_argument", f"{name} 必须为非空字符串")
    return value


def _selector(value: Any, name: str) -> Any:
    """校验逗号串选择器为非空字符串或非空字符串数组，数组由客户端序列化为逗号串。"""
    if isinstance(value, str):
        return _text(value, name)
    _nonempty(value, name)
    for item in value:
        _text(item, name)
    return value


class _Resource:
    """保存显式客户端，不持有全局身份或资源缓存。"""

    def __init__(self, client: Client) -> None:
        """初始化资源分组；client 为携带用户和工作空间身份的客户端。"""
        self._client = client

    def _path(self, resource: str, allowed: set[str]) -> str:
        """解析资源并校验目标类型，返回服务器相对资源路径。"""
        return self._client.resolve(resource, allowed).path

    def _batch_refs(self, resources: list[str], allowed: set[str]) -> list[ResourceRef]:
        """对单个目录快照解析多个资源并校验类型。"""
        return self._client.resolve_many(resources, allowed)
