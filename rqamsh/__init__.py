"""面向 Agent 的 AMS Python API，与 rqamsh 命令共用实现。"""

from .client import Client, DEFAULT_BASE_URL
from .errors import HarnessError

__version__ = "0.0.1"
_client = None


def init(base_url=None, workspace_id=None, *, token=None, timeout=60, wait_timeout=300, poll_interval=1):
    """设置模块默认客户端并关闭旧连接；显式 Client 可并存不同身份。

    地址和令牌省略时读取用户目录的 rqamsh_settings.json（可用 RQAMSH_SETTINGS 覆盖），
    包括最后选择的空间；没有设置文件时先运行 ``rqamsh auth``。workspace_id 省略时沿用该
    最后空间；没有可沿用的保存空间时，首次业务调用使用服务端成员列表首项（原序首项，
    不排序、不按权益筛选），没有任何成员空间则报错，首项缺权益由服务端拒绝而不换后项。
    私有化部署必须显式传入 base_url 或把地址保存进设置文件。身份来自 Bearer 令牌，
    与显式 Client 行为一致。
    """
    global _client
    new_client = Client(
        base_url, workspace_id, token=token,
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


def login(base_url=None, workspace_id=None, *, settings_path=None, timeout=300, open_browser=None):
    """在本机启动浏览器登录并把令牌写入设置文件。

    与 CLI 的 ``rqamsh auth`` 共用实现；校验令牌后读取成员空间：显式 workspace_id 必须
    命中成员列表，没有显式空间时直接保存成员列表首项；提交令牌即完成登录，不再二次选择
    空间。返回设置路径与所选工作空间，不返回令牌。
    """
    from .auth import login as browser_login

    return browser_login(
        base_url or DEFAULT_BASE_URL,
        workspace_id=workspace_id,
        settings_path=settings_path,
        timeout=timeout,
        open_browser=open_browser,
    )


def __getattr__(name):
    """在调用时查找默认客户端功能块，避免持有旧身份的静态代理。"""
    if name.startswith("_"):
        raise AttributeError(name)
    from .resources import RESOURCE_CLASSES
    if name not in RESOURCE_CLASSES:
        raise AttributeError(name)
    if _client is None:
        raise HarnessError("not_initialized", "先运行 rqamsh auth，或调用 rqamsh.init(token=...)，或使用显式 Client")
    return getattr(_client, name)
