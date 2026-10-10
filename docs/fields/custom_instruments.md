# custom_instruments 字段字典

需要维护行情未覆盖标的或独立公允价时，按[自定义标的操作](../custom_instruments.md)创建/更新品种、代码和名称。`instrument_id` 是记录 ID，`order_book_id` 是业务代码，两者不能互换。

- `rqamsh.custom_instruments.list` 用于找记录，不含历史价格；`get` 用于核对标的及 `fair_values`。
- 本页只列字段与业务含义；写入与覆盖规则见[自定义标的操作](../custom_instruments.md)，本页不逐行重复。`只读` 表示服务端生成。

价格不自动换汇。通用公允价记录仅供解释价格数据，不是自定义标的价格替换的请求格式。

表中使用 JSON 类型：日期为 `YYYY-MM-DD` 字符串，日期时间为字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值，不代表写入时允许省略或传 `null`；输入必填项和省略行为按对应操作规则执行。查询可能只返回部分字段，缺失或 `null` 均不等于 `0`、`false` 或空数组，不能自行补值参与估值。金额不自动缩放，比例 `0.01` 表示 `1%`；未声明单位的数字不要猜测为万元或百分数。

<a id="customizedinstrument"></a>

## 自定义标的与价格历史

自定义标的基本信息和历史价格。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`asset_class`|资产类别|string（枚举）|—|枚举[资产品种与会计科目](others.md#assetclass)|自定义标的只可能取其中 8 个取值，允许范围见[创建自定义标的](../custom_instruments.md#create)|
|`order_book_id`|证券/合约代码|string|—|不是自定义合约记录 ID|—|
|`symbol`|显示名称|string|—|标的或资产单元显示名称|—|
|`user_id`|创建/所属用户 ID|number（整数）|—|由请求身份确定|只读|
|`workspace_id`|所属工作空间 ID|string|字符串 ID|由请求身份确定|只读|
|`create_time`|创建时间|string|ISO 日期时间|业务对象创建时间|只读|
|`product_id`|归属产品 ID|string / null|字符串 ID|归属产品 ID|由目标 resource 确定；为空仅出现在无归属产品的历史标的上|
|`fair_values`|完整历史价格列表|array（object 元素） / null|—|自定义合约完整历史价格列表|get 返回|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读|

### 公允价历史数组展开

|英文字段|中文名称|类型|单位与业务含义|备注|
|---|---|---|---|---|
|`fair_values[].date`|价格日期|string|YYYY-MM-DD，对应价格日期|—|
|`fair_values[].value`|公允价格|number|标的公允报价，上传不自动换汇|—|
|`fair_values[].customized_ins_id`|归属自定义标的记录 ID|string|归属自定义标的记录 ID|服务端在 JSON 替换时附加|

<a id="fairvalue"></a>

## 通用公允价记录

通用公允价记录字段；不要据此构造自定义标的全历史替换请求。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`order_book_id`|证券/合约代码|string|—|不是自定义合约记录 ID|—|
|`asset_class`|资产类别|string（枚举）|—|枚举[资产品种与会计科目](others.md#assetclass)|取全量取值，不受自定义标的允许取值范围限制|
|`date`|业务日期|string|YYYY-MM-DD|业务日期，不等同写入时间|—|
|`symbol`|显示名称|string|—|标的或资产单元显示名称|—|
|`value`|公允价格|number|标的报价单位|公允价格数值，按标的报价单位，不自动换汇|—|
|`product_id`|归属产品 ID|string / null|字符串 ID|归属产品 ID|由目标 resource 确定|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读|
