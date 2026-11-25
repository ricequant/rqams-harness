# 净值与收益指标 analytics

下列 5 个操作读取服务端已算好的指标结果，客户端不重算；上游历史数据是否齐备先用[头寸报表](../balances.md)时序核对。与[组合对比](portfolio_analysis.md#组合对比) 的 `group_indicators` 不同：后者按成员集合整组取数，口径与单产品指标不通用。

本页是 [analytics 总览](index.md) 的子页：用户需求与完成条件见[总览的场景表](index.md#从用户需求到操作)，`resource`/`resources` 语义与阻塞式调用等公共约定见[总览](index.md#api-使用约定)；本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。

## indicators

计算产品或产品组区间指标。
- indicators：产品/组 daily_risk、weekly_risk、monthly_risk 与 last_unit_net_value；extra_indicators 可选 annual_risk、returns_summary、asset_series、benchmark_series、monthly_returns、win_rate、excess_returns、leverage_ratio、max_drawdown、excess_max_drawdown、ashares_market_value。额外字段各自数据形状见[下方完整返回字段表](#indicators-returns)。

Python 签名：`rqamsh.analytics.indicators(resource: str, *, start_date: str | None=None, end_date: str | None=None, benchmark: str | None=None, extra_indicators: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用资源起始日。单只指增产品从交易起始日分析时，首日不计入受影响的超额指标，见[指增超额起算口径](#index-enhanced-excess-start)。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用最近结算日，且受产品到期日限制。|
|`benchmark`|`str \| None`|`None`|省略时使用产品或产品组已配置的基准；显式覆盖用“类型,ID”，例如 `index,000300.XSHG`。其他类型和 ID 从[当前空间可用基准](../market_data.md#benchmarks)核对。|
|`extra_indicators`|`list[str] \| None`|`None`|额外指标名称数组。|

<a id="indicator-inputs"></a>

### 从每日头寸到区间指标

#### 输入整理与日历

1. **取输入。** 产品侧读取逐日头寸报表摘要，单产品另取区间开始日前的基点净值；有可用的当日实时截面时可并入。统计侧另取[基准收益、日历和无风险利率](#external-inputs)。这是服务端取数，调用方无需另外连接 RQData。没有头寸摘要或基准时可返回 `{}`，不表示零收益。
2. **对齐日期。** 头寸摘要先与自然日基准日期对齐：净资产、总资产和单位净值的缺口沿用之前的值，头寸日收益缺失按 `0`，累计单位净值不在此步补齐。收益样本再按产品或产品组日历取日期，分析区间受起始日、到期日及实际基准范围限制；净值按 AMS 精度舍入后参与计算。
3. **形成收益样本。** 单产品的累计单位净值和单位净值两列均有有效值时，剩余净值缺口用后续有效值补齐。日收益取「当日累计单位净值 − 上一估值日累计单位净值」除以「上一估值日单位净值」；首日用区间前一自然日的基点净值，对应基点缺失或为零时按 `1`。周、月收益用相同的净值差口径取各周期的期初和期末，不是累计净值相除。产品组或缺上述净值的单产品，日频使用整理后的头寸日收益，周、月收益由周期内的日增长倍数连乘再减 `1`；基准周、月收益也按此法聚合。周按周日结束，月按月末，年按年末分组；首尾可为不完整周期。

#### 收益概览与风险统计

- **风险统计按同一套方法读。** `daily_risk`、`weekly_risk`、`monthly_risk` 分别使用相应频率下的配对产品收益与基准收益；`annual_risk` 按年组织这些样本，并取该年区间的无风险利率。Alpha、Sharpe、波动、回撤、跟踪误差等由 [RQRISK](https://github.com/ricequant/rqrisk) 的 [`Risk` 实现](https://github.com/ricequant/rqrisk/blob/1.0.13/rqrisk/risk.py)计算。AMS 决定传入的样本、频率和无风险利率，并额外组装年化收益、单利年化和卡马尔比率等字段。源码链接用于查统计实现；接口的输入口径和返回字段仍以本页为准。
- **区间收益先区分输出用途。** `returns_summary.total` 是收益概览：单产品有可用净值时，从整个区间的基点和期末累计单位净值求差，再除以基点单位净值。`{frequency}_risk.total_returns` 是对应频率的收益连乘。在使用同一组对齐后日收益的分支（如产品组），`returns_summary.total` 与 `daily_risk.total_returns` 都是日收益连乘；走净值差分支时，两者可能不同，例如分红使单位净值与累计单位净值分离。不能只凭字段都叫「区间累计收益」就直接替换。
- **核对超额前先确认起算日。** 单产品策略为 `index_enhanced`，且分析起始日等于 `trading_start_date` 时，受影响的超额指标不计入首日，绝对收益口径不变。不能拿原区间绝对收益和原区间基准直接复算这些超额；见下方[指增超额起算口径](#index-enhanced-excess-start)。
- **需要核对样本时再取序列。** 在 `extra_indicators` 中选 `asset_series` 和 `benchmark_series`，核对相同频率下两边的日期和收益。`asset_series.daily[].daily_returns` 是整理后的指标日收益，不是[原始头寸时序](../balances.md#series)中的同名字段；日期对齐补出的行也不证明当日头寸参与了计算。

<a id="index-enhanced-excess-start"></a>

#### 指增超额起算口径

单只指增产品从交易起始日分析时，首日不计入下列超额指标：以交易起始日的结算单位净值和累计单位净值为基点，产品与基准都从产品日历中的下一交易日开始取样本，期末不变。这是指增超额的正常口径，不改变绝对收益。如果请求从后续日期开始或查的是产品组，不按此规则再跳一天；下一交易日超过期末，或缺首日结算净值、后续头寸摘要或基准样本时，服务端不做这次调整。

|受影响的返回位置|按指增口径计算的字段|
|---|---|
|`returns_summary`|`arithmetic_excess`、`geometric_excess`|
|`daily_risk`、`weekly_risk`、`monthly_risk` 及 `annual_risk`|`total_arithmetic_excess_return`、`total_geometric_excess_return`、`arithmetic_excess_annual_return`、`geometric_excess_annual_return`、`excess_sharpe`、`geometric_excess_max_drawdown`、`excess_annual_volatility`、`information_ratio`、`annual_tracking_error`；仅替换重算结果实际返回的年份、频率及字段，未匹配的保留原值|
|`monthly_returns` 年节点及月节点|重算结果中匹配的年、月节点替换 `arithmetic_excess_returns`、`geometric_excess_returns`；只有月节点还会替换 `annual_excess_volatility`（若重算结果返回该字段）。不替换周节点|

`asset_series`、`benchmark_series`、`excess_returns` 时序仍按原区间返回，不能把原区间时序的首日当作重算超额的首个样本。核验时保留原请求和原返回，再用同一基准、同一期末单独核对首日结算后的区间；确认基点及两侧实际样本对齐后，再复算算术差和几何比值。缺证据时只报告已取得的指标和核验缺口，不补零或据此认定计算异常。见[收益排查案例](../demo/returns-diagnosis/README.md#index-enhanced-excess-check)。

<a id="indicator-sample-coverage"></a>

#### 当日样本覆盖

请求 `end_date` 包含当日但快照未并入时，基准对齐仍可能生成当日行，缺失的头寸日收益会补为 `0`。返回当日行、当日收益为 `0` 或 HTTP 200，都不能单独证明当日已纳入计算。

用户要求「本周截至当前」等含实时的结论时，将指标日序列与同一对象的[当日头寸报表](../balances.md#get)交叉核对，不因单一净值字段为 `null` 或两种日收益口径不同就断言缺数据。截面尚未就绪时，按[未就绪规则](../connection.md#unready-inputs)有界等待并重读原指标请求；截面可读但仍无法确认已纳入时，保留两份回执并报告覆盖缺口，不擅自改截止日或以自算结果替换接口值。若另算描述性统计，单列来源、公式和实际样本范围。

<a id="indicators-returns"></a>

### 返回字段与计算公式

返回原始收益风险 JSON：有有效数据时默认包含 `daily_risk`、`weekly_risk`、`monthly_risk`；摘要非空且存在单位净值列时另含 `last_unit_net_value`。额外区块需通过 `extra_indicators` 选择；空组或无有效交易日会失败，无头寸摘要或基准数据可返回 `{}`。公式仅用于解释返回，API 不额外返回公式文本。

#### 完整返回字段大表

本表按服务端实际组装的返回结构整理，不是一次线上请求的实测样本；请求所选区块、是否提供累计单位净值和数据可用性决定实际出现哪些字段。

- 指标行中的头寸输入均链接到[头寸字段字典](../fields/balances.md#balance-calculation)：该页是字段定义、逐仓/估值计算、精度和业务输入的唯一来源。本页只解释指标如何选取、对齐或聚合这些字段。
- 路径相对于 Python `result` 根对象；`.` 表示对象层级，`[]` 表示数组元素。重复指标合并说明：`{frequency}` 分别代入 `daily`、`weekly`、`monthly`；`{period_frequency}` 仅代入 `weekly`、`monthly`。两者都不是实际 JSON 键，也不表示把多个频率的结果合成一个值。例如 `{frequency}_risk.alpha` 对应 `daily_risk.alpha`、`weekly_risk.alpha`、`monthly_risk.alpha`。年度风险另有动态年份 `{year}`，例如 `annual_risk.2025.daily_risk.alpha`；年/月/周收益树节点仍逐项展开。
- “随父级返回”以父级确实存在且相应数据有效为前提，不代表无条件必有。未请求的额外区块不返回；缺失键、`null`、空对象和空数组不能解释为数值 0。
- 比例用小数表示，`0.01 = 1%`；金额为估值币种金额；净值、杠杆及风险比率不直接按百分数展示。样本不足、零分母及非有限数值见[口径与异常值](#口径与异常值)。
- `NAV`／`AccNAV` 分别表示[单位净值](../fields/balances.md#unit-net-value)／[累计单位净值](../fields/balances.md#acc-unit-net-value)。`[起点]` 是区间收益基点，`[期初]`、`[期末]` 是对应周期的起止端点。
- 用于比较业绩时，应同时展示区间、频率和基准。`r`、`b` 分别是对应频率的产品或产品组收益序列、基准收益序列；`n` 为该频率样本数，`F` 为该频率年化因子。`R=prod(1+r) - 1`，`B=prod(1+b) - 1`，`Ra=(1+R)^(F/n) - 1`，`Ba=(1+B)^(F/n) - 1`，`f` 为[年化无风险利率](#external-inputs)，`f_p=(1+f)^(1/F) - 1`；`std`、`var`、`cov` 分别为样本标准差、方差、协方差（分母 `n - 1`），`C=[1,cumprod(1+r)]`，`cumprod` 为累计连乘，`running_max` 为截至当期的最高值。
- 年度风险中的 `r`、`b`、`n` 使用该年的分组数据，周/月仍沿用服务端周期归属；`R_daily`、`n_daily` 使用该年与请求区间交集的日序列。`dividend_ratio` 和复用整个请求区间的换手率按各自行说明。

|返回字段路径|中文名称|JSON 类型|返回条件|计算公式 / 结构|备注|
|---|---|---|---|---|---|
|`daily_risk`|日频风险指标|object|默认|按日频收益计算；交易日日历年化因子 252，自然日日历为 365|有效样本下含下列 21 项；该频率无样本时只给末尾三项年化/卡马尔字段|
|`weekly_risk`|周频风险指标|object|默认|按周频收益计算；年化因子 52|有效样本下含下列 21 项；该频率无样本时只给末尾三项年化/卡马尔字段|
|`monthly_risk`|月频风险指标|object|默认|按月频收益计算；年化因子 12|有效样本下含下列 21 项；该频率无样本时只给末尾三项年化/卡马尔字段|
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
|`{frequency}_risk.total_returns`|区间累计收益率|number / null|随父级对象返回|`R`|该频率收益连乘；与 `returns_summary.total` 的关系见[收益概览与风险统计](#收益概览与风险统计)|
|`{frequency}_risk.total_geometric_excess_return`|区间几何超额收益率|number / null|随父级对象返回|`(1+R)/(1+B) - 1`|`R`、`B` 取同一超额窗口；见[指增起算](#index-enhanced-excess-start)|
|`{frequency}_risk.total_arithmetic_excess_return`|区间算术超额收益率|number / null|随父级对象返回|`R-B`|与逐期算术超额连乘不同；见[指增起算](#index-enhanced-excess-start)|
|`{frequency}_risk.total_annual_returns`|日频区间累计收益折算的年化收益率|number / null|随父级对象返回|所有频率统一引用 `(1+R_daily)^(D/n_daily) - 1`，`D=交易252/自然365`|—|
|`{frequency}_risk.annual_simple_interest`|日频区间累计收益折算的单利年化收益率|number / null|随父级对象返回|所有频率统一引用 `R_daily/n_daily*S`，`S=交易250/自然365`|—|
|`{frequency}_risk.calmar_ratio`|卡马尔比率|number / null|随父级对象返回|上述日频期间年化收益除该频率 `max_drawdown`|期间年化收益相对最大回撤；零回撤时不能理解为可确定的无限回报|
|`last_unit_net_value`|区间末单位净值|number / null|默认；摘要非空且存在 unit_net_value 列|整理后同日头寸报表 [unit_net_value](../fields/balances.md#unit-net-value) 的最后一条|默认返回，不是累计净值|
|`annual_risk`|逐年风险|object|extra_indicators 包含 annual_risk|年份键 → 日/周/月风险对象|需 extra_indicators 选择 annual_risk；每年重新选择无风险利率|
|`annual_risk.{year}`|某年风险指标|object|随 annual_risk 返回|{year} 为实际年份字符串，例如 2025|按请求区间与该年的交集计算|
|`annual_risk.{year}.daily_risk`|该年日频风险指标|object|随 annual_risk 返回|该年日频收益；沿用全区间日频年化因子，重选该年区间无风险利率|有效样本下含下列 23 项；该频率无样本时只给三项年化/卡马尔字段及两项年度补充字段|
|`annual_risk.{year}.weekly_risk`|该年周频风险指标|object|随 annual_risk 返回|该年周频收益；沿用全区间周频年化因子，重选该年区间无风险利率|有效样本下含下列 23 项；该频率无样本时只给三项年化/卡马尔字段及两项年度补充字段|
|`annual_risk.{year}.monthly_risk`|该年月频风险指标|object|随 annual_risk 返回|该年月频收益；沿用全区间月频年化因子，重选该年区间无风险利率|有效样本下含下列 23 项；该频率无样本时只给三项年化/卡马尔字段及两项年度补充字段|
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
|`annual_risk.{year}.{frequency}_risk.total_returns`|区间累计收益率|number / null|随父级对象返回|`R`|只连乘该年对应频率的收益；`returns_summary.total` 覆盖整个请求区间，有可用净值的单产品还改用净值差法，不能用来校验该年累计收益|
|`annual_risk.{year}.{frequency}_risk.total_geometric_excess_return`|区间几何超额收益率|number / null|随父级对象返回|`(1+R)/(1+B) - 1`|`R`、`B` 取同一超额窗口；见[指增起算](#index-enhanced-excess-start)|
|`annual_risk.{year}.{frequency}_risk.total_arithmetic_excess_return`|区间算术超额收益率|number / null|随父级对象返回|`R-B`|与逐期算术超额连乘不同；见[指增起算](#index-enhanced-excess-start)|
|`annual_risk.{year}.{frequency}_risk.total_annual_returns`|日频区间累计收益折算的年化收益率|number / null|随父级对象返回|所有频率统一引用 `(1+R_daily)^(D/n_daily) - 1`，`D=交易252/自然365`|—|
|`annual_risk.{year}.{frequency}_risk.annual_simple_interest`|日频区间累计收益折算的单利年化收益率|number / null|随父级对象返回|所有频率统一引用 `R_daily/n_daily*S`，`S=交易250/自然365`|—|
|`annual_risk.{year}.{frequency}_risk.calmar_ratio`|卡马尔比率|number / null|随父级对象返回|上述日频期间年化收益除该频率 `max_drawdown`|期间年化收益相对最大回撤；零回撤时不能理解为可确定的无限回报|
|`annual_risk.{year}.{frequency}_risk.dividend_ratio`|股票分红率|number / null|随父级对象返回|请求年份范围内 `sum(stock_dividend_amount)` / 该年范围最后自然日 `(cn_stock_market_value+hk_stock_market_value)`|不是平均股票市值，也不含产品分红。金额全为零时可能无结果；金额缺失或无效时可能提示估值未就绪，零分母为空值；来源 [stock_dividend_amount](../fields/balances.md#balancedailysummary) 与[股票市值字段](../fields/balances.md#balance-calculation)。|
|`annual_risk.{year}.{frequency}_risk.annual_twoside_turnover_rate`|年化双边换手率|number / null|随父级对象返回|同 returns_summary.annual_twoside_turnover_rate|复用整个请求区间值，不是按年独立重算|
|`returns_summary`|区间收益概览|object|extra_indicators 包含 returns_summary|含以下十个字段|需 extra_indicators 选择 returns_summary|
|`returns_summary.total`|区间累计收益|number / null|随父级对象返回|单产品有可用累计单位净值和单位净值时 `(AccNAV[期末] - AccNAV[起点]) / NAV[起点]`<br>&emsp;否则日收益连乘减 1|见[收益概览与风险统计](#收益概览与风险统计)|
|`returns_summary.this_week`|向前一周的滚动收益|number / null|随父级对象返回|从区间末日回看 1 周的滚动窗口|并非本自然周|
|`returns_summary.this_month`|向前一月的滚动收益|number / null|随父级对象返回|从区间末日回看 1 月的滚动窗口|并非本自然月|
|`returns_summary.this_quarter`|向前三月的滚动收益|number / null|随父级对象返回|从区间末日回看 3 月的滚动窗口|并非本自然季度|
|`returns_summary.this_year`|向前一年的滚动收益|number / null|随父级对象返回|从区间末日回看 1 年的滚动窗口|并非本自然年度|
|`returns_summary.annual`|复利年化收益率|number / null|随父级对象返回|(1+returns_summary.total)^(D/n_daily)−1；D=交易252/自然365|n_daily 为对齐后的基准日收益样本数|
|`returns_summary.annual_simple_interest`|单利年化收益率|number / null|随父级对象返回|returns_summary.total/n_daily×S；S=交易250/自然365|不采用风险频率的 F|
|`returns_summary.arithmetic_excess`|区间算术超额收益|number / null|随父级对象返回|`R_summary−B_daily`|`R_summary` 是超额窗口内按收益概览口径算的产品收益，`B_daily` 为同窗口基准日收益连乘减 1；命中[指增起算](#index-enhanced-excess-start)时，不能用原区间 `returns_summary.total` 代替|
|`returns_summary.geometric_excess`|区间几何超额收益|number / null|随父级对象返回|`(1+R_summary)/(1+B_daily)−1`|与算术超额使用同一窗口；基准增长倍数为零时无效；见[指增起算](#index-enhanced-excess-start)|
|`returns_summary.annual_twoside_turnover_rate`|年化双边换手率|number / null|随父级对象返回|`(sum(buy_amount)+sum(sell_amount))/mean(total_equity)/n*D`，`D=252/365`|买卖金额取[买入](../fields/balances.md#buy-amount)、[卖出](../fields/balances.md#sell-amount)，净资产取[total_equity](../fields/balances.md#total-equity)。空序列为空值；净资产缺口沿用之前值，交易日按日历对齐。零净资产时不能给出有效换手结论；缺失金额不应被理解为已确认无交易。|
|`asset_series`|产品表现序列|object|extra_indicators 包含 asset_series|daily/weekly/monthly → array（日期记录）|需 extra_indicators 选择同名区块|
|`asset_series.daily`|日频记录列表|array（object）|随 asset_series 返回|按日频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`asset_series.weekly`|周频记录列表|array（object）|随 asset_series 返回|按周频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`asset_series.monthly`|月频记录列表|array（object）|随 asset_series 返回|按月频排列的日期记录|不是“日期 → 值”映射；空序列为 []|
|`asset_series.{frequency}[].date`|业务日期|string|随父级记录返回|日频为样本日期；周/月频为实际周期末日|不假定为完整周/月；当日行不证明实时头寸已纳入，见[当日样本覆盖](#indicator-sample-coverage)|
|`asset_series.daily[].daily_returns`|日收益率|number / null|随父级记录返回|`r_daily`；净值差法或整理后的头寸报表 [daily_returns](../fields/balances.md#daily-returns)|见[输入整理与日历](#输入整理与日历)|
|`asset_series.daily[].period_net_value`|计算用净值|number / null|随父级记录返回|提供累计单位净值时取后向补齐的 [acc_unit_net_value](../fields/balances.md#acc-unit-net-value)；否则 cumprod(1+r_daily)|不是所有分支都等于单位净值|
|`asset_series.daily[].cumulative_returns`|累计收益率|number / null|随父级记录返回|提供累计单位净值时 (AccNAV[当日]−AccNAV[起点])/NAV[起点]；否则 cumprod(1+r_daily)−1|—|
|`asset_series.{frequency}[].unit_net_value`|单位净值|number / null|随父级记录返回|取整理后同日/周期末头寸报表 [unit_net_value](../fields/balances.md#unit-net-value)|保留缺失，不假定三种净值相同|
|`asset_series.{frequency}[].acc_unit_net_value`|累计单位净值|number / null|随父级记录返回|取整理后同日/周期末头寸报表 [acc_unit_net_value](../fields/balances.md#acc-unit-net-value)|保留缺失，不假定三种净值相同|
|`asset_series.{frequency}[].adjusted_net_value`|复权净值|number / null|随父级记录返回|日频提供累计单位净值时 cumprod(1+r_daily)；其他情况取头寸报表 [adjusted_net_value](../fields/balances.md#adjusted-net-value)，全缺时以连乘补算；周/月取周期末头寸报表值|保留缺失，不假定三种净值相同|
|`asset_series.{period_frequency}[].portfolio_returns`|周期收益率|number / null|随父级记录返回|周期净值差/期初单位净值；组或未提供累计单位净值时 prod(1+r_daily)−1|—|
|`asset_series.{period_frequency}[].cumulative_returns`|周期累计收益率|number / null|随父级记录返回|同频率 portfolio_returns 的 cumprod(1+r)−1|对有可用净值的单产品，周/月频连乘各周期收益（各用自身期初单位净值），而日频累计用整个区间的起点单位净值；需要复算时按各自公式取基点|
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
|`monthly_returns`|年/月/周收益明细|array（object）|extra_indicators 包含 monthly_returns|年份节点 children 为月份，月份 children 为周|年/月节点部分超额字段适用[指增起算](#index-enhanced-excess-start)，周节点不适用|
|`monthly_returns[]`|年收益记录|object|随父级数组返回|以下字段组成一个年节点|数组元素路径；[] 不是 JSON 键|
|`monthly_returns[].date`|年份|string|随父级记录返回|YYYY|结构标签|
|`monthly_returns[].portfolio_returns`|产品周期收益|number / null|随父级记录返回|单产品净值差/NAV[期初]；否则 prod(1+r_daily)−1|净值来源见下方字段链接|
|`monthly_returns[].benchmark_returns`|基准周期收益|number / null|随父级记录返回|prod(1+b_daily)−1|[基准来源](#external-inputs)，不是产品头寸|
|`monthly_returns[].arithmetic_excess_returns`|算术超额收益|number / null|随父级记录返回|同窗口产品收益减基准收益|见[指增起算](#index-enhanced-excess-start)；不能总用同节点返回的原区间收益复算|
|`monthly_returns[].geometric_excess_returns`|几何超额收益|number / null|随父级记录返回|同窗口产品增长倍数除以基准增长倍数再减 1|基准增长倍数为零时无效；见[指增起算](#index-enhanced-excess-start)|
|`monthly_returns[].unit_net_value`|期末单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [unit_net_value](../fields/balances.md#unit-net-value)|—|
|`monthly_returns[].acc_unit_net_value`|期末累计单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [acc_unit_net_value](../fields/balances.md#acc-unit-net-value)|—|
|`monthly_returns[].adjusted_net_value`|期末复权净值|number / null|随父级记录返回|期末头寸报表 [adjusted_net_value](../fields/balances.md#adjusted-net-value)|—|
|`monthly_returns[].children`|月份列表|array|随父级记录返回|所选年份内实际月份|月份节点的 children 是周列表|
|`monthly_returns[].children[]`|月收益记录|object|随父级数组返回|以下字段组成一个月节点|数组元素路径；[] 不是 JSON 键|
|`monthly_returns[].children[].date`|月份|string|随父级记录返回|YYYY-MM|结构标签|
|`monthly_returns[].children[].portfolio_returns`|产品周期收益|number / null|随父级记录返回|单产品净值差/NAV[期初]；否则 prod(1+r_daily)−1|净值来源见下方字段链接|
|`monthly_returns[].children[].benchmark_returns`|基准周期收益|number / null|随父级记录返回|prod(1+b_daily)−1|[基准来源](#external-inputs)，不是产品头寸|
|`monthly_returns[].children[].arithmetic_excess_returns`|算术超额收益|number / null|随父级记录返回|同窗口产品收益减基准收益|见[指增起算](#index-enhanced-excess-start)；不能总用同节点返回的原区间收益复算|
|`monthly_returns[].children[].geometric_excess_returns`|几何超额收益|number / null|随父级记录返回|同窗口产品增长倍数除以基准增长倍数再减 1|基准增长倍数为零时无效；见[指增起算](#index-enhanced-excess-start)|
|`monthly_returns[].children[].unit_net_value`|期末单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [unit_net_value](../fields/balances.md#unit-net-value)|—|
|`monthly_returns[].children[].acc_unit_net_value`|期末累计单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [acc_unit_net_value](../fields/balances.md#acc-unit-net-value)|—|
|`monthly_returns[].children[].adjusted_net_value`|期末复权净值|number / null|随父级记录返回|期末头寸报表 [adjusted_net_value](../fields/balances.md#adjusted-net-value)|—|
|`monthly_returns[].children[].end_date`|月内末个观测日|string|随父级记录返回|月样本最后日期|不保证自然月末|
|`monthly_returns[].children[].annual_excess_volatility`|月内超额波动率|number / null|随父级记录返回|月内日收益差 std(r_daily−b_daily)×sqrt(D)，D=交易252/自然365|样本标准差；用日频年化因子折算，不按月内天数折算，也不按月频 12 折算|
|`monthly_returns[].children[].children`|周列表|array|随父级记录返回|月份所含周收益记录|允许不完整周|
|`monthly_returns[].children[].children[]`|周收益记录|object|随父级数组返回|以下字段组成一个周节点|数组元素路径；[] 不是 JSON 键|
|`monthly_returns[].children[].children[].date`|月内周序号|integer|随父级记录返回|按产品日历划分的月内周编号|周按周日结束，跨月周依服务端归属|
|`monthly_returns[].children[].children[].portfolio_returns`|产品周期收益|number / null|随父级记录返回|单产品净值差/NAV[期初]；否则 prod(1+r_daily)−1|净值来源见下方字段链接|
|`monthly_returns[].children[].children[].benchmark_returns`|基准周期收益|number / null|随父级记录返回|prod(1+b_daily)−1|[基准来源](#external-inputs)，不是产品头寸|
|`monthly_returns[].children[].children[].arithmetic_excess_returns`|算术超额收益|number / null|随父级记录返回|portfolio_returns−benchmark_returns|使用同一频率的产品与基准收益|
|`monthly_returns[].children[].children[].geometric_excess_returns`|几何超额收益|number / null|随父级记录返回|(1+portfolio_returns)/(1+benchmark_returns)−1|基准增长倍数为零时无效|
|`monthly_returns[].children[].children[].unit_net_value`|期末单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [unit_net_value](../fields/balances.md#unit-net-value)|—|
|`monthly_returns[].children[].children[].acc_unit_net_value`|期末累计单位净值|number / null|单产品且累计净值与单位净值有效时返回|期末头寸报表 [acc_unit_net_value](../fields/balances.md#acc-unit-net-value)|—|
|`monthly_returns[].children[].children[].adjusted_net_value`|期末复权净值|number / null|随父级记录返回|期末头寸报表 [adjusted_net_value](../fields/balances.md#adjusted-net-value)|—|
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
|`leverage_ratio.{frequency}[].leverage_ratio`|资产杠杆倍数|number / null|随父级记录返回|total_assets/total_equity|分子取同日/周期末 [total_assets](../fields/balances.md#total-assets)，分母取 [total_equity](../fields/balances.md#total-equity)；零净资产时比值可能非有限|
|`leverage_ratio.{frequency}[].total_assets`|总资产|number / null|随父级记录返回|同日/周期末头寸报表 [total_assets](../fields/balances.md#total-assets)|字段定义与计算见[头寸字段字典](../fields/balances.md#balance-calculation)；零净资产时比值可能非有限|
|`leverage_ratio.{frequency}[].total_equity`|净资产|number / null|随父级记录返回|同日/周期末头寸报表 [total_equity](../fields/balances.md#total-equity)|字段定义与计算见头寸字段字典；零净资产时比值可能非有限|
|`max_drawdown`|绝对回撤详情|object|extra_indicators 包含 max_drawdown|产品累计增长曲线 C的高点、谷底和恢复时间|需 extra_indicators 选择同名项；并非风险表中的数值 max_drawdown|
|`max_drawdown.max_drawdown_period`|绝对最大回撤区间|string|随父级对象返回|同深度取最后谷底；前峰至谷底的日期和包含两端的样本日数|无回撤为“未出现回撤”；初始基点前峰按第一样本日标记；非单笔最大亏损|
|`max_drawdown.max_drawdown_recovery_days`|绝对回撤修复时长|string|随父级对象返回|谷底后首次不低于前峰的样本距离|标记交易日/自然日；未回撤、未修复、终止前未修复均保留原文，不转换成 0|
|`excess_max_drawdown`|几何超额回撤详情|object|extra_indicators 包含 excess_max_drawdown|产品/基准累计增长比值曲线的高点、谷底和恢复时间|需 extra_indicators 选择同名项；并非风险表中的数值 max_drawdown|
|`excess_max_drawdown.geometric_excess_max_drawdown_period`|几何超额最大回撤区间|string|随父级对象返回|同深度取最后谷底；前峰至谷底的日期和包含两端的样本日数|无回撤为“未出现回撤”；初始基点前峰按第一样本日标记；非单笔最大亏损|
|`excess_max_drawdown.geometric_excess_max_drawdown_recovery_days`|几何超额回撤修复时长|string|随父级对象返回|谷底后首次不低于前峰的样本距离|标记交易日/自然日；未回撤、未修复、终止前未修复均保留原文，不转换成 0|
|`ashares_market_value`|沪深市值|object|extra_indicators 包含 ashares_market_value|末个可用沪深股票市值及 T-20 至 T-1 均值|需 extra_indicators 选择同名项；T 为请求截止日|
|`ashares_market_value.sh_market_value`|沪市股票市值|number|随父级对象返回|最后可用头寸报表 cn_sh_stock_market_value|[股票市值](../fields/balances.md#balance-calculation)|
|`ashares_market_value.sh_market_value_prev`|沪市前20日平均市值|number|随父级对象返回|T-20 至 T-1 的 cn_sh_stock_market_value 合计/20|交易所交易日回看；缺日仍除 20，不是最近20条记录均值|
|`ashares_market_value.sz_market_value`|深市股票市值|number|随父级对象返回|最后可用头寸报表 cn_sz_stock_market_value|[股票市值](../fields/balances.md#balance-calculation)|
|`ashares_market_value.sz_market_value_prev`|深市前20日平均市值|number|随父级对象返回|T-20 至 T-1 的 cn_sz_stock_market_value 合计/20|交易所交易日回看；缺日仍除 20，不是最近20条记录均值|

#### 口径与异常值

alpha、beta、Sharpe、information_ratio 至少需 2 期；不足时不可作为有效比较结果。波动、下行风险和跟踪误差不足 2 期时返回的 `0` 不代表已观察到零波动。收益低于 -100%、基准净值为零或零分母等输入可产生非有限数值；若计算生成 `NaN` 或正负无穷并进入正常 JSON 响应，服务端将其编码为 `null`。`null` 不指明具体失败原因，也不同于无样本导致的缺键；不要补零或用于排名。

滚动收益 this_week/this_month/this_quarter/this_year 分别回看 1 周、1 月、3 月、1 年；提供累计单位净值时沿用区间末累计净值减窗口起点累计净值、除窗口起点单位净值，起点缺失时回退请求区间基点；其他情况对窗口日收益连乘减 1。并非自然周/月/季度/年度。

两种公开胜率操作都把零收益算赢，但采用的收益序列可能不同，不应直接拼接或宣称一致。若用户要求严格“正收益才算赢”，应先约定口径，不把默认胜率冒充该统计。

<a id="external-inputs"></a>

#### 数据来源与复算边界

##### 产品侧：AMS 头寸摘要

[头寸报表](../fields/balances.md#balance-calculation)提供净值和原始日收益，后者不一定等于整理后的指标日收益。杠杆取总资产和净资产；换手率取产品或组的[买入金额](../fields/balances.md#buy-amount)、[卖出金额](../fields/balances.md#sell-amount)及平均净资产；年度股票分红率取摘要里的[股票分红到账金额](../fields/balances.md#balancedailysummary)和各年区间末的股票市值；沪深市值取摘要中的沪深股票市值，RQData 交易日历只用于选取 T−20 至 T−1 的窗口。计算和缺值规则仍见各字段行。

[行情、汇率和公司行动](../fields/balances.md#position-inputs)，以及人工公允价、托管及份额事件、组权重和[估值表覆盖](../reconciliation.md#valuation-report-overwrite)，是**形成头寸摘要的上游输入**。例如年度股票分红率不直接用 RQData 公告分红重算，换手率也不用指数成交额或简单汇总原始流水来替代。

##### 统计侧：基准、日历和无风险利率

|输入|来源及用法|
|---|---|
|指数基准收益与成交额|[RQData `get_price`](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi) 取 `frequency="1d"`、`adjust_type="pre"` 的 `close`、`total_turnover`，向前多取一个交易日作为首日比较基点；收盘点位按日历前向填充后取涨跌幅。缺当日日线时可从可用的[行情快照](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot)补入当日点位及成交额。周/月成交额按日金额求和，不取均值或年化。|
|国债与固定收益基准|国债基准用 [RQData `get_yield_curve`](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_yield_curve) 的 `1Y` 曲线，按日期对齐并沿用前值；固定收益基准用[自定义基准配置](../market_data.md#customized_benchmarks)的年化 `rates`。两者按 `(1+年利率)^(1/D) − 1` 日化，交易日口径 `D=252`、自然日口径 `D=365`，不提供市场成交额。|
|复合基准|成分和生效权重取自 AMS [自定义基准配置](../market_data.md#customized_benchmarks)，不是产品持仓比例，也不是 RQData 的指数成分权重。服务端对配置成分取前复权行情，按生效时段加权日收益；支持时也加权成交额。缺价可前后填充；特殊债券成分不参与该成分行情计算，包含它们的时段不提供基准成交额。|
|交易日历|按产品或组所设日历确定指标样本日期；交易日口径的日期及回看基点依赖 [RQData `get_trading_dates`](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates) 和 [`get_previous_trading_date`](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_previous_trading_date)。这与单产品区间前一自然日的净值基点不是一回事。|
|无风险利率 `f`|取 [RQData `get_yield_curve`](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_yield_curve) 的中债国债曲线，剔除含缺值的期限列，按区间自然日跨度选不超过该跨度的可用期限，取该列首个观测值；不是固定用国债基准的 `1Y`。曲线为空才按 `0`；非空但无可选期限时尝试取 `0S`，列缺失会报错，不能自行按 `0` 复算。|

**复核指标和追溯估值是两件事。** 先固定对象、区间、日历和实际基准，保存请求、回执、用于复核的头寸摘要及基点；对风险统计可按需取得 `asset_series`、`benchmark_series` 交叉核对。复算依赖利率的指标还要知道当时使用的 `f`，或从当时的曲线按同口径还原。基准收益也可能因缺行情而补 `0`，`indicators` 不返回逐成分缺行情告警；仅凭回执不能证明行情完整。只有要解释头寸摘要为什么不同，才继续沿头寸字段追溯行情、事件、估值覆盖等输入。缺基点、原始行情或配置时，列明复算缺口，不用当前数据或自定口径替代。

##### 本页其他操作的输入

以下基差、标的指数贡献用于 [`long_short_returns`](#long_short_returns)，申赎字段用于 [`series`](#series)，不是 `indicators` 的计算输入。

|英文字段|中文名称|实际计算|备注|
|---|---|---|---|
|`basis_returns`|基差变化收益贡献外部输入|[RQData futures.get_basis](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)(fields=['settle_basis','open','index'])；其 index 指定标的再取 [get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)(fields=['close','open'])；[instruments](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments).contract_multiplier|`settle_basis` 为结算基差；开盘基差=期货 open-指数 open。需要日期和合约对应关系，不能仅凭一张 positions 表复算，另有上文跨合约 shift 限制|
|`underlying_returns`|对应标的指数变化贡献外部输入|[RQData futures.get_basis](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)(fields=['settle_basis','open','index'])；其 index 指定标的再取 [get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)(fields=['close','open'])；[instruments](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments).contract_multiplier|`settle_basis` 为结算基差；开盘基差=期货 open-指数 open。需要日期和合约对应关系，不能仅凭一张 positions 表复算，另有上文跨合约 shift 限制|
|`subscription_amount`|申购/投入金额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](../custodian_events.md)、[unit_events](../unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|
|`redemption_amount`|赎回/撤出金额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](../custodian_events.md)、[unit_events](../unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|
|`subscription_units`|申购份额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](../custodian_events.md)、[unit_events](../unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|
|`redemption_units`|赎回份额|见[四项申赎字段](#series-inputs)，直接汇总事件和现金类流水|不是投资收益，不需要靠证券行情计算；托管事件与份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询（见 [custodian_events](../custodian_events.md)、[unit_events](../unit_events.md)），但不能宣称单靠公开 API 已取得全部源记录|

外部输入表不是 API 返回字段列表；托管/份额事件可分别由 `custodian_events.list` 与 `unit_events.list` 查询。


结果检查：区分 daily_risk、weekly_risk、monthly_risk 及所选 extra_indicators 的数据形状。空组或无有效交易日会失败；字段缺失或 null 时不能宣称该项风险为零，需核对日期、历史头寸报表与基准行情。返回空对象时按[未就绪与缺输入](../connection.md#unready-inputs)区分「估值未就绪」与「缺基准/输入」。

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
|`indicators`|`list[str] \| None`|`None`|指标名数组；省略或编码后查询值为空时使用下表全部指标，`[]` 和 `[""]` 都编码为空值。|

<a id="series-inputs"></a>

### 返回字段与计算公式

返回 `{指标名: {日期字符串: 数值}}`，下表 `{date}` 为实际日期键；`weekly_pnl` 例外为树形数组。以下是全部 19 个可选指标，不是滚动 Sharpe 或滚动风险序列。查询值非空时，服务端按逗号拆分，只保留精确匹配的指标名；重复名称合并，未知名称直接忽略，没有任何已知名称时返回 `{}`。先用下表核对请求名称，再判断所需序列是否返回，不把缺键当作缺估值或数值为 0。

|英文字段|中文名称|JSON 类型|计算公式|备注|
|---|---|---|---|---|
|`unit_net_value.{date}`|单位净值|number / null|同日头寸报表 [unit_net_value](../fields/balances.md#unit-net-value)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`acc_unit_net_value.{date}`|累计单位净值|number / null|同日头寸报表 [acc_unit_net_value](../fields/balances.md#acc-unit-net-value)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`adjusted_net_value.{date}`|复权净值|number / null|同日头寸报表 [adjusted_net_value](../fields/balances.md#adjusted-net-value)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`total_assets.{date}`|总资产|number / null|同日头寸报表 [total_assets](../fields/balances.md#total-assets)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`total_equity.{date}`|净资产|number / null|同日头寸报表 [total_equity](../fields/balances.md#total-equity)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`daily_pnl.{date}`|当日盈亏|number / null|同日头寸报表 [daily_pnl](../fields/balances.md#daily-pnl)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`equity_net_exposure.{date}`|权益净敞口|number / null|同日头寸报表 [equity_net_exposure](../fields/balances.md#equity-net-exposure)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`cash.{date}`|现金|number / null|同日头寸报表 [cash](../fields/balances.md#cash)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`net_cash_in.{date}`|净出入金|number / null|同日头寸报表 [net_cash_in](../fields/balances.md#net-cash-in)|按产品日历对齐；缺值不能解释为零。字段定义、计算与精度见链接目标。|
|`buy_amount.{date}`|买入金额|number / null|`stock_buy_amount+bond_buy_amount+fund_buy_amount`；分项筛选和逐笔口径见[头寸报表 buy_amount](../fields/balances.md#buy-amount)|重新合计三类流水分项；不采用估值表覆盖后的倒推金额，覆盖后可不同于同日头寸 `buy_amount`。|
|`sell_amount.{date}`|卖出金额|number / null|`stock_sell_amount+bond_sell_amount+fund_sell_amount`；分项筛选和逐笔口径见[头寸报表 sell_amount](../fields/balances.md#sell-amount)|重新合计三类流水分项；不采用估值表覆盖后的倒推金额，覆盖后可不同于同日头寸 `sell_amount`。|
|`risk_exposure.{date}`|风险资产总敞口|number / null|[total_risk_market_value](../fields/balances.md#total-risk-market-value) / [total_equity](../fields/balances.md#total-equity)|各项取同日头寸报表；风险敞口是比例，不是风险市值；零分母遵循服务端 safe_div。|
|`net_risk_exposure.{date}`|风险资产净敞口|number / null|[net_risk_market_value](../fields/balances.md#net-risk-market-value) / [total_equity](../fields/balances.md#total-equity)|各项取同日头寸报表；风险敞口是比例，不是风险市值；零分母遵循服务端 safe_div。|
|`leverage_ratio.{date}`|资产杠杆倍数|number / null|[total_assets](../fields/balances.md#total-assets) / [total_equity](../fields/balances.md#total-equity)|各项取同日头寸报表；资产与净资产使用同一估值币种，零分母遵循服务端 safe_div。|
|`subscription_amount.{date}`|申购/投入金额|number / null|同日 `subscription_fund_received.amount + cash_in.settlement_amount + 托管划入 quantity×price-commission-tax-other_fees`|金额；[流水](../fields/trades.md)、[份额事件来源](../fields/balances.md#balance-inputs)。|
|`redemption_amount.{date}`|赎回/撤出金额|number / null|同日 `redemption_paid.amount + cash_out.settlement_amount + 托管划出 quantity×price-commission-tax-other_fees`|金额；[流水](../fields/trades.md)、[份额事件来源](../fields/balances.md#balance-inputs)。|
|`subscription_units.{date}`|申购份额|number / null|手工及自动份额事件 `subscription_units` 按事件日期求和|份；[流水](../fields/trades.md)、[份额事件来源](../fields/balances.md#balance-inputs)。|
|`redemption_units.{date}`|赎回份额|number / null|手工及自动份额事件 `redemption_units` 按事件日期求和|份；[流水](../fields/trades.md)、[份额事件来源](../fields/balances.md#balance-inputs)。|
|`weekly_pnl`|周盈亏树|array（object）|按年→月→周对头寸报表 [daily_pnl](../fields/balances.md#daily-pnl) 求和|不采用收益率连乘|
|`weekly_pnl[].date`|年份|integer|年分组年份|子节点 date 分别为月份及该月内周序号|
|`weekly_pnl[].period_pnl`|年盈亏|number|该年内 daily_pnl 合计|仅请求区间内数据|
|`weekly_pnl[].children`|月份列表|array|年份内的月份分组|叶子周节点不含 children|
|`weekly_pnl[].children[].date`|月份|integer|月份 1–12|不是 YYYY-MM-DD|
|`weekly_pnl[].children[].period_pnl`|月盈亏|number|该月内 daily_pnl 合计|金额，不是收益率|
|`weekly_pnl[].children[].children`|周列表|array|该月内的周分组|按周日结束|
|`weekly_pnl[].children[].children[].date`|月内周序号|integer|月内按周日分组，从 1 编号|跨月周在各月内分组|
|`weekly_pnl[].children[].children[].period_pnl`|周盈亏|number|该月内该周 daily_pnl 合计|金额，不是收益率|

统计按流水 trading_date 和事件 date 汇总，不按股票除息日；金额分项在实际汇总中可补零，但最终缺日、权限不足或缺字段不能一律由客户端补零。份额事件的产生见[头寸报表输入](../fields/balances.md#balance-inputs)，源记录字段见[流水字段](../fields/trades.md)。产品组汇总成员记录，不是按投资权重缩放申赎金额。`weekly_pnl`（周盈亏）为周内 daily_pnl 金额相加，按年/月/周树输出，不是周收益率。

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
|`returns_series[].daily_returns`|产品日收益|number|单产品有累计净值时 AccNAV[当日]/AccNAV[上一估值日]−1；否则取头寸报表 [daily_returns](../fields/balances.md#daily-returns)|与 get 净值差法不同|
|`returns_series[].benchmark_returns`|基准日收益|number / null|资源已配置基准的同日收益 b_daily|[基准来源](#external-inputs)；该操作无 benchmark 参数|

单产品累计净值先后向补齐并按 AMS 精度舍入，起点取请求首日前一天累计净值，缺失或为零时取 1；日收益无效的行被剔除。无头寸摘要或无有效日收益时返回 `{}`；此时按[未就绪与缺输入](../connection.md#unready-inputs)区分估值未就绪与缺基准/输入。周/月周期收益：无累计净值的单产品取 `prod(1+日收益)−1`；其他分支取 `AccNAV[期末]/AccNAV[期初]−1`，产品组也依赖有效累计净值。周期基准收益为 `prod(1+b_daily)−1`。

两种公开胜率操作均将零收益算赢，但此处的累计净值比值法与 `indicators` 的净值差法不等价；不能因名称相同而拼接结果。无有效样本和基准缺失时不能宣称已完成统计。


结果检查：分别读取 daily_win_rate、weekly_win_rate、monthly_win_rate 和 returns_series；零收益算赢。与 indicators 的 win_rate 比较前先确认算法与样本区间相同，不能直接用同名字段断定结果不一致。

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

返回：服务端任务终态 JSON（`status`、`progress`、`data`、`message`，见[任务终态 JSON](../connection.md#task-result)），拆解结果在 `data` 内；失败或超时抛 HarnessError。下表路径相对任务结果数据，仅列成功任务的业务结果，任务状态不是收益指标。

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
|`{return_node}.portfolio_returns`|本拆解返回的产品收益|number / null|日频取头寸报表 [daily_returns](../fields/balances.md#daily-returns)<br>&emsp;周期有累计净值时为 `AccNAV[期末] / AccNAV[期初] - 1`<br>&emsp;无净值时为增长倍数 `prod(1+r)`，不减 1|不能直接与 `analytics.indicators` 的区间收益比较；{return_node} 为序列记录或年/月/周树节点。|

日盈亏取 [positions[].daily_pnl](../fields/balances.md#position)，数量取 [positions[].quantity](../fields/balances.md#position)，多空与品种筛选取同仓 direction/asset_class；分母取当日 [total_equity](../fields/balances.md#total-equity)，不取持仓成本或昨日权益。期货合约乘数及指数、[基差](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)来源见[外部输入](#external-inputs)。


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
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](../connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](../connection.md#download-result)|

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

