"""验证本地设置文件、令牌持久化、默认成员空间与登录页行为。"""

import itertools
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import pytest

from rqamsh import auth as auth_module
from rqamsh.auth import login
from rqamsh.client import Client
from rqamsh.errors import HarnessError
from rqamsh.settings import load_settings, remember_workspace, save_settings, settings_path

WORKSPACE = "0123456789abcdef01234567"
OTHER_WORKSPACE = "fedcba987654321001234567"
VALID_TOKEN = "valid-token"
BASE_URL = "https://private.example.com"
# 上游错误里可能混入内部地址或诊断标记：页面和返回结构都不得回显。
UPSTREAM_SECRET = "upstream-diagnostic-mark"
UPSTREAM_URL = "http://10.255.255.1/internal/trace"


def _read(request):
    """发送请求并返回 (状态码, 文本, 响应头)；HTTP 错误按响应返回，不抛异常。"""
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8"), response.headers
    except HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8"), exc.headers
        finally:
            exc.close()


def _submit(url, body):
    """向登录页提交原始表单字节，返回 (状态码, 文本, 响应头)。"""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return _read(Request(url, data=body, method="POST", headers=headers))


def _fetch(url):
    """读取登录页，返回 (状态码, 文本, 响应头)。"""
    return _read(Request(url))


def _declared_status(url, content_length):
    """只发请求头声明正文长度，返回响应状态码；用于验证不读正文的超限拒绝。"""
    parsed = urlsplit(url)
    with socket.create_connection((parsed.hostname, parsed.port), timeout=5) as stream:
        head = (
            f"POST {parsed.path} HTTP/1.0\r\nHost: {parsed.hostname}\r\n"
            f"Content-Type: application/x-www-form-urlencoded\r\nContent-Length: {content_length}\r\n\r\n"
        )
        stream.sendall(head.encode())
        return int(stream.recv(64).split(b" ")[1])


def _raw_login_post(url, fields):
    """用原始 TCP 连接提交表单，返回未关闭的 socket 供测试制造断连。"""
    parsed = urlsplit(url)
    stream = socket.create_connection((parsed.hostname, parsed.port), timeout=5)
    body = urlencode(fields).encode()
    head = (
        f"POST {parsed.path} HTTP/1.0\r\nHost: {parsed.hostname}\r\n"
        f"Content-Type: application/x-www-form-urlencoded\r\nContent-Length: {len(body)}\r\n\r\n"
    )
    stream.sendall(head.encode() + body)
    return stream


def _reset(stream):
    """用 SO_LINGER(1,0) 关闭连接，让对端在下次写入时收到 TCP RST。"""
    linger = struct.pack("hh" if sys.platform == "win32" else "ii", 1, 0)
    stream.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    stream.close()


def client_factory(resolve):
    """构造登录用客户端工厂；每次成员列表查询都交给 resolve 决定结果。

    Args:
        resolve: 接收本次令牌、返回成员空间记录数组（或抛 HarnessError）的回调，可阻塞。

    Returns:
        客户端类；``created`` 记录创建的实例，``listed`` 记录每次返回的成员快照。
    """
    created = []
    listed = []

    class Members:
        """成员空间列表访问器：调用 resolve 并记录结果。"""

        def __init__(self, token):
            """记录本次查询使用的令牌。"""
            self.token = token

        def list(self):
            """返回本次成员快照的副本。"""
            rows = resolve(self.token)
            listed.append(rows)
            return {"data": [dict(row) for row in rows]}

    class StubClient:
        """登录页测试客户端：把成员查询委托给 resolve。"""

        def __init__(self, base_url, **kwargs):
            """记录连接参数，便于断言发现请求不携带空间。"""
            self.base_url = base_url
            self.token = kwargs.get("token")
            self.kwargs = kwargs
            created.append(self)

        def __enter__(self):
            """支持上下文管理器。"""
            return self

        def __exit__(self, *args):
            """无需释放资源。"""
            return None

        @property
        def workspaces(self):
            """返回成员空间列表访问器。"""
            return Members(self.token)

    StubClient.created = created
    StubClient.listed = listed
    return StubClient


def member_factory(*snapshots):
    """构造登录用客户端工厂：第 n 次成员列表调用返回第 n 个快照，末个快照可复用。

    Args:
        snapshots: 每项为一次成员空间响应中的 data 数组。

    Returns:
        客户端类；``created`` 记录创建的实例，``listed`` 记录每次返回的成员快照。
    """
    order = itertools.count()

    def resolve(token):
        """返回按调用顺序命中的快照；非预期令牌按带内部诊断的 401 失败。"""
        if token != VALID_TOKEN:
            raise HarnessError("http_error", f"{UPSTREAM_URL} rejected request ({UPSTREAM_SECRET})", status=401)
        index = next(order)
        return snapshots[min(index, len(snapshots) - 1)]

    return client_factory(resolve)


def failing_factory(status):
    """构造成员查询总是以给定状态失败的客户端工厂，错误文案带上游内部诊断。"""

    def resolve(_token):
        """抛出带状态码、内部地址和标记的上游错误。"""
        raise HarnessError("http_error", f"{UPSTREAM_URL} rejected request ({UPSTREAM_SECRET})", status=status)

    return client_factory(resolve)


def gated_save(monkeypatch):
    """替换 auth.save_settings：首次写入前报告并阻塞，制造确定的写入窗口。

    Returns:
        ``claimed`` 表示首次写入已进入临界区，``allow`` 放行该写入，``count`` 记录调用次数。
    """
    claimed, allow = threading.Event(), threading.Event()
    counter = {"calls": 0}
    lock = threading.Lock()
    original = auth_module.save_settings

    def save(token, workspace_id=None, base_url=None, *, path=None):
        """记录调用次数；首次调用在真正写盘前阻塞到测试放行。"""
        with lock:
            counter["calls"] += 1
            first = counter["calls"] == 1
        if first:
            claimed.set()
            assert allow.wait(10), "设置写入未被放行"
        return original(token, workspace_id, base_url, path=path)

    monkeypatch.setattr(auth_module, "save_settings", save)
    return claimed, allow, counter


class LoginRun:
    """在后台运行一次 login()，便于按步骤提交表单并保留最终结果。"""

    def __init__(self, client_factory, settings_path, *, timeout=5, **kwargs):
        """记录登录参数；进入上下文时启动后台线程。"""
        self.client_factory = client_factory
        self.settings_path = Path(settings_path)
        self.timeout = timeout
        self.kwargs = kwargs
        self.url = None
        self.result = {}
        self.error = None
        self._thread = None

    def _open(self, url):
        """记录登录页地址，模拟浏览器已经打开。"""
        self.url = url
        return True

    def __enter__(self):
        """启动登录线程并等待登录页地址。"""

        def run():
            """等待浏览器提交；异常留给测试结束时检查。"""
            try:
                self.result.update(
                    login(
                        BASE_URL,
                        settings_path=self.settings_path,
                        timeout=self.timeout,
                        open_browser=self._open,
                        client_factory=self.client_factory,
                        **self.kwargs,
                    )
                )
            except Exception as exc:  # 失败用例需要读到具体 HarnessError，不能静默丢弃
                self.error = exc

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 5
        while self.url is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert self.url is not None, "登录页未在等待时间内打开"
        return self

    def post(self, fields):
        """向登录页提交表单，返回 (状态码, 页面文本)。"""
        status, page, _ = _submit(self.url, urlencode(fields).encode())
        return status, page

    def post_async(self, fields):
        """在后台提交表单（用于故意阻塞的请求），返回线程与结果容器。"""
        holder = {}

        def submit():
            """提交表单并记录响应；异常留给等待方断言。"""
            try:
                holder["response"] = self.post(fields)
            except Exception as exc:  # 后台线程不静默丢弃异常，交给 joined 断言
                holder["error"] = exc

        thread = threading.Thread(target=submit, daemon=True)
        thread.start()
        return thread, holder

    @staticmethod
    def joined(thread, holder):
        """等待后台提交结束，返回 (状态码, 页面文本)。"""
        thread.join(10)
        assert not thread.is_alive(), "后台表单提交未结束"
        assert "error" not in holder, f"后台提交异常：{holder.get('error')!r}"
        return holder["response"]

    def wait_finished(self, seconds=10):
        """等待后台登录线程结束（用于超时用例），返回是否已结束。"""
        self._thread.join(seconds)
        return not self._thread.is_alive()

    def __exit__(self, *args):
        """等待登录线程结束，避免后台线程悬挂。"""
        self._thread.join(self.timeout + 5)
        assert not self._thread.is_alive(), "登录线程未在等待时间内结束"
        return None


def test_settings_path_defaults_to_home(monkeypatch, tmp_path):
    """未覆盖时设置文件位于用户目录。"""
    monkeypatch.delenv("RQAMSH_SETTINGS", raising=False)
    assert settings_path() == Path.home() / "rqamsh_settings.json"


def test_settings_path_honors_override(monkeypatch, tmp_path):
    """测试或多身份场景可用环境变量指定设置文件。"""
    target = tmp_path / "profile" / "rqamsh_settings.json"
    monkeypatch.setenv("RQAMSH_SETTINGS", str(target))
    assert settings_path() == target


def test_save_and_load_token_workspace_and_base_url(tmp_path):
    """保存后能读回令牌、最后空间和部署地址。"""
    target = tmp_path / "rqamsh_settings.json"
    save_settings("token-value\r\n", WORKSPACE, base_url="https://private.example.com/", path=target)
    data = load_settings(target)
    assert data["token"] == "token-value"
    assert data["workspace_id"] == WORKSPACE
    assert data["base_url"] == "https://private.example.com/"
    assert '"token-value"' in target.read_text(encoding="utf-8")


def test_load_missing_file_returns_empty(tmp_path):
    """首次使用没有设置文件时返回空映射，不抛错。"""
    assert load_settings(tmp_path / "missing.json") == {}


def test_invalid_settings_file_is_reported_without_token(tmp_path):
    """损坏或非法设置文件报 invalid_config，不回显文件内容。"""
    target = tmp_path / "rqamsh_settings.json"
    target.write_text('{"token": "secret"', encoding="utf-8")
    with pytest.raises(HarnessError) as error:
        load_settings(target)
    assert error.value.code == "invalid_config"
    assert "secret" not in str(error.value)


def test_remember_workspace_updates_existing_file_only(tmp_path):
    """切换空间时只更新已有设置；没有设置文件时不会凭空创建令牌文件。"""
    target = tmp_path / "rqamsh_settings.json"
    assert remember_workspace(OTHER_WORKSPACE, path=target) is None
    save_settings("token-value", WORKSPACE, path=target)
    assert remember_workspace(OTHER_WORKSPACE.lower(), path=target) == target
    assert load_settings(target)["workspace_id"] == OTHER_WORKSPACE.lower()
    assert load_settings(target)["token"] == "token-value"


def test_client_loads_saved_token_and_workspace(tmp_path):
    """显式 Client 省略令牌和空间时使用设置文件，并记住后续切换。"""
    target = tmp_path / "rqamsh_settings.json"
    save_settings("saved-token", WORKSPACE, base_url="https://private.example.com", path=target)
    with Client(settings_path=target) as client:
        assert client.base_url == "https://private.example.com/api/rqams/v2"
        assert client.workspace_id == WORKSPACE
        assert client.session.headers["Authorization"] == "Bearer saved-token"
        client.use_workspace(OTHER_WORKSPACE)
    assert load_settings(target)["workspace_id"] == OTHER_WORKSPACE


def test_login_saves_token_and_member_workspace(tmp_path):
    """单成员空间时令牌提交直接保存，页面与返回结构都不回显令牌。"""
    target = tmp_path / "rqamsh_settings.json"
    factory = member_factory([{"id": WORKSPACE, "name": "团队A"}])
    with LoginRun(factory, target) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 200
        assert VALID_TOKEN not in page
        assert WORKSPACE in page
    assert run.error is None
    assert run.result["workspace_id"] == WORKSPACE
    assert run.result["base_url"] == BASE_URL
    assert "token" not in run.result
    data = load_settings(target)
    assert data["token"] == VALID_TOKEN
    assert data["workspace_id"] == WORKSPACE
    assert data["base_url"] == BASE_URL
    # 成员列表请求不携带任何工作空间参数：发现阶段没有默认空间。
    assert factory.created[0].kwargs == {"token": VALID_TOKEN}
    assert len(factory.listed) == 1


def test_login_multi_workspace_saves_first_member_once(tmp_path):
    """多成员空间一次提交即保存服务端原序首项：不排序、不筛选，也不追问用户。"""
    target = tmp_path / "rqamsh_settings.json"
    # 首项故意不是按 ID 排序的最小项：保存身份必须来自服务端返回顺序。
    rows = [{"id": OTHER_WORKSPACE, "name": "团队B"}, {"id": WORKSPACE, "name": "团队A"}]
    factory = member_factory(rows)
    with LoginRun(factory, target) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 200
        assert VALID_TOKEN not in page
        assert OTHER_WORKSPACE in page
        assert load_settings(target)["workspace_id"] == OTHER_WORKSPACE
    assert run.error is None
    assert run.result["workspace_id"] == OTHER_WORKSPACE
    data = load_settings(target)
    assert data["token"] == VALID_TOKEN
    assert data["base_url"] == BASE_URL
    assert len(factory.listed) == 1


def test_login_explicit_workspace_overrides_default(tmp_path):
    """显式给出的成员空间优先于默认首项：即使令牌可访问多个空间也直接保存该空间。"""
    target = tmp_path / "rqamsh_settings.json"
    factory = member_factory([{"id": WORKSPACE, "name": "团队A"}, {"id": OTHER_WORKSPACE, "name": "团队B"}])
    with LoginRun(factory, target, workspace_id=OTHER_WORKSPACE.upper()) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 200
        assert VALID_TOKEN not in page
        assert OTHER_WORKSPACE in page
    assert run.error is None
    assert run.result["workspace_id"] == OTHER_WORKSPACE
    assert load_settings(target)["workspace_id"] == OTHER_WORKSPACE
    assert len(factory.listed) == 1


def test_login_explicit_non_member_workspace_is_rejected(tmp_path):
    """显式空间不在成员列表时报错，既不保存也不改写已保存的默认身份。"""
    target = tmp_path / "rqamsh_settings.json"
    save_settings("saved-token", WORKSPACE, base_url=BASE_URL, path=target)
    factory = member_factory([{"id": WORKSPACE}])
    with LoginRun(factory, target, timeout=1, workspace_id=OTHER_WORKSPACE) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 400
        assert VALID_TOKEN not in page
    assert load_settings(target) == {"token": "saved-token", "workspace_id": WORKSPACE, "base_url": BASE_URL}


def test_login_invalid_token_keeps_saved_settings(tmp_path):
    """令牌校验失败不泄露上游内部诊断，已保存的令牌和空间不被覆盖。"""
    target = tmp_path / "rqamsh_settings.json"
    save_settings("saved-token", WORKSPACE, base_url=BASE_URL, path=target)
    factory = member_factory([{"id": WORKSPACE}])
    with LoginRun(factory, target, timeout=1) as run:
        status, page = run.post({"token": "bad-token-value"})
        assert status == 400
        assert "bad-token-value" not in page
        assert UPSTREAM_SECRET not in page
        assert UPSTREAM_URL not in page
    assert load_settings(target) == {"token": "saved-token", "workspace_id": WORKSPACE, "base_url": BASE_URL}
    assert factory.listed == []


def test_login_without_member_workspace_keeps_saved_settings(tmp_path):
    """令牌没有任何成员空间时报错，不保存身份，也不结束本次登录等待。"""
    target = tmp_path / "rqamsh_settings.json"
    save_settings("saved-token", WORKSPACE, base_url=BASE_URL, path=target)
    factory = member_factory([])
    with LoginRun(factory, target, timeout=1) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 400
        assert VALID_TOKEN not in page
    assert isinstance(run.error, HarnessError)
    assert run.error.code == "auth_timeout"
    assert load_settings(target) == {"token": "saved-token", "workspace_id": WORKSPACE, "base_url": BASE_URL}


def test_login_requires_exactly_one_token_field(tmp_path):
    """表单只接受恰好一个 token 字段：空令牌、缺失或额外字段都 400，且不读成员、不覆盖已保存身份。"""
    target = tmp_path / "rqamsh_settings.json"
    saved = {"token": "saved-token", "workspace_id": WORKSPACE, "base_url": BASE_URL}
    save_settings("saved-token", WORKSPACE, base_url=BASE_URL, path=target)
    factory = member_factory([{"id": OTHER_WORKSPACE}, {"id": WORKSPACE}])
    with LoginRun(factory, target, timeout=1) as run:
        status, page = run.post({"token": ""})
        assert status == 400
        assert load_settings(target) == saved
        status, _ = run.post({"workspace": WORKSPACE})
        assert status == 400
        assert load_settings(target) == saved
        status, page = run.post({"token": VALID_TOKEN, "workspace": WORKSPACE})
        assert status == 400
        assert VALID_TOKEN not in page
        assert load_settings(target) == saved
        # 上述拒绝都发生在读取成员列表之前，最终一次合法提交才保存原序首项。
        assert factory.created == []
        assert factory.listed == []
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 200
        assert WORKSPACE not in page
    assert run.error is None
    assert load_settings(target) == {"token": VALID_TOKEN, "workspace_id": OTHER_WORKSPACE, "base_url": BASE_URL}
    assert len(factory.listed) == 1


def test_login_page_uses_nonce_path_and_no_store(tmp_path):
    """登录页只在随机 nonce 路径提供，并保留 no-store、CSP 与 referrer 策略。"""
    target = tmp_path / "rqamsh_settings.json"
    factory = member_factory([{"id": WORKSPACE}])
    with LoginRun(factory, target, timeout=1) as run:
        status, page, headers = _fetch(run.url)
        assert status == 200
        assert VALID_TOKEN not in page
        assert headers["Cache-Control"] == "no-store"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'none'" in headers["Content-Security-Policy"]
        nonce = urlsplit(run.url).path.strip("/")
        assert len(nonce) >= 24
        status, _, _ = _fetch(f"http://127.0.0.1:{urlsplit(run.url).port}/wrong/")
        assert status == 404


def test_login_rejects_oversized_body(tmp_path):
    """声明超过 16KiB 的表单直接被拒绝，不读取正文也不构造客户端。"""
    target = tmp_path / "rqamsh_settings.json"
    factory = member_factory([{"id": WORKSPACE}])
    with LoginRun(factory, target, timeout=1) as run:
        assert _declared_status(run.url, 16 * 1024 + 1) == 413
        assert not target.exists()
    assert factory.created == []


def test_login_reports_settings_write_failure(tmp_path):
    """设置写入失败时报 settings_error，而不是假装登录成功。"""
    target = tmp_path / "rqamsh_settings.json"
    target.mkdir()
    factory = member_factory([{"id": WORKSPACE}])
    with LoginRun(factory, target) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 500
        assert VALID_TOKEN not in page
    assert isinstance(run.error, HarnessError)
    assert run.error.code == "settings_error"
    assert VALID_TOKEN not in str(run.error)


def test_login_completed_save_blocks_late_stale_token_write(tmp_path, monkeypatch):
    """新令牌已进入保存临界区后，迟到的旧令牌查询不得再写设置。"""
    target = tmp_path / "rqamsh_settings.json"
    started, release = threading.Event(), threading.Event()
    claimed, allow, writes = gated_save(monkeypatch)

    def resolve(token):
        """旧令牌阻塞到放行；另一个令牌返回别的成员空间。"""
        if token == "slow-token":
            started.set()
            assert release.wait(10), "旧令牌成员查询未被放行"
            return [{"id": WORKSPACE, "name": "团队A"}]
        return [{"id": OTHER_WORKSPACE, "name": "团队B"}]

    factory = client_factory(resolve)
    with LoginRun(factory, target) as run:
        slow = run.post_async({"token": "slow-token"})
        assert started.wait(10), "旧令牌成员查询未开始"
        fast = run.post_async({"token": VALID_TOKEN})
        assert claimed.wait(10), "新令牌未进入保存临界区"
        release.set()
        allow.set()
        status, page = LoginRun.joined(*slow)
        assert status == 409
        assert "slow-token" not in page
        status, _ = LoginRun.joined(*fast)
        assert status == 200
    assert writes["calls"] == 1
    assert load_settings(target) == {"token": VALID_TOKEN, "workspace_id": OTHER_WORKSPACE, "base_url": BASE_URL}


def test_login_stale_single_save_cannot_beat_newer_token(tmp_path):
    """旧令牌的默认保存不得在新令牌已写入后覆盖它，即使旧查询先算完。"""
    target = tmp_path / "rqamsh_settings.json"
    started, release = threading.Event(), threading.Event()

    def resolve(token):
        """旧令牌阻塞后返回自己的工作空间；新令牌立即返回另一个空间。"""
        if token == "slow-token":
            started.set()
            assert release.wait(10), "旧令牌成员查询未被放行"
            return [{"id": WORKSPACE}]
        return [{"id": OTHER_WORKSPACE}]

    factory = client_factory(resolve)
    expected = {"token": VALID_TOKEN, "workspace_id": OTHER_WORKSPACE, "base_url": BASE_URL}
    with LoginRun(factory, target) as run:
        slow = run.post_async({"token": "slow-token"})
        assert started.wait(10), "旧令牌成员查询未开始"
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 200
        assert OTHER_WORKSPACE in page
        assert load_settings(target) == expected
        release.set()
        status, _ = LoginRun.joined(*slow)
        assert status == 409
        assert load_settings(target) == expected
    assert load_settings(target) == expected


def test_login_empty_token_invalidates_inflight_submission(tmp_path):
    """空令牌提交也推进代次：被阻塞的旧令牌不得再保存，重新输入令牌仍可完成登录。"""
    target = tmp_path / "rqamsh_settings.json"
    started, release = threading.Event(), threading.Event()

    def resolve(token):
        """旧令牌阻塞到放行后返回单空间；有效令牌立即返回两个空间。"""
        if token == "slow-token":
            started.set()
            assert release.wait(10), "旧令牌成员查询未被放行"
            return [{"id": WORKSPACE}]
        return [{"id": OTHER_WORKSPACE}, {"id": WORKSPACE}]

    factory = client_factory(resolve)
    with LoginRun(factory, target) as run:
        slow = run.post_async({"token": "slow-token"})
        assert started.wait(10), "旧令牌成员查询未开始"
        status, page = run.post({"token": ""})
        assert status == 400
        assert not target.exists()
        release.set()
        status, _ = LoginRun.joined(*slow)
        assert status == 409
        assert not target.exists()
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 200
        assert OTHER_WORKSPACE in page
    assert run.error is None
    assert load_settings(target) == {"token": VALID_TOKEN, "workspace_id": OTHER_WORKSPACE, "base_url": BASE_URL}


def test_login_duplicate_token_submissions_write_once(tmp_path, monkeypatch):
    """同一令牌的两次并发提交只有一次写盘，另一个回 409。"""
    target = tmp_path / "rqamsh_settings.json"
    barrier = threading.Barrier(2)
    claimed, allow, writes = gated_save(monkeypatch)

    def resolve(_token):
        """两次成员查询在屏障处汇合后一起返回同一个成员空间。"""
        barrier.wait(10)
        return [{"id": WORKSPACE}]

    factory = client_factory(resolve)
    with LoginRun(factory, target) as run:
        first = run.post_async({"token": VALID_TOKEN})
        second = run.post_async({"token": VALID_TOKEN})
        assert claimed.wait(10), "没有提交进入保存临界区"
        allow.set()
        statuses = sorted([LoginRun.joined(*first)[0], LoginRun.joined(*second)[0]])
    assert statuses == [200, 409]
    assert writes["calls"] == 1
    assert load_settings(target) == {"token": VALID_TOKEN, "workspace_id": WORKSPACE, "base_url": BASE_URL}


def test_login_late_submission_after_timeout_never_writes(tmp_path):
    """登录超时后仍未返回的成员查询不能保存任何身份。"""
    target = tmp_path / "rqamsh_settings.json"
    started, release = threading.Event(), threading.Event()

    def resolve(_token):
        """成员查询阻塞到放行后才返回。"""
        started.set()
        assert release.wait(10), "成员查询未被放行"
        return [{"id": WORKSPACE, "name": "团队A"}]

    factory = client_factory(resolve)
    with LoginRun(factory, target, timeout=1) as run:
        inflight = run.post_async({"token": VALID_TOKEN})
        assert started.wait(10), "成员查询未开始"
        assert run.wait_finished(10), "登录未在超时后结束"
        assert isinstance(run.error, HarnessError)
        assert run.error.code == "auth_timeout"
        assert not target.exists()
        release.set()
        status, _ = LoginRun.joined(*inflight)
        assert status == 409
        assert not target.exists()
    assert not target.exists()


def test_login_timed_out_query_cannot_save_first_member(tmp_path):
    """登录超时后返回的多空间查询不得再保存首项，也不得改写设置。"""
    target = tmp_path / "rqamsh_settings.json"
    started, release = threading.Event(), threading.Event()

    def resolve(_token):
        """成员查询阻塞到放行，然后返回两个空间即未显式指定时的默认保存路径。"""
        started.set()
        assert release.wait(10), "成员查询未被放行"
        return [{"id": WORKSPACE}, {"id": OTHER_WORKSPACE}]

    factory = client_factory(resolve)
    with LoginRun(factory, target, timeout=1) as run:
        inflight = run.post_async({"token": VALID_TOKEN})
        assert started.wait(10), "成员查询未开始"
        assert run.wait_finished(10), "登录未在超时后结束"
        assert isinstance(run.error, HarnessError)
        assert run.error.code == "auth_timeout"
        release.set()
        status, page = LoginRun.joined(*inflight)
        assert status == 409
        assert VALID_TOKEN not in page
        # 超时后的结果不发布到页面：既不回显令牌，也不暴露候选空间。
        assert WORKSPACE not in page
    assert not target.exists()


def test_login_failure_page_hides_upstream_diagnostics(tmp_path):
    """非 401 的校验失败同样不泄露上游地址与诊断标记，也不保存身份。"""
    target = tmp_path / "rqamsh_settings.json"
    factory = failing_factory(503)
    with LoginRun(factory, target, timeout=1) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 400
        assert UPSTREAM_SECRET not in page
        assert UPSTREAM_URL not in page
    assert not target.exists()


def test_login_settings_value_error_reports_settings_error(tmp_path):
    """设置路径非法（NUL）时保存抛 ValueError，登录必须报 settings_error 而不是超时。"""
    target = tmp_path / "bad\x00name.json"
    factory = member_factory([{"id": WORKSPACE}])
    with LoginRun(factory, target, timeout=1) as run:
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 500
        assert VALID_TOKEN not in page
    assert isinstance(run.error, HarnessError)
    assert run.error.code == "settings_error"
    assert VALID_TOKEN not in str(run.error)


def test_login_connection_reset_on_stale_request_keeps_new_identity(tmp_path):
    """旧请求连接被复位只是该连接结束，不得终结登录或改动已保存的新身份。"""
    target = tmp_path / "rqamsh_settings.json"
    started, release = threading.Event(), threading.Event()

    def resolve(token):
        """旧令牌阻塞到放行后返回自己的空间顺序；新令牌立即返回两个空间。"""
        if token == "old-token":
            started.set()
            assert release.wait(10), "旧令牌成员查询未被放行"
            return [{"id": OTHER_WORKSPACE}, {"id": WORKSPACE}]
        return [{"id": WORKSPACE}, {"id": OTHER_WORKSPACE}]

    factory = client_factory(resolve)
    expected = {"token": VALID_TOKEN, "workspace_id": WORKSPACE, "base_url": BASE_URL}
    with LoginRun(factory, target) as run:
        stale = _raw_login_post(run.url, {"token": "old-token"})
        assert started.wait(10), "旧令牌成员查询未开始"
        _reset(stale)
        status, page = run.post({"token": VALID_TOKEN})
        assert status == 200
        assert WORKSPACE in page
        assert load_settings(target) == expected
        release.set()
        # 旧请求回写 409 时撞上 RST；这段时间登录不得被旧连接的异常终结。
        for _ in range(100):
            if run.error is not None:
                break
            time.sleep(0.01)
        assert run.error is None
    assert run.result["workspace_id"] == WORKSPACE
    assert load_settings(target) == expected
