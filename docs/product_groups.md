# 产品组 product_groups

产品组把多只已经存在的产品放在一起观察，用于查看它们合在一起的资产和投资表现。例如，用户可以把同一策略下的几只基金组成一个产品组。成员产品仍各自独立，产品组不代替它们保存和修改业务资料。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

成员、权重及其他配置的含义见[产品组字段](fields/products.md#productgroup)。


## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。替换示例目标并准备实际 JSON 配置，写入和删除须获得授权。成员使用产品 ID，不使用名称；本组只维护组合，不把写操作广播到成员产品。

## list
列出当前用户可访问的产品组；返回后台产品组列表对象。

Python 签名：`rqamsh.product_groups.list()`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|—|—|无参数|当前显式连接身份|

返回：含 `product_groups` 的列表对象；SDK 只发一次集合请求，用响应的 `permissions[].group_id` 排除明确拒绝的非所有者记录，并同步调整已有的 `total` 与 `permissions`，见[资源权限](permissions.md#可见不等于可写)。列表项可含 `accessible`、`accessible_err_msg`，不等同于 [`get`](#get) 的完整配置。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_groups`|可访问产品组列表|array（object 元素）|—|后台按当前身份返回的产品组列表项；可含配置字段与 `accessible`、`accessible_err_msg`、`permissions` 等视图字段|恒返回；范围与字段由后台裁定、可受权限裁剪；空数组表示当前身份没有可列出的组，不代表工作空间内没有其他组；完整配置按组 ID 用 [`get`](#get) 读取|

结果检查：从 product_groups 中选择组 ID；空数组表示当前身份没有可列出的组，不证明其他成员或工作空间没有该组。列表项与 get 不是同一份配置：`accessible` 只说明组配置是否可用，不表示调用方有读取权限；需要完整成员、权重或日期配置时按组 ID 用 `get` 复核，缺失成员的判定方法见该操作的返回说明，不要用该次结果判定成员已不在组内。

```python
result = rqamsh.product_groups.list()
```

```console
rqamsh product-groups list 
```

## get
读取产品组配置。

Python 签名：`rqamsh.product_groups.get(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品组唯一 ID 或名称。|

返回：服务端产品组对象，根对象就是该组；除配置字段外还带成员摘要与可访问性判定。

列表项与这里的完整配置不是同一份数据：`get` 按组 ID 读取完整配置与成员摘要；`list` 不逐项读取详情。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|产品组对象|object|—|一个产品组；配置字段 `name`、`report_name`、`product_ids`、`benchmark`、`description`、`create_time`、`user_id`、`workspace_id`、`trading_start_date`、`start_date`、`label`、`product_weights`、`rebalance_frequency`、`id` 的含义见[产品组配置](fields/products.md#productgroup)；基准行情见[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)，另有下列视图字段|恒返回；`label` 取值见[产品标签](fields/products.md#productlabel)，清空成员且未显式提供起始日的组 `start_date` 为 `null`|
|`products`|成员产品摘要|array（object 元素）|—|成员产品摘要（产品配置字段的子集），元素键见[产品配置](fields/products.md#product)：`id`、`name`、`data_source`、`start_date`、`trading_start_date`、`investment_category`、`strategy_category`、`benchmark`、`calendar`、`realtime_period_type`、`maturity_date`、`closing_date` 等；成员 `calendar` 对应的交易日序列见[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)|恒返回；只含缓存中可解析的成员，`product_ids` 中有但缓存缺失的成员不出现|
|`maturity_date`|成员最早到期日|string / null|YYYY-MM-DD|组结果可见区间的上界，取成员最早到期日|由数据决定；无成员或成员缓存缺失时为 `null`|
|`realtime_period_type`|组实时监控时段|string（枚举） / null|—|成员共用的实时监控时段|由数据决定；成员实时时段不一致时为 `null`，取值见[实时监控时段](fields/products.md#realtimeperiodtype)|
|`strategy_category`|成员策略类别合集|array（string 元素）|—|按成员顺序列出各成员策略类别|恒返回；取值见[投资策略类别](fields/products.md#strategycategory)|
|`is_agg_by_weights`|是否权重组|boolean|—|`true` 为按成员权重加权的权重组，`false` 为聚合组|恒返回；与 `product_weights` 是否为空等价|
|`accessible`|组配置是否可用|boolean|—|成员未到期、未被删除且实时时段一致时为 `true`|恒返回；不表示调用方有读取权限|
|`accessible_err_msg`|组不可用原因|array（string 元素）|—|逐条说明成员已到期、成员已删除、成员实时时段不一致|恒返回；`accessible` 为 `true` 时为空数组|

结果检查：核对 product_ids、product_weights、benchmark 及日期。后续按唯一 ID 操作，避免同名组误选；组配置不等于成员产品配置。以 `product_ids` 与 `products[].id` 的差集判断成员缓存是否缺失：`product_ids` 里有而 `products[].id` 未出现的成员，按[未就绪与缺输入](connection.md#unready-inputs)稍后重试同一读取，不要把缺失成员当作已不在组内或组配置不一致。

```python
result = rqamsh.product_groups.get(resource='授权测试产品组')
```

```console
rqamsh product-groups get --resource "授权测试产品组"
```

## create
创建产品组。通过校验且组有成员、估值起始日非空时，从组起始日提交组自身重算；否则不提交。
[产品组完整字段](fields/products.md#productgroup)。create 必填 name、report_name、product_ids、benchmark、description、label、start_date、trading_start_date；成员必须使用产品 ID，不能放产品名称；基准行情见[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)。label 取值见[产品标签](fields/products.md#productlabel)；成员权限也需满足创建要求。

### 创建时的推荐起点

以下由调用方显式组织，SDK 不自动补值；用户明确配置优先，仅用于新建，不在更新时覆盖原配置。

|字段|推荐值或处理方式|适用条件与注意事项|
|---|---|---|
|`label`|`live`|普通实盘产品组；模拟产品组按实际选 `paper` 等标签|
|`report_name`|与 `name` 相同|名称由用户指定并查重|
|`benchmark`|`{"type":"index","id":"000300.XSHG"}`|未指定时采用沪深 300；已有明确基准时按实际提交|
|`description`|`""`|没有说明时传空字符串；该键仍是创建必填项|
|`product_ids`|用户指定的成员产品 ID|不默认全空间、不传名称、不自动增加成员|
|组类型|聚合组|未要求权重组合时不传 `product_weights` 与 `rebalance_frequency`；不把聚合误当等权收益组合|
|`product_weights`|仅权重组传产品 ID → 小数权重|按用户指定权重；明确要求等权才等分，权重合计为 1（如两只各 `0.5`），不传百分数 `50`|
|`rebalance_frequency`|`daily`|仅权重组的默认调仓频率；其他频率按实际要求|
|`start_date`|聚合组取成员最早起始日；权重组取所有成员同时有单位净值的最早日期|调用方查询并显式提交；权重组可用 `balances.field_earliest_date(resources=[成员ID], field="unit_net_value")` 获取共同最早日期，不逐个日期猜测|
|`trading_start_date`|与本次 `start_date` 相同|实际交易起始日更晚时按实际填写；不得早于估值起始日|

权重组没有共同净值日期时不能用当天或成员成立日替代；完整日期与日历边界见下文。

<a id="group-date-constraints"></a>**起始日规则（创建与更新共用）**

`start_date` 是显式输入字段，服务端只校验下面的区间，不按成员起始日自动推导。

- `start_date`（组估值起始日）与 `trading_start_date`（组交易起始日）创建时都必填；`trading_start_date` 不能早于 `start_date`。
- 组计算以 `start_date` 为起点：该日与再平衡日同样按成员目标权重起算。
- 权重组（`product_weights` 非空）：`start_date` 不能早于所有成员都有单位净值的最早日期（权重组按成员单位净值加权，成员净值不齐时组结果不可得），也不能晚于成员中最早的到期日；若该最早日期不存在（成员从未同时有净值），任何 `start_date` 都会被拒绝。
- 聚合组（不提供权重）：`start_date` 不能早于成员最早的 `start_date`（不要求成员已有净值）；不校验到期日上限，可以晚于成员到期日。
- 读取语义：组结果只在 `[start_date, 成员最早到期日]` 内可见，请求区间与它取交集；交集内缺日报未就绪，区间外不返回结果、也不回退到更早的旧结果。无成员或 `start_date` 为空（配置无效）时不返回任何组结果，避免读到配置变更前的旧结果。
- 起始日与调仓频率的修改是否提交组重算，见 [更新](#update)；调仓频率取值见[产品组调仓频率](fields/products.md#rebalancefreq)。

<a id="group-calendar"></a>**组日历（由成员推导）**

组本身没有日历字段，组日历是成员集合的属性：成员非空且日历完全一致（取值见枚举[估值日历](fields/products.md#calendartype)）时沿用该日历，成员日历缺失、成员之间混合取值或取值无效时一律按自然日推进。按自然日推进不会跳过非交易日，因此混合日历的组会在成员的非交易日也产出结果。

能力边界：权重组的调仓日期推进只支持 `exchange` 与 `natural`，不支持成员日历全部为 `exchange_hkt` 的组合。需要按港股通共同开市日统计时，不要通过修改成员日历来绕过这一限制，否则会改变业务口径。纯聚合组不经过调仓日期判断，不受这项权重组限制。

Python 签名：`rqamsh.product_groups.create(data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`data`|`dict[str, Any]`|必填|产品组 JSON；必含 name、report_name、product_ids、benchmark、 description、label、start_date、trading_start_date；成员使用产品 ID。|

返回：原始 `product_group_id`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_group_id`|新建产品组 ID|string|—|服务端记录 ID（字符串）|恒返回；配置有效（有成员且设置估值起始日）时创建即提交组重算，不代表组结果已就绪；同名或成员无权限时整体失败，不返回该键|

操作检查：确认全部成员可访问，权重与日期合法；同名或成员权限错误应修正后再提交。保存 product_group_id 并用 get 核对配置，再读取组头寸报表或指标，不能用创建返回值证明估值已完成。

```python
import json
from pathlib import Path

result = rqamsh.product_groups.create(data=json.loads(Path("product-group.json").read_text(encoding="utf-8")))
```

```console
rqamsh product-groups create --input @product-group.json
```

## update
修改产品组配置。`product_weights` 是产品 ID 到权重的 JSON 对象，不要假定任意权重会被归一化；清空权重须同时提供 `product_ids`。提交成员配置时服务端会按该配置重新核对组权限，不改成员产品自己的权限。起始日校验与创建相同（见[起始日规则](#group-date-constraints)）；清空成员且未显式提供 `start_date` 时该字段被置空。

更新后有成员且有估值起始日，并且 `label`、`product_ids`、`product_weights`、`start_date`、`trading_start_date`、`benchmark`、`rebalance_frequency` 中至少一项实际变化时，从更新后的 `start_date` 提交组自身重算，不逐个重算成员。只重排成员、提交等值配置，或只改 `name`、`report_name`、`description` 时不提交；没有成员或估值起始日也不提交。

Python 签名：`rqamsh.product_groups.update(resource: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品组唯一 ID 或名称。|
|`data`|`dict[str, Any]`|必填|需修改字段；product_weights 为空时须同时提供 product_ids。|

返回：服务端原始 `effect_count`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际更新的产品组数，按命中记录数计|恒返回；没有字段需要写入时为 `0`，命中并执行更新为 `1`，提交值与现值相同也计 `1`；见[写入结果](connection.md#write-result)|

操作检查：提交前保存原成员与权重；涉及成员配置时也保存可读取的组权限。返回后检查 `effect_count`，用 `get` 核对配置；涉及成员配置时另用 [`permissions.list`](permissions.md#list) 核对组权限。组权限先于组配置更新；同时改成员和名称时，即使随后因名称冲突未保存组配置，已调整的权限也不会回滚。这种失败同样要先读回组配置与组权限，再决定如何修正。发生重算时读取组头寸报表或指标，不能用 `effect_count` 代替计算结果。

```python
import json
from pathlib import Path

result = rqamsh.product_groups.update(resource='授权测试产品组', data=json.loads(Path("update.json").read_text(encoding="utf-8")))
```

```console
rqamsh product-groups update --resource "授权测试产品组" --input @update.json
```

## delete
删除产品组及其权限，不删除成员产品。

Python 签名：`rqamsh.product_groups.delete(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品组唯一 ID 或名称。|

返回：服务端原始 `effect_count`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的产品组数（同次同时清除该组的全部权限记录）|恒返回；删除成功为 `1`；见[写入结果](connection.md#write-result)|

操作检查：确认删除的是组而非成员产品，返回后核对 effect_count 和组列表。删除组不会删除成员；若需求是删除成员产品，需要单独授权并使用 products 操作。

```python
result = rqamsh.product_groups.delete(resource='授权测试产品组')
```

```console
rqamsh product-groups delete --resource "授权测试产品组"
```

## recompute
从组起始日提交产品组自身重算，不逐个重算成员。

Python 签名：`rqamsh.product_groups.recompute(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品组唯一 ID 或名称。|

返回：原始 `submit_recompute_count`，统计匹配到并发起重算请求的组数，不是任务受理或完成计数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`submit_recompute_count`|匹配到的产品组数|integer|个|本次发起重算请求时在当前空间命中的组数|恒返回；命中单组返回 `1`，服务端未匹配到组时为 `0`|

完成条件：读取组头寸报表或指标并按[等待规则](connection.md)核对可用结果；若成员产品数据尚未正确估值，应先处理成员，单独重算组不能替代该步骤。

```python
result = rqamsh.product_groups.recompute(resource='授权测试产品组')
```

```console
rqamsh product-groups recompute --resource "授权测试产品组"
```
