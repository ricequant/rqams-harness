"""本机浏览器登录：校验 Bearer 令牌、选定成员空间并写入本地设置。"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .client import Client, DEFAULT_BASE_URL
from .errors import HarnessError
from .settings import save_settings, settings_path as default_settings_path

_MAX_BODY = 16 * 1024
_WORKSPACE_CHARS = set("0123456789abcdefABCDEF")


def _workspace_id(value: Any) -> str:
    """校验服务端返回的空间 ID，统一为小写并拒绝其他形态。"""
    if not isinstance(value, str) or len(value) != 24 or any(char not in _WORKSPACE_CHARS for char in value):
        raise HarnessError("invalid_response", "工作空间记录缺少合法的 24 位十六进制 ID")
    return value.lower()


def _failure_text(exc: HarnessError) -> str:
    """把成员校验失败映射为稳定类别。

    不回显上游 message：它可能包含内部地址、诊断标记或凭据，页面只给可操作的类别。
    """
    if exc.status == 401:
        return "令牌无效（HTTP 401），请检查令牌是否正确"
    return "令牌校验失败：无法读取当前用户的工作空间列表"


def _page(title: str, body: str) -> str:
    """生成不依赖外部资源的登录页。"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 560px; margin: 8vh auto; padding: 0 20px; color: #202124; }}
h1 {{ font-size: 22px; }}
code {{ background: #f1f3f4; padding: 2px 5px; border-radius: 4px; }}
input[type=password] {{ box-sizing: border-box; width: 100%; padding: 9px; margin: 8px 0 14px; font: inherit; }}
label {{ display: block; margin: 6px 0; }}
button {{ padding: 9px 16px; font: inherit; cursor: pointer; }}
.note {{ color: #5f6368; font-size: 13px; }}
.error {{ color: #b3261e; }}
</style>
</head>
<body>
{body}
<p class="note">令牌只在本机使用，不会显示在页面、地址或日志里。</p>
</body>
</html>
"""


def _form(action: str, base_url: str, error: str | None = None) -> str:
    """渲染令牌输入表单；错误信息不回显令牌。"""
    alert = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return _page(
        "连接 AMS",
        f"""<h1>连接 AMS</h1>
<p>服务地址：<code>{html.escape(base_url)}</code></p>
{alert}
<form method="post" action="{html.escape(action, quote=True)}">
<label for="token">Bearer 令牌</label>
<input id="token" name="token" type="password" autocomplete="off" autofocus required>
<button type="submit">保存并连接</button>
</form>""",
    )


def _success(workspace_id: str) -> str:
    """渲染成功页。"""
    return _page(
        "连接成功",
        f"""<h1>连接成功</h1>
<p>令牌和默认工作空间已写入本机设置。</p>
<p>工作空间：<code>{html.escape(workspace_id)}</code></p>
<p>可以关闭此页面，回到 Agent 继续。</p>""",
    )


def login(
    base_url: str = DEFAULT_BASE_URL,
    *,
    workspace_id: str | None = None,
    settings_path: str | Path | None = None,
    timeout: float = 300,
    open_browser: Callable[[str], bool] | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """启动仅监听本机的登录页，校验令牌、选定成员空间并保存设置。

    令牌提交后立即用成员空间列表校验身份并保存：显式给出的空间必须是成员；没有显式空间时
    默认保存服务端返回顺序的首项，不排序也不筛除，此后不会改选其他空间；没有成员空间则报错。
    只有保存成功才算完成登录；令牌、超时、无成员空间、保存失败都不覆盖既有设置。
    并发与迟到提交按提交代次与终态判断：登录结束、已有一次写入或已被更新的令牌取代后，其余
    请求只得到 409，不再写入设置。校验失败页只显示稳定类别，不回显上游诊断。

    Args:
        base_url: AMS 部署地址；默认线上地址。
        workspace_id: 可选的空间 ID；必须属于当前令牌的成员空间，否则登录失败。
        settings_path: 设置文件路径；省略时使用用户目录。
        timeout: 等待浏览器提交的秒数。
        open_browser: 打开浏览器的回调；测试可注入，默认使用 webbrowser。
        client_factory: 令牌校验客户端工厂；测试可注入。

    Returns:
        ``{"settings": ..., "base_url": ..., "workspace_id": ..., "opened": ...}``，不含令牌。

    Raises:
        HarnessError: 浏览器等待超时、令牌无效、空间不属于令牌、设置写入失败或页面处理异常。
    """
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise HarnessError("invalid_config", "登录等待时间必须为正数")
    if workspace_id is not None and (
        not isinstance(workspace_id, str)
        or len(workspace_id) != 24
        or any(char not in _WORKSPACE_CHARS for char in workspace_id)
    ):
        raise HarnessError("invalid_config", "workspace_id 必须为 24 位十六进制 ID")
    explicit = workspace_id.lower() if workspace_id is not None else None
    target = Path(settings_path).expanduser() if settings_path is not None else default_settings_path()
    nonce = secrets.token_urlsafe(24)
    path = f"/{nonce}/"
    # finalized 表示本次登录的终态已定（写入或内部失败）；所有写入路径在同一把锁里先判断它。
    state: dict[str, Any] = {
        "done": threading.Event(),
        "lock": threading.Lock(),
        "closed": False,
        "finalized": False,
        "generation": 0,
        "workspace_id": None,
        "error": None,
    }
    factory = client_factory or Client

    class Handler(BaseHTTPRequestHandler):
        """仅接受携带本次 nonce 路径的 GET/POST。"""

        def _send(self, status: int, content: str, content_type: str = "text/html; charset=utf-8") -> None:
            """发送无缓存响应。"""
            data = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def _may_commit(self, generation: int | None = None) -> bool:
            """判断本次请求能否推进登录终态；调用方必须持有 ``state["lock"]``。

            登录结束、终态已定或代次已被更新的提交取代时一律不能推进；省略 generation 时
            只做前两项判断（用于请求入口与认领代次）。
            """
            if state["closed"] or state["finalized"]:
                return False
            return generation is None or state["generation"] == generation

        def _read_fields(self) -> dict[str, list[str]] | None:
            """读取表单字段；长度或编码不合法时已回复错误页并返回 None。"""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send(400, _form(path, base_url, "请求长度不合法"))
                return None
            if length <= 0 or length > _MAX_BODY:
                self._send(413 if length > _MAX_BODY else 400, _form(path, base_url, "请求长度不合法"))
                return None
            try:
                return parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            except (UnicodeDecodeError, ValueError):
                self._send(400, _form(path, base_url, "表单内容不合法"))
                return None

        def _member_ids(self, token: str) -> list[str]:
            """读取成员空间并一次校验结构、ID 与唯一性，返回服务端原序的规范化 ID。"""
            with factory(base_url, token=token) as client:
                payload = client.workspaces.list()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise HarnessError("invalid_response", "工作空间列表返回结构不合法")
            identifiers = [
                _workspace_id(row.get("id") if isinstance(row, dict) else None) for row in rows
            ]
            if len(set(identifiers)) != len(identifiers):
                raise HarnessError("invalid_response", "工作空间列表包含重复 ID")
            return identifiers

        def _save(self, token: str, selected: str, generation: int) -> None:
            """保存令牌与选定空间；认领终态与写盘在同一临界区，晚到或过期的提交一律拒绝。"""
            with state["lock"]:
                allowed = self._may_commit(generation)
                failure = None
                if allowed:
                    # 先定局再写盘：之后的保存、失败与终态发布都不再改动本次登录。
                    state["finalized"] = True
                    try:
                        save_settings(token, selected, base_url, path=target)
                    except Exception:
                        # 写入方已定局，任何保存异常都安全收敛为 settings_error 并结束登录。
                        failure = HarnessError("settings_error", f"保存设置失败：{target}")
                        state["error"] = failure
                    else:
                        state["workspace_id"] = selected
            if not allowed:
                try:
                    self._send(409, _form(path, base_url, "登录已结束或有更新的令牌提交，请重新运行登录"))
                except OSError:
                    return
                return
            if failure is not None:
                try:
                    self._send(500, _page("保存失败", "<h1>保存失败</h1><p>请检查本机设置文件权限。</p>"))
                finally:
                    state["done"].set()
                return
            try:
                # 设置已经写入，浏览器读取成功页失败也不能把登录报成失败。
                self._send(200, _success(selected))
            finally:
                state["done"].set()

        def _submit_token(self, raw: str) -> None:
            """处理令牌提交：校验成员身份后立即保存显式空间或服务端返回的首项。"""
            token = raw.strip()
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            with state["lock"]:
                # 登录结束或终态已定后不再接受新流程，也不写入任何状态。
                active = self._may_commit()
                if active:
                    # 任何一次提交（含空令牌）都推进代次，让此前在途的请求失效。
                    state["generation"] += 1
                    generation = state["generation"]
                    self._generation = generation
            if not active:
                self._send(409, _form(path, base_url, "登录已结束，请重新运行登录"))
                return
            if not token:
                self._send(400, _form(path, base_url, "请输入令牌"))
                return
            try:
                identifiers = self._member_ids(token)
            except HarnessError as exc:
                self._send(400, _form(path, base_url, _failure_text(exc)))
                return
            if explicit is not None:
                if explicit not in identifiers:
                    self._send(400, _form(path, base_url, "指定的工作空间不属于当前令牌"))
                    return
                self._save(token, explicit, generation)
                return
            if not identifiers:
                self._send(400, _form(path, base_url, "当前令牌没有可用工作空间，无法完成登录"))
                return
            # 未显式指定时保存服务端原序首项：不排序、不筛权益，也不改选其他空间。
            self._save(token, identifiers[0], generation)

        def do_GET(self):
            """显示令牌输入表单；其他路径一律 404。"""
            known = urlsplit(self.path).path in {path, path.rstrip("/")}
            try:
                if known:
                    self._send(200, _form(path, base_url))
                else:
                    self._send(404, "Not Found", "text/plain; charset=utf-8")
            except OSError:
                # 浏览器提前断开时不再回写；页面内容不涉及令牌。
                return

        def do_POST(self):
            """处理令牌提交；任何异常都结束等待，不留悬挂线程。"""
            if urlsplit(self.path).path not in {path, path.rstrip("/")}:
                try:
                    self._send(404, "Not Found", "text/plain; charset=utf-8")
                except OSError:
                    return
                return
            self._generation = None
            try:
                self._handle_post()
            except OSError:
                # 浏览器断连或 TCP 复位只结束这条连接（与 GET 的处理一致），不改变登录状态。
                return
            except Exception as exc:
                with state["lock"]:
                    # 终态只能发布一次；已写入、已结束或旧代次的异常都不覆盖当前流程。
                    terminal = self._may_commit(self._generation)
                    if terminal:
                        state["finalized"] = True
                        state["error"] = HarnessError(
                            "internal_error", f"登录页面处理失败：{type(exc).__name__}"
                        )
                if terminal:
                    state["done"].set()
                try:
                    self._send(500, _page("登录失败", "<h1>登录失败</h1><p>页面处理异常，请重新运行登录。</p>"))
                except OSError:
                    return

        def _handle_post(self):
            """只接受恰好一个令牌字段的表单；任何额外或缺失字段都按非法请求拒绝。"""
            fields = self._read_fields()
            if fields is None:
                return
            if set(fields) != {"token"}:
                self._send(400, _form(path, base_url, "表单参数不合法：只提交令牌"))
                return
            self._submit_token(fields["token"][0])

        def log_message(self, *args):
            """不要记录请求或令牌。"""
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}{path}"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    opened = False
    try:
        if open_browser is None:
            import webbrowser

            open_browser = webbrowser.open
        opened = bool(open_browser(url))
        if not state["done"].wait(timeout):
            raise HarnessError("auth_timeout", "等待浏览器登录超时", details={"url": url})
        if state["error"] is not None:
            raise state["error"]
        if state["workspace_id"] is None:
            raise HarnessError("invalid_response", "登录未取得工作空间")
        return {"settings": str(target), "base_url": base_url, "workspace_id": state["workspace_id"], "opened": opened}
    finally:
        with state["lock"]:
            # 结束登录后拒绝一切迟到写入，也不在内存里保留任何身份状态。
            state["closed"] = True
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
