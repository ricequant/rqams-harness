# 份额事件 unit_events

份额事件是产品份额发生变化的手工记录，只有申购和赎回两类，记的是份额而不是金额。它是估值与对账的输入之一：与[托管事件](custodian_events.md)不同，托管事件记金额，份额事件记份额；随流水、对账或托管事件自动生成的事件在这里只读。

## 字段说明

事件字段与来源枚举见[份额事件字段](fields/unit_events.md)。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|查看某产品的手工与自动份额事件|`list` 限定日期|手工项来源为 manual、自动项折叠为 auto；两类都在同一个数组里，按日期倒序|
|核对某日份额变动与当日份额|`list` 读取 unit_changes 的申购、赎回与 units|当日 units 来自估值结果，与事件份额是两回事；没有估值结果时该字段为空，属依赖估值未产出，见[未就绪与缺输入](connection.md#unready-inputs)|
|录入一笔或一批手工申购、赎回|准备 JSON，必含 unit_event_type、date、units → `create` → `list` 复核|effect_count 与预期条数一致；服务端不返回新记录 ID，须用 list 取回 ID|
|更正手工事件的份额|`list` 取得手工事件 ID → `update` 提交两个份额字段 → `list` 复核|该事件的申购或赎回份额已按提交值更新；自动事件 ID 会得到 404|
|删除误录的手工事件|`list` 确认手工事件 ID → `delete` → 重新查询|effect_count 与所选条数一致；自动事件不受影响，删除不可撤销|

## API 使用约定

Python 与 CLI 完成相同业务操作，连接、任务等待及部分失败处理见[连接说明](connection.md)。替换示例产品与事件 ID；写入和删除须获得授权。网关上读取要求 `read_import_data`，写入要求目标产品 `write`；客户端不预判权限。

日期为 YYYY-MM-DD，枚举传英文值，取值见[份额事件类型](fields/unit_events.md#uniteventtype)与[份额事件来源](fields/unit_events.md#uniteventsource)。事件日期不能晚于今天，也不能晚于产品到期日；申购与赎回必须且只能提供其中一个；份额产品必须填写 product_share，且该份额需在事件日期有效；估值报告数据源的产品不支持录入份额事件；封账与静态会计保护仍按事件日期判断，但 `create` 走的服务端批量接口不做封账日与起始日校验（见 [create](#create)）。

服务端批量接口接受的是 subscription_units / redemption_units，不接受 units 与 unit_event_type。本项目在客户端按同一规则折算后提交：

|提交字段|提交示例|实际请求体|
|---|---|---|
|申购|`{"unit_event_type": "subscription", "date": "2026-01-05", "units": 1000.0}`|`[{"date": "2026-01-05", "subscription_units": 1000.0, "redemption_units": null}]`|
|赎回|`{"unit_event_type": "redemption", "date": "2026-01-05", "units": 500.0}`|`[{"date": "2026-01-05", "subscription_units": null, "redemption_units": 500.0}]`|

## list
列出产品份额事件与逐日份额变动。

Python 签名：`rqamsh.unit_events.list(resource: str, *, start_date: str | None=None, end_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设下界。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设上界。|

返回：服务端原始对象，含 `daily_units` 与 `unit_changes`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`daily_units`|手工与自动事件列表|array（object）|—|手工事件与自动事件的合并列表，按日期倒序；元素为一条[份额事件](fields/unit_events.md#unitevent)：`date`(YYYY-MM-DD)、`subscription_units` / `redemption_units`(number 或空，份)、`source`(枚举；查询返回只出现 `manual` 与 `auto`)、`product_share`(string 或空)、`id`(字符串 ID)|恒返回；不含 `product_id`|
|`unit_changes`|逐日份额变动|array（object）|—|按日期把当日全部事件合计；元素为一条[逐日份额变动](fields/unit_events.md#uniteventchange)：`product_id`(字符串 ID)、`date`、`subscription_units` / `redemption_units`(number，份)、`units`(number 或空，份)|恒返回；此项含 `product_id`，`units` 来自估值结果，为 `null` 表示该日依赖的估值尚未产出|

结果检查：需要修改或删除时只能使用 source 为 manual 的 id；单位净值与金额属于托管事件，不要在本方法的结果里找。`unit_changes[].units` 为 `null` 表示该日依赖的估值尚未产出，不要把它当作零份额；按[未就绪与缺输入](connection.md#unready-inputs)确认计算状态后就绪再读同一结果。

```python
result = rqamsh.unit_events.list(resource='授权测试产品', start_date='2026-01-01', end_date='2026-01-31')
```

```console
rqamsh unit-events list --resource "授权测试产品" --start-date 2026-01-01 --end-date 2026-01-31
```

## create
新增一个或多个手工份额事件。

传入单个对象或其非空数组；两种写法发送完全相同的请求体。每项必含 unit_event_type（subscription 或 redemption）、date、units；份额产品还需 product_share。`unit_event_type` 只接受 `subscription` 与 `redemption`，其他值在请求发出前即被拒绝；两种类型必须且只能设置一个份额字段。客户端把 units 折算为服务端的 subscription_units/redemption_units 后提交，源字段 source 由服务端固定为 manual，不接受手工提交（查询返回里的 `auto` 是折叠值，见[份额事件来源](fields/unit_events.md#uniteventsource)）。

服务端逐项处理：能解析的事件写入并计入 effect_count，解析失败的事件按序号写入 err_msg（缺少日期、日期格式错误、未指定申购/赎回份额），两者可以同时出现。约束违规不是逐项错误：申购与赎回同时给出、份额产品缺 product_share、估值报告数据源产品等会整批失败。批量接口不返回新记录 ID，插入后请用 `list` 取回。

批量接口也不做封账日与起始日校验——那是单条录入才有的守卫，因此本方法允许写入落在封账日之前或产品起始日之前的日期，需要该保护时请先自行核对日期区间。

Python 签名：`rqamsh.unit_events.create(resource: str, data: dict[str, Any] | list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称；估值报告数据源的产品会被服务端拒绝。|
|`data`|`dict[str, Any] \| list[dict[str, Any]]`|必填|单个事件对象或其非空数组，元素必含 unit_event_type、date、units。|

返回：服务端原始结果；有可写入事件时含 `effect_count`，存在解析失败项时含 `err_msg`，两者可同时出现，`err_msg` 非空时抛部分失败异常。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际写入条数|integer|条|本批成功写入的份额事件条数|有可写入事件时才返回；批量接口不返回新记录 ID，须用 `list` 取回|
|`err_msg`|逐项解析失败说明|array（string 元素）|—|按提交顺序说明第几个事件为何失败（缺日期、日期格式错误、未指定申购/赎回份额）|存在解析失败项时才返回；见[逐项失败容器](connection.md#item-errors)|

结果检查：核对 effect_count 与提交条数；出现部分失败时按 err_msg 的序号定位问题事件，修正后只重发失败项，避免重复写入已成功的事件。

```python
result = rqamsh.unit_events.create(
    resource='授权测试产品',
    data=[
        {"unit_event_type": "subscription", "date": "2026-01-05", "units": 1000.0},
        {"unit_event_type": "redemption", "date": "2026-01-12", "units": 500.0},
    ],
)
```

```console
rqamsh unit-events create --resource "授权测试产品" --input @unit_events.json
```

## update
修改一个手工份额事件的份额。

只能修改手工事件；自动事件 ID 会得到 404。未提供的字段沿用原事件，因此可以只提交需要改变的份额值，但 subscription_units 与 redemption_units 必须同时给出（其中一个为 null）。

Python 签名：`rqamsh.unit_events.update(resource: str, unit_event_id: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`unit_event_id`|`str`|必填|`list` 返回的手工事件 ID。|
|`data`|`dict[str, Any]`|必填|必须同时含 subscription_units 与 redemption_units（其一可为 null），可选 product_share。|

返回：服务端原始 `effect_count`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际修改的事件条数|恒返回；提交内容与现值相同时为 `0`，不代表事件不存在；见[写入结果](connection.md#write-result)|

结果检查：用 `list` 复核该事件的份额与来源；把申购改成赎回时两个字段都要显式给出，否则会被服务端按「只设置一个」规则拒绝。

```python
result = rqamsh.unit_events.update(
    resource='授权测试产品',
    unit_event_id='6a1f4c2e9b3d4f5a6b7c8d90',
    data={"subscription_units": None, "redemption_units": 800.0},
)
```

```console
rqamsh unit-events update --resource "授权测试产品" --unit-event-id 6a1f4c2e9b3d4f5a6b7c8d90 --input @unit_event.json
```

## delete
按事件 ID 批量删除手工份额事件。

Python 签名：`rqamsh.unit_events.delete(resource: str, unit_event_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`unit_event_ids`|`list[str]`|必填|非空手工事件 ID 数组；空数组在发送前即被拒绝。|

返回：服务端原始 `effect_count`；自动事件保存在另一处，传自动事件 ID 不会命中。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的手工事件条数|恒返回；ID 不存在或指向自动事件时为 `0`；见[写入结果](connection.md#write-result)|

结果检查：删除前确认 ID 来自 source 为 manual 的记录；删除不可撤销并触发必要重算，可用 `list` 重新确认事件与份额变动已消失。

```python
result = rqamsh.unit_events.delete(resource='授权测试产品', unit_event_ids=['6a1f4c2e9b3d4f5a6b7c8d90'])
```

```console
rqamsh unit-events delete --resource "授权测试产品" --unit-event-ids '["6a1f4c2e9b3d4f5a6b7c8d90"]'
```
