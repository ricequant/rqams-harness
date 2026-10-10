"""面向 Agent 的 AMS Python API，与 rqamsh 命令共用实现。"""

from .client import Client
from .errors import HarnessError

__version__ = "0.0.1"
_client = None


def init(base_url, workspace_id=None, *, session=None, cookies=None, timeout=60, wait_timeout=300, poll_interval=1):
    """设置模块默认客户端并关闭旧连接；显式 Client 可并存不同身份。

    身份来自注入的 session/cookies，与显式 Client 行为一致。
    """
    global _client
    new_client = Client(
        base_url, workspace_id, session=session, cookies=cookies,
        timeout=timeout, wait_timeout=wait_timeout, poll_interval=poll_interval,
    )
    if _client is not None:
        _client.close()
    _client = new_client
    return new_client


def close():
    """关闭并清除模块默认客户端。"""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def __getattr__(name):
    """在调用时查找默认客户端功能块，避免持有旧身份的静态代理。"""
    if name.startswith("_"):
        raise AttributeError(name)
    from .resources import RESOURCE_CLASSES
    if name not in RESOURCE_CLASSES:
        raise AttributeError(name)
    if _client is None:
        raise HarnessError("not_initialized", "先调用 rqamsh.init(base_url, workspace_id, cookies=...)，或使用显式 Client")
    return getattr(_client, name)
