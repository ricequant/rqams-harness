# custodian_events 字段字典

需要用托管事件建立或更正权益、费用与科目调整输入时，按[托管事件操作](../custodian_events.md)调用 `rqamsh.custodian_events.create/update`，再用 `list` 核对。本页只列字段与业务含义；写入必填、省略与覆盖规则见[托管事件操作](../custodian_events.md)，本页不逐行重复；各事件类型进入估值后改动哪些科目、现金与份额见[事件类型与计算影响](../custodian_events.md#custodian-event-calculation)。`product_id` 由目标 resource 确定，列表返回不含该字段。

表中使用 JSON 类型：日期为 `YYYY-MM-DD` 字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值，不代表写入时允许省略或传 `null`；输入必填项和省略行为按对应操作规则执行。查询可能只返回部分字段（未设置的字段被省略），缺失或 `null` 均不等于 `0`、`false` 或空数组，不能自行补值参与估值。金额不自动缩放，未声明单位的数字不要猜测为万元或百分数。

<a id="custodiantevent"></a>

## 托管事件

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`custodian_event_type`|托管事件类型|string（枚举）|—|事件业务类型；枚举[托管事件类型](#custodianeventtype)|—|
|`date`|出入账日期|string|YYYY-MM-DD|资金实际出入账的日期|不等同写入时间|
|`amount`|金额|number|金额；主估值人民币|事件金额；按事件类型落到现金、应付或应收科目、或申赎折算份额上|按份额赎回时由服务端用 `redemption_units` × `unit_net_value` 覆盖|
|`sr_open_date`|申赎开放日期|string / null|YYYY-MM-DD|该笔申赎对应的开放日；仅申赎类事件有业务含义，只登记开放日当天单位净值，不改头寸、份额与净资产——申购与赎回份额按 `unit_net_value` 折算|缺省取出入账日的前一交易日，且不能晚于出入账日期（见 [create](../custodian_events.md#create)）|
|`product_cost_type`|托管事件费用类别|string / null（枚举）|—|产品费用实付的费用种类，决定冲减哪个应付科目；枚举[托管事件费用类别](#custodianeventcosttype)|仅产品费用实付使用；与[产品费用类别](products.md#productcosttype)不是同一枚举；签约费直接减现金|
|`adjust_operation`|科目调整操作|string / null（枚举）|—|金额相对调整项的方向；枚举[科目调整操作](#adjustoperation)|份额净资产调整与科目调整使用|
|`adjust_target`|调整目标科目|string / null|—|科目调整的目标资产类别，调整后的余额记在该科目的头寸记录上|仅科目调整使用；枚举[资产品种与会计科目](others.md#assetclass)|
|`unit_net_value`|申赎单位净值|number / null|每单位份额金额/净值|申赎业务的单位净值，申购与赎回份额按其折算（不按开放日净值反查）|仅申赎类事件使用|
|`effective_date`|权益生效日期|string / null|YYYY-MM-DD|权益归属的生效日期|仅产品分红与赎回款出账有业务含义，缺省取出入账日；份额结算与资金收付的两段口径见[事件类型与计算影响](../custodian_events.md#custodian-event-calculation)|
|`product_share`|归属份额|string / null|—|事件归属的分类份额名称，决定自动份额事件的归属与分类应付明细|份额产品的申赎事件使用；分类份额定义见[分类份额估值](balances.md#productsharevalue)|
|`redemption_units`|赎回数量|number / null|份|按份额赎回时提交的赎回份额|仅赎回款出账使用|
|`remarks`|备注|string / null|—|业务备注|—|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读|

文件导入的列名、归属与覆盖范围见[托管事件操作](../custodian_events.md#upload_file)，本页不重复文件格式。

## 枚举取值

<a id="adjustoperation"></a>

### 科目调整操作

托管事件里 `adjust_operation` 表示金额相对调整项的方向；份额净资产调整只支持调增与调减。

|值|含义|
|---|---|
|`increase`|调增：按金额增加目标项|
|`decrease`|调减：按金额减少目标项|
|`adjust_to`|调整到：把目标项调整为给定金额，仅科目调整支持|

<a id="custodianeventcosttype"></a>

### 托管事件费用类别

产品费用实付事件的费用种类；与[产品费用类别](products.md#productcosttype)不是同一枚举，后者用于产品配置中的费用计提比例。两个枚举互相独立，取值前 5 项同名，两表不得合并使用。

|值|含义|
|---|---|
|`management_fee`|管理费|
|`custodian_fee`|托管费|
|`sales_and_service_fee`|销售服务费|
|`operation_fee`|运营费|
|`performance_pay`|业绩报酬|
|`signing_fee`|签约费|

<a id="custodianeventtype"></a>

### 托管事件类型

托管事件的业务类型；各事件类型要求的必填字段见[托管事件操作](../custodian_events.md#create)。

|值|含义|
|---|---|
|`subscription_fund_received`|申购款入账|
|`redemption_paid`|赎回款出账|
|`product_cost_paid`|产品费用实付|
|`product_dividend_paid`|产品分红|
|`subject_adjusted`|科目调整|
|`product_share_equity_adjusted`|份额净资产调整|
