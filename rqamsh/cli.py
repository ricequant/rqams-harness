"""从 Python 功能块签名构建 CLI；不复制业务实现。"""

import argparse
import inspect
import json
import os
from pathlib import Path
import sys
import types
import typing

from .auth import login
from .client import Client, DEFAULT_BASE_URL
from .errors import HarnessError
from .resources import RESOURCE_CLASSES
from .settings import load_settings, settings_path


class JsonArgumentParser(argparse.ArgumentParser):
    """以结构化错误代替 argparse 的非 JSON 失败输出。"""

    def error(self, message):
        """参数错误交由主入口统一写 stderr。"""
        raise HarnessError("invalid_arguments", message)


def _json_value(value):
    """解析 JSON 字面量、@UTF-8文件或 @- 标准输入。"""
    if value == "@-":
        value = sys.stdin.read()
    elif value.startswith("@"):
        value = Path(value[1:]).read_text(encoding="utf-8-sig")
    return json.loads(value)


def _convert(value, annotation):
    """按方法注解转换参数，并拒绝 JSON 类型不匹配。"""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in {typing.Union, types.UnionType}:
        non_null = [arg for arg in args if arg is not type(None)]
        if len(non_null) == 1:
            return _convert(value, non_null[0])
        if value.lstrip().startswith("[") and any(
            typing.get_origin(arg) is list or arg is list for arg in non_null
        ):
            return _convert(value, list)
        if str in non_null:
            return value
        return _json_value(value)
    expected = origin or annotation
    if expected is bool:
        if value.lower() not in {"true", "false"}:
            raise ValueError("布尔参数必须为 true 或 false")
        return value.lower() == "true"
    if expected in {int, float}:
        return expected(value)
    if expected in {list, dict, tuple} or annotation is typing.Any:
        parsed = _json_value(value)
        if expected in {list, dict} and not isinstance(parsed, expected):
            raise ValueError(f"参数应为 JSON {expected.__name__}")
        return parsed
    return value


def schema():
    """返回离线可发现的功能块、方法、参数及业务说明。"""
    result = {}
    for name, cls in RESOURCE_CLASSES.items():
        methods = {}
        for method_name, method in inspect.getmembers(cls, inspect.isfunction):
            if method_name.startswith("_"):
                continue
            params = {}
            for parameter in inspect.signature(method).parameters.values():
                if parameter.name == "self":
                    continue
                params[parameter.name] = {
                    "type": str(parameter.annotation),
                    "required": parameter.default is inspect.Parameter.empty,
                    "default": None if parameter.default is inspect.Parameter.empty else parameter.default,
                }
            methods[method_name] = {"description": inspect.getdoc(method), "parameters": params}
        result[name] = methods
    return result


def _token(value):
    """读取 --token/RQAMSH_TOKEN；以 @ 开头时从文件读取，去掉首尾空白。"""
    if not value:
        return None
    if value.startswith("@"):
        path = value[1:]
        if not path:
            raise HarnessError("invalid_config", "token 文件路径不能为空：@")
        try:
            return Path(path).read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            raise HarnessError("invalid_config", f"读取 token 文件失败：{path}（{exc}）") from exc
    return value.strip()


def _parser():
    """注册连接配置、离线发现及每个资源的公开业务方法。"""
    parser = JsonArgumentParser(prog="rqamsh", description="面向 Agent 的 AMS API；连接配置也可由 RQAMSH_* 环境变量提供")
    parser.add_argument("--base-url", default=None, help="AMS 服务地址；默认线上 https://www.ricequant.com，私有化部署必须覆盖；也可用 RQAMSH_BASE_URL 或设置文件")
    parser.add_argument("--workspace-id", default=None, help="成员工作空间 ID；省略时沿用设置文件中的最后空间，否则使用成员列表首项；也可用 RQAMSH_WORKSPACE_ID")
    parser.add_argument("--token", default=None, metavar="TOKEN", help="Bearer 令牌；省略时使用设置文件或 RQAMSH_TOKEN，也可用 @文件 从文件读取；直接传字面值会进入 shell 历史和进程命令行，临时调试才用")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--wait-timeout", type=float, default=300)
    parser.add_argument("--poll-interval", type=float, default=1)
    blocks = parser.add_subparsers(dest="block")
    blocks.add_parser("schema", help="离线输出全部 API 签名、参数与说明")
    auth = blocks.add_parser("auth", help="在浏览器中输入令牌并保存到本机设置；未指定空间时保存成员列表首项")
    auth.add_argument("--auth-timeout", type=float, default=300, help="等待浏览器提交令牌的秒数")
    auth.add_argument("--no-browser", action="store_true", help="不自动打开浏览器，只在 stderr 输出登录地址")
    for name, cls in RESOURCE_CLASSES.items():
        block = blocks.add_parser(name.replace("_", "-"), help=inspect.getdoc(cls))
        verbs = block.add_subparsers(dest="verb", required=True)
        for method_name, method in inspect.getmembers(cls, inspect.isfunction):
            if method_name.startswith("_"):
                continue
            description = inspect.getdoc(method)
            command = verbs.add_parser(method_name.replace("_", "-"), help=(description or "").split("\n")[0], description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
            for parameter in inspect.signature(method).parameters.values():
                if parameter.name == "self":
                    continue
                flags = ["--" + parameter.name.replace("_", "-")]
                if parameter.name == "data":
                    flags.append("--input")
                command.add_argument(*flags, required=parameter.default is inspect.Parameter.empty, default=argparse.SUPPRESS, help=f"Python 参数 {parameter.name}，类型 {parameter.annotation}；JSON 支持 @文件 或 @-")
            command.set_defaults(_block=name, _method=method_name)
    return parser


def _emit(value, stream):
    """仅输出严格 JSON，不接受 NaN/Infinity 等非标准数值。"""
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str) + "\n")


def _auto_login_enabled() -> bool:
    """业务命令缺少登录时是否自动打开本机登录；可用 RQAMSH_AUTO_LOGIN=0 关闭。"""
    value = os.environ.get("RQAMSH_AUTO_LOGIN")
    return value is None or value.strip().lower() not in {"0", "false", "no", "off"}


def _has_saved_token() -> bool:
    """安全检查设置文件是否已有令牌；损坏文件视为未登录，交给登录流程修复。"""
    try:
        return bool(load_settings(settings_path()).get("token"))
    except HarnessError:
        return False


def _run_auth(namespace, *, emit: bool = True):
    """运行浏览器登录；业务命令自动登录时不向 stdout 输出额外 JSON。"""
    local_settings = settings_path()
    try:
        saved = load_settings(local_settings)
    except HarnessError:
        # 设置文件损坏时仍允许重新登录覆盖它，避免用户被坏文件锁死。
        saved = {}
    base_url = namespace.base_url or os.environ.get("RQAMSH_BASE_URL") or saved.get("base_url") or DEFAULT_BASE_URL

    def open_browser(url):
        """打开浏览器；无法自动打开时把地址留给用户。"""
        if namespace.no_browser:
            print(f"请在浏览器打开：{url}", file=sys.stderr)
            return False
        import webbrowser

        opened = webbrowser.open(url)
        if not opened:
            print(f"无法自动打开浏览器，请访问：{url}", file=sys.stderr)
        return opened

    result = login(
        base_url,
        workspace_id=namespace.workspace_id or os.environ.get("RQAMSH_WORKSPACE_ID"),
        settings_path=local_settings,
        timeout=namespace.auth_timeout,
        open_browser=open_browser,
    )
    if emit:
        _emit({"status": "ok", "settings": result["settings"], "base_url": result["base_url"], "workspace_id": result["workspace_id"]}, sys.stdout)
    return 0


def main(argv=None):
    """运行命令并返回退出码；所有失败 JSON 写入 stderr。"""
    try:
        namespace = _parser().parse_args(argv)
        if namespace.block is None:
            namespace.no_browser = False
            namespace.auth_timeout = 300
            return _run_auth(namespace)
        if namespace.block == "schema":
            _emit(schema(), sys.stdout)
            return 0
        if namespace.block == "auth":
            return _run_auth(namespace)
        token = _token(namespace.token) if namespace.token is not None else _token(os.environ.get("RQAMSH_TOKEN"))
        workspace = namespace.workspace_id or os.environ.get("RQAMSH_WORKSPACE_ID")
        if token is None and not _has_saved_token() and _auto_login_enabled():
            namespace.auth_timeout = 300
            namespace.no_browser = False
            _run_auth(namespace, emit=False)
        cls = RESOURCE_CLASSES[namespace._block]
        method = getattr(cls, namespace._method)
        hints = typing.get_type_hints(method)
        arguments = {}
        for name, parameter in inspect.signature(method).parameters.items():
            if name != "self" and hasattr(namespace, name):
                value = getattr(namespace, name)
                if name == "data" and namespace._method == "upload" and not value.lstrip().startswith(("@", "[", "{")):
                    value = "@" + value
                arguments[name] = _convert(value, hints.get(name, parameter.annotation))
        base_url = namespace.base_url or os.environ.get("RQAMSH_BASE_URL")
        with Client(base_url, workspace, token=token, settings_path=settings_path(), timeout=namespace.timeout, wait_timeout=namespace.wait_timeout, poll_interval=namespace.poll_interval) as client:
            result = getattr(getattr(client, namespace._block), namespace._method)(**arguments)
        _emit(result, sys.stdout)
        return 0
    except HarnessError as exc:
        _emit(exc.to_dict(), sys.stderr)
        return 1
    except (ValueError, TypeError, OSError) as exc:
        _emit({"error": "invalid_input", "message": str(exc)}, sys.stderr)
        return 2
    except KeyboardInterrupt:
        _emit({"error": "interrupted", "message": "客户端等待已中断；服务端写入或任务未被取消，请勿盲目重放"}, sys.stderr)
        return 130
    except Exception as exc:
        _emit({"error": "client_error", "message": str(exc), "type": type(exc).__name__}, sys.stderr)
        return 1
