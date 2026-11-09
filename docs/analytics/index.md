# 净值与收益指标、持仓分析、业绩归因与组合对比 analytics

指标是从不同角度衡量投资表现的一组数值：既可以看一段时间赚了多少，也可以看价值波动多大、曾经跌了多少，以及是否跑赢选定的比较对象。同名指标可能有不同算法，解读时应使用这里明确的计算口径，而不是只按名称猜测。

分析类操作回答“这段时间赚在哪、暴露在哪、同行之间差在哪”。它们都以产品估值结果为输入，再叠加持仓明细、分类标准、基准和行情；因此结论可能晚于估值就绪，也必须连同区间、基准和分类口径一起交付。

指标不是独立业务对象；完整字段列表直接列在各操作的返回说明中：[indicators](metrics.md#indicators-returns)、[series](metrics.md#series-inputs)、[win_rate](metrics.md#win-rate-returns)、[long_short_returns](metrics.md#long-short-returns-fields)；指标时序还可以用 [`download_series_file`](metrics.md#download_series_file) 导出为工作簿。公式中的业务对象继续引用[头寸字段字典](../fields/balances.md)。

分析结果不是新的估值数据，不能反向当作持仓或净值来源；区间内缺少头寸报表、行情或基准时，应报告缺口，而不是补零或缩小口径后宣称完成。字段级定义继续引用[头寸字段字典](../fields/balances.md)，指标口径引用[指标返回字段与公式](metrics.md#indicators-returns)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。

[收益异常定位案例](../demo/returns-diagnosis/README.md)展示如何从具体指标与比较依据出发，对齐区间和基点，再沿头寸历史与原始业务输入追因；不把归因结果或行情涨跌直接当作收益核验结论。

[单产品综合分析案例](../demo/product-briefing/README.md)从“截至今天的净值、前十大持仓、行业、风格、主要风险及昨日变化”出发，说明怎样选择指标、复用头寸、组织独立查询，并判断哪些结果能够比较。

## 页面划分

本页是 `analytics` 块的入口页：跨族场景表与接口公共约定留在本页，操作细节按主题分成四页。

|主题|页面|覆盖操作|
|---|---|---|
|净值与收益指标|[metrics.md](metrics.md)|indicators、series、win_rate、long_short_returns、download_series_file|
|持仓分析|[holdings_analysis.md](holdings_analysis.md)|asset_weight、equity_holdings、convertible_holdings、convertible_positions、futures_holdings、option_holdings、holdings_summary_file|
|业绩归因|[attribution.md](attribution.md)|create_attribution、attribution、delete_attribution、export_attribution、realtime_risk_attribution、realtime_factor_exposure|
|组合对比与交易分析|[portfolio_analysis.md](portfolio_analysis.md)|group_indicators、group_returns、group_capital_size、group_allocation、group_returns_correlation、group_excess_correlation、group_overview_file、weekly_report、weekly_net_value_report、trading_analysis、single_trading_analysis、algo_trading_performance|

## 从用户需求到操作

|用户需求|API 与输入准备|完成条件|
|---|---|---|
|今天净值多少，今天或一段时间赚了多少|当前净值、当日收益先读[头寸报表](../balances.md#get)；区间表现用 [indicators](metrics.md#indicators) 或 [series](metrics.md#series)；明确日历、起止日期与比较基准|净值和收益率分开；实际业务日期及区间覆盖已核验，不用净值环比或净资产变化率替代收益率|
|前十大持仓、行业分布及相对昨日变化|按[时间与口径](../demo/README.md#时间与口径)，优先遵循明确日期，否则参考产品日历确定昨日对照；两日完整[头寸](../balances.md#get)用于筛选、排序、聚合与差分；需要特定分类或服务端统计时再用 [asset_weight](holdings_analysis.md#asset_weight) 等持仓分析|明确实际比较日期、持仓范围、排序、行业标准和权重分母；比较完整集合而非只比较两份前十，缺字段不补零|
|当前是什么风格，历史风格怎样变化|当前用 [realtime_factor_exposure](attribution.md#realtime_factor_exposure)；历史用已知 ID 的 [attribution](attribution.md#attribution)，没有现成结果且需新建时另按 [create_attribution](attribution.md#create_attribution) 的授权与输入要求处理|当前结果有实际时点；历史比较对齐模板、基准、权重和底层暴露日期，不以日期标签相同直接相减；暴露不等于贡献|
|主要风险在哪里，是否偏离基准|持仓判断集中度、行业和实际多空敞口；[indicators](metrics.md#indicators) 按问题选择波动、回撤、跟踪误差或超额回撤；有风险分解需求时再用归因|区分绝对风险与相对基准风险；区间、频率及有效样本清楚；不把缺结果当作无风险，不凭指标自行设违规阈值|
|今天收益由哪些行业或因子贡献|[realtime_risk_attribution](attribution.md#realtime_risk_attribution)，核对当日可计算性、基准及分类|当日归因已就绪，贡献与暴露、常规风险指标分开解释；非交易日空结果不是零贡献|
|做历史某日或区间业绩归因|已有 ID 直接 [attribution](attribution.md#attribution)；需新建时 `create_attribution` 提交后读同一 ID；归档才 [export_attribution](attribution.md#export_attribution)|归因终态成功，产品、区间、基准和模板对应；新建持久化分析有授权，不为普通查询默认创建|
|产品收益为什么与预期不同|先按[收益异常定位](../demo/returns-diagnosis/README.md)核对区间、基点、净值、份额、分红和数据源，再按证据追历史输入；需分析收益来源时再选归因|观察、候选解释与凭证支持的根因分开；有归因结果不代表原始输入真实完整|
|多个产品或组合谁表现好、配置有何不同|按 [组合对比](portfolio_analysis.md#组合对比) 选择组级表现、配置及相关性，固定成员和区间|按组级契约解释结果，不与单产品指标混作同一口径；成员及实际日期覆盖清楚|

先用头寸报表时序核对所需历史数据是否齐备，再计算指标。不同方法的缺省日期不同；跨方法比较时显式对齐 start_date/end_date，避免把区间差异误判为计算差异。

计算类操作可能耗时较久；等待超时不代表任务取消——先确认原请求结果，不要直接重放提交。组合对比只提供一套组级口径，避免同一需求出现两套并行结果。

## API 使用约定

Python 与 CLI 完成相同调用，连接、任务等待与公共错误处理见[连接说明](../connection.md)。`resource` 为产品或产品组的唯一 ID 或名称；`resources` 为非空数组，重复项会被去重，顺序保留。可选参数为 `None` 时不下发；数组型选择器可直接传逗号串，也可传数组。

做区间对比时显式指定日期、基准及指标集合，并记录实际返回中的缺失值。

- 调用是阻塞式的：Harness 内部完成等待与重试，最终返回服务端 JSON、文件元数据，或在达到等待上限时抛 `wait_timeout`；具体规则见[连接说明](../connection.md)。
- **分析类**操作在返回说明里给出返回顶层结构与已核实的键，键内元素随服务端分析结果；净值与收益指标操作的字段与公式完整列在各自返回说明中。交付前先看实际键，不要按名称推断未列出的键。

用户只说“主要风险”“表现怎么样”时，先结合实际配置和业务目的选择少量相关指标，并说明选择理由、区间与基准。例如指增产品既看自身波动、回撤，也看相对基准的跟踪误差、超额回撤；不默认把全部指标都搬进摘要。口径确实会改变结论时，明确并列必要的比较口径或集中澄清，不擅自混算；用户已指定指标或口径时按原请求处理。字段名、公式及无效样本规则以对应子页为准，不能按常见金融定义替换 AMS 的实际口径。
