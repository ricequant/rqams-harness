"""本地设置：保存 Bearer 令牌、最后使用的空间与部署地址。"""

from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import tempfile
from time import monotonic, sleep
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


def _normalized_base_url(value):
    """规范化部署 API 根地址，用于请求和保存身份的部署绑定比较。"""
    if not isinstance(value, str):
        raise HarnessError("invalid_config", "base_url 必须为 HTTP(S) 地址字符串")
    try:
        parsed = urlsplit(value.strip(_WRAPPING_WHITESPACE))
        port = parsed.port
    except ValueError as exc:
        raise HarnessError("invalid_config", "base_url 必须为合法 HTTP(S) 地址") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.query or parsed.fragment:
        raise HarnessError("invalid_config", "base_url 必须为不带身份、查询和片段的 HTTP(S) 地址")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != default_port:
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/rqams/v2"):
        path += "/api/rqams/v2"
    return urlunsplit((parsed.scheme, host, path, "", ""))


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


@contextmanager
def _settings_lock(target: Path, *, deadline: float | None = None):
    """同一路径的登录保存与空间更新共用进程锁；关闭描述符时释放。"""
    target = target.parent.resolve() / target.name
    lock = target.with_name(target.name + ".lock")
    target.parent.mkdir(parents=True, exist_ok=True)
    # 保留锁文件，防止等待者和新写入者锁住不同文件。
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _acquire_settings_lock(fd, deadline)
        yield target
    finally:
        os.close(fd)


def _acquire_settings_lock(fd: int, deadline: float | None) -> None:
    """仅在锁忙时续等，登录到期后结束，其他文件错误原样上报。"""
    while True:
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError("等待设置文件锁超时")
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if deadline is not None else 0)
                fcntl.flock(fd, flags)
            return
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            sleep(0.05 if deadline is None else max(0, min(0.05, deadline - monotonic())))


def _save_locked(target: Path, token: str, workspace_id: str | None, base_url: str | None) -> Path:
    """在持有设置文件锁时保存登录结果。"""
    data = {"version": SETTINGS_VERSION, "token": _token(token)}
    if workspace_id is not None:
        data["workspace_id"] = _workspace(workspace_id)
    if base_url is not None:
        data["base_url"] = _base_url(base_url)
    return _write(target, data)


def save_settings(token: str, workspace_id: str | None = None, base_url: str | None = None, *, path=None) -> Path:
    """保存令牌、最后空间和部署地址；不把令牌写入日志或错误信息。"""
    with _settings_lock(_path(path)) as target:
        return _save_locked(target, token, workspace_id, base_url)


def remember_workspace(workspace_id: str, *, token: str, base_url: str, path=None) -> Path | None:
    """仅为仍匹配客户端读取时令牌与部署的设置更新最后空间。"""
    selected = _workspace(workspace_id)
    with _settings_lock(_path(path)) as target:
        data = load_settings(target)
        if data.get("token") != token:
            return None
        try:
            same_deployment = _normalized_base_url(data.get("base_url")) == base_url
        except HarnessError:
            return None
        if not same_deployment:
            return None
        if data.get("workspace_id") == selected:
            return target
        data["workspace_id"] = selected
        data["version"] = SETTINGS_VERSION
        return _write(target, data)
