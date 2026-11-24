---
name: rqamsh
description: 用 rqamsh 查询或操作米筐 AMS 的产品、流水、估值、头寸、净值、归因、模拟交易、对账、托管事件及其余业务数据时使用；也用于解释 AMS 业务概念。
---

# rqamsh

`rqamsh` 是用于查询和受控写入 AMS 业务数据的 Python API 与 CLI，发行包名 `rqams-harness`。未安装、需要升级或宿主只能访问 Skill 目录时，按 [rqams-harness 安装说明](https://github.com/ricequant/rqams-harness/blob/dev/README.md#agent-skill)处理。

## 找到当前版本的文档

运行 `python -m rqamsh docs`，读返回的 `path`；如果宿主只能看 Skill 目录，读已同步的 `sdk-docs/<docs_sha256>/`。下面路径均相对该文档根目录。正常任务不拉在线开发分支。已定位操作时用 `python -m rqamsh <块> <操作> --help` 核对参数，需要完整签名与操作清单才用 `schema`。取值范围、返回结构、单位与业务口径只读命中的文档段落，不凭字段名推断。

| 用户目标 | 从这里开始 |
|---|---|
| 只问概念或能力 | 由 `index.md` 找对应业务页；对象不明确时看 `demo/README.md` 的「对象与动作边界」。不连接 AMS、不索要凭据。 |
| 当前单产品简报，或当前与昨日比较 | `demo/product-briefing/README.md` 的「开始执行」「取数编排」。先取产品配置和当前快照，再按实际日期与缺项决定后续读取。 |
| 指定日期的单产品头寸或净值 | `balances.md#get`。按业务日期读取，不额外查询实时快照。 |
| 对账或托管事件 | 分别读 `reconciliation.md`、`custodian_events.md`，先定位产品、日期、外部凭证和目标动作。 |
| 其他跨业务目标 | 优先用 `demo/README.md` 的业务目标索引，否则用 `index.md` 选业务块。分析接口从 `analytics/index.md` 定位主题。 |

## 连接与编排

- 用户确实要接入或查询业务数据时，在本机主动执行首个相关 CLI 只读命令；尚无具体查询时用 `python -m rqamsh workspaces list`。已有身份直接复用；缺身份时保持命令运行，让用户在自动打开的本机页面填写 key，登录后继续原任务。Python `init()` / `Client` 不会自动打开登录页。不要索取或回显凭据，不让 key 进命令字面值、对话或日志；非交互终端不等于没有本机浏览器。
- 已明确部署和空间时直接复用。首次连接私有部署、切换空间或排查身份问题时读 `connection.md`、`workspaces.md`；空间选择不增加授权，当前空间被拒绝不自动换另一个空间或令牌。CLI 转 Python 时保持身份、部署和目标空间：Python `Client` / `init()` 不读取 CLI 的连接环境变量。CLI 使用临时令牌时，Python 从同一安全来源读取并显式传入 `token`、`base_url`、`workspace_id`，不能误用保存身份。
- 多步查询尽量在一个 Python 进程内复用 `Client` 和已核实的资源 ID。多资源优先用已有批量操作，否则按 `connection.md` 组织有限并发；不为了一个产品逐一查全空间详情。

## 判断完成与写入

- 实时、批量、估值或分析任务按 `demo/README.md#task-readiness` 验收。首次遇估值依赖，读 `index.md#valuation-lifecycle`。缺项、运行中、失败或等待超时，按 `connection.md#unready-inputs` 处理：有整体截止时间，保留已获结果，不换业务日期，不把小计当全量，也不把超时当作撤销。
- 写入前读 `demo/README.md#6-写操作计划卡` 和业务页的写入、覆盖与失败规则。明确目标、关键字段和授权，执行后读回记录和受影响的业务结果。明确授权创建且可用公开默认时不重复索要许可；新增覆盖、删除、扩大范围或使用未确认口径时先取得相应授权。不要盲目重发结果未知的写入。
- 对账修正、状态标记、自动对账或撤销，以及托管事件的创建、修改、导入或删除，即使用户已提出写入目标，也要先只读诊断，报告拟改对象、日期、依据、影响与可撤销范围，取得确认后再写。对账区分人工标记和估值表整体覆盖；只有差异已消除，或用户明确接受余差并要求标记，才能写入完成，见 `demo/reconciliation-controls/README.md` 的诊断和复查。托管写入读 `custodian_events.md` 的写前规则与目标操作；申赎先核实开放日与单位净值，缺少资料时可用前序有效头寸的单位净值提出四位小数的候选，说明日期和来源并让用户确认，无可靠依据则不写。
- 回答按 `demo/README.md#7-结果翻译` 组织：说明对象与业务日期、已核验结果、依据和缺口，区分事实与推断。案例用于理解判断、分支和复查，不直接拿脚本和示例输入代替当前任务。
