# 资产单元 asset_units

资产单元是一个产品内单独管理的一部分资产。例如，同一基金可以把分配给某项策略的资产作为一个单元，单独查看和核对。它依附于所属产品，不是一只新的基金，也不等同于券商账户。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

配置和持仓单结构见[资产单元字段](fields/asset_units.md)。

## 从用户需求到操作

|用户需求|操作顺序与目标|完成条件|
|---|---|---|
|找到产品内某个资产单元|`list(resource=产品)` → 取单元 ID 调 `get`|核对 symbol、代码和 product_id，避免把账户或产品当作单元|
|建立独立管理的资产单元|先核对产品支持流水数据源 → 准备代码、名称、起点及 bound_position → `create`|保存 insert_id 并用 list/get 核对配置，再检查产品重算后的估值|
|调整单元配置|`get` 保存原配置 → `update(resource=单元, data=...)` → `get`|目标五个业务字段符合预期，受影响的产品估值已核对|
|上传或核对单元持仓单|确认单元 ID 及 product_id → 使用 [positions_statements](positions_statements.md)|以持仓单详情核对日期和数量；单元创建本身不等于导入持仓|
|管理收益互换持仓的底层组合并对账|先按[资产单元与收益互换持仓](#asset-unit-binding)核对互换代码与绑定键 → `create` 对应资产单元 → 用 `positions_statements.list` 与 `reconciliation.asset_unit_diff` 核对数量|互换持仓的代码与资产单元同键、可用持仓候选已确认；缺件与差异能定位到具体单元|

<a id="asset-unit-binding"></a>

## 资产单元与收益互换持仓

收益互换（`asset_class=total_return_swap`）在产品头寸里只是一条合约，它背后的底层组合由资产单元承载。**绑定不是开关，而是隐式键匹配**：产品头寸中 `asset_class=total_return_swap` 的项与资产单元的 `(order_book_id, asset_class)` 同键，即视为该产品把这条互换持仓绑定到该资产单元；服务端没有独立的绑定字段或绑定表，因此创建时传入的 `bound_position` 不影响绑定结果。下面按业务链条逐条列出可核对的结论。

1. **互换代码来自 OTC 合约。** 创建入口是自定义合约的 `POST /customized_instruments`，其 `asset_class` 白名单包含 `total_return_swap`；代码由调用方在创建时给定，服务端不生成编号；流水导入也可按通道自动建档。同一工作空间、同一品种、同一代码且同一归属产品的重复创建会失败。
2. **该代码的流水形成产品上的互换持仓项。** 这些流水形成产品 `asset_class=total_return_swap` 的持仓项；`order_book_id` 命中自定义合约即判为 OTC 类型。
3. **可用持仓候选只来自本产品的互换持仓。** `GET /products/<product_id>/asset_units:get_available_positions` 只返回该产品的收益互换持仓。
4. **绑定是隐式键匹配，没有独立绑定字段或绑定表。** 产品头寸中的 `total_return_swap` 项与 `asset_unit_positions[(order_book_id, asset_class)]` 同键即视为绑定。
5. **`bound_position` 必填但已废弃。** 绑定判定与估值计算都不读它，因此不产生任何效果。
6. **资产单元独立估值，再据此推进母产品互换价格。** 计算服务先按 `max(计算起始日, 资产单元 start_date)` 取流水独立估值（行情价来自 [合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)）；当日盈亏汇总后推进互换价格「当日 = 前一天 + 当日资产单元盈亏 + 当日出入金」，首日为 `net_cash_in + daily_pnl`，有估值表价格时估值表优先。
7. **指标穿透。** 互换项被替换为资产单元持仓，参与股票市值、风险敞口、ETF 折溢价、期货期权结算判断与分钟级多空盈亏（实时行情见 [当前行情快照](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot)）。
8. **展示与产品组聚合。** 资产单元持仓打上 `asset_unit_id` 后与互换父项合并，非「保留互换」时父项被剔除。
9. **对账的缺件与差异。** 缺件集合 = 「已生效且当日持有同键互换持仓（数量大于 0）的资产单元」减去「当日已上传持仓单的资产单元」；资产单元级差异比较 `asset_unit_balances` 与持仓单的 `(asset_class, direction, order_book_id)` 数量并排除类现金；产品级差异把属于资产单元的键标 `is_asset_unit`。
10. **资产单元持仓单不参与估值。** 写入只做同日删旧、upsert、源文件入库与导入凭证，不触发重算、不覆盖资产单元头寸；计算时不把它作为覆盖估值表或覆盖持仓表输入。它与产品持仓表（`positions_sheets`）不是一回事。

创建资产单元时，独立参数 `bound_position` 必填但已废弃：服务端与计算都不读取它，绑定结果由上面的键匹配决定；`update(resource, data)` 的 `data` 是可选字段对象，可不含该键。字段口径见[资产单元字段](fields/asset_units.md#assetunit)。要让绑定生效，`asset_class` 应取 `total_return_swap`，默认 `asset_unit` 不会命中绑定键。



## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。替换示例资源与业务值，写入须获得授权。注意 create 的 resource 是产品，而 get/update 及持仓单方法使用资产单元；不要复用错误层级的名称或 ID。
list 可省略 resource 列出当前工作空间可访问单元，或传产品限定；get 只能传资产单元。get 输出含 product_id，调用持仓单方法时仅传单元，不需额外传归属产品。创建/更新会改变业务估值输入；本组没有资产单元 delete，不能用产品删除代替单元删除需求。

## list
列出当前工作空间可访问的资产单元，可按归属产品限定范围。

Python 签名：`rqamsh.asset_units.list(resource: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str \| None`|`None`|可选归属产品唯一 ID 或名称；省略列出当前工作空间可访问资产单元。|

返回：资产单元数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|资产单元|array（object 元素）|—|当前工作空间可访问的资产单元，元素键为 `id`、`product_id`、`asset_class`、`order_book_id`、`symbol`、`start_date`、`bound_position`，键名与[资产单元配置](fields/asset_units.md#assetunit)一致|恒返回；无可见单元时为空数组；省略 `resource` 时可能含多个产品的单元|

结果检查：按 product_id 和代码确认归属，再用 id 选择后续目标；省略 resource 时列表可能包含多个产品的单元。空列表不证明其他权限范围内没有单元。

```python
result = rqamsh.asset_units.list()
```

```console
rqamsh asset-units list 
```

## get
读取可访问资产单元的配置和归属产品。

Python 签名：`rqamsh.asset_units.get(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称（symbol），不是归属产品名称。|

返回：目录中的完整资产单元 JSON，根对象就是该单元配置。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|资产单元|object|—|一个[资产单元配置](fields/asset_units.md#assetunit)，键名为 `id`、`product_id`、`asset_class`、`order_book_id`、`symbol`、`start_date`、`bound_position`|恒返回；`asset_class` 为 `total_return_swap` 时才可能命中互换绑定键，见[资产单元与收益互换持仓](#asset-unit-binding)|

结果检查：核对 id、product_id、symbol、start_date 和 bound_position；同名歧义时用 list 得到的 ID 重查。读取单元配置不返回持仓单明细，数量对账需使用 positions_statements.list。

```python
result = rqamsh.asset_units.get(resource='授权测试资产单元')
```

```console
rqamsh asset-units get --resource "授权测试资产单元"
```

## create
在产品下创建资产单元并由服务端提交重算。

创建目标 resource 是产品，必须支持 trade 或混合数据源；order_book_id、symbol、start_date、bound_position 必填，asset_class 默认 asset_unit（要让绑定生效应取 total_return_swap）。其中 `bound_position` 已废弃：服务端与计算均不读取，绑定由键匹配决定，见[资产单元与收益互换持仓](#asset-unit-binding)和[资产单元字段](fields/asset_units.md#assetunit)。返回 insert_id/effect_count 并提交归属产品重算；创建成功不代表估值已完成。

Python 签名：`rqamsh.asset_units.create(resource: str, order_book_id: str, symbol: str, start_date: str, bound_position: bool, *, asset_class: str='asset_unit')`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|归属产品唯一 ID 或名称，须支持交易流水数据源。|
|`order_book_id`|`str`|必填|资产单元代码。|
|`symbol`|`str`|必填|资产单元名称。|
|`start_date`|`str`|必填|起始日期 YYYY-MM-DD。|
|`bound_position`|`bool`|必填|已废弃：必须显式传布尔值，但服务端与计算均不读取；绑定见[资产单元字段](fields/asset_units.md#assetunit)。|
|`asset_class`|`str`|`'asset_unit'`|资产类别，默认 asset_unit；取全量[资产品种与会计科目](fields/others.md#assetclass)，不受自定义标的允许取值范围限制。|

返回：服务端原始写入结果。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`insert_id`|新建记录 ID|string / null|字符串 ID|新建资产单元的记录 ID|恒返回；未插入时为 `null`；见[写入结果](connection.md#write-result)|
|`effect_count`|实际写入条数|integer|条|本次创建命中的记录数：成功为 `1`，未插入为 `0`|恒返回；见[写入结果](connection.md#write-result)|

操作检查：先确认产品数据源；`bound_position` 仍须显式传布尔值，但它不改变绑定结果，不能把它当作绑定开关。返回后保存 insert_id 并核对 effect_count 与 list/get；重算提交不代表头寸报表已就绪。

```python
result = rqamsh.asset_units.create(resource='授权测试产品', order_book_id='TEST-ASSET-001', symbol='授权测试标的', start_date='2026-01-01', bound_position=False)
```

```console
rqamsh asset-units create --resource "授权测试产品" --order-book-id "TEST-ASSET-001" --symbol "授权测试标的" --start-date "2026-01-01" --bound-position false
```

## update
修改资产单元，自动解析归属产品并提交重算。

更新目标 resource 是资产单元。data 可含 asset_class、symbol、order_book_id、start_date、bound_position，其中 `bound_position` 已废弃：服务端与计算均不读取，绑定由键匹配决定，见[资产单元与收益互换持仓](#asset-unit-binding)和[资产单元字段](fields/asset_units.md#assetunit)；更新后提交归属产品重算，需核对受影响的估值。

Python 签名：`rqamsh.asset_units.update(resource: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称，不是产品名称。|
|`data`|`dict[str, Any]`|必填|修改字段 JSON，可含 asset_class、symbol、order_book_id、start_date、bound_position（bound_position 已废弃，不改变绑定结果）。|

返回：服务端原始写入结果，只含修改条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际修改的资产单元记录数|恒返回；提交内容与现值相同时为 `0`，不代表单元不存在；见[写入结果](connection.md#write-result)|

操作检查：只提交用户要求修改的五个业务字段中的相关字段。返回后核对 effect_count 和 get；改起点、`asset_class` 或代码时还需检查归属产品的受影响估值（改 `bound_position` 不会改变绑定结果），不能只核对单元名称。

```python
import json
from pathlib import Path

result = rqamsh.asset_units.update(resource='授权测试资产单元', data=json.loads(Path("update.json").read_text(encoding="utf-8")))
```

```console
rqamsh asset-units update --resource "授权测试资产单元" --input @update.json
```
