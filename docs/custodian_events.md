# 托管事件 custodian_events

托管事件是产品收到或支付权益、费用，以及调整会计科目的业务记录，例如申购款入账、赎回款出账、产品分红、产品费用实付、份额净资产调整和科目调整。它们是估值与对账的输入之一，与[份额事件](unit_events.md)分开维护：托管事件记的是金额，份额事件记的是份额。

## 字段说明

事件字段与枚举见[托管事件字段](fields/custodian_events.md)；文件导入的列名与覆盖范围见下方 [upload_file](#upload_file)。

<a id="custodian-event-calculation"></a>

## 事件类型与计算影响

托管事件进入估值后只改两类东西：**会计科目余额**与**份额**。科目在头寸报表里是一条 `asset_class` 为科目名的记录，数量就是金额（负债科目的数量是负债金额），现金是其中的活期存款科目；事件不会改变股票、债券、基金、期货、期权等证券持仓的数量。金额、单位净值、份额与净资产的关系见[头寸字段字典](fields/balances.md)，本页不重复公式。

|事件类型|改什么|改在哪一天|是否改份额|
|---|---|---|---|
|申购款入账 `subscription_fund_received`|活期存款增加、当日净投入增加|出入账日|按[份额策略](fields/products.md#unit-policy)生成申购份额＝金额 ÷ 申赎单位净值|
|赎回款出账 `redemption_paid`|权益生效日：其他应付款（`other_payable`）增加、当日净投入减少；出入账日：冲回该应付款、活期存款减少|权益生效日与出入账日（可能同一天）|生效日生成赎回份额＝金额 ÷ 申赎单位净值|
|产品费用实付 `product_cost_paid`|按费用类别冲减对应应付科目（计提管理费、计提托管费、计提销售服务费、计提运营费、计提业绩报酬）；签约费直接减活期存款|出入账日|不改|
|产品分红 `product_dividend_paid`|权益生效日：其他应付款增加，并按金额计入当日每份分红；出入账日：冲回该应付款、活期存款减少|权益生效日与出入账日（可能同一天）|不改|
|科目调整 `subject_adjusted`|按[科目调整操作](fields/custodian_events.md#adjustoperation)改 `adjust_target` 科目：调增与调减按金额加减，调整到把余额设为给定金额|出入账日|不改|
|份额净资产调整 `product_share_equity_adjusted`|不改科目、现金与产品净资产，只改指定分类份额的净资产|出入账日|不改|

赎回款出账与产品分红是「两段式」，与其余类型的区别在生效日：**权益生效日**（`effective_date`，缺省取出入账日）记应付并结算份额、当日净投入按流出计；**出入账日**（`date`）才冲回应付、减少现金。两天相同时当天走完两段、应付款科目归零；不同时应付先挂账、支付日结清，而份额变化只发生在生效日。产品分红只减少净资产与单位净值（累计每份分红按生效日累计），不减少份额。

其余口径：

- 调减不会把负债科目做成负数：科目余额不足时先把该科目冲到 0，超出部分转入活期存款。
- 产品费用实付的归属份额只对管理费与业绩报酬有分类明细；托管费、销售服务费、运营费按母产品口径计入，不要填 `product_share`。
- 事件不产生交易流水。份额是否自动生成取决于产品的[份额策略](fields/products.md#unit-policy)：自动份额的产品按申赎金额与申赎单位净值折算并写入份额事件，手工修改份额的产品只改现金与科目、份额由手工份额事件决定；此时申赎金额会直接改变单位净值。
- 当日净投入按当日重算、不是现金余额变化；估值表覆盖日的当日盈亏会把当日托管现金流单独扣除，口径见[头寸字段字典](fields/balances.md#net-cash-in)与[当日盈亏](fields/balances.md#daily-pnl)。
- 日内的实时快照与分钟序列同样应用当日事件，实时截面里的科目与现金已反映当天已录入的事件。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|查看某产品在某个区间的托管事件|`list` 限定日期与类型|日期、类型、金额与调整项符合业务原始记录；列表项不含产品 ID，归属由 resource 决定|
|查各产品最近一次录入到哪一天|`latest`|只返回当前身份可见产品的日期；没有事件的产品不出现|
|录入一笔或一批托管事件|准备 JSON，必含 custodian_event_type 与 date → `create` → `list` 读回|effect_count 与预期条数一致；服务端不返回新记录 ID，须用 list 按日期区间取回 ID|
|更正已录入的事件|`list` 取得事件 ID → `update` 提交完整字段 → `list` 复核|该事件字段被整体覆盖；未提供的可选字段不会保留原值|
|删除误录事件|`list` 确认 ID 与日期 → `delete`|effect_count 与所选条数一致；删除不可撤销并触发必要重算|
|用文件批量导入并留痕|确认文件列与归属产品 → `upload_file` → `confirmations.list` 或 `confirmations.latest('CustodianEvents')` 核对|err_msg 逐行说明问题，confirmation_ids 可下载源文件复核|

导入按产品整体覆盖：`upload_file` 对每个产品从文件内最早事件日期起先删除同产品既有事件，再写入文件内容，所以它是区间覆盖而不是增量追加。先导入再手工补录请在导入之后执行，否则补录会被下一次导入覆盖。

## API 使用约定

Python 与 CLI 完成相同业务操作，连接、任务等待及部分失败处理见[连接说明](connection.md)。替换示例产品、事件 ID 与文件路径；写入、覆盖和删除须获得授权。网关上读取要求 `read_import_data`，写入与文件导入要求目标产品 `write`；客户端不预判权限。

日期为 YYYY-MM-DD；枚举传英文值，取值见[托管事件类型](fields/custodian_events.md#custodianeventtype)、[托管事件费用类别](fields/custodian_events.md#custodianeventcosttype)与[科目调整操作](fields/custodian_events.md#adjustoperation)。事件日期不能晚于产品到期日，封账与静态会计保护按出入账日期或权益生效日期判断，服务端拒绝时会说明具体原因。部分失败异常保留完整结果，不保证已写入内容回滚。

## list
列出产品托管事件。

Python 签名：`rqamsh.custodian_events.list(resource: str, *, start_date: str | None=None, end_date: str | None=None, custodian_event_type: str | None=None, adjust_target: str | None=None, offset: int | None=None, limit: int | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设下界。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设上界。|
|`custodian_event_type`|`str \| None`|`None`|托管事件类型，取值见[托管事件类型](fields/custodian_events.md#custodianeventtype)。|
|`adjust_target`|`str \| None`|`None`|科目调整目标资产类别；省略返回全部调整目标。|
|`offset`|`int \| None`|`None`|跳过条数；省略由服务端按 0 处理。|
|`limit`|`int \| None`|`None`|返回条数上限；省略由服务端按全部处理。|

返回：服务端原始对象，含事件数组与条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`custodian_events`|托管事件列表|array（object 元素）|—|筛选命中的托管事件，按出入账日期倒序；元素键与[托管事件](fields/custodian_events.md#custodiantevent)一致，但不含 `product_id`|恒返回；无命中时为空数组；归属产品由 `resource` 决定，不能从列表项读出|
|`total`|记录条数|integer|条|筛选条件下的托管事件条数|恒返回；只由筛选条件决定，不受 `offset`、`limit` 影响|

结果检查：核对 date、custodian_event_type、amount 与调整项是否为业务原始值；省略日期不设该端限制，不能把默认全量列表当作某个区间或某个产品的结果。记录 ID 从本方法取回，供 update 与 delete 使用。

```python
result = rqamsh.custodian_events.list(resource='授权测试产品', start_date='2026-01-01', end_date='2026-01-31', custodian_event_type='product_dividend_paid')
```

```console
rqamsh custodian-events list --resource "授权测试产品" --start-date 2026-01-01 --end-date 2026-01-31
```

## latest
读取工作空间内各产品的最新托管事件日期。

Python 签名：`rqamsh.custodian_events.latest()`。

返回：产品 ID 到最新日期字符串的映射（工作空间级读取，只需登录）；`{product_id}` 是动态键，不是实际 JSON 键名。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`{product_id}`|最新事件日期|string|YYYY-MM-DD|该产品已有托管事件的最晚出入账日期|由数据决定：只包含当前身份在目录中可见、且已有事件的产品；值是日期而不是事件记录|

结果检查：日期是「该产品已有事件的最晚日期」，不代表估值已到该日；核对前先确认产品是否在可见范围内，缺失产品不等于没有事件。

```python
result = rqamsh.custodian_events.latest()
```

```console
rqamsh custodian-events latest
```

## create
新增一个或多个托管事件。

传入单个对象或其数组；两种写法发送完全相同的请求体（都是 JSON 数组），因此不会出现「单条走一条路由、批量走另一条」的差异。必填字段只有 custodian_event_type 与 date，其余按事件类型要求：

- 申赎事件（subscription_fund_received、redemption_paid）省略 sr_open_date 时取出入账日前一交易日，且不能晚于出入账日期；必须提供为正的 unit_net_value；份额产品必须填写 product_share。
- redemption_paid 同时提供 redemption_units 时，服务端按 redemption_units × unit_net_value 覆盖 amount。
- effective_date 仅产品分红与赎回款出账支持，省略时按出入账日期，且不能晚于出入账日期。
- 产品费用实付必须提供 product_cost_type；科目调整必须提供 adjust_target 与 adjust_operation；份额净资产调整必须提供 product_share，金额须为正数，且 adjust_operation 只能是调增或调减。

服务端批量接口不返回新记录 ID，插入后请用 `list` 按日期区间取回。

Python 签名：`rqamsh.custodian_events.create(resource: str, data: dict[str, Any] | list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`data`|`dict[str, Any] \| list[dict[str, Any]]`|必填|单个事件对象或其非空数组，元素必含 custodian_event_type 与 date。|

返回：服务端原始写入结果，只含插入条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际写入条数|integer|条|本批成功插入的托管事件条数|恒返回；批量接口不返回新记录 ID，须用 `list` 取回；见[写入结果](connection.md#write-result)|

结果检查：effect_count 应等于提交的事件条数；条数不符时用 `list` 按同一日期区间核对实际落库内容。写入会触发必要的重算，返回成功不代表估值已完成，需要时再用 `products.compute_state` 确认计算状态。

```python
import json
from pathlib import Path

events = [
    {"custodian_event_type": "product_dividend_paid", "date": "2026-01-05", "amount": 10000.0, "effective_date": "2026-01-05"},
    {"custodian_event_type": "product_cost_paid", "date": "2026-01-06", "amount": 1500.0, "product_cost_type": "management_fee"},
]
result = rqamsh.custodian_events.create(resource='授权测试产品', data=events)
```

```console
rqamsh custodian-events create --resource "授权测试产品" --input @events.json
```

## update
按事件 ID 整体覆盖修改一个托管事件。

服务端用旧 ID 覆盖写入本次请求构造的事件，因此**未提供的可选字段不会保留原值**：需要保留的字段必须随请求一起提交。事件类型的必填规则与 `create` 相同，封账判断取原事件日期与本次生效日期中较早的一个。

Python 签名：`rqamsh.custodian_events.update(resource: str, custodian_event_id: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`custodian_event_id`|`str`|必填|`list` 返回的事件 ID。|
|`data`|`dict[str, Any]`|必填|事件字段，必含 custodian_event_type 与 date。|

返回：服务端原始写入结果，只含修改条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际覆盖写入的事件条数|恒返回；ID 不属于该产品时服务端返回 404，不产生本返回；见[写入结果](connection.md#write-result)|

结果检查：修改后用 `list` 复核完整字段，重点核对被覆盖掉的调整项、费用类型与备注是否符合预期；不要在未读取原值的情况下局部提交。

```python
result = rqamsh.custodian_events.update(
    resource='授权测试产品',
    custodian_event_id='6a1f4c2e9b3d4f5a6b7c8d90',
    data={"custodian_event_type": "product_dividend_paid", "date": "2026-01-05", "amount": 12000.0},
)
```

```console
rqamsh custodian-events update --resource "授权测试产品" --custodian-event-id 6a1f4c2e9b3d4f5a6b7c8d90 --input @event.json
```

## delete
按事件 ID 批量删除托管事件。

Python 签名：`rqamsh.custodian_events.delete(resource: str, custodian_event_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`custodian_event_ids`|`list[str]`|必填|非空事件 ID 数组；空数组在发送前即被拒绝。|

返回：服务端原始结果，命中计数以实际响应为准。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的事件条数|由数据：服务端原始结果，命中计数以实际响应为准，见[写入结果](connection.md#write-result)|

结果检查：删除前用 `list` 确认 ID 与日期；删除不可撤销，会触发必要重算。

```python
result = rqamsh.custodian_events.delete(resource='授权测试产品', custodian_event_ids=['6a1f4c2e9b3d4f5a6b7c8d90'])
```

```console
rqamsh custodian-events delete --resource "授权测试产品" --custodian-event-ids '["6a1f4c2e9b3d4f5a6b7c8d90"]'
```

## upload_file
用一个文件批量导入一个或多个产品的托管事件，并生成导入凭证。

文件支持 CSV 与 Excel，按「产品名称」列归属到 products 中选定的产品，因此多个产品可以共用一份文件。

|列名|是否必填|对应字段|说明|
|---|---|---|---|
|产品名称|必填|归属产品|必须匹配所选 products 中的产品名称|
|申赎开放日期|必填|`sr_open_date`|仅申赎类事件有业务含义|
|出入账日期|必填|`date`|YYYY-MM-DD|
|事件类型|必填|`custodian_event_type`|传中文业务名称，例如申购款入账、赎回款出账、产品分红|
|金额|必填|`amount`|数值|
|费用类型及调整项|必填|`product_cost_type` 或 `adjust_target`|按事件类型填写费用种类或调整目标科目|
|申赎单位净值|必填|`unit_net_value`|数值|
|备注|必填|`remarks`|可为空字符串|
|权益生效日期|可选|`effective_date`|仅产品分红与赎回款出账有业务含义|
|归属份额|可选|`product_share`|份额产品的申赎事件必填|
|赎回数量|可选|`redemption_units`|仅赎回款出账使用|

文件列与事件字段不同名是正常现象：解析时按上表换算，问题行按行号进入 `err_msg`。

两个列的取值有固定名单，写文件时照抄：

|「事件类型」列取值|对应事件类型|
|---|---|
|申购款入账、申购、认购、份额调增|申购款入账 `subscription_fund_received`|
|赎回款出账、赎回、份额调减|赎回款出账 `redemption_paid`|
|产品分红、现金分红|产品分红 `product_dividend_paid`|
|产品费用实付|产品费用实付 `product_cost_paid`|
|份额净资产调增、份额净资产调减|份额净资产调整 `product_share_equity_adjusted`，同时决定[科目调整操作](fields/custodian_events.md#adjustoperation)为调增或调减|
|调增、调减、调整到|科目调整 `subject_adjusted`，同时决定[科目调整操作](fields/custodian_events.md#adjustoperation)|

|「费用类型及调整项」列取值|适用事件类型|
|---|---|
|管理费、托管费、业绩报酬、运营费、销售服务费、签约费（见[托管事件费用类别](fields/custodian_events.md#custodianeventcosttype)）|产品费用实付|
|科目中文名：活期存款、结算备付金、存出保证金、证券清算款、应收股利、其他应收利息、应收申购款、其他应收款、其他资产、现金类负债、其他应付利息、计提管理费、计提销售服务费、计提托管费、计提业绩报酬、计提运营费、应付税、其他应付款、其他负债|科目调整与份额净资产调整，对应字段是 `adjust_target`|

不在名单内的类型名或科目名会让该行解析失败并写入 `err_msg`，同一文件的合法行仍会写入；文件缺少必填列则整批被拒绝。

导入是覆盖式的：对每个产品，服务端从文件内最早事件日期起删除该产品既有事件后再写入，因此文件必须包含该日期起的全部事件。解析失败的行进入 err_msg 并同时作为失败项记入凭证；合法行仍会写入，不整批回滚。

Python 签名：`rqamsh.custodian_events.upload_file(resources: list[str], file_path: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resources`|`list[str]`|必填|非空产品 ID/名称数组；服务端按 form 的 product_ids 归属事件。|
|`file_path`|`str`|必填|本地托管事件文件路径，CSV 或 Excel。|

返回：服务端原始写入结果，含写入条数、逐行错误与凭证 ID。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际写入条数|integer|条|本批合法行写入的托管事件条数|恒返回；导入按产品覆盖写入，此数不含解析失败行|
|`err_msg`|逐行解析失败说明|array（string 元素）|—|按行说明哪一行为何失败，形如「第N行: …」|恒返回；无失败行时为空数组，非空即抛部分失败异常，见[逐项失败容器](connection.md#item-errors)|
|`confirmation_ids`|导入凭证 ID|array（string 元素）|—|本次为每个涉及产品生成的凭证 ID|恒返回；可用 `confirmations.list` 核对登记条数，用 `confirmations.download` 取回源文件|

结果检查：先核对 err_msg 中每一行的原因，再用 `confirmations.list` 或 `confirmations.latest('CustodianEvents')` 确认凭证与登记条数，需要时用 `confirmations.download` 取回源文件复核。客户端不预判权限：成员不存在或有歧义时请求不会发出，越权由服务端或网关拒绝。

```python
result = rqamsh.custodian_events.upload_file(resources=['授权测试产品'], file_path='custodian_events.xlsx')
```

```console
rqamsh custodian-events upload-file --resources '["授权测试产品"]' --file-path custodian_events.xlsx
```
