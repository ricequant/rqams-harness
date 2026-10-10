# 风险监控与看板数据 risk_monitor

风险监控回答两类问题：**我配置了哪些预警条件**（条款的读写），以及**现在有哪些数据可用于判断风险**（实时预警、违规公告、两融、ETF 份额与折溢价、VIX、商誉占比）。

条款是需要维护的业务配置：录入错误的条件会持续产生或漏掉预警，因此写入前先确认目标产品/产品组、指标、比较方式、阈值、执行频率，以及 3 级及以上所需的 Webhook 地址。看板数据是外部行情与统计的只读镜像，不含调用方产品的估值口径，也不能用来替代[头寸报表](balances.md)、[净值与收益指标](analytics.md#indicators-returns)或[持仓分析](analytics.md#asset_weight)。

## 从用户需求到操作

|用户需求|API 与输入准备|完成条件|
|---|---|---|
|查看现有预警条款|`clauses`，按产品/产品组、日期区间或等级过滤|返回条款清单；每条带 `err_msg` 说明目标产品是否已到期/删除、产品组是否已删除或异常|
|新增预警条款|`create_clauses`，整批提交并逐项自检|整批成功才返回；任一项非法则整批失败，且不留下半批条款|
|修改或删除条款|`update_clause` 局部更新；`delete_clauses` 按 ID 批量删除|更新作用于单个条款 ID 且内容非空；删除按 ID 计数，删除后条款不再产生预警|
|查看当前实时预警|`realtime_warnings`|返回当前用户与工作空间的预警消息与关联条款、资源 ID；无需再取产品目录|
|查看全市场违规公告标的|`illegal_announcements`|任务终态返回标的代码列表；该结果不按产品过滤，是所有非 ST 标的中标题含违规/违法公告的对象|
|看两融、VIX、ETF 份额与折溢价、商誉占比|`margin_balance`、`vix`、`etf_shares`、`etf_premium_rate`、`goodwill_ratio`|返回服务端缓存的市场数据序列；日度历史必须显式给日期区间|

监控数据是行情与统计镜像，不写入产品数据；查询本身不改变条款或预警状态。

## API 使用约定

Python 与 CLI 完成相同调用，连接与公共错误处理见[连接说明](connection.md)。条款与看板接口是工作空间级资源，不需要指定产品或产品组，但只能看到当前用户与工作空间范围内的数据。

- 选择器参数（`index_ids`、`etf_ids`、`board_types`）可传逗号串或数组；空串与空数组会被本地拒绝，避免退化为全量或无筛选。
- 条款过滤参数 `product_ids`、`group_ids` 传名称或 ID，Harness 解析为 ID 后下发，重复项去重。
- 条款等级过滤的下发参数名是单数 `level`，值为逗号串；`levels=[1,3]` 对应 `level=1,3`。
- `vix` 与 `etf_premium_rate` 的 `fields` 决定查询形态：`minbar` 为当日分时，`daily` 为日度历史；含 `daily` 时必须同时给 `start_date` 与 `end_date`，否则服务端会因空日期直接失败，Harness 因此在本地拒绝。
- `illegal_announcements` 为任务型接口，客户端在同一路由等待到终态（`legacy_task=True`）。等待与超时规则见[连接说明](connection.md)。

## clauses
按条件查询风险预警条款。
- clauses：返回条款清单，每条附带 `err_msg` 数组；产品与产品组之间是「或」（命中任一侧即返回），日期区间与等级再与其它条件相「与」，未给的条件不参与过滤。

Python 签名：`rqamsh.risk_monitor.clauses(*, product_ids: list[str] | None=None, group_ids: list[str] | None=None, start_date: str | None=None, end_date: str | None=None, levels: list[int] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`product_ids`|`list[str] \| None`|`None`|生效产品名称或 ID 数组；解析为 ID 逗号串下发。|
|`group_ids`|`list[str] \| None`|`None`|生效产品组名称或 ID 数组；解析为 ID 逗号串下发。|
|`start_date`|`str \| None`|`None`|创建日期下界 YYYY-MM-DD。|
|`end_date`|`str \| None`|`None`|创建日期上界 YYYY-MM-DD。|
|`levels`|`list[int] \| None`|`None`|预警等级数组，如 `[1, 3]`，下发为逗号串。|

返回：条款数组，每条为一个预警条款对象。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|预警条款|array（object 元素）|—|每条条款一项，键见下表各行；归属当前用户与工作空间|恒返回；不含其他用户创建的条款|
|`[].id`|条款 ID|string|—|条款记录 ID|恒返回；`update_clause` 与 `delete_clauses` 用该 ID|
|`[].level`|预警等级|integer|—|预警等级，3 级及以上必须有 Webhook 地址|恒返回|
|`[].indicator_type`|指标大类|string（枚举）|—|条款条件所属的指标大类|恒返回；与 `indicator` 一起定位指标|
|`[].indicator`|指标|string（枚举）|—|具体指标，决定 `operation` 与 `value` 是否必填|恒返回；ST 与违规公告类指标不需要比较方式与数值|
|`[].operation`|比较方式|string（枚举）或 null|—|比较方式取值，如大于、小于|由数据决定；ST 与违规公告类指标不接受比较方式，此时为 `null`|
|`[].value`|比较数值|number 或 null|—|条款阈值|由数据决定；与 `operation` 同时为空或同时有值|
|`[].crontab_expression`|执行频率|cron 表达式或 array（string 元素）|—|条款的调度频率，可为单个表达式或表达式数组|恒返回|
|`[].warning_urls`|Webhook 地址|array（string 元素）或 null|—|3 级及以上条款的 Webhook 地址数组|由数据决定；级别低于 3 时为 `null`|
|`[].target_ids`|生效范围|object|—|含 `products`、`product_groups`（array，string 元素，记录 ID），两者至少一个非空|恒返回|
|`[].detail`|条件摘要|string|—|服务端拼出的中文条件描述|恒返回；查询时补入|
|`[].err_msg`|条款状态提示|array（string 元素）|—|目标产品已到期/已删除、产品组已删除或异常|恒返回；查询时补入，空数组表示当前无问题|
|`[].create_date`|创建日期|string（YYYY-MM-DD）|—|条款创建日期，日期区间过滤按它判定|恒返回|
|`[].update_dt`|更新时间|string|—|最近一次修改的服务端时间|恒返回|
|`[].user_id`|归属用户|integer|—|条款创建者用户 ID|恒返回；只读|
|`[].workspace_id`|归属工作空间|string|—|条款所属工作空间 ID|恒返回；只读|

结果检查：`err_msg` 非空表示该条款当前存在问题（目标已到期、已删除或产品组异常），需要先修正条款再依赖其预警。

## create_clauses
批量创建预警条款。
- create_clauses：整批提交，服务端逐项校验；任一项非法时整批失败，不产生部分写入。

Python 签名：`rqamsh.risk_monitor.create_clauses(clauses: list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`clauses`|`list[dict[str, Any]]`|必填|非空条款数组，元素为对象。|

每个条款至少要能通过服务端校验：

- 必含 `level`、`indicator_type`、`indicator`、`crontab_expression`。
- `target_ids` 中至少给出 `products` 或 `product_groups` 之一，且包含有效 ID；都为空直接失败。
- 指标不是 ST 或违规公告时，必须给 `operation` 与 `value`。
- 市值权重、持仓数量权重类指标不能使用「小于」「小于等于」比较方式。
- `level` 为 3 及以上时必须提供 `warning_urls`（Webhook 地址数组）。

返回：服务端原始响应，含 `inserted_count`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`inserted_count`|实际新建条数|integer|条|本批成功写入的条款数|恒返回；任一项非法时整批失败、不写入，因此该值等于提交条数|

## update_clause
局部更新单个条款。
- update_clause：只提交需要变更的字段，服务端把更新后的完整条款重新校验；内容为空时不产生任何变更，因此本地拒绝空对象。

Python 签名：`rqamsh.risk_monitor.update_clause(clause_id: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`clause_id`|`str`|必填|条款 ID。|
|`data`|`dict[str, Any]`|必填|非空变更对象；`target_ids` 中的 ID 会被服务端转为对象 ID。|

返回：服务端原始 `{effect_count}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际修改的条款数|恒返回；`data` 为空对象时服务端直接返回 `0`（客户端已本地拒绝），条款不存在时报 404；见[写入结果](connection.md#write-result)|

## delete_clauses
按 ID 批量删除条款。
- delete_clauses：请求体是 ID 裸数组，不接受对象包装；空数组本地拒绝。

Python 签名：`rqamsh.risk_monitor.delete_clauses(clause_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`clause_ids`|`list[str]`|必填|非空条款 ID 数组。|

返回：服务端原始 `{deleted_count}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`deleted_count`|实际删除条数|integer|条|本次实际删除的条款数|恒返回；不存在的 ID 不计入，`0` 表示没有命中任何条款|

## realtime_warnings
读取当前实时预警消息。
- realtime_warnings：不接收过滤参数，也不触发目录查询；结果已经是当前用户与工作空间范围。

Python 签名：`rqamsh.risk_monitor.realtime_warnings()`。

返回：对象，按命中情况给出三类键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`warning_msgs`|预警消息|object|—|键为按消息内容去重后的摘要，值为消息对象：`datetime`、`next_run_time`（服务端时间字符串）、`warning_urls`、`type`（`warning` 或 `error`）、`message`、可选 `position`|由数据决定；只收 2 级及以上条款的命中消息，没有命中时整个键不出现；消息对象不含产品或产品组名称|
|`warning_clause_ids`|命中条款 ID|array（string 元素）|—|产生这些预警的条款 ID|由数据决定；没有命中时整个键不出现|
|`warning_resource_ids`|按资源分组的消息|object|—|键为资源 ID（产品或产品组，也含系统级资源），值为该资源命中消息的数组，元素与 `warning_msgs` 的值同构|由数据决定；没有命中时整个键不出现|

键仅在确有命中时出现，缺键不等于「无风险」。消息对象只给预警消息、条款 ID 与资源 ID，不含产品或产品组名称；需要名称时由调用方按 `warning_clause_ids` 与资源 ID 自行解析，且不替代逐条持仓核对。

## illegal_announcements
读取全市场违规公告标的列表。结果按服务端缓存口径给出与调用方持仓无关的全市场代码。
- illegal_announcements：首次调用触发服务端任务，Harness 在同一路由重复读取直到终态。

Python 签名：`rqamsh.risk_monitor.illegal_announcements()`。

返回：成功终态为标的代码数组；任务失败抛 `task_failed`，等待超时抛 `wait_timeout`，语义见[任务终态 JSON](connection.md#task-result)。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|违规公告标的代码|array（string 元素）|—|非 ST 标的中标题含违规或违法公告的标的代码|恒返回；服务端直接返回任务结果、不加 `status`/`data` 包装，客户端等到终态才返回该数组|

该结果为服务端缓存口径，是否覆盖某只标的需要结合业务判断，不能当作全量公告审计。

## 看板数据

|操作|数据内容|输入要点|
|---|---|---|
|`vix`|波动率指数分时与日度序列|`index_ids` 非空；`fields='minbar,daily'`；含 `daily` 时必须给区间|
|`margin_balance`|融资融券余额|`start_date` 与 `end_date` 必填|
|`etf_shares`|单只 ETF 份额|`etf_id` 单值，区间必填|
|`etf_premium_rate`|ETF 折溢价率|`etf_ids` 非空；`fields` 规则同 `vix`|
|`goodwill_ratio`|按板块口径的商誉占比|`board_types` 非空且只接受 `GEM`（创业板）、`KSH`（科创板），区间必填|

Python 签名：`rqamsh.risk_monitor.vix(index_ids: str | list[str], *, fields: str='minbar,daily', start_date: str | None=None, end_date: str | None=None)`、`rqamsh.risk_monitor.margin_balance(*, start_date: str, end_date: str)`、`rqamsh.risk_monitor.etf_shares(etf_id: str, *, start_date: str, end_date: str)`、`rqamsh.risk_monitor.etf_premium_rate(etf_ids: str | list[str], *, fields: str='minbar,daily', start_date: str | None=None, end_date: str | None=None)`、`rqamsh.risk_monitor.goodwill_ratio(board_types: str | list[str], *, start_date: str, end_date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`index_ids`|`str \| list[str]`|必填|VIX 指数代码，逗号串或字符串数组。|
|`etf_ids`|`str \| list[str]`|必填|ETF 代码，逗号串或字符串数组。|
|`etf_id`|`str`|必填|ETF 代码单值。|
|`board_types`|`str \| list[str]`|必填|板块代码，逗号串或字符串数组；只接受 `GEM`（创业板）、`KSH`（科创板），其他取值报「不支持的 board_type」。|
|`fields`|`str`|`minbar,daily`|数据形态组合，仅接受 `minbar`、`daily`。|
|`start_date` / `end_date`|`str`|按操作而定|两融、ETF 份额、商誉占比必填；`vix` 与 `etf_premium_rate` 在含 `daily` 时必填。|

以下按操作给出返回形态与返回字段表。两点口径先说明：① 分时是当日口径、日度是历史区间口径，两者的时间字段与值都不可互换；② 数据来自 RQData 外部行情与统计（具体调用与使用位置见 [RQData 官方调用来源](rqdata.md#rqdata-calls)）。

### vix

返回：对象，按 `fields` 分键给出指数序列。两个键都是「每行一个时间点 + 每个请求代码一列」的横向展开形态：时间字段固定，代码列随请求变化，与多数操作「一行一个字段」的竖排记录不同。点位取自 [米筐特色指数行情](https://www.ricequant.com/doc/rqdata/python/ricequant-index#rqdata-API-get_price) 的 VIX 日线与分钟线；指数代码与基日见 [VIX 指数口径](https://www.ricequant.com/doc/rqdata/python/ricequant-index#ricequant-vix)。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`minbar`|当日分时序列|array（object 元素）|—|当日分时记录，一行一分钟，取当日分钟线缓存|由参数选择；`fields` 含 `minbar` 时才返回；当日没有分时数据时为空数组 `[]`|
|`minbar[].datetime`|分时时间|string|—|该分钟的分钟线时间，`YYYY-MM-DD HH:MM:SS`|随父级记录返回|
|`minbar[].{指数代码}`|该指数该分钟点位|number|点|该分钟该指数的收盘点位；键名就是请求里的指数代码|由数据决定；只出现缓存里有数据的指数|
|`daily`|日度历史序列|array（object 元素）|—|区间内每个交易日一条|由参数选择；`fields` 含 `daily` 时才返回，需同时给 `start_date` 与 `end_date`；无数据时为空数组 `[]`|
|`daily[].date`|交易日|string|—|`YYYY-MM-DD`|随父级记录返回|
|`daily[].{指数代码}`|该指数收盘点位|number|点|该交易日该指数的收盘点位；键名就是请求里的指数代码|由数据决定；只出现服务端缓存覆盖的指数|

### margin_balance

返回：两融余额数组，按日期升序给出，一行一个交易日；日期取「沪深两市融资余额」与「A 股流通市值合计」两个来源都有数据的交集，交集为空时整体为空数组。融资余额取自 [融资融券信息](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_securities_margin)，流通市值取自 [因子值](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_factor) 的 `market_cap_2`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|两融余额项|array（object 元素）|—|一个交易日一条|恒返回；没有可取的交集日期时为空数组 `[]`|
|`[].date`|日期|string|—|`YYYY-MM-DD`|随父级记录返回|
|`[].margin_balance`|沪深两市融资余额合计|number|元|沪市与深市当日融资余额之和|随父级记录返回|
|`[].margin_ratio`|融资余额占流通市值比例|number|小数|该日融资余额合计 ÷ 该日全部 A 股流通市值合计|随父级记录返回；分母只含能取到流通市值因子的股票（该因子不支持科创板），`0.03` 表示 3%|

### etf_shares

返回：对象，含该 ETF 的份额序列与拆分记录；份额或对应指数点位取不到时服务端返回空对象 `{}`，此时两个键都不出现。份额取自 [基金日度份额](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_daily_units)，拆分取自 [基金拆分信息](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_split)，指数点位取自 [合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`etf_shares`|份额序列|array（object 元素）|—|一个交易日一条，日期取份额与对应指数收盘点位都有数据的交集|随父级返回；取不到份额或指数点位时没有该键|
|`etf_shares[].date`|交易日|string|—|`YYYY-MM-DD`|随父级记录返回|
|`etf_shares[].units`|期末总份额|number|份|该 ETF 该日的期末总份额|随父级记录返回|
|`etf_shares[].close`|对应指数收盘点位|number|点|该 ETF 所跟踪指数当日的收盘点位|随父级记录返回；跟踪关系由服务端内置的 ETF 与指数映射决定，不由请求指定|
|`etf_splits`|拆分记录|array（object 元素）|—|该 ETF 的全部历史拆分，一条一次拆分|随父级返回；没有拆分记录时为空数组 `[]`|
|`etf_splits[].ex_dividend_date`|除权除息日|string|—|该次拆分的除权除息日，`YYYY-MM-DD`|随父级记录返回|
|`etf_splits[].split_ratio`|拆分折算比例|number|小数|该次拆分的折算比例（1 拆几）|随父级记录返回|

`etf_splits` 是上游基金拆分数据的原样输出，不受 `start_date` / `end_date` 限制：请求区间内没有拆分也可能返回多年前的记录。

### etf_premium_rate

返回：对象，按 `fields` 分键给出折溢价率序列。形态与 `vix` 一致：时间字段固定，每个请求的 ETF 代码各占一列。价格取 `close`、场内基金实时估算净值取 `iopv`，见 [合约行情返回字段](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-return)。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`minbar`|当日分时折溢价率|array（object 元素）|—|当日分时记录，一行一分钟|由参数选择；`fields` 含 `minbar` 时才返回；当日没有分时数据时为空数组 `[]`|
|`minbar[].datetime`|分时时间|string|—|该分钟的分钟线时间，`YYYY-MM-DD HH:MM:SS`|随父级记录返回|
|`minbar[].{ETF代码}`|该 ETF 该分钟折溢价率|number|小数|`close ÷ iopv − 1`；键名就是请求里的 ETF 代码|由数据决定；`close` 或 `iopv` 缺失、`iopv` 为 `0` 的分时不参与计算；`0.01` 表示溢价 1%|
|`daily`|日度历史折溢价率|array（object 元素）|—|区间内每个交易日一条|由参数选择；`fields` 含 `daily` 时才返回，需同时给 `start_date` 与 `end_date`；无数据时为空数组 `[]`|
|`daily[].date`|交易日|string|—|`YYYY-MM-DD`|随父级记录返回|
|`daily[].{ETF代码}`|该 ETF 当日折溢价率|number|小数|`close ÷ iopv − 1`；键名就是请求里的 ETF 代码|由数据决定；缺失或 `iopv` 为 `0` 的标的不参与计算|

### goodwill_ratio

返回：按日期的板块商誉占比数组，一行一个日期；日期取请求板块的商誉与全部 A 股商誉都有数据的交集，只保留能算出占比的日期。商誉取自 [因子值](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_factor) 的 `goodwill`，板块归属取自 [全部合约基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-all_instruments) 的 `board_type`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|商誉占比项|array（object 元素）|—|一个日期一条|恒返回；没有可用日期时为空数组 `[]`|
|`[].date`|日期|string|—|`YYYY-MM-DD`|随父级记录返回|
|`[].{板块}`|该板块商誉占比|number|小数|该板块商誉合计 ÷ 全部 A 股商誉合计；键名就是请求里的板块代码（`GEM`、`KSH`）|由参数选择；只出现请求的板块键；某个日期上占比为空时该板块键在该条记录里不出现|

## RQData 官方调用来源

本页用到的 rqdata 调用、对应官方页面与使用位置集中列在 [RQData 官方调用来源](rqdata.md#rqdata-calls)。看板数据与违规公告的取值都来自这些调用，不含产品自身的估值结果；本页不再重复清单。
