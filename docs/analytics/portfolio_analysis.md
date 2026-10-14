# 组合对比与交易分析 analytics

组合对比把显式给出的成员集合在指标、收益、规模、配置与相关性上并排或矩阵式返回，并可导出报告；周报给出报告周的指标与净值报告；交易分析定位区间交易、单标的明细与算法交易效果。三者都读服务端算好的结果，不重算；组级口径与单产品口径不通用（单产品指标见[净值与收益指标](metrics.md#indicators-returns)）。

本页是 [analytics 总览](index.md) 的子页：用户需求与完成条件见[总览的场景表](index.md#从用户需求到操作)，`resource`/`resources` 语义与阻塞式调用等公共约定见[总览](index.md#api-使用约定)；本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。
- 组合对比的成员集合由调用方显式给出，Harness 不按产品组配置展开，避免与用户预期不一致。

## 组合对比

组合对比包含下列操作：`group_indicators`（指标）、`group_returns`（收益）、`group_capital_size`（规模）、`group_allocation`（配置穿透）、`group_returns_correlation` 与 `group_excess_correlation`（收益与超额收益相关性）、`group_overview_file`（报告导出），以及周报用途的 `weekly_report`（本周指标与指数周收益）与 `weekly_net_value_report`（周度净值报告导出）。除 `group_allocation` 返回成员合计后的整组配置外，其余操作都按成员并排或成员间矩阵给出，便于横向对比；`group_overview_file` 导出这些内容。成员集合由 `resources` 显式给出，顺序保留、重复去重；`end_date` 必填，`start_date` 省略时由服务端按默认区间处理，但请求体中该键会被省略而不是下发空值。两条周报操作不套用下面这组共同前缀，签名与参数见[周报数据](#周报数据)。

Python 签名（共同前缀）：`resources: list[str], end_date: str, start_date: str | None=None, benchmark: str | None=None`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resources`|`list[str]`|必填|非空成员数组，元素为产品或产品组唯一 ID 或名称。|
|`end_date`|`str`|必填|YYYY-MM-DD。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略时不下发该键。|
|`benchmark`|`str \| None`|`None`|可选基准；仅收益、超额相关性与报告导出接受该参数。|
|`output`|`str`|必填（仅 `group_overview_file`）|本地输出文件路径，父目录须存在且目标文件不得已存在；任务终态后才写入。|

- group_indicators：以查询串提交，其他组合对比操作以请求体提交。
- group_allocation：不接受 `start_date` 与 `benchmark`，只能给 `end_date`。
- group_returns_correlation：不接受 `benchmark`。
- group_overview_file：额外需要 `output`，任务终态后才落盘，目标文件已存在时抛错。

这七个操作都是任务型的：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，业务结果在 `data` 内（`task_id`、`status`、`message` 的含义见[任务终态 JSON](../connection.md#task-result)）。逐操作的表结构如下。

**`group_indicators`**

返回：`data` 为成员逐条指标数组，一名成员一条；表中的 `{frequency}` 代入 `daily`、`weekly`、`monthly`，三者键名相同，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|成员指标数组|array（object）|—|一名成员一条，元素含下列键|`status` 为 `SUCCESS` 时返回；成员数可能少于 `resources`（不可见或已删除的成员、没有成员产品的产品组被丢弃）|
|`data[].id`|成员 ID|string|—|成员产品或产品组的唯一 ID|随父级记录返回|
|`data[].name`|成员名称|string|—|成员产品或产品组的名称|随父级记录返回|
|`data[].start_date`|成员起始日|string|YYYY-MM-DD|该成员自身的产品起始日|随父级记录返回；不是请求的 `start_date`|
|`data[].benchmark_name`|成员基准名称|string / null|—|该成员自身配置的基准名称|随父级记录返回；基准不在受支持基准与自定义基准内时查不到名称，取值为 `null`|
|`data[].net_value`|区间末净值|number / null|净值|该成员区间末行（`end_date` 与到期日的较早者）的净值：产品组取复权净值，产品取单位净值|随父级记录返回；是净值倍数，不是金额，也不是区间收益|
|`data[].annual_twoside_turnover_rate`|年化双边换手率|number / null|倍数|区间买卖金额合计 ÷ 区间平均净资产 ÷ 样本数 × 年化因子（交易日 252、自然日 365）|随父级记录返回；只在这一层出现，三个频率区块内没有同名键|
|`data[].period_acc_returns`|区间累计收益率|number / null|小数|区间内日收益累乘的末值；产品在区间内存在累计单位净值时改用区间末累计单位净值相对区间前一日单位净值的涨幅|随父级记录返回；与 `data[].daily.period_acc_returns` 同值|
|`data[].daily`|日频区块|object|—|含本表末尾的 21 项风险键、下列 10 项概况指标与 4 项回撤详情文本|随父级记录返回；日频无有效样本时只剩 10 项概况指标；基准收益率为空时风险键与回撤详情都不出现|
|`data[].daily.net_cash_in`|区间净投入|number / null|估值币种金额|区间内每日 [net_cash_in](../fields/balances.md#net-cash-in) 的合计|随父级记录返回|
|`data[].daily.period_pnl`|区间盈亏|number / null|估值币种金额|区间内每日 [daily_pnl](../fields/balances.md#daily-pnl) 的合计|随父级记录返回；是金额，不是收益率|
|`data[].daily.equity_net_exposure`|权益净敞口|number / null|估值币种金额|区间末有效日的 [equity_net_exposure](../fields/balances.md#equity-net-exposure)|随父级记录返回；取末条，不是区间合计|
|`data[].daily.period_buy_amount`|区间买入金额|number / null|估值币种金额|区间内股票、债券与基金买入金额的合计|随父级记录返回；头寸来源为纯估值表的成员取值为 `null`，不是 `0`|
|`data[].daily.period_sell_amount`|区间卖出金额|number / null|估值币种金额|区间内股票、债券与基金卖出金额的合计|随父级记录返回；与买入金额同为区间合计口径|
|`data[].daily.cash`|期末现金|number / null|估值币种金额|区间末有效日的 [cash](../fields/balances.md#cash)|随父级记录返回|
|`data[].daily.total_equity`|期末净资产|number / null|估值币种金额|区间末有效日的 [total_equity](../fields/balances.md#total-equity)|随父级记录返回；与风险键 `total_returns` 不同物|
|`data[].daily.period_acc_returns`|区间累计收益率|number / null|小数|与 `data[].period_acc_returns` 同值|随父级记录返回|
|`data[].daily.cn_stock_market_value`|期末 A 股市值|number / null|估值币种金额|区间末有效日的 A 股持仓市值|随父级记录返回|
|`data[].daily.hk_stock_market_value`|期末港股市值|number / null|估值币种金额|区间末有效日的港股持仓市值|随父级记录返回|
|`data[].daily.max_drawdown_period`|最大回撤区间|string|—|口径与取值同[指标返回字段与公式](metrics.md#indicators-returns) 的 `max_drawdown.max_drawdown_period`|随父级记录返回；是文本明细，不是数值回撤|
|`data[].daily.max_drawdown_recovery_days`|最大回撤修复时长|string|—|口径与取值同[指标返回字段与公式](metrics.md#indicators-returns) 的 `max_drawdown.max_drawdown_recovery_days`|随父级记录返回；未回撤、未修复的取值规则见该表|
|`data[].daily.geometric_excess_max_drawdown_period`|几何超额最大回撤区间|string|—|口径与取值同[指标返回字段与公式](metrics.md#indicators-returns) 的 `excess_max_drawdown.geometric_excess_max_drawdown_period`|随父级记录返回；不要与数值键 `data[].{frequency}.geometric_excess_max_drawdown` 混淆|
|`data[].daily.geometric_excess_max_drawdown_recovery_days`|几何超额最大回撤修复时长|string|—|口径与取值同[指标返回字段与公式](metrics.md#indicators-returns) 的 `excess_max_drawdown.geometric_excess_max_drawdown_recovery_days`|随父级记录返回；未修复的取值规则见该表|
|`data[].weekly`|周频区块|object|—|只含本表末尾的 21 项风险键|随父级记录返回；周频无有效样本时为空对象 `{}`；不并入概况指标与回撤详情|
|`data[].monthly`|月频区块|object|—|只含本表末尾的 21 项风险键|随父级记录返回；月频无有效样本时为空对象 `{}`；不并入概况指标与回撤详情|
|`data[].{frequency}.alpha`|年化詹森阿尔法|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.alpha`|随父级返回|
|`data[].{frequency}.absolute_alpha`|零无风险利率口径的年化阿尔法|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.absolute_alpha`|随父级返回|
|`data[].{frequency}.beta`|贝塔|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.beta`|随父级返回|
|`data[].{frequency}.sharpe`|夏普比率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.sharpe`|随父级返回|
|`data[].{frequency}.absolute_sharpe`|零无风险利率口径的夏普比率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.absolute_sharpe`|随父级返回|
|`data[].{frequency}.excess_sharpe`|超额收益夏普比率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.excess_sharpe`|随父级返回|
|`data[].{frequency}.max_drawdown`|最大回撤|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.max_drawdown`|随父级返回；是数值回撤，与 `data[].daily.max_drawdown_period` 不同物|
|`data[].{frequency}.annual_downside_risk`|年化下行风险|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.annual_downside_risk`|随父级返回|
|`data[].{frequency}.information_ratio`|信息比率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.information_ratio`|随父级返回|
|`data[].{frequency}.geometric_excess_annual_return`|几何超额年化收益率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.geometric_excess_annual_return`|随父级返回|
|`data[].{frequency}.arithmetic_excess_annual_return`|逐期算术超额连乘后的年化收益率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.arithmetic_excess_annual_return`|随父级返回；不是几何超额年化收益率|
|`data[].{frequency}.annual_volatility`|年化收益波动率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.annual_volatility`|随父级返回|
|`data[].{frequency}.excess_annual_volatility`|年化超额收益波动率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.excess_annual_volatility`|随父级返回|
|`data[].{frequency}.annual_tracking_error`|年化跟踪误差|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.annual_tracking_error`|随父级返回|
|`data[].{frequency}.geometric_excess_max_drawdown`|几何超额最大回撤|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.geometric_excess_max_drawdown`|随父级返回|
|`data[].{frequency}.total_returns`|区间累计收益率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.total_returns`|随父级返回；与 `data[].period_acc_returns` 分属风险表与概况两个口径，不要互相顶替|
|`data[].{frequency}.total_geometric_excess_return`|区间几何超额收益率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.total_geometric_excess_return`|随父级返回|
|`data[].{frequency}.total_arithmetic_excess_return`|区间算术超额收益率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.total_arithmetic_excess_return`|随父级返回|
|`data[].{frequency}.total_annual_returns`|日频区间累计收益折算的年化收益率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.total_annual_returns`|随父级返回|
|`data[].{frequency}.annual_simple_interest`|日频区间累计收益折算的单利年化收益率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.annual_simple_interest`|随父级返回|
|`data[].{frequency}.calmar_ratio`|卡马尔比率|number / null|小数|同[指标返回字段与公式](metrics.md#indicators-returns) 的 `{frequency}_risk.calmar_ratio`|随父级返回|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：这是组级口径的成员指标，与单产品 `indicators` 的对应区块不能互换比较；元素随成员数量变化，缺估值的成员不会出现在结果里（任务先补算重试，最终失败），只有生命周期与请求区间无交集的成员占一条且只含前四个身份键。

**`group_returns`**

返回：`data` 为记录数组，第一条是基准记录，随后每个算得出指标的成员一条；下表中的 `{frequency}` 代入 `daily`、`weekly`、`monthly`，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|成员收益序列数组|array（object）|—|首条恒为基准记录，其后每个算得出指标的成员一条，元素含下列键|`status` 为 `SUCCESS` 时返回；区间内无数据的成员不占一条，元素数可能少于 `resources` 数量加一|
|`data[].id`|记录 ID|string|—|基准记录为请求的基准 ID 原文，成员记录为成员产品或产品组的唯一 ID|随父级记录返回|
|`data[].type`|记录类型|string（枚举）|—|`benchmark` 基准、`product` 成员产品、`group` 成员产品组|随父级记录返回|
|`data[].name`|记录名称|string|—|基准名称、产品或产品组名称|随父级记录返回|
|`data[].daily`|日频序列|array（object）|—|按交易日排列，元素含下列频率键|随父级记录返回；无有效样本时为空数组 `[]`|
|`data[].weekly`|周频序列|array（object）|—|按自然周排列，元素含下列频率键|随父级记录返回；无有效样本时为空数组 `[]`；元素日期取该周内最后一个日期|
|`data[].monthly`|月频序列|array（object）|—|按自然月排列，元素含下列频率键|随父级记录返回；无有效样本时为空数组 `[]`；元素日期取该月内最后一个日期|
|`data[].{frequency}[].date`|日期|string|YYYY-MM-DD|该条记录对应的日期、周末尾或月末|随父级记录返回|
|`data[].{frequency}[].cumulative_returns`|累计收益|number|小数|自区间起点累计的收益，首条即含首期收益|随父级记录返回；没有前置的 0 初始行，不是净值|
|`data[].{frequency}[].daily_returns`|日收益|number|小数|日频为该日收益；周频与月频下只有基准记录返回该键，值为该周或该月的复利区间收益|由数据决定：成员记录的周频与月频没有该键|
|`data[].{frequency}[].excess_earnings`|算术超额收益|number|小数|当日组合收益减当日基准收益|由数据决定：只有成员记录的日频有该键；是逐期算术差，不是累计差|
|`data[].{frequency}[].geometric_excess_cumulative_returns`|几何超额累计收益|number|小数|同期组合累计增长因子 ÷ 同期基准累计增长因子 − 1|由数据决定：只有成员记录有该键，日频、周频与月频都有|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：先按 `type` 分出基准与成员，再比较同一频率的 `cumulative_returns`；只有基准记录的周、月周期收益落在 `daily_returns` 键上，成员记录的周/月频没有该键，不要按日频键集去取周/月记录。再按请求的 `resources` 与 `data[].id` 逐项对账：缺项且成员估值未就绪时稍后重试同一读取；成员生命周期与请求区间无交集属确定性省略，不因重试而出现。

**`group_capital_size`**

返回：`data` 为日期记录数组，按成员投资类别给出规模。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|规模走势数组|array（object）|—|区间内每个有估值的日期一条，元素含下列键|`status` 为 `SUCCESS` 时返回；成员全部不可见或日期都落在[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)之外时为空数组 `[]`|
|`data[].date`|记录日期|string|YYYY-MM-DD|该条记录对应的估值日|随父级记录返回；该日期不在交易日历内时整条记录不出现|
|`data[].asset_classes`|分类规模列表|array（object）|—|该日期按成员投资类别聚合后的规模，元素只有下列两个键|随父级记录返回；`date` 只在元素外层，元素内没有该键；某日全部成员的投资类别都为空时该日记录仍在，此键为空数组 `[]`|
|`data[].asset_classes[].asset_class_name`|成员投资类别|string|—|该成员产品配置里 `investment_category` 的中文名，即[产品投资类别](../fields/products.md#productinvestmentcategory) 的「含义」列（12 项之一）；字段名带 `asset_class`，但不是[资产品种与会计科目](../fields/others.md#assetclass) 的取值|随父级记录返回；产品组成员恒为「产品组」；投资类别为空的成员不进该日记录；取值不在枚举内时原样保留|
|`data[].asset_classes[].value`|该类当日净资产合计|number|估值币种金额|该投资类别下全部成员当日的净资产合计|随父级记录返回；是净资产合计，不是市值，也不是收益率|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：`value` 是净资产金额，不是收益率；按类别分别看趋势，不要直接相加不同类别的口径。成员集合不可见或日期全落在交易日历之外时才是空数组，请求区间本身缺估值会让任务失败。

**`group_allocation`**

返回：`data` 为配置权重对象，只覆盖截止日截面；表中的 `{交易资产属性}` 与 `{子类型}` 是中文业务名动态键，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|配置权重|object|—|以交易资产属性中文名为键，值为「子类型中文名 → 权重」的对象|`status` 为 `SUCCESS` 时返回；全部成员当日都没有持仓时为空对象 `{}`|
|`data.{交易资产属性}`|该属性下的子类型权重|object|—|该属性下各子类型的权重；属性键是[交易资产属性](../fields/others.md#tradingassetclass) 的中文名，共 10 个可能出现的取值|由数据决定：只出现当日有持仓的属性；资产类别不在归并表内时该持仓整体不计入，对应属性键也不出现|
|`data.{交易资产属性}.{子类型}`|子类型权重|number / null|小数|该子类型的持仓市值合计 ÷ 当日有持仓成员的净资产合计|由数据决定：分母为 `0` 时取值为 `null`；带符号市值可让权重为负；股票与基金的子类型按板块与基金类型细分，细分匹配失败时保留服务端原始取值|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：两个层级的键都是中文业务名（股票与基金的子类型细分匹配失败时保留服务端原始取值），不是 `asset_class` 枚举值；权重分母是当日有持仓成员的净资产合计，不等于某一成员内部的持仓占比，带符号市值可让权重为负。

**`group_returns_correlation`**

返回：`data` 为收益相关性矩阵，按频率分组；表中的 `{frequency}` 代入 `daily`、`weekly`、`monthly`，`{成员名}` 是成员名称动态键，二者都不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|收益相关性|object|—|按频率给出成员两两相关系数|`status` 为 `SUCCESS` 时返回；成员公共区间为空或全部成员取不到数据时为空对象 `{}`|
|`data.{frequency}`|该频率的相关矩阵|object|—|成员名 → 「成员名 → 相关系数」的方阵|由数据决定：该频率有效观测期超过 1 个才出现，没有成员数下限，单成员时仍是 1×1 矩阵；不出现该频率键不代表相关为零|
|`data.{frequency}.{成员名}`|该成员对应的矩阵行|object|—|该成员与每个成员（含自身）的相关系数|随父级返回；`{成员名}` 是成员名称，不是产品 ID；键序不保证与 `resources` 顺序一致，同名成员会互相覆盖|
|`data.{frequency}.{成员名}.{成员名}`|相关系数|number / null|—|两个成员该频率收益的皮尔逊相关系数|随父级返回；矩阵对称、对角线为 `1`，保留两位小数；两个成员没有共同有效观测或其中一方方差为 `0` 时为 `null`|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：相关系数保留两位小数；只有部分频率有值时说明该频率的有效观测期不超过 1 个（不是成员数不足，成员数没有下限），不能用 `0` 顶替；矩阵键是成员名称，同名成员会互相覆盖。

**`group_excess_correlation`**

返回：`data` 为超额收益相关性矩阵，结构与 `group_returns_correlation` 相同。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|超额收益相关性|object|—|按频率给出成员两两几何超额收益相关系数|`status` 为 `SUCCESS` 时返回；成员公共区间为空或全部成员取不到数据时为空对象 `{}`|
|`data.{frequency}`|该频率的超额相关矩阵|object|—|成员名 → 「成员名 → 相关系数」的方阵|由数据决定：该频率有效观测期超过 1 个才出现，没有成员数下限，单成员时仍是 1×1 矩阵；不出现该频率键不代表相关为零|
|`data.{frequency}.{成员名}`|该成员对应的矩阵行|object|—|该成员与每个成员（含自身）的相关系数|随父级返回；`{成员名}` 是成员名称，不是产品 ID；键序不保证与 `resources` 顺序一致，同名成员会互相覆盖|
|`data.{frequency}.{成员名}.{成员名}`|相关系数|number / null|—|两个成员该频率几何超额收益的皮尔逊相关系数|随父级返回；矩阵对称、对角线为 `1`，保留两位小数；两个成员没有共同有效观测或其中一方方差为 `0` 时为 `null`|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：矩阵基于几何超额收益，与 `group_returns_correlation` 不可混用；换 `benchmark` 会改变全部相关系数。

**`group_overview_file`**

返回：客户端下载元数据，含 `path`、`size`；任务终态后才落盘，目标文件已存在时抛错。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](../connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](../connection.md#download-result)|

交付检查：导出内容与同参数的组合对比查询一致；先确认成员集合、区间与基准，再核对新文件。

### 周报数据

`weekly_report` 与 `weekly_net_value_report` 服务周报口径：前者给出一期周报需要的本周收益、本周超额、周频风险指标与指数周收益，后者导出周度净值报告工作簿。两者都以报告截止日所在的自然周为窗口，窗口起点由服务端给出并随结果返回，不在客户端推算。

**`weekly_report`**

Python 签名：`rqamsh.analytics.weekly_report(resources: list[str], *, end_date: str | None=None, start_date_mode: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resources`|`list[str]`|必填|非空成员数组，元素为产品或产品组唯一 ID 或名称；重复项去重，顺序保留。|
|`end_date`|`str \| None`|`None`|报告截止日 YYYY-MM-DD；省略时不下发该键，由服务端按今日处理。|
|`start_date_mode`|`str \| None`|`None`|成员统计起点口径：`trading_start_date` 取成员交易起始日，`start_date` 取成员成立日；省略时不下发该键，由服务端按 `trading_start_date` 处理。其他取值在本地拒绝。|

返回：`data` 内按策略分桶给出成员条目与指数周收益；`task_id`、`status`、`progress` 与 `message` 的含义见[任务终态 JSON](../connection.md#task-result)。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`data.start_date`|窗口起始日|string|YYYY-MM-DD|本次报告窗口的第一个交易日：截止日所在自然周的周一，周一非交易日时顺延到其后的交易日|`status` 为 `SUCCESS` 时返回；不是请求的 `start_date_mode` 对应日期|
|`data.end_date`|窗口截止日|string|YYYY-MM-DD|本次报告使用的截止日|`status` 为 `SUCCESS` 时返回；省略 `end_date` 时为服务端当日|
|`data.index_returns`|指数周收益|object|小数|固定四个指数的本周收益：`000300.XSHG`、`000905.XSHG`、`000852.XSHG`、`932000.INDX`|`status` 为 `SUCCESS` 时返回；键是指数代码，是按窗口首日起算的区间收益，不是成分收益|
|`data.market_neutral`|市场中性成员条目|array（object 元素）|—|策略类别属于市场中性、多空或杠杆中性的成员；元素含下列各键|`status` 为 `SUCCESS` 时返回；没有该类成员、或成员缺本周或全区间指标时为空数组 `[]`|
|`data.index_enhanced`|指数增强成员条目|array（object 元素）|—|其余策略类别的成员；元素含下列各键|同上，两类都为空数组表示没有可入报告的成员|
|`data.{桶}[].product_id`|成员 ID|string|—|成员产品或产品组的唯一 ID|随父级返回|
|`data.{桶}[].product_name`|成员名称|string|—|成员的报告名称；杠杆中性成员的名称带杠杆倍数说明|随父级返回；`product_id` 指向产品组时名称是组名|
|`data.{桶}[].start_date`|成员统计起点|string|YYYY-MM-DD|按 `start_date_mode` 取的成员起点|随父级返回；不是报告窗口起始日|
|`data.{桶}[].week_returns`|本周收益|number / null|小数|本窗口内的区间累计收益率，口径同 [indicators](metrics.md#indicators-returns) 的 `returns_summary.total`|随父级返回|
|`data.index_enhanced[].week_excess_returns`|本周几何超额收益|number / null|小数|本窗口内的几何超额收益率，口径同 [indicators](metrics.md#indicators-returns) 的 `returns_summary.geometric_excess`|仅指数增强条目返回；市场中性条目没有该键|
|`data.market_neutral[].sharpe`|周频夏普比率|number / null|小数|全区间周频夏普比率，口径同 [indicators](metrics.md#indicators-returns) 的 `weekly_risk.sharpe`|仅市场中性条目返回|
|`data.market_neutral[].annual_returns`|周频年化收益率|number / null|小数|全区间周频累计收益折算的年化收益率，口径同 [indicators](metrics.md#indicators-returns) 的 `weekly_risk.total_annual_returns`|仅市场中性条目返回|
|`data.market_neutral[].max_drawdown`|周频最大回撤|number / null|小数|全区间周频最大回撤取负后的数值，负回撤在报告中显示为正数|仅市场中性条目返回；与 [indicators](metrics.md#indicators-returns) 的 `weekly_risk.max_drawdown` 符号相反|
|`data.index_enhanced[].excess_sharpe`|周频超额夏普比率|number / null|小数|自成员统计起点之后开始、以该起点次一交易日为区间起点的周频超额夏普比率|仅指数增强条目返回；与全区间 `weekly_risk.excess_sharpe` 的样本起点不同|
|`data.index_enhanced[].total_geometric_excess_return`|区间几何超额收益率|number / null|小数|与 `excess_sharpe` 同一样本区间的几何超额收益率|仅指数增强条目返回；不是 `week_excess_returns`|
|`data.index_enhanced[].geometric_excess_annual_return`|几何超额年化收益率|number / null|小数|与 `excess_sharpe` 同一样本区间的几何超额年化收益率|仅指数增强条目返回|
|`data.{桶}[].asset_series`|组合序列|array（object 元素）|—|按自然周排列的组合序列，覆盖成员统计起点到截止日|随父级返回；无有效样本时为空数组 `[]`；元素键见下方序列元素表|
|`data.index_enhanced[].excess_series`|超额序列|array（object 元素）|—|按自然周排列的算术与几何超额序列|仅指数增强条目返回；无有效样本时为空数组 `[]`|
|`data.{桶}[].benchmark_series`|基准序列|array（object 元素）|—|按自然周排列的成员基准序列|随父级返回；无有效样本时为空数组 `[]`|

三个序列的元素键如下；`asset_series` 与 `benchmark_series` 的数值字段名称不同，不能互相顶替。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`asset_series[].date`|日期|string|YYYY-MM-DD|该周内最后一个日期|随父级返回|
|`asset_series[].portfolio_returns`|周收益|number / null|小数|该周的组合收益|随父级返回；首周即含该周收益，没有前置的 0 初始行|
|`asset_series[].cumulative_returns`|累计收益|number / null|小数|自成员统计起点累计到该周的收益|随父级返回；不是净值|
|`asset_series[].adjusted_net_value`|复权净值|number / null|净值|该周的组合复权净值，起点为 `1`|随父级返回|
|`asset_series[].unit_net_value`|单位净值|number / null|净值|该周的组合单位净值|由数据决定：取不到净值口径时为 `null`，缺失不等于 `1`|
|`asset_series[].acc_unit_net_value`|累计单位净值|number / null|净值|该周的组合累计单位净值|由数据决定：取不到净值口径时为 `null`|
|`excess_series[].date`|日期|string|YYYY-MM-DD|该周内最后一个日期|仅指数增强条目的 `excess_series` 返回|
|`excess_series[].arithmetic_excess_returns`|周算术超额收益|number / null|小数|该周组合收益减基准收益|同上|
|`excess_series[].geometric_excess_returns`|周几何超额收益|number / null|小数|该周组合与基准的增长因子之比减一|同上|
|`excess_series[].arithmetic_excess_cumulative_returns`|累计算术超额收益|number / null|小数|自成员统计起点累计的算术超额|同上|
|`excess_series[].geometric_excess_cumulative_returns`|累计几何超额收益|number / null|小数|自成员统计起点累计的几何超额|同上|
|`benchmark_series[].date`|日期|string|YYYY-MM-DD|该周内最后一个日期|随父级返回|
|`benchmark_series[].benchmark_returns`|基准周收益|number / null|小数|该周成员基准收益|随父级返回|
|`benchmark_series[].benchmark_cumulative_returns`|累计基准收益|number / null|小数|自成员统计起点累计的基准收益|随父级返回|

结果检查：先读 `data.start_date`~`data.end_date` 确认窗口，再按桶取成员——[投资策略类别](../fields/products.md#strategycategory)为多重时，全部属于市场中性、多空、杠杆中性才进 `market_neutral`，否则进 `index_enhanced`；两类都为空数组表示本期没有可入报告的成员，不是收益为零。`week_returns` 只覆盖窗口，`sharpe`、`annual_returns` 与 `asset_series` 覆盖成员统计起点到截止日的全区间，两类指标不要互相印证。成员缺本周或全区间指标时不占条目，也不补零。任务返回 `SUCCESS` 仍可能出现空桶或成员缺项：先按请求的 `resources` 与两个桶的 `product_id` 核对成员是否齐全，成员估值未就绪时稍后重试同一读取，不要直接把空桶或缺项当作本期结论。

**`weekly_net_value_report`**

Python 签名：`rqamsh.analytics.weekly_net_value_report(resource: str, output: str, *, start_date: str | None=None, end_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`output`|`str`|必填|本地输出文件路径，父目录须存在且目标文件不得已存在；任务终态后才写入。|
|`start_date`|`str \| None`|`None`|起始日期 YYYY-MM-DD；省略时不下发该键，由服务端按成员成立日处理。|
|`end_date`|`str \| None`|`None`|截止日期 YYYY-MM-DD；省略时不下发该键，由服务端按今日处理。|

返回：客户端下载元数据，含 `path`、`size`；任务终态后才落盘，目标文件已存在时抛错。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](../connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](../connection.md#download-result)|

交付检查：工作簿按成员策略类别选用市场中性或指数增强模板，列集合随类别不同；先确认成员、区间与策略类别，再核对净值和超额列。

```python
result = rqamsh.analytics.weekly_report(resources=["授权测试产品组"], end_date="2026-09-30")
rqamsh.analytics.weekly_net_value_report(resource="授权测试产品组", output="weekly.xlsx")
```

```console
rqamsh analytics weekly-report --resources '["授权测试产品组"]' --end-date 2026-09-30
rqamsh analytics weekly-net-value-report --resource 授权测试产品组 --output weekly.xlsx
```

## 交易分析

- trading_analysis：读取区间交易分析列表；区间可省略，由服务端决定默认范围。
- single_trading_analysis：读取单标的交易分析；标的代码必填且非空，可选方向与资产类别过滤。
- algo_trading_performance：读取算法交易效果；可选算法类型、算法名与时间跨度、展示方式。

Python 签名：`rqamsh.analytics.trading_analysis(resource: str, *, start_date: str | None=None, end_date: str | None=None)`、`rqamsh.analytics.single_trading_analysis(resource: str, order_book_id: str, *, start_date: str | None=None, end_date: str | None=None, asset_class: str | None=None, direction: str | None=None)`、`rqamsh.analytics.algo_trading_performance(resource: str, *, start_date: str | None=None, end_date: str | None=None, algo_type: str | None=None, algo_name: str | None=None, algo_time_span: str | None=None, display_mode: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`order_book_id`|`str`|必填|标的代码，仅 `single_trading_analysis`；空串或空白被拒绝。|
|`start_date` / `end_date`|`str \| None`|`None`|YYYY-MM-DD；省略时由服务端决定默认区间。|
|`asset_class` / `direction`|`str \| None`|`None`|资产类别与买卖方向过滤。|
|`algo_type` / `algo_name` / `algo_time_span` / `display_mode`|`str \| None`|`None`|算法交易过滤与展示参数；只在提供时下发。|

这三个操作也都是任务型的：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，业务结果在 `data` 内（含义见[任务终态 JSON](../connection.md#task-result)）。

**`trading_analysis`**

返回：`data` 为区间交易分析记录数组，一行一个「资产类别 + 标的代码 + 标的名称 + 方向」分组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|区间交易分析记录|array（object）|—|一个元素一个「资产类别 + 标的代码 + 标的名称 + 方向」分组，含下列键|`status` 为 `SUCCESS` 时返回；区间内没有持仓盈亏时为空数组 `[]`|
|`data[].asset_class`|资产品种|string|—|该分组持仓的资产类别取值，如 `stock`、`closed_end_fund`；全量取值与中文含义见[资产品种与会计科目](../fields/others.md#assetclass)|随父级记录返回；是英文取值，不是中文名|
|`data[].order_book_id`|标的代码|string|—|该分组的标的代码|随父级记录返回；因改名而变更的代码已按区间末条概要日的生效映射统一|
|`data[].symbol`|标的名称|string|—|该分组的标的名称|随父级记录返回；与 `data[].order_book_id` 出自同一份改名映射|
|`data[].direction`|持仓方向|string（枚举）|—|`long` 多头、`short` 空头|随父级记录返回|
|`data[].asset_category`|交易属性分类中文名|string|—|该资产类别对应的[交易资产属性](../fields/others.md#tradingassetclass) 中文名|随父级记录返回；不在归并表内的类别取固定文案「其他资产」（仍照常成组）|
|`data[].date`|该分组最后一次出现的估值日|string|YYYY-MM-DD|该分组在区间内最后一次出现在概要里的日期|随父级记录返回；不是「最后一个有盈亏的日期」，当日盈亏缺失时本键照常推进|
|`data[].period_pnl`|截至 `date` 的区间累计盈亏|number / null|估值币种金额|该分组区间内逐条 [daily_pnl](../fields/balances.md#daily-pnl) 按出现顺序的累加值|随父级记录返回；该组末条明细当日盈亏缺失时取值为 `null`，与数值 `0` 不同|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：这是结果视图，不修改流水；`period_pnl` 按分组逐条累计，该组末条明细缺当日盈亏时取值为 `null` 而不是 0；请求区间本身缺估值会让任务失败，不是空数组。

**`single_trading_analysis`**

返回：`data` 为单标的走势对象，含价格、持仓、累计盈亏与[买卖点](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_share_transformation)序列。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|单标的分析结果|object|—|恒含下列五个键|`status` 为 `SUCCESS` 时返回|
|`data.prev_adjusted_price_series`|前复权价格序列|array（object）|—|区间内该标的的逐日价格，元素含下列键|恒返回；区间内取不到行情时为空数组 `[]`|
|`data.prev_adjusted_price_series[].date`|日期|string|YYYY-MM-DD|该条价格对应的业务日|随父级记录返回|
|`data.prev_adjusted_price_series[].price`|前复权价格|number / null|—|按资产类别取价：基金取[复权净值](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_nav)，期货与期权取结算价，ETF 取 IOPV，LOF 取前复权收盘价并用复权净值补缺，其余取前复权收盘价|随父级记录返回；区间前段无行情时为 `null`，非行情日沿用前一交易日价格；不是成交价，量纲随资产类别变化|
|`data.position_quantity_series`|持仓数量序列|array（object）|—|该标的的逐日持仓，元素含下列键|恒返回；区间内没有该标的持仓时为空数组 `[]`|
|`data.position_quantity_series[].date`|日期|string|YYYY-MM-DD|该条持仓对应的业务日|随父级记录返回|
|`data.position_quantity_series[].quantity`|持仓数量|number|—|该日该标的的持仓数量|随父级记录返回；该日无持仓时补 `0`，不是 `null`；数量单位随资产类别变化，不是成交数量|
|`data.pnl_series`|盈亏序列|array（object）|—|该标的的逐日盈亏与区间累计盈亏，元素含下列键|恒返回；区间内没有该标的持仓时为空数组 `[]`|
|`data.pnl_series[].date`|日期|string|YYYY-MM-DD|该条盈亏对应的业务日|随父级记录返回|
|`data.pnl_series[].daily_pnl`|当日盈亏|number|估值币种金额|该日该标的的持仓盈亏|随父级记录返回；该日无持仓时为 `0`；同日多条记录先求和|
|`data.pnl_series[].pnl`|区间累计盈亏|number|估值币种金额|请求区间内逐日盈亏的累加值|随父级记录返回；从区间首日起算，不是该持仓自建仓以来的累计盈亏|
|`data.buy_points`|买入日期数组|array（string 元素）|—|区间内该标的买入流水的业务日，日期去重|恒返回；该标的资产类别不在支持范围内或区间内没有买入时为空数组 `[]`；元素顺序不保证|
|`data.sell_points`|卖出日期数组|array（string 元素）|—|区间内该标的卖出流水的业务日，日期去重|恒返回；条件与 `data.buy_points` 相同|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：`asset_class`、`direction` 与 `order_book_id` 一起确定唯一标的，省略 `asset_class` 或 `direction` 时定位不到持仓，持仓与盈亏序列会返回空数组；价格按资产类别取自复权净值、结算价、ETF 的 IOPV 或前复权收盘价，不是成交价。

**`algo_trading_performance`**

返回：`data` 为算法绩效对象，含分组明细、总数与告警。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|算法绩效结果|object|—|含 `items`、`total`、`warnings`，三者恒同时返回|`status` 为 `SUCCESS` 时返回|
|`data.items`|算法绩效条目|array（object）|—|按 `display_mode` 分组后的条目，元素含下列键|随父级返回；无任何可聚合分组时为空数组 `[]`，此时 `data.warnings` 仍可能非空|
|`data.items[].algo_name`|算法名称|string|—|该条目所属的算法名|随父级返回；没有算法名的流水不进任何条目|
|`data.items[].algo_type`|算法类型|string|—|按算法名分组时是组内出现过的算法类型去重拼接串，其余展示方式下是分组键原值|随父级返回；取值来自算法类型枚举，不是中文名|
|`data.items[].algo_time_span`|算法时间段|string|—|按算法名或算法名加类型分组时是组内时间段去重拼接串，按三者分组时是分组键原值|随父级返回；没有时间段时是空串，不是 `null`|
|`data.items[].turnover`|双边成交金额|number|本币金额|买入均价与卖出均价各自乘匹配数量后的合计|随父级返回；按本币折算；非 T0 只计已匹配部分，T0 有未平仓时改用全量买卖金额|
|`data.items[].total_equity`|期间日均净资产|number|本币金额|该条目涉及日期上产品净资产的算术平均|随父级返回；只对该条目出现过的日期取平均；取不到净资产的日期按 `0` 计入，故可能为 `0`|
|`data.items[].gross_pnl`|毛盈亏|number|本币金额|买卖均价差乘匹配数量的合计；T0 未平仓部分另按[标记价](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_open_auction_info)补算|随父级返回；不含费用；T0 取不到标记价时不补算，另有告警|
|`data.items[].gross_return_by_turnover`|毛收益率（成交额口径）|number|小数|`data.items[].gross_pnl` ÷ `data.items[].turnover`|随父级返回；分母为 `0` 或不可除时取 `0`，不是 `null`|
|`data.items[].gross_return_by_total_equity`|毛收益率（净资产口径）|number|小数|`data.items[].gross_pnl` ÷ `data.items[].total_equity`|随父级返回；分母为 `0` 时取 `0`，不是 `null`|
|`data.items[].net_pnl`|净盈亏|number|本币金额|毛盈亏减按匹配数量摊薄后的买卖费用|随父级返回；T0 有未平仓时费用按全量口径，不摊薄|
|`data.items[].return_by_turnover`|净收益率（成交额口径）|number|小数|`data.items[].net_pnl` ÷ `data.items[].turnover`|随父级返回；分母为 `0` 或不可除时取 `0`，不是 `null`|
|`data.items[].return_by_total_equity`|净收益率（净资产口径）|number|小数|`data.items[].net_pnl` ÷ `data.items[].total_equity`|随父级返回；分母为 `0` 时取 `0`，不是 `null`|
|`data.total`|条目总数|integer|条|`data.items` 的条目数|随父级返回；空结果时为 `0`；是分组条目数，不是交易笔数|
|`data.warnings`|告警|array（string 元素）|—|未纳入统计的说明：被忽略的暂不支持交易类型流水条数、T0 未平仓未取到标记价等|随父级返回；恒为数组，无告警时为空数组 `[]`|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：分组键随 `display_mode` 变化，比较不同展示方式前先对齐分组口径；`warnings` 非空说明部分流水未纳入统计，不能当作完整绩效；`items` 为空不代表没有异常，不支持的交易类型只体现在 `warnings` 上。

交易分析是结果视图，不修改流水；需要核对成交本身时用 [trades](../trades.md)。

