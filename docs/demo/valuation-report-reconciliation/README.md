# 估值表导入与报告核对（valuation-report-reconciliation）

> 学习案例，不是接口清单。产品、日期、金额、份额与文件内容均为构造输入，不代表真实业务数据或操作回执；字段、模板适用范围、覆盖规则与返回结构以 [`docs/`](../../index.md) 和当前 `rqamsh schema` 为准。

## 学习目标

- 从“用户给了一份估值表，请导入”定位唯一的产品、业务日期、数据源、`auto_overwrite` 与封账状态。
- 判断文件入口还是结构化 JSON；理解 CSV 不能靠改后缀、模板与内容必须匹配。
- 同日已有报告时取得日期级替换授权，并区分“替换报告记录”和“产品采用报告/估值表覆盖”。
- 把保存、解析成功、采用、估值就绪分开核对；失败或未知先查报告列表和凭证，不盲目重传。
- 核对元数据、源文件内容、头寸和对账状态；产品级 `reconciliation.diff` 只适用于混合产品。

## 构造场景

业务用户说：托管方发来“示例混合产品”2026-06-30 的 xlsx 估值表。这个产品之前这天已导入过一份，但单位净值录错了；请用新文件替换这一天，只改 06-30，不要动其他日期。导入后核对净资产、份额、单位净值，并告诉我对账状态。

|项|构造值|
|---|---|
|`P`|“示例混合产品”，`data_source=trade_and_valuation_report`，`auto_overwrite=false`|
|业务日|2026-06-30，以报告内容中的日期为准|
|已有报告|同一天、上一次导入的错误记录；只获授权替换这一天|
|新报告|净资产 1,200,000、份额 1,000,000、单位净值 1.2；持仓行以文件为准|
|输入|`.xlsx` 受支持估值表模板|

纯估值表产品的采用分支不同；本场景选混合产品，是为了展示“保存 ≠ 采用”。日期、金额是构造的。

## 读写与权限边界

通用边界见[写入范围与授权](../README.md#6-写操作计划卡)和[任务完成条件](../README.md#task-readiness)。本例额外限定同日替换、报告采用与脚本清理的范围，不能用通用“已授权导入”代替这些具体确认。

- 读取：`products.get`、`valuation_reports.list/download`、`balances.get`、`confirmations.list/get`、`reconciliation.list`。对账读取按对账级权限授权（要求 `write`）。
- 写入：`valuation_reports.upload/delete`、`reconciliation.auto/undo_auto`、`reconciliation.mark`，以及修改产品 `auto_overwrite`。本案例只计划替换 06-30 的报告记录；采用、删除和开关单独授权。
- 写权限看 `products.list` 的 `permissions`：按 `product_id` 匹配；`is_owner=true` 是创建者/空间管理员，按最高级别；遇到 `permission=forbidden` 先看 `is_owner`，不能一概判为不可读/不可写。不要用试探写入判断权限，也不要用全量 `products.list` 代替产品定位。
- 读取报告/下载要求 `read_import_data`；导入/删除要求产品 `write`。权限不足、产品/日期/报告不能唯一确认时停止。
- `workspaces.list()` 只列成员空间，不确认当前路由；需要选择时用 `workspaces.use(workspace="<成员空间 ID>")` 并核对返回 `id`。空间选择不授予产品权限。

## 第 1 步：定位产品、日期与采用设置

**为什么。** 估值表只能导入支持估值报告数据源的产品；同一天的“系统结果”“已保存报告”“估值表覆盖”可能是三件事。

**查什么。** 先按唯一 ID 或唯一名称 `products.get(resource="<P 的产品 ID 或唯一名称>")`，读 `data_source`、`auto_overwrite`、`start_date`、`closing_date`、`maturity_date`。名称有歧义时才用 `products.list` 看候选；不先做无筛选全空间扫描。`auto_overwrite` 是产品级“是否自动采用后续报告”的设置，不是本次上传的覆盖参数。

**判断。** `data_source=trade` 不能导入报告；`valuation_report` 的有效报告会进入覆盖并重算；混合产品由 `auto_overwrite` 决定是否自动采用。报告日期不能晚于到期日，且要落在产品业务区间；目标日处于封账范围时写入/替换通常被拒绝。

## 第 2 步：盘点已有报告与文件合法性

**为什么。** “导入”可能是新增，也可能覆盖已有记录；没有明确授权就覆盖，会把“补一份”变成“改掉已有记录”。

**查什么。** 用 `valuation_reports.list(resource="<P 的产品 ID>", start_date="2026-06-01", end_date="2026-06-30")` 看 `date`、`file_name`、`valuation_report_id`、`source`、`valuation_level`。列表只有元数据，不含净资产和持仓。列表在给定日期区间没看到报告，只说明该筛选下没有返回；先核对产品、区间、权限和导入材料，不能直接断言报告不存在。需要定位交易日缺口时可用 `missing_dates`；它是交易日差集，不保证升序，也不补非交易日。

检查文件：必须是 `.xls`/`.xlsx` 的受支持估值表模板；文件内科目层级、编码分隔符、业务日期、净资产、份额、单位净值和持仓要能通过解析。文件名、扩展名和用户口述都不能替代内容核对。本客户端文件入口按缺省四级解析，没有级别参数；改名或改扩展名不会改变解析级别。原始 CSV 不能作为估值文件上传，要 CSV 形态时按字段转成结构化 JSON；把 `.csv` 改成 `.xlsx` 既不会变成 Excel，也不会按估值表模板解析。

**同日已有报告。** 先取得“只替换该业务日”的明确授权，再用 `replace_dates=["2026-06-30"]` 限定；不要因为“反正是覆盖”就默认允许。用户只授权一天时，不要使用全局 `is_overwrite=True`。同一天有多份报告且无法判断哪份权威、文件日期与用户说法不一致时，停止。

`replace_dates` 是允许覆盖的白名单，只对本次上传报告实际日期生效；它不是删除白名单里的全部报告，也不影响其他日期。上传覆盖参数与产品级 `auto_overwrite` 是两件事：前者只允许替换同日已保存记录，后者决定报告是否进入估值表覆盖。

## 第 3 步：上传或替换

**文件入口：**

```python
result = rqamsh.valuation_reports.upload(
    resource="<P 的产品 ID>",
    file_path="估值表-20260630.xlsx",
    replace_dates=["2026-06-30"],
)
```

`data` 与 `file_path` 必须且只能给一个。结构化入口的必填字段、持仓键和返回结构，以[估值报告操作](../../valuation_reports.md#upload)与[字段页](../../fields/valuation_reports.md)为准，不在这里另立契约。报告的 `source` 默认 `open_api`，允许 `manual`/`open_api`/`client_upload`；它描述报告来源，不是产品数据源。

**返回怎么读。** 重点看 `err_msg`、`confirmation_id`、`effect_count`、`valuation_report_id`、`date`、`is_modified`。`err_msg` 非空表示解析/保存错误，客户端抛部分失败异常且已保存内容不保证回滚；`effect_count` 新建时为 1、覆盖后内容未变化时为 0；`is_modified` 新建同日报告时为 false；`date` 是服务端按报告内容解析出的日期，必须与目标日一致。

同日已有报告但未给 `replace_dates`/`is_overwrite` 会被拒绝；`err_msg` 非空、部分失败或结果未知时，保留 `confirmation_id` 和完整结果，先查报告列表与凭证，不重传整份文件。返回日期不符或错误无法解释时停止。

## 第 4 步：保存、解析、采用、就绪是四层

|层次|证据|不能证明|
|---|---|---|
|保存|`valuation_reports.list` 能看到目标日期、报告 ID、来源、级别；`effect_count`/`is_modified` 符合预期|内容解析正确，或已采用|
|解析成功|`err_msg` 为空；凭证 `total_parsed` 与 `total_registered` 一致；下载/原件内容逐项匹配|产品已采用|
|采用报告|纯估值表产品的有效报告进入覆盖；混合产品看 `auto_overwrite`，或获授权的单日 `reconciliation.auto`；创建初始化报告是另条例外|不能仅凭保存/替换推断已采用|
|估值就绪|`compute_state=normal` 后重新读目标日及后续受影响日期|业务对账通过，或所有差异已解释|

易混点：混合产品 `auto_overwrite=false` 且未获显式采用授权时，保存报告只供核对，`balances.get` 可能仍是系统结果；`auto_overwrite=false` **不能证明历史上没有覆盖**，此前显式 `auto`、初始化或历史覆盖可能仍在，必须读 `auto_reconciled`/覆盖状态，不能只凭开关推断。开启 `auto_overwrite` 会把已保存报告批量写入覆盖，关闭会移除已有覆盖输入，不是单日开关。`reconciliation.auto` 是明确采用某日的动作；`undo_auto` 删除覆盖输入，不承诺恢复旧快照。`done=true` 可来自人工标记，或来自会写覆盖的路径（`auto`、纯估值表产品/开启自动覆盖时的报告导入、初始化报告）；撤销/删除报告/关闭自动覆盖会置 `false`，人工标记也可能被覆盖写入或撤销清掉，不能当独立验收。

## 第 5 步：读回元数据、内容、头寸与对账状态

**报告记录。** 优先使用本次上传返回的 `valuation_report_id`，到目标日列表里按该 ID 匹配；不要用 `meta[0]` 选报告。列表缺失、同一日期出现多份且无法确认本次记录时停止。

```python
uploaded = result  # 第 3 步 upload 的返回；不要为了读回再次上传
rows = rqamsh.valuation_reports.list(resource="<P 的产品 ID>", start_date="2026-06-30", end_date="2026-06-30")
matched = [r for r in rows if r.get("valuation_report_id") == uploaded["valuation_report_id"]]
if len(matched) != 1:
    raise RuntimeError("本次报告在目标日列表缺失或不唯一，停止")
report_id = uploaded["valuation_report_id"]
```

`list` 只回答有哪些报告、来源和级别；不能回答净资产、份额、持仓是否正确。核对其他日期未被替换时，对比替换前保存的区间列表和记录 ID。

**源文件与内容。** 用 `valuation_reports.download(resource="<P 的产品 ID>", valuation_report_id=report_id, output="downloaded-20260630.xlsx")` 下载，返回 `path` 与 `size`；打开文件核对业务日期、净资产、份额、单位净值和代表性持仓。结构化导入生成的是 CSV 源文件，本地扩展名不会把它变成 Excel。字节相同只证明“拿回同一份文件”，不能证明服务端解析正确。下载报 404/409 时，先核实原件确实缺失/损坏，并确认已有同日替换授权，才补传原件；不要默认重传，也不要靠换输出路径或换报告 ID 绕过核对。

**头寸与状态。** `products.compute_state(resource="<P 的产品 ID>")` 只查询一次。公开产品状态 `error` 立即停止诊断，`computing` 在总截止内只读重查；未知状态或字段缺失先核实，不能把底层任务的状态名称套到这里。`normal` 也可能对应旧结果，需结合写入前后 `execution_id` 与目标内容是否更新；正常状态下目标结果仍未就绪时，按[等待规则](../../connection.md#unready-inputs)有界重读，不重复提交写入。

```python
state = rqamsh.products.compute_state(resource="<P 的产品 ID>")
balance = rqamsh.balances.get(resource_or_resources="<P 的产品 ID>", date="2026-06-30", fields=["total_equity", "units", "unit_net_value", "positions"])
```

`balances.get` 当前签名的第一个关键字参数是 `resource_or_resources`，不要用位置参数。只有 `normal` 后读到的头寸才适合作为估值结果；若产品混合且未采用报告，这个 `balance` 是系统结果，不是报告值，不能据此说导入失败；若已采用，核对目标日并抽查后续日期。

**对账与凭证。** `reconciliation.list(resources=["<P 的产品 ID>"], start_date="2026-06-30", end_date="2026-06-30")` 的 `closed`、`auto_reconciled`、`unit_net_value`、`lack`、`done`、`have_position_statement` 一起读：`done=true` 不是独立核对通过；`auto_reconciled=true` 只表示存在覆盖记录，不能推断由谁/哪条路径产生；`lack.type=valuation_report` 与“有报告但持仓单缺失”不是一回事。`reconciliation.diff` 只支持混合产品，且要求该日有估值表、计算不在进行/失败；它返回分组差异对照，不是自动判定谁对。

`confirmations.list(resource="<P 的产品 ID>", start_date=..., end_date=...)` 的 `total_registered < total_parsed` 表示有解析/登记失败，用 `confirmations.get(..., status="failed")` 看失败项；日期筛选是凭证操作时间，不是报告业务日，刚导入时要放宽。凭证没查到也只说明该操作时间区间/筛选没有返回，先核材料与范围，不能直接断言未导入。

**交付条件。** 目标日报告存在且元数据与预期一致；源文件/原件内容逐项匹配；凭证解析/登记一致；采用分支和 `compute_state` 后头寸已明确；失败/部分失败/未知都有 `confirmation_id`、列表和逐项证据。未采用时明确写“报告已保存但未用于估值”，不要用报告值冒充头寸。

## 停止与失败

|情况|动作|
|---|---|
|同日已有报告但无明确替换授权|停止，取得日期级授权；不用全局开关绕开|
|模板/内容不匹配、CSV 改后缀、级别不符|停止；换正确模板或按字段准备结构化报告，不伪造层级|
|`err_msg` 非空/`partial_failure`|查列表和凭证失败项，修复后按新授权再上传；不重传未知整份|
|上传超时/响应不完整|先 `list` 该日期和凭证，确认前不发起第二次上传|
|下载 404/409|核实原件缺失/损坏并有替换授权后补传；不靠换路径/报告 ID 绕过核对|
|目标日封账、晚于到期日、无权限|停止，向业务确认或补授权；不换产品绕过|
|`compute_state` 为 `error`，或状态无法解释|停止诊断，不无限轮询或改数据|

## 可选受控演示

`docs/demo/valuation-report-reconciliation/run.py` 只围绕来源日志中已登记的自有产品运行，不创建或删除产品。它支持结构化批量上传、按日期替换并轮询头寸、下载源文件核对、按日期删除报告和受支持 xlsx 文件上传；同日已有报告时上传必须显式给替换范围，删除按日期而非报告 ID，`--confirm` 必须与日志及读回名称一致。它只验证脚本提供的路径，不覆盖采用设置、`reconciliation.auto`、任意模板、封账、权限拒绝和全部失败组合；参数全集以脚本说明和 `--help` 为准。

### 准备真实来源日志，演示后清理

首次运行没有来源日志时，使用本案例的 [prepare_product.py](prepare_product.py) 和[构造产品配置](product.json)。只在已获创建、导入和清理授权的演示空间执行；先把配置中的名称与报告名改为本次唯一名称，并同步替换下列 `--confirm`。它实际调用 `products.create`，保存返回的产品 ID，再用 `products.get` 核对 ID、名称后登记为已核实；不是手工给任意已有产品补一条“自有”记录。同名产品会停止，创建超时、部分失败或读回不一致时保留诊断，不能按名称认领、重建或删除。

凭据由运行环境注入 `RQAMSH_TOKEN`。以下命令在仓库根目录运行，部署、空间、名称及路径必须替换为本次授权值；每个 `--output` 都须为新文件。准备脚本只负责产品生命周期，不替代本页的报告和估值核对。

```console
python docs/demo/valuation-report-reconciliation/prepare_product.py --base-url https://ams.example.com --workspace-id <演示空间ID> --journal valuation-demo.journal.json --output valuation-create.json --confirm harness-valuation-example create --config docs/demo/valuation-report-reconciliation/product.json --batch-id valuation-example
```

确认创建证据为 `passed`，取实际返回的产品 ID；后续使用同一部署、空间、日志和确认名称。构造产品从 2026-10-26 开始，下面只导入 `inputs/` 中的结构化 JSON 报告；产品配置刻意放在该目录之外，不能把配置 JSON 当作估值表批量上传。目录中的 2026-09-25 XLSX 是文件格式教学材料，早于该产品开始日，不用于这个准备流程。

```console
python docs/demo/valuation-report-reconciliation/run.py --base-url https://ams.example.com --workspace-id <演示空间ID> --journal valuation-demo.journal.json --output valuation-upload.json --confirm harness-valuation-example --product <实际创建返回的产品ID> upload --reports-dir docs/demo/valuation-report-reconciliation/inputs
```

按本页读回报告和头寸、核对结果后，确认无需保留，再用准备脚本按同一日志清理本次创建的专用产品，不使用同名搜索结果替代 ID：

```console
python docs/demo/valuation-report-reconciliation/prepare_product.py --base-url https://ams.example.com --workspace-id <演示空间ID> --journal valuation-demo.journal.json --output valuation-delete.json --confirm harness-valuation-example delete --product <实际创建返回的产品ID>
```

产品删除不是物理擦除历史数据；如需演示报告删除，须先按原脚本的日期级授权和报告 ID 归属核对完成，再停用产品。任一步结果未知，停止后续写入或清理，保留日志只读查明，不重复提交。

## 变式问题

1. 用户给的是 CSV 但文件名是 `.xlsx`：直接上传会怎样？正确做法是改后缀、另存 Excel，还是准备结构化报告？
2. 同日有两份报告，用户说“换掉错的那份”：`replace_dates` 是否足够？还需要哪些元数据/源文件证据？
3. 混合产品 `auto_overwrite=false`，报告保存后头寸与报告不同：是导入失败、未采用，还是系统结果不同？下一步读什么？
4. 下载返回 409：换输出路径、换报告 ID，还是先核实原件并取得替换授权？为什么？

## 证据不足时怎么交付

- 先列已确认：产品/日期/数据源如何定位，上传返回的报告 ID、目标日列表匹配结果、源文件内容、凭证解析/登记数量、`compute_state` 实际值。
- 再列未确认：只保存未采用、未取得头寸、后续日期未重算、只验证字节未验证内容、差异未解释。不要用“应该已生效”补齐。
- 部分失败/未知保留 `confirmation_id`、报告列表、逐项错误与 `execution_id`；先只读核对，不重传。
- 缺少内容核对、采用状态或头寸读回时明确说“尚未证明”，不要用上传 200 或字节一致代替验收。

## 下一步与权威页

报告已保存但未采用、需要处理差异：进入[对账控制案例](../reconciliation-controls/README.md)，按定位产品/日期 → 查缺件和状态 → 分组诊断 → 有依据地修正输入 → 等待复查 → 人工标记或明确采用处理。报告日期缺失时先看 `list`/`missing_dates` 并确认业务上应有该日报告。

- [估值报告操作](../../valuation_reports.md)、[估值报告字段](../../fields/valuation_reports.md)
- [估值表覆盖设置](../../reconciliation.md#valuation-report-overwrite-setting)、[对账差异分组](../../reconciliation.md#reconciliationdiffgroup)
- [产品与 permissions](../../products.md)、[资源权限](../../permissions.md)
- [写入结果](../../connection.md#write-result)、[逐项失败容器](../../connection.md#item-errors)、[下载结果](../../connection.md#download-result)
- [导入凭证](../../confirmations.md)、[头寸读取](../../balances.md)
