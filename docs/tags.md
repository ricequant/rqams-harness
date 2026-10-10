# 标签 tags

标签是调用方私有的组织信息：给产品与产品组分组标注、方便自己筛选，它不参与估值、持仓与对账的任何计算。标签本身、标签与产品/产品组的绑定关系都只属于当前用户与当前工作空间，服务端已按身份过滤，Harness 不再二次筛选。

标签不是产品字段：产品上的 `label` 是一个取值固定的分类字段（见[产品标签](fields/products.md#productlabel)），与这里可自由命名的标签对象不是一回事。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|查看自己有哪些标签、各绑定了什么|`list`|返回的标签与绑定都属于当前身份；没有标签时是空数组|
|新建标签并挂到产品、产品组上|`upsert` 提交名称与绑定 ID → `list` 核对|写入按项返回结果；出现失败项时整体报 `partial_failure`，按 `details.failed` 只重试失败项|
|改名、改说明或调整绑定对象|`upsert` 带 `tag_id` 并提交完整的绑定数组 → `list` 核对|该标签只保留本次提交的绑定，未提交的绑定会被移除|
|不再需要某个标签|`delete` 传标签 ID 数组 → `list` 核对|返回 `effect_count`；产品与产品组本身不受影响|

## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。替换示例中的标签 ID、绑定 ID 与名称。本组在网关上只要求登录、不校验资源级别，越权由网关拒绝；写入与删除的请求体都是裸 JSON 数组，不接受对象包装，空数组由 Harness 在本地拒绝，不会发出请求。

绑定对象必须用 ID：`product_ids` 与 `product_group_ids` 的元素是 24 位十六进制 ObjectId。传产品或产品组名称会让该项失败，服务端不会按名称解析。

逐项处理时，客户端在 `detail` 中出现 `success` 为 `false` 的项时抛 `partial_failure`，并在 `details.failed` 保留诊断；失败项不一定带可用的 `tag_id`，需要另行核对后清理，避免留下无绑定的孤立标签。

## list

列出当前用户与工作空间的标签及其绑定对象。

Python 签名：`rqamsh.tags.list()`。

返回：根为数组的标签列表，根对象就是该数组；没有标签时是空数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|标签对象|object|—|一个标签及其绑定对象；键见下列 `[].…` 各行|恒返回|
|`[].tag_id`|标签 ID|string|—|标签记录 ID；`upsert` 更新与 `delete` 都按它定位|恒返回|
|`[].name`|标签名称|string|—|当前用户与工作空间内唯一的标签名|恒返回|
|`[].description`|标签说明|string|—|标签备注；从未设置过时为空字符串|恒返回|
|`[].product_ids`|绑定产品 ID 列表|array（string 元素）|—|该标签绑定的产品 ID|恒返回；空数组表示没有绑定产品|
|`[].product_group_ids`|绑定产品组 ID 列表|array（string 元素）|—|该标签绑定的产品组 ID|恒返回；空数组表示没有绑定产品组|

```python
tags = rqamsh.tags.list()
```

```console
rqamsh tags list
```

## upsert

批量创建或更新标签，并整体替换标签的绑定对象。

请求体是标签数组，服务端**逐项**处理：省略 `tag_id` 表示按名称创建，带 `tag_id` 表示更新该标签。整体是覆盖语义：某标签本次未提交的产品或产品组绑定不会保留。

Python 签名：`rqamsh.tags.upsert(tags: list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`tags`|`list[dict[str, Any]]`|必填|非空标签数组；元素可含 `tag_id`、`name`、`description`、`product_ids`、`product_group_ids`。|

返回：服务端响应对象，含顶层 `effect_count` 与逐项 `detail`；存在失败项时整体抛 `partial_failure`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|成功处理的标签项数|integer|条|本批 `detail[].success` 为 `true` 的标签项数，不是绑定变更条数|恒返回；`0` 表示所有项都失败或没有可处理项|
|`detail`|逐项处理结果|array（object 元素）|—|按提交顺序逐项给出 `tag_id`、`effect_count`（该标签本次新增或移除的绑定条数）、`success`、失败时的 `error_msg`|恒返回；元素结构与失败判定见[逐项失败容器](connection.md#item-errors)；创建失败（例如绑定 ID 非法或名称重复）时该项 `tag_id` 为 `null`|

出现失败项时 `details.failed` 给出失败项与服务端原因：成功的标签已经写入，只需按诊断重试失败项，不要整批重传。

```python
result = rqamsh.tags.upsert(tags=[{'name': '重点观察', 'product_ids': ['授权测试产品 ID']}])
```

```console
rqamsh tags upsert --tags '[{"name": "重点观察", "product_ids": ["授权测试产品 ID"]}]'
```

## delete

按标签 ID 批量删除标签及其绑定关系。

请求体是标签 ID 裸数组，不接受对象包装；空数组本地拒绝。删除标签只影响标签与绑定关系，不触碰产品或产品组本身。

Python 签名：`rqamsh.tags.delete(tag_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`tag_ids`|`list[str]`|必填|非空标签 ID 数组。|

返回：服务端响应对象，含 `effect_count`；不存在的 ID 不计入删除数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的标签数，只统计属于当前用户与当前工作空间的 ID|恒返回；`0` 表示提交的 ID 都不存在或不属于当前用户；见[写入结果](connection.md#write-result)|

```python
rqamsh.tags.delete(tag_ids=['标签 ID'])
```

```console
rqamsh tags delete --tag-ids '["标签 ID"]'
```
