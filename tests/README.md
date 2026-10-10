# tests 目录：客户端契约测试

`pytest tests` 只测一件事：**`rqamsh` 客户端的契约**——请求发到哪个端点、参数怎么映射、返回与错误怎么原样交回。当前 225 项，全部用进程内脚本化 HTTP 服务端跑，不连真实 AMS、不需要凭据。

**不在范围内的两类**（详见[必要边界](../docs/index.md#必要边界)）：

- **第三方能力**：企业微信、邮件、办公套件等外部系统。不做对接封装、不写测试，需要时由 Agent 查对端官方文档自行实现。
- **Agent 侧加工**：排序、区间差分、加权、渲染（Markdown/DOCX/PNG）、多产品合并、调度与推送。属调用方职责。

金律：`Agent 自身能力 + 第三方能力 + rqamsh 业务数据管理能力 = 满足用户需求`——本目录只保证等号左边第三项。

## 怎么跑

```console
python -m pip install -e .
python -m pytest tests -q
```

146 个公开操作全部有调用式契约测试（请求形状 + 返回/错误）；夹具里的响应结构取自真机证据（证据留本地，不随仓库提交）。用例文件按业务块划分（`test_products.py`、`test_balances.py`、`test_analytics.py`、`test_permissions.py`、`test_workspaces.py`、`test_trades.py` …，共 21 个文件），`test_client.py` 提供共用的 `service` fixture：它启动一个真实的 `ThreadingHTTPServer`，测试把期望响应序列塞进去，客户端按真实 HTTP 走一遍，断言**实际发出的请求**（method / path / body / headers）与返回或异常。因此它验证的是客户端不偷改语义，不验证服务端算得对不对。

## 本机联调：注入管理员给的令牌

本项目的连接约定是「由管理员提供已认证入口」，不为客户端代办登录、也不接收账号密码（见 [`docs/connection.md`](../docs/connection.md)）。在真实 AMS 上做只读/写入探测时，把管理员给的令牌（当前部署是名为 `sid` 的登录会话 cookie）注入 `Client`：

```python
from rqamsh import Client

URI = "https://<ams-host>:<port>"
with Client(base_url=URI, workspace_id="<工作空间 ID>", cookies={"sid": "<令牌>"}) as client:
    print(client.products.list()[:1])                  # 身份由注入的令牌决定
```

CLI 同样支持令牌注入：`rqamsh --base-url <url> --cookie sid=<值> workspaces list`（`--cookie` 可重复，也可用 `RQAMSH_COOKIE`，多个以分号分隔）；`--workspace-id` 可以省略，省略时只能列举或切换空间，拿到目标 id 后由后续命令带上 `--workspace-id <id>`。

- 令牌的取得方式与有效期由 AMS 平台决定；过期后重新取得，客户端不代办登录、也不会替你续期。
- `workspace_id` 可以省略：省略时只有 workspaces list/use 可用，业务调用在本地报 `invalid_config`（不发请求）；给错会报 `当前用户未登录` 或读到空列表。
- 目录可见性只看详情能否读到：读不到（403/404）的资源不进目录；客户端不查授权行、不做权限预判，越权由服务端与网关拒绝。
- 凭据只走命令行参数/环境变量，禁止写进脚本、证据 JSON 或提交记录；HTTPS 证书校验保持开启，不要为了避免报错而关闭校验。
- 自签或内网证书环境需要管理员提供可用入口，不要改 `verify`。

## 实测量级（决定超时与重试策略）

以下是在 ST 环境（工作空间 61 个产品）上观测到的值，写下来是为了避免把长耗时误判成故障：

|调用|观测耗时|
|---|---|
|`products.get` / 普通单产品查询|约 11 秒/次（连续 3 次共 33 秒）|
|`analytics.group_indicators`（多成员）|约 47 秒|
|`balances.get`（实时、含持仓）|约 31 秒|
|`analytics.create_attribution` → `attribution` 终态|约 11 秒 + 12 秒|
|`products.list`（61 个产品）|约十几秒|

默认等待是单请求 60 秒 / 总 300 秒 / 间隔 1 秒（[`docs/connection.md`](../docs/connection.md)）；做多产品循环时建议 `timeout` ≥ 120、`wait_timeout` ≥ 600，超时前**先确认原请求结果**再决定是否重发写入。

## rqdatac 直连（市场数据侧）

`RQDATAC2_CONF` / `RQDATAC_CONF` 的值是连接串 `tcp://<user>:<secret>@<host>:<port>`（不是 yaml 路径）；`rqdatac.init()` 无参即生效，两个变量互为冗余。实测可用范围：A 股、期货、港股（港股必须显式 `market='hk'`）、指数与申万行业、**历史逐日风格因子暴露**、停复牌、分红、复权因子、交易日历；**美股未开通**。这是 Agent 侧的外部数据源，不是 `rqamsh` 的操作；文档里引用到的 rqdata 调用见 [`docs/rqdata.md`](../docs/rqdata.md#rqdata-calls)。
