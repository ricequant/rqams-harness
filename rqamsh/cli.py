"""从 Python 功能块签名构建 CLI；不复制业务实现。"""

import argparse
import inspect
import json
import os
from pathlib import Path
import sys
import types
import typing

from .client import Client
from .errors import HarnessError
from .resources import RESOURCE_CLASSES


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


def _env_cookies():
    """从 RQAMSH_COOKIE 读取初始 cookie 列表（多个以分号分隔）；空值返回 None。"""
    raw = os.environ.get("RQAMSH_COOKIE")
    items = [item for item in (raw or "").split(";") if item.strip()]
    return items or None


def _cookies(items):
    """把 --cookie/RQAMSH_COOKIE 的 name=value 列表解析为 cookie 映射；非法项抛 HarnessError。"""
    jar = {}
    for item in items or []:
        name, separator, value = item.partition("=")
        if not separator or not name.strip():
            raise HarnessError("invalid_config", f"cookie 必须形如 name=value：{item}")
        jar[name.strip()] = value.strip()
    return jar or None


def _parser():
    """注册连接配置、离线发现及每个资源的公开业务方法。"""
    parser = JsonArgumentParser(prog="rqamsh", description="面向 Agent 的 AMS API；连接配置也可由 RQAMSH_* 环境变量提供")
    parser.add_argument("--base-url", default=os.environ.get("RQAMSH_BASE_URL"), help="AMS 服务地址；也可用 RQAMSH_BASE_URL")
    parser.add_argument("--workspace-id", default=os.environ.get("RQAMSH_WORKSPACE_ID"), help="初始工作空间 ID；省略时先用 workspaces list 列举可见空间、workspaces use 选定，也可用 RQAMSH_WORKSPACE_ID")
    parser.add_argument("--cookie", action="append", default=_env_cookies(), metavar="NAME=VALUE", help="令牌（当前形态是会话 cookie）；可重复，也可用 RQAMSH_COOKIE（多个以分号分隔）")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--wait-timeout", type=float, default=300)
    parser.add_argument("--poll-interval", type=float, default=1)
    blocks = parser.add_subparsers(dest="block", required=True)
    blocks.add_parser("schema", help="离线输出全部 API 签名、参数与说明")
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


def main(argv=None):
    """运行命令并返回退出码；所有失败 JSON 写入 stderr。"""
    try:
        namespace = _parser().parse_args(argv)
        if namespace.block == "schema":
            _emit(schema(), sys.stdout)
            return 0
        if namespace.base_url is None:
            raise HarnessError("invalid_config", "必须显式配置 base_url（参数或 RQAMSH_BASE_URL 环境变量）")
        cookies = _cookies(namespace.cookie)
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
        with Client(namespace.base_url, namespace.workspace_id, cookies=cookies, timeout=namespace.timeout, wait_timeout=namespace.wait_timeout, poll_interval=namespace.poll_interval) as client:
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
