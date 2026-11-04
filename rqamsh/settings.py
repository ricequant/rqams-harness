"""本地设置：保存 Bearer 令牌、最后使用的空间与部署地址。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .errors import HarnessError

SETTINGS_FILENAME = "rqamsh_settings.json"
SETTINGS_VERSION = 1
_WORKSPACE_CHARS = set("0123456789abcdefABCDEF")
_WRAPPING_WHITESPACE = " \t\r\n\v\f"


def settings_path() -> Path:
    """返回设置文件路径：默认用户目录，可用 RQAMSH_SETTINGS 覆盖。"""
    override = os.environ.get("RQAMSH_SETTINGS")
    return Path(override).expanduser() if override else Path.home() / SETTINGS_FILENAME


def _path(path=None) -> Path:
    """规范化设置文件路径。"""
    return Path(path).expanduser() if path is not None else settings_path()


def _token(value: Any) -> str:
    """校验并清理令牌；错误信息不包含令牌内容。"""
    if not isinstance(value, str) or not value.strip(_WRAPPING_WHITESPACE):
        raise HarnessError("invalid_config", "设置文件中的 token 必须为非空字符串")
    token = value.strip(_WRAPPING_WHITESPACE)
    if any(char in token for char in "\r\n"):
        raise HarnessError("invalid_config", "设置文件中的 token 不能包含换行")
    return token


def _workspace(value: Any) -> str:
    """校验工作空间为 24 位十六进制 ID，并统一为小写。"""
    if not isinstance(value, str) or len(value) != 24 or any(char not in _WORKSPACE_CHARS for char in value):
        raise HarnessError("invalid_config", "设置文件中的 workspace_id 必须为 24 位十六进制 ID")
    return value.lower()


def _base_url(value: Any) -> str:
    """校验设置中的部署地址为非空字符串；格式由 Client 建连时继续校验。"""
    if not isinstance(value, str) or not value.strip(_WRAPPING_WHITESPACE):
        raise HarnessError("invalid_config", "设置文件中的 base_url 必须为非空字符串")
    return value.strip(_WRAPPING_WHITESPACE)


def load_settings(path=None) -> dict[str, Any]:
    """读取设置文件；文件不存在返回空映射，损坏或字段非法时报错。"""
    target = _path(path)
    try:
        text = target.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise HarnessError("invalid_config", f"读取设置文件失败：{target}（{exc}）") from exc
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HarnessError("invalid_config", f"设置文件不是合法 JSON：{target}") from exc
    if not isinstance(data, dict):
        raise HarnessError("invalid_config", f"设置文件必须是 JSON 对象：{target}")
    result: dict[str, Any] = {}
    if "token" in data:
        result["token"] = _token(data["token"])
    if "workspace_id" in data:
        result["workspace_id"] = _workspace(data["workspace_id"])
    if "base_url" in data:
        result["base_url"] = _base_url(data["base_url"])
    return result


def _write(target: Path, data: dict[str, Any]) -> Path:
    """原子写入权限受限的设置文件，避免留下半截 JSON。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".rqamsh-settings-", suffix=".tmp", dir=target.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            # Windows 不保证 POSIX 权限；保留默认权限，不因 chmod 失败阻断保存。
            pass
        os.replace(temporary_path, target)
    finally:
        if temporary_path.exists():
            temporary_path.unlink(missing_ok=True)
    return target


def save_settings(token: str, workspace_id: str | None = None, base_url: str | None = None, *, path=None) -> Path:
    """保存令牌、最后空间和部署地址；不把令牌写入日志或错误信息。"""
    data = {"version": SETTINGS_VERSION, "token": _token(token)}
    if workspace_id is not None:
        data["workspace_id"] = _workspace(workspace_id)
    if base_url is not None:
        data["base_url"] = _base_url(base_url)
    return _write(_path(path), data)


def remember_workspace(workspace_id: str, *, path=None) -> Path | None:
    """更新已有设置文件的最后空间；没有设置文件时不凭空创建令牌文件。"""
    target = _path(path)
    data = load_settings(target)
    if not data.get("token"):
        return None
    data["workspace_id"] = _workspace(workspace_id)
    data["version"] = SETTINGS_VERSION
    return _write(target, data)
