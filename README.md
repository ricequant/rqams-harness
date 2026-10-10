# rqams-harness

面向 AMS 用户 Agent 的 Python API 与 CLI 操作入口：将产品管理、数据导入、头寸查询、业绩分析和对账需求转换成可执行操作，业务数据与估值计算由 AMS 管理。本项目只负责需求中的「AMS 业务数据管理」一块，三类的划分见[金律](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md)。先读[AMS 业务与 API 使用指南](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md)，理解业务输入、头寸链与本项目的能力边界。发行包名 `rqams-harness`，Python 导入名和命令名均为 `rqamsh`；需要 Python >=3.10。

## 安装与离线发现

Python >=3.10，在本项目目录：

```console
python -m pip install -e .
rqamsh --help
rqamsh schema
python -m rqamsh trades upload --help
```

`schema` 和帮助无需连接服务，可用来发现操作与参数。若终端找不到 `rqamsh`，先激活安装该包的 Python 环境，或使用 `python -m rqamsh`。
离线 `schema` 的 `balances.get` 仅公开单一签名；它会说明 `benchmark_id` 使用纯 ID，以及过去日期使用自定义基准时只能选择顶层收益字段，不能同时返回 `positions` 或 `daily_pnls`。


## 作为 Agent Skill 使用

本项目配有一份供 agent 使用的 skill，位于 [`ricequant-skills`](https://github.com/ricequant/ricequant-skills) 的 `skills/basic/rqams` 技能族下，技能名 `rqamsh`。它只包含一个 `SKILL.md`，做三件事：告诉 agent 文档在哪、怎么按需检索、怎么调用 `rqamsh`。契约文档的单一来源仍是本仓库的 [`docs/`](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md)，skill 不复制文档内容，也不提供下载或索引脚本——agent 自行获取（首选 `git clone --depth 1` 本仓库后本地检索，也可直接读 raw 单页）。

把下面这段交给你的 agent，它会自行定位技能目录并落盘：

> 在 `https://github.com/ricequant/ricequant-skills` 里找到 `skills/basic/rqams` 下名为 `rqamsh` 的技能，读取其中的 `SKILL.md`；在我使用的 agent 技能目录下建同名技能目录 `rqamsh` 并写入该文件，然后按文件内的引导完成初始化自检（`rqamsh schema`），最后告诉我安装的绝对路径与 `rqamsh schema` 的输出是否正常。

安装后即可用它处理「取 AMS 已算好的业务数据、执行受控写入」类需求。文档与本地安装版本不一致时，以 `rqamsh schema` 的运行时输出为准。

## 只读入门

```python
from rqamsh import Client

with Client(
    base_url="http://127.0.0.1:21015",
    workspace_id="0123456789abcdef01234567",
    cookies={"sid": "<令牌>"},
) as client:
    products = client.products.list()
    # 从已获授权的产品中选择唯一 ID 或名称。
    # historical = client.balances.get(resource_or_resources="授权测试产品", date="2026-01-05")
    # realtime = client.balances.get(resource_or_resources="授权测试产品")  # 省略 date 为北京时间当天的实时语义
    # get 默认包含平铺头寸；非空 classifier 改为分层头寸。
```

示例地址、会话名与空间仅说明格式，不代表可访问配置。CLI连接参数必须位于子命令前，也可由 `RQAMSH_BASE_URL`、`RQAMSH_WORKSPACE_ID`、`RQAMSH_COOKIE` 提供（前两个必需；会话怎么取得见[登录会话](https://github.com/ricequant/rqams-harness/blob/main/docs/connection.md#session-injection)）：

```console
rqamsh --base-url http://127.0.0.1:21015 --workspace-id 0123456789abcdef01234567 --cookie sid=<令牌> products list
```

模块式调用同样可用：先 `rqamsh.init(base_url, workspace_id=..., cookies={...})`，再 `rqamsh.products.get(resource=...)`，最后 `rqamsh.close()`；并行不同身份应分别持有显式 Client，不共享模块默认实例。

## 定位与需求拆解

**金律**：`Agent 自身能力 + 第三方能力 + rqamsh 业务数据管理能力 = 满足用户需求`。本项目只负责第三项——把 AMS 已算好、已落库的业务数据取回来，以及受控写入；第三方系统对接与调用方自己的加工不在范围内，三类的划分与真缺口判据见[金律](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md)。

## 能力与边界

19 个业务块、146 个公开操作：工作空间、产品、产品组、资源权限、自定义标的/公允价、头寸报表、净值与收益指标、分析（持仓分析/业绩归因/组合对比/周报/交易分析）、风险监控与看板数据、市场数据与基准、流水、估值报告、资产单元、持仓单、对账、托管事件、份额事件、产品持仓表、导入凭证。它们是 AMS 整体能力的一个子集：资产单元的可用持仓（业务位置见 [`docs/asset_units.md`](https://github.com/ricequant/rqams-harness/blob/main/docs/asset_units.md#asset-unit-binding)）与期货手续费参数、模拟交易、自定义指标注册表、用户偏好与前端配置方案、平台与运维端点等仍未暴露；分析类结果通常耗时较久（等待与超时规则见 [`docs/connection.md`](https://github.com/ricequant/rqams-harness/blob/main/docs/connection.md)），组合对比只提供一套组级口径。统一 `resource` 接受可访问产品/组/单元 ID 或名称；各操作的资源范围不同，多匹配必须消歧，不会向产品组广播写入。

- `create` 创建业务对象；`upload` 向既有对象导入数据；`update` 修改记录；`replace_fairvalues` 明确全量替换。
- CLI成功JSON仅stdout，错误JSON在stderr且非零退出；Python抛 HarnessError。返回保持服务端原始结构，不静默拆包；各操作实际返回的数据结构在各业务页的返回字段表中列出（表头与路径写法见 [`docs/connection.md`](https://github.com/ricequant/rqams-harness/blob/main/docs/connection.md#return-fields)）。
- 调用会按需等待服务端算完：默认单请求60秒、总等待300秒、间隔1秒（`--timeout`/`--wait-timeout`/`--poll-interval`）；等待超时不代表服务端取消或失败，写请求不会盲目重放。
- 文件导入可能按日期/账户覆盖旧数据；结构化流水非空foreign_id按产品upsert。部分失败可能已写入合法项，异常保留完整结果。
- 下载必须指定新输出文件，不覆盖已有文件。
- **未暴露能力不等于阻塞**：模糊检索与打分、区间差分、加权贡献、报告渲染（Markdown/DOCX/PNG）、序列拼接、定时推送、写入前预览与幂等键属于调用方（Agent）职责；企业微信、邮件这类第三方通道的对接由对端官方接口决定，本项目不封装也不测试。两者都不算本项目缺口，真正的缺口只有两类：**取不到的数据**（服务端未持久化的配置版本/审批元数据、需服务端规则引擎的判定）与**外部凭证或公网入口**。边界判据见[必要边界](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md#必要边界)；客户端契约测试、只读联调配方与实测量级见 [`tests/README.md`](https://github.com/ricequant/rqams-harness/blob/main/tests/README.md)。

**安全：**本版不代办登录，也不接收账号密码。请向 AMS 管理员取得服务地址、获授权的工作空间与可用的令牌（当前部署是登录会话 cookie）。即使地址是本机，也可能操作正式业务数据；上传、修改、删除、重算前必须确认目标与授权，客户端资源筛选不能替代服务端授权。

## 从用户需求选择能力

|用户需求|AMS 业务路径|结果核对|
|---|---|---|
|“把这只基金纳入管理”|先用 `products.list/get` 确认是否已有产品；没有时按数据源创建产品并配置账户|核对产品 ID、数据源、起始日、账户和基准，不能把创建成功当作已有估值|
|“导入今天成交，更新持仓”|确认交易源产品和账户 → `trades.upload` → `products.compute_state` → `balances.get` 读取同日头寸报表及其中的头寸|检查逐项导入结果、估值状态、业务日期、数量与权益；部分失败不代表全批回滚|
|“按托管估值表对账”|确认估值报告或混合数据源产品 → `valuation_reports.upload/list` → `products.compute_state` → `reconciliation.list/diff` 查缺件与差异 → `balances.get`|确认同日替换范围和估值表覆盖配置，再比较报告日期、净资产、净值和头寸；采用或撤销自动对账用 `reconciliation.auto/undo_auto`，并按读回结果核对|
|“这段时间赚了多少、承担多大风险”|确认产品/组、区间、基准和日历 → `analytics.indicators`；画净值曲线用 `analytics.series`|区分金额与收益率，披露数据缺失及指标口径；不要把空结果解释为零收益|
|“合并查看几只产品”|用 `product_groups` 管理成员；用组查询 `balances.get` 读取历史或实时头寸报表及成员权重视图，用 `analytics` 查询指标与净值收益序列|核对成员、权重、日期和实时结算状态；向组查询不等于向所有成员写入|
|“按自己的分组标注产品”|用 `tags.list` 读现有标签 → `tags.upsert` 建/改标签并整体覆盖绑定；不再需要时 `tags.delete` 按 ID 删除|标签是调用方私有的组织信息，只影响标签与绑定关系|
|“维护场外资产或账户内子组合”|场外标的及价格用 `custom_instruments`；产品内资产单元用 `asset_units`，其持仓单用 `positions_statements`|区分标的记录 ID、证券代码和资产单元 ID；价格替换与持仓单覆盖前确认范围|

### Agent 执行顺序

1. 明确用户目标、产品/组/单元、日期或区间，以及交付形式（解释、JSON 或导出文件）。缺少影响业务结果的信息时先询问用户。
2. 从当前身份可访问资源中匹配唯一目标；同名时用 ID 消歧。查询详情，确认数据源、账户、基准、日历和权限符合需求。
3. 先读后写。导入、覆盖、删除和重算前说明目标与影响范围；只有用户授权后才执行，不能为了让查询成功而擅自修改历史数据。
4. 检查逐项结果与最终状态。超时只表示停止等待，不代表任务取消；先确认原请求结果，再决定是否重试。
5. 按同一日期与口径读回结果。回答中注明资源、区间、关键指标及未完成/缺失项，而不是只报告“API 调用成功”。

## 文档

从[AMS 业务与 API 使用指南](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md)开始：先理解 AMS 的输入、估值与输出，再了解 Harness 的公开能力，按场景选择 API 步骤和完成条件。各业务页提供完整参数/默认值、返回和副作用、Python/CLI 示例；字段字典展开嵌套结构。三类能力的划分与判定口径见[金律](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md#金律三类能力拼装本项目只做第三点)与[必要边界](https://github.com/ricequant/rqams-harness/blob/main/docs/index.md#必要边界)；客户端契约测试、只读联调配方与实测量级见 [`tests/README.md`](https://github.com/ricequant/rqams-harness/blob/main/tests/README.md)。尤其先读：

- [连接、身份、等待与错误](https://github.com/ricequant/rqams-harness/blob/main/docs/connection.md)
- [工作空间是什么](https://github.com/ricequant/rqams-harness/blob/main/docs/connection.md#workspace)：工作空间是服务端数据分区，`workspace_id` 只选择请求分区，不是登录凭证
- [工作空间列举与切换](https://github.com/ricequant/rqams-harness/blob/main/docs/workspaces.md)：列举当前身份可见的空间，并在会话内切换请求分区；需要与业务接口相同的认证入口
- [标签：产品与产品组的分组标注](https://github.com/ricequant/rqams-harness/blob/main/docs/tags.md)
- [头寸报表：单一 get 与历史时序](https://github.com/ricequant/rqams-harness/blob/main/docs/balances.md)
- [交易流水：结构化upsert与文件覆盖](https://github.com/ricequant/rqams-harness/blob/main/docs/trades.md)
- [估值报告：同日覆盖白名单](https://github.com/ricequant/rqams-harness/blob/main/docs/valuation_reports.md)
- [对账：状态、差异、人工标记与估值表覆盖](https://github.com/ricequant/rqams-harness/blob/main/docs/reconciliation.md)
- [指标计算口径、年化、日历和缺失边界](https://github.com/ricequant/rqams-harness/blob/main/docs/analytics.md#indicators-returns)

所有示例均需替换为用户获授权的身份和目标。字段、结果形状及限制见对应业务页；文档示例不是对任意环境的数据写入授权。

## 许可

本软件为米筐科技双许可：

- **非商业用途**（个人出于非商业目的，或高校、研究所等非营利机构出于教育、科研目的）：遵守 [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0)；本软件分发时需保持当前许可“原样”不变，且不得附加任何条件。
- **商业用途**（个人出于任何商业目的，或法人及其他组织出于任何目的）：须先获得米筐科技授权，并在此前提下同样遵守 Apache 2.0 许可；两者冲突之处以当前许可为准。

完整条款见仓库根目录的 [LICENSE](https://github.com/ricequant/rqams-harness/blob/main/LICENSE)，授权流程请联系 public@ricequant.com。
