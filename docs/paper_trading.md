# 模拟交易 paper_trading

模拟交易是在 AMS 内按模板持续接收信号并按行情撮合的产品。信号生成模拟交易流水，之后和普通流水一样进入估值与头寸链。它不是实盘交易通道，也不产生真实委托；信号上传成功只表示进入模拟撮合队列，**不表示已经成交**。

对外只暴露模板类型；模板决定创建参数、支持的文件形态和执行方式：

|模板|业务含义|适用信号|关键配置|
|---|---|---|---|
|`equity_long`|权益类多头策略，按算法执行目标权重|目标权重单|`algo`、佣金、滑点、执行时间|
|`conventional`|通用策略，按策略分类和费率撮合|交易单、目标数量单、目标权重单|`strategy_category`、股票/期货费率、融资与融券利率|

两种模板创建产品时都会自动设置：

- `report_name` 为产品名；
- 默认交易账户；
- `unit_policy=auto_prev_unit_net_value`（自动份额）；
- 产品标签为模拟交易产品、数据源为交易流水。

因此不要用通用 `products.create` 创建模拟交易产品；通用接口只创建产品壳，不会生成模板配置。

## 从用户需求到操作

其他业务场景按需参考下表。

|用户需求|API 与输入准备|完成条件|
|---|---|---|
|创建权益类多头策略模拟产品|确认名称、基准、开始日、初始资金、算法 → `create(template='equity_long', ...)` → `get` 读回|返回 `product_id` 与模板配置；`get` 的 `template` 为 `equity_long`|
|查模拟产品模板与配置|`list` 或 `get`|拿到 `template`、产品、配置；普通产品壳会明确报没有模拟交易配置|
|上传信号|确认产品与本地文件路径 → `upload_signals` → `list_signals` 读回|逐文件结果可读；有失败文件时抛 `partial_failure` 并保留成功与失败结果，不自动重传|
|删除或重算信号|`delete_signals` 按日期或 ID 删除；`recompute` 从指定日开始重算|任务终态成功；删除/重算不可撤销，重算完成前不宣称结果已更新|
|删除模拟产品|`delete`|产品和模拟配置一起删除；不可撤销|

## API 使用约定

- 产品参数可传 ID 或名称；写入和查询都解析到唯一产品。
- `create` 是任务型接口，客户端等待终态；失败不自动重试。
- 上传文件的输入约束、逐文件结果与失败恢复统一见[信号上传](#upload_signals)。
- 两模板的专属参数互斥：`equity_long` 不接受通用策略的策略分类、股票费率、融资/融券利率及期货浮动费率；`conventional` 不接受 `algo`、执行时间或权益类多头策略的佣金参数。
- 创建、上传、删除和重算中的异步请求由 Harness 等待任务终态；受理不等于任务完成，上传任务完成也不等于信号撮合完成。等待与错误语义见[连接说明](connection.md#task-result)。

## create

按模板创建模拟交易产品。`template` 不只是标签：它决定创建方式和整套必填参数；把另一模板的参数传进来会在本地拒绝，不会发请求。

返回：创建任务终态，字段与模板分支见下方「返回」。

Python 签名：`rqamsh.paper_trading.create(template: str, *, name: str, benchmark: str, start_date: str, init_amount: float, algo: str | None=None, strategy_category: str | None=None, stock_min_fee: float | None=None, stock_commission_rate: float | None=None, loan_rate: float | None=None, margin_rate: float | None=None, futures_float_rate: float | None=None, futures_float_amount: float | None=None, slippage_rate: float | None=None, slippage_ticks: int | None=None, start_time: str | None=None, end_time: str | None=None, commission_rate: float | None=None, min_fee: float | None=None, tag_ids: list[str] | None=None, description: str | None=None)`。

### 创建时的推荐起点

用户未指定的配置可按下表选取，用户显式提供的值优先。这些是调用方组织创建参数的公开推荐值，**不是 SDK 自动补值或服务端省略默认**：采用时须显式传入，不能把签名中的 `None` 当成数值 `0`。用户已明确要求创建、名称和真实起始日已知且模板可确定时，说明采用的完整配置后创建并读回，不逐项追问已公开的默认值；授权规则见[写入范围与授权](demo/README.md#6-写操作计划卡)。

|字段|推荐值或处理方式|适用条件与注意事项|
|---|---|---|
|`template`|`equity_long`|普通权益多头目标权重策略的起点；需要交易单、目标数量单或其他策略时用 `conventional`，不要为套用默认值改变用户的信号类型|
|`name`|用户指定的产品名称|无通用默认；创建前查重|
|`start_date`|真实交易起始日|无通用默认；不擅自用当天或固定历史日期补齐|
|`init_amount`|`10000000` 元|初始资金 1000 万；用户指定金额优先|
|`benchmark`|`index,000300.XSHG`|沪深 300；用户给定基准或策略有明确对应基准时按实际配置|
|`slippage_rate`|`0`|默认选择比例滑点；不同时传 `slippage_ticks`。明确选择跳数时只传 `slippage_ticks`，不再传比例|
|`tag_ids`|省略|无标签时不传 `[]`，SDK 只接受非空标签 ID 数组|
|`description`|省略|无说明时不必补文字|
|`algo`|`vwap`|仅 `equity_long`；不向 `conventional` 传算法参数，其算法由信号文件指定|
|`start_time` / `end_time`|`09:30` / `15:00`|`equity_long` 的默认 VWAP 窗口；改用 `open` 时两项都省略；其他执行窗口按用户要求|
|`commission_rate` / `min_fee`|`0.0002` / `0` 元|仅 `equity_long`；佣金万二、最低佣金为 0|
|`strategy_category`|按实际策略填写|仅 `conventional`，没有统一默认；明确股票多头可用 `stock_long`，不能把未知策略自动归为股票多头|
|`stock_commission_rate` / `stock_min_fee`|`0.0002` / `0` 元|仅 `conventional`；股票佣金万二、最低佣金为 0|
|`loan_rate` / `margin_rate`|`0` / `0`|仅 `conventional`；分别是融资利率与融券利率，不是期货保证金比例|
|`futures_float_rate`|`0`|仅 `conventional`，默认选择期货每手上浮比例；不同时传 `futures_float_amount`。明确按金额上浮时只传金额|

**比例统一传小数，不传界面显示的百分数或基点数。** 佣金 `2 bp`（万二）传 `0.0002`，融资或融券年利率 `8%` 传 `0.08`，滑点 `0.1%` 传 `0.001`；最低佣金与每手浮动金额直接传元，跳数直接传整数。这里的 `0` 是明确选择不计该项模拟成本，不表示真实交易没有成本，也不是给未知实盘费用补零。

默认权益多头配置示例；名称和日期仅为示例，须替换为本次获授权的实际值：

```python
result = rqamsh.paper_trading.create(
    template="equity_long", name="授权测试模拟交易", start_date="2026-01-05",
    benchmark="index,000300.XSHG", init_amount=10000000,
    algo="vwap", start_time="09:30", end_time="15:00",
    commission_rate=0.0002, min_fee=0, slippage_rate=0,
)
```

通用股票多头配置示例；只有用户目标确为股票多头时才采用该策略分类：

```python
result = rqamsh.paper_trading.create(
    template="conventional", name="授权测试通用模拟交易", start_date="2026-01-05",
    benchmark="index,000300.XSHG", init_amount=10000000,
    strategy_category="stock_long", stock_commission_rate=0.0002,
    stock_min_fee=0, loan_rate=0, margin_rate=0,
    futures_float_rate=0, slippage_rate=0,
)
```

创建后用 `get` 核对模板、基准、资金、算法/窗口、费率和滑点；返回配置的数值以实际持久化结果为准，创建成功不等于已有信号、成交或估值结果。

### 通用参数

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`template`|`str`|必填|`equity_long` 或 `conventional`；决定下方使用哪组模板参数。|
|`name`|`str`|必填|产品名称，也是默认报告名称。|
|`benchmark`|`str`|必填|`index,代码` 或 `customized_index,代码`。|
|`start_date`|`str`|必填|产品开始日 YYYY-MM-DD。|
|`init_amount`|`float`|必填|初始资金，非负数。|
|`slippage_rate` / `slippage_ticks`|`float \| int \| None`|可选，互斥|滑点比例或跳数；两种模板都可选。|
|`tag_ids`|`list[str] \| None`|可选|非空字符串数组。|
|`description`|`str \| None`|可选|产品说明。|

### equity_long：权益类多头策略

按算法执行目标权重单。除通用参数外，只使用以下字段：

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`algo`|`str`|必填|`open`、`vwap` 或 `twap`。|
|`start_time` / `end_time`|`str \| None`|`vwap`/`twap` 必填|HH:MM；开始早于结束，分钟为 5 的倍数。`open` 不接受这两个参数。|
|`commission_rate` / `min_fee`|`float \| None`|可选|佣金率与最低佣金。|

不接受的参数：`strategy_category`、`stock_min_fee`、`stock_commission_rate`、`loan_rate`、`margin_rate`、`futures_float_rate`、`futures_float_amount`。

### conventional：通用策略

按策略分类和费率撮合，支持交易单、目标数量单和目标权重单。除通用参数外，只使用以下字段：

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`strategy_category`|`str`|必填|策略分类，如 `stock_long`、`equity_market_neutral`、`commodity_trading_advisor`。|
|`stock_min_fee` / `stock_commission_rate`|`float`|必填|股票最低佣金与佣金率。|
|`loan_rate` / `margin_rate`|`float`|必填|融资年利率与融券年利率，按小数传入；不是期货保证金比例。|
|`futures_float_rate` / `futures_float_amount`|`float \| None`|可选，互斥|期货浮动费率或浮动金额。|

不接受的参数：`algo`、`start_time`、`end_time`、`commission_rate`、`min_fee`。

### 返回

创建任务终态的对象；`data` 展开后附 `template`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`template`|模板|string（枚举）|—|本次创建的模板|恒返回|
|`product_id`|产品 ID|string|—|新建产品 ID|恒返回|
|`paper_trading_id`|权益类多头策略配置 ID|string|—|`equity_long` 的模板配置 ID|仅 `equity_long` 返回|
|`channel_id`|通用策略配置 ID|string|—|`conventional` 的模板配置 ID|仅 `conventional` 返回|

## get
读取一个模拟交易产品的模板和配置。

Python 签名：`rqamsh.paper_trading.get(resource: str) -> dict[str, Any]`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|模拟交易产品 ID 或名称。|

返回：产品、模板和模板配置。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`template`|模板|string（枚举）|—|`equity_long` 或 `conventional`|恒返回|
|`product_id`|产品 ID|string|—|模拟交易产品 ID|恒返回|
|`product`|产品配置|object|—|服务端产品 JSON，含名称、基准、账户与份额策略|恒返回|
|`config`|模板配置|object|—|服务端原始模板配置；键随模板不同|恒返回|

产品不是模拟交易产品时返回 `not_paper_trading`；是产品但没有模板配置时返回 `paper_trading_config_not_found`，此时不能按模拟交易继续上传。

## list
列出当前空间内已配置的模拟交易产品。

Python 签名：`rqamsh.paper_trading.list() -> list[dict[str, Any]]`。

返回：数组，每项结构与 `get` 相同；同一产品只出现一次，按产品名和 ID 排序。没有配置的产品不出现在结果中。

## upload_signals
按产品模板上传信号文件。

返回：按 `template` 分支返回上传任务终态，结构见下表；错误与重试边界见[上传失败与恢复](#upload-failures)。

Python 签名：`rqamsh.paper_trading.upload_signals(resource: str, file_paths: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|模拟交易产品 ID 或名称。|
|`file_paths`|`list[str]`|必填|非空本地文件路径数组；元素必须是存在的普通文件。只发送路径末尾的文件名，同一服务端批次内文件名须唯一，包括来自不同目录的文件；客户端不校验重名。|

下表是服务端接受的形态与模板对应关系，供准备文件时参考：

|文件形态|识别列|`equity_long`|`conventional`|
|---|---|---|---|
|交易单|`transaction_type`|不支持|支持；必需 `order_book_id`、`transaction_type`、`quantity`、`algo`；非 `open` 算法还要开始/结束时间|
|目标数量单|`target_quantity`|不支持|支持；必需 `order_book_id`、`target_quantity`；文件名带算法；可在合约交易时段外指定执行窗口|
|目标权重单|`target_weight`|支持；必需 `order_book_id`、`target_weight`|支持；必需 `order_book_id`、`target_weight`；文件名带算法|

`conventional` 的目标数量单和目标权重单给出的是**目标**，不是增量：撮合按信号开始前的实际持仓计算调仓差额，已有持仓计入差额，不会在现有持仓上再叠加一次目标值。初始截面取信号开始前已经发生的流水，包括用户录入的流水和同日更早信号已生成的成交；只有时间严格早于信号开始时间的流水计入，等于开始时间的不计入。`09:30` 及之前的信号没有可用的前一分钟行情，仍以上一估值日收盘截面为起点并应用这些流水，因此同一交易日连续多个信号不会把更早信号建立的持仓当成新目标重复买入；目标权重单在这类信号下先用收盘价更新持仓市值再算权重差额。产品起始日的信号没有昨收截面，仍按分钟线与当日流水重算。初始截面不把数量为 0 的持仓计入调仓基数，当天已开仓又平仓到零的合约不会生成多余的平仓单或零数量指令；信号里给出非零目标数量时仍按目标建仓。

`conventional` 的交易时段校验只作用于交易单和目标权重单：目标数量单描述的是目标持仓，导入资格不受合约交易时段限制，能否成交由撮合阶段的行情可用性决定，服务端接受上传不等于盘外一定成交。交易单仍须落在合约交易时段，跨夜与不支持夜盘的检查同样只作用于这两类信号。`equity_long` 的目标权重单走另一条上传链路，其校验口径不在本节这组规则内。

同日规则按模板区分，上传不覆盖已有信号：

- `equity_long`：每个业务日只接受一条信号。同一批中通过解析的文件若命中同日，这些同日文件均报错；数据库已有该日信号时，新文件也报错。其他日期中通过校验的文件照常写入。
- `conventional`：同日允许多条信号，但类型必须一致，执行窗口不能重叠，前一条的结束时间等于后一条的开始时间也算重叠。服务端按日期和开始时间检查新文件，遇到与已有或本批已通过校验的信号冲突时，只拒绝冲突文件。

两种模板写入成功时，新信号进入待撮合状态；从本批最早写入的信号日期起，已有信号也会重置为待撮合，其原模拟成交流水和撮合结果被清理。头寸与每日汇总也从受影响日期起清理，但封账日及以前的头寸与每日汇总保留。先核对 [信号列表](#list_signals) 的记录和状态，再核对重新生成的流水和估值，不把 `new_id` 当作已成交或已完成估值。

### 逐文件结果

两个模板的任务终态 `data` 结构相同：`data` 是文件名到单文件结果的映射。下表的字段相对于 `data`，`{文件名}` 是动态键占位符，不是实际 JSON 键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`{文件名}`|单文件结果|object|—|按文件名记录该文件的处理结果|由数据决定；同批重名会共用同一键，成功结果可覆盖同名文件的错误；不能据此确认所有输入都成功|
|`{文件名}.new_id`|新信号 ID|string|—|上传成功时生成的信号记录 ID|由数据决定；仅成功文件返回|
|`{文件名}.err_msg`|失败原因|string|—|上传失败时的错误原因|由数据决定；仅失败文件返回，处理规则见[上传失败与恢复](#upload-failures)|

`equity_long` 返回：

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`template`|模板|string|—|`equity_long`|恒返回|
|`product_id`|产品 ID|string|—|目标产品|恒返回|
|`file_session_id`|文件会话 ID|string|—|批量上传会话|恒返回|
|`result`|上传任务终态|object|—|结构见[任务终态 JSON](connection.md#task-result)|恒返回|
|`result.data`|逐文件结果|object|—|文件名到单文件结果的映射|随父级返回；结构见[逐文件结果](#逐文件结果)|

`conventional` 返回：

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`template`|模板|string|—|`conventional`|恒返回|
|`product_id`|产品 ID|string|—|目标产品|恒返回|
|`channel_id`|通用策略配置 ID|string|—|模拟交易通道 ID|恒返回|
|`batches`|逐批任务结果|array（object 元素）|—|每批一个任务终态；元素结构见[任务终态 JSON](connection.md#task-result)，默认每批最多 50 个文件|恒返回；提交中断边界见[上传失败与恢复](#upload-failures)|
|`batches[].data`|逐文件结果|object|—|文件名到单文件结果的映射|随父级返回；结构见[逐文件结果](#逐文件结果)|

<a id="upload-failures"></a>

### 上传失败与恢复

任一文件 `err_msg` 非空时抛 `partial_failure`：`details.results` 保留完整返回包装（包括成功与失败文件），`details.failed_files` 是失败文件名到 `err_msg` 的映射。`conventional` 在首个含失败文件的批次后停止；后续文件尚未提交，也不出现在 `batches` 的结果中。客户端不自动重传；恢复时先核对已提交批次，只修正失败文件并另行提交未上传文件，不重传已成功文件。

单文件解析器报告的校验错误（例如进入必填列检查后发现缺列）和同日冲突写入该文件的 `err_msg`。**当前实现例外：** `conventional` 交易单缺少 `algo` 列时，解析器在必填列检查前直接读取该列，导致当前批在写入前失败；同批其他文件不写入，也没有该文件的 `err_msg`。上传前应核对 `algo` 列。

请求或整个任务失败（如 `equity_long` 上传会话不存在，或服务端写入异常使任务中断），不按逐文件 `partial_failure` 返回。没有逐文件回执时，先用 [`list_signals`](#list_signals) 核对目标日期、文件名与状态，再补交确认未写入的文件。

`upload_signals` 只走模拟交易上传入口，不会把文件发到资产单元持仓单或交易流水。

## list_signals
读取模拟交易信号列表。

Python 签名：`rqamsh.paper_trading.list_signals(resource: str, *, start_date: str | None=None, end_date: str | None=None, fields: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|模拟交易产品 ID 或名称。|
|`start_date` / `end_date`|`str \| None`|可选|日期区间 YYYY-MM-DD；给出的边界均包含当天，省略一端则不限制该端。|
|`fields`|`str \| None`|可选|逗号串字段；仅 `equity_long` 支持，`conventional` 传该参数会本地拒绝。|

返回：服务端原始信号数组。两个模板默认读取 `_id`（信号 ID）、`filename`、`fs_id`、`date`、`status`；`equity_long` 默认还读取 `hash`，并按日期倒序。指定 `fields` 的 `equity_long` 请求改用所给字段投影；核对上传时保留 `filename`、`date` 和 `status`，并用 `_id` 对照上传返回的 `new_id`。

## delete_signals
按日期或信号 ID 删除模拟交易信号。

Python 签名：`rqamsh.paper_trading.delete_signals(resource: str, *, start_date: str | None=None, end_date: str | None=None, signal_ids: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|模拟交易产品 ID 或名称。|
|`start_date` / `end_date`|`str \| None`|按日期删除时至少一个|删除区间。|
|`signal_ids`|`list[str] \| None`|按 ID 删除时必填|非空信号 ID 数组；与日期至少提供一种。|

返回：`equity_long` 为异步任务终态；`conventional` 按日期删除为批量任务终态，按信号 ID 删除为逐项任务终态。未提供的日期不会写成 `null`；`equity_long` 会提交实际给出的日期与信号 ID，`conventional` 按信号 ID 删除时不使用日期条件。删除不可撤销，删除后需要重算才能反映结果；任务成功不等于已重新撮合。

## recompute
按模板提交模拟交易重算。

Python 签名：`rqamsh.paper_trading.recompute(resource: str, *, date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|模拟交易产品 ID 或名称。|
|`date`|`str \| None`|可选|从该日 YYYY-MM-DD 开始重算；省略或传 `None` 时不发送日期字段，重算全部信号。|

返回：两种模板都返回异步任务终态。受理或提交不代表撮合完成。

## delete
删除模拟交易产品及其模板配置。

Python 签名：`rqamsh.paper_trading.delete(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|模拟交易产品 ID 或名称。|

返回：异步任务终态，并附 `template`。删除会连同模板配置、信号和模拟交易流水一起清理，不可撤销。
