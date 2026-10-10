# asset_units 字段字典

需要在产品内单独估值或绑定持仓时，使用[资产单元操作](../asset_units.md)的 `rqamsh.asset_units.create/update`，再以 `list/get` 核对归属产品、`symbol` 和配置。资产单元名称使用 `symbol`，ID 从返回记录取得，不是产品内账户。本页只列字段与业务含义；创建、更新与上传规则见[资产单元操作](../asset_units.md)和[持仓单操作](../positions_statements.md)，本页不逐行重复。`只读` 表示服务端生成。

需要数量对账时，使用[持仓单操作](../positions_statements.md)的 `rqamsh.positions_statements.upload/list`。持仓单仅支持文件上传；下表用于解释记录和准备对应通道文件内容，不是可直接提交的 JSON 写入格式。`list` 使用 `is_detail=True` 才含 `positions`；删除使用查询返回的 `positions_statement_id`，不要假设所有结果都叫 `id`。

持仓单只记录品种、方向、代码、名称、数量，不是完整估值报告，也不向券商发送交易。上传后按日期查询核对合并后的数量；同产品、资产单元、日期的合法持仓单会整体覆盖旧记录，不能将导入成功解释为自动改写计算头寸。

表中使用 JSON 类型：日期为 `YYYY-MM-DD` 字符串，日期时间为字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值，不代表写入时允许省略或传 `null`；输入必填项和省略行为按对应操作规则执行。查询可能只返回部分字段，缺失或 `null` 均不等于 `0`、`false` 或空数组，不能自行补值参与估值。金额不自动缩放，比例 `0.01` 表示 `1%`；未声明单位的数字不要猜测为万元或百分数。

<a id="assetunit"></a>

## 资产单元配置

资产单元配置，创建/更新与只读管理字段分列。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`asset_class`|资产类别|string（枚举）|—|枚举[资产品种与会计科目](others.md#assetclass)|创建时要让绑定生效，应取 `total_return_swap`（默认 `asset_unit` 不会命中绑定键），见[资产单元与收益互换持仓](../asset_units.md#asset-unit-binding)|
|`order_book_id`|证券/合约代码|string|—|不是自定义合约记录 ID|—|
|`symbol`|显示名称|string|—|标的或资产单元显示名称|—|
|`start_date`|起始日期|string|YYYY-MM-DD|产品/单元起始日期|—|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品 ID|由目标 resource 确定|
|`bound_position`|绑定持仓|boolean|布尔|已废弃的绑定标记：不参与绑定判定，也不参与计算与对账|create 时必填，update 的 `data` 可不含该键；服务端仅落库不读取；绑定由 `(asset_class, order_book_id)` 与产品收益互换持仓同键决定，见[资产单元与收益互换持仓](../asset_units.md#asset-unit-binding)|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读|

<a id="positionstatement"></a>

## 持仓单记录

持仓单记录，字段来自文件解析及查询；不是结构化上传契约。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品 ID|由目标 resource 确定|
|`asset_unit_id`|归属资产单元 ID|string|字符串 ID|归属资产单元 ID|由目标资产单元 resource 确定|
|`date`|业务日期|string|YYYY-MM-DD|业务日期，不等同写入时间|—|
|`file_name`|原上传文件名|string|—|原上传文件名|—|
|`fs_id`|原文件存储 ID|string|字符串 ID|服务端原文件存储 ID|只读|
|`positions`|持仓明细列表|array（object 元素）|—|持仓记录列表；<br>&emsp;展开见 [持仓单明细](asset_units.md#positionstatementposition)|—|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读|

<a id="positionstatementposition"></a>

## 持仓单数量明细

持仓单 `positions[]` 明细，只包含数量对账所需字段。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`positions[].asset_class`|资产类别|string（枚举）|—|枚举[资产品种与会计科目](others.md#assetclass)|—|
|`positions[].direction`|多空方向|string（枚举）|—|多空方向；枚举[多空方向](balances.md#direction)|—|
|`positions[].order_book_id`|证券/合约代码|string|—|不是自定义合约记录 ID|—|
|`positions[].symbol`|显示名称|string|—|标的或资产单元显示名称|—|
|`positions[].quantity`|数量|number|股/份/合约单位；依品种|持仓/成交数量；股票为股、基金为份、衍生品按合约单位|—|

<a id="positions-statement-latest"></a>

`positions_statements.latest` 的返回字段已移至[持仓单操作](../positions_statements.md#latest)，本页不再重复。
