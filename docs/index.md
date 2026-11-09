# AMS 业务与 API 使用指南

## 金律：三类能力拼装，rqamsh 提供第三点

`Agent 自身能力 + 第三方能力 + rqamsh 业务数据管理能力 = 满足用户需求`

拆解用户需求时，每一项都要归到三类之一，归属决定谁来做、谁维护：

|归属|范围|谁做|本指南的覆盖|
|---|---|---|---|
|**rqamsh（本项目）**|AMS 业务数据的读与受控写入：产品、流水、头寸、指标、归因、对账、托管与份额事件等|本项目|本指南逐页给出参数、返回、口径与副作用；行为由 `rqamsh` 的契约测试保证|
|**第三方能力**|企业微信、邮件、办公套件、行情源、外部存储等外部系统|对接方|**不实现、不测试、不封装**：按对端官方文档自行实现，本项目只保证给它们提供数据的那一段（即上一行的操作）|
|**Agent 自身能力**|排序取前 N、区间差分、加权贡献、名称模糊匹配、文字摘要、Markdown/DOCX/PNG 渲染、多产品合并、定时触发与推送|调用方|**不实现、不测试**：由调用方按需组合|

只有三类都覆盖不到才算真缺口：**取不到的数据**（服务端未持久化的配置版本或审批元数据、需要服务端规则引擎的判定）与**外部凭证或公网入口**。反过来，第三类没有现成封装、第二类没有现成对接，都不是本项目的缺口；而任何「取数 → 加工 → 投递」的需求，取数这一段必须落在本指南的操作上，加工与投递由调用方完成。

<a id="valuation-lifecycle"></a>
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
|变动输入|交易流水、托管事件、份额事件、交割单|描述成交、资金、权益或份额变化；能否接入及如何进入估值取决于产品数据源与业务配置|
|截面输入|估值表、持仓单、起始日头寸|提供某日已知状态，用于建立起点、校准或对账；不自动等同于完整估值结果|

估值表可提供某日净资产、份额净值和持仓截面；是否直接采用、校准或以估值表覆盖已有结果，见[估值表覆盖设置](reconciliation.md#valuation-report-overwrite-setting)。持仓单有的只用于数量对账，不含完整资产负债和净值，不能全部替代估值。起始日头寸也必须来自真实业务数据，不能为补齐查询而编造。

### 逐日推进：今天的结果承接之前的状态

产品的估值不是每天互不相关地计算。上一日的持仓、现金、负债和份额状态，是下一日计算的基础；当天处理完交易、事件、费用与估值价格后，形成的新状态又传给后一天。历史头寸链按自然日逐日推进，没有成交的日期也不能直接跳过；这与收益、风险指标统计时采用交易日还是自然日日历是两回事，统计口径见[指标计算口径](analytics/metrics.md#indicators-returns)。

因此，查询某日结果时，可能需要先补齐它依赖的前序估值。例如，所需历史只准备到周二，查询周五时可能要先依次计算周三、周四，再得到周五结果。这里的顺序依赖发生在同一产品的日期链上，不表示所有产品必须排成一条队列计算。

逐日推进也不等于每次从产品成立日重算。已有有效头寸可以作为起点，从其后继续计算；起始日头寸与被采用的估值表、持仓表如何建立或校准状态，仍取决于对应输入规则。

### 历史更正：改过去可能影响后续结果

补录或更正过去某日的交易、事件、价格或估值输入，可能改变当天状态，并沿头寸链影响后续日期。因此，修改成功后不应只核对当天，也不能直接把尚未更新的后续结果交付给用户；应核对本次受影响范围，等待计算并读回目标日期的结果。

影响范围取决于产品数据源、输入采用方式及[封账规则](products.md#set_closing_entry)，不是任何更正都从成立日全量重算；估值表也不是上传后必然覆盖系统结果。

### 按需计算：查询有时也在准备结果

部分结果不是始终提前生成，而是在需要读取时检查是否可用；缺少必要估值时，读取可能触发补算或结果准备，这称为惰性计算。它不是“只有查询才会计算”：写入数据也可能触发计算，具体以各操作说明为准。

已有可用结果会被复用；历史输入被更正、需要补齐前序日期或所需截面尚未产出时，则可能需要重新准备。因此，首次查询、重复查询以及更正数据后的查询，等待时间可能不同，不能仅凭快慢判断结果是否正确或系统是否异常。

含港股头寸的产品还有定时估值刷新：按服务时区，在 A 股交易日 `05:30` 与 `22:30` 提交当日重算，候选产品按前一自然日的港股持仓筛选；不是从前一交易日选取，也不表示重算上一日。到达提交时点不代表结果已完成，仍需核对业务日期与实际结果。这与港股通在途款项的到账和换汇时点不是同一规则，后者见[在途类字段](fields/balances.md#in-transit-fields)。

批量查询还可能先返回已准备好的部分产品。暂未返回不等于没有资产，也不能据此断定每一项都已进入计算队列；缺输入和明确失败不能靠一直等待解决。等待、诊断及停止条件统一见[未就绪与缺输入](connection.md#unready-inputs)。

### 输出：状态、业绩与核对

历史估值、实时截面和分析结果不是同一份产物。实时截面依赖相应的历史头寸基础，再结合盘中变动和实时行情生成；指标、归因还可能需要进一步准备。历史估值正常，不保证所需实时截面已经可读；头寸可读，也不保证所需分析已经完成。

AMS 的业务能力包括查看头寸和资产负债、净值与指标及基准比较，进行归因、交易分析、投资概览，并支持对账和周报等工作。它们都依赖输入完整性、日期和计算口径；输入文件已导入不代表后续估值和分析已就绪。完成用户任务要检查实际所需的产物，而不只是某次调用成功，见[任务完成条件](demo/README.md#task-readiness)。

## 一条主线：把业务块放回产品生命周期

AMS 的业务不是一组并列模块。它们围绕产品的一条流水线发生；先定位当前阶段，再选操作：

```text
工作空间
  → 产品 / 产品组 / 资产单元
  → 输入：信号 → 流水，估值表、托管/份额事件、持仓单、持仓表、公允价
  → 计算状态
  → 头寸 / 净值 / 指标
  → 对账 / 封账
  → 分析 / 监控
        ↑ 差异、缺件、失败项回到输入补齐
```

|阶段|用户问题|主要业务块/操作|完成标志|
|---|---|---|---|
|0 分区|在哪个数据分区做？|`workspaces`|当前身份可见，分区正确|
|1 定边界|这是产品、产品组，还是产品内的资产单元？|`products`、`product_groups`、`asset_units`|产品的数据源/起始日/账户/基准明确；产品组成员与权重明确；资产单元归属产品明确，目前用于收益互换底层组合|
|2 进输入|今天有什么变动或截面要进来？|`trades`、`paper_trading`、`valuation_reports`、`custodian_events`、`unit_events`、`positions_statements`、`positions_sheets`、`custom_instruments`|逐项结果无未解释失败；文件、日期、覆盖范围明确|
|3 等计算|估值算完了吗？|`products.compute_state`（产品）；产品组按组查询等待|产品状态为 `normal` 仅说明计算状态，仍需进入下一阶段读回所需结果；组结果按组读取；运行态不是成功，未就绪按[等待规则](connection.md#unready-inputs)处理|
|4 读结果|头寸、净值、指标是多少？|`balances`、`analytics`|对象、实际业务日期、来源、所需字段与请求集合逐项核对；未完成项有明确失败原因、缺输入诊断或达到等待上限的记录，不能把部分结果交付成完整结果|
|5 核对与封账|和托管对得上吗？能封账吗？|`reconciliation`、`products.set_closing_entry/clear_closing_entry`|差异有解释；封账日正确；读回一致|
|6 分析与监控|为什么涨跌？风险在哪？|`analytics`、`risk_monitor`|区间、基准、模板、口径明确；条款与命中一致|
|7 协作与组织|谁能看、怎么分组？|`permissions`、`tags`|授权、标签可追溯|

横向支撑不单独占阶段，但影响全链：

- `market_data`：行情、日历、基准，供分析、基准比较与交易判断使用；不直接参与产品估值。
- `confirmations`：追查导入批次与逐项结果，是审计轨，不是估值步骤。

`workspaces` 是阶段 0 的前提，`permissions` / `tags` 在阶段 7 首次配置但作用贯穿全链；`custom_instruments` 是阶段 2 的定价输入。它们已在阶段表中出现，不再重复列为横切块。

三条使用规则：

1. **先定位阶段，再选操作。** 不知道用户说的是哪一步时，先用这张表定位；不要从操作清单反推业务。
2. **输入成功、计算就绪、结果可交付是三件事。** 导入成功不代表估值完成；`compute_state` 就绪也不代表头寸已核对。
3. **写操作不能替代上游补齐。** 对账标记、授权、标签不会替你补估值；差异或失败项要回到上游输入补齐，再重算、再读回。

`业务块导航` 是块级索引，`常见场景` 是按用户目标直接找步骤；这张主线表用于“不知道目标属于哪一步”时定位。三者不互相替代。

## 再理解本项目：Agent 操作 AMS 的入口

`rqams-harness` 为 AMS 用户 Agent 提供 Python API 与 CLI 操作入口；业务数据和计算由 AMS 管理，本项目不另建一套估值系统。当前公开能力以 `rqamsh schema` 为准，只覆盖下方导航列出的范围：可导入交易流水、交割单、估值报告、资产单元持仓单、托管事件、份额事件和产品持仓表，可接收模拟交易信号并生成流水，可读取头寸报表、指标与分析结果，可查询风险条款、实时预警、市场行情与基准数据，可追查导入凭证，可读取与调整资源授权、生成周报、读取成员工作空间并选择目标空间。AMS 已有、但本 Harness 仍无对应操作的能力包括（不限于）：资产单元的可用持仓（候选与绑定口径见[资产单元与收益互换持仓](asset_units.md#asset-unit-binding)）与期货手续费参数、自定义指标注册表、平台与运维端点（用户设置、上传会话等）。不要把 AMS 的整体业务介绍当成可直接调用的 API 清单，也不要将读取数据后自行整理的报告称为 AMS 原生报告。

接入与异常处理见[连接、身份、等待与错误](connection.md)。`rqamsh schema` 可离线查询当前完整能力；其中 `balances.get` 只显示统一单日签名及其历史自定义基准限制。用户说法不确定对应哪个对象或操作时，按[学习案例与共用判断](demo/README.md)拆解目标：确认边界与副作用，必要时澄清，写入核对计划及已有授权；不靠关键词匹配，也不要求每个会话重走固定步骤。CLI 将方法名中的下划线替换为连字符，`data` 使用 `--input`（别名 `--data`）。每个业务页给出完整参数、默认值与覆盖规则，并用返回字段表列出该操作实际返回的数据结构；表头、路径写法与通用返回结构的约定见[返回值与返回字段表](connection.md#return-fields)。

产品是独立核算边界；账户是产品内的流水归属配置，不是可独立选择的资源。产品组用于汇总成员，不是批量写入口。资产单元属于一个产品，目前只用于收益互换的底层组合；其持仓单与产品流水、托管估值报告不能互相替代。

## 核心学习案例与其他业务场景

学习如何把本页的业务与各页 API 串起来，先看[核心学习案例](demo/README.md)：从流水、估值表导入进入，以对账展示对象定位、状态解释、缺件补齐、差异处理和结果复查；[收益异常定位](demo/returns-diagnosis/README.md)从用户质疑的指标追到口径、异常日期和原始业务输入。这里只保留业务主线、机制与块导航，不维护全量任务及执行状态；下表中的其他场景是按需业务指引，不是待完成的案例清单，也不把缺少样例解释为缺少 API。

先确认用户目标、获授权的唯一资源、业务日期或区间、数据源及交付形式。写入前确认覆盖范围并取得授权；下表中的写入方法名是操作指引，不是执行授权。

|用户想做什么|API 步骤与处理方式|完成条件|
|---|---|---|
|建立产品并开始估值|`products.list/get` 查重和确认配置；确需新建时用 `products.name_exists/create`，模拟交易产品改用 `paper_trading.create` 按模板创建；再按产品类型准备账户、起始日、份额与基准 → 导入对应业务数据 → `products.compute_state` → `balances.get`|检查创建与导入错误，核对产品配置；计算状态为 `normal`，同日头寸与净值可读且符合输入。创建成功不等于已有估值|
|做区间业绩归因|`analytics.create_attribution` 提交 → `analytics.attribution` 轮询同一归因 ID → 需要文件时 `analytics.export_attribution`；实时口径用 `realtime_risk_attribution`/`realtime_factor_exposure`|归因终态成功；区间、基准、模板与行业标准一一对应，删除归因是写操作|

跨产品的差异口径整理仍需用已暴露查询取得相同日期和口径的数据后自行组织，并标明数据来源、差异与缺失项；对账状态、差异、人工标记与估值表自动对账已由[reconciliation](reconciliation.md)承载。净值与收益指标、持仓分析、业绩归因、交易分析、组合对比、周报、风控监控与市场数据已分别由 [analytics](analytics/index.md)、[risk_monitor](risk_monitor.md)、[market_data](market_data.md) 承载，资源分享与授权由 [permissions](permissions.md) 承载，成员工作空间与目标空间选择由 [workspaces](workspaces.md) 承载。超出上列范围的平台运维需求，应明确说明不能通过当前 Harness 直接完成；需要判断具体能力是否可用时，先用 `rqamsh schema` 或本页导航核对操作清单，不要按 AMS 业务全貌推断。

## 业务块导航

以下按业务块类型分组，便于按块查参数与操作；跨块的发生顺序见上面的“一条主线”。分组不是严格执行顺序：例如对账与输入数据同组，实际发生在估值和头寸之后；权限、标签在阶段 7 首次配置但作用贯穿全链，凭证是横切审计轨。

### 工作空间

确定请求所属的数据分区：读取当前用户的成员工作空间，并为后续请求明确目标空间。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[workspaces](workspaces.md)|成员工作空间与目标空间选择|list/use；列出成员空间并按成员 ID 选择目标分区，未指定时默认使用首项，选择不增加业务权限|

### 资源、标注与授权

确定核算边界与成员，并管理资源的标注与访问：产品、产品组、产品下的资产单元（目前用于收益互换），以及标签与权限。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[products](products.md)|产品配置/生命周期|产品 list/get/create/update/delete/recompute/compute_state/name_exists/field_exists/enable_shares/valuation_report_missing_dates/uploaded_file_hashes/set_closing_entry/clear_closing_entry/create_example|
|[product_groups](product_groups.md)|成员组合与组配置|组 list/get/create/update/delete/recompute；不广播成员写入|
|[asset_units](asset_units.md)|产品下资产单元，目前承载收益互换底层组合；绑定见[资产单元与收益互换持仓](asset_units.md#asset-unit-binding)|产品下 create/list；单元 get/update；list 可省略产品|
|[tags](tags.md)|标签：产品与产品组的分组标注|list/upsert/delete；只需登录，写入与删除都是裸数组体|
|[permissions](permissions.md)|产品或产品组的授权明细与分享|产品/组 list/grant/grant_many/revoke；批量只服务同一类型，`admin` 不能通过本接口授予|

### 输入数据

把流水、报告、事件、截面与定价资料导入到已存在的产品与单元；模拟交易信号进入对应产品后生成流水。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[trades](trades.md)|流水导入、管理、导出，以及交易类型对头寸的影响与写入校验|产品/组 list/download；产品 get/upload/upload_intraday_file/upload_settlement_file/update/delete；产品 create_auto_balance_override/delete_auto_balance_override|
|[paper_trading](paper_trading.md)|模拟交易：按模板创建产品，信号进入模拟撮合后生成流水|create/get/list/upload_signals/list_signals/delete_signals/recompute/delete；对外按模板区分，不暴露实现版本|
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
|[analytics](analytics/index.md)|净值与收益指标、持仓分析、业绩归因、组合对比与交易分析|四页：[净值与收益指标](analytics/metrics.md) 产品/组 `indicators/series/win_rate/download_series_file`，`long_short_returns` 仅产品；[持仓分析](analytics/holdings_analysis.md) `asset_weight`、各类 holdings、`holdings_summary_file`；[业绩归因](analytics/attribution.md) attribution 家族、`realtime_risk_attribution`、`realtime_factor_exposure`；[组合对比与交易分析](analytics/portfolio_analysis.md) `group_*`、`weekly_report/weekly_net_value_report`、`trading_analysis` 家族|

### 预警与市场数据

按条款监控实时风险，并取行情、日历与基准等外部数据。外部数据调用与官方页面集中列在 [RQData 官方调用来源](rqdata.md)。

|业务块|业务定位|支持目标与操作|
|---|---|---|
|[risk_monitor](risk_monitor.md)|风险条款、实时预警与看板数据|条款 clauses/create_clauses/update_clause/delete_clauses；预警 realtime_warnings/illegal_announcements；看板 vix/margin_balance/etf_shares/etf_premium_rate/goodwill_ratio|
|[market_data](market_data.md)|行情、日历与基准|基准 benchmarks/benchmark_returns/realtime_benchmark_returns；自定义基准 customized_benchmarks/create/update/delete；行情 instruments/realtime_quotes；日历 trading_dates；指数期货基差 index_futures_basis|

遇到净值、前十、行业、风格和风险混合在同一句请求里的任务，先按 [analytics 的需求选路表](analytics/index.md#从用户需求到操作)区分结果族，再参考[单产品综合分析案例](demo/product-briefing/README.md)组织取数和比较；不把业务问题拆成互不关联的逐接口调用。

## 字段与计算口径

承载业务功能的对象在 fields 目录保留字段说明；指标属于 API 计算结果，完整列表与公式直接放在[各操作返回说明](analytics/metrics.md#indicators-returns)，不另建指标对象字段页。[头寸字段字典](fields/balances.md)用一张五列表说明报表、摘要、持仓及分类份额；按完整英文字段路径查找，计算、筛选条件和原始输入来源都在该字段行，较长的资产分类枚举链接到文末清单。复算时沿[指标输入](analytics/metrics.md#indicator-inputs) → [资产负债汇总](fields/balances.md#balance-calculation) → [逐仓市值](fields/balances.md#position-calculation) → [价格及外部来源](fields/balances.md#position-inputs)追溯；托管现金变动见[净投入字段](fields/balances.md#balance-inputs)。不是所有指标都经过持仓；国债曲线、基准行情及申赎统计见[指标特殊来源](analytics/metrics.md#external-inputs)，各外部调用的官方页面见 [RQData 官方调用来源](rqdata.md)。

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
|收益窗口语义|`returns_summary.this_week`/`this_year` 是**向前滚动 1 周 / 1 年**（不是自然周 / 自然年度），`total` 才是区间累计；要自然窗口用 `balances.series` 的日收益复利|[指标公式](analytics/metrics.md#indicators-returns)|
|实时 vs 历史|`date` 省略或等于北京时间当天 = 实时语义（可能未结算）；过去日期 = 历史；未来日期拒绝。当天结果不能冒充日终历史|[头寸报表](balances.md)|
|分类节点的行业基准|`shenwan_level_*`/`zx_level_*` 节点上的 `benchmark_returns`/`excess_returns` 是**当前行情快照**，与请求 `date` 无关；历史行业超额走归因|[头寸字段](fields/balances.md)|
|风格暴露的"历史"|实时截面用 `realtime_factor_exposure`；逐日历史暴露走归因 `result.attribution.factor_exposure`（异步任务）|[业绩归因](analytics/attribution.md#create_attribution)|
|扩指标只返回值|`extra_indicators` 白名单内的指标返回**只有值**，没有公式文本/版本/参数；白名单外的名字被静默忽略，不报错|[指标公式](analytics/metrics.md#indicators-returns)|
|产品权限位|`products.list` 返回的 `permissions` 由 AMS 平台按请求人权限生成，客户端**不重算**；不要用本地权限推导判断可写性|[产品](products.md)|
|成员空间不等于授权|`workspaces.list` 列的是当前用户所属空间，`use` 只改目标分区；能否读写由服务端按成员、AMS 权益与资源权限判定，不能靠改请求头扩大授权|[工作空间](workspaces.md#use)|
|权限级别顺序|六个级别不是按名字排高低：`read_import_data`（三级）高于 `read_position`（二级）；操作要求的是下限，高级别可通过低级别要求的读取|[权限级别](permissions.md#权限级别)|
|写入的必填与过滤|`products.create` 在所有数据源上运行期必填 `start_date`；`update` 没有字段白名单——提交未声明的键会直接报错，已声明的只读字段反而会被写入|[产品](products.md)|
|导入流水的价格口径|`price` 填**不复权**实际成交价；持仓市值与净值按不复权行情算，用复权价导入会让买入金额与估值价格不同口径，凭空造出收益或亏损|[流水导入](trades.md#upload)|
|名称与批量形态|`resource` 必须精确匹配 ID 或名称（不精确报「不存在或不可访问」，不做模糊匹配）；`balances.get` 的数组形态只接受 `fields`，`date`/`classifier`/`benchmark_id` 与非默认布尔参数传入即报 `invalid_argument`|[单字符串资源选择器](connection.md#单字符串资源选择器)|
|周报窗口与分桶|`weekly_report` 的窗口是报告截止日所在自然周（周一非交易日顺延），起点随 `data.start_date` 下发；成员按策略分入 `market_neutral` 与 `index_enhanced`，策略为多重时全属中性类才进前者|[周报数据](analytics/portfolio_analysis.md#周报数据)|
|授权批量形态|`grant_many` 一次只服务同一类型（产品与产品组不混批），批量项不接受 `permission_id`；改既有授权行的级别要用 `grant` 带该行 `id`|[资源权限](permissions.md)|

## 必要边界

本指南只覆盖 `rqamsh` 这一类能力（AMS 业务数据的取与受控写入）：它把服务端已算好、已落库的数据取回来，并做受控写入，不提供一站式报告、检索、调度、渲染或诊断封装——这类需求不是本项目缺口。第三方系统（企业微信、邮件、办公套件等）的对接与调用方自己的加工（渲染、调度、推送）不在这里：前者按对端官方文档自行实现，后者由 Agent 组合。三类的定义与归属表见[金律](#金律三类能力拼装rqamsh-提供第三点)，定位与需求拆解见[学习案例与共用判断](demo/README.md)。

判断一项需求是否落在本指南范围，问三步：

1. **数据可得吗**：所需原始数据是否有对应操作与字段；没有就是真缺口，如实说明。
2. **谁能加工、谁来对接**：把原始数据加工成目标形态——排序取前 N、区间差分、按权重算贡献、名称模糊匹配与打分、文字摘要、Markdown/DOCX/PNG 渲染、多产品循环合并、序列拼接、定时触发与推送——是调用方（Agent）的职责；与第三方系统对接，是调用方查对端官方文档后自行实现的职责。两者都不是本项目缺能力。
3. **只剩真缺口时**才提示：服务端未持久化的配置版本与审批元数据、需要服务端规则引擎的判定、外部系统凭证与公网入口。

不要把第 2 类算作「AMS/本项目缺 X」；也不要因为缺第 1 类就不说明替代路径——应给出「用哪几个操作能拼出什么、哪些由 Agent 补」。

- 本项目不代办账号密码登录，也不接收账号密码；认证只有 Bearer 令牌。需要接入或查询业务数据且本机缺身份时，由 Agent 执行首个相关只读 CLI 命令触发本机网页登录，用户只在页面填写 key，校验保存后继续原命令；只问概念不触发登录，已有安全身份直接复用，不因新会话重复登录。仅在明确的远程、容器、无图形或无人值守环境才设 `RQAMSH_AUTO_LOGIN=0`，并从权限受限文件或运行环境注入 `--token @文件` / `RQAMSH_TOKEN`；捕获输出或非 TTY 本身不证明没有浏览器。不要让用户把令牌贴进对话或写进命令字面参数。默认连接 RQAMS 官方地址 `https://www.ricequant.com`，私有化部署必须显式覆盖地址；令牌的取得、保存与优先级见[认证与令牌](connection.md#token-auth)。默认工作空间按显式参数、保存的最后选择、成员列表首项依次解析：未指定且无可沿用保存空间时使用服务端当次返回首项（不排序、不按权益筛选），首项缺少权益由服务端拒绝而不换后项，没有成员空间时报无可用空间；注入令牌不继承也不改写保存的空间。成员空间列表不等于 AMS 权益，见[工作空间](workspaces.md)。客户端资源筛选不能替代服务端授权。
- 写入前确认身份、唯一目标、权限及覆盖范围；删除不等于物理擦除历史数据。重算会改变结果，不是只读诊断操作。
- 导入成功、任务完成和估值就绪是不同阶段。检查逐项错误与计算状态，再读回同一日期的数据；等待超时不代表任务取消，保留任务 ID 并先确认原请求结果，不要直接重放写入。
- 查询为空、字段缺失或 `null` 不表示零。新产品尚无历史头寸报表时，头寸报表、持仓和指标可能不可用；应核实真实起始日及初始化数据，而不是为消除错误编造历史。
- `balances.get` 的 `classifier=None` 返回平铺头寸，非空分类器返回分层头寸；空字符串或纯空白分类器会被拒绝。`date=None` 或北京时间当天为实时语义，过去日期为历史，未来日期拒绝。`balances.series` 保留自身返回形状，不能套用单日的结构假设。
- 券商/托管文件模板须符合对应导入要求；持仓单同日覆盖、估值表覆盖和流水导入的规则不同。公允价日期应唯一，价格全量替换须包含要保留的完整区间；下载使用新输出文件，不覆盖已有文件。
- 分析、组合对比与导出通常耗时较久；等待超时不代表任务取消，先确认原请求结果。组合对比只提供一套组级口径，同一需求不要与单产品结果混用。
- 自定义基准的创建与更新都是覆盖语义，删除不可回滚；风险条款写入后立即影响后续预警，3 级及以上必须提供 Webhook 地址。
- 业绩解释需保留产品/组、区间、基准、日历和估值口径。仅凭一次公开返回不能重建全部历史行情、汇率、份额及权益事件；不能把所有收益都解释为成交价差。
- 批量或长区间正式执行前，先用一个产品、一个接口做一次小样验证，确认参数与返回形态；参数与格式不确定时先读对应业务页，不要用失败重试试出参数。
- 取数与聚合写成脚本文件再执行，不用内联单行命令（避开 shell 的转义与引号歧义）；产物落盘后复读内容、条数与日期，再交付。
- 交付时先给已核验的核心结论，未核验或缺项的部分单列；用字段关系做一次守恒核对（净资产 = 资产 − 负债、单位净值 = 净资产 ÷ 份额，见[头寸字段](fields/balances.md#total-equity)）。
