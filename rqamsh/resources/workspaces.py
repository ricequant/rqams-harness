"""工作空间：列举当前身份可见的数据分区，并在会话内切换。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _text


class Workspaces(_Resource):
    """工作空间的列举与切换。

    Args:
        client: 已连接的业务客户端；切换只改变该客户端后续请求的数据分区。
    """

    def list(self) -> Any:
        """列举当前身份可见的工作空间。

        Returns:
            用户接口原始响应，形如 ``{"data": [记录, ...]}``；记录含 id、name、
            admin、capacity、ctime、description、tags、users。未登录时抛
            not_logged_in，不把「未登录」当作空列表。
        """
        payload = self._client.call("GET", "v1/workspaces", base=self._client.user_url)
        if isinstance(payload, dict) and payload.get("code"):
            raise HarnessError(
                "not_logged_in",
                f"用户接口未返回工作空间：{payload.get('message', '未登录')}",
                status=401,
                details={"response": payload},
            )
        return payload

    def use(self, workspace: str) -> Any:
        """把客户端切到指定工作空间，返回被选中的工作空间记录。

        Args:
            workspace: 工作空间 ID 或名称；按 ID 或名称精确匹配，歧义时拒绝切换。

        Returns:
            被选中的工作空间记录；此后该客户端的业务请求都发往该工作空间。
        """
        target = _text(workspace, "workspace")
        payload = self.list()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise HarnessError("invalid_response", "用户接口未返回工作空间数组", details={"response": payload})
        matches = [row for row in rows if isinstance(row, dict) and target in {row.get("id"), row.get("name")}]
        if not matches:
            raise HarnessError("resource_not_found", "工作空间不存在或不属于当前身份", status=404, details={"workspace": target})
        if len(matches) > 1:
            raise HarnessError(
                "ambiguous_resource",
                "工作空间存在歧义，请使用 ID",
                status=400,
                details={"workspace": target, "candidates": [row.get("id") for row in matches]},
            )
        self._client.use_workspace(str(matches[0]["id"]))
        return matches[0]
