# 自定义标的与公允价 custom_instruments

自定义标的是用户在 AMS 中登记的一项投资资产，适用于行情库（[合约基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)、[全部合约](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-all_instruments)）没有覆盖、或需要自行提供估值价格的资产。公允价是用来衡量这项资产在某个日期价值的价格。登记资产和价格本身不代表已经买入，实际持有情况仍由业务资料决定。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

资产资料和价格记录的结构见[自定义标的与公允价字段](fields/custom_instruments.md)。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|找到已有场外或自定义资产|`list` 按产品、品种或关键词筛选 → 取记录 ID 调 `get`|代码、类别与归属产品正确；价格历史必须通过 get 查看|
|为未覆盖资产建立估值信息|核对产品及代码 → `create` → `get` → 上传或替换公允价|取得 customized_ins_id，基础信息与所需日期价格均正确；不代表已建立持仓|
|更新一段价格或纠正全部历史|先 `get` 保存旧价格 → 按覆盖范围选择 `upload_fairvalue` 或 `replace_fairvalues` → 再 `get`|所需历史日期完整且价格正确，再检查关联产品的重算状态与头寸报表|
|改名称、代码或归属 / 删除标的|`get` 核对关联关系 → `update` 或经授权 `delete` → 重新查询|基础信息符合要求或目标记录已移除；价格修改不能用普通 update|
|给某只未覆盖的代码补某日价格|确认产品与代码 → `insert_fairvalues` 提交该日期价格 → 检查重算状态与头寸报表|目标日期价格已写入且其他日期未受影响；重复日期以更新而非重复记录结束|





## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。替换示例中的产品、instrument_id 和文件路径；写入、覆盖和删除须获得授权。价格文件或 JSON 数组需按本页覆盖规则准备，不能把示例 ID 当作资产代码。
权限：instrument_id 必须对应当前工作空间可访问的标的。产品归属标的需要产品可访问；修改/删除/价格导入另需写权限。无归属历史标的同空间可读但仅创建者可写（归属由服务端判定）；改归属时需同时具备原目标与新产品的相应权限。批量删除要求所有 ID 均匹配，越权由服务端或网关拒绝。客户端不预判读取级别。list 的 total 为可访问结果分页前数量；offset/limit 不可为负，limit=0 与省略均表示不限制条数。

## list
查询当前工作空间自定义标的，列表不含公允价历史。

Python 签名：`rqamsh.custom_instruments.list(*, resource: str | None=None, asset_class: str | None=None, q: str | None=None, offset: int | None=None, limit: int | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str \| None`|`None`|可选归属产品唯一 ID 或名称；不支持产品组。|
|`asset_class`|`str \| None`|`None`|按模式匹配的过滤条件，不做枚举取值校验；传非白名单值不会报错，只是可能匹配不到记录。|
|`q`|`str \| None`|`None`|服务端名称或代码搜索字符串。|
|`offset`|`int \| None`|`None`|分页起始偏移。|
|`limit`|`int \| None`|`None`|单页数量。|

返回：含 `customized_instruments` 与 `total` 的对象；列表不含公允价历史。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`customized_instruments`|自定义标的列表|array（object 元素）|—|当前工作空间内可访问的自定义标的；元素键见[自定义标的基本信息](fields/custom_instruments.md#customizedinstrument)，但整体不含 `fair_values`|恒返回；客户端已按归属产品可访问性过滤，并按 offset / limit 本地切片|
|`total`|可访问标的数量|integer|条|客户端过滤后、分页前的可访问标的条数|恒返回；分页在客户端完成，因此它不是服务端返回的原始总数|

结果检查：读取 customized_instruments 与 total；分页时继续查询直到取得需求范围内结果。列表不含 fair_values，不能据此判断标的尚无价格。

```python
result = rqamsh.custom_instruments.list()
```

```console
rqamsh custom-instruments list 
```

## get
读取自定义标的及完整公允价历史。

Python 签名：`rqamsh.custom_instruments.get(instrument_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`instrument_id`|`str`|必填|自定义标的记录 ID，不是 order_book_id。|

返回：服务端标的原始 JSON，根对象就是该标的，含完整公允价历史。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|自定义标的|object|—|一个自定义标的；键名与[自定义标的与价格历史](fields/custom_instruments.md#customizedinstrument)一致（`asset_class`、`order_book_id`、`symbol`、`user_id`、`workspace_id`、`create_time`、`product_id`、`fair_values`、`id`）|恒返回；`product_id` 可为空，情形见[自定义标的与价格历史](fields/custom_instruments.md#customizedinstrument)|
|`fair_values`|完整公允价历史|array（object 元素） / null|—|该标的的全部公允价记录；元素键为 `date`(YYYY-MM-DD) 与 `value`，由 JSON 全量替换写入的记录还带 `customized_ins_id`|恒返回；元素结构与单位见[公允价历史数组展开](fields/custom_instruments.md#公允价历史数组展开)|

结果检查：核对记录 ID、代码、类别、归属产品及 fair_values 的日期覆盖。将修改前历史保存为可回查数据，再进行价格替换或归属调整。

```python
result = rqamsh.custom_instruments.get(instrument_id='0123456789abcdef01234567')
```

```console
rqamsh custom-instruments get --instrument-id "0123456789abcdef01234567"
```

## create
在指定产品下创建自定义标的。
[完整字段](fields/custom_instruments.md)。创建时必须给出归属产品：当前服务端没有无归属产品的创建入口（按流水自动建档的标的同样归属导入产品），归属后只能改绑（见 [update](#update)），不能解除；归属产品的价格变更重算范围见 [upload_fairvalue](#upload_fairvalue)。相同工作空间、品种、代码和归属产品组合重复会失败。list 不返回 fair_values，get 才包含完整历史。

Python 签名：`rqamsh.custom_instruments.create(resource: str, asset_class: str, order_book_id: str, symbol: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|归属产品唯一 ID 或名称，必须是当前可访问的产品；不存在时请求失败。|
|`asset_class`|`str`|必填|当前服务端只接受 stock、otc_option、otc_futures、other_fund、total_return_swap、bond、repo、reverse_repo 这 8 个取值；超出取值范围会被拒绝。|
|`order_book_id`|`str`|必填|自定义资产代码。|
|`symbol`|`str`|必填|资产名称。|

返回：原始 `customized_ins_id`；同空间、产品、类别及代码重复会失败。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`customized_ins_id`|新建标的记录 ID|string|—|服务端记录 ID（字符串），后续 `get` 与价格写入都用它|恒返回；同一工作空间内品种、代码与归属产品组合重复时整体失败，不返回该键|

操作检查：同空间、品种、代码和产品组合不能重复。保存 customized_ins_id 并用 get 核对，再准备价格；创建标的本身不会替用户录入交易或持仓。

```python
result = rqamsh.custom_instruments.create(resource='授权测试产品', asset_class='other_fund', order_book_id='TEST-ASSET-001', symbol='授权测试标的')
```

```console
rqamsh custom-instruments create --resource "授权测试产品" --asset-class "other_fund" --order-book-id "TEST-ASSET-001" --symbol "授权测试标的"
```

## update
局部修改自定义标的基础字段，不修改价格历史。

Python 签名：`rqamsh.custom_instruments.update(instrument_id: str, *, resource: str | None=None, asset_class: str | None=None, order_book_id: str | None=None, symbol: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`instrument_id`|`str`|必填|自定义标的记录 ID。|
|`resource`|`str \| None`|`None`|新归属产品唯一 ID 或名称；省略保持不变。只能改绑到另一个产品，不能清空归属。|
|`asset_class`|`str \| None`|`None`|新资产类别，取值范围与 [create](#create) 相同；省略保持不变。|
|`order_book_id`|`str \| None`|`None`|新资产代码；省略保持不变。|
|`symbol`|`str \| None`|`None`|新名称；省略保持不变。|

返回：服务端原始 `effect_count`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际修改的标的数|恒返回；提交值与现值相同（记录未变化）时为 `0`；见[写入结果](connection.md#write-result)|

操作检查：至少提供一个实际要修改的基础字段；下方示例修改名称。省略字段保持不变；返回后检查 effect_count 和 get，代码或归属变化还需核对已有流水与估值使用的标的。

```python
result = rqamsh.custom_instruments.update(instrument_id='0123456789abcdef01234567', symbol='调整后的标的名称')
```

```console
rqamsh custom-instruments update --instrument-id "0123456789abcdef01234567" --symbol "调整后的标的名称"
```

## delete
批量删除自定义标的。

Python 签名：`rqamsh.custom_instruments.delete(instrument_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`instrument_ids`|`list[str]`|必填|非空自定义标的记录 ID 数组，不接受资产代码。|

返回：服务端原始 `effect_count`；具体删除约束由服务端执行。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的标的数|恒返回；客户端预检只保证 ID 在当前空间可见并能解析归属产品，真正删除约束由服务端执行，故 `effect_count` 可能小于提交条数，须用实际值核对本批结果，不承诺与提交条数相等；见[写入结果](connection.md#write-result)|

操作检查：先逐项确认记录 ID、产品归属和删除授权，保存需要留存的价格历史。任一 ID 未匹配或未授权时先修正目标；成功后核对 effect_count 与 list，不能把部分未匹配记录当作已删除。

```python
result = rqamsh.custom_instruments.delete(instrument_ids=['0123456789abcdef01234567'])
```

```console
rqamsh custom-instruments delete --instrument-ids '["0123456789abcdef01234567"]'
```

## upload_fairvalue
上传公允价文件，覆盖文件最早日期起的全部历史价格。
公允价变更会提交相关产品重算：有归属产品从价格最早日开始；历史共享标的会影响持有它的产品，起点与最早持有日期有关。上传价格不做汇率换算，应事先核对价格币种。不要上传空价格文件；空文件不保证是无操作。文件中每个日期只保留一条价格，不依赖重复日期的覆盖优先级；上传后用 get 核对历史。若要明确清空全部价格，使用 replace_fairvalues 的空数组并确认清空授权。

文件列为“日期”“公允价格”。只保留文件最早日期之前的旧价，最早日期及以后全部旧价由文件记录替换；文件没有包含的后续日期也会丢失。这不是逐日期增量更新。

Python 签名：`rqamsh.custom_instruments.upload_fairvalue(instrument_id: str, file_path: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`instrument_id`|`str`|必填|自定义标的记录 ID。|
|`file_path`|`str`|必填|本地价格文件路径，按原文件上传；不做汇率换算。|

返回：服务端原始 `effect_count`；相关产品可能被重算。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际覆盖的标的数|integer|条|本次实际覆盖价格历史的标的数：写入成功为 `1`|恒返回；文件没有可解析的价格行时服务端直接返回 `0`，既不覆盖历史也不提交重算，写入结果与现存价格相同时也是 `0`；见[写入结果](connection.md#write-result)|

操作检查：上传前保存旧价格，确认文件非空、日期唯一，并包含最早日期之后所有需要保留的价格。返回后用 get 对照完整历史；再检查关联产品估值，不能仅凭 effect_count 宣称价格已反映到头寸报表。

```python
result = rqamsh.custom_instruments.upload_fairvalue(instrument_id='0123456789abcdef01234567', file_path='prices.xlsx')
```

```console
rqamsh custom-instruments upload-fairvalue --instrument-id "0123456789abcdef01234567" --file-path "prices.xlsx"
```

## replace_fairvalues
全量替换公允价历史，空数组表示清空，遗漏日期不会保留。

提交完整 `[{'date':'YYYY-MM-DD','value':数字}]` 数组；`[]` 明确清空历史。所有希望保留的日期必须一起提交。价格不自动换算币种，变更会提交相关产品重算，需读回历史价格并核对估值。

Python 签名：`rqamsh.custom_instruments.replace_fairvalues(instrument_id: str, data: list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`instrument_id`|`str`|必填|自定义标的记录 ID。|
|`data`|`list[dict[str, Any]]`|必填|完整价格数组，每项含 date（YYYY-MM-DD）和 value（数值）。|

返回：服务端原始 `effect_count` 与逐项 `err_msg`；可能触发相关产品重算，需另行核对估值结果；`err_msg` 非空时抛部分失败异常。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际覆盖价格历史的标的数：写入成功为 `1`|恒返回；提交的完整数组与现存价格完全相同时为 `0`，此时不提交重算；见[写入结果](connection.md#write-result)|
|`err_msg`|逐项错误说明|array（string 元素） / null|—|按提交顺序说明哪一条价格为何未写入（如日期重复）|客户端在返回后调用 `partial_failure` 校验：`err_msg` 非空即抛 `partial_failure` 并保留完整结果，说明部分价格已写入，不能盲目整批重试；见[逐项失败容器](connection.md#item-errors)|

操作检查：data 是完整目标历史，不是增量补丁；提交前核对所有保留日期，空数组须有清空授权。返回后用 get 比对 fair_values，并检查关联产品的重算状态及受影响日期头寸报表；抛 `partial_failure` 时按 `err_msg` 只重发失败项，避免覆盖已成功写入的价格。

```python
import json
from pathlib import Path

result = rqamsh.custom_instruments.replace_fairvalues(instrument_id='0123456789abcdef01234567', data=json.loads(Path("fairvalues.json").read_text(encoding="utf-8")))
```

```console
rqamsh custom-instruments replace-fairvalues --instrument-id "0123456789abcdef01234567" --input @fairvalues.json
```

## insert_fairvalues
按归属产品增量写入通用公允价，用于给行情库没有覆盖的代码提供某日价值，不要求先建立自定义标的记录。

与另两个价格操作的区别：`upload_fairvalue` 和 `replace_fairvalues` 作用于自定义标的历史（由 `instrument_id` 定位、整体覆盖），本操作作用于产品级通用公允价记录，按 `(产品, 日期, 资产类别, 代码)` 增量写入，同日同标的记录被更新，其他日期不受影响。

其 `asset_class` 取全量[资产品种与会计科目](fields/others.md#assetclass)，不受自定义标的允许取值范围限制（自定义标的的范围见 [create](#create)）。

写入会从本次最早日期开始提交该产品重算；`field` 为 `fair_value` 且代码以 `.XHKG` 结尾时，服务端按当日 [港币汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk) 折算传入值，因此传折算前价格。

Python 签名：`rqamsh.custom_instruments.insert_fairvalues(resource: str, data: list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|归属产品唯一 ID 或名称，不是 instrument_id。|
|`data`|`list[dict[str, Any]]`|必填|非空公允价数组，每项含 order_book_id、asset_class、date、symbol、value；可含 field。|

返回：服务端原始返回，根为数组，即本轮**新增**记录的 ID 数组；被更新（同日同标的已存在）的记录不出现在其中。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|新增记录 ID|string|—|本次实际新插入的通用公允价记录 ID；同日同标的已存在的记录按更新处理，不计入|恒返回；提交项全部命中已有记录时为空数组；只有写入结果会出现在这里，服务端是否受理重算不体现在返回值中|

操作检查：空数组在客户端被拒绝，不会发出请求，也不会起到清空作用（清空请用 `replace_fairvalues`）。返回的 ID 数量小于提交条数说明部分记录被更新；服务端判定为重复创建时返回错误，应先用 [`balances.get`](balances.md#get) 核对该日期已有记录。本块 `get(instrument_id)` 读取的是 `customized_instruments/{id}`，只能核对自定义标的的 `fair_values`，不适用于产品级通用公允价记录，不能用它核对。写入后检查产品重算状态与受影响日期的头寸报表。

```python
result = rqamsh.custom_instruments.insert_fairvalues(
    resource='授权测试产品',
    data=[{
        'order_book_id': 'CUSTOM001', 'asset_class': 'stock', 'date': '2026-01-05',
        'symbol': '授权测试标的', 'value': 12.5, 'field': 'fair_value',
    }],
)
```

```console
rqamsh custom-instruments insert-fairvalues --resource "授权测试产品" --input @fairvalues_insert.json
```
