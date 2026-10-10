# 产品组 product_groups

产品组把多只已经存在的产品放在一起观察，用于查看它们合在一起的资产和投资表现。例如，用户可以把同一策略下的几只基金组成一个产品组。成员产品仍各自独立，产品组不代替它们保存和修改业务资料。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

成员、权重及其他配置的含义见[产品组字段](fields/products.md#productgroup)。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|查看已有组合的构成|`list` 找组 → `get` 核对成员 ID、权重、基准与起始日|确认组的成员和计算口径，而不只匹配组名|
|把多个产品组成加权分析对象|先用 `rqamsh.products.list` 获取成员 ID → 准备配置 → `create` → `get`|取得 product_group_id 且成员配置正确；再读取组头寸报表或指标核对分析结果|
|换成员、调权重或调整起点|保存原配置 → `update` → `get`；需主动刷新组结果时 `recompute`|配置变更已生效，组头寸报表/指标可读取并符合新口径；成员产品本身需要重算时另行操作|
|移除组合但保留产品|核对组 ID → `delete` → `list`|组不再可见；成员产品仍独立存在|





## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。替换示例目标并准备实际 JSON 配置，写入和删除须获得授权。成员使用产品 ID，不使用名称；本组只维护组合，不把写操作广播到成员产品。

## list
列出当前用户可访问的产品组；返回含 product_groups 的对象。

Python 签名：`rqamsh.product_groups.list()`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|—|—|无参数|当前显式连接身份|

返回：含 `product_groups` 的对象；数组元素是产品组对象，键与本页 [`get`](#get) 的返回表一致（目录逐个读取组详情组装，详情不可读的组不进目录）。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_groups`|可访问产品组列表|array（object 元素）|—|当前身份可访问的产品组；元素为产品组对象，键见本页 [`get`](#get) 返回表|恒返回；空数组表示当前身份没有可列出的组，不代表工作空间内没有其他组|

结果检查：从 product_groups 中选择组 ID；空数组表示当前身份没有可列出的组，不证明其他成员或工作空间没有该组。

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

结果检查：核对 product_ids、product_weights、benchmark 及日期。后续按唯一 ID 操作，避免同名组误选；组配置不等于成员产品配置。

```python
result = rqamsh.product_groups.get(resource='授权测试产品组')
```

```console
rqamsh product-groups get --resource "授权测试产品组"
```

## create
创建产品组，服务端校验成员权限并在配置有效时提交组重算。
[产品组完整字段](fields/products.md#productgroup)。create 必填 name、report_name、product_ids、benchmark、description、label、start_date、trading_start_date；成员必须使用产品 ID，不能放产品名称；基准行情见[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)。label 取值见[产品标签](fields/products.md#productlabel)；成员权限也需满足创建要求。

<a id="group-date-constraints"></a>**起始日规则（创建与更新共用）**

`start_date` 是显式输入字段，服务端只校验下面的区间，不按成员起始日自动推导。

- `start_date`（组估值起始日）与 `trading_start_date`（组交易起始日）创建时都必填；`trading_start_date` 不能早于 `start_date`。
- 组计算以 `start_date` 为起点：该日与再平衡日同样按成员目标权重起算。
- 权重组（`product_weights` 非空）：`start_date` 不能早于所有成员都有单位净值的最早日期（权重组按成员单位净值加权，成员净值不齐时组结果不可得），也不能晚于成员中最早的到期日；若该最早日期不存在（成员从未同时有净值），任何 `start_date` 都会被拒绝。
- 聚合组（不提供权重）：`start_date` 不能早于成员最早的 `start_date`（不要求成员已有净值）；不校验到期日上限，可以晚于成员到期日。
- 读取语义：组结果只在 `[start_date, 成员最早到期日]` 内可见，请求区间与它取交集；交集内缺日报未就绪，区间外不返回结果、也不回退到更早的旧结果。无成员或 `start_date` 为空（配置无效）时不返回任何组结果，避免读到配置变更前的旧结果。
- `start_date` 属于计算配置：校验通过且有成员时，创建与真实变更都会提交组重算；展示字段（name/report_name/description）变化不提交。
- `rebalance_frequency` 同属计算配置，变更影响与成员、权重、起始日相同（取值见[产品组调仓频率](fields/products.md#rebalancefreq)）。

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
修改产品组；成员变化会调整组访问权限，计算配置变化可能触发组重算。
product_weights 是产品 ID→权重的 JSON 对象；不要自行假设任意权重会被归一化。空权重修改须同时提供 product_ids。成员变更会更新组权限；成员、权重、起始日、调仓频率等计算配置改变可能提交组计算，name/report_name/description 等展示字段不因自身变更而重算。起始日校验与创建相同（见[起始日规则](#group-date-constraints)）；清空成员且未显式提供 `start_date` 时该字段被置空。

Python 签名：`rqamsh.product_groups.update(resource: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品组唯一 ID 或名称。|
|`data`|`dict[str, Any]`|必填|需修改字段；product_weights 为空时须同时提供 product_ids。|

返回：服务端原始 `effect_count`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际更新的产品组数，按命中记录数计|恒返回；请求体没有任何可更新字段时为 `0`，成功更新为 `1`；提交值与现值相同也计 `1`，因此它不代表配置真的发生了变化；见[写入结果](connection.md#write-result)|

操作检查：提交前保存原成员与权重；清空 product_weights 时同时给 product_ids。返回后检查 effect_count 并用 get 核对；成员变更会影响组访问权限，计算配置变更还需核对组头寸报表或指标。

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

返回：原始 `submit_recompute_count`；提交成功不表示计算完成。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`submit_recompute_count`|已提交重算的组数|integer|个|本次从组起始日提交重算匹配到的产品组数|恒返回；单组操作为 `1`，目标组不属于当前工作空间时为 `0`；只是提交计数，不代表计算完成或结果已就绪|

完成条件：submit_recompute_count 只表示提交数量。随后读取组头寸报表或指标并按[等待规则](connection.md)等待可用结果；若成员产品数据尚未正确估值，应先处理成员，单独重算组不能替代该步骤。

```python
result = rqamsh.product_groups.recompute(resource='授权测试产品组')
```

```console
rqamsh product-groups recompute --resource "授权测试产品组"
```
