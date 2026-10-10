# unit_events 字段字典

需要用份额事件记录或更正产品份额变动时，按[份额事件操作](../unit_events.md)调用 `rqamsh.unit_events.create/update`，再用 `list` 核对。本页只列字段与业务含义；写入必填、折算与删除规则见[份额事件操作](../unit_events.md)，本页不逐行重复。`product_id` 由目标 resource 确定，`daily_units` 中不含该字段。

表中使用 JSON 类型：日期为 `YYYY-MM-DD` 字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值，不代表写入时允许省略或传 `null`；输入必填项和省略行为按对应操作规则执行。缺失或 `null` 均不等于 `0`，不能自行补值；份额单位是份，不是金额。

<a id="unitevent"></a>

## 份额事件

`daily_units` 中每一项的形状，也是手工事件保存后的内容。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`date`|事件日期|string|YYYY-MM-DD|份额变动发生的日期|不等同写入时间|
|`subscription_units`|申购份额|number / null|份|当次申购份额|与 `redemption_units` 二者只出现一个非空值|
|`redemption_units`|赎回份额|number / null|份|当次赎回份额|与 `subscription_units` 二者只出现一个非空值|
|`source`|事件来源|string（枚举）|—|事件的产生方式；枚举[份额事件来源](#uniteventsource)|查询返回只出现 `manual` 与 `auto`|
|`product_share`|归属份额|string / null|—|事件归属的分类份额名称|分类份额定义见[分类份额估值](balances.md#productsharevalue)|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读；修改与删除只能使用手工事件的 ID|

<a id="uniteventcreateinput"></a>

## 写入折算字段

`create` 接受的输入字段，请求发出前折算为[份额事件](unit_events.md#unitevent)的份额字段；其余业务校验按[份额事件操作](../unit_events.md#create)执行。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`unit_event_type`|份额事件类型|string（枚举）|—|本次变动是申购还是赎回；枚举[份额事件类型](#uniteventtype)|—|
|`units`|变动份额|number|份|本次变动的份额数量|折算为对应的申购或赎回份额，另一字段写成 `null`|

<a id="uniteventchange"></a>

## 逐日份额变动

`unit_changes` 中每一项的形状，按日期把当日全部手工与自动事件合计。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品|与 `daily_units` 不同，本项包含产品 ID|
|`date`|日期|string|YYYY-MM-DD|汇总日期|—|
|`subscription_units`|当日申购份额|number|份|当日全部事件申购份额之和|当日无申购事件时合计为 0|
|`redemption_units`|当日赎回份额|number|份|当日全部事件赎回份额之和|当日无赎回事件时合计为 0|
|`units`|当日产品份额|number / null|份|该日估值结果中的产品份额|来自估值结果，不是事件的合计；该日暂无结果时为空，不等于 0|

## 枚举取值

<a id="uniteventsource"></a>

### 份额事件来源

份额事件按产生方式区分：手工录入的事件可修改与删除，其余来源由业务过程生成、只读。枚举成员只有 `manual`、`from_custodian_event`、`from_reconciliation`、`from_trade` 四个值；`auto` 是查询返回中的折叠值，不是枚举成员。

|值|含义|
|---|---|
|`manual`|手工录入的申购或赎回|
|`from_custodian_event`|由托管事件折算生成的份额变动|
|`from_reconciliation`|由对账流程生成的份额变动|
|`from_trade`|由交易流水生成的份额变动|
|`auto`|查询返回中的折叠值，代表上述任一种自动来源|

<a id="uniteventtype"></a>

### 份额事件类型

手工份额事件的类型，取值决定本次份额变动是增加还是减少；写入规则见[份额事件操作](../unit_events.md#create)。

|值|含义|
|---|---|
|`subscription`|申购：份额增加|
|`redemption`|赎回：份额减少|
