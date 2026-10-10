"""requests 连接在每次底层读取前应用同一个调用截止时间。"""

from contextlib import contextmanager
from contextvars import ContextVar
import io
from time import monotonic

from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

_deadline = ContextVar("rqamsh_request_deadline", default=None)


@contextmanager
def request_deadline(value):
    """将截止时间限制在当前调用上下文，异常也恢复旧值。"""
    token = _deadline.set(value)
    try:
        yield
    finally:
        _deadline.reset(token)


class _DeadlineReader(io.RawIOBase):
    """约束每次recv，防止服务器持续慢速发送绕过read timeout。"""

    def __init__(self, raw, sock, deadline):
        """保存原始SocketIO和当前请求截止时间。"""
        self._raw, self._socket, self._deadline = raw, sock, deadline
        self._timeout = sock.gettimeout()

    def readable(self):
        """支持HTTP响应的缓冲读取。"""
        return True

    def readinto(self, buffer):
        """每次实际socket读取均重新计算剩余总时限。"""
        if self._deadline is not None:
            remaining = self._deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("AMS 请求总等待超时")
            self._socket.settimeout(min(self._timeout, remaining) if self._timeout else remaining)
        return self._raw.readinto(buffer)

    def close(self):
        """释放文件引用，连接socket仍由urllib3池管理。"""
        self._raw.close()
        super().close()


class _DeadlineSocket:
    """委托socket行为，仅替换HTTP使用的makefile读取器。"""

    def __init__(self, sock):
        """保存已建立的普通或TLS socket。"""
        self._socket = sock

    def __getattr__(self, name):
        """其余socket行为原样委托，包括关闭和设置超时。"""
        return getattr(self._socket, name)

    def sendall(self, data, *args, **kwargs):
        """建连后与每段上传前重算剩余时限，防止沿用过期timeout。"""
        deadline = _deadline.get()
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("AMS 上传总等待超时")
            timeout = self._socket.gettimeout()
            self._socket.settimeout(min(timeout, remaining) if timeout else remaining)
        return self._socket.sendall(data, *args, **kwargs)

    def makefile(self, mode="r", buffering=None, *args, **kwargs):
        """给HTTPResponse的二进制读取增加总时限约束。"""
        if mode != "rb":
            return self._socket.makefile(mode, buffering if buffering is not None else -1, *args, **kwargs)
        raw = self._socket.makefile("rb", buffering=0)
        return io.BufferedReader(_DeadlineReader(raw, self._socket, _deadline.get()))


class _HTTPConnection(HTTPConnection):
    """创建带截止时间读取器的HTTP连接。"""

    def connect(self):
        """连接建立后封装socket，保持urllib3连接池协议。"""
        super().connect()
        self.sock = _DeadlineSocket(self.sock)


class _HTTPSConnection(HTTPSConnection):
    """保持TLS验证，握手后约束HTTP响应读取。"""

    def connect(self):
        """使用urllib3原有证书校验，随后封装TLS socket。"""
        super().connect()
        self.sock = _DeadlineSocket(self.sock)


class _HTTPPool(HTTPConnectionPool):
    """使用限定时间的HTTP连接类。"""

    ConnectionCls = _HTTPConnection


class _HTTPSPool(HTTPSConnectionPool):
    """使用限定时间的HTTPS连接类。"""

    ConnectionCls = _HTTPSConnection


class DeadlineAdapter(HTTPAdapter):
    """独立池映射，不修改urllib3进程全局配置。"""

    def init_poolmanager(self, *args, **kwargs):
        """为本适配器配置HTTP和HTTPS连接池。"""
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _HTTPPool, "https": _HTTPSPool}
