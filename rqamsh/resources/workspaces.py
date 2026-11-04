"""工作空间：读取用户的成员空间，并为后续 AMS 请求明确选择目标。"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from ._base import _Resource, _text


class Workspaces(_Resource):
    """用户级 PAT 的成员工作空间；选择空间不增加业务权限。"""

    def list(self) -> Any:
        """读取当前 PAT 用户的全部成员空间，不要求或改变当前空间。

        Returns:
            服务端原始 ``{"data": [...]}``；记录包含 id、name 及实际返回的成员资料。
            空列表表示用户没有成员空间，不代表凭据无效或具备 AMS 权益。
        """
        payload = self._client.call(
            "GET", "v1/workspaces", base=self._client.user_base,
            select_workspace=False, headers={"X-AMS-Workspace": None},
        )
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise HarnessError("invalid_response", "工作空间响应缺少成员数组", details={"response": payload})
        seen = set()
        for row in rows:
            identifier = row.get("id") if isinstance(row, dict) else None
            if (not isinstance(identifier, str) or len(identifier) != 24
                    or any(char not in "0123456789abcdef" for char in identifier)
                    or identifier in seen):
                raise HarnessError("invalid_response", "成员工作空间缺少合法且唯一的 id", details={"response": payload})
            seen.add(identifier)
        return payload

    def use(self, workspace: str) -> Any:
        """按成员空间 ID 选择后续业务请求的目标；失败时不改变当前客户端。

        Args:
            workspace: 当前 PAT 用户所属工作空间的精确 ID，不按名称匹配。

        Returns:
            实际命中的成员空间记录；AMS 权益和资源权限仍由业务请求独立验证。
        """
        target = _text(workspace, "workspace")
        record = next((row for row in self.list()["data"] if row["id"] == target), None)
        if record is None:
            raise HarnessError(
                "resource_not_found", "工作空间不存在或当前用户不是该空间成员",
                status=404, details={"workspace": target},
            )
        self._client.use_workspace(record["id"])
        return record
