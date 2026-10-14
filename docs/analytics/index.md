# 净值与收益指标、持仓分析、业绩归因与组合对比 analytics

指标是从不同角度衡量投资表现的一组数值：既可以看一段时间赚了多少，也可以看价值波动多大、曾经跌了多少，以及是否跑赢选定的比较对象。同名指标可能有不同算法，解读时应使用这里明确的计算口径，而不是只按名称猜测。

分析类操作回答“这段时间赚在哪、暴露在哪、同行之间差在哪”。它们都以产品估值结果为输入，再叠加持仓明细、分类标准、基准和行情；因此结论可能晚于估值就绪，也必须连同区间、基准和分类口径一起交付。

指标不是独立业务对象；完整字段列表直接列在各操作的返回说明中：[indicators](metrics.md#indicators-returns)、[series](metrics.md#series-inputs)、[win_rate](metrics.md#win-rate-returns)、[long_short_returns](metrics.md#long-short-returns-fields)；指标时序还可以用 [`download_series_file`](metrics.md#download_series_file) 导出为工作簿。公式中的业务对象继续引用[头寸字段字典](../fields/balances.md)。

分析结果不是新的估值数据，不能反向当作持仓或净值来源；区间内缺少头寸报表、行情或基准时，应报告缺口，而不是补零或缩小口径后宣称完成。字段级定义继续引用[头寸字段字典](../fields/balances.md)，指标口径引用[指标返回字段与公式](metrics.md#indicators-returns)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。

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
|比较区间收益、波动或回撤|`indicators`，明确日期和 benchmark，按需选择 extra_indicators|所需风险区块和额外指标可用，并注明日历、基准和有效区间|
|绘制或导出指标曲线|`series`，显式给区间和 indicators|按字段→日期→值解析；日期覆盖及缺失值已检查，不能把序列当作滚动风险统计|
|分析日/周/月胜率|`win_rate`，统一目标区间|同时核对各频率胜率与 returns_series，注明此方法和 indicators 中胜率口径不同|
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

Python 与 CLI 完成相同调用，连接、任务等待与公共错误处理见[连接说明](../connection.md)。`resource` 为产品或产品组的唯一 ID 或名称；`resources` 为非空数组，重复项会被去重，顺序保留。可选参数为 `None` 时不下发；数组型选择器可直接传逗号串，也可传数组。

做区间对比时显式指定日期、基准及指标集合，并记录实际返回中的缺失值。

- 调用是阻塞式的：Harness 内部完成等待与重试，最终返回服务端 JSON、文件元数据，或在达到等待上限时抛 `wait_timeout`；具体规则见[连接说明](../connection.md)。
- **分析类**操作在返回说明里给出返回顶层结构与已核实的键，键内元素随服务端分析结果；净值与收益指标操作的字段与公式完整列在各自返回说明中。交付前先看实际键，不要按名称推断未列出的键。

用户需求没说到具体指标或口径时，把可能相关的口径尽量都并列取出（如几何超额与算术超额、最大回撤与几何超额回撤），逐项标注口径名与区间，不替用户选择；用户明确指定口径时才只给该口径。
