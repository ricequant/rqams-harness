# 净值与收益指标、持仓分析、业绩归因与组合对比 analytics

指标是从不同角度衡量投资表现的一组数值：既可以看一段时间赚了多少，也可以看价值波动多大、曾经跌了多少，以及是否跑赢选定的比较对象。同名指标可能有不同算法，解读时应使用这里明确的计算口径，而不是只按名称猜测。

分析类操作回答“这段时间赚在哪、暴露在哪、同行之间差在哪”。它们都以产品估值结果为输入，再叠加持仓明细、分类标准、基准和行情；因此结论可能晚于估值就绪，也必须连同区间、基准和分类口径一起交付。

指标不是独立业务对象；完整字段列表直接列在各操作的返回说明中：[indicators](metrics.md#indicators-returns)、[series](metrics.md#series-inputs)、[win_rate](metrics.md#win-rate-returns)、[long_short_returns](metrics.md#long-short-returns-fields)；指标时序还可以用 [`download_series_file`](metrics.md#download_series_file) 导出为工作簿。公式中的业务对象继续引用[头寸字段字典](../fields/balances.md)。

分析结果不是新的估值数据，不能反向当作持仓或净值来源；区间内缺少头寸报表、行情或基准时，应报告缺口，而不是补零或缩小口径后宣称完成。字段级定义继续引用[头寸字段字典](../fields/balances.md)，指标口径引用[指标返回字段与公式](metrics.md#indicators-returns)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。

[收益异常定位案例](../demo/returns-diagnosis/README.md)展示如何从具体指标与比较依据出发，对齐区间和基点，再沿头寸历史与原始业务输入追因；不把归因结果或行情涨跌直接当作收益核验结论。

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
|做区间业绩归因|`create_attribution` 提交计算 → `attribution` 轮询同一归因 ID → `export_attribution` 导出|任务终态成功；归因 ID 与区间、基准、分类标准一一对应|

先用头寸报表时序核对所需历史数据是否齐备，再计算指标。不同方法的缺省日期不同；跨方法比较时显式对齐 start_date/end_date，避免把区间差异误判为计算差异。

计算类操作可能耗时较久；等待超时不代表任务取消——先确认原请求结果，不要直接重放提交。组合对比只提供一套组级口径，避免同一需求出现两套并行结果。

## API 使用约定

Python 与 CLI 完成相同调用，连接、任务等待与公共错误处理见[连接说明](../connection.md)。`resource` 为产品或产品组的唯一 ID 或名称；`resources` 为非空数组，重复项会被去重，顺序保留。可选参数为 `None` 时不下发；数组型选择器可直接传逗号串，也可传数组。

做区间对比时显式指定日期、基准及指标集合，并记录实际返回中的缺失值。

- 调用是阻塞式的：Harness 内部完成等待与重试，最终返回服务端 JSON、文件元数据，或在达到等待上限时抛 `wait_timeout`；具体规则见[连接说明](../connection.md)。
- **分析类**操作在返回说明里给出返回顶层结构与已核实的键，键内元素随服务端分析结果；净值与收益指标操作的字段与公式完整列在各自返回说明中。交付前先看实际键，不要按名称推断未列出的键。

用户需求没说到具体指标或口径时，把可能相关的口径尽量都并列取出（如几何超额与算术超额、最大回撤与几何超额回撤），逐项标注口径名与区间，不替用户选择；用户明确指定口径时才只给该口径。
