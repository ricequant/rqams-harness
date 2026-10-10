# confirmations 字段字典

解释 `rqamsh.confirmations.list`、`get`、`latest` 的返回内容时按本页查找字段。凭证只读，不写业务数据；来源取值与含义见[导入凭证来源](#confirmationsource)，业务用法与完成条件见[导入凭证操作](../confirmations.md)。

表中使用 JSON 类型：日期时间为字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值；缺失或 `null` 均不等于 `0`。统计字段之间可互相推导，不要用 `items` 长度代替统计字段，也不要把解析条数当作已正确登记的业务数据。

<a id="confirmationlistitem"></a>

## 凭证列表项

`list` 返回的 `items` 中每一项。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`id`|凭证 ID|string|字符串 ID|凭证唯一 ID|`get` 与 `download` 使用|
|`source_enum`|凭证来源|string（枚举）|—|该批次的导入来源；枚举[导入凭证来源](#confirmationsource)|—|
|`name`|凭证名称|string / null|—|该批次的名称|由导入入口生成，例如产品持仓表按产品与日期命名|
|`fund_account`|资金账号|string / null|—|导入所属资金账号|与账户相关的来源才有值|
|`asset_unit_id`|资产单元 ID|string / null|字符串 ID|归属资产单元|与资产单元相关的来源才有值|
|`operation_time`|操作时间|string|日期时间字符串|该批次的导入时间|不是被导入数据的业务日期|
|`total_parsed`|解析条数|number|条|从文件或请求中解析出的条数|—|
|`total_registered`|登记条数|number|条|实际写入业务的条数|小于解析条数表示存在未生效条目|
|`earliest_registered_date`|最早登记日期|string / null|YYYY-MM-DD|该批次写入数据的最早业务日期|未生效条目不参与|
|`latest_registered_date`|最晚登记日期|string / null|YYYY-MM-DD|该批次写入数据的最晚业务日期|未生效条目不参与|

<a id="confirmationdetail"></a>

## 凭证明细

`get` 返回的字段，包含列表项统计与逐项结果。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`id`|凭证 ID|string|字符串 ID|与请求中的 confirmation_id 一致|—|
|`source_enum`|凭证来源|string（枚举）|—|该批次的导入来源；枚举[导入凭证来源](#confirmationsource)|—|
|`asset_unit_id`|资产单元 ID|string / null|字符串 ID|归属资产单元|与资产单元相关的来源才有值|
|`fund_account`|资金账号|string / null|—|导入所属资金账号|与账户相关的来源才有值|
|`is_successful`|是否全部登记|bool|—|解析条数与登记条数是否相等|—|
|`operation_time`|操作时间|string|日期时间字符串|该批次的导入时间|不是被导入数据的业务日期|
|`total_parsed`|解析条数|number|条|解析出的条数|—|
|`total_registered`|登记条数|number|条|实际写入业务的条数|—|
|`earliest_registered_date`|最早登记日期|string / null|YYYY-MM-DD|写入数据的最早业务日期|—|
|`latest_registered_date`|最晚登记日期|string / null|YYYY-MM-DD|写入数据的最晚业务日期|—|
|`items`|逐项结果|array|—|该批次的条目明细；<br>&emsp;展开见 [逐项结果](confirmations.md#confirmationitem)|受 status 与分页影响|
|`src_file`|源文件信息|object / null|—|导入时保存的原始文件；<br>&emsp;展开见 [源文件](confirmations.md#confirmationsourcefile)|为 null 表示该批次没有源文件，产品持仓表等结构化写入保存的凭证都是这样|
|`total`|当前子集条数|number|条|按 status 统计的条数|与 `items` 同一子集|

<a id="confirmationitem"></a>

## 逐项结果

`items` 中每一项，由解析出的业务条目加上未生效原因组成。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`data`|条目内容|object / null|—|该条解析出的业务字段；枚举随来源不同，例如[估值报告](valuation_reports.md)、[头寸](balances.md)、[份额事件](unit_events.md)|未生效条目为 null|
|`fail_reason`|未生效原因|string / null|—|该条未能登记的原因|非空表示该条未生效|

<a id="confirmationsourcefile"></a>

## 源文件

`src_file` 的字段，由 `download` 取回内容。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`filename`|文件名|string|—|导入时提交的文件名|本地下载路径由 `output` 决定，不使用本字段|
|`content`|文件内容|string / null|—|原文件的字节内容|查询接口不回传内容，恒为 null；取内容用 `download`|

<a id="confirmationlatestitem"></a>

## 最新导入状态

`latest` 返回的每一项：以产品为单位，附该产品下各账户或各资产单元的最近导入状态。返回形状随 `source` 不同，见下表。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_id`|产品 ID|string|字符串 ID|归属产品|三种形状都包含|
|`product_name`|产品名称|string|—|归属产品名称|三种形状都包含|
|`account_items`|账户导入状态|array（object 元素）|—|逐账户的最近导入状态；<br>&emsp;展开见 [账户导入状态](confirmations.md#confirmationaccountitem)|估值表、流水等账户级来源|
|`custodian_item`|托管事件导入状态|object|—|该产品的托管事件最近导入状态；<br>&emsp;展开见 [托管事件导入状态](confirmations.md#confirmationcustodianitem)|仅 CustodianEvents 来源；从未导入时为空对象|
|`positions_statement_items`|资产单元导入状态|array（object 元素）|—|逐资产单元的持仓单上传状态；<br>&emsp;展开见 [最新持仓单状态](../positions_statements.md#latest)|由 `positions_statements.latest` 返回；服务端 `confirmations` 的资产单元分支当前不可达|

<a id="confirmationaccountitem"></a>

## 账户导入状态

账户级来源下 `account_items` 中每一项。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`account_name`|账户名称|string|—|产品内账户名称|—|
|`is_custodian`|是否托管账户|bool|—|该账户是否为托管账户|—|
|`update_time`|最近导入时间|string / null|日期时间字符串|该账户最近一次导入的时间|从未导入时不出现该键|
|`message`|导入结论|string|—|最近一次导入的结论|取值只有 导入成功、部分成功、导入失败 与 从未导入|

<a id="confirmationcustodianitem"></a>

## 托管事件导入状态

CustodianEvents 来源下 `custodian_item` 的字段；该产品从未导入过托管事件文件时为空对象。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`update_time`|最近导入时间|string|日期时间字符串|该产品最近一次托管事件文件导入的时间|—|

## 枚举取值

<a id="confirmationsource"></a>

### 导入凭证来源

凭证来源由业务入口决定；`confirmations.latest` 的 `source` 参数、凭证列表与明细的 `source_enum` 都使用这些展示名。

|值|含义|
|---|---|
|`OpenAPI`|通过开放接口录入的流水|
|`IntraDayTrades`|盘中流水文件上传|
|`ValuationForm`|托管估值表导入|
|`EODTrades`|结算流水文件上传|
|`CustodianEvents`|托管事件文件导入|
|`PositionsStatement`|资产单元持仓单上传|
|`PositionsSheet`|产品持仓表写入|
