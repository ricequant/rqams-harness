# valuation_reports 字段字典

需要用托管估值数据建立产品估值或核对某日资产时，按[估值报告操作](../valuation_reports.md)调用 `rqamsh.valuation_reports.upload`，用本页组装一份报告 JSON；查询已上传日期和文件信息使用 `rqamsh.valuation_reports.list`。报告数据是写入输入，元数据是查询输出，不能把元数据当作报告上传。

产品持仓表（`rqamsh.positions_sheets.upsert`）是与结构化上传同形的另一种截面输入，字段同样见本页；两种形态的定位、互斥与覆盖规则见[估值表输入的两种形态](../valuation_reports.md#positions-sheet-input)。

本页只列字段与业务含义；上传必填、省略与检查规则见[估值报告操作](../valuation_reports.md)，本页不逐行重复。`product_id` 由目标产品确定。分类份额金额与净值见[分类份额估值](balances.md#productsharevalue)；应付金额拆分使用 `positions[].extras.product_share_quantities.{份额}`，不要使用 `payable_amount_by_share`。

表中使用 JSON 类型：日期为 `YYYY-MM-DD` 字符串，日期时间为字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值，不代表写入时允许省略或传 `null`；输入必填项和省略行为按对应操作规则执行。查询可能只返回部分字段，缺失或 `null` 均不等于 `0`、`false` 或空数组，不能自行补值参与估值。金额不自动缩放，比例 `0.01` 表示 `1%`；未声明单位的数字不要猜测为万元或百分数。

<a id="valuationreportbalance"></a>

## 估值报告数据

一份估值报告对象，作为结构化上传的 `data`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`date`|业务日期|string|YYYY-MM-DD|业务日期，不等同写入时间|—|
|`total_equity`|净资产/总权益|number|金额；主估值人民币，交易/在途依币种|净资产/总权益|—|
|`units`|份额|number|份|产品或分类份额|—|
|`unit_net_value`|单位净值|number|每单位份额金额/净值|单位净值：净资产除以份额|—|
|`positions`|报告持仓列表|array（object 元素）|—|持仓记录列表；<br>&emsp;展开见 [报告持仓](valuation_reports.md#valuationreportposition)|—|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品 ID|由目标 resource 确定|
|`acc_unit_net_value`|累计单位净值|number / null|每单位份额金额/净值|按产品累计净值口径计算|—|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读|
|`share_values`|分类份额估值|object（string 键 → object） / null|—|分类份额估值，键为分类份额名称；<br>&emsp;展开见 [分类份额估值](balances.md#productsharevalue)|—|

<a id="valuationreportposition"></a>

## 估值报告持仓

报告中的持仓数组 `positions[]`；是否需要价格和数量取决于品种。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`positions[].order_book_id`|证券/合约代码|string|—|不是自定义合约记录 ID|—|
|`positions[].symbol`|显示名称|string|—|标的或资产单元显示名称|—|
|`positions[].asset_class`|资产类别|string（枚举）|—|枚举[资产品种与会计科目](others.md#assetclass)|—|
|`positions[].direction`|多空方向|string（枚举）|—|多空方向；枚举[多空方向](balances.md#direction)|—|
|`positions[].market_value`|持仓市值|number|金额；主估值人民币，交易/在途依币种|持仓市值；总表不含应收应付|—|
|`positions[].quantity`|持仓数量|number / null|股/份/合约单位；依品种|持仓/成交数量；股票为股、基金为份、衍生品按合约单位|—|
|`positions[].cost_price`|单位成本价|number / null|标的报价单位；setl_ccy 为结算币种|估值报告中的单位成本价|—|
|`positions[].cost`|持仓成本|number / null|金额；主估值人民币，交易/在途依币种|持仓成本，含税费|—|
|`positions[].fair_value`|公允价格|number / null|标的报价单位；setl_ccy 为结算币种|公允价格/债券全价，人民币估值口径|—|
|`positions[].fair_value_setl_ccy`|结算币种公允价格|number / null|标的报价单位；setl_ccy 为结算币种|结算币种公允价格，例如港币价格|—|
|`positions[].accrued_interest`|累计应计利息|number / null|金额；主估值人民币，交易/在途依币种|累计应计利息|—|
|`positions[].sterilisation_market_value`|期货平衡项市值|number / null|金额；主估值人民币，交易/在途依币种|期货平衡项市值|—|
|`positions[].extras`|应付金额分类份额拆分|object / null|—|应付金额按分类份额拆分；<br>&emsp;展开见 [应付金额分类份额拆分](balances.md#payablepositionextra)|—|

<a id="positionssheet"></a>

## 持仓表

产品持仓表按产品与日期保存的一份截面，写入与查询共用同一组字段；调用方式与覆盖规则见[产品持仓表操作](../positions_sheets.md)。

同形输入的差异按来源区分：本表的记录键是 `_id`，结构化上传的[估值报告数据](valuation_reports.md#valuationreportbalance)用 `id`；本表的持仓明细不含 `fair_value_setl_ccy` 与 `extras`。两种形态同名字段的类型、单位与备注以各自所属的表为准，不要跨形态套用。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`date`|业务日期|string|YYYY-MM-DD|该持仓表对应的日期|同一产品同日只有一份|
|`total_equity`|净资产/总权益|number|金额；主估值人民币|当日产品净资产|—|
|`units`|份额|number|份|当日产品份额|—|
|`unit_net_value`|单位净值|number|每单位份额金额/净值|当日单位净值|—|
|`positions`|持仓明细|array（object 元素）|—|当日持仓列表；<br>&emsp;展开见 [持仓明细](valuation_reports.md#positionssheetposition)|空数组表示该日无持仓|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品|由目标 resource 确定|
|`_id`|记录 ID|string|字符串 ID|服务端记录 ID|只读；查询返回的键就是 `_id`，没有 `id`；删除使用日期而不是本字段|

<a id="positionssheetposition"></a>

## 持仓明细

`positions` 中每一项的形状。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`order_book_id`|证券/合约代码|string|—|持仓标的代码|不是自定义合约记录 ID|
|`symbol`|证券名称|string|—|持仓标的名称|—|
|`asset_class`|资产类别|string（枚举）|—|枚举[资产品种与会计科目](others.md#assetclass)|—|
|`direction`|多空方向|string（枚举）|—|持仓方向；枚举[多空方向](balances.md#direction)|—|
|`market_value`|市值|number|金额；本币|以本币计的持仓市值|—|
|`sterilisation_market_value`|期货平衡市值|number|金额；本币|期货类资产的平衡项市值|仅期货类资产使用|
|`quantity`|数量|number / null|按品种|持仓数量|股票为股、基金为份、衍生品按合约单位|
|`cost_price`|成本价|number / null|按品种每单位价格|持仓成本价|—|
|`cost`|成本金额|number / null|金额；原币|以原币记的持仓成本金额|—|
|`fair_value`|公允价值|number / null|按品种每单位价格|公允价值/全价，以原币记|—|
|`accrued_interest`|应计利息|number / null|金额；原币|持仓的应计利息|—|

<a id="positionssheetupsertresult"></a>

## 写入结果

`upsert` 返回的计数与错误项见[产品持仓表 upsert 返回](../positions_sheets.md#upsert)；本页不重复该返回结构。

<a id="valuationreportmetadata"></a>

## 估值报告文件信息

报告文件元数据。下表字段均为列表返回键，不是需要发送的 JSON 外层键；列表通常只返回 `date`、`file_name`、`valuation_report_id`、`source`。其他字段是否提供以实际结果为准。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`date`|业务日期|string|YYYY-MM-DD|业务日期，不等同写入时间|只读元数据；以实际返回字段为准|
|`valuation_report_id`|估值报告业务记录 ID|string|字符串 ID|估值报告业务记录 ID|只读元数据；以实际返回字段为准|
|`fs_id`|原文件存储 ID|string|字符串 ID|服务端原文件存储 ID|只读元数据；以实际返回字段为准|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品 ID|只读元数据；以实际返回字段为准|
|`file_name`|原上传文件名|string|—|原上传文件名|只读元数据；以实际返回字段为准|
|`hash`|文件内容标识|string|—|上传文件内容标识|只读元数据；以实际返回字段为准|
|`source`|来源|string（枚举）|—|流水或估值报告来源；枚举[估值报告来源](#valuationreportsource)|只读元数据；以实际返回字段为准|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读元数据；以实际返回字段为准|

## 枚举取值

<a id="valuationreportsource"></a>

### 估值报告来源

估值报告的来源取值；写入规则与默认值见[上传估值报告](../valuation_reports.md#upload)。

|值|含义|
|---|---|
|`manual`|估值表手动录入|
|`open_api`|OPENAPI|
|`client_upload`|客户端估值表上传|
