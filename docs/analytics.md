# 净值与收益指标、持仓分析、业绩归因与组合对比 analytics

指标是从不同角度衡量投资表现的一组数值：既可以看一段时间赚了多少，也可以看价值波动多大、曾经跌了多少，以及是否跑赢选定的比较对象。同名指标可能有不同算法，解读时应使用这里明确的计算口径，而不是只按名称猜测。

分析类操作回答“这段时间赚在哪、暴露在哪、同行之间差在哪”。它们都以产品估值结果为输入，再叠加持仓明细、分类标准、基准和行情；因此结论可能晚于估值就绪，也必须连同区间、基准和分类口径一起交付。

指标不是独立业务对象；完整字段列表直接列在各操作的返回说明中：[indicators](#indicators-returns)、[series](#series-inputs)、[win_rate](#win-rate-returns)、[long_short_returns](#long-short-returns-fields)；指标时序还可以用 [`download_series_file`](#download_series_file) 导出为工作簿。公式中的业务对象继续引用[头寸字段字典](fields/balances.md)。

分析结果不是新的估值数据，不能反向当作持仓或净值来源；区间内缺少头寸报表、行情或基准时，应报告缺口，而不是补零或缩小口径后宣称完成。字段级定义继续引用[头寸字段字典](fields/balances.md)，指标口径引用[指标返回字段与公式](#indicators-returns)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 从用户需求到操作

|用户需求|API 与输入准备|完成条件|
|---|---|---|
|比较区间收益、波动或回撤|`indicators`，明确日期和 benchmark，按需选择 extra_indicators|所需风险区块和额外指标可用，并注明日历、基准和有效区间|
|绘制或导出指标曲线|`series`，显式给区间和 indicators|按字段→日期→值解析；日期覆盖及缺失值已检查，不能把序列当作滚动风险统计|
|分析日/周/月胜率|`win_rate`，统一目标区间|同时核对各频率胜率与 returns_series，注明此方法和 get 中胜率口径不同|
|解释中性产品多空收益|`long_short_returns`，使用符合资产类别要求的单产品与日期范围|任务完成且拆解结果可用；不支持组，也不能把行情缺失当作零收益|
|把指标时序与胜率交付给线下核对|`series` 确认区间与指标 → `download_series_file` 落到新文件|工作簿已保存且日期、指标与 series 结果一致；不覆盖既有文件|
|看资产大类、行业或指数的权重分布|`asset_weight`，给产品/组、区间与分类数组|返回权重视图；分类数组非空，空分类会被拒绝|
|看股票、转债、期货、期权的持仓明细|`equity_holdings`、`convertible_holdings`、`convertible_positions`、`futures_holdings`、`option_holdings`，统一区间|任务终态成功，且区间内有对应资产类别持仓；空类别不是「无风险」|
|把持仓分析汇总交付线下|先用 `equity_holdings` 等确认口径 → `holdings_summary_file` 指定模板与新输出路径|工作簿落盘；模板必须显式选择，区间不能省略|
|做区间业绩归因|`create_attribution` 提交计算 → `attribution` 轮询同一归因 ID → `export_attribution` 导出|任务终态成功；归因 ID 与区间、基准、分类标准一一对应|
|看实时因子暴露与实时风险归因|`realtime_factor_exposure`、`realtime_risk_attribution`，仅单产品|返回实时截面；模板决定分解方式，产品组不支持该口径|
|比较成员产品的收益、规模与相关性|`group_returns`、`group_capital_size`、`group_returns_correlation`、`group_excess_correlation`，显式给成员与区间|任务终态成功；成员集合、区间与基准一致，否则相关性不可比|
|看组成员配置与组级指标|`group_allocation`、`group_indicators`|任务终态成功；指标视图与单产品指标口径不同，不能互换|
|导出组合对比报告|`group_overview_file` 指定新输出路径|工作簿落盘且与同参数查询一致；不覆盖既有文件|
|出一期周报|`weekly_report` 给成员与报告截止日|任务终态成功；按 `data.start_date`~`data.end_date` 引用本周窗口，成员按策略分入 `market_neutral` 与 `index_enhanced`|
|把周度净值报告交付线下|`weekly_net_value_report` 指定新输出路径|工作簿落盘且覆盖报告周；不覆盖既有文件|
|定位交易行为|`trading_analysis` 看区间交易列表，`single_trading_analysis` 看单标的明细，`algo_trading_performance` 看算法交易效果|任务终态成功；标的、方向与区间明确，算法交易的过滤条件按需给|

先用头寸报表时序核对所需历史数据是否齐备，再计算指标。不同方法的缺省日期不同；跨方法比较时显式对齐 start_date/end_date，避免把区间差异误判为计算差异。

计算类操作可能耗时较久；等待超时不代表任务取消——先确认原请求结果，不要直接重放提交。组合对比只提供一套组级口径，避免同一需求出现两套并行结果。

## API 使用约定

Python 与 CLI 完成相同调用，连接、任务等待与公共错误处理见[连接说明](connection.md)。`resource` 为产品或产品组的唯一 ID 或名称；`resources` 为非空数组，重复项会被去重，顺序保留。可选参数为 `None` 时不下发；数组型选择器可直接传逗号串，也可传数组。

做区间对比时显式指定日期、基准及指标集合，并记录实际返回中的缺失值。

- 调用是阻塞式的：Harness 内部完成等待与重试，最终返回服务端 JSON、文件元数据，或在达到等待上限时抛 `wait_timeout`；具体规则见[连接说明](connection.md)。
- **分析类**操作在返回说明里给出返回顶层结构与已核实的键，键内元素随服务端分析结果；净值与收益指标操作的字段与公式完整列在各自返回说明中。交付前先看实际键，不要按名称推断未列出的键。
- `attribution` 与 `export_attribution` 依赖已存在的归因 ID；删除归因按 ID 直接删除，网关要求 `read_position`，权限不足时以服务端错误返回。
- 组合对比的成员集合由调用方显式给出，Harness 不按产品组配置展开，避免与用户预期不一致。

## 净值与收益指标

下列 5 个操作读取服务端已算好的指标结果，客户端不重算；上游历史数据是否齐备先用[头寸报表](balances.md)时序核对。与[组合对比](#组合对比) 的 `group_indicators` 不同：后者按成员集合整组取数，口径与单产品指标不通用。

## indicators

计算产品或产品组区间指标。
- indicators：产品/组 daily_risk、weekly_risk、monthly_risk 与 last_unit_net_value；extra_indicators 可选 annual_risk、returns_summary、asset_series、benchmark_series、monthly_returns、win_rate、excess_returns、leverage_ratio、max_drawdown、excess_max_drawdown、ashares_market_value。额外字段各自数据形状见[下方完整返回字段表](#indicators-returns)。

Python 签名：`rqamsh.analytics.indicators(resource: str, *, start_date: str | None=None, end_date: str | None=None, benchmark: str | None=None, extra_indicators: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用资源起始日。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用最近结算日，且受产品到期日限制。|
|`benchmark`|`str \| None`|`None`|可选基准，格式为“类型,代码”。|
|`extra_indicators`|`list[str] \| None`|`None`|额外指标名称数组。|

<a id="indicators-returns"></a>

### 返回字段与计算公式

返回原始收益风险 JSON：有有效数据时默认包含 `daily_risk`、`weekly_risk`、`monthly_risk`；摘要非空且存在单位净值列时另含 `last_unit_net_value`。额外区块需通过 `extra_indicators` 选择；空组或无有效交易日会失败，无头寸摘要或基准数据可返回 `{}`。公式仅用于解释返回，API 不额外返回公式文本。

#### 完整返回字段大表

本表按服务端实际组装的返回结构整理，不是一次线上请求的实测样本；请求所选区块、是否提供累计单位净值和数据可用性决定实际出现哪些字段。

- 指标行中的头寸输入均链接到[头寸字段字典](fields/balances.md#balance-calculation)：该页是字段定义、逐仓/估值计算、精度和业务输入的唯一来源。本页只解释指标如何选取、对齐或聚合这些字段。
- 路径相对于 Python `result` 根对象；`.` 表示对象层级，`[]` 表示数组元素。重复指标合并说明：`{frequency}` 分别代入 `daily`、`weekly`、`monthly`；`{period_frequency}` 仅代入 `weekly`、`monthly`。两者都不是实际 JSON 键，也不表示把多个频率的结果合成一个值。例如 `{frequency}_risk.alpha` 对应 `daily_risk.alpha`、`weekly_risk.alpha`、`monthly_risk.alpha`。年度风险另有动态年份 `{year}`，例如 `annual_risk.2025.daily_risk.alpha`；年/月/周收益树节点仍逐项展开。
- “随父级返回”以父级确实存在且相应数据有效为前提，不代表无条件必有。未请求的额外区块不返回；缺失键、`null`、空对象和空数组不能解释为数值 0。
- 比例用小数表示，`0.01 = 1%`；金额为估值币种金额；净值、杠杆及风险比率不直接按百分数展示。表中 `number / null` 描述常规数值/空值，非有限数值的实际返回并不保证统一为 `null`，见下文异常数值说明。
- 用于比较业绩时，应同时展示区间、频率和基准。`n` 为该频率样本数，`F` 为该频率年化因子，`R=prod(1+r) - 1`，`B=prod(1+b) - 1`，`Ra=(1+R)^(F/n) - 1`，`Ba=(1+B)^(F/n) - 1`，`f` 为年化无风险利率，`f_p=(1+f)^(1/F) - 1`；`std`、`var`、`cov` 分别为样本标准差、方差、协方差（分母 `n - 1`），`C=[1,cumprod(1+r)]`，`cumprod` 为累计连乘，`running_max` 为截至当期的最高值。
- 年度风险中的 `r`、`b`、`n` 使用该年的分组数据，周/月仍沿用服务端周期归属；`R_daily`、`n_daily` 使用该年与请求区间交集的日序列。`dividend_ratio` 和复用整个请求区间的换手率按各自行说明。

|返回字段路径|中文名称|JSON 类型|返回条件|计算公式 / 结构|备注|
|---|---|---|---|---|---|
|`daily_risk`|日频风险指标|object|默认|按日频收益计算；年化因子 252|有效样本下含下列合并说明的 21 项；空频率可能仅含末尾三项年化/卡马尔字段，不应按完整对象强取|
|`weekly_risk`|周频风险指标|object|默认|按周频收益计算；年化因子 52|有效样本下含下列合并说明的 21 项；空频率可能仅含末尾三项年化/卡马尔字段，不应按完整对象强取|
|`monthly_risk`|月频风险指标|object|默认|按月频收益计算；年化因子 12|有效样本下含下列合并说明的 21 项；空频率可能仅含末尾三项年化/卡马尔字段，不应按完整对象强取|
|`{frequency}_risk.alpha`|年化詹森阿尔法|number / null|随父级对象返回|`Ra-f-beta*(Ba-f)`|扣除无风险收益及基准暴露后的收益|
|`{frequency}_risk.absolute_alpha`|零无风险利率口径的年化阿尔法|number / null|随父级对象返回|同 alpha，但 `f=0`|不是 `abs(alpha)`|
|`{frequency}_risk.beta`|贝塔|number / null|随父级对象返回|`cov(r,b)/var(b)`|收益相对基准的敏感度|
|`{frequency}_risk.sharpe`|夏普比率|number / null|随父级对象返回|`sqrt(F)*(mean(r)-f_p)/std(r)`|超无风险收益相对自身波动|
|`{frequency}_risk.absolute_sharpe`|零无风险利率口径的夏普比率|number / null|随父级对象返回|同 Sharpe，但 `f=0`|不是 `abs(sharpe)`|
|`{frequency}_risk.excess_sharpe`|超额收益夏普比率|number / null|随父级对象返回|`sqrt(F)*mean(r-b)/std(r-b)`|—|
|`{frequency}_risk.max_drawdown`|最大回撤|number / null|随父级对象返回|`abs(min((C-running_max(C))/running_max(C)))`，含初始 1|—|
|`{frequency}_risk.annual_downside_risk`|年化下行风险|number / null|随父级对象返回|`sqrt(F)*sqrt(sum(min(r-mean(r),0)^2)/(n - 1))`|低于自身均值部分的波动；阈值不是零或无风险利率|
|`{frequency}_risk.information_ratio`|信息比率|number / null|随父级对象返回|`(Ra-beta*Ba)/(std(r-beta*b)*sqrt(F))`|基准暴露调整后的残差收益/残差风险；**不是** `mean(r-b)/tracking_error`|
|`{frequency}_risk.geometric_excess_annual_return`|几何超额年化收益率|number / null|随父级对象返回|`(1+Ra)/(1+Ba) - 1`|—|
|`{frequency}_risk.arithmetic_excess_annual_return`|逐期算术超额连乘后的年化收益率|number / null|随父级对象返回|`prod(1+r-b)^(F/n) - 1`|不是 `Ra-Ba`|
|`{frequency}_risk.annual_volatility`|年化收益波动率|number / null|随父级对象返回|`std(r)*sqrt(F)`|—|
|`{frequency}_risk.excess_annual_volatility`|年化超额收益波动率|number / null|随父级对象返回|`std(r-b)*sqrt(F)`|—|
|`{frequency}_risk.annual_tracking_error`|年化跟踪误差|number / null|随父级对象返回|`std(r-b)*sqrt(F)`|基准全 NaN 时 NaN|
|`{frequency}_risk.geometric_excess_max_drawdown`|几何超额最大回撤|number / null|随父级对象返回|对 `cumprod(1+r)/cumprod(1+b)`（含初始 1）求最大回撤|—|
|`{frequency}_risk.total_returns`|区间累计收益率|number / null|随父级对象返回|`R`|该频率收益序列；不保证等于 `returns_summary.total` 的净值差法|
|`{frequency}_risk.total_geometric_excess_return`|区间几何超额收益率|number / null|随父级对象返回|`(1+R)/(1+B) - 1`|—|
|`{frequency}_risk.total_arithmetic_excess_return`|区间算术超额收益率|number / null|随父级对象返回|`R-B`|与逐期算术超额连乘不同|
|`{frequency}_risk.total_annual_returns`|日频区间累计收益折算的年化收益率|number / null|随父级对象返回|所有频率统一引用 `(1+R_daily)^(D/n_daily) - 1`，`D=交易252/自然365`|—|
|`{frequency}_risk.annual_simple_interest`|日频区间累计收益折算的单利年化收益率|number / null|随父级对象返回|所有频率统一引用 `R_daily/n_daily*S`，`S=交易250/自然365`|—|
|`{frequency}_risk.calmar_ratio`|卡马尔比率|number / null|随父级对象返回|上述日频期间年化收益除该频率 `max_drawdown`|期间年化收益相对最大回撤；零回撤时不能理解为可确定的无限回报|
|`last_unit_net_value`|区间末单位净值|number / null|默认；摘要非空且存在 unit_net_value 列|整理后同日头寸报表 [unit_net_value](fields/balances.md#unit-net-value) 的最后一条|默认返回，不是累计净值|
|`annual_risk`|逐年风险|object|extra_indicators 包含 annual_risk|年份键 → 日/周/月风险对象|需 extra_indicators 选择 annual_risk；每年重新选择无风险利率|
|`annual_risk.{year}`|某年风险指标|object|随 annual_risk 返回|{year} 为实际年份字符串，例如 2025|按请求区间与该年的交集计算|
|`annual_risk.{year}.daily_risk`|该年日频风险指标|object|随 annual_risk 返回|该年对应频率收益；重新选择该年区间无风险利率|有效样本下含下列合并说明的 23 项；空频率仍可能只含年化/卡马尔及两项补充字段|
|`annual_risk.{year}.weekly_risk`|该年周频风险指标|object|随 annual_risk 返回|该年对应频率收益；重新选择该年区间无风险利率|有效样本下含下列合并说明的 23 项；空频率仍可能只含年化/卡马尔及两项补充字段|
|`annual_risk.{year}.monthly_risk`|该年月频风险指标|object|随 annual_risk 返回|该年对应频率收益；重新选择该年区间无风险利率|有效样本下含下列合并说明的 23 项；空频率仍可能只含年化/卡马尔及两项补充字段|
|`annual_risk.{year}.{frequency}_risk.alpha`|年化詹森阿尔法|number / null|随父级对象返回|`Ra-f-beta*(Ba-f)`|扣除无风险收益及基准暴露后的收益|
|`annual_risk.{year}.{frequency}_risk.absolute_alpha`|零无风险利率口径的年化阿尔法|number / null|随父级对象返回|同 alpha，但 `f=0`|不是 `abs(alpha)`|
|`annual_risk.{year}.{frequency}_risk.beta`|贝塔|number / null|随父级对象返回|`cov(r,b)/var(b)`|收益相对基准的敏感度|
|`annual_risk.{year}.{frequency}_risk.sharpe`|夏普比率|number / null|随父级对象返回|`sqrt(F)*(mean(r)-f_p)/std(r)`|超无风险收益相对自身波动|
|`annual_risk.{year}.{frequency}_risk.absolute_sharpe`|零无风险利率口径的夏普比率|number / null|随父级对象返回|同 Sharpe，但 `f=0`|不是 `abs(sharpe)`|
|`annual_risk.{year}.{frequency}_risk.excess_sharpe`|超额收益夏普比率|number / null|随父级对象返回|`sqrt(F)*mean(r-b)/std(r-b)`|—|
|`annual_risk.{year}.{frequency}_risk.max_drawdown`|最大回撤|number / null|随父级对象返回|`abs(min((C-running_max(C))/running_max(C)))`，含初始 1|—|
|`annual_risk.{year}.{frequency}_risk.annual_downside_risk`|年化下行风险|number / null|随父级对象返回|`sqrt(F)*sqrt(sum(min(r-mean(r),0)^2)/(n - 1))`|低于自身均值部分的波动；阈值不是零或无风险利率|
|`annual_risk.{year}.{frequency}_risk.information_ratio`|信息比率|number / null|随父级对象返回|`(Ra-beta*Ba)/(std(r-beta*b)*sqrt(F))`|基准暴露调整后的残差收益/残差风险；**不是** `mean(r-b)/tracking_error`|
|`annual_risk.{year}.{frequency}_risk.geometric_excess_annual_return`|几何超额年化收益率|number / null|随父级对象返回|`(1+Ra)/(1+Ba) - 1`|—|
|`annual_risk.{year}.{frequency}_risk.arithmetic_excess_annual_return`|逐期算术超额连乘后的年化收益率|number / null|随父级对象返回|`prod(1+r-b)^(F/n) - 1`|不是 `Ra-Ba`|
|`annual_risk.{year}.{frequency}_risk.annual_volatility`|年化收益波动率|number / null|随父级对象返回|`std(r)*sqrt(F)`|—|
|`annual_risk.{year}.{frequency}_risk.excess_annual_volatility`|年化超额收益波动率|number / null|随父级对象返回|`std(r-b)*sqrt(F)`|—|
|`annual_risk.{year}.{frequency}_risk.annual_tracking_error`|年化跟踪误差|number / null|随父级对象返回|`std(r-b)*sqrt(F)`|基准全 NaN 时 NaN|
|`annual_risk.{year}.{frequency}_risk.geometric_excess_max_drawdown`|几何超额最大回撤|number / null|随父级对象返回|对 `cumprod(1+r)/cumprod(1+b)`（含初始 1）求最大回撤|—|
|`annual_risk.{year}.{frequency}_risk.total_returns`|区间累计收益率|number / null|随父级对象返回|`R`|该频率收益序列；不保证等于 `returns_summary.total` 的净值差法|
|`annual_risk.{year}.{frequency}_risk.total_geometric_excess_return`|区间几何超额收益率|number / null|随父级对象返回|`(1+R)/(1+B) - 1`|—|
|`annual_risk.{year}.{frequency}_risk.total_arithmetic_excess_return`|区间算术超额收益率|number / null|随父级对象返回|`R-B`|与逐期算术超额连乘不同|
|`annual_risk.{year}.{frequency}_risk.total_annual_returns`|日频区间累计收益折算的年化收益率|number / null|随父级对象返回|所有频率统一引用 `(1+R_daily)^(D/n_daily) - 1`，`D=交易252/自然365`|—|
|`annual_risk.{year}.{frequency}_risk.annual_simple_interest`|日频区间累计收益折算的单利年化收益率|number / null|随父级对象返回|所有频率统一引用 `R_daily/n_daily*S`，`S=交易250/自然365`|—|
|`annual_risk.{year}.{frequency}_risk.calmar_ratio`|卡马尔比率|number / null|随父级对象返回|上述日频期间年化收益除该频率 `max_drawdown`|期间年化收益相对最大回撤；零回撤时不能理解为可确定的无限回报|
|`annual_risk.{year}.{frequency}_risk.dividend_ratio`|股票分红率|number / null|随父级对象返回|请求年份范围内 `sum(stock_dividend_amount)` / 该年范围最后自然日 `(cn_stock_market_value+hk_stock_market_value)`|不是平均股票市值，也不含产品分红。金额全为零时可能无结果；金额缺失或无效时可能提示估值未就绪，零分母为空值；来源 [stock_dividend_amount](fields/balances.md#balancedailysummary) 与[股票市值字段](fields/balances.md#balance-calculation)。|
|`annual_risk.{year}.{frequency}_risk.annual_twoside_turnover_rate`|年化双边换手率|number / null|随父级对象返回|同 returns_summary.annual_twoside_turnover_rate|复用整个请求区间值，不是按年独立重算|
|`returns_summary`|区间收益概览|object|extra_indicators 包含 returns_summary|含以下十个字段|需 extra_indicators 选择 returns_summary|
|`returns_summary.total`|区间累计收益|number / null|随父级对象返回|单产品且提供累计单位净值时 `(AccNAV[期末] - AccNAV[起点]) / NAV[起点]`<br>&emsp;否则日收益累乘|`annual` 使用252/365，`annual_simple_interest` 使用250/365|
|`returns_summary.this_week`|向前一周的滚动收益|number / null|随父级对象返回|从区间末日回看 1 周的滚动窗口|并非本自然周|
|`returns_summary.this_month`|向前一月的滚动收益|number / null|随父级对象返回|从区间末日回看 1 月的滚动窗口|并非本自然月|
|`returns_summary.this_quarter`|向前三月的滚动收益|number / null|随父级对象返回|从区间末日回看 3 月的滚动窗口|并非本自然季度|
|`returns_summary.this_year`|向前一年的滚动收益|number / null|随父级对象返回|从区间末日回看 1 年的滚动窗口|并非本自然年度|
|`returns_summary.annual`|复利年化收益率|number / null|随父级对象返回|(1+returns_summary.total)^(D/n_daily)−1；D=交易252/自然365|n_daily 为对齐后的基准日收益样本数|
|`returns_summary.annual_simple_interest`|单利年化收益率|number / null|随父级对象返回|returns_summary.total/n_daily×S；S=交易250/自然365|不采用风险频率的 F|
|`returns_summary.arithmetic_excess`|区间算术超额收益|number / null|随父级对象返回|returns_summary.total−B_daily|B_daily 为同区间基准日收益连乘减 1|
|`returns_summary.geometric_excess`|区间几何超额收益|number / null|随父级对象返回|(1+returns_summary.total)/(1+B_daily)−1|基准增长倍数为零时无效|
|`returns_summary.annual_twoside_turnover_rate`|年化双边换手率|number / null|随父级对象返回|`(sum(buy_amount)+sum(sell_amount))/mean(total_equity)/n*D`，`D=252/365`|买卖金额取[买入](fields/balances.md#buy-amount)、[卖出](fields/balances.md#sell-amount)，净资产取[total_equity](fields/balances.md#total-equity)。空序列为空值；净资产缺口沿用之前值，交易日按日历对齐。零净资产时不能给出有效换手结论；缺失金额不应被理解为已确认无交易。|
|`asset_series`|产品表现序列|object|extra_indicators 包含 asset_series|daily/weekly/monthly → array（日期记录）|需 extra_indicators 选择同名区块|
|`asset_series.daily`|日频记录列表|array（object）|随 asset_series 返回|按日频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`asset_series.weekly`|周频记录列表|array（object）|随 asset_series 返回|按周频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`asset_series.monthly`|月频记录列表|array（object）|随 asset_series 返回|按月频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`asset_series.{frequency}[].date`|业务日期|string|随父级记录返回|日频为当日；周/月频为实际周期末日|日期随产品日历及可用数据，不假定为完整周/月|
|`asset_series.daily[].daily_returns`|日收益率|number / null|随父级记录返回|r_daily；净值差法或头寸报表 [daily_returns](fields/balances.md#daily-returns)|按本操作输入整理规则|
|`asset_series.daily[].period_net_value`|计算用净值|number / null|随父级记录返回|提供累计单位净值时取后向补齐的 [acc_unit_net_value](fields/balances.md#acc-unit-net-value)；否则 cumprod(1+r_daily)|不是所有分支都等于单位净值|
|`asset_series.daily[].cumulative_returns`|累计收益率|number / null|随父级记录返回|提供累计单位净值时 (AccNAV[当日]−AccNAV[起点])/NAV[起点]；否则 cumprod(1+r_daily)−1|—|
|`asset_series.{frequency}[].unit_net_value`|单位净值|number / null|随父级记录返回|取整理后同日/周期末头寸报表 [unit_net_value](fields/balances.md#unit-net-value)|保留缺失，不假定三种净值相同|
|`asset_series.{frequency}[].acc_unit_net_value`|累计单位净值|number / null|随父级记录返回|取整理后同日/周期末头寸报表 [acc_unit_net_value](fields/balances.md#acc-unit-net-value)|保留缺失，不假定三种净值相同|
|`asset_series.{frequency}[].adjusted_net_value`|复权净值|number / null|随父级记录返回|日频提供累计单位净值时 cumprod(1+r_daily)；其他情况取头寸报表 [adjusted_net_value](fields/balances.md#adjusted-net-value)，全缺时以连乘补算；周/月取周期末头寸报表值|保留缺失，不假定三种净值相同|
|`asset_series.{period_frequency}[].portfolio_returns`|周期收益率|number / null|随父级记录返回|周期净值差/期初单位净值；组或未提供累计单位净值时 prod(1+r_daily)−1|—|
|`asset_series.{period_frequency}[].cumulative_returns`|周期累计收益率|number / null|随父级记录返回|同频率 portfolio_returns 的 cumprod(1+r)−1|不保证与日频净值差法累计收益一致|
|`benchmark_series`|基准表现序列|object|extra_indicators 包含 benchmark_series|daily/weekly/monthly → array（日期记录）|需 extra_indicators 选择同名区块|
|`benchmark_series.daily`|日频记录列表|array（object）|随 benchmark_series 返回|按日频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`benchmark_series.weekly`|周频记录列表|array（object）|随 benchmark_series 返回|按周频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`benchmark_series.monthly`|月频记录列表|array（object）|随 benchmark_series 返回|按月频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`benchmark_series.{frequency}[].date`|业务日期|string|随父级记录返回|日频为当日；周/月频为实际周期末日|日期随产品日历及可用数据，不假定为完整周/月|
|`benchmark_series.daily[].daily_returns`|基准日收益|number / null|随父级记录返回|b_daily|[基准来源](#external-inputs)，不是产品头寸|
|`benchmark_series.daily[].unit_net_value`|基准增长净值|number / null|原始摘要存在 unit_net_value 列时返回|cumprod(1+b_daily)|[基准来源](#external-inputs)，不是产品头寸|
|`benchmark_series.daily[].cumulative_returns`|基准累计收益|number / null|原始摘要存在 unit_net_value 列时返回|cumprod(1+b_daily)−1|[基准来源](#external-inputs)，不是产品头寸|
|`benchmark_series.{frequency}[].total_turnover`|基准成交额|number|基准成交额序列非空时返回|日频取行情成交额，周/月按日成交额求和|仅数据支持时返回；[外部输入](#external-inputs)，不是产品买卖额|
|`benchmark_series.{period_frequency}[].benchmark_returns`|基准周期收益|number / null|随父级记录返回|prod(1+b_daily)−1|—|
|`benchmark_series.{period_frequency}[].benchmark_cumulative_returns`|基准周期累计收益|number / null|随父级记录返回|cumprod(1+b_period)−1|—|
|`monthly_returns`|年/月/周收益明细|array（object）|extra_indicators 包含 monthly_returns|年份节点 children 为月份，月份 children 为周|需 extra_indicators 选择 monthly_returns|
|`monthly_returns[]`|年收益记录|object|随父级数组返回|以下字段组成一个年节点|数组元素路径；[] 不是 JSON 键|
|`monthly_returns[].date`|年份|string|随父级记录返回|YYYY|结构标签|
|`monthly_returns[].portfolio_returns`|产品周期收益|number / null|随父级记录返回|单产品净值差/NAV[期初]；否则 prod(1+r_daily)−1|净值来源见下方字段链接|
|`monthly_returns[].benchmark_returns`|基准周期收益|number / null|随父级记录返回|prod(1+b_daily)−1|[基准来源](#external-inputs)，不是产品头寸|
|`monthly_returns[].arithmetic_excess_returns`|算术超额收益|number / null|随父级记录返回|portfolio_returns−benchmark_returns|使用同一频率的产品与基准收益|
|`monthly_returns[].geometric_excess_returns`|几何超额收益|number / null|随父级记录返回|(1+portfolio_returns)/(1+benchmark_returns)−1|基准增长倍数为零时无效|
|`monthly_returns[].unit_net_value`|期末单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [unit_net_value](fields/balances.md#unit-net-value)|—|
|`monthly_returns[].acc_unit_net_value`|期末累计单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [acc_unit_net_value](fields/balances.md#acc-unit-net-value)|—|
|`monthly_returns[].adjusted_net_value`|期末复权净值|number / null|随父级记录返回|期末头寸报表 [adjusted_net_value](fields/balances.md#adjusted-net-value)|—|
|`monthly_returns[].children`|月份列表|array|随父级记录返回|所选年份内实际月份|月份节点的 children 是周列表|
|`monthly_returns[].children[]`|月收益记录|object|随父级数组返回|以下字段组成一个月节点|数组元素路径；[] 不是 JSON 键|
|`monthly_returns[].children[].date`|月份|string|随父级记录返回|YYYY-MM|结构标签|
|`monthly_returns[].children[].portfolio_returns`|产品周期收益|number / null|随父级记录返回|单产品净值差/NAV[期初]；否则 prod(1+r_daily)−1|净值来源见下方字段链接|
|`monthly_returns[].children[].benchmark_returns`|基准周期收益|number / null|随父级记录返回|prod(1+b_daily)−1|[基准来源](#external-inputs)，不是产品头寸|
|`monthly_returns[].children[].arithmetic_excess_returns`|算术超额收益|number / null|随父级记录返回|portfolio_returns−benchmark_returns|使用同一频率的产品与基准收益|
|`monthly_returns[].children[].geometric_excess_returns`|几何超额收益|number / null|随父级记录返回|(1+portfolio_returns)/(1+benchmark_returns)−1|基准增长倍数为零时无效|
|`monthly_returns[].children[].unit_net_value`|期末单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [unit_net_value](fields/balances.md#unit-net-value)|—|
|`monthly_returns[].children[].acc_unit_net_value`|期末累计单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [acc_unit_net_value](fields/balances.md#acc-unit-net-value)|—|
|`monthly_returns[].children[].adjusted_net_value`|期末复权净值|number / null|随父级记录返回|期末头寸报表 [adjusted_net_value](fields/balances.md#adjusted-net-value)|—|
|`monthly_returns[].children[].end_date`|月内末个观测日|string|随父级记录返回|月样本最后日期|不保证自然月末|
|`monthly_returns[].children[].annual_excess_volatility`|月内超额波动率|number / null|随父级记录返回|月内日收益差 std(r_daily−b_daily)×sqrt(D/完整月日数)，D=交易252/自然365|样本标准差；分母为完整月日数，不是请求区间截取天数|
|`monthly_returns[].children[].children`|周列表|array|随父级记录返回|月份所含周收益记录|允许不完整周|
|`monthly_returns[].children[].children[]`|周收益记录|object|随父级数组返回|以下字段组成一个周节点|数组元素路径；[] 不是 JSON 键|
|`monthly_returns[].children[].children[].date`|月内周序号|integer|随父级记录返回|按产品日历划分的月内周编号|周按周日结束，跨月周依服务端归属|
|`monthly_returns[].children[].children[].portfolio_returns`|产品周期收益|number / null|随父级记录返回|单产品净值差/NAV[期初]；否则 prod(1+r_daily)−1|净值来源见下方字段链接|
|`monthly_returns[].children[].children[].benchmark_returns`|基准周期收益|number / null|随父级记录返回|prod(1+b_daily)−1|[基准来源](#external-inputs)，不是产品头寸|
|`monthly_returns[].children[].children[].arithmetic_excess_returns`|算术超额收益|number / null|随父级记录返回|portfolio_returns−benchmark_returns|使用同一频率的产品与基准收益|
|`monthly_returns[].children[].children[].geometric_excess_returns`|几何超额收益|number / null|随父级记录返回|(1+portfolio_returns)/(1+benchmark_returns)−1|基准增长倍数为零时无效|
|`monthly_returns[].children[].children[].unit_net_value`|期末单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [unit_net_value](fields/balances.md#unit-net-value)|—|
|`monthly_returns[].children[].children[].acc_unit_net_value`|期末累计单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [acc_unit_net_value](fields/balances.md#acc-unit-net-value)|—|
|`monthly_returns[].children[].children[].adjusted_net_value`|期末复权净值|number / null|随父级记录返回|期末头寸报表 [adjusted_net_value](fields/balances.md#adjusted-net-value)|—|
|`monthly_returns[].children[].children[].start_date`|周起始日|string|随父级记录返回|本周期计算起点|可能与请求起点截断相关|
|`monthly_returns[].children[].children[].end_date`|周结束日|string|随父级记录返回|本周期最后样本日|不保证完整周|
|`win_rate`|各频率胜率|object|extra_indicators 包含 win_rate|日/周/月各三项非负收益比例|需 extra_indicators 选择 win_rate；不是独立 win_rate API 的返回树|
|`win_rate.{frequency}_abs_win_rate`|绝对收益胜率|number / null|随父级对象返回|相应频率满足 r>=0 的样本数/总样本数|零收益算赢；缺样本不等于胜率零|
|`win_rate.{frequency}_arithmetic_win_rate`|算术超额胜率|number / null|随父级对象返回|相应频率满足 r−b>=0 的样本数/总样本数|零收益算赢；缺样本不等于胜率零|
|`win_rate.{frequency}_geometric_win_rate`|几何超额胜率|number / null|随父级对象返回|相应频率满足 (1+r)/(1+b)−1>=0 的样本数/总样本数|零收益算赢；缺样本不等于胜率零|
|`excess_returns`|超额收益序列|object|extra_indicators 包含 excess_returns|daily/weekly/monthly → array（日期记录）|需 extra_indicators 选择同名区块|
|`excess_returns.daily`|日频记录列表|array（object）|随 excess_returns 返回|按日频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`excess_returns.weekly`|周频记录列表|array（object）|随 excess_returns 返回|按周频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`excess_returns.monthly`|月频记录列表|array（object）|随 excess_returns 返回|按月频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`excess_returns.{frequency}[].date`|业务日期|string|随父级记录返回|日频为当日；周/月频为实际周期末日|日期随产品日历及可用数据，不假定为完整周/月|
|`excess_returns.{frequency}[].arithmetic_excess_returns`|算术超额收益|number / null|随父级记录返回|r−b|使用对应频率的收益序列|
|`excess_returns.{frequency}[].geometric_excess_returns`|几何超额收益|number / null|随父级记录返回|(1+r)/(1+b)−1|使用对应频率的收益序列|
|`excess_returns.{frequency}[].arithmetic_excess_cumulative_returns`|累计比较的算术超额|number / null|随父级记录返回|cumprod(1+r)−cumprod(1+b)|使用对应频率的收益序列|
|`excess_returns.{frequency}[].geometric_excess_cumulative_returns`|累计几何超额|number / null|随父级记录返回|cumprod(1+r)/cumprod(1+b)−1|使用对应频率的收益序列|
|`leverage_ratio`|资产杠杆序列|object|extra_indicators 包含 leverage_ratio|daily/weekly/monthly → array（日期记录）|需 extra_indicators 选择同名区块|
|`leverage_ratio.daily`|日频记录列表|array（object）|随 leverage_ratio 返回|按日频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`leverage_ratio.weekly`|周频记录列表|array（object）|随 leverage_ratio 返回|按周频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`leverage_ratio.monthly`|月频记录列表|array（object）|随 leverage_ratio 返回|按月频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`leverage_ratio.{frequency}[].date`|业务日期|string|随父级记录返回|日频为当日；周/月频为实际周期末日|日期随产品日历及可用数据，不假定为完整周/月|
|`leverage_ratio.{frequency}[].leverage_ratio`|资产杠杆倍数|number / null|随父级记录返回|total_assets/total_equity|分子取同日/周期末 [total_assets](fields/balances.md#total-assets)，分母取 [total_equity](fields/balances.md#total-equity)；零净资产时比值可能非有限|
|`leverage_ratio.{frequency}[].total_assets`|总资产|number / null|随父级记录返回|同日/周期末头寸报表 [total_assets](fields/balances.md#total-assets)|字段定义与计算见[头寸字段字典](fields/balances.md#balance-calculation)；零净资产时比值可能非有限|
|`leverage_ratio.{frequency}[].total_equity`|净资产|number / null|随父级记录返回|同日/周期末头寸报表 [total_equity](fields/balances.md#total-equity)|字段定义与计算见头寸字段字典；零净资产时比值可能非有限|
|`max_drawdown`|绝对回撤详情|object|extra_indicators 包含 max_drawdown|产品累计增长曲线 C的高点、谷底和恢复时间|需 extra_indicators 选择同名项；并非风险表中的数值 max_drawdown|
|`max_drawdown.max_drawdown_period`|绝对最大回撤区间|string|随父级对象返回|同深度取最后谷底；前峰至谷底的日期和包含两端的样本日数|无回撤为“未出现回撤”；初始基点前峰按第一样本日标记；非单笔最大亏损|
|`max_drawdown.max_drawdown_recovery_days`|绝对回撤修复时长|string|随父级对象返回|谷底后首次不低于前峰的样本距离|标记交易日/自然日；未回撤、未修复、终止前未修复均保留原文，不转换成 0|
|`excess_max_drawdown`|几何超额回撤详情|object|extra_indicators 包含 excess_max_drawdown|产品/基准累计增长比值曲线的高点、谷底和恢复时间|需 extra_indicators 选择同名项；并非风险表中的数值 max_drawdown|
|`excess_max_drawdown.geometric_excess_max_drawdown_period`|几何超额最大回撤区间|string|随父级对象返回|同深度取最后谷底；前峰至谷底的日期和包含两端的样本日数|无回撤为“未出现回撤”；初始基点前峰按第一样本日标记；非单笔最大亏损|
|`excess_max_drawdown.geometric_excess_max_drawdown_recovery_days`|几何超额回撤修复时长|string|随父级对象返回|谷底后首次不低于前峰的样本距离|标记交易日/自然日；未回撤、未修复、终止前未修复均保留原文，不转换成 0|
|`ashares_market_value`|沪深市值|object|extra_indicators 包含 ashares_market_value|末个可用沪深股票市值及 T-20 至 T-1 均值|需 extra_indicators 选择同名项；T 为请求截止日|
|`ashares_market_value.sh_market_value`|沪市股票市值|number|随父级对象返回|最后可用头寸报表 cn_sh_stock_market_value|[股票市值](fields/balances.md#balance-calculation)|
|`ashares_market_value.sh_market_value_prev`|沪市前20日平均市值|number|随父级对象返回|T-20 至 T-1 的 cn_sh_stock_market_value 合计/20|交易所交易日回看；缺日仍除 20，不是最近20条记录均值|
|`ashares_market_value.sz_market_value`|深市股票市值|number|随父级对象返回|最后可用头寸报表 cn_sz_stock_market_value|[股票市值](fields/balances.md#balance-calculation)|
|`ashares_market_value.sz_market_value_prev`|深市前20日平均市值|number|随父级对象返回|T-20 至 T-1 的 cn_sz_stock_market_value 合计/20|交易所交易日回看；缺日仍除 20，不是最近20条记录均值|

<a id="indicator-inputs"></a>

#### 数据链与变量

- 指标建立在逐日头寸报表、盈亏和净值序列上，可能包含可用实时截面；不是把流水金额简单相加。行情、汇率、权益与托管事件、份额变化、公允价及[估值表覆盖](reconciliation.md#valuation-report-overwrite)影响头寸字段；字段定义、计算、精度和输入链只见[头寸字段字典](fields/balances.md#balance-calculation)。
- 指标公式使用的头寸字段：`Equity[当日]` → [total_equity](fields/balances.md#total-equity)，`PnL[当日]` → [daily_pnl](fields/balances.md#daily-pnl)，`NAV[当日]` → [unit_net_value](fields/balances.md#unit-net-value)，`AccNAV[当日]` → [acc_unit_net_value](fields/balances.md#acc-unit-net-value)。
- `Return[当日]` 是当前整理频率下的产品/组周期收益，日频时为该日收益；`r` 表示该周期收益序列。`b_t` 是同日历、同频率的基准周期收益，`b` 表示对应基准收益序列；`f` 为年化无风险利率，来源见[外部输入](#external-inputs)。
- `[上一估值日]` 是整理后序列的上一估值时点；`[期初]`、`[期末]` 为选定统计区间端点；`[起点]` 是该分支采用的收益计算基点。`AccNAV[当日] - 1` 是减一，`AccNAV[上一估值日]` 是取历史值，二者不能混用。
- 公式符号：`prod` 连乘，`sum` 求和，`abs` 绝对值，`mean` 平均数。`buy_amount`、`sell_amount`、`stock_dividend_amount`、市值、风险市值和申赎字段均链接本页各指标行或[头寸字段字典](fields/balances.md#balance-calculation)，不在指标页重述其估值或流水计算。

#### 输入整理与日历

1. 无头寸报表摘要或无基准数据时可能返回 `{}`；不表示零收益。分析区间受产品开始日、到期日及实际基准范围限制；没有合法日历日期时会报错。
2. 头寸报表摘要与自然日基准日期对齐；[total_equity](fields/balances.md#total-equity)、[total_assets](fields/balances.md#total-assets)、[unit_net_value](fields/balances.md#unit-net-value) 缺口使用之前的值，[daily_returns](fields/balances.md#daily-returns) 缺失按 0。累计净值不在此步补齐。
3. 交易日产品只保留交易所日历，自然日产品保留自然日；净值按 AMS 精度舍入后参与指标计算。精度位数和字段自身的舍入顺序见[头寸字段字典](fields/balances.md#balance-calculation)，本页不另作假定或客户端重算。
4. 单产品有有效累计净值和单位净值时，净值空缺先用后续有效值补齐；再用 `Return[当日] = (AccNAV[当日] - AccNAV[上一估值日]) / NAV[上一估值日]`。请求区间前一天净值为起点，缺失或零基点按 1。周/月收益为 `(期末累计净值-期初累计净值)/期初单位净值`，**不是累计净值相除**。产品组及无上述净值的产品使用 [daily_returns](fields/balances.md#daily-returns) 连乘。
5. 周按周日结束，月按月末，年按年末分组。结果可含不完整周/月；比较不同区间时应检查实际起止日期。
6. 日/周/月风险指标的年化因子分别为 252/52/12，包括自然日产品的日频波动、Sharpe 等风险指标。另有字段特定口径：`total_annual_returns` 使用交易日 252 / 自然日 365，`annual_simple_interest` 使用交易日 250 / 自然日 365。不能把自然日产品所有指标一律按 365 年化。

`alpha` 表示扣除基准暴露及无风险收益后的年化收益，`beta` 表示相对基准的敏感度，Sharpe 用波动衡量收益风险比，回撤衡量区间内由高点到低点的跌幅。跟踪误差描述与基准收益差异的波动；`information_ratio` 使用本表明确口径，不能替换成另一种常见定义。

零分母可能产生无效数值。alpha、beta、Sharpe、information_ratio 至少需 2 期；不足时不可作为有效比较结果。波动、下行风险和跟踪误差不足 2 期可能返回 0，后续比值仍可能无效。收益低于 -100%、基准净值为零或非有限值也可能使结果无效；返回表现并不保证统一为 `null`，Agent 不得伪造为 0 或继续排名。

滚动收益 this_week/this_month/this_quarter/this_year 分别回看 1 周、1 月、3 月、1 年；提供累计单位净值时沿用区间末累计净值减窗口起点累计净值、除窗口起点单位净值，起点缺失时回退请求区间基点；其他情况对窗口日收益连乘减 1。并非自然周/月/季度/年度。

两种公开胜率操作都把零收益算赢，但采用的收益序列可能不同，不应直接拼接或宣称一致。若用户要求严格“正收益才算赢”，应先约定口径，不把默认胜率冒充该统计。

指数增强特殊口径：仅单产品、策略 `index_enhanced` 且请求 `start_date` 等于 `trading_start_date` 时，指定超额指标从交易起始日**下一交易所交易日**起算，以交易起始日结算单位/累计净值为基点；绝对收益不因此改变。缺基点、后续头寸报表摘要或基准时不应用此调整。比较指增产品时，应核对区间是否触发该口径。


#### 复算所需的外部输入

##### 可复算边界

国债曲线、基准成分及历史行情修订、日历、场外价格（[基金净值](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_nav)）、汇率时点（[港币汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk)）、权益到账规则（[股票分红](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)）、托管及份额事件、资产单元穿透、组权重/调仓和历史估值结果均不包含在一次指标返回中。做对账或审计时，应保存请求区间、产品/组配置、头寸报表序列、基准及相关行情、实际返回；仅凭流水 `price*quantity` 无法复算全部指标。不能复核时明确说明缺少哪些数据，并请求用户或 AMS 管理员协助，不要修改公式来凑齐结果。

<a id="external-inputs"></a>

##### 外部数据与非持仓来源
|英文字段|中文名称|实际计算|备注|
|---|---|---|---|
|`f`|年化无风险利率|[RQData get_yield_curve](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_yield_curve)(start_date,end_date) 获取中债国债收益率曲线，数值为小数年利率，例如 `0.02` 表示 2%；删除含缺值的期限列，按区间自然日跨度选择不长于区间的可用期限，取该列首个观测值|曲线 None/空表取 0；列过滤后没有可选期限不保证也返回 0。不除以 100，不从产品现金利息倒算，不直接将年利率减到日收益上|
|`b_t`|基准周期收益|预设指数：前复权 `close` 按日历对齐前向填充后 `pct_change`，读取起点前一交易日；收益缺失补 0。<br>&emsp;国债基准：固定取曲线 1Y，沿用前值后按 `(1+y)^(1/D) - 1`，`D=交易252/自然365`。<br>&emsp;固定收益基准：配置 `rates` 按 `(1+rates)^(1/D) - 1`。<br>&emsp;组合基准（[指数权重](https://www.ricequant.com/doc/rqdata/python/indices-mod#rqdata-API-index_weights_ex)）：按生效时段合计 `sum(weight_i×成分日收益_i)`，成分来自前复权 `close`。|指数用 [get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi) `frequency="1d", adjust_type="pre", fields=["close","total_turnover"]`，今日可追加快照；服务端补 0 不证明真实零收益。国债基准期限不同于 `f`。固定利率无市场成交额；组合权重是用户配置，不是持仓权重，成交额支持时加权；缺失处理可含前后填充，特殊债券成分可能不提供成交额。|
|`benchmark_series.daily[].total_turnover`<br>`benchmark_series.weekly[].total_turnover`<br>`benchmark_series.monthly[].total_turnover`|基准成交额|[RQData get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi) 返回的指数 `total_turnover`（日成交额）；周/月按日金额相加，不取均值，也不年化|是市场/基准成交额，不能用产品 `buy_amount`/`sell_amount` 替代，也不是成交量 volume；无支持数据时可不返回|
|`trading_dates`|[RQData get_trading_dates](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)|`get_trading_dates` 确定交易日序列、起点基准和沪深 T-20/T-1 窗口|数据选择日历与风险年化因子是两回事，自然日风险日频仍按 252|
|`previous_trading_date`|[RQData get_previous_trading_date](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_previous_trading_date)|`get_previous_trading_date` 确定交易日序列、起点基准和沪深 T-20/T-1 窗口|数据选择日历与风险年化因子是两回事，自然日风险日频仍按 252|
|`basis_returns`|基差变化收益贡献外部输入|[RQData futures.get_basis](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)(fields=['settle_basis','open','index'])；其 index 指定标的再取 [get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)(fields=['close','open'])；[instruments](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments).contract_multiplier|`settle_basis` 为结算基差；开盘基差=期货 open-指数 open。需要日期和合约对应关系，不能仅凭一张 positions 表复算，另有上文跨合约 shift 限制|
|`underlying_returns`|对应标的指数变化贡献外部输入|[RQData futures.get_basis](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)(fields=['settle_basis','open','index'])；其 index 指定标的再取 [get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)(fields=['close','open'])；[instruments](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments).contract_multiplier|`settle_basis` 为结算基差；开盘基差=期货 open-指数 open。需要日期和合约对应关系，不能仅凭一张 positions 表复算，另有上文跨合约 shift 限制|
|`buy_amount`|买入金额|由[头寸报表计算](fields/balances.md#balance-calculation)提供，继续依赖[头寸输入](fields/balances.md#position-inputs)|人工公允价、托管报告、初始化、历史修订不是 RQData；与查询区间内流水可能无法一一对应|
|`subscription_amount`|申购/投入金额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](custodian_events.md)、[unit_events](unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|
|`redemption_amount`|赎回/撤出金额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](custodian_events.md)、[unit_events](unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|
|`subscription_units`|申购份额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](custodian_events.md)、[unit_events](unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|
|`redemption_units`|赎回份额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](custodian_events.md)、[unit_events](unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|

外部输入表不是 API 返回字段列表；托管/份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询。


结果检查：区分 daily_risk、weekly_risk、monthly_risk 及所选 extra_indicators 的数据形状。空组或无有效交易日会失败；字段缺失或 null 时不能宣称该项风险为零，需核对日期、历史头寸报表与基准行情。

```python
result = rqamsh.analytics.indicators(resource='授权测试产品')
```

```console
rqamsh analytics indicators --resource "授权测试产品"
```

## series

读取产品或产品组指标时序。
- series：字段名→日期→值的序列，不是滚动 Sharpe；包含头寸报表类指标和申赎输入汇总，weekly_pnl 为嵌套树。

Python 签名：`rqamsh.analytics.series(resource: str, *, start_date: str | None=None, end_date: str | None=None, indicators: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略等于截止日期，并受资源起始日限制。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略为今日，且受到期日限制。|
|`indicators`|`list[str] \| None`|`None`|指标名数组，省略使用服务端默认集合。|

<a id="series-inputs"></a>

### 返回字段与计算公式

返回 `{指标名: {日期字符串: 数值}}`，下表 `{date}` 为实际日期键；`weekly_pnl` 例外为树形数组。以下是全部 19 个可选指标，不是滚动 Sharpe 或滚动风险序列。客户端原样透传 `indicators`；未识别指标的返回由服务端决定，不要依赖静默忽略。

|英文字段|中文名称|JSON 类型|计算公式|备注|
|---|---|---|---|---|
|`unit_net_value.{date}`|单位净值|number / null|同日头寸报表 [unit_net_value](fields/balances.md#unit-net-value)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`acc_unit_net_value.{date}`|累计单位净值|number / null|同日头寸报表 [acc_unit_net_value](fields/balances.md#acc-unit-net-value)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`adjusted_net_value.{date}`|复权净值|number / null|同日头寸报表 [adjusted_net_value](fields/balances.md#adjusted-net-value)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`total_assets.{date}`|总资产|number / null|同日头寸报表 [total_assets](fields/balances.md#total-assets)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`total_equity.{date}`|净资产|number / null|同日头寸报表 [total_equity](fields/balances.md#total-equity)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`daily_pnl.{date}`|当日盈亏|number / null|同日头寸报表 [daily_pnl](fields/balances.md#daily-pnl)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`equity_net_exposure.{date}`|权益净敞口|number / null|同日头寸报表 [equity_net_exposure](fields/balances.md#equity-net-exposure)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`cash.{date}`|现金|number / null|同日头寸报表 [cash](fields/balances.md#cash)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`net_cash_in.{date}`|净出入金|number / null|同日头寸报表 [net_cash_in](fields/balances.md#net-cash-in)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`buy_amount.{date}`|买入金额|number / null|`stock_buy_amount+bond_buy_amount+fund_buy_amount`；分项筛选和逐笔口径见[头寸报表 buy_amount](fields/balances.md#buy-amount)|重新合计三类流水分项；不采用估值表覆盖后的倒推金额，覆盖后可不同于同日头寸 `buy_amount`。|
|`sell_amount.{date}`|卖出金额|number / null|`stock_sell_amount+bond_sell_amount+fund_sell_amount`；分项筛选和逐笔口径见[头寸报表 sell_amount](fields/balances.md#sell-amount)|重新合计三类流水分项；不采用估值表覆盖后的倒推金额，覆盖后可不同于同日头寸 `sell_amount`。|
|`risk_exposure.{date}`|风险资产总敞口|number / null|[total_risk_market_value](fields/balances.md#total-risk-market-value) / [total_equity](fields/balances.md#total-equity)|各项取同日头寸报表；风险敞口是比例，不是风险市值；零分母遵循服务端 safe_div。|
|`net_risk_exposure.{date}`|风险资产净敞口|number / null|[net_risk_market_value](fields/balances.md#net-risk-market-value) / [total_equity](fields/balances.md#total-equity)|各项取同日头寸报表；风险敞口是比例，不是风险市值；零分母遵循服务端 safe_div。|
|`leverage_ratio.{date}`|资产杠杆倍数|number / null|[total_assets](fields/balances.md#total-assets) / [total_equity](fields/balances.md#total-equity)|各项取同日头寸报表；资产与净资产使用同一估值币种，零分母遵循服务端 safe_div。|
|`subscription_amount.{date}`|申购/投入金额|number / null|同日 `subscription_fund_received.amount + cash_in.settlement_amount + 托管划入 quantity×price-commission-tax-other_fees`|金额；[流水](fields/trades.md)、[份额事件来源](fields/balances.md#balance-inputs)。|
|`redemption_amount.{date}`|赎回/撤出金额|number / null|同日 `redemption_paid.amount + cash_out.settlement_amount + 托管划出 quantity×price-commission-tax-other_fees`|金额；[流水](fields/trades.md)、[份额事件来源](fields/balances.md#balance-inputs)。|
|`subscription_units.{date}`|申购份额|number / null|手工及自动份额事件 `subscription_units` 按事件日期求和|份；[流水](fields/trades.md)、[份额事件来源](fields/balances.md#balance-inputs)。|
|`redemption_units.{date}`|赎回份额|number / null|手工及自动份额事件 `redemption_units` 按事件日期求和|份；[流水](fields/trades.md)、[份额事件来源](fields/balances.md#balance-inputs)。|
|`weekly_pnl`|周盈亏树|array（object）|按年→月→周对头寸报表 [daily_pnl](fields/balances.md#daily-pnl) 求和|不采用收益率连乘|
|`weekly_pnl[].date`|年份|integer|年分组年份|子节点 date 分别为月份及该月内周序号|
|`weekly_pnl[].period_pnl`|年盈亏|number|该年内 daily_pnl 合计|仅请求区间内数据|
|`weekly_pnl[].children`|月份列表|array|年份内的月份分组|叶子周节点不含 children|
|`weekly_pnl[].children[].date`|月份|integer|月份 1–12|不是 YYYY-MM-DD|
|`weekly_pnl[].children[].period_pnl`|月盈亏|number|该月内 daily_pnl 合计|金额，不是收益率|
|`weekly_pnl[].children[].children`|周列表|array|该月内的周分组|按周日结束|
|`weekly_pnl[].children[].children[].date`|月内周序号|integer|月内按周日分组，从 1 编号|跨月周在各月内分组|
|`weekly_pnl[].children[].children[].period_pnl`|周盈亏|number|该月内该周 daily_pnl 合计|金额，不是收益率|

统计按流水 trading_date 和事件 date 汇总，不按股票除息日；金额分项在实际汇总中可补零，但最终缺日、权限不足或缺字段不能一律由客户端补零。份额事件的产生见[头寸报表输入](fields/balances.md#balance-inputs)，源记录字段见[流水字段](fields/trades.md)。产品组汇总成员记录，不是按投资权重缩放申赎金额。`weekly_pnl`（周盈亏）为周内 daily_pnl 金额相加，按年/月/周树输出，不是周收益率。

结果检查：检查每个请求指标的日期覆盖及 null 值，weekly_pnl 需按嵌套树解析。省略 start_date 可能只得到截止日数据；需要区间曲线时应明确传入两端日期。

```python
result = rqamsh.analytics.series(resource='授权测试产品')
```

```console
rqamsh analytics series --resource "授权测试产品"
```

## win_rate

读取产品或产品组区间胜率。
- win_rate：返回 daily_win_rate/weekly_win_rate/monthly_win_rate 与 returns_series；其累计净值比值算法不等同 get 中 win_rate 的净值差法，零收益算赢。

Python 签名：`rqamsh.analytics.win_rate(resource: str, *, start_date: str | None=None, end_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用资源起始日。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略为今日，且受到期日限制。|

<a id="win-rate-returns"></a>

### 返回字段与计算公式

返回：`daily_win_rate`、`weekly_win_rate`、`monthly_win_rate` 三棵胜率分组树，加 `returns_series` 日收益记录。

|英文字段|中文名称|JSON 类型|计算公式|备注|
|---|---|---|---|---|
|`daily_win_rate`|日频胜率分组|array（object）|按年→月→周汇总日收益样本的非负比例|不是周收益为正的比例|
|`weekly_win_rate`|周频胜率分组|array（object）|按年→月汇总周收益样本的非负比例|跨月周按实际周起始日归属年/月|
|`monthly_win_rate`|月频胜率分组|array（object）|各年份中月收益样本的非负比例|无月份 children|
|`daily_win_rate[].date`|年份|integer|年度分组键|—|
|`daily_win_rate[].children`|月份列表|array|按年内月份分组|—|
|`daily_win_rate[].children[].date`|月份|integer|月份 1–12|—|
|`daily_win_rate[].children[].children`|周列表|array|各周内日频胜率记录|—|
|`daily_win_rate[].children[].children[].date`|月内周序号|integer|所含周从 1 编号|—|
|`daily_win_rate[].children[].children[].start_date`|周起始样本日|string|周内第一有效日收益日期|—|
|`daily_win_rate[].children[].children[].end_date`|周结束样本日|string|周内最后有效日收益日期|—|
|`weekly_win_rate[].date`|年份|integer|年度分组键|—|
|`weekly_win_rate[].children`|月份列表|array|月内周频胜率记录|—|
|`weekly_win_rate[].children[].date`|月份|integer|周所属月份|—|
|`monthly_win_rate[].date`|年份|integer|年度分组键|—|
|`{win_node}.abs_win_rate`|绝对收益胜率|number / null|相应样本收益>=0的个数/样本数|{win_node} 为以上三棵树的年、月或周记录；样本频率由顶层块决定|
|`{win_node}.excess_win_rate`|算术超额胜率|number / null|相应样本收益减基准收益>=0的个数/样本数|日频用日收益差；周/月先各自累计，再相减；没有几何超额胜率字段|
|`returns_series`|日收益记录|array（object）|剔除产品日收益无效的日期后保留|基准缺失不代表零基准收益|
|`returns_series[].date`|样本日期|string|按产品日历对齐的日期索引 reset_index 后输出|索引沿用源头寸报表的 date 名称，不是 index|
|`returns_series[].daily_returns`|产品日收益|number|单产品有累计净值时 AccNAV[当日]/AccNAV[上一估值日]−1；否则取头寸报表 [daily_returns](fields/balances.md#daily-returns)|与 get 净值差法不同|
|`returns_series[].benchmark_returns`|基准日收益|number / null|资源已配置基准的同日收益 b_daily|[基准来源](#external-inputs)；该操作无 benchmark 参数|

单产品累计净值先后向补齐并按 AMS 精度舍入，起点取请求首日前一天累计净值，缺失或为零时取 1；日收益无效的行被剔除。无头寸摘要或无有效日收益时返回 `{}`。周/月周期收益：无累计净值的单产品取 `prod(1+日收益)−1`；其他分支取 `AccNAV[期末]/AccNAV[期初]−1`，产品组也依赖有效累计净值。周期基准收益为 `prod(1+b_daily)−1`。

两种公开胜率操作均将零收益算赢，但此处的累计净值比值法与 `indicators` 的净值差法不等价；不能因名称相同而拼接结果。无有效样本和基准缺失时不能宣称已完成统计。


结果检查：分别读取 daily_win_rate、weekly_win_rate、monthly_win_rate 和 returns_series；零收益算赢。与 get 的 win_rate 比较前先确认算法与样本区间相同，不能直接用同名字段断定结果不一致。

```python
result = rqamsh.analytics.win_rate(resource='授权测试产品')
```

```console
rqamsh analytics win-rate --resource "授权测试产品"
```

## long_short_returns

等待产品多空收益拆解任务结果；不支持产品组。
- long_short_returns：仅单产品中性多空收益拆解，会创建并等待任务；依赖股指期货基差和标的行情，资产类别不满足会报错。组不支持。

Python 签名：`rqamsh.analytics.long_short_returns(resource: str, *, start_date: str | None=None, end_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用产品起始日。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用最近结算日。|

<a id="long-short-returns-fields"></a>

### 返回字段与计算公式

返回：服务端任务终态 JSON（`status`、`progress`、`data`、`message`，见[任务终态 JSON](connection.md#task-result)），拆解结果在 `data` 内；失败或超时抛 HarnessError。下表路径相对任务结果数据，仅列成功任务的业务结果，任务状态不是收益指标。

用于股票多头与股指期货对冲的中性策略分析，仅支持产品。非类现金多头只允许股票、ETF、股指期货，货币基金不纳入；空头只允许股指期货。不满足品种要求时会报错，不能把该拆解套用到任意资产组合。

上一日权益为 0 的日期不纳入拆解。基差差额取合并表前一行结算基差之差，缺前值时用“期货开盘价－标的开盘价”；标的价格差取前一行收盘价之差，缺前值时用指数开盘价。公开日/周/月序列位于 `long_short_dismantle_returns_series`，另有 `monthly_long_short_dismantle_returns` 年/月/周树。无股指空头或基差数据时可返回空字典，无头寸报表时可为空值，均不表示零收益。

|英文字段|中文名称|JSON 类型|计算公式|备注|
|---|---|---|---|---|
|`long_short_dismantle_returns_series`|多空收益序列|object|daily/weekly/monthly → 日期记录数组|下表路径相对任务结果数据；若终态含 data 包装，应先取 data|
|`long_short_dismantle_returns_series.{frequency}[].date`|业务日期|string|日频日期或周期实际结束日期|{frequency}=daily/weekly/monthly|
|`monthly_long_short_dismantle_returns`|年/月/周拆解树|array（object）|年份→children 月份→children 周|不是另一套归因算法|
|`monthly_long_short_dismantle_returns[].date`|年份|string|YYYY|—|
|`monthly_long_short_dismantle_returns[].children`|月份列表|array|年内月份节点|—|
|`monthly_long_short_dismantle_returns[].children[].date`|月份|string|YYYY-MM|—|
|`monthly_long_short_dismantle_returns[].children[].end_date`|月末样本日|string|月内实际末日|—|
|`monthly_long_short_dismantle_returns[].children[].children`|周列表|array|月内周节点|—|
|`monthly_long_short_dismantle_returns[].children[].children[].date`|月内周序号|integer|按周所在月计算的序号|—|
|`monthly_long_short_dismantle_returns[].children[].children[].start_date`|周起始日|string|实际周样本起始日|—|
|`monthly_long_short_dismantle_returns[].children[].children[].end_date`|周结束日|string|实际周样本结束日|—|
|`{return_node}.basis_returns`|基差变化收益贡献|number / null|日频 `-sum(基差差额×期货空头数量×合约乘数)/当日净资产`<br>&emsp;周期为 `prod(1+日基差收益) - 1`|公开日/周/月序列返回此字段；{return_node} 为序列记录或年/月/周树节点|
|`{return_node}.long_excess_returns`|多头相对对应指数的超额贡献|number / null|日频 `equity_returns-underlying_returns`<br>&emsp;周期为两条收益各自连乘后的差|公开日/周/月序列返回此字段；{return_node} 为序列记录或年/月/周树节点|
|`{return_node}.portfolio_returns`|本拆解返回的产品收益|number / null|日频取头寸报表 [daily_returns](fields/balances.md#daily-returns)<br>&emsp;周期有累计净值时为 `AccNAV[期末] / AccNAV[期初] - 1`<br>&emsp;无净值时为增长倍数 `prod(1+r)`，不减 1|不能直接与 `analytics.indicators` 的区间收益比较；{return_node} 为序列记录或年/月/周树节点。|

日盈亏取 [positions[].daily_pnl](fields/balances.md#position)，数量取 [positions[].quantity](fields/balances.md#position)，多空与品种筛选取同仓 direction/asset_class；分母取当日 [total_equity](fields/balances.md#total-equity)，不取持仓成本或昨日权益。期货合约乘数及指数、[基差](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)来源见[外部输入](#external-inputs)。


**多合约特别限制：** 多合约情形下不能把这项输出表述为已经验证的逐合约基差归因；数量取当日头寸，也不是逐笔成交期间的时间加权数量。

完成条件：等待任务终态并检查拆解数据；失败或超时的 HarnessError 不是有效收益结果。保存任务诊断，先核对产品类型及股指期货基差、标的行情等依赖，不用重复提交代替查明缺失数据。

```python
result = rqamsh.analytics.long_short_returns(resource='授权测试产品')
```

```console
rqamsh analytics long-short-returns --resource "授权测试产品"
```

## download_series_file

导出指标时序工作簿，用于离线核对或存档。工作簿由服务端生成，含指标时序工作表，以及日、周、月度胜率工作表。

日期语义与 [`series`](#series) 一致：`start_date` 省略时使用 `end_date`，`end_date` 省略时为今日并受到期日限制。`download_series_file` 的 `indicators` 参数作用于时序部分，胜率工作表按服务端默认口径生成；表格排版不是公开 API，字段口径仍以[指标公式](#indicators-returns)为准。

Python 签名：`rqamsh.analytics.download_series_file(resource: str, output: str, *, start_date: str | None=None, end_date: str | None=None, indicators: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`output`|`str`|必填|本地输出文件路径，父目录须存在且目标文件不得已存在。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用 `end_date`。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略为今日，且受到期日限制。|
|`indicators`|`list[str] \| None`|`None`|指标名数组；省略使用服务端默认集合。|

返回：客户端下载元数据，含 `path`、`size`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](connection.md#download-result)|

交付检查：确认 output 是新文件并与导出前记录一致；工作簿不包含 `series` 之外的额外计算，导出成功不证明历史行情或头寸数据完整。目标文件已存在时客户端直接报错，不覆盖既有文件。

```python
result = rqamsh.analytics.download_series_file(
    resource='授权测试产品', output='indicators.xlsx',
    start_date='2026-01-01', end_date='2026-01-31', indicators=['adjusted_net_value'],
)
```

```console
rqamsh analytics download-series-file --resource "授权测试产品" --output "indicators.xlsx" --start-date "2026-01-01" --end-date "2026-01-31" --indicators '["adjusted_net_value"]'
```

## asset_weight

读取产品或产品组的资产权重视图；[行业分类](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)缓存构建期服务端会要求稍后重试。
- asset_weight：按区间与分类数组返回权重分布；分类数组为空或只有空白会被拒绝，避免退化成全量或空筛选。

Python 签名：`rqamsh.analytics.asset_weight(resource: str, *, start_date: str, end_date: str, classifiers: str | list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|
|`classifiers`|`str \| list[str]`|必填|非空分类或分类数组，数组按下发顺序序列化为逗号串；取值只能是 `asset_class`（资产属性）、`trading_asset_class`（[交易属性](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)）、`shenwan_level_1`/`shenwan_level_2`/`shenwan_level_3`、`zx_level_1`/`zx_level_2`，其他值会被服务端拒绝。|

返回：服务端权重视图，含 `classifier_weight` 与 `trading_asset_class_weight_series` 两部分。若行业分类缓存正在构建，服务端会以「正在初始化」提示并要求稍后重试（带重试间隔），Harness 按该提示重试到等待上限；此时不会有数值返回，不要把它当成空权重。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|权重视图对象|object|—|服务端直接返回的权重视图，恒含 `classifier_weight` 与 `trading_asset_class_weight_series` 两部分|恒返回；行业分类缓存构建中时不返回数值，服务端以「正在初始化」提示要求稍后重试|
|`classifier_weight`|按分类的权重|array（object）|—|每个请求分类一项，元素含 `classifier` 与 `weight`|由参数选择；只对请求中给出的分类返回条目，不会扩展成全量分类|
|`classifier_weight[].classifier`|分类名|string|—|该项对应的分类取值|随父级记录返回|
|`classifier_weight[].weight`|该分类下的分组权重行|array（object）|—|元素含 `name`、`quantity`、`quantity_pct`、`market_value`、`weight`、`children`|随父级记录返回；无持仓或该分类无可用取值时为空数组|
|`classifier_weight[].weight[].name`|分组名|string|—|该分类取值下的分组名；`classifiers` 含 `trading_asset_class` 时是[交易资产属性](fields/others.md#tradingassetclass) 的英文值|随父级记录返回|
|`classifier_weight[].weight[].quantity`|持仓数量合计|number|—|该分组持仓数量合计|随父级记录返回|
|`classifier_weight[].weight[].quantity_pct`|数量占比|number|小数|该分组数量占同一分类合计数量的比例|随父级记录返回|
|`classifier_weight[].weight[].market_value`|持仓市值合计|number|估值币种金额|该分组持仓市值合计|随父级记录返回|
|`classifier_weight[].weight[].weight`|市值权重|number|小数|该分组市值占同一报告市值合计的比例|随父级记录返回|
|`classifier_weight[].weight[].children`|分组内逐券明细|array（object）|—|元素含 `order_book_id`、`symbol`、`quantity`、`market_value`、`weight`|随父级记录返回；无明细时为空数组|
|`trading_asset_class_weight_series`|交易属性权重时序|object|—|恒含 `series_names` 与 `series` 两部分|恒返回|
|`trading_asset_class_weight_series.series_names`|序列中出现的交易属性名|array（string）|—|序列中出现过的[交易资产属性](fields/others.md#tradingassetclass) 英文值|恒返回；无数据时为 `[]`|
|`trading_asset_class_weight_series.series`|逐日权重记录|array（object）|—|每个产品日历日一条，元素含 `date` 与各交易属性名键，值为该属性当日市值合计/同日净资产|恒返回；无数据时为 `[]`；不是“日期 → 值”映射|
|`trading_asset_class_weight_series.series[].date`|业务日期|string|—|该条记录对应的产品日历日|随父级记录返回|
|`trading_asset_class_weight_series.series[].{交易属性名}`|该交易属性当日权重|number|小数|该交易属性当日市值合计 / 同日净资产；键名是[交易资产属性](fields/others.md#tradingassetclass) 的英文值|由数据决定；只对该日有持仓的属性出现，键名以 `series_names` 为准|

## equity_holdings

读取股票持仓分析。
- equity_holdings：给产品或产品组、区间、行业分类标准；`include_component_weight_view=True` 只对产品组有意义并附带成员权重，产品上传入会被拒绝。

Python 签名：`rqamsh.analytics.equity_holdings(resource: str, *, start_date: str, end_date: str, industry_classifier: str='sws', split_long_short: bool=False, include_component_weight_view: bool=False)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|
|`industry_classifier`|`str`|`sws`|行业分类标准。|
|`split_long_short`|`bool`|`False`|是否拆分多空。|
|`include_component_weight_view`|`bool`|`False`|成员权重视图；仅产品组可用。|

返回：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，分析结果在 `data` 内。表中的 `{指数名}` 是动态键（代入指数名，服务端按固定顺序给出），`[][序号]` 表示定长位置数组的第几个位置，二者都不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|股票持仓分析结果|object|—|本次股票持仓分析的结果对象，含下列键|`status` 为 `SUCCESS` 时返回；未拆分多空时为本表下列键，`split_long_short=True` 时改出本表末尾的 `long_*`／`short_*` 键|
|`data.snapshot_industry_distribution`|期末行业分布|array（object）|—|末个交易日各行业的持仓权重|恒返回；无股票持仓时为空数组 `[]`|
|`data.snapshot_industry_distribution[].industry`|行业名|string|—|该记录所属行业，取值随请求的[行业分类](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)标准|随父级记录返回；行业分类缓存构建中时服务端要求稍后重试，不会返回不完整分布|
|`data.snapshot_industry_distribution[].weight`|行业权重|number|小数|该行业末个交易日持仓市值合计 / 期末净资产|随父级记录返回；未拆分多空时含空头持仓|
|`data.period_industry_distribution`|区间行业盈亏|array（object）|—|区间内各行业的累计盈亏|恒返回；区间内无股票持仓时为空数组 `[]`|
|`data.period_industry_distribution[].industry`|行业名|string|—|取值口径同 `data.snapshot_industry_distribution[].industry`|随父级记录返回|
|`data.period_industry_distribution[].pnl`|行业区间盈亏|number|估值币种金额|该行业区间内各日盈亏之和|随父级记录返回；负值表示区间亏损|
|`data.top_ten_instruments`|期末前十大持仓|array（object）|—|末个交易日按持仓市值绝对值降序的前十只股票|恒返回；不足十只为实际只数，无股票持仓时为空数组 `[]`|
|`data.top_ten_instruments[].order_book_id`|标的代码|string|—|该持仓的股票代码|随父级记录返回|
|`data.top_ten_instruments[].direction`|持仓方向|string（枚举）|—|`long` 多头、`short` 空头|随父级记录返回|
|`data.top_ten_instruments[].symbol`|标的名称|string|—|该股票名称|随父级记录返回|
|`data.top_ten_instruments[].market_value`|期末持仓市值|number|估值币种金额|末个交易日该股持仓市值|随父级记录返回|
|`data.top_ten_instruments[].weight`|期末市值权重|number|小数|末个交易日持仓市值 / 期末净资产|随父级记录返回；分母是净资产，不是持仓市值合计|
|`data.top_ten_instruments[].pe_ttm`|滚动市盈率|number / null|倍|末个交易日的 TTM [市盈率](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_factor)|由数据决定；因子取不到或查询失败时为 `null`|
|`data.top_five_instruments`|区间盈利前五|array（object）|—|区间内累计盈亏最高的五只股票，按盈亏降序|恒返回；不足五只为实际只数，无股票持仓时为空数组 `[]`|
|`data.top_five_instruments[].order_book_id`|标的代码|string|—|该记录的股票代码|随父级记录返回|
|`data.top_five_instruments[].direction`|持仓方向|string（枚举）|—|`long` 多头、`short` 空头|随父级记录返回|
|`data.top_five_instruments[].symbol`|标的名称|string|—|该股票名称|随父级记录返回|
|`data.top_five_instruments[].pnl`|区间累计盈亏|number|估值币种金额|该股区间内各日盈亏之和|随父级记录返回|
|`data.bottom_five_instruments`|区间亏损前五|array（object）|—|区间内累计盈亏最低的五只股票，按盈亏升序|恒返回；区间内持仓不足五只时与 `data.top_five_instruments` 为同一批记录|
|`data.bottom_five_instruments[].order_book_id`|标的代码|string|—|该记录的股票代码|随父级记录返回|
|`data.bottom_five_instruments[].direction`|持仓方向|string（枚举）|—|`long` 多头、`short` 空头|随父级记录返回|
|`data.bottom_five_instruments[].symbol`|标的名称|string|—|该股票名称|随父级记录返回|
|`data.bottom_five_instruments[].pnl`|区间累计盈亏|number|估值币种金额|该股区间内各日盈亏之和|随父级记录返回；负值表示区间亏损|
|`data.quantity_series`|个股权重分位数序列|object|—|恒含 `long`；区间内出现过空头持仓时另含 `short`|恒返回；区间内无交易日时为空对象 `{}`；内容是权重不是数量；`split_long_short=True` 时同名保留|
|`data.quantity_series.long`|多头权重分位数序列|array（object）|—|每个有持仓的交易日一条|恒返回；无多头持仓记录时为空数组 `[]`；不是“日期 → 值”映射|
|`data.quantity_series.long[].date`|业务日期|string|—|该记录对应的交易日|随父级记录返回|
|`data.quantity_series.long[].median_50`|个股权重中位数|number|小数|当日多头个股个股市值的 50 分位|随父级记录返回；权重分母为当日净资产|
|`data.quantity_series.long[].median_75`|个股权重 75 分位|number|小数|同口径的 75 分位|随父级记录返回|
|`data.quantity_series.long[].median_100`|个股权重最大值|number|小数|100 分位即当日多头个股中最大权重|随父级记录返回|
|`data.quantity_series.short`|空头权重分位数序列|array（object）|—|结构同 `data.quantity_series.long`，口径为空头持仓|由数据决定；区间内任一日出现空头持仓时出现|
|`data.quantity_series.short[].date`|业务日期|string|—|该记录对应的交易日|随父级记录返回|
|`data.quantity_series.short[].median_50`|个股权重中位数|number|小数|当日空头个股个股市值的 50 分位|随父级记录返回；权重分母为当日净资产|
|`data.quantity_series.short[].median_75`|个股权重 75 分位|number|小数|同口径的 75 分位|随父级记录返回|
|`data.quantity_series.short[].median_100`|个股权重最大值|number|小数|100 分位即当日空头个股中最大权重|随父级记录返回|
|`data.stock_weight_distribution`|期末个股权重分布桶|array（object）|—|末个交易日个股（个股市值 / 净资产）的分桶直方图|恒返回；末个交易日无持仓时为空数组 `[]`|
|`data.stock_weight_distribution[].lower_bound`|桶下界|number|小数|该桶的权重下界|随父级记录返回；普通桶左闭右开、末桶两端都含；权重全相同时只有单桶且上下界相等|
|`data.stock_weight_distribution[].upper_bound`|桶上界|number|小数|该桶的权重上界|随父级记录返回|
|`data.stock_weight_distribution[].count`|桶内只数|integer|只|落在该桶的个股数|随父级记录返回|
|`data.stock_weight_distribution[].count_ratio`|桶内只数占比|number|小数|桶内只数 / 参与统计的个股数|随父级记录返回|
|`data.stock_weight_statistics`|期末个股权重统计|object|—|末个交易日个股权重的统计量|恒返回；末个交易日无持仓时为空对象 `{}`|
|`data.stock_weight_statistics.count`|参与统计只数|integer|只|参与统计的个股数|随父级记录返回|
|`data.stock_weight_statistics.min`|最小权重|number|小数|个股权重最小值|随父级记录返回|
|`data.stock_weight_statistics.percentile_25`|权重 25 分位|number|小数|线性插值分位数|随父级记录返回|
|`data.stock_weight_statistics.median`|权重中位数|number|小数|50 分位|随父级记录返回|
|`data.stock_weight_statistics.mean`|权重均值|number|小数|个股权重的算术平均|随父级记录返回|
|`data.stock_weight_statistics.percentile_75`|权重 75 分位|number|小数|线性插值分位数|随父级记录返回|
|`data.stock_weight_statistics.max`|最大权重|number|小数|个股权重最大值|随父级记录返回|
|`data.index_belong`|指数归属序列|array（object）|—|每个有持仓的交易日一条，含 `date` 与各指数名键|恒返回；区间内无股票持仓时为空数组 `[]`；未拆分多空时只按多头持仓计算|
|`data.index_belong[].date`|业务日期|string|—|该记录对应的交易日|随父级记录返回|
|`data.index_belong[].{指数名}`|该指数归属统计|array|—|定长四项 `[持仓市值, 市值权重, 持仓只数, 只数权重]`，取成分股在该日的股票持仓|由数据决定；该日缺该指数成分数据时为空数组 `[]`；指数名以服务端固定顺序给出|
|`data.index_belong[].{指数名}[][0]`|成分股持仓市值|number|估值币种金额|属于该指数的持仓市值合计|随父级记录返回|
|`data.index_belong[].{指数名}[][1]`|成分股市值权重|number|小数|成分股持仓市值 / 当日全部股票持仓市值|随父级记录返回；分母不可得时服务端写 `0`|
|`data.index_belong[].{指数名}[][2]`|成分股持仓只数|integer|只|属于该指数的持仓只数|随父级记录返回|
|`data.index_belong[].{指数名}[][3]`|成分股只数占比|number|小数|成分股只数 / 当日全部股票持仓只数|随父级记录返回|
|`data.market_capital_size`|期末市值档位分布|array（array）|—|按个股总市值档位统计的持仓分布，每个档位一条定长六项记录 `[档位阈值, 档位名, 持仓市值, 市值权重, 持仓只数, 只数占比]`|恒返回；无股票持仓或市值因子整体取不到时为空数组 `[]`|
|`data.market_capital_size[][0]`|档位阈值|integer|十亿元|该档位内最大总市值按 10 亿元取整（「1000亿及以上」为 `100`）|随父级记录返回；不是 0 起始的档位编号|
|`data.market_capital_size[][1]`|档位名|string|—|市值档位名称，如 `1000亿及以上`、`20亿以下`|随父级记录返回|
|`data.market_capital_size[][2]`|档位持仓市值|number|估值币种金额|该档位持仓市值合计|随父级记录返回|
|`data.market_capital_size[][3]`|档位市值权重|number|小数|该档位持仓市值 / 有市值因子的持仓市值合计|随父级记录返回；分母不含市值因子缺失的持仓|
|`data.market_capital_size[][4]`|档位持仓只数|integer|只|该档位持仓只数|随父级记录返回|
|`data.market_capital_size[][5]`|档位只数占比|number|小数|该档位只数 / 有市值因子的持仓只数|随父级记录返回|
|`data.board_belong`|期末板块分布|array（array）|—|按股票代码前缀划分板块后的持仓分布，每个板块一条定长五项记录 `[板块名, 持仓市值, 市值权重, 持仓只数, 只数占比]`|恒返回；无股票持仓时为空数组 `[]`|
|`data.board_belong[][0]`|板块名|string|—|主板、中小板、创业板、科创板、其他之一|随父级记录返回|
|`data.board_belong[][1]`|板块持仓市值|number|估值币种金额|该板块持仓市值合计|随父级记录返回|
|`data.board_belong[][2]`|板块市值权重|number|小数|该板块持仓市值 / 当日全部持仓市值|随父级记录返回|
|`data.board_belong[][3]`|板块持仓只数|integer|只|该板块持仓只数|随父级记录返回|
|`data.board_belong[][4]`|板块只数占比|number|小数|该板块只数 / 当日全部持仓只数|随父级记录返回|
|`data.product_weights`|成员产品权重|object|—|成员产品 ID 到该成员在组内权重的映射|由参数选择：仅产品组且 `include_component_weight_view=True` 时出现；末个交易日无可用成员权重时该键不出现|
|`data.product_weights.{产品ID}`|成员产品权重|number|小数|该成员在产品组内的权重（组持有份数 / 成员份额；权重组用配置权重）|随父级记录返回；不是成员市值占比|
|`data.long_market_capital_size`|多头期末市值档位分布|array（array）|—|元素结构同 `data.market_capital_size`，只统计多头持仓|由参数选择：`split_long_short=True`；空头侧为 `data.short_market_capital_size`|
|`data.short_market_capital_size`|空头期末市值档位分布|array（array）|—|元素结构同 `data.market_capital_size`，只统计空头持仓|由参数选择：`split_long_short=True`；多头侧为 `data.long_market_capital_size`|
|`data.long_board_belong`|多头期末板块分布|array（array）|—|元素结构同 `data.board_belong`，只统计多头持仓|由参数选择：`split_long_short=True`|
|`data.short_board_belong`|空头期末板块分布|array（array）|—|元素结构同 `data.board_belong`，只统计空头持仓|由参数选择：`split_long_short=True`|
|`data.long_snapshot_industry_distribution`|多头期末行业分布|array（object）|—|元素结构同 `data.snapshot_industry_distribution`，只统计多头持仓|由参数选择：`split_long_short=True`|
|`data.short_snapshot_industry_distribution`|空头期末行业分布|array（object）|—|元素结构同 `data.snapshot_industry_distribution`，只统计空头持仓|由参数选择：`split_long_short=True`|
|`data.long_top_ten_instruments`|多头期末前十大持仓|array（object）|—|元素结构同 `data.top_ten_instruments`，只取多头持仓|由参数选择：`split_long_short=True`|
|`data.short_top_ten_instruments`|空头期末前十大持仓|array（object）|—|元素结构同 `data.top_ten_instruments`，只取空头持仓|由参数选择：`split_long_short=True`|
|`data.long_top_five_instruments`|多头区间盈利前五|array（object）|—|元素结构同 `data.top_five_instruments`，只取多头持仓|由参数选择：`split_long_short=True`|
|`data.long_bottom_five_instruments`|多头区间亏损前五|array（object）|—|元素结构同 `data.bottom_five_instruments`，只取多头持仓|由参数选择：`split_long_short=True`|
|`data.short_top_five_instruments`|空头区间盈利前五|array（object）|—|元素结构同 `data.top_five_instruments`，只取空头持仓|由参数选择：`split_long_short=True`|
|`data.short_bottom_five_instruments`|空头区间亏损前五|array（object）|—|元素结构同 `data.bottom_five_instruments`，只取空头持仓|由参数选择：`split_long_short=True`|
|`data.long_period_industry_distribution`|多头区间行业盈亏|array（object）|—|元素结构同 `data.period_industry_distribution`，只统计多头持仓|由参数选择：`split_long_short=True`|
|`data.short_period_industry_distribution`|空头区间行业盈亏|array（object）|—|元素结构同 `data.period_industry_distribution`，只统计空头持仓|由参数选择：`split_long_short=True`|
|`data.long_stock_weight_distribution`|多头期末权重分布桶|array（object）|—|元素结构同 `data.stock_weight_distribution`，只统计多头持仓|由参数选择：`split_long_short=True`；该分支下没有 `data.stock_weight_distribution`|
|`data.short_stock_weight_distribution`|空头期末权重分布桶|array（object）|—|元素结构同 `data.stock_weight_distribution`，只统计空头持仓|由参数选择：`split_long_short=True`|
|`data.long_stock_weight_statistics`|多头期末权重统计|object|—|元素结构同 `data.stock_weight_statistics`，只统计多头持仓|由参数选择：`split_long_short=True`；该分支下没有 `data.stock_weight_statistics`|
|`data.short_stock_weight_statistics`|空头期末权重统计|object|—|元素结构同 `data.stock_weight_statistics`，只统计空头持仓|由参数选择：`split_long_short=True`|
|`data.long_index_belong_series`|多头指数归属序列|array（object）|—|元素结构同 `data.index_belong`，只按多头持仓计算|由参数选择：`split_long_short=True`；该分支下没有 `data.index_belong`|
|`data.short_index_belong_series`|空头指数归属序列|array（object）|—|元素结构同 `data.index_belong`，只按空头持仓计算|由参数选择：`split_long_short=True`；该分支下没有 `data.index_belong`|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：区分截面键与区间键，空数组表示该区间没有对应持仓，不是零收益；`split_long_short=True` 时汇总键换成 `long_*`／`short_*` 分支键（`index_belong` 换成 `long_index_belong_series`／`short_index_belong_series`），成员权重视图只在产品组的 `include_component_weight_view=True` 下出现。

## convertible_holdings

读取可转债持仓分析。
- convertible_holdings：给产品或产品组与区间，返回区间内的转债持仓分析结果。

Python 签名：`rqamsh.analytics.convertible_holdings(resource: str, *, start_date: str, end_date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|

返回：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，分析结果在 `data` 内。表中的 `{指数名}` 是动态键（代入指数名，服务端按固定顺序给出 12 个指数），`[][序号]` 表示定长位置数组的第几个位置，二者都不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|可转债持仓分析结果|object|—|含下列五个键；行业、板块与市值档位均按正股归类，市值按转债持仓市值统计|`status` 为 `SUCCESS` 时返回；区间内无转债持仓或相应数据不可得时对应键为空数组 `[]`|
|`data.snapshot_industry_distribution`|期末行业权重分布|array（object）|—|按正股所属行业汇总的转债市值权重|恒返回；无转债持仓时为空数组 `[]`|
|`data.snapshot_industry_distribution[].industry`|行业名称|string|—|正股在请求的行业分类标准下的行业名|随父级记录返回|
|`data.snapshot_industry_distribution[].weight`|行业市值权重|number|小数|该行业正股对应的转债持仓市值合计 / 该截面全部持仓市值|随父级记录返回；分母是同日头寸报表的整体持仓市值，不是净资产|
|`data.period_industry_distribution`|区间行业盈亏分布|array（object）|—|区间内逐日盈亏按正股行业汇总|由数据决定；区间内无可归类的转债持仓时为空数组 `[]`|
|`data.period_industry_distribution[].industry`|行业名称|string|—|取值口径同 `data.snapshot_industry_distribution[].industry`|随父级记录返回|
|`data.period_industry_distribution[].pnl`|行业区间盈亏|number|估值币种金额|区间内该行业转债持仓的逐日盈亏合计|随父级记录返回；区间累计口径，不区分已实现与浮动|
|`data.index_belong`|指数归属序列|array（object）|—|每个有头寸的交易日一条，元素含 `date` 与 12 个指数名键|恒返回；无交易日或无持仓截面时为空数组 `[]`|
|`data.index_belong[].date`|业务日期|string|—|该记录对应的头寸报表业务日|随父级记录返回|
|`data.index_belong[].{指数名}`|该指数归属统计|array|—|定长四项 `[持仓市值, 市值权重, 持仓只数, 只数权重]`；除中证转债指数按转债代码判定外，其余按正股是否属于[指数成分](https://www.ricequant.com/doc/rqdata/python/indices-mod#rqdata-API-index-components)判定|由数据决定；当日无该指数成分数据时为空数组 `[]`；有成分数据但无持仓时为 `[0,0,0,0]`|
|`data.index_belong[].{指数名}[][0]`|指数内持仓市值|number|估值币种金额|命中该指数成分的转债持仓市值合计|随父级记录返回|
|`data.index_belong[].{指数名}[][1]`|指数内市值权重|number|小数|该指数成分转债市值 / 当日全部转债持仓市值|随父级记录返回；分母为零时服务端写 `0`|
|`data.index_belong[].{指数名}[][2]`|指数内持仓只数|integer|只|命中该指数成分的转债条数|随父级记录返回|
|`data.index_belong[].{指数名}[][3]`|指数内只数权重|number|小数|命中只数 / 当日转债条数|随父级记录返回；分母为零时服务端写 `0`|
|`data.market_capital_size`|正股市值档位分布|array（array）|—|按正股总市值档位统计的转债持仓分布，每个档位一条定长六项记录 `[档位阈值, 档位名, 持仓市值, 市值权重, 持仓只数, 只数占比]`|由数据决定；正股[市值因子](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_factor)取不到时为空数组 `[]`|
|`data.market_capital_size[][0]`|档位阈值|integer|十亿元|该档位内最大正股总市值按 10 亿元取整（「1000亿及以上」为 `100`）|随父级记录返回|
|`data.market_capital_size[][1]`|档位名|string|—|市值档位名称，如 `1000亿及以上`、`20亿以下`|随父级记录返回|
|`data.market_capital_size[][2]`|档位内持仓市值|number|估值币种金额|该档位正股对应的转债持仓市值合计|随父级记录返回|
|`data.market_capital_size[][3]`|档位内市值权重|number|小数|该档位转债市值 / 参与统计的转债市值合计|随父级记录返回；分母只含有正股市值因子的转债|
|`data.market_capital_size[][4]`|档位内持仓只数|integer|只|落在该档位的转债条数|随父级记录返回|
|`data.market_capital_size[][5]`|档位内只数占比|number|小数|该档位条数 / 参与统计的转债条数|随父级记录返回|
|`data.board_belong`|正股板块分布|array（array）|—|按正股代码前缀划分板块后的转债持仓分布，每个板块一条定长五项记录 `[板块名, 持仓市值, 市值权重, 持仓只数, 只数占比]`|恒返回；无转债持仓时为空数组 `[]`|
|`data.board_belong[][0]`|板块名|string|—|主板、中小板、创业板、科创板、其他之一|随父级记录返回|
|`data.board_belong[][1]`|板块内持仓市值|number|估值币种金额|该板块正股对应的转债持仓市值合计|随父级记录返回|
|`data.board_belong[][2]`|板块内市值权重|number|小数|该板块转债市值 / 该截面全部转债持仓市值|随父级记录返回|
|`data.board_belong[][3]`|板块内持仓只数|integer|只|该板块转债条数|随父级记录返回|
|`data.board_belong[][4]`|板块内只数占比|number|小数|该板块条数 / 该截面转债条数|随父级记录返回|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：转债口径按正股行业与板块归类；空数组表示区间内没有该资产类别持仓，不是零仓位风险。逐券明细用 [`convertible_positions`](#convertible_positions)。

## convertible_positions

读取可转债持仓明细。
- convertible_positions：与 `convertible_holdings` 同一资产类别，但返回逐券明细口径，用于核对转股、溢价与持仓数量。

Python 签名：`rqamsh.analytics.convertible_positions(resource: str, *, start_date: str, end_date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|

返回：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，分析结果在 `data` 内。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|可转债持仓明细结果|object|—|含 `date`（服务端实际采用的截止日）与 `positions`（逐券明细数组）两个键|`status` 为 `SUCCESS` 时返回；无转债持仓时 `positions` 为 `[]`|
|`data.date`|实际截止日|string|—|服务端实际采用的截面日：先取最近结算日与请求 `end_date` 的较早者，该日不是交易日时再回退到最近交易日，输出为 `YYYY-MM-DD`；同一天也用于取截面指标|恒返回；不等于请求 `end_date` 时说明被结算日或交易日历截断|
|`data.positions`|逐券明细|array（object）|—|每只可转债一条，字段按下列各行给出|恒返回；无转债持仓时为空数组 `[]`；行情或指标不可得的列为 `null`，不是 `0`|
|`data.positions[].order_book_id`|可转债代码|string|—|该条明细的可转债合约代码|随父级记录返回|
|`data.positions[].symbol`|可转债简称|string|—|该可转债的显示名称，取自同日头寸报表|随父级记录返回|
|`data.positions[].market_value`|持仓市值|number|估值币种金额|该可转债在同日头寸报表上的持仓市值|随父级记录返回；可转债只可能多头，取值为正|
|`data.positions[].weight`|市值权重|number / null|小数|该转债持仓市值 / 同日净资产|随父级记录返回；净资产为零时不是有效权重|
|`data.positions[].stock_order_book_id`|正股代码|string / null|—|该可转债对应正股的合约代码|由数据决定：取不到该转债合约信息时为 `null`|
|`data.positions[].stock_symbol`|正股简称|string / null|—|正股的显示名称|由数据决定：取不到正股合约信息时为 `null`|
|`data.positions[].stock_industry_name`|正股所属行业|string / null|—|正股在请求的[行业分类](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)标准下的行业名，查不到归属时为「其他」|由数据决定：无正股代码时为 `null`|
|`data.positions[].maturity_date`|转债到期日|string / null|—|该可转债合约的到期日，输出为 `YYYY-MM-DD`|由数据决定：取不到该转债合约信息时为 `null`；按日期字符串给出，不是数值时间戳|
|`data.positions[].convertible_price`|转债收盘价|number / null|元|取价日该转债的前复权收盘价（面值 100 元口径）|由数据决定：取不到行情时为 `null`；取价日可能不等于 `data.date`|
|`data.positions[].stock_price`|正股收盘价|number / null|元|同一取价日正股的前复权收盘价|由数据决定：取不到行情时为 `null`|
|`data.positions[].conversion_price`|转股价|number / null|元|服务端由[转股系数](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-instruments)换算：`100 ÷ 转股系数`，四舍五入到 2 位|由数据决定：截面指标不可得时为 `null`；不是上游直接返回的字段|
|`data.positions[].conversion_value`|转股价值|number / null|元|转债按转股价折算成正股后的价值|由数据决定：截面指标不可得时为 `null`|
|`data.positions[].conversion_premium`|转股溢价率|number / null|小数|转债价格相对[转股价值](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_indicators)的溢价率，`0.01 = 1%`|由数据决定：不可得时为 `null`；`0` 表示平价，不等于缺失|
|`data.positions[].remaining_size`|剩余规模|number / null|元|查询日尚未转股、赎回的债券余额|由数据决定：不可得时为 `null`|
|`data.positions[].call_trigger_price`|赎回触发价|number / null|元|正股价格达到该价位即触及强制赎回条款（面值 100 元口径）|由数据决定：不可得时为 `null`|
|`data.positions[].put_trigger_price`|回售触发价|number / null|元|正股价格跌破该价位即触及回售条款（面值 100 元口径）|由数据决定：不可得时为 `null`|
|`data.positions[].call_qualified_days`|赎回已满足天数|number / null|天|截至查询日强赎条款已满足的天数|由数据决定：不可得时为 `null`；`0` 表示尚未满足，不等于缺失|
|`data.positions[].put_qualified_days`|回售已满足天数|number / null|天|截至查询日回售条款已满足的天数|由数据决定：不可得时为 `null`；`0` 表示尚未满足，不等于缺失|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：`weight` 的分母是同日净资产；`conversion_price` 由转股比例换算，`conversion_value`、`conversion_premium` 取查询日截面，不可得时为空值而不是 0。

## futures_holdings

读取期货持仓分析。
- futures_holdings：额外给出平均总成交额与成交额排名参数，用于期货交易活跃度分析。

Python 签名：`rqamsh.analytics.futures_holdings(resource: str, *, start_date: str, end_date: str, average_total_turnover: int=2, total_turnover_ranking: int=3)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|
|`average_total_turnover`|`int`|`2`|平均总成交额口径参数，服务端按「十亿」量级换算；Harness 不换算单位。|
|`total_turnover_ranking`|`int`|`3`|成交额排名口径参数。|

返回：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，分析结果在 `data` 内。表中的 `{品种代码}` 是动态键（服务端固定给出 `IF`、`IC`、`IM`），不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|期货持仓分析结果|object|—|含下列键|`status` 为 `SUCCESS` 时返回；无数据的键为空数组或空对象|
|`data.industry_distribution`|行业多空仓位分布|array（object）|—|期末截面上按合约行业分组的持仓市值，每个有持仓的行业一条|恒返回；期末无期货持仓时为空数组 `[]`；是期末截面，不是区间序列|
|`data.industry_distribution[].industry_name`|行业名称|string|—|该记录对应的行业分组名，取自期货合约的行业信息|随父级记录返回；缺行业信息时以占位名归组|
|`data.industry_distribution[].net`|净头寸|number|估值币种金额|该行业全部持仓市值合计，多空不拆分|随父级记录返回|
|`data.industry_distribution[].long`|多头市值|number|估值币种金额|该行业多头持仓市值合计|随父级记录返回；无多头持仓时为 `0`|
|`data.industry_distribution[].short`|空头市值|number|估值币种金额|该行业空头持仓市值合计|随父级记录返回；无空头持仓时为 `0`；按带符号市值计入，通常为负|
|`data.commodity_distribution`|品种多空仓位分布|array（object）|—|期末截面上按品种分组的持仓市值，每个有持仓的品种一条|恒返回；期末无期货持仓时为空数组 `[]`；分组含股指、国债与商品期货|
|`data.commodity_distribution[].underlying_symbol`|品种名称|string|—|该记录对应的期货品种名|随父级记录返回；股指期货与 10 年期国债为中文名，其余为合约代码去掉数字|
|`data.commodity_distribution[].net`|净头寸|number|估值币种金额|该品种全部持仓市值合计，多空不拆分|随父级记录返回|
|`data.commodity_distribution[].long`|多头市值|number|估值币种金额|该品种多头持仓市值合计|随父级记录返回；无多头持仓时为 `0`|
|`data.commodity_distribution[].short`|空头市值|number|估值币种金额|该品种空头持仓市值合计|随父级记录返回；无空头持仓时为 `0`；按带符号市值计入，通常为负|
|`data.industry_weight`|行业权重逐日序列|array（object）|—|每个有期货持仓的产品日历日一条，元素含 `date` 与 `items`|恒返回；区间内无期货持仓时为空数组 `[]`；不是“日期 → 值”映射|
|`data.industry_weight[].date`|业务日期|string|—|该条记录对应的产品日历日|随父级记录返回|
|`data.industry_weight[].items`|当日行业权重明细|array（object）|—|元素含 `industry_name` 与 `weight`|随父级记录返回；该日无持仓的行业不出现，不补零|
|`data.industry_weight[].items[].industry_name`|行业名称|string|—|该明细项对应的行业分组名|随父级记录返回|
|`data.industry_weight[].items[].weight`|行业权重|number|小数|该行业当日持仓市值合计 / 同日净资产|随父级记录返回；按带符号净市值计算，可为负|
|`data.commodity_weight`|品种权重逐日序列|array（object）|—|每个有期货持仓的产品日历日一条，元素含 `date` 与 `items`|恒返回；区间内无期货持仓时为空数组 `[]`；不是“日期 → 值”映射|
|`data.commodity_weight[].date`|业务日期|string|—|该条记录对应的产品日历日|随父级记录返回|
|`data.commodity_weight[].items`|当日品种权重明细|array（object）|—|元素含 `underlying_symbol` 与 `weight`|随父级记录返回；该日无持仓的品种不出现，不补零|
|`data.commodity_weight[].items[].underlying_symbol`|品种名称|string|—|该明细项对应的期货品种名|随父级记录返回；取值口径同 `data.commodity_distribution[].underlying_symbol`|
|`data.commodity_weight[].items[].weight`|品种权重|number|小数|该品种当日持仓市值合计 / 同日净资产|随父级记录返回；按带符号净市值计算，可为负|
|`data.industry_pnls`|行业区间盈亏|array（object）|—|区间内按行业汇总的期货持仓盈亏|恒返回；区间内无期货持仓时为空数组 `[]`|
|`data.industry_pnls[].industry_name`|行业名称|string|—|该记录对应的行业分组名|随父级记录返回|
|`data.industry_pnls[].total_pnl`|区间总盈亏|number|估值币种金额|区间内该行业每日持仓盈亏之和|随父级记录返回|
|`data.industry_pnls[].basis_pnl`|区间基差盈亏|number|估值币种金额|区间内该行业股指期货的[基差](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)收益合计，逐日为基差变化 × 合约乘数 × 持仓数量 × 方向|随父级记录返回；只对股指期货计基差收益，其余品种按 `0` 计入|
|`data.industry_pnls[].remain_pnl`|区间标的盈亏|number|估值币种金额|`total_pnl − basis_pnl`，剔除基差贡献后的盈亏|随父级记录返回|
|`data.commodity_pnls`|品种区间盈亏|array（object）|—|区间内按品种汇总的期货持仓盈亏|恒返回；区间内无期货持仓时为空数组 `[]`|
|`data.commodity_pnls[].underlying_symbol`|品种名称|string|—|该记录对应的期货品种名|随父级记录返回；取值口径同 `data.commodity_distribution[].underlying_symbol`|
|`data.commodity_pnls[].total_pnl`|区间总盈亏|number|估值币种金额|区间内该品种每日持仓盈亏之和|随父级记录返回|
|`data.commodity_pnls[].basis_pnl`|区间基差盈亏|number|估值币种金额|口径同 `data.industry_pnls[].basis_pnl`，按品种汇总|随父级记录返回；非股指期货品种为 `0`|
|`data.commodity_pnls[].remain_pnl`|区间标的盈亏|number|估值币种金额|`total_pnl − basis_pnl`|随父级记录返回|
|`data.inactive_variety`|不活跃品种持仓|array（object）|—|期末截面上被判为不活跃品种的持仓|恒返回；无满足判定的品种时为空数组 `[]`|
|`data.inactive_variety[].industry_name`|行业名称|string|—|该记录对应的行业分组名|随父级记录返回|
|`data.inactive_variety[].market_value`|持仓市值|number|估值币种金额|该行业下全部不活跃品种的期末持仓市值合计|随父级记录返回|
|`data.inactive_variety[].items`|不活跃品种明细|array（object）|—|元素含 `underlying_symbol` 与 `market_value`|随父级记录返回|
|`data.inactive_variety[].items[].underlying_symbol`|品种名称|string|—|该不活跃品种的品种名|随父级记录返回；取值口径同 `data.commodity_distribution[].underlying_symbol`|
|`data.inactive_variety[].items[].market_value`|持仓市值|number|估值币种金额|该不活跃品种的期末持仓市值合计|随父级记录返回|
|`data.inactive_contract`|不活跃合约持仓|array（object）|—|活跃品种内成交额排名靠后[合约](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-all_instruments)的期末持仓|恒返回；无满足判定的合约时为空数组 `[]`|
|`data.inactive_contract[].industry_name`|行业名称|string|—|该记录对应的行业分组名|随父级记录返回|
|`data.inactive_contract[].market_value`|持仓市值|number|估值币种金额|该行业下全部不活跃合约的期末持仓市值合计|随父级记录返回|
|`data.inactive_contract[].items`|不活跃合约明细|array（object）|—|元素含 `underlying_symbol`、`symbol`、`order_book_id` 与 `market_value`|随父级记录返回|
|`data.inactive_contract[].items[].underlying_symbol`|品种名称|string|—|该不活跃合约所属品种|随父级记录返回；取值口径同 `data.commodity_distribution[].underlying_symbol`|
|`data.inactive_contract[].items[].symbol`|合约名称|string|—|该不活跃合约的名称|随父级记录返回|
|`data.inactive_contract[].items[].order_book_id`|合约代码|string|—|该不活跃合约的合约代码|随父级记录返回|
|`data.inactive_contract[].items[].market_value`|持仓市值|number|估值币种金额|该不活跃合约的期末持仓市值|随父级记录返回|
|`data.dominant_basis_series`|主力合约年化基差序列|object|—|按品种代码给出[主力合约](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_dominant)的年化基差序列|由数据决定：策略分类为市场中性且基差数据可得时返回，否则为空对象 `{}`|
|`data.dominant_basis_series.{品种代码}`|该品种主力合约基差序列|array（object）|—|元素含 `date` 与 `annual_basis_rate`|随父级对象返回；该品种无主力合约数据时为空数组 `[]`|
|`data.dominant_basis_series.{品种代码}[].date`|业务日期|string|—|该条记录对应的交易日|随父级记录返回|
|`data.dominant_basis_series.{品种代码}[].annual_basis_rate`|年化基差率|number|小数|该日主力合约的年化基差率，`0.01` 表示 1%|随父级记录返回；不是百分数文本|
|`data.start_date`|区间起始日|string|—|本次分析请求的起始日，输出为 `YYYY-MM-DD`|恒返回；等于请求参数，服务端内部日期截断只影响计算|
|`data.end_date`|区间截止日|string|—|本次分析请求的截止日，输出为 `YYYY-MM-DD`|恒返回；等于请求参数，服务端内部日期截断只影响计算|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：`average_total_turnover` 与 `total_turnover_ranking` 只影响不活跃品种与合约的判定，不改变盈亏口径；年化基差为比值小数，不是百分比文本。

## option_holdings

读取期权持仓分析。
- option_holdings：给产品或产品组与区间，返回区间内的期权持仓分析结果。

Python 签名：`rqamsh.analytics.option_holdings(resource: str, *, start_date: str, end_date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|

返回：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，分析结果在 `data` 内。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|期权持仓分析结果|object|—|含 `greeks`、`series_greeks`、`underlying_series_greeks` 三个键，三键恒同时出现|`status` 为 `SUCCESS` 时返回；无期权持仓或希腊字母不可得时三键分别为 `{}`、`[]`、`[]`，键本身仍存在|
|`data.greeks`|截止日希腊字母截面|object|—|含 `date` 与 `data` 两个键，`data` 按标的品种分组|恒返回；区间内无期权持仓或服务端取不到希腊字母时为空对象 `{}`，此时不含 `date` 与 `data` 键|
|`data.greeks.date`|希腊字母截面截止日|string|—|服务端实际采用的截面日：请求 `end_date` 先与最近结算日取较早者，再截断到该日或之前的交易日，输出为 `YYYY-MM-DD`|随父级返回；即使 `data` 为空数组也返回|
|`data.greeks.data`|按标的品种的截止日希腊字母|array（object）|—|每个在截止日仍有[希腊字母](https://www.ricequant.com/doc/rqdata/python/options-mod#rqdata-API-options-get_greeks)的标的品种一条|随父级返回；截止日无可用截面时为空数组 `[]`|
|`data.greeks.data[].group`|标的品种|string|—|该组对应的期权标的品种名，取标的合约名称去掉尾部数字|随父级记录返回；合约信息不可得时回退为固定兜底文案|
|`data.greeks.data[].delta`|Delta 合计|number|标的计价币种金额|该品种逐合约 `delta` 之和|随父级记录返回；已按持仓数量与合约乘数折算为市值口径|
|`data.greeks.data[].gamma`|Gamma 合计|number|标的计价币种金额|该品种逐合约 `gamma` 之和|随父级记录返回；已按持仓数量与合约乘数折算为市值口径|
|`data.greeks.data[].vega`|Vega 合计|number|标的计价币种金额|该品种逐合约 `vega` 之和|随父级记录返回；已按持仓数量与合约乘数折算为市值口径|
|`data.greeks.data[].theta`|Theta 合计|number|标的计价币种金额／日|该品种逐合约 `theta` 之和|随父级记录返回；已折算为日度市值口径|
|`data.greeks.data[].rho`|Rho 合计|number|标的计价币种金额|该品种逐合约 `rho` 之和|随父级记录返回；已按持仓数量与合约乘数折算为市值口径|
|`data.greeks.data[].detail`|逐合约希腊字母明细|array（object）|—|该品种在截止日的逐合约记录|随父级记录返回；多空对冲后数量为 0 的仓与无持仓的合约不返回|
|`data.greeks.data[].detail[].delta`|Delta|number|标的计价币种金额|原始 delta × 持仓净数量 × [合约乘数](https://www.ricequant.com/doc/rqdata/python/options-mod#rqdata-API-options-get-contract_property) × 标的收盘价|随父级记录返回；标的收盘价取不到时按 `0` 返回|
|`data.greeks.data[].detail[].gamma`|Gamma|number|标的计价币种金额|原始 gamma × 持仓净数量 × 合约乘数 × 标的收盘价² ÷ 100|随父级记录返回；标的收盘价取不到时按 `0` 返回|
|`data.greeks.data[].detail[].vega`|Vega|number|标的计价币种金额|原始 vega ÷ 100 × 持仓净数量 × 合约乘数|随父级记录返回|
|`data.greeks.data[].detail[].theta`|Theta|number|标的计价币种金额／日|原始 theta ÷ 365 × 持仓净数量 × 合约乘数|随父级记录返回；按日度口径折算|
|`data.greeks.data[].detail[].rho`|Rho|number|标的计价币种金额|原始 rho ÷ 100 × 持仓净数量 × 合约乘数|随父级记录返回|
|`data.greeks.data[].detail[].quantity`|持仓净数量|number|合约单位（按品种）|该合约截止日的持仓数量，多头为正、空头为负|随父级记录返回；JSON 为浮点数，不保证是整数值|
|`data.greeks.data[].detail[].last_price`|合约收盘价|number / null|合约报价单位|该期权合约截止日的收盘价|由数据决定：截止日无该合约行情时为空值；是行情口径，不是 AMS 估值价格|
|`data.greeks.data[].detail[].symbol`|合约名称|string|—|该期权合约名称|随父级记录返回；[合约信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)不可得时为固定兜底文案|
|`data.greeks.data[].detail[].order_book_id`|合约代码|string|—|该期权合约代码|随父级记录返回|
|`data.series_greeks`|按合约的区间希腊字母时序|array（object）|—|区间内每个「交易日 × 期权合约」一条|恒返回；无数据时为空数组 `[]`|
|`data.series_greeks[].date`|业务日期|string|—|该条记录对应的交易日|随父级记录返回；非交易日与无持仓日不返回|
|`data.series_greeks[].group`|期权合约名称|string|—|该条记录对应的期权合约名称，每个合约一个分组|随父级记录返回；合约退市或无持仓后的日期不返回；**不是**标的品种|
|`data.series_greeks[].delta`|Delta|number|标的计价币种金额|该合约当日全部持仓的折算后 `delta` 合计|随父级记录返回；口径同 `data.greeks.data[].detail[].delta`|
|`data.series_greeks[].gamma`|Gamma|number|标的计价币种金额|该合约当日全部持仓的折算后 `gamma` 合计|随父级记录返回；口径同上|
|`data.series_greeks[].vega`|Vega|number|标的计价币种金额|该合约当日全部持仓的折算后 `vega` 合计|随父级记录返回；口径同上|
|`data.series_greeks[].theta`|Theta|number|标的计价币种金额／日|该合约当日全部持仓的折算后 `theta` 合计|随父级记录返回；口径同上|
|`data.series_greeks[].rho`|Rho|number|标的计价币种金额|该合约当日全部持仓的折算后 `rho` 合计|随父级记录返回；口径同上|
|`data.underlying_series_greeks`|按标的品种的区间希腊字母时序|array（object）|—|区间内每个「交易日 × 标的品种」一条|恒返回；无数据时为空数组 `[]`|
|`data.underlying_series_greeks[].date`|业务日期|string|—|该条记录对应的交易日|随父级记录返回；非交易日与无持仓日不返回|
|`data.underlying_series_greeks[].underlying_symbol`|标的品种|string|—|该条记录对应的标的品种名，取标的合约名称去掉尾部数字|随父级记录返回；与 `data.greeks.data[].group` 同源|
|`data.underlying_series_greeks[].delta`|Delta|number|标的计价币种金额|该品种当日各合约折算后 `delta` 的合计|随父级记录返回|
|`data.underlying_series_greeks[].gamma`|Gamma|number|标的计价币种金额|该品种当日各合约折算后 `gamma` 的合计|随父级记录返回|
|`data.underlying_series_greeks[].vega`|Vega|number|标的计价币种金额|该品种当日各合约折算后 `vega` 的合计|随父级记录返回|
|`data.underlying_series_greeks[].theta`|Theta|number|标的计价币种金额／日|该品种当日各合约折算后 `theta` 的合计|随父级记录返回|
|`data.underlying_series_greeks[].rho`|Rho|number|标的计价币种金额|该品种当日各合约折算后 `rho` 的合计|随父级记录返回|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：希腊字母已按持仓数量与合约乘数折算为市值口径（`delta`、`gamma` 另乘标的价格，`theta` 除以 365 折算为日、`vega` 与 `rho` 除以 100），不是单份合约的原始值；非交易日与已无持仓的日期不返回记录。

## holdings_summary_file

导出持仓分析汇总工作簿（生成文件并落盘）。
- holdings_summary_file：模板与区间都是服务端硬要求，缺省会直接失败，因此三者在签名中均为必填。

Python 签名：`rqamsh.analytics.holdings_summary_file(resource: str, output: str, template: str, *, start_date: str, end_date: str, benchmark: str | None=None, industry_classifier: str | None=None, split_long_short: bool | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`output`|`str`|必填|输出文件路径；父目录须存在且目标文件不得已存在。|
|`template`|`str`|必填|`equity`、`convertible`、`futures`、`option` 之一；其他取值被本地拒绝。|
|`start_date`|`str`|必填|YYYY-MM-DD；服务端该端点没有默认区间。|
|`end_date`|`str`|必填|YYYY-MM-DD，不能晚于今天。|
|`benchmark`|`str \| None`|`None`|基准纯 ID，如 `000300.XSHG`；省略时服务端使用 `000300.XSHG`。|
|`industry_classifier`|`str \| None`|`None`|行业分类标准。|
|`split_long_short`|`bool \| None`|`None`|是否拆分多空。|

返回：客户端下载元数据，含 `path`、`size`；目标文件已存在时抛错，不覆盖既有文件。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；任务终态后才写入；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](connection.md#download-result)|

交付检查：先确认 `template` 与区间对应的查询结果，再核对导出的新文件；落盘成功不证明区间内行情或头寸数据完整。

## create_attribution

提交区间业绩归因计算，直接返回归因 ID。
- create_attribution：基准必填且格式为「类型,代码」；模板与「仅收益拆解」至少给一个，都不给时无法确定分解方式。

Python 签名：`rqamsh.analytics.create_attribution(resource: str, *, start_date: str, end_date: str, benchmark: str, template: str | None=None, industry_standard: str | None=None, drilldown: bool=False, only_returns_decomposition: bool=False, need_market_value_weights: bool=False)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|
|`benchmark`|`str`|必填|「类型,代码」格式的基准。|
|`template`|`str \| None`|`None`|归因模板，取 `equity/brinson`、`equity/factor`、`equity/factor_v2` 之一；服务端按枚举校验，其他值直接失败。|
|`industry_standard`|`str \| None`|`None`|行业分类标准，取 `sws`、`sws_second`、`citics`、`citics_second` 之一；省略时由服务端按模板决定。|
|`drilldown`|`bool`|`False`|是否对资产单元穿透。|
|`only_returns_decomposition`|`bool`|`False`|是否只做收益拆解。|
|`need_market_value_weights`|`bool`|`False`|是否同时返回市值权重。|

返回：服务端新建的归因记录对象，只含归因 ID；提交成功只代表任务已排队，必须用 [`attribution`](#attribution) 轮询到终态。记录里服务端会把 `benchmark` 归一化为 `{"type": ..., "id": ...}`，并在未指定时填入默认行业分类标准。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|新建归因记录|object|—|服务端直接返回的归因记录，只含归因 ID，不含归因结果|恒返回；`benchmark` 归一化与默认行业分类标准体现在记录的读取结果中，见 `attribution` 的返回表|
|`id`|归因 ID|string|字符串 ID|新建归因记录的 ID，供 [`attribution`](#attribution)、[`export_attribution`](#export_attribution)、[`delete_attribution`](#delete_attribution) 使用|恒返回；`attribution` 查询结果里同一值落在 `_id`|

结果检查：`id` 只是任务标识；区间内没有产品交易日历时服务端直接拒绝提交，不要用重放创建来换取结果。

## attribution

按归因 ID 查询归因结果。
- attribution：运行中的归因会持续返回进行中状态，Harness 在同一查询路由重复读取，不会重新提交计算。

Python 签名：`rqamsh.analytics.attribution(resource: str, attribution_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`attribution_id`|`str`|必填|`create_attribution` 返回的归因 ID。|

返回：任务成功后是服务端原样的归因记录对象，运行中则是任务状态对象（`status`、`progress`、`message`，见[任务终态 JSON](connection.md#task-result)）；失败终态会抛出错误并保留服务端诊断。归因结果体的形状随参数变化：`only_returns_decomposition=True` 时 `result` 本身就是收益拆解数组，否则是按模板组织的对象（`result[].factor` 里的 `{资产类别}` 是资产类别中文名的占位，不是 JSON 键）；它由归因引擎产出、服务端原样返回（只不含导出附件与 Brinson 日度序列），下表只列服务端与导出实际读写的键，引擎版本变化可能带来其它键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|归因记录对象|object|—|服务端直接返回的归因记录；任务成功时才带归因结果|恒返回；运行中返回任务状态对象，不含归因记录字段|
|`_id`|归因 ID|string|字符串 ID|与 [`create_attribution`](#create_attribution) 返回的 `id` 相同|随归因记录返回|
|`product_or_group_id`|产品或产品组 ID|string|字符串 ID|本次归因的对象|随归因记录返回|
|`product_or_group_name`|对象名称|string|—|本次归因的产品或产品组名称|随归因记录返回|
|`user_id`|提交人 ID|integer|—|提交该归因任务的用户|随归因记录返回|
|`start_date`|区间起始日|string|—|提交时的分析起始日|随归因记录返回|
|`end_date`|区间截止日|string|—|提交时的分析截止日|随归因记录返回|
|`benchmark`|归一化基准|object|—|由提交的「类型,代码」拆分成的对象，含 `type` 与 `id`|随归因记录返回|
|`benchmark.type`|基准类型|string（枚举）|—|归一化后的基准类型取值|随父级返回|
|`benchmark.id`|基准 ID|string|字符串 ID|指数代码或自定义基准 ID|随父级返回|
|`template`|归因模板|string|—|提交时选择的模板，取值同提交参数|由参数选择；仅做收益拆解时该键缺席|
|`create_time`|创建时间|string|—|服务端记录的任务创建时间|随归因记录返回|
|`drilldown`|是否对资产单元穿透|boolean|—|与提交参数一致|随归因记录返回|
|`industry_standard`|行业分类标准|string（枚举）|—|提交时未指定时由服务端填入默认值|随归因记录返回|
|`only_returns_decomposition`|是否仅收益拆解|boolean|—|与提交参数一致|随归因记录返回|
|`status`|任务状态|string（枚举）|—|任务完成时由服务端写入 `SUCCESS`|由数据决定；见[任务终态 JSON](connection.md#task-result)|
|`message`|任务提示|string / null|—|任务完成时由服务端写入的说明文案|由数据决定；成功时可能为空字符串|
|`result`|归因结果主体|object / array|—|按 `only_returns_decomposition` 与 `template` 组成的归因结果：模板分支下是含下列键的对象，仅收益拆解分支下根对象就是收益拆解数组|由数据决定；任务成功后才返回；不含导出附件键，Brinson 模板下也不含日度归因序列|
|`result[]`|收益拆解节点|object|—|仅收益拆解分支的数组元素；树形结构由 `children` 递归，字段见下列 `result[].…` 各行|由参数选择：`only_returns_decomposition=True`|
|`result[].factor`|节点名称|string|—|节点名：`总收益`、`交易收益`、`杠杆收益`、`持仓收益`、`超额收益`、`基准持仓收益`、`基准收益`、`穿透效应`，以及各类资产的`{资产类别}收益`／`{资产类别}配置收益`／`{资产类别}选择收益`|随父级返回|
|`result[].value`|节点收益|number|小数|该节点的区间累计收益（多期连接后累计，不是逐日求和）|随父级返回|
|`result[].children`|子节点列表|array / null|—|下一层拆解节点；叶子节点为 `null`|由数据决定：叶子节点为 `null`|
|`result.returns_decomposition`|收益拆解树|array（object）|—|元素结构同 `result[]` 三行；对象分支下各模板都有|由参数选择：`template` 为 `equity/brinson`、`equity/factor`、`equity/factor_v2` 之一时返回|
|`result.attribution`|模板归因结果|object|—|该模板的归因结果容器，键由模板决定|由参数选择：同上三模板；实时与仅收益拆解分支没有该键|
|`result.attribution.brinson`|行业归因|array（object）|—|每行一个行业，按引擎的行业排序输出|由参数选择：`template=equity/brinson`|
|`result.attribution.brinson[].industry`|行业|string|—|[行业名](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)；基准为现金时为 `其他`，为国债收益率时为 `债券`|随父级返回|
|`result.attribution.brinson[].allocation_return`|行业配置收益|number|小数|区间累计的行业配置收益|随父级返回|
|`result.attribution.brinson[].selection_return`|选股收益|number|小数|区间累计的选股收益|随父级返回|
|`result.attribution.brinson[].active_return`|主动收益|number|小数|配置收益与选股收益之和|随父级返回|
|`result.attribution.brinson[].portfolio_weight`|组合权重|number|小数|区间均值权重|随父级返回|
|`result.attribution.brinson[].benchmark_weight`|基准权重|number|小数|区间均值权重|随父级返回|
|`result.attribution.brinson[].allocation_risk`|行业配置风险贡献|number|小数|该行业配置对日频主动收益标准差的贡献（未年化，不是金额）|随父级返回|
|`result.attribution.brinson[].selection_risk`|选股风险贡献|number|小数|同口径的选股风险贡献|随父级返回|
|`result.attribution.factor_attribution`|因子归因|array（object）|—|5 个固定类别元素：`style`、`industry`、`country`、`specific_return`、`other`；服务端按 `style`、`specific_return`、`industry`、`country`、`other` 排序|由参数选择：`template=equity/factor` 或 `equity/factor_v2`|
|`result.attribution.factor_attribution[].type`|因子类别|string|—|取值即上一行的五个类别名|随父级返回|
|`result.attribution.factor_attribution[].factors`|因子项列表|array（object）|—|该类别下的因子项，字段见下列各行；可能为空数组|随父级返回|
|`result.attribution.factor_attribution[].factors[].factor`|因子名|string|—|风格、行业、国别因子名或 `specific_return`／`other`|随父级返回|
|`result.attribution.factor_attribution[].factors[].portfolio_return`|因子组合收益|number|小数|区间累计因子收益|随父级返回|
|`result.attribution.factor_attribution[].factors[].benchmark_return`|因子基准收益|number|小数|同口径的基准因子收益|随父级返回|
|`result.attribution.factor_attribution[].factors[].active_return`|因子主动收益|number|小数|组合与基准因子收益之差|随父级返回|
|`result.attribution.factor_attribution[].factors[].portfolio_exposure`|组合暴露度|number / null|—|区间均值暴露度；`specific_return` 与 `other` 两类恒为 `null`|随父级返回|
|`result.attribution.factor_attribution[].factors[].benchmark_exposure`|基准暴露度|number / null|—|同口径的基准暴露度；该类别不适用时为 `null`|随父级返回|
|`result.attribution.factor_attribution[].factors[].active_exposure`|主动暴露度|number / null|—|组合与基准暴露度之差|随父级返回|
|`result.attribution.factor_attribution[].factors[].portfolio_risk`|因子组合风险贡献|number / null|小数|对日频组合收益标准差的贡献（未年化，不是金额）|随父级返回|
|`result.attribution.factor_attribution[].factors[].benchmark_risk`|因子基准风险贡献|number / null|小数|同口径的基准风险贡献|随父级返回|
|`result.attribution.factor_attribution[].factors[].active_risk`|因子主动风险贡献|number / null|小数|同口径的主动风险贡献|随父级返回|
|`result.attribution.factor_exposure`|因子暴露序列|array（object）|—|每项一个因子的逐日[暴露度](https://www.ricequant.com/doc/rqdata/python/risk-factors-mod#rqdata-API-get_factor_exposure)|由参数选择：`template=equity/factor` 或 `equity/factor_v2`|
|`result.attribution.factor_exposure[].factor`|因子名|string|—|与因子归因里的因子名一致|随父级返回|
|`result.attribution.factor_exposure[].data`|逐日暴露度|array（object）|—|元素见下列各行|随父级返回|
|`result.attribution.factor_exposure[].data[].date`|暴露度日期|string|—|取该日的前一交易日，`YYYY-MM-DD`|随父级返回|
|`result.attribution.factor_exposure[].data[].portfolio`|组合暴露度|number|—|按组合权重加权的暴露度|随父级返回|
|`result.attribution.factor_exposure[].data[].normalized`|权益部分暴露度|number|—|按归一化权重（权重 ÷ 权重合计）加权的暴露度|随父级返回|
|`result.attribution.factor_exposure[].data[].active`|主动暴露度|number|—|组合暴露度与基准暴露度之差|随父级返回|
|`result.attribution.sensitivity`|净值回归|array（object）|—|最多 3 个时间段，每段一项|由参数选择：`template=equity/factor` 或 `equity/factor_v2`|
|`result.attribution.sensitivity[].date`|区间结束日|string|—|该段结束日，`YYYY-MM-DD`|随父级返回|
|`result.attribution.sensitivity[].data`|逐因子回归结果|array（object）|—|元素见下列各行|随父级返回|
|`result.attribution.sensitivity[].data[].factor`|因子名|string|—|与因子归因里的因子名一致|随父级返回|
|`result.attribution.sensitivity[].data[].portfolio`|因子敏感度|number|—|组合日收益对因子收益回归的系数|随父级返回|
|`result.attribution.sensitivity[].data[].t_statistics`|敏感度 t 值|number|—|该回归系数的 t 统计量|随父级返回|
|`result.is_benchmark_weight_daily`|基准权重是否按日更新|boolean|—|按基准类型与权重来源判定；服务端不消费该键|由参数选择：`template` 为 `equity/brinson`、`equity/factor`、`equity/factor_v2` 之一时返回|

结果检查：用 `_id` 做后续查询与导出；`result` 缺失时说明结果尚未写入，不要把它当作空归因结果。

## delete_attribution

删除归因记录。
- delete_attribution：按归因 ID 直接删除，返回 null；网关要求 `read_position`，客户端不预判权限。

Python 签名：`rqamsh.analytics.delete_attribution(resource: str, attribution_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`attribution_id`|`str`|必填|要删除的归因 ID。|

返回：空响应，客户端得到 `None`；删除成功与「记录本就不存在」都是这个结果，删除不改变历史估值结果。

## export_attribution

导出归因结果（生成文件并落盘）。
- export_attribution：先有终态归因，再导出到新文件；目标文件已存在时抛错。

Python 签名：`rqamsh.analytics.export_attribution(resource: str, attribution_id: str, output: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`attribution_id`|`str`|必填|已终态的归因 ID。|
|`output`|`str`|必填|输出文件路径；父目录须存在且目标文件不得已存在。|

返回：客户端下载元数据，含 `path`、`size`；先有终态归因、任务完成后才写入本地新文件。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](connection.md#download-result)|

已知服务端缺陷：`equity/brinson` 归因结果的日度序列表为空时，导出任务会失败且不给出可读业务错误，而同样区间下 `equity/factor` 结果可正常导出；遇到该失败应改用因子模板，或先确认该区间确实没有可导出的 Brinson 日度序列。

## realtime_risk_attribution

读取实时风险归因。
- realtime_risk_attribution：仅单产品；模板决定分解方式，因子模板与 Brinson 模板的行业标准参数分别可选，只有提供时才下发。

Python 签名：`rqamsh.analytics.realtime_risk_attribution(resource: str, *, template: str='equity/factor', benchmark: str | None=None, factor_industry_standard: str | None=None, brinson_industry_standard: str | None=None, drilldown: bool=False)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称；不支持产品组。|
|`template`|`str`|`equity/factor`|分解模板，取 `equity/factor` 或 `equity/factor_v2`；服务端在同一次任务内同时计算 Brinson 结果。|
|`benchmark`|`str \| None`|`None`|可选基准。|
|`factor_industry_standard`|`str \| None`|`None`|因子模板下的[行业分类](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)标准。|
|`brinson_industry_standard`|`str \| None`|`None`|Brinson 模板下的行业分类标准。|
|`drilldown`|`bool`|`False`|是否对资产单元穿透。|

服务端不接受日期参数，固定以北京时间当天作为归因区间，因此当天不是交易日时该操作必然失败（报错为「分析区间内没有交易日」），调用方无法通过参数换区间——需要指定区间时必须用 `create_attribution`。实时因子暴露 `realtime_factor_exposure` 走另一套实时序列检查，不受此限制。

返回：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，归因结果在 `data` 内。`data` 是当次实时因子归因结果，服务端在同一次任务内把实时行业归因并入 `attribution.brinson`；键集合固定，但因子列表随当日持仓与暴露度数据变化。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|实时风险归因结果|object|—|实时因子归因结果与同一次任务内合入的实时行业归因；字段见下列各行|由数据决定；`status` 为 `SUCCESS` 时返回|
|`data.attribution`|实时归因结果容器|object|—|只含 `factor_attribution` 与 `brinson` 两个键；没有 `returns_decomposition`、`excel_report`、`factor_exposure`、`sensitivity`|随父级返回|
|`data.attribution.factor_attribution`|因子归因|array（object）|—|5 个固定类别元素，排序与区间归因一致|随父级返回|
|`data.attribution.factor_attribution[].type`|因子类别|string|—|`style`、`industry`、`country`、`specific_return`、`other`|随父级返回|
|`data.attribution.factor_attribution[].factors`|因子项列表|array（object）|—|该类别下的因子项；可能为空数组|随父级返回|
|`data.attribution.factor_attribution[].factors[].factor`|因子名|string|—|风格、行业、国别因子名或 `specific_return`／`other`|随父级返回|
|`data.attribution.factor_attribution[].factors[].portfolio_return`|因子组合收益|number|小数|当日口径的因子收益（实时归因只用当天数据）|随父级返回|
|`data.attribution.factor_attribution[].factors[].benchmark_return`|因子基准收益|number|小数|同口径的基准因子收益|随父级返回|
|`data.attribution.factor_attribution[].factors[].active_return`|因子主动收益|number|小数|组合与基准因子收益之差|随父级返回|
|`data.attribution.factor_attribution[].factors[].portfolio_exposure`|组合暴露度|number / null|—|按当日持仓权重与前一交易日个股[暴露度](https://www.ricequant.com/doc/rqdata/python/risk-factors-mod#rqdata-API-get_factor_exposure)算出；算不出暴露度的因子保持 `null`|随父级返回|
|`data.attribution.factor_attribution[].factors[].benchmark_exposure`|基准暴露度|number / null|—|按基准权重与同一批暴露度算出|随父级返回|
|`data.attribution.factor_attribution[].factors[].active_exposure`|主动暴露度|number / null|—|组合暴露度与基准暴露度之差|随父级返回|
|`data.attribution.brinson`|实时行业归因|array（object）|—|同一次任务内算出的行业归因，只有收益与权重，没有风险贡献两项|随父级返回|
|`data.attribution.brinson[].industry`|行业|string|—|行业名；基准为现金时为 `其他`，为国债收益率时为 `债券`|随父级返回|
|`data.attribution.brinson[].allocation_return`|行业配置收益|number|小数|当日口径的行业配置收益|随父级返回|
|`data.attribution.brinson[].selection_return`|选股收益|number|小数|当日口径的选股收益|随父级返回|
|`data.attribution.brinson[].active_return`|主动收益|number|小数|配置收益与选股收益之和|随父级返回|
|`data.attribution.brinson[].portfolio_weight`|组合权重|number|小数|当日权重|随父级返回|
|`data.attribution.brinson[].benchmark_weight`|基准权重|number|小数|当日权重|随父级返回|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键；提示级别见 `message_type` 行|
|`message_type`|提示级别|string|—|`error`／`warning`：区分失败原因与可继续解读的提示（基准权重按月度近似时为 `warning`）|由数据决定；与 `message` 同时出现|

结果检查：`data` 的键固定为因子归因与实时行业归因两族，但因子列表随当日持仓与暴露度数据变化，解读前先看实际键；当天不是交易日时任务必然失败，这不是数据缺口。

## realtime_factor_exposure

读取实时因子暴露序列。
- realtime_factor_exposure：仅单产品；模板必填，客户端不校验该参数，非法值由服务端拒绝。返回 `exposure_series`（逐时点暴露）与 `start`/`end`；持仓内没有股票或暴露度尚未就绪时只返回区间信息。

Python 签名：`rqamsh.analytics.realtime_factor_exposure(resource: str, *, template: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称；不支持产品组。|
|`template`|`str`|必填|因子模板，取 `equity/factor` 或 `equity/factor_v2`；其他值由服务端拒绝。|

返回：服务端原始时序对象，含 `exposure_series`、`start`、`end`；持仓内没有股票或暴露度尚未就绪时只返回区间信息。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|实时因子暴露结果|object|—|服务端直接返回的暴露时序对象，含 `exposure_series`、`start`、`end`，另有告警时附带告警键|恒返回；持仓无股票或无暴露数据时只含 `start`、`end`|
|`exposure_series`|逐时点暴露序列|array（object）|—|每个实时时点一条，元素含 `datetime` 与各因子名键，值为持仓加权暴露减基准暴露|由数据决定；无股票持仓或全部标的无暴露数据时不返回该键|
|`exposure_series[].datetime`|时点|string|—|该条记录的实时时点|随父级记录返回|
|`exposure_series[].{因子名}`|该因子主动暴露|number|—|该时点该因子的[主动暴露](https://www.ricequant.com/doc/rqdata/python/risk-factors-mod#rqdata-API-get_factor_exposure)，键名为英文因子名|由数据决定；键随模板与暴露数据，同一条内并非所有因子都有值|
|`start`|区间起点|string|—|本次实时序列的起点时点|恒返回|
|`end`|区间终点|string|—|本次实时序列的终点时点|恒返回|
|`message_type`|提示级别|string（枚举）|—|基准等依赖数据不可用时的提示级别|由数据决定；只在有告警时与 `warning_message` 一起返回|
|`warning_message`|告警文案|string|—|基准等依赖数据不可用时的说明|由数据决定；只在有告警时返回|

结果检查：只有 `start`、`end` 时表示没有股票持仓或暴露度未就绪，不是零暴露；因子键名以实际返回为准，不要按模板名推断完整因子集合。

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

这七个操作都是任务型的：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，业务结果在 `data` 内（`task_id`、`status`、`message` 的含义见[任务终态 JSON](connection.md#task-result)）。逐操作的表结构如下。

**`group_indicators`**

返回：`data` 为成员逐条指标数组，一名成员一条；表中的 `{frequency}` 代入 `daily`、`weekly`、`monthly`，三者键名相同，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|成员指标数组|array（object）|—|一名成员一条，元素含下列键|`status` 为 `SUCCESS` 时返回；成员数可能少于 `resources`（不可见或已删除的成员、没有成员产品的产品组被丢弃）|
|`data[].id`|成员 ID|string|—|成员产品或产品组的唯一 ID|随父级记录返回|
|`data[].name`|成员名称|string|—|成员产品或产品组的名称|随父级记录返回|
|`data[].start_date`|成员起始日|string|YYYY-MM-DD|该成员自身的产品起始日|随父级记录返回；不是请求的 `start_date`|
|`data[].benchmark_name`|成员基准名称|string / null|—|该成员自身配置的基准名称|随父级记录返回；基准不在受支持基准与自定义基准内时查不到名称，取值为 `null`|
|`data[].net_value`|区间末净值|number / null|净值|该成员区间末行（`end_date` 与到期日的较早者）的净值：产品组取复权净值，产品取单位净值|随父级记录返回；是净值倍数，不是金额，也不是区间收益|
|`data[].annual_twoside_turnover_rate`|年化双边换手率|number / null|倍数|区间买卖金额合计 ÷ 区间平均净资产 ÷ 样本数 × 年化因子（交易日 252、自然日 365）|随父级记录返回；只在这一层出现，三个频率区块内没有同名键|
|`data[].period_acc_returns`|区间累计收益率|number / null|小数|区间内日收益累乘的末值；产品在区间内存在累计单位净值时改用区间末累计单位净值相对区间前一日单位净值的涨幅|随父级记录返回；与 `data[].daily.period_acc_returns` 同值|
|`data[].daily`|日频区块|object|—|含本表末尾的 21 项风险键、下列 10 项概况指标与 4 项回撤详情文本|随父级记录返回；日频无有效样本时只剩 10 项概况指标；基准收益率为空时风险键与回撤详情都不出现|
|`data[].daily.net_cash_in`|区间净投入|number / null|估值币种金额|区间内每日 [net_cash_in](fields/balances.md#net-cash-in) 的合计|随父级记录返回|
|`data[].daily.period_pnl`|区间盈亏|number / null|估值币种金额|区间内每日 [daily_pnl](fields/balances.md#daily-pnl) 的合计|随父级记录返回；是金额，不是收益率|
|`data[].daily.equity_net_exposure`|权益净敞口|number / null|估值币种金额|区间末有效日的 [equity_net_exposure](fields/balances.md#equity-net-exposure)|随父级记录返回；取末条，不是区间合计|
|`data[].daily.period_buy_amount`|区间买入金额|number / null|估值币种金额|区间内股票、债券与基金买入金额的合计|随父级记录返回；头寸来源为纯估值表的成员取值为 `null`，不是 `0`|
|`data[].daily.period_sell_amount`|区间卖出金额|number / null|估值币种金额|区间内股票、债券与基金卖出金额的合计|随父级记录返回；与买入金额同为区间合计口径|
|`data[].daily.cash`|期末现金|number / null|估值币种金额|区间末有效日的 [cash](fields/balances.md#cash)|随父级记录返回|
|`data[].daily.total_equity`|期末净资产|number / null|估值币种金额|区间末有效日的 [total_equity](fields/balances.md#total-equity)|随父级记录返回；与风险键 `total_returns` 不同物|
|`data[].daily.period_acc_returns`|区间累计收益率|number / null|小数|与 `data[].period_acc_returns` 同值|随父级记录返回|
|`data[].daily.cn_stock_market_value`|期末 A 股市值|number / null|估值币种金额|区间末有效日的 A 股持仓市值|随父级记录返回|
|`data[].daily.hk_stock_market_value`|期末港股市值|number / null|估值币种金额|区间末有效日的港股持仓市值|随父级记录返回|
|`data[].daily.max_drawdown_period`|最大回撤区间|string|—|口径与取值同[指标返回字段与公式](#indicators-returns) 的 `max_drawdown.max_drawdown_period`|随父级记录返回；是文本明细，不是数值回撤|
|`data[].daily.max_drawdown_recovery_days`|最大回撤修复时长|string|—|口径与取值同[指标返回字段与公式](#indicators-returns) 的 `max_drawdown.max_drawdown_recovery_days`|随父级记录返回；未回撤、未修复的取值规则见该表|
|`data[].daily.geometric_excess_max_drawdown_period`|几何超额最大回撤区间|string|—|口径与取值同[指标返回字段与公式](#indicators-returns) 的 `excess_max_drawdown.geometric_excess_max_drawdown_period`|随父级记录返回；不要与数值键 `data[].{frequency}.geometric_excess_max_drawdown` 混淆|
|`data[].daily.geometric_excess_max_drawdown_recovery_days`|几何超额最大回撤修复时长|string|—|口径与取值同[指标返回字段与公式](#indicators-returns) 的 `excess_max_drawdown.geometric_excess_max_drawdown_recovery_days`|随父级记录返回；未修复的取值规则见该表|
|`data[].weekly`|周频区块|object|—|只含本表末尾的 21 项风险键|随父级记录返回；周频无有效样本时为空对象 `{}`；不并入概况指标与回撤详情|
|`data[].monthly`|月频区块|object|—|只含本表末尾的 21 项风险键|随父级记录返回；月频无有效样本时为空对象 `{}`；不并入概况指标与回撤详情|
|`data[].{frequency}.alpha`|年化詹森阿尔法|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.alpha`|随父级返回|
|`data[].{frequency}.absolute_alpha`|零无风险利率口径的年化阿尔法|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.absolute_alpha`|随父级返回|
|`data[].{frequency}.beta`|贝塔|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.beta`|随父级返回|
|`data[].{frequency}.sharpe`|夏普比率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.sharpe`|随父级返回|
|`data[].{frequency}.absolute_sharpe`|零无风险利率口径的夏普比率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.absolute_sharpe`|随父级返回|
|`data[].{frequency}.excess_sharpe`|超额收益夏普比率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.excess_sharpe`|随父级返回|
|`data[].{frequency}.max_drawdown`|最大回撤|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.max_drawdown`|随父级返回；是数值回撤，与 `data[].daily.max_drawdown_period` 不同物|
|`data[].{frequency}.annual_downside_risk`|年化下行风险|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.annual_downside_risk`|随父级返回|
|`data[].{frequency}.information_ratio`|信息比率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.information_ratio`|随父级返回|
|`data[].{frequency}.geometric_excess_annual_return`|几何超额年化收益率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.geometric_excess_annual_return`|随父级返回|
|`data[].{frequency}.arithmetic_excess_annual_return`|逐期算术超额连乘后的年化收益率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.arithmetic_excess_annual_return`|随父级返回；不是几何超额年化收益率|
|`data[].{frequency}.annual_volatility`|年化收益波动率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.annual_volatility`|随父级返回|
|`data[].{frequency}.excess_annual_volatility`|年化超额收益波动率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.excess_annual_volatility`|随父级返回|
|`data[].{frequency}.annual_tracking_error`|年化跟踪误差|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.annual_tracking_error`|随父级返回|
|`data[].{frequency}.geometric_excess_max_drawdown`|几何超额最大回撤|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.geometric_excess_max_drawdown`|随父级返回|
|`data[].{frequency}.total_returns`|区间累计收益率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.total_returns`|随父级返回；与 `data[].period_acc_returns` 分属风险表与概况两个口径，不要互相顶替|
|`data[].{frequency}.total_geometric_excess_return`|区间几何超额收益率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.total_geometric_excess_return`|随父级返回|
|`data[].{frequency}.total_arithmetic_excess_return`|区间算术超额收益率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.total_arithmetic_excess_return`|随父级返回|
|`data[].{frequency}.total_annual_returns`|日频区间累计收益折算的年化收益率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.total_annual_returns`|随父级返回|
|`data[].{frequency}.annual_simple_interest`|日频区间累计收益折算的单利年化收益率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.annual_simple_interest`|随父级返回|
|`data[].{frequency}.calmar_ratio`|卡马尔比率|number / null|小数|同[指标返回字段与公式](#indicators-returns) 的 `{frequency}_risk.calmar_ratio`|随父级返回|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：这是组级口径的成员指标，与单产品 `indicators` 的对应区块不能互换比较；元素随成员数量变化，缺估值的成员不会出现在结果里（任务先补算重试，最终失败），只有生命周期与请求区间无交集的成员占一条且只含前四个身份键。

**`group_returns`**

返回：`data` 为记录数组，第一条是基准记录，随后每个算得出指标的成员一条；下表中的 `{frequency}` 代入 `daily`、`weekly`、`monthly`，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
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

结果检查：先按 `type` 分出基准与成员，再比较同一频率的 `cumulative_returns`；只有基准记录的周、月周期收益落在 `daily_returns` 键上，成员记录的周/月频没有该键，不要按日频键集去取周/月记录。

**`group_capital_size`**

返回：`data` 为日期记录数组，按成员投资类别给出规模。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|规模走势数组|array（object）|—|区间内每个有估值的日期一条，元素含下列键|`status` 为 `SUCCESS` 时返回；成员全部不可见或日期都落在[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)之外时为空数组 `[]`|
|`data[].date`|记录日期|string|YYYY-MM-DD|该条记录对应的估值日|随父级记录返回；该日期不在交易日历内时整条记录不出现|
|`data[].asset_classes`|分类规模列表|array（object）|—|该日期按成员投资类别聚合后的规模，元素只有下列两个键|随父级记录返回；`date` 只在元素外层，元素内没有该键；某日全部成员的投资类别都为空时该日记录仍在，此键为空数组 `[]`|
|`data[].asset_classes[].asset_class_name`|成员投资类别|string|—|该成员产品配置里 `investment_category` 的中文名，即[产品投资类别](fields/products.md#productinvestmentcategory) 的「含义」列（12 项之一）；字段名带 `asset_class`，但不是[资产品种与会计科目](fields/others.md#assetclass) 的取值|随父级记录返回；产品组成员恒为「产品组」；投资类别为空的成员不进该日记录；取值不在枚举内时原样保留|
|`data[].asset_classes[].value`|该类当日净资产合计|number|估值币种金额|该投资类别下全部成员当日的净资产合计|随父级记录返回；是净资产合计，不是市值，也不是收益率|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：`value` 是净资产金额，不是收益率；按类别分别看趋势，不要直接相加不同类别的口径。成员集合不可见或日期全落在交易日历之外时才是空数组，请求区间本身缺估值会让任务失败。

**`group_allocation`**

返回：`data` 为配置权重对象，只覆盖截止日截面；表中的 `{交易资产属性}` 与 `{子类型}` 是中文业务名动态键，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|配置权重|object|—|以交易资产属性中文名为键，值为「子类型中文名 → 权重」的对象|`status` 为 `SUCCESS` 时返回；全部成员当日都没有持仓时为空对象 `{}`|
|`data.{交易资产属性}`|该属性下的子类型权重|object|—|该属性下各子类型的权重；属性键是[交易资产属性](fields/others.md#tradingassetclass) 的中文名，共 10 个可能出现的取值|由数据决定：只出现当日有持仓的属性；资产类别不在归并表内时该持仓整体不计入，对应属性键也不出现|
|`data.{交易资产属性}.{子类型}`|子类型权重|number / null|小数|该子类型的持仓市值合计 ÷ 当日有持仓成员的净资产合计|由数据决定：分母为 `0` 时取值为 `null`；带符号市值可让权重为负；股票与基金的子类型按板块与基金类型细分，细分匹配失败时保留服务端原始取值|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：两个层级的键都是中文业务名（股票与基金的子类型细分匹配失败时保留服务端原始取值），不是 `asset_class` 枚举值；权重分母是当日有持仓成员的净资产合计，不等于某一成员内部的持仓占比，带符号市值可让权重为负。

**`group_returns_correlation`**

返回：`data` 为收益相关性矩阵，按频率分组；表中的 `{frequency}` 代入 `daily`、`weekly`、`monthly`，`{成员名}` 是成员名称动态键，二者都不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
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
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
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
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](connection.md#download-result)|

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

返回：`data` 内按策略分桶给出成员条目与指数周收益；`task_id`、`status`、`progress` 与 `message` 的含义见[任务终态 JSON](connection.md#task-result)。

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
|`data.{桶}[].week_returns`|本周收益|number / null|小数|本窗口内的区间累计收益率，口径同 [indicators](#indicators-returns) 的 `returns_summary.total`|随父级返回|
|`data.index_enhanced[].week_excess_returns`|本周几何超额收益|number / null|小数|本窗口内的几何超额收益率，口径同 [indicators](#indicators-returns) 的 `returns_summary.geometric_excess`|仅指数增强条目返回；市场中性条目没有该键|
|`data.market_neutral[].sharpe`|周频夏普比率|number / null|小数|全区间周频夏普比率，口径同 [indicators](#indicators-returns) 的 `weekly_risk.sharpe`|仅市场中性条目返回|
|`data.market_neutral[].annual_returns`|周频年化收益率|number / null|小数|全区间周频累计收益折算的年化收益率，口径同 [indicators](#indicators-returns) 的 `weekly_risk.total_annual_returns`|仅市场中性条目返回|
|`data.market_neutral[].max_drawdown`|周频最大回撤|number / null|小数|全区间周频最大回撤取负后的数值，负回撤在报告中显示为正数|仅市场中性条目返回；与 [indicators](#indicators-returns) 的 `weekly_risk.max_drawdown` 符号相反|
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

结果检查：先读 `data.start_date`~`data.end_date` 确认窗口，再按桶取成员——[投资策略类别](fields/products.md#strategycategory)为多重时，全部属于市场中性、多空、杠杆中性才进 `market_neutral`，否则进 `index_enhanced`；两类都为空数组表示本期没有可入报告的成员，不是收益为零。`week_returns` 只覆盖窗口，`sharpe`、`annual_returns` 与 `asset_series` 覆盖成员统计起点到截止日的全区间，两类指标不要互相印证。成员缺本周或全区间指标时不占条目，也不补零。

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
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](connection.md#download-result)|

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

这三个操作也都是任务型的：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，业务结果在 `data` 内（含义见[任务终态 JSON](connection.md#task-result)）。

**`trading_analysis`**

返回：`data` 为区间交易分析记录数组，一行一个「资产类别 + 标的代码 + 标的名称 + 方向」分组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|区间交易分析记录|array（object）|—|一个元素一个「资产类别 + 标的代码 + 标的名称 + 方向」分组，含下列键|`status` 为 `SUCCESS` 时返回；区间内没有持仓盈亏时为空数组 `[]`|
|`data[].asset_class`|资产品种|string|—|该分组持仓的资产类别取值，如 `stock`、`closed_end_fund`；全量取值与中文含义见[资产品种与会计科目](fields/others.md#assetclass)|随父级记录返回；是英文取值，不是中文名|
|`data[].order_book_id`|标的代码|string|—|该分组的标的代码|随父级记录返回；因改名而变更的代码已按区间末条概要日的生效映射统一|
|`data[].symbol`|标的名称|string|—|该分组的标的名称|随父级记录返回；与 `data[].order_book_id` 出自同一份改名映射|
|`data[].direction`|持仓方向|string（枚举）|—|`long` 多头、`short` 空头|随父级记录返回|
|`data[].asset_category`|交易属性分类中文名|string|—|该资产类别对应的[交易资产属性](fields/others.md#tradingassetclass) 中文名|随父级记录返回；不在归并表内的类别取固定文案「其他资产」（仍照常成组）|
|`data[].date`|该分组最后一次出现的估值日|string|YYYY-MM-DD|该分组在区间内最后一次出现在概要里的日期|随父级记录返回；不是「最后一个有盈亏的日期」，当日盈亏缺失时本键照常推进|
|`data[].period_pnl`|截至 `date` 的区间累计盈亏|number / null|估值币种金额|该分组区间内逐条 [daily_pnl](fields/balances.md#daily-pnl) 按出现顺序的累加值|随父级记录返回；该组末条明细当日盈亏缺失时取值为 `null`，与数值 `0` 不同|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键|

结果检查：这是结果视图，不修改流水；`period_pnl` 按分组逐条累计，该组末条明细缺当日盈亏时取值为 `null` 而不是 0；请求区间本身缺估值会让任务失败，不是空数组。

**`single_trading_analysis`**

返回：`data` 为单标的走势对象，含价格、持仓、累计盈亏与[买卖点](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_share_transformation)序列。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
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
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](connection.md#task-result)|
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

交易分析是结果视图，不修改流水；需要核对成交本身时用 [trades](trades.md)。

