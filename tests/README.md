# tests 目录：客户端契约测试

`pytest tests` 只测一件事：**`rqamsh` 客户端的契约**——请求发到哪个端点、参数怎么映射、返回与错误怎么原样交回。全部用例都用进程内脚本化 HTTP 服务端跑，不连真实 AMS、不需要凭据。

**不在范围内的两类**（详见[必要边界](../docs/index.md#必要边界)）：

- **第三方能力**：企业微信、邮件、办公套件等外部系统。不做对接封装、不写测试，需要时由 Agent 查对端官方文档自行实现。
- **Agent 侧加工**：排序、区间差分、加权、渲染（Markdown/DOCX/PNG）、多产品合并、调度与推送。属调用方职责。

金律：`Agent 自身能力 + 第三方能力 + rqamsh 业务数据管理能力 = 满足用户需求`——本目录只保证等号左边第三项。

## 怎么跑

```console
python -m pip install -e .
python -m pytest tests -q
```

测试按业务块覆盖已实现的消费者可见行为与错误边界，不代表当前全部公开操作均有调用覆盖；操作集合以 `rqamsh schema` 为准。重点回归包括部署凭据隔离、地址优先级、目录详情过期、实时/历史分流、批量部分失败及模拟交易逐文件失败。用例文件按业务块划分（如 `test_products.py`、`test_balances.py`、`test_analytics.py`、`test_permissions.py`、`test_workspaces.py`、`test_trades.py`、`test_paper_trading.py`），`test_client.py` 提供共用的 `service` fixture：它启动真实的 `ThreadingHTTPServer`；业务请求按脚本顺序出队，资源目录端点按路径匹配——`catalog_routes(...)` 一次登记三个集合端点与逐项详情，使断言不依赖并发到达顺序。测试验证实际 HTTP 请求和返回/异常，不验证服务端计算，也不能证明真实环境联调或端到端耗时已达标。

## 本机联调：首次网页登录，后续复用身份

本机首次联调由 Agent 主动执行 CLI 只读命令；缺身份时会打开本机登录页，用户在页面填写 key，保存到隔离用户目录的 `rqamsh_settings.json` 后继续原命令。不要把管理员签发 Bearer 令牌与代办账号密码登录混为一谈，也不要仅因工具捕获输出或非 TTY 就禁用浏览器。测试新用户流程时使用独立用户目录与 `RQAMSH_SETTINGS`，不要删除真实配置或卸载现有 Skill；完整首次使用流程见[Agent 使用引导](../docs/guide.md#使用方式用户说业务agent-读文档)。地址优先级见[建立连接](../docs/connection.md#建立连接)，未指定地址时优先沿用保存部署，没有保存地址才回退官方地址。已有身份时直接复用；也可先运行 `rqamsh auth`，或在明确远程、无图形或无人值守的探测脚本中显式注入令牌：

```python
from rqamsh import Client

URI = "https://<ams-host>:<port>"
with Client(base_url=URI, token="<令牌>") as client:
    print(client.products.list()[:1])                  # 身份由注入的令牌决定
```

CLI 支持自动登录，也支持临时覆盖：`rqamsh workspaces list`（首次自动登录）、`rqamsh auth`、`rqamsh --base-url <url> --token @文件 workspaces list`（也可用 `RQAMSH_TOKEN`）；`@文件` 的内容必须就是令牌本身，多键 YAML/密钥库请先取出对应值。不指定 `--workspace-id` 时，仅复用同部署保存身份才沿用设置文件的最后空间；注入令牌不继承该空间，否则使用成员列表首项。仅明确远程、无图形或无人值守时设 `RQAMSH_AUTO_LOGIN=0`，不要把所有 Agent 调用归为这类环境。

- 令牌的取得方式与有效期由 AMS 平台决定；过期后重新运行 `rqamsh auth`，客户端不代办账号密码登录、也不会替你续期。
- `workspace_id` 可以省略：复用同部署保存身份时优先使用设置文件中的最后空间，否则读取 `GET <部署>/api/user/v1/workspaces` 的成员列表——非空时使用服务端当次返回的首项，零项报 `resource_not_found`。首项按服务端原序取，不排序、不按权益筛选；首项缺权益由服务端拒绝，不换后项。令牌关联用户，可在自己的成员空间之间切换；`workspaces.use` 失败不改变当前空间、缓存与设置。
- 目录可见性只看详情能否读到：读不到（403/404）的资源不进目录；客户端不查授权行、不做权限预判，越权由服务端与网关拒绝。
- 凭据可保存在 `rqamsh_settings.json`（含明文令牌，应限制为当前用户可读），或临时走命令行参数/环境变量/`--token @文件`；禁止写进脚本、证据 JSON 或提交记录；HTTPS 证书校验保持开启，不要为了避免报错而关闭校验。
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
