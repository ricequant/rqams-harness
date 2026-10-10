# AMS 业务与 API 使用指南

## 金律：三类能力拼装，本项目只做第三点

`Agent 自身能力 + 第三方能力 + rqamsh 业务数据管理能力 = 满足用户需求`

拆解用户需求时，每一项都要归到三类之一，归属决定谁来做、谁维护：

|归属|范围|谁做|本指南的覆盖|
|---|---|---|---|
|**rqamsh（本项目）**|AMS 业务数据的读与受控写入：产品、流水、头寸、指标、归因、对账、托管与份额事件等|本项目|本指南逐页给出参数、返回、口径与副作用；行为由 `rqamsh` 的契约测试保证|
|**第三方能力**|企业微信、邮件、办公套件、行情源、外部存储等外部系统|对接方|**不实现、不测试、不封装**：按对端官方文档自行实现，本项目只保证给它们提供数据的那一段（即上一行的操作）|
|**Agent 自身能力**|排序取前 N、区间差分、加权贡献、名称模糊匹配、文字摘要、Markdown/DOCX/PNG 渲染、多产品合并、定时触发与推送|调用方|**不实现、不测试**：由调用方按需组合|

只有三类都覆盖不到才算真缺口：**取不到的数据**（服务端未持久化的配置版本或审批元数据、需要服务端规则引擎的判定）与**外部凭证或公网入口**。反过来，第三类没有现成封装、第二类没有现成对接，都不是本项目的缺口；而任何「取数 → 加工 → 投递」的需求，取数这一段必须落在本指南的操作上，加工与投递由调用方完成。

## 先理解 AMS：围绕产品持续维护头寸链

AMS 围绕产品接收业务输入、进行估值，并持续维护每日头寸、净资产、净值及分析结果。产品不是一张孤立的持仓表：某日的交易、资金和权益事件会影响当日状态，也可能影响后续日期。

```text
业务输入 → 更新持仓、现金、负债与份额 → 估值 → 头寸 / 净值 / 指标 / 分析

上日头寸 + 当日交易与事件 → 当日持仓及资金、份额状态
当日状态结合当日行情、汇率及估值规则 → 当日估值结果
```

这里的“+”表示应用业务变动，不是把持仓数量与价格相加。例如普通现货的市值通常基于数量乘估值价格，再按需要换算币种；期货等品种还需采用各自的保证金、权益和市值口径。

### 输入：变动与截面

|输入类别|典型业务资料|在头寸链中的作用|
|---|---|---|
|变动输入|交易流水、托管事件、份额事件、交割单、模拟交易信号|描述成交、资金、权益或份额变化；能否接入及如何进入估值取决于产品数据源与业务配置|
|截面输入|估值表、持仓单、起始日头寸|提供某日已知状态，用于建立起点、校准或对账；不自动等同于完整估值结果|

估值表可提供某日净资产、份额净值和持仓截面；是否直接采用、校准或以估值表覆盖已有结果，见[估值表覆盖设置](reconciliation.md#valuation-report-overwrite-setting)。持仓单有的只用于数量对账，不含完整资产负债和净值，不能全部替代估值。起始日头寸也必须来自真实业务数据，不能为补齐查询而编造。

### 输出：状态、业绩与核对

AMS 的业务能力包括查看头寸和资产负债、净值与指标及基准比较，进行归因、交易分析、投资概览，并支持对账和周报等工作。它们都依赖输入完整性、日期和计算口径；输入文件已导入不代表后续估值和分析已就绪。

## 再理解本项目：Agent 操作 AMS 的入口

`rqams-harness` 为 AMS 用户 Agent 提供 Python API 与 CLI 操作入口；业务数据和计算由 AMS 管理，本项目不另建一套估值系统。当前公开 **19 个业务块、146 个操作方法**，只覆盖下方导航列出的能力：可导入交易流水、交割单、估值报告、资产单元持仓单、托管事件、份额事件和产品持仓表，可读取头寸报表、指标与分析结果，可查询风险条款、实时预警、市场行情与基准数据，可追查导入凭证，可读取与调整资源授权、生成周报、列举并切换工作空间。AMS 已有、但本 Harness 仍无对应操作的能力包括（不限于）：资产单元的可用持仓（候选与绑定口径见[资产单元与收益互换持仓](asset_units.md#asset-unit-binding)）与期货手续费参数、模拟交易、自定义指标注册表、平台与运维端点（用户设置、上传会话等）。不要把 AMS 的整体业务介绍当成可直接调用的 API 清单，也不要将读取数据后自行整理的报告称为 AMS 原生报告。

操作前先读[连接、身份、等待与错误](connection.md)。`rqamsh schema` 可离线查询当前完整能力；其中 `balances.get` 只显示统一单日签名及其历史自定义基准限制。CLI 将方法名中的下划线替换为连字符，`data` 使用 `--input`（别名 `--data`）。每个业务页给出完整参数、默认值与覆盖规则，并用返回字段表列出该操作实际返回的数据结构；表头、路径写法与通用返回结构的约定见[返回值与返回字段表](connection.md#return-fields)。

产品是独立核算边界；账户是产品内的流水归属配置，不是可独立选择的资源。产品组用于汇总成员，不是批量写入口。资产单元属于一个产品，其持仓单与产品流水、托管估值报告不能互相替代。

## 常见场景：按步骤执行，再核对完成条件

先确认用户目标、获授权的唯一资源、业务日期或区间、数据源及交付形式。写入前确认覆盖范围并取得授权；下表中的写入方法名是操作指引，不是执行授权。

|用户想做什么|API 步骤与处理方式|完成条件|
|---|---|---|
|建立产品并开始估值|`products.list/get` 查重和确认配置；确需新建时用 `products.name_exists/create`，按数据源准备账户、起始日、份额与基准 → 导入对应业务数据 → `products.compute_state` → `balances.get`|检查创建与导入错误，核对产品配置；计算状态为 `normal`，同日头寸与净值可读且符合输入。创建成功不等于已有估值|
|导入或更正成交、资金流水|`products.get` 确认数据源和账户 → `trades.list` 查已有数据 → 新数据用 `trades.upload`，更正已有记录按 `trade_id` 用 `trades.update`；交割单用 `trades.upload_settlement_file` → `products.compute_state` → `balances.get`|逐项导入结果、计算状态与业务日期均核对；数量、资金和权益符合预期。部分失败可能已有合法项写入，不能整批盲目重传|
|导入托管估值表并对账|`products.get` 确认数据源及估值表覆盖配置 → `valuation_reports.list` 查同日记录 → 明确授权后 `valuation_reports.upload` → `products.compute_state` → `reconciliation.list/diff` 查缺件与差异 → `balances.get`|报告日期与实际替换范围正确，估值就绪；缺件与差异逐项说明，人工结论用 `reconciliation.mark` 记录|
|查对账状态、标记或自动对账|`reconciliation.list` 查区间缺件与人工状态 → `reconciliation.diff` 或资产单元 `reconciliation.asset_unit_diff/positions_statement` 核对差异 → 授权后用 `reconciliation.mark` 记录结论，或用 `reconciliation.auto/undo_auto` 采用、撤销估值表覆盖 → `products.compute_state` → `balances.get` 读回|缺件与差异均有解释，读写结果一致；自动对账返回不代表计算完成|
|查看历史资产、仓位或盘中变动|历史截面用 `balances.get(resource_or_resources=..., date=...)`；实时截面用 `balances.get(resource_or_resources=...)` 或北京时间当天 `date`；历史时序用 `balances.series`；少数顶层字段传 `fields`|交付包含目标、实际返回业务日期或估值时点、头寸与所需字段；当天/省略日期为实时语义，不能冒充日终历史结果。省略 `classifier` 返回平铺头寸，传非空分类器返回含 `children` 的分层头寸|
|分析收益、回撤、风险或画曲线|确认产品/组、区间、基准与日历 → 汇总用 `analytics.indicators`，曲线用 `analytics.series`，胜率用 `analytics.win_rate`，产品多空拆解用 `analytics.long_short_returns`|按[指标计算口径](analytics.md#indicators-returns)区分金额、比例及年化，注明缺失数据；不能以这些结果声称完成未暴露的完整归因分析|
|汇总多只产品|`product_groups.list/get` 核对现有组；授权后按需 `product_groups.create/update` 配置成员 → 用组读取 `balances.get/series` 和 `analytics.indicators/series`；实时成员权重视图使用 `balances.get(include_component_weight_view=True)`|成员、权重、日期和计算口径明确；成员权重视图仅实时产品组且需相应权限。成员数据修改仍逐产品执行|
|给产品或产品组打标签|`tags.list` 查现有标签与绑定 → `tags.upsert` 写入名称、说明与绑定对象（整体覆盖）→ 不再需要时 `tags.delete` 按标签 ID 删除|标签与绑定只属于当前用户与[工作空间](connection.md#workspace)；删除只影响标签与绑定，不动产品与产品组|
|给场外资产定价|`custom_instruments.list/get` 查标的及价格 → 必要时 `custom_instruments.create` 建档 → 按覆盖意图选择 `custom_instruments.upload_fairvalue` 或 `custom_instruments.replace_fairvalues` → `products.compute_state` → `balances.get`|代码、归属产品、币种和价格日期正确；确认是覆盖文件最早日起全部价格还是替换完整历史，并核对受影响日期估值|
|管理资产单元并核对持仓单|`asset_units.list/get` 确认单元及归属产品（与收益互换持仓的绑定口径见[资产单元与收益互换持仓](asset_units.md#asset-unit-binding)）；授权后按需 `asset_units.create/update` → `positions_statements.list` 查已有记录 → `positions_statements.upload` → `positions_statements.list(resource=..., is_detail=True)` 读回|模板、单元、日期及数量正确，同日覆盖符合授权；持仓单完成只代表相应输入与数量核对，不能据此宣称产品净值已核对|
|录入或更正托管事件、份额事件|`products.get` 确认数据源 → `custodian_events.list`/`unit_events.list` 查已有记录 → 单条或批量用 `custodian_events.create/update/delete`、`unit_events.create/update/delete`，文件批量导入用 `custodian_events.upload_file` → `products.compute_state` → `balances.get` 读回|`effect_count` 与 `err_msg` 逐项核对；份额产品的申赎须带 `product_share`；文件导入是覆盖式，文件需包含该日起全部事件；自动份额事件只读|
|导入产品持仓表并追查导入结果|`positions_sheets.get` 查已有日期 → 准备该日完整持仓 → `positions_sheets.upsert`（两种截面形态见[估值表输入的两种形态](valuation_reports.md#positions-sheet-input)）→ `get` 读回；导入批次用 `confirmations.list/get` 核对，必要时 `confirmations.latest` 与 `download`|预计与实际计数一致且 `error_messages` 为空；已有估值表覆盖的日期按跳过处理；凭证 `is_successful` 为真才表示全部登记|
|封账、解封或批量核对缺表|`products.set_closing_entry` 或 `clear_closing_entry`；缺表用 `products.valuation_report_missing_dates` 汇总，再对单个产品用 `valuation_reports.missing_dates` 定位 → 补导报告 → `products.compute_state` → `balances.get`|封账日符合约定；缺表日期已补导或被明确排除；解封后重算到 `normal` 且头寸报表已核对|
|输出头寸全景、指标时序或持仓单原文件|用 `balances.export_file`、`analytics.download_series_file` 或 `positions_statements.download` 指定新输出路径|文件已落盘且大小与实际内容核对；目标文件已存在时另选路径，不覆盖既有文件|
|修正自动生成的红利或红股|`trades.list` 核对除权除息日结果 → `trades.create_auto_balance_override` 或 `delete_auto_balance_override` → 重新查询或读头寸报表|`effect_count` 与重新查询一致，普通流水未受影响|
|分析持仓结构与暴露|`analytics.asset_weight` 看权重分布，`equity_holdings`/`convertible_holdings`/`convertible_positions`/`futures_holdings`/`option_holdings` 看各类资产持仓，需要交付线下时用 `holdings_summary_file`|任务终态成功；区间内有对应资产类别持仓，且分类标准、成员权重口径已注明|
|做区间业绩归因|`analytics.create_attribution` 提交 → `analytics.attribution` 轮询同一归因 ID → 需要文件时 `analytics.export_attribution`；实时口径用 `realtime_risk_attribution`/`realtime_factor_exposure`|归因终态成功；区间、基准、模板与行业标准一一对应，删除归因是写操作|
|比较成员产品的收益、规模与相关性|`analytics.group_returns`/`group_capital_size`/`group_returns_correlation`/`group_excess_correlation`/`group_allocation`/`group_indicators`，显式给成员与区间；报告用 `group_overview_file`|任务终态成功；成员集合与区间一致，组合对比只提供组级口径|
|定位交易行为|`analytics.trading_analysis` 看区间交易，`analytics.single_trading_analysis` 看单标的，`analytics.algo_trading_performance` 看算法交易效果|任务终态成功；标的、方向、区间与算法过滤条件明确|
|配置风险预警并查看实时预警|`risk_monitor.clauses` 查现有条款 → `create_clauses`/`update_clause`/`delete_clauses` 维护 → `risk_monitor.realtime_warnings` 看当前命中；持仓负面公告用 `illegal_announcements`|条款写入后逐项确认；实时预警的 `warning_msgs`/`warning_clause_ids`/`warning_resource_ids` 与条款一致，缺键不等于无风险|
|取行情、日历与基准数据|`market_data.instruments` 查代码、`realtime_quotes` 取快照、`trading_dates` 对齐日历、`benchmarks`/`benchmark_returns` 取基准与收益；自定义基准用 `customized_benchmarks`/`create_customized_benchmark`/`update_customized_benchmark`/`delete_customized_benchmark`|自定义基准类型与权重合法（成分权重和为 1），行情与日历结果注明数据时点与日历口径|
|给某只未覆盖的代码补某日公允价|`products.get` 确认产品 → `custom_instruments.insert_fairvalues` 提交该日价格 → `products.compute_state` → `balances.get`|目标日期价格已写入且其他日期未受影响；重复日期以更新而非重复记录结束|
|把产品或组分享给同事、调整级别或收回|`permissions.list` 取授权行 → `permissions.grant` 按 `user_id` 授权或带该行 `id` 改级别，收回用 `permissions.revoke` 提交授权行 `id`；多个同类型资源一次授权用 `grant_many`|`effect_count` 与逐项 `error_messages` 核对；被授予级别不高于调用者在该资源上的级别，`admin` 不能通过本接口授予|
|列举或切换工作空间|`workspaces.list` 看当前身份可见的空间 → `workspaces.use` 按 ID 或名称切到目标空间|返回被选中的空间记录；切换后先复读目标空间内的资源再写入，切换只影响当前客户端|
|出一期周报|`analytics.weekly_report` 给成员与报告截止日 → 需要工作簿时 `analytics.weekly_net_value_report` 指定新输出路径|窗口以返回的 `data.start_date`~`data.end_date` 为准，成员按策略分入 `market_neutral` 或 `index_enhanced`；缺本周或全区间指标的成员不占条目，两类都为空不等于收益为零|

跨产品的差异口径整理仍需用已暴露查询取得相同日期和口径的数据后自行组织，并标明数据来源、差异与缺失项；对账状态、差异、人工标记与估值表自动对账已由[reconciliation](reconciliation.md)承载。净值与收益指标、持仓分析、业绩归因、交易分析、组合对比、周报、风控监控与市场数据已分别由 [analytics](analytics.md)、[risk_monitor](risk_monitor.md)、[market_data](market_data.md) 承载，资源分享与授权由 [permissions](permissions.md) 承载，工作空间的列举与切换由 [workspaces](workspaces.md) 承载。超出上列范围的模拟交易与平台运维需求，应明确说明不能通过当前 Harness 直接完成；需要判断具体能力是否可用时，先用 `rqamsh schema` 或本页导航核对操作清单，不要按 AMS 业务全貌推断。

## 19 个业务块导航

按使用顺序排列：先确定工作空间，再确定资源并管理其标注与授权，然后导入输入数据，读取输出数据，最后是预警与市场数据。

### 工作空间

确定请求所属的数据分区：列举当前身份可见的工作空间，并在会话内切换。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[workspaces](workspaces.md)|工作空间列举与切换|list/use；切换只改请求头，不改身份|

### 资源、标注与授权

确定核算边界与成员，并管理资源的标注与访问：产品、产品组、产品下的资产单元，以及标签与权限。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[products](products.md)|产品配置/生命周期|产品 list/get/create/update/delete/recompute/compute_state/name_exists/field_exists/enable_shares/valuation_report_missing_dates/uploaded_file_hashes/set_closing_entry/clear_closing_entry/create_example|
|[product_groups](product_groups.md)|成员组合与组配置|组 list/get/create/update/delete/recompute；不广播成员写入|
|[asset_units](asset_units.md)|产品下资产单元；与收益互换持仓的绑定见[资产单元与收益互换持仓](asset_units.md#asset-unit-binding)|产品下 create/list；单元 get/update；list 可省略产品|
|[tags](tags.md)|标签：产品与产品组的分组标注|list/upsert/delete；只需登录，写入与删除都是裸数组体|
|[permissions](permissions.md)|产品或产品组的授权明细与分享|产品/组 list/grant/grant_many/revoke；批量只服务同一类型，`admin` 不能通过本接口授予|

### 输入数据

把流水、报告、事件、截面与定价资料导入到已存在的产品与单元。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[trades](trades.md)|流水导入、管理、导出，以及交易类型对头寸的影响与写入校验|产品/组 list/download；产品 get/upload/upload_intraday_file/upload_settlement_file/update/delete；产品 create_auto_balance_override/delete_auto_balance_override|
|[valuation_reports](valuation_reports.md)|托管估值报告输入；产品持仓表为其另一种截面形态，见[估值表输入的两种形态](valuation_reports.md#positions-sheet-input)|产品 list/upload/delete/download/missing_dates|
|[custodian_events](custodian_events.md)|托管事件：权益、费用与科目调整输入|产品 list/latest/create/update/delete；跨产品文件 upload_file（覆盖式）|
|[unit_events](unit_events.md)|手工申购与赎回份额|产品 list/create/update/delete；自动事件只读|
|[positions_statements](positions_statements.md)|资产单元持仓单对账|单元 list/upload/delete/download；[空间级](connection.md#workspace) latest|
|[positions_sheets](positions_sheets.md)|产品持仓表截面|产品 get/upsert/delete；按日期覆盖，删除参数是日期|
|[custom_instruments](custom_instruments.md)|自定义合约与公允价|产品归属；标的记录用 instrument_id；list/get/create/update/delete/upload_fairvalue/replace_fairvalues；产品级增量写用 insert_fairvalues|
|[confirmations](confirmations.md)|导入凭证追查|产品 list/get/download；[空间级](connection.md#workspace) latest 按来源查最新导入状态|
|[reconciliation](reconciliation.md)|对账状态、差异与估值表覆盖|产品批量 list；产品 diff/mark/auto/undo_auto；单元 asset_unit_diff/positions_statement|

### 输出数据

读取头寸、指标与分析结果；这些结果依赖输入完整性和计算状态。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[balances](balances.md)|单日头寸报表、历史与盘中时序|产品/组 `get/series/previous_summary/previous_summaries/export_file/export_snapshot`；字段最早日期 `field_earliest_date/field_earliest_dates`（仅产品）；`get` 支持单资源与批量，支持 date 统一历史与实时，成员权重视图仅实时产品组|
|[analytics](analytics.md)|净值与收益指标、持仓分析、业绩归因、组合对比与交易分析|产品/组 `indicators/series/win_rate/download_series_file`（原 indicators 块，已并入）、`asset_weight`/各类 holdings/attribution 家族/`realtime_risk_attribution`/`realtime_factor_exposure`；`long_short_returns` 仅产品；组合对比 `group_indicators/group_returns/group_capital_size/group_allocation/group_returns_correlation/group_excess_correlation/group_overview_file`；周报 `weekly_report/weekly_net_value_report`；交易分析 `trading_analysis/single_trading_analysis/algo_trading_performance`|

### 预警与市场数据

按条款监控实时风险，并取行情、日历与基准等外部数据。外部数据调用与官方页面集中列在 [RQData 官方调用来源](rqdata.md)。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[risk_monitor](risk_monitor.md)|风险条款、实时预警与看板数据|条款 clauses/create_clauses/update_clause/delete_clauses；预警 realtime_warnings/illegal_announcements；看板 vix/margin_balance/etf_shares/etf_premium_rate/goodwill_ratio|
|[market_data](market_data.md)|行情、日历与基准|基准 benchmarks/benchmark_returns/realtime_benchmark_returns；自定义基准 customized_benchmarks/create/update/delete；行情 instruments/realtime_quotes；日历 trading_dates；指数期货基差 index_futures_basis|

## 字段与计算口径

承载业务功能的对象在 fields 目录保留字段说明；指标属于 API 计算结果，完整列表与公式直接放在[各操作返回说明](analytics.md#indicators-returns)，不另建指标对象字段页。[头寸字段字典](fields/balances.md)用一张五列表说明报表、摘要、持仓及分类份额；按完整英文字段路径查找，计算、筛选条件和原始输入来源都在该字段行，较长的资产分类枚举链接到文末清单。复算时沿[指标输入](analytics.md#indicator-inputs) → [资产负债汇总](fields/balances.md#balance-calculation) → [逐仓市值](fields/balances.md#position-calculation) → [价格及外部来源](fields/balances.md#position-inputs)追溯；托管现金变动见[净投入字段](fields/balances.md#balance-inputs)。不是所有指标都经过持仓；国债曲线、基准行情及申赎统计见[指标特殊来源](analytics.md#external-inputs)，各外部调用的官方页面见 [RQData 官方调用来源](rqdata.md)。

- [产品、产品组及账户/基准/分类份额嵌套字段](fields/products.md)
- [交易流水全部字段](fields/trades.md)
- [头寸：报表、摘要、positions、分类份额及品种 extras](fields/balances.md)
- [估值报告、嵌套持仓/元数据与产品持仓表字段](fields/valuation_reports.md)
- [自定义标的与公允价](fields/custom_instruments.md)
- [资产单元与持仓单](fields/asset_units.md)
- [托管事件字段](fields/custodian_events.md)
- [份额事件与逐日份额变动](fields/unit_events.md)
- [导入凭证、逐项结果与源文件](fields/confirmations.md)
- [其他数据结构与跨块口径](fields/others.md)
- [RQData 官方调用来源](rqdata.md)

## 口径速查：容易踩的十三条（一行一句，详情点权威页）

判定与核算前先扫一眼这张表；每条只写结论，口径的完整说明在链接页，避免两处维护。

|容易踩的地方|结论|权威页|
|---|---|---|
|收益窗口语义|`returns_summary.this_week`/`this_year` 是**向前滚动 1 周 / 1 年**（不是自然周 / 自然年度），`total` 才是区间累计；要自然窗口用 `balances.series` 的日收益复利|[指标公式](analytics.md#indicators-returns)|
|实时 vs 历史|`date` 省略或等于北京时间当天 = 实时语义（可能未结算）；过去日期 = 历史；未来日期拒绝。当天结果不能冒充日终历史|[头寸报表](balances.md)|
|分类节点的行业基准|`shenwan_level_*`/`zx_level_*` 节点上的 `benchmark_returns`/`excess_returns` 是**当前行情快照**，与请求 `date` 无关；历史行业超额走归因|[头寸字段](fields/balances.md)|
|风格暴露的"历史"|实时截面用 `realtime_factor_exposure`；逐日历史暴露走归因 `result.attribution.factor_exposure`（异步任务）|[业绩归因](analytics.md#create_attribution)|
|扩指标只返回值|`extra_indicators` 白名单内的指标返回**只有值**，没有公式文本/版本/参数；白名单外的名字被静默忽略，不报错|[指标公式](analytics.md#indicators-returns)|
|产品权限位|`products.list` 返回的 `permissions` 由服务端下发，客户端**不重算**；不要用本地权限推导判断可写性|[产品](products.md)|
|工作空间列举与切换|列举走 AMS 用户接口 `/api/user/v1/workspaces`，未登录时返回 HTTP 200 与 `code` 非 0（不是 401）；切换只改请求头，同一会话即可换分区|[工作空间](workspaces.md)|
|权限级别顺序|六个级别不是按名字排高低：`read_import_data`（三级）高于 `read_position`（二级）；路由要求的是下限，高级别可通过低级别要求的读取|[权限级别](permissions.md#权限级别)|
|写入的必填与过滤|`products.create` 在所有数据源上运行期必填 `start_date`；`update` 没有字段白名单——提交未声明的键会直接报错，已声明的只读字段反而会被写入|[产品](products.md)|
|导入流水的价格口径|`price` 填**不复权**实际成交价；持仓市值与净值按不复权行情算，用复权价导入会让买入金额与估值价格不同口径，凭空造出收益或亏损|[流水导入](trades.md#upload)|
|名称与批量形态|`resource` 必须精确匹配 ID 或名称（不精确报「不存在或不可访问」，不做模糊匹配）；`balances.get` 的数组形态只接受 `fields`，`date`/`classifier`/`benchmark_id` 与非默认布尔参数传入即报 `invalid_argument`|[单字符串资源选择器](connection.md#单字符串资源选择器)|
|周报窗口与分桶|`weekly_report` 的窗口是报告截止日所在自然周（周一非交易日顺延），起点随 `data.start_date` 下发；成员按策略分入 `market_neutral` 与 `index_enhanced`，策略为多重时全属中性类才进前者|[周报数据](analytics.md#周报数据)|
|授权批量形态|`grant_many` 一次只服务同一类型（产品与产品组不混批），批量项不接受 `permission_id`；改既有授权行的级别要用 `grant` 带该行 `id`|[资源权限](permissions.md)|

## 必要边界

本指南只覆盖 `rqamsh` 这一类能力（AMS 业务数据的取与受控写入）：它把服务端已算好、已落库的数据取回来，并做受控写入，不提供一站式报告、检索、调度、渲染或诊断封装——这类需求不是本项目缺口。第三方系统（企业微信、邮件、办公套件等）的对接与调用方自己的加工（渲染、调度、推送）不在这里：前者按对端官方文档自行实现，后者由 Agent 组合。三类的定义与归属表见[金律](#金律三类能力拼装本项目只做第三点)，定位与需求拆解见 [README](../README.md)。

判断一项需求是否落在本指南范围，问三步：

1. **数据可得吗**：所需原始数据是否有对应操作与字段；没有就是真缺口，如实说明。
2. **谁能加工、谁来对接**：把原始数据加工成目标形态——排序取前 N、区间差分、按权重算贡献、名称模糊匹配与打分、文字摘要、Markdown/DOCX/PNG 渲染、多产品循环合并、序列拼接、定时触发与推送——是调用方（Agent）的职责；与第三方系统对接，是调用方查对端官方文档后自行实现的职责。两者都不是本项目缺能力。
3. **只剩真缺口时**才提示：服务端未持久化的配置版本与审批元数据、需要服务端规则引擎的判定、外部系统凭证与公网入口。

不要把第 2 类算作「AMS/本项目缺 X」；也不要因为缺第 1 类就不说明替代路径——应给出「用哪几个操作能拼出什么、哪些由 Agent 补」。

- 本项目不代办登录，也不接收账号密码。向 AMS 管理员取得服务地址与可用的令牌（当前部署是登录会话 cookie，见[登录会话](connection.md#session-injection)）；工作空间默认使用可见空间中的第一个，需要时再切换，见[工作空间](workspaces.md)；本机地址也可能连接正式业务数据，客户端资源筛选不能替代服务端授权。
- 写入前确认身份、唯一目标、权限及覆盖范围；删除不等于物理擦除历史数据。重算会改变结果，不是只读诊断操作。
- 导入成功、任务完成和估值就绪是不同阶段。检查逐项错误与计算状态，再读回同一日期的数据；等待超时不代表任务取消，保留任务 ID 并先确认原请求结果，不要直接重放写入。
- 查询为空、字段缺失或 `null` 不表示零。新产品尚无历史头寸报表时，头寸报表、持仓和指标可能不可用；应核实真实起始日及初始化数据，而不是为消除错误编造历史。
- `balances.get` 的 `classifier=None` 返回平铺头寸，非空分类器返回分层头寸；空字符串或纯空白分类器会被拒绝。`date=None` 或北京时间当天为实时语义，过去日期为历史，未来日期拒绝。`balances.series` 保留自身返回形状，不能套用单日的结构假设。
- 券商/托管文件模板须符合对应导入要求；持仓单同日覆盖、估值表覆盖和流水导入的规则不同。公允价日期应唯一，价格全量替换须包含要保留的完整区间；下载使用新输出文件，不覆盖已有文件。
- 分析、组合对比与导出通常耗时较久；等待超时不代表任务取消，先确认原请求结果。组合对比只提供一套组级口径，同一需求不要与单产品结果混用。
- 自定义基准的创建与更新都是覆盖语义，删除不可回滚；风险条款写入后立即影响后续预警，3 级及以上必须提供 Webhook 地址。
- 业绩解释需保留产品/组、区间、基准、日历和估值口径。仅凭一次公开返回不能重建全部历史行情、汇率、份额及权益事件；不能把所有收益都解释为成交价差。
