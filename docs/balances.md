# 头寸报表 balances

`balances` 的公开读取操作分四类：单日入口 `get`（单资源或批量）与历史/盘中时序 `series`，`previous_summary`、`previous_summaries` 读取上一交易日概览，`export_file`、`export_snapshot` 导出工作簿，`field_earliest_date`、`field_earliest_dates` 查询字段最早存在日期。`get` 根据 `date`、资源类型和请求参数选择历史或实时底层查询；调用方不选择模式，也不需要知道底层 HTTP 路由。该收敛只发生在 Harness 客户端，AMS 服务端既有 HTTP/YApi 端点不改动。

头寸报表描述产品或产品组某一业务时点的资产、负债、净资产、净值和持仓。实时结果用于观察最新可用估值状态；历史结果用于可重复的日终核对。字段含义、计算口径和分类树见[头寸字段与计算](fields/balances.md)，区间业绩分析见[指标公式](analytics/metrics.md#indicators-returns)。

## 从用户需求到操作

|用户需求|操作与输入|结果判读|
|---|---|---|
|核对过去某日净资产、净值和持仓|`get`，传过去的 `date`；不传 `fields` 取得完整报表|核对返回业务日期、权益、净值和 `positions`；`null` 不等于 `0`。|
|查看今天或当前可用状态|`get`，省略 `date` 或传北京时间当天；按需传 `fields`、`classifier`、`drilldown`|核对实际返回日期、`update_time`、结算状态和分类/穿透口径；请求时间不是行情时间。|
|解释产品组各成员及权重|实时 `get`，资源为产品组，传 `include_component_weight_view=True`|按成员产品 ID→成员对象读取；保留每个成员的 `product_weight` 和错误信息，不能摊平成一个组报表。|
|只交付少数顶层字段|`get`，传非空 `fields`，例如 `['total_equity', 'unit_net_value']`|只使用实际返回的字段；服务端缺失字段不补 `null`，已返回的 `null` 原样保留。|
|查看历史变化或逐日对账|`series`，明确 `start_date`/`end_date`；用 `position_fields` 选择额外持仓字段|按逐日结果检查日期覆盖与缺失；不能把缺失日期补成零头寸报表。|
|快速查看最近一个已结算交易日的概览|`previous_summary`（单个）或 `previous_summaries`（批量）|核对返回资源与概览字段；估值未就位的资源不出现，批量失败项在 `error_messages` 中。概览用于观察最近一个已结算交易日，不能替代当日实时结果或指定历史日期的结果。|
|把持仓全景交给线下核对|`export_file` 指定输出路径，必要时传过去的 `date`|文件已落盘且字节数与服务端一致；目标文件已存在时不覆盖。|
|一次读取多只产品/产品组的当天截面|`get`，第一个参数传数组；只给 `fields`|按资源 ID 读取结果，并检查 `pending_valuation` 与 `error_messages` 是否都为空。|
|导出实时监控快照|单资源用 `export_snapshot(resource, output)`；多资源传数组并用 `previous_trading_day` 取上一交易日口径|文件已落盘；单资源与多资源接受的参数不同，交叉传入会被拒绝。|
|看盘中逐时点变动|`series`，省略 `end_date`（盘中分支），按需传 `benchmark_id`|得到当日分时序列 `asset_series` 与区间起止；盘中序列没有 `start_date`、也不接受 `position_fields`。|
|确认某字段从哪天开始有数据|`field_earliest_date` 或 `field_earliest_dates`，只传产品|返回最早日期；产品组会被拒绝，不能把空结果当成「从未有数据」。|

先确认产品已有匹配数据源的流水或估值报告、产品组已配置成员。无数据、字段缺失、等待超时或未就绪时应报告缺口，不输出零净资产结论，也不得改用上一交易日概览或邻近日期报表替代当日结果。需要可重复对账时必须传过去的业务日期；当天和未传日期都是实时语义，不能用来冒充某日的历史结算结果。

## API 使用约定

Python 与 CLI 参数一一对应；连接、等待和公共错误处理见[连接说明](connection.md)。`resource` 是当前身份可访问的唯一产品或产品组 ID/名称；名称多匹配时先用 ID 消歧。该业务块只读计算结果，不新增、修改或删除持仓，也不下单。头寸字段的定义、计算、精度和输入链统一见[头寸字段字典](fields/balances.md#balance-calculation)；修正估值应按授权修改相应[流水](trades.md)、[估值报告](valuation_reports.md)或产品配置，再读取受影响日期。

普通结果是报表对象而非裸 `positions` 列表：

- `classifier=None`：`positions` 为平铺持仓。
- 非空分类器：`positions` 为通过 `children` 连接的分类树；分类节点含汇总值，不能与叶子持仓重复相加。
- 服务端任务包装（例如 `{"status":"SUCCESS","data":...}`）保持原形；Harness 不擅自拆包。

### 日期与实时语义

- `date=None`：按北京时间当天处理，走实时语义。
- `date=北京时间当天`：同样走实时语义；它不是强制读取日终历史结果的开关。
- `date=过去日期`：读取历史头寸报表，适合对账和复现。
- 日期必须是严格的 `YYYY-MM-DD`；未来日期、时间戳和无效日期在客户端以 `invalid_argument` 拒绝。
- 实时结果的实际业务归属以返回值为准。夜盘可能归属下一交易日，缓存的实时行情也可能早于请求时间；应同时检查返回日期、`update_time`，以及期货/期权是否已取到结算价（持仓 `has_settlement`，根级看 `all_futures_options_has_settlement`）；「结算」的四种含义见[结算类字段词义](fields/balances.md#settlement)。`has_settlement` 为 `false` 只表示这次返回里对应期货/期权合约还没有行情结算价（盘中普遍如此，日终才有），属行情状态，不等于整条结果未就绪——结果是否就绪看 `pending_valuation` 与 `error_messages`。需要结算价的口径据此标注本次结果不含结算价，等行情更新后重读同一操作；不依赖结算价的字段照常交付。两者都不得改用上一交易日概览替代当日结果。

对明确为日间周期（`realtime_period_type=daytime`）的产品，少数字段的实时请求可以使用净值摘要路由。夜盘或周期未知的产品绝不因传了当天日期而误走历史摘要：展示期货冲销项时，Harness 改用不带 `date` 的 `asset_snapshot_summary`；不展示时改用不带 `date` 的 `balance`，并要求头寸读取权限。此为内部路由选择，不是额外的公开操作。

## get

统一查询产品或产品组的单日历史/实时头寸报表。

Python 签名：`rqamsh.balances.get(resource_or_resources: str | list[str], *, date: str | None=None, fields: list[str] | None=None, classifier: str | None=None, show_futures_sterilisation: bool=True, benchmark_id: str | None=None, drilldown: bool=True, include_component_weight_view: bool=False)`。

第一个参数既可以是单个资源，也可以是非空资源数组；数组表示一次读取多个资源的当天实时截面，参数面比单资源窄（见下方“批量实时截面”）。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource_or_resources`|`str \| list[str]`|必填|单个唯一产品或产品组 ID/名称，或非空数组；成员权重视图仅接受产品组。数组形态只接受 `fields`：`date`、`classifier`、`benchmark_id` 与 `drilldown=False`、`show_futures_sterilisation=False`、`include_component_weight_view=True` 都不支持，传入即报 `invalid_argument`。|
|`date`|`str \| None`|`None`|严格 `YYYY-MM-DD`。<br>&emsp;省略或北京时间当天：实时。<br>&emsp;过去日期：历史。若服务端返回其他非空日期，客户端报 `historical_date_mismatch`，绝不把它当作请求日。<br>&emsp;未来日期：拒绝。|
|`fields`|`list[str] \| None`|`None`|`None`：返回完整报表，含 `positions`。<br>&emsp;非空列表：投影最终结果的顶层字段。<br>&emsp;只接受顶层字段名；持仓传 `positions`，禁止 `positions.quantity` 等嵌套路径。|
|`classifier`|`str \| None`|`None`|`None`：平铺持仓。<br>&emsp;非空分类口径（如 `asset_class`）：返回带 `children` 的分类树。<br>&emsp;空字符串和纯空白值：拒绝。|
|`show_futures_sterilisation`|`bool`|`True`|是否展示期货冲销项。实时请求取 `False` 时，不能同时请求不穿透、自定义基准或成员权重视图。|
|`benchmark_id`|`str \| None`|`None`|基准**纯 ID**；不得传“类型,代码”形式或包含逗号。<br>&emsp;省略：使用资源配置。<br>&emsp;过去日期：只支持顶层收益字段；`fields=None`、`positions` 或 `daily_pnls` 与自定义基准组合会被拒绝。|
|`drilldown`|`bool`|`True`|是否对资产单元穿透。<br>&emsp;历史请求：不支持 `False`。<br>&emsp;实时切换：需注意下方服务端缓存限制。|
|`include_component_weight_view`|`bool`|`False`|仅实时产品组支持。<br>&emsp;成员对象继承本次 `fields`、`classifier`、`drilldown` 与 `benchmark_id`。<br>&emsp;结果不摊平为组报表。|

### 返回与字段投影

返回：返回形态共四支，由参数与资源类型选择——`fields=None` 是完整头寸报表，非空 `fields` 是最终结果的顶层字段投影，`include_component_weight_view=True` 是「成员产品 ID → 成员对象」映射，数组形态是「资源 ID → 实时概览」映射加两个诊断键。四支都原样保留服务端的业务日期、`null`、缺失键与任务包装，不把缺失补成 `0`。

下表 `{资源 ID}` 是动态键占位符，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|返回根|object|—|单资源形态为一份头寸报表；成员视图与数组形态为资源 ID → 对象的映射|恒返回；报表经 `fields` 投影后仍是同一层级的对象，不是裸 `positions` 列表|
|`date`|报表业务日期|string / null|YYYY-MM-DD|本次结果实际归属的业务日期|恒返回；实时分支的归属日由服务端监控周期决定，夜盘不一定等于请求当天；服务端当日无结果而回退默认文档时该键可能缺失|
|`positions`|持仓明细|array（object 元素）|—|当前口径下的持仓：`classifier` 省略时为平铺持仓，非空时是经 `children` 连接的分类树；元素字段见[持仓明细](fields/balances.md#position)|由参数选择：`fields=None` 或投影含 `positions` 时返回；只接受顶层字段名，传 `positions` 才取得完整持仓结构，`positions.quantity` 这类嵌套路径被拒绝|
|`positions[].children`|分类子节点|array（object 元素）|—|分类节点挂载的下一层分类或叶子持仓|由参数选择：`classifier` 非空时随分类节点返回；分类节点的汇总量与叶子持仓不能重复相加|
|`positions[].level_type`|分类层级字段名|string|—|该节点所在层的索引字段名：根节点是固定顶层标记（`top_level`，服务端写为前后各两个下划线的私有形态），`asset_class` 分类下依次是 `product_accounting_major_subject`、`asset_category`、`asset_class`|由参数选择：`classifier` 非空时只随分类节点返回；叶子持仓记录没有该键，不能用它判断叶子层级|
|`positions[].name`|节点或标的名称|string|—|分类节点是该层分组的显示名，叶子持仓是标的名称|随父级记录返回；分类节点的显示名可能被服务端改写（活期存款节点固定显示「活期存款」，而 `level_type` 仍是 `asset_class`），判断层级用 `level_type`，不要用 `name` 反推 `asset_class`|
|`share_values`|分类份额估值|object（string 键 → object） / null|—|`{份额类别}` → 分类份额字段对象，逐项见[分类份额](fields/balances.md#productsharevalue)|随父级返回；实时快照分支（不展示期货冲销项的实时查询）返回完整截面时才保证带该键与应付份额子持仓|
|`total_equity`|净资产|number / null|—|报表顶层字段之一；`total_assets`、`total_liabilities`、`units`、`unit_net_value`、`acc_unit_net_value`、`adjusted_net_value`、`daily_pnl`、`daily_returns`、`update_time` 等其余顶层字段同名同义，含义与计算见[头寸字段字典](fields/balances.md#balance-calculation)|随父级返回；投影只保留调用方请求且服务端实际返回的字段，未知或未返回的字段省略，实际返回的 `null` 原样保留|
|`benchmark_returns`|基准收益|number / null|—|该业务日的基准收益|由参数选择：`fields` 含该键或 `excess_returns` 时返回|
|`excess_returns`|超额收益|number / null|—|当日收益减基准收益|由参数选择：`fields` 含该键或 `benchmark_returns` 时返回；服务端会一并计算两者，投影只保留调用方请求的字段|
|`{资源 ID}`|成员对象或实时概览|object|—|成员权重视图为成员产品 ID → 成员报表；批量实时截面为资源 ID → 该资源的实时概览|由参数选择：成员视图（`include_component_weight_view=True`）与数组形态的结果根键；不是实际 JSON 键|
|`{资源 ID}.product_weight`|成员权重|number / null|—|该成员在产品组内的权重|成员视图随成员对象返回；`error_messages` 或 `pending_valuation` 非空时本次响应所有成员都不带该键|
|`error_messages`|未就绪原因|object（资源 ID → string）|—|按资源 ID 记录该项失败原因，原样来自服务端|成员视图与数组形态恒返回，无失败项时为空对象；逐项失败容器见[逐项失败容器](connection.md#item-errors)|
|`pending_valuation`|未就绪资源|array（string 元素）|—|已请求但未出现在结果中的资源 ID|成员视图与数组形态恒返回；由 Harness 依据缺失项推导，服务端不返回该键|
|`status`|任务状态|string（枚举）|—|服务端任务包装的外层状态|由数据决定：部分内部路由返回任务包装时原样保留，不拆包；见[任务终态 JSON](connection.md#task-result)|

- 分类树的分类节点除 `name`、`level_type`、`children` 外，带的是同名汇总值（`market_value`、`daily_pnl`、`acc_pnl`、`weight`、`contribute_returns`、`floating_pnl` 等）：字段名与[持仓明细](fields/balances.md#position) 相同，口径是整层汇总，不能当逐仓值使用，也不能与叶子相加。根节点的 `daily_pnl_rate` 实际是头寸 `daily_returns`、`daily_pnl` 是产品层口径，与叶子同名字段不同源。
- 行业分类（`shenwan_level_1`、`shenwan_level_2`、`zx_level_1`、`zx_level_2`）节点上的 `benchmark_returns` 与 `excess_returns` 是**按当前行情快照**算出的行业基准收益（该层成分股按权重加权），与请求的 `date` 无关；请求历史日期时这两个键仍给当日口径。需要历史区间或逐日的行业超额，走 [业绩归因](analytics/attribution.md#create_attribution) 的区间行业归因，或自行按 `market_data.benchmark_returns` 与行业分类计算，不要直接采用历史日期下分类节点的这两个键。
- 成员权重视图：成员报表不能合并或摊平成产品组报表；即使投影不包含它，成员对象的 `product_weight` 与结果中的 `error_messages`、`pending_valuation` 仍会保留。
- 成员权重的完整性只能由两个诊断键共同判定：服务端在存在错误信息时**不会计算权重**，本次响应里所有成员都没有 `product_weight`；估值未就绪的成员还会被静默跳过，此时同样不返回任何 `product_weight`。因此“权重完整”= `error_messages` 为空 **且** `pending_valuation` 为空；只看其中一项会把残缺成员集合误读成完整权重。
- 过去日期且指定字段：Harness 可内部额外请求 `date` 校验，但返回仍只保留调用方选定字段。实际日期为其他非空日期时抛出 `historical_date_mismatch`；`details` 包含 `requested_date`、`actual_date` 和原始响应。没有 `date` 或其为 `null` 时保留原始缺失语义。
- 过去日期配合 `benchmark_id`：只能请求纯顶层收益字段；完整报表（`fields=None`）、`positions` 或 `daily_pnls` 会被拒绝，不能借历史持仓结果声称已按自定义基准计算。
- 实时切换 `drilldown`：服务端缓存键不含该参数。若返回形状仍像先前口径，不能据此确认穿透已切换；记录实际返回，并在严格口径比较中避免混用缓存结果。

### 批量实时截面

数组形态的 `get` 走批量实时汇总路由，用于一次看多只产品/产品组当天的就绪情况：

```python
batch = rqamsh.balances.get(resource_or_resources=['授权测试产品', '授权测试产品组'], fields=['total_equity'])
ready = [key for key in batch if key not in {'error_messages', 'pending_valuation'}]
```

```console
rqamsh balances get --resource-or-resources '["授权测试产品", "授权测试产品组"]' --fields '["total_equity"]'
```

- 结果为资源 ID → 汇总的映射加两个诊断键，键形与返回条件见上表 `{资源 ID}`、`pending_valuation`、`error_messages` 三行。
- 两个诊断键都为空才表示本次请求全部就绪；缺失且不在 `error_messages` 中的资源说明估值尚未触达，按[未就绪与缺输入](connection.md#unready-inputs)稍后重试，不能当作零头寸。批量与成员权重视图的重试都按本页[组合限制与错误](#组合限制与错误)的要求提交同一请求，不得改用上一交易日概览或邻近日期报表替代。
- `fields` 以数组下发，服务端按字段名过滤；该路由不接受日期、分类、基准与成员视图参数。

### 内部路由与权限

调用方只使用 `get`；下表说明相同表面签名对应的内部路由，以及网关对这些路由的最低读取级别（客户端不预判权限，越级由网关拒绝）：

|请求条件|Harness 内部选择|网关最低读取级别|
|---|---|---|
|产品<br>&emsp;过去日期<br>&emsp;`fields` 为下列简字段<br>&emsp;平铺、穿透、展示冲销项、未自定义基准|`balance_summary` 内部路由|`read_net_value`|
|明确日间周期产品<br>&emsp;当天或省略日期<br>&emsp;满足同一简字段和默认业务参数|实时净值摘要内部路由|`read_net_value`|
|实时、展示期货冲销项，且不属于上面两行任一情形<br>&emsp;如 `fields=None`、`fields=['positions']`、夜盘或未知周期产品、产品组、自定义基准、成员视图|`asset_snapshot_summary` 内部路由|`read_net_value`|
|任一条件：<br>&emsp;历史查询且不属于第一行（`fields=None`、产品组、`positions` 或其他字段、分类、不穿透、自定义基准、成员视图）<br>&emsp;实时且不展示期货冲销项|完整 `balance` 内部路由|`read_import_data`|

简字段只有：`date`、`total_equity`、`total_assets`、`total_liabilities`、`units`、`unit_net_value`、`acc_unit_net_value`、`adjusted_net_value`、`daily_pnl`、`daily_returns`、`acc_unit_dividend`。字段含义和计算统一见[头寸字段字典](fields/balances.md#balance-calculation)。客户端根据资源和产品周期选择，调用方不能强制简字段路由；资源仍必须在当前身份授权范围内，详见[权限说明](permissions.md#可见不等于可写)。

### 组合限制与错误

|情形|客户端行为|处理方式|
|---|---|---|
|日期无效或晚于北京时间当天|`invalid_argument`|传严格、非未来的 `YYYY-MM-DD`；当天需要实时语义时可直接省略 `date`。|
|过去日期返回其他非空业务日期|`historical_date_mismatch`|不能将结果当作请求日；保留 `details.requested_date`、`details.actual_date` 和原始响应，待该历史日结算可用后再查。|
|`fields=[]`、字段不是合法顶层名，或传 `positions.quantity`|`invalid_argument`|传非空顶层字段列表；请求持仓使用 `positions`。|
|分类器为空白|`invalid_argument`|省略以取得平铺持仓，或传真实分类口径。|
|`benchmark_id` 为空/含逗号/带类型前缀|`invalid_argument`|只传基准纯 ID。|
|过去日期的 `benchmark_id` 与 `fields=None`、`positions` 或 `daily_pnls` 组合|`invalid_argument`|历史自定义基准只请求顶层收益字段；如需完整历史持仓，省略 `benchmark_id`。|
|历史请求 `drilldown=False` 或成员视图|`invalid_argument`|历史使用默认穿透且不请求成员视图；需要成员结果时查询实时产品组。|
|实时 `show_futures_sterilisation=False` 同时不穿透、自定义基准或成员视图|`invalid_argument`|恢复展示冲销项，或移除冲突参数。|
|实时切换 `drilldown` 后返回形状未切换|服务端既有缓存限制|不要把缓存结果当成新穿透口径；记录结果并避免在严格比较中混用。|
|成员视图的资源不是产品组|资源类型校验失败|改用已授权的唯一产品组。|
|数组形态传入日期、分类、基准或成员视图参数|`invalid_argument`|批量实时截面只支持 `fields`；需要这些参数时逐资源调用单资源形态。|
|字段最早日期传产品组|资源类型校验失败|改用产品；组没有该字段口径。|
|权限不足|来自服务端或网关|按上表申请 `read_net_value` 或 `read_import_data`；不要替换成猜测的资源 ID。|
|服务端尚在处理、等待超时、字段缺失或 `null`|结果尚未就绪或数据不可用|按[未就绪与缺输入](connection.md#unready-inputs)保留诊断并报告缺口；不得补零或反复查询代替缺失输入。|

过去日期的完整历史报表：

```python
result = rqamsh.balances.get(resource_or_resources='授权测试产品', date='2026-01-05')
positions = result['positions']
```

```console
rqamsh balances get --resource-or-resources "授权测试产品" --date "2026-01-05"
```

省略 `date` 的实时字段投影：

```python
realtime = rqamsh.balances.get(
    resource_or_resources='授权测试产品',
    fields=['total_equity', 'positions', 'update_time'],
)
```

```console
rqamsh balances get --resource-or-resources "授权测试产品" --fields '["total_equity", "positions", "update_time"]'
```

实时产品组成员视图可同时分类、不穿透并指定基准纯 ID：

```python
members = rqamsh.balances.get(
    resource_or_resources='授权测试产品组',
    fields=['total_equity', 'update_time'],
    classifier='asset_class',
    drilldown=False,
    benchmark_id='000300.XSHG',
    include_component_weight_view=True,
)
```

```console
rqamsh balances get --resource-or-resources "授权测试产品组" --fields '["total_equity", "update_time"]' --classifier asset_class --drilldown false --benchmark-id "000300.XSHG" --include-component-weight-view true
```

实时不展示期货冲销项时，不可与上述冲突参数组合：

```python
without_sterilisation = rqamsh.balances.get(
    resource_or_resources='授权测试产品',
    show_futures_sterilisation=False,
)
```

```console
rqamsh balances get --resource-or-resources "授权测试产品" --show-futures-sterilisation false
```

历史自定义基准只取顶层收益字段：

```python
historical_benchmark = rqamsh.balances.get(
    resource_or_resources='授权测试产品',
    date='2026-01-05',
    fields=['benchmark_returns'],
    benchmark_id='000300.XSHG',
)
```

```console
rqamsh balances get --resource-or-resources "授权测试产品" --date "2026-01-05" --fields '["benchmark_returns"]' --benchmark-id "000300.XSHG"
```


## series

查询产品或产品组的历史头寸报表时序。此操作保持原有时序返回形状：

- 不接受 `classifier`、成员权重视图或单日 `fields` 投影。
- `end_date` 省略表示读取当日盘中序列：此时不接受 `start_date` 与 `position_fields`，`benchmark_id` 仅在该分支可用；反之，历史分支必须同时给出 `start_date` 与 `end_date`，且不接受 `benchmark_id`。
- `position_fields` 直接指定额外持仓字段名，不加 `positions.` 前缀。
- 字段定义、计算和精度见[头寸字段字典](fields/balances.md#balance-calculation)。

Python 签名：`rqamsh.balances.series(resource: str, start_date: str | None=None, end_date: str | None=None, *, position_fields: list[str] | None=None, benchmark_id: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|唯一产品或产品组 ID/名称。|
|`start_date`|`str`|历史分支必填|起始业务日（YYYY-MM-DD）；盘中分支不接受。|
|`end_date`|`str`|省略即盘中分支|结束业务日；省略表示读取当日盘中序列。|
|`position_fields`|`list[str]`|可选|额外持仓字段名，不加 `positions.` 前缀；盘中分支不接受。|
|`benchmark_id`|`str`|可选|基准纯 ID；仅盘中分支可用。|

返回：历史分支（`start_date` 与 `end_date` 都给出）返回头寸报表对象数组，每项一个业务日；盘中分支（省略 `end_date`）返回当日分时序列对象。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|历史时序元素|object|—|一个业务日的头寸报表对象，含 `date`(YYYY-MM-DD) 与 `total_equity`、`total_assets`、`unit_net_value`、`acc_unit_net_value`、`adjusted_net_value`、`daily_pnl`、`daily_returns` 等报表字段，逐项见[头寸字段字典](fields/balances.md#balance-calculation)|恒返回（历史分支）；元素键随服务端序列结构，不能按单日 `get` 的成员映射、分类树或字段投影规则解释|
|`[].positions`|持仓明细|array（object 元素）|—|穿透后的持仓；元素含 `order_book_id`、`symbol`、`direction`、`asset_class`、`market_value`，以及 `position_fields` 指定的额外字段|随父级返回（历史分支）；字段含义见[持仓明细](fields/balances.md#position)|
|`asset_series`|当日分时序列|array（object 元素）|—|分钟线记录，元素含 `datetime`、`minute_return`、`equity_long_returns`、`equity_short_returns`、`benchmark_return`、`active_return`、`adjusted_net_value`；其余键随服务端序列结构|恒返回（盘中分支）；它描述当天盘中变化，不是某个业务日的日终结果|
|`asset_series[].minute_return_on_close`|按收盘价计的分钟收益|number / null|—|基于昨日收盘价的收益率列|由数据决定：仅当产品或组内产品持有期货/期权时返回，否则该键整体不出现|
|`start`|序列起始时点|string|日期时间|本次序列首个分钟线的时点|恒返回（盘中分支）|
|`end`|序列截止时点|string|日期时间|本次序列末个分钟线的时点|恒返回（盘中分支）|
|`prev_unit_net_value`|上一估值日单位净值|number / null|—|最近结算日的单位净值，盘中收益口径的基点|恒返回（盘中分支）；产品专用，产品组盘中序列不含该键|
|`last_total_equity`|最新总权益|number / null|—|服务端上报的序列末点总权益|恒返回（盘中分支）；权重组为 null|
|`minute_black_list`|停牌区间|array（array 元素）|—|当日被排除出序列的分钟区间列表|恒返回（盘中分支）；元素为区间的成对时点|

```python
result = rqamsh.balances.series(
    resource='授权测试产品',
    start_date='2026-01-01',
    end_date='2026-01-31',
    position_fields=['quantity', 'daily_pnl'],
)
```

```console
rqamsh balances series --resource "授权测试产品" --start-date "2026-01-01" --end-date "2026-01-31" --position-fields '["quantity", "daily_pnl"]'
```

盘中序列（省略 `end_date`）：

```python
intraday = rqamsh.balances.series(resource='授权测试产品', benchmark_id='000300.XSHG')
series_points = intraday['asset_series']
```

```console
rqamsh balances series --resource "授权测试产品" --benchmark-id "000300.XSHG"
```

## previous_summary

读取产品或产品组上一交易日的头寸概览。日期由服务端按上一交易日决定，本操作不接受日期参数，因此不会取到当天实时截面冒充已结算概览。

Python 签名：`rqamsh.balances.previous_summary(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|唯一产品或产品组 ID/名称。|

返回：服务端原始概览对象，不含 `positions`，并按服务端规则附带 `benchmark_returns` 与 `excess_returns`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|返回根|object|—|上一交易日的头寸概览对象|恒返回；不含 `positions`，需要持仓明细时改用 `get`|
|`date`|业务日期|string / null|YYYY-MM-DD|该概览归属的业务日期|恒返回；日期由服务端按上一交易日决定，本操作不接受日期参数|
|`total_equity`|净资产|number / null|—|概览字段之一；`total_assets`、`total_liabilities`、`units`、`unit_net_value`、`acc_unit_net_value`、`adjusted_net_value`、`daily_pnl`、`daily_returns` 等字段与单日报表顶层字段同名同义，逐项见[上一交易日概览](fields/balances.md#previous-summary)|随父级返回|
|`benchmark_returns`|基准收益|number / null|—|该业务日的基准收益|恒返回；服务端按上一交易日规则计算|
|`excess_returns`|超额收益|number / null|—|当日收益减基准收益|恒返回；与 `benchmark_returns` 同时给出|

结果检查：核对返回的概览字段与业务日期归属；需要持仓明细时改用 `get`，本操作不返回 `positions`。网关最低读取级别为 `read_net_value`。

```python
result = rqamsh.balances.previous_summary(resource='授权测试产品')
```

```console
rqamsh balances previous-summary --resource "授权测试产品"
```

## previous_summaries

批量读取多个产品或产品组上一交易日的头寸概览。资源可以是产品与产品组的混合数组，客户端逐项解析后再提交 ID。

与 `previous_summary` 的区别只在数量与失败表达：单项失败不阻塞其余资源，估值尚未就位的资源既不出现在结果键中，也不写入 `error_messages`。

Python 签名：`rqamsh.balances.previous_summaries(product_or_group_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`product_or_group_ids`|`list[str]`|必填|非空的产品或产品组 ID/名称数组。|

返回：`{资源 ID}` → 上一交易日概览的映射；成功项形状与 `previous_summary` 相同，失败项收在 `error_messages` 下，估值未就位的资源两处都不出现。下表 `{资源 ID}` 是动态键占位符，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|返回根|object|—|资源 ID → 上一交易日概览的映射|恒返回|
|`{资源 ID}`|概览对象|object|—|单个资源上一交易日的概览，形状与 `previous_summary` 相同：`date`、概览字段与 `benchmark_returns`、`excess_returns`|由数据决定：只有估值就位的资源出现在映射中|
|`error_messages`|失败原因|object（资源 ID → string）|—|按资源 ID 记录该项失败原因|由数据决定：只在存在失败项时出现，无失败项时该键整体不出现；逐项失败容器见[逐项失败容器](connection.md#item-errors)|

结果检查：逐个资源确认是否出现在结果中；缺失且不在 `error_messages` 中说明估值未就位，按[未就绪与缺输入](connection.md#unready-inputs)稍后重试或改查该资源的计算状态，不能当作零头寸。

```python
result = rqamsh.balances.previous_summaries(product_or_group_ids=['授权测试产品', '授权测试产品组'])
```

```console
rqamsh balances previous-summaries --product-or-group-ids '["授权测试产品", "授权测试产品组"]'
```

## export_file

导出产品或产品组的持仓全景 Excel，用于线下核对。

工作簿由服务端生成，包含资产单元工作表与份额列；导出与 `get` 共用同一份计算结果，但表格排版不是公开 API，字段口径以[头寸字段字典](fields/balances.md)为准。

日期语义与 `get` 一致但不接受未来日期：省略 `date` 表示今日实时截面，传入过去日期导出该日结果。产品已到期时服务端以警告拒绝导出。

Python 签名：`rqamsh.balances.export_file(resource: str, output: str, *, date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|唯一产品或产品组 ID/名称。|
|`output`|`str`|必填|本地输出文件路径，父目录须存在且目标文件不得已存在。|
|`date`|`str \| None`|`None`|严格 `YYYY-MM-DD`；省略为今日实时截面，不能晚于北京时间当天。|

返回：客户端下载元数据，文件内容不随响应返回。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；与落盘文件核对，`0` 不代表内容完整|

操作检查：核对 `path` 指向的目标文件与 `size`；目标文件已存在时客户端直接报错且不发起下载，需换路径或先处理既有文件。下载结果不写入产品数据，也不触发重算。

```python
result = rqamsh.balances.export_file(resource='授权测试产品', output='balance.xlsx', date='2026-01-05')
```

```console
rqamsh balances export-file --resource "授权测试产品" --output "balance.xlsx" --date "2026-01-05"
```


## export_snapshot

导出实时监控快照工作簿。它与 `export_file` 是两份报告：`export_file` 是头寸全景、只接受 `date`；`export_snapshot` 是实时监控口径、不接受 `date`，但单资源与多资源接受的参数不同。

- 单资源：可传 `classifier` 分类口径，直接返回文件；**不接受** `previous_trading_day`。
- 多资源（数组）：按产品与产品组拆分 ID，由服务端生成后返回，可传 `previous_trading_day=True` 取上一交易日口径；**不接受** `classifier`。

交叉传入会在本地以 `invalid_argument` 拒绝，而不是被服务端静默忽略。

Python 签名：`rqamsh.balances.export_snapshot(resource_or_resources: str | list[str], output: str, *, classifier: str | None=None, previous_trading_day: bool | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource_or_resources`|`str \| list[str]`|必填|单个资源或非空数组；数组表示概览口径。|
|`output`|`str`|必填|本地输出文件路径，父目录须存在且目标文件不得已存在。|
|`classifier`|`str \| None`|`None`|仅单资源可用；非空分类口径。|
|`previous_trading_day`|`bool \| None`|`None`|仅多资源可用；为真时取上一交易日口径。|

返回：客户端下载元数据；单资源同步落盘，多资源形态在任务终态后才写入文件，等待超时不代表任务取消。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；多资源形态的字节数在任务终态落盘后才可用；`0` 不代表内容完整|

```python
single = rqamsh.balances.export_snapshot(resource_or_resources='授权测试产品', output='snapshot.xlsx', classifier='asset_class')
multiple = rqamsh.balances.export_snapshot(resource_or_resources=['授权测试产品', '授权测试产品组'], output='overview.xlsx', previous_trading_day=True)
```

```console
rqamsh balances export-snapshot --resource-or-resources "授权测试产品" --output "snapshot.xlsx" --classifier asset_class
```

## field_earliest_date

查询多个产品上某字段最早存在的日期。

只接受**产品**：字段最早日期按产品维度统计，传产品组会被拒绝，而不是返回空结果。

Python 签名：`rqamsh.balances.field_earliest_date(resources: list[str], *, field: str='unit_net_value')`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resources`|`list[str]`|必填|非空产品 ID/名称数组。|
|`field`|`str`|`unit_net_value`|目标字段名，非空。|

返回：`{"earliest_date": ...}`；多个产品合并计算同一个最早日期。该日期说明数据起点，不代表区间内每一天都有值，缺失日期仍需按头寸报表逐日核对。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|返回根|object|—|只含 `earliest_date` 一个键的对象|恒返回|
|`earliest_date`|最早存在日期|string / null|YYYY-MM-DD|所有请求产品都同时存在该字段值的最早业务日期|恒返回；任一天只有全部请求产品都有该字段的值时才计入，没有这样的日期时为 `null`|

```python
rqamsh.balances.field_earliest_date(resources=['授权测试产品'])
```

```console
rqamsh balances field-earliest-date --resources '["授权测试产品"]'
```

## field_earliest_dates

批量查询多个产品某字段的最早存在日期。

与 `field_earliest_date` 使用同一数据来源，区别只在返回形状：本操作按产品给出最早日期，适合先摸清一批产品的数据起点再安排历史查询。同样只接受产品。

Python 签名：`rqamsh.balances.field_earliest_dates(resources: list[str], *, field: str='unit_net_value')`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resources`|`list[str]`|必填|非空产品 ID/名称数组。|
|`field`|`str`|`unit_net_value`|目标字段名，非空。|

返回：数组，元素含 `product_id` 与 `earliest_date`；无可用数据的产品其 `earliest_date` 为 `null`，产品本身仍出现在数组里。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|逐产品结果|object|—|一个请求产品的查询结果|恒返回；每个请求的产品都有一项，顺序与请求一致|
|`[].product_id`|产品 ID|string|字符串 ID|该结果对应的产品 ID|恒返回|
|`[].earliest_date`|最早存在日期|string / null|YYYY-MM-DD|该产品该字段存在的最早业务日期|恒返回；该产品没有可用数据时为 `null`，不能当作零起点|

```python
rqamsh.balances.field_earliest_dates(resources=['授权测试产品', '另一只授权测试产品'])
```

```console
rqamsh balances field-earliest-dates --resources '["授权测试产品", "另一只授权测试产品"]'
```
