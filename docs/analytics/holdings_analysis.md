# 持仓分析 analytics

下列操作读取服务端已算好的持仓、权重与暴露视图：权重按分类给出分布，各类资产给出逐券明细，汇总视图可导出工作簿。它们都以产品估值结果为输入，区间内没有对应资产类别的持仓时结果为空，不能当作「无风险」；字段与公式见[头寸字段字典](../fields/balances.md)。

本页是 [analytics 总览](index.md) 的子页：用户需求与完成条件见[总览的场景表](index.md#从用户需求到操作)，`resource`/`resources` 语义与阻塞式调用等公共约定见[总览](index.md#api-使用约定)；本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。

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

返回：服务端权重视图，含 `classifier_weight` 与 `trading_asset_class_weight_series` 两部分。若行业分类缓存正在构建，服务端会以「正在初始化」提示并要求稍后重试（带重试间隔），需由调用方识别该提示后稍后重试同一读取：这里是普通 200 业务响应，客户端不会自动重试，也不会取出该响应里的间隔去等待（重试间隔只在任务状态轮询时使用）；此时不会有数值返回，不要把它当成空权重。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|权重视图对象|object|—|服务端直接返回的权重视图，恒含 `classifier_weight` 与 `trading_asset_class_weight_series` 两部分|恒返回；行业分类缓存构建中时不返回数值，服务端以「正在初始化」提示要求稍后重试|
|`classifier_weight`|按分类的权重|array（object）|—|每个请求分类一项，元素含 `classifier` 与 `weight`|由参数选择；只对请求中给出的分类返回条目，不会扩展成全量分类|
|`classifier_weight[].classifier`|分类名|string|—|该项对应的分类取值|随父级记录返回|
|`classifier_weight[].weight`|该分类下的分组权重行|array（object）|—|元素含 `name`、`quantity`、`quantity_pct`、`market_value`、`weight`、`children`|随父级记录返回；无持仓或该分类无可用取值时为空数组|
|`classifier_weight[].weight[].name`|分组名|string|—|该分类取值下的分组名；`classifiers` 含 `trading_asset_class` 时是[交易资产属性](../fields/others.md#tradingassetclass) 的英文值|随父级记录返回|
|`classifier_weight[].weight[].quantity`|持仓数量合计|number|—|该分组持仓数量合计|随父级记录返回|
|`classifier_weight[].weight[].quantity_pct`|数量占比|number|小数|该分组数量占同一分类合计数量的比例|随父级记录返回|
|`classifier_weight[].weight[].market_value`|持仓市值合计|number|估值币种金额|该分组持仓市值合计|随父级记录返回|
|`classifier_weight[].weight[].weight`|市值权重|number|小数|该分组市值占同一报告市值合计的比例|随父级记录返回|
|`classifier_weight[].weight[].children`|分组内逐券明细|array（object）|—|元素含 `order_book_id`、`symbol`、`quantity`、`market_value`、`weight`|随父级记录返回；无明细时为空数组|
|`trading_asset_class_weight_series`|交易属性权重时序|object|—|恒含 `series_names` 与 `series` 两部分|恒返回|
|`trading_asset_class_weight_series.series_names`|序列中出现的交易属性名|array（string）|—|序列中出现过的[交易资产属性](../fields/others.md#tradingassetclass) 英文值|恒返回；无数据时为 `[]`|
|`trading_asset_class_weight_series.series`|逐日权重记录|array（object）|—|每个产品日历日一条，元素含 `date` 与各交易属性名键，值为该属性当日市值合计/同日净资产|恒返回；无数据时为 `[]`；不是“日期 → 值”映射|
|`trading_asset_class_weight_series.series[].date`|业务日期|string|—|该条记录对应的产品日历日|随父级记录返回|
|`trading_asset_class_weight_series.series[].{交易属性名}`|该交易属性当日权重|number|小数|该交易属性当日市值合计 / 同日净资产；键名是[交易资产属性](../fields/others.md#tradingassetclass) 的英文值|由数据决定；只对该日有持仓的属性出现，键名以 `series_names` 为准|

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
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
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
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
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
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
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
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
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
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；成功终态为 `1`|恒返回；见[任务终态 JSON](../connection.md#task-result)|
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
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；任务终态后才写入；见[下载元数据](../connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](../connection.md#download-result)|

交付检查：先确认 `template` 与区间对应的查询结果，再核对导出的新文件；落盘成功不证明区间内行情或头寸数据完整。

