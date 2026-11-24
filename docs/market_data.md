# 市场数据与基准 market_data

本块提供估值与分析之外的**外部参照数据**：[内置基准](https://www.ricequant.com/doc/rqdata/python/indices-mod#rqdata-API-indices_list)及其收益序列、自定义基准的维护、[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)、[标的检索](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)与[实时行情快照](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot)。

这些数据不参与产品估值：它们是判断“跑赢没有”“今天能不能交易”“这只代码到底是谁”的依据。等待与超时规则见[连接说明](connection.md)。基准收益序列用于比较业绩，交易日历用于对齐区间，标的检索用于把名称或拼音换成代码，实时快照只反映最近一笔行情。产品自身的收益与风险口径见[净值与收益指标](analytics/metrics.md#indicators-returns)，分析类视图见[持仓分析、业绩归因与组合对比](analytics/portfolio_analysis.md#组合对比)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。


## API 使用约定

Python 与 CLI 完成相同调用，连接与公共错误处理见[连接说明](connection.md)。基准目录与自定义基准列表只列出当前工作空间可见的自定义基准；查询分时收益时从 [`benchmarks`](#benchmarks) 选择已确认的基准 ID。

- `benchmark_returns` 的 `include_customized` 只在为 `true` 时下发：服务端按字符串真值判断该参数，下发 `false` 会被当作真，从而把自定义基准混进结果，因此 Harness 省略该参数来表达“不含自定义基准”。
- `benchmark_returns` 的 `start_date` 省略时服务端从 2020-01-01 起算，`end_date` 省略时算到今天；需要精确区间时显式给出。
- 基准代码数组（`benchmark_ids`、`order_book_ids`）可传逗号串或数组；空串与空数组会被本地拒绝。
- `benchmark_ids` 只写基准代码本身（如 `000300.XSHG`），**不要**写成[净值收益指标](analytics/metrics.md)基准参数的「类型,代码」形式。
- 自定义基准是写入操作：`create` 与 `update` 都会整体替换权重，`update` 是全量覆盖而不是局部合并；删除按基准 ID 执行。
- 日历与行情取自外部数据源缓存，查询本身不改变任何产品数据。

## benchmark_returns
取基准区间收益序列；基准行情取自 [合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)。
- benchmark_returns：省略基准时返回服务端支持的全部内置基准；`include_customized=True` 时追加当前工作空间的自定义基准。

Python 签名：`rqamsh.market_data.benchmark_returns(*, benchmark_ids: str | list[str] | None=None, start_date: str | None=None, end_date: str | None=None, calendar_type: str='natural', include_customized: bool=False)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`benchmark_ids`|`str \| list[str] \| None`|`None`|基准代码或代码数组；省略时不筛选。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略时服务端从 2020-01-01 起算。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略时服务端算到今天。|
|`calendar_type`|`str`|`natural`|日历口径。|
|`include_customized`|`bool`|`False`|为真时下发该参数，结果包含自定义基准；为假时不下发。|

返回：数组，每个基准一项 `{"order_book_id": …, "returns": [...]}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|基准收益序列|array（object 元素）|—|每个基准一项，键为 `order_book_id`（string）与 `returns`（逐日收益数组）|恒返回；省略基准时为服务端支持的全部内置基准，`include_customized=True` 时追加当前工作空间的自定义基准|
|`[].returns`|逐日收益|array（object 元素）|—|元素 `trading_date`（YYYY-MM-DD）、`daily_returns`（number，日收益）、`cumulative_returns`（number，累计收益）|恒返回；日期按日历补齐，无行情的日期沿用前值、收益记为 `0`，不能按 `0` 判断区间无数据；`cumulative_returns` 以请求区间首日为[基准累计起点](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_previous_trading_date)连乘|

## realtime_benchmark_returns
取基准当日分时收益。
- `realtime_benchmark_returns` 一次查询一个基准；先用 [`benchmarks`](#benchmarks) 确认代码，再显式传入。

Python 签名：`rqamsh.market_data.realtime_benchmark_returns(*, benchmark_id: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`benchmark_id`|`str \| None`|调用时指定|单个基准代码，例如 `000300.XSHG`。省略或传 `None` 都不发送该参数。|

**省略参数的当前实现偏差：** 省略不会像旧版说明所述那样返回全部内置基准。服务端只实现单基准查询，缺少 ID 时进入自定义基准查找并报未找到（HTTP 404），不是空行情结果。取多个基准时，先取目录，再逐个显式查询所需 ID。

返回：分钟级收益数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|分钟收益|array（object 元素）|—|每行 `datetime`（分钟时间）与 `minute_return`（number，分钟收益率）|查询成功时返回；内置指数缺分时行情或上一结算日收盘价时为空数组，不能当零收益|

`minute_return` 的口径随基准类型：内置指数为相对上一结算日收盘的收益率，复合基准按配置对成分的同口径收益加权。[国债类基准](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_yield_curve)与固定数值基准按年化收益率折算为固定日收益。复合基准只纳入同时取得分时行情和上一结算日收盘价的成分，不重新归一权重；不能仅凭非空结果认定所有成分均已覆盖。

## benchmarks
列出当前空间可用的内置与自定义基准。
- benchmarks：返回当前工作空间可见的基准信息，用于确认可用的基准 ID。

Python 签名：`rqamsh.market_data.benchmarks()`。

返回：基准描述数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|基准描述|array（object 元素）|—|每个基准一项，键为 `id`（内置基准为基准代码、自定义基准为记录 ID）、`type`（`index`、`yield_rate` 或 `customized_index`）、`name`（string）与起始日期|恒返回；含当前工作空间可见的自定义基准|

元素只用于取得基准 ID（如沪深300 对应 `000300.XSHG`，见[指数列表](https://www.ricequant.com/doc/rqdata/python/indices-mod#rqdata-API-indices_list)）；把它当唯一来源，不要用文档或经验猜基准代码。

## customized_benchmarks
列出当前工作空间的自定义基准。

Python 签名：`rqamsh.market_data.customized_benchmarks()`。

返回：自定义基准数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|自定义基准|array（object 元素）|—|每项键为 `id`、`name`、`type`（`composite` 或 `fixed_rates`）、`remarks`、`rates`（number，固定数值基准的年化收益率）、`weights`（复合基准的权重块数组）、`user_id`（integer）与 `workspace_id`（string）|恒返回；只含当前工作空间的自定义基准|
|`[].weights`|权重块|array（object 元素）|—|元素 `start_date`（YYYY-MM-DD，权重生效日）、`weights`（成分数组，元素含 `order_book_id` 与 `weight`）以及权重记录自身的 `customized_benchmark_id`、`id`|由数据决定；只有复合基准才有该键，固定数值基准读 `rates`|

## create_customized_benchmark
新建自定义基准。
- create_customized_benchmark：类型决定必填载荷；复合基准必须给权重，固定数值必须给非负收益率。

Python 签名：`rqamsh.market_data.create_customized_benchmark(name: str, type: str, *, remarks: str | None=None, weights: list[dict[str, Any]] | None=None, rates: float | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`name`|`str`|必填|基准名称，非空。|
|`type`|`str`|必填|`composite`（复合基准）或 `fixed_rates`（固定数值基准）。|
|`remarks`|`str \| None`|`None`|备注；省略时不下发。|
|`weights`|`list[dict[str, Any]] \| None`|`None`|复合基准的权重块数组，必须非空。|
|`rates`|`float \| None`|`None`|固定数值基准的收益率，必须为非负数值。|

**创建推荐：** 未指定类型时以 `composite` 为起点，但成分、权重和生效日期必须按业务补齐，不能提交空权重。无备注时省略 `remarks`，不要传空字符串（SDK 会拒绝）；明确需要 `fixed_rates` 时可采用 `rates=0` 作为零收益基准，其他年化收益率按实际填写。SDK 不自动补类型或收益率。权重和收益率均传小数：`50%` 权重传 `0.5`，`3%` 年化收益率传 `0.03`；类型切换后只提交对应的 `weights` 或 `rates`，不把示例比例当默认投资配置。

服务端在 Harness 的结构校验之外还有语义校验，失败会明确报错：

- 每个权重块至少包含一个成分，成分需含 `order_book_id` 与数值 `weight`；成分代码必须是可识别的标的。
- 同一基准内权重块的 `start_date` 不能重复；省略时服务端按已有权重的最早起始日或最小值填充。
- 单个权重块的成分权重之和必须为 1（容差到小数点后 6 位）。

返回：服务端原始创建结果 `{"inserted_id": …}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`inserted_id`|新建基准 ID|string|—|新建自定义基准的记录 ID|恒返回；键名即服务端原始字段 `inserted_id`，之后可用该 ID 或 `customized_benchmarks` 读回定义|

## update_customized_benchmark
整体覆盖自定义基准。
- update_customized_benchmark：与新建使用同一套校验，权重会被整体替换，未提交的旧权重不会保留。

Python 签名：`rqamsh.market_data.update_customized_benchmark(customized_benchmark_id: str, name: str, type: str, *, remarks: str | None=None, weights: list[dict[str, Any]] | None=None, rates: float | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`customized_benchmark_id`|`str`|必填|自定义基准 ID。|
|`name` / `type` / `remarks` / `weights` / `rates`|同上|同上|覆盖后的完整定义。|

返回：服务端原始结果 `{"modified": …}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`modified`|是否发生修改|boolean|—|本次覆盖是否改动或新增了定义（复合基准还会写入权重表，权重有增改同样为 `true`）|恒返回；`false` 表示提交的定义与现值一致|

覆盖会改变依赖该基准的比较口径，执行前确认影响范围。

## delete_customized_benchmark
删除自定义基准。

Python 签名：`rqamsh.market_data.delete_customized_benchmark(customized_benchmark_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`customized_benchmark_id`|`str`|必填|自定义基准 ID。|

返回：服务端原始结果 `{"deleted": …}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`deleted`|是否删除|boolean|—|本次是否删除了该自定义基准记录|恒返回；`false` 表示没有命中该 ID|

删除后引用该基准的历史比较结果不再可用，不能把它当作可回滚操作。

## trading_dates
取交易所[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)。
- trading_dates：只支持交易所日历；其他取值服务端会返回空数组，Harness 因此在本地拒绝，避免把空结果误读为「这段时间没有交易日」。

Python 签名：`rqamsh.market_data.trading_dates(type: str, *, start_date: str | None=None, end_date: str | None=None, fmt: str='date')`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`type`|`str`|必填|只接受 `exchange`；其他取值本地拒绝。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略时服务端从 2010-01-01 起算。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略时服务端算到最新交易日。|
|`fmt`|`str`|`date`|`date` 返回日期字符串，`timestamp` 返回时间戳。|

返回：区间内的交易日数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|交易日|array（string / integer 元素）|—|`fmt='date'` 时为日期字符串（YYYY-MM-DD），`fmt='timestamp'` 时为时间戳（integer）|恒返回；只含交易所日历、且落在请求区间内的日期，升序|

## instruments
检索标的；标的详情与到期日取自 [合约基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)，名称与拼音前缀匹配的全量清单见 [全部合约](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-all_instruments)。
- instruments：`q`、`asset_class`、`instrument_type` 至少要给一个，否则服务端直接拒绝；`limit` 为负数时返回匹配条件下的全量快照，不是「最后若干条」。

Python 签名：`rqamsh.market_data.instruments(*, q: str | None=None, asset_class: str | None=None, instrument_type: str | None=None, limit: int=20)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`q`|`str \| None`|`None`|关键词：中文走名称匹配，其他走代码或拼音前缀匹配。|
|`asset_class`|`str \| None`|`None`|资产类别过滤。|
|`instrument_type`|`str \| None`|`None`|标的类型过滤。|
|`limit`|`int`|`20`|返回条数上限；非负整数走普通检索（`0` 只返回空数组，超过 `10000` 被拒绝），负数表示返回匹配条件下的全量快照。|

返回：标的数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|标的|array（object 元素）|—|每个命中标的的 `order_book_id`（标的代码）、`symbol`（名称）、`abbrev_symbol`（简称）、`trading_asset_class`（资产类别）与 `instrument_type`（标的类型）|恒返回；服务端只返回这五个键；普通检索最多 `limit` 条，全量快照返回匹配条件下的全部标的，不再受 `10000` 限制|

某个检索条件的全量快照首次被请求时，服务端可能先返回 202 表示快照正在生成，客户端会自动重查同一读取直到取到快照或达到等待上限；202 不是错误，但全量结果的构建与传输明显更慢，能缩小 `q`、`asset_class` 或 `instrument_type` 时不要直接取全量。

检索是模糊匹配，命中的第一名不一定就是目标标的，写入前核对代码。

## realtime_quotes
取指定标的的[实时行情快照](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot)。
- realtime_quotes：代码以逗号串下发，数组会被序列化；空数组或空串本地拒绝。

Python 签名：`rqamsh.market_data.realtime_quotes(order_book_ids: str | list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`order_book_ids`|`str \| list[str]`|必填|非空标的代码或代码数组。|

返回：实时快照数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|行情快照|array（object 元素）|—|每个标的一项：`order_book_id`、`datetime`（快照时间）、`last`（number，最新价）、`change_value`（number，涨跌额）与 `change_rate`（number，涨跌幅）|恒返回；服务端只返回这五个键，停牌或未订阅的标的不出现在结果中|

快照来自行情缓存，间隔数秒可能重复；不能按返回条数判断标的有效性。

## index_futures_basis
取指数期货基差数据。
- index_futures_basis：默认同时取快照、分钟线与历史；`snapshot_indicators` 恒定返回，用于列出各品种及其合约。

各口径的外部来源：品种与合约列表取自 [期货合约列表](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_contracts)，指数期货基差快照取自 [期货当前基差](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_current_basis)，基差序列取自 [期货基差](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)，基差分红调整取自 [预测分红点数](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_predicted_dividend_point)，开盘基差口径取自 [实时逐笔成交](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_live_ticks)。

Python 签名：`rqamsh.market_data.index_futures_basis(*, dividend_adjusted: bool=False, fields: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`dividend_adjusted`|`bool`|`False`|`True` 使用分红调整口径，`False` 使用未调整口径；每次调用都显式下发，不接受 `None`。|
|`fields`|`str \| None`|`None`|`snapshot`、`minbar_series`、`history` 的组合；省略时服务端取三者全部。|

返回：对象，按 `fields` 分键给出基差数据；`snapshot_indicators` 恒定返回。客户端在对象结果中补 `dividend_adjusted`，明确本次结果使用的口径，不能把两种口径的基差当成同一序列。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`dividend_adjusted`|分红调整口径|boolean|—|`true` 为分红调整，`false` 为未调整|恒返回；由本次请求参数确定，回答时必须同时说明该口径|
|`snapshot_indicators`|品种与合约|array（object 元素）|—|每个品种一项：`order_book_id`（品种，如 `IF`）、`symbol`（品种名）与 `children`（合约数组，元素含 `order_book_id`；取过快照后每项另含 `date`、`current_basis`、`basis_annual_rate`、`maturity_dates`（number，距到期天数）、`acc_basis_diff`（number 或 null））|恒返回；盘前只有 `order_book_id`，用于渲染品种与合约列表|
|`history_basis_series`|历史基差序列|object|—|键为合约代码，值为该合约的记录数组（元素含 `date`（YYYY-MM-DD）、`basis`（number，结算价升贴水）、`basis_annual_rate`（number，年化升贴水率））|由参数选择；`fields` 含 `history` 时才返回|
|`minbar_series`|当日分钟线基差|object|—|键为合约代码，值为该合约的分钟记录数组（元素含 `date`、`basis`、`basis_annual_rate`），开盘第一个基差点排在最前|由参数选择；`fields` 含 `minbar_series` 时才返回，9:25 前不取|
