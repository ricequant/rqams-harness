# 产品 products

产品是 AMS 中承载一份投资对象的数据和展示结果的载体，通常对应现实中的一只基金产品或一个投资组合。用户把相关交易、报表等资料放到这个产品下，再查看它的资产、持仓与投资表现。不同产品分别管理，便于持续跟踪同一投资对象。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

字段含义、类型与嵌套结构见[产品字段](fields/products.md)。创建、修改及删除的注意事项分别见下方对应 API。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|找到要管理或分析的产品|`list` 筛选可访问产品 → `get` 核对数据源、账户与日期；后续优先使用产品 ID|目标唯一且配置符合用户指定的产品；列表为空不等于产品不存在|
|建立新的估值对象|先确定流水、估值报告或混合数据源 → `name_exists` 检查名称 → 准备对应字段并 `create` → 按数据源导入业务数据|取得 `product_id`，检查 `err_msgs` 并用 `get` 核对；创建成功不表示已有可用估值|
|调整配置或修正历史估值|`get` 保存修改前配置 → `update` 提交所需字段，必要时 `recompute` 指定起点 → `compute_state` → 读取受影响日期头寸报表|配置符合预期，计算状态为 `normal`，相关头寸报表已核对；提交数量不代表计算完成|
|停用产品|确认目标及删除授权 → `delete` → `list` 核对不再可见|删除结果与列表一致；此操作不满足历史数据彻底擦除需求|
|封账或解封|`set_closing_entry` 写入封账日 → `get` 核对；解封改用 `clear_closing_entry` → `compute_state` → 核对头寸报表|封账日符合业务约定；解封后重算已到 `normal` 且报表已核对|
|批量核对哪些产品缺估值表|`valuation_report_missing_dates` 取缺失数量 → 对缺表产品用 `valuation_reports.list` 与 `missing_dates` 定位日期 → 补导报告|缺失数量归零或已解释，报告已导入并通过核对|
|判断本地文件是否已上传|`uploaded_file_hashes` 取已上传哈希 → 与本地文件比对 → 决定补导或按覆盖参数重导|结论基于哈希比对，未重复导入同一文件|
|把历史产品改为分类份额|准备份额设置与原事件归属 → `enable_shares` → 等待任务终态 → `get` 核对 shares 与事件归属|任务 `SUCCESS`，份额配置与事件归属与业务约定一致|
|检查名称或字段是否可用|`field_exists` 指定一个字段 → 按 exists 决定是否调整取值|exists 结论来自对应字段检查，未把未占用当作创建成功的保证|






## API 使用约定

Python 与 CLI 完成相同业务操作，连接及公共错误处理见[连接说明](connection.md)。示例中的产品名称、ID 和文件路径需替换为实际目标；写入和删除须获得授权。JSON 文件按[产品字段](fields/products.md)准备；参数为 None 时省略发送，具体默认值见各操作，不把省略日期视为固定业务日期。

## list
查询当前工作空间中当前用户可访问的产品。

Python 签名：`rqamsh.products.list(*, fields: list[str] | None=None, sources: list[str] | None=None, member_user_id: int | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`fields`|`list[str] \| None`|`None`|返回字段列表；省略使用服务端默认字段，始终保留 id 供后续选择产品。|
|`sources`|`list[str] \| None`|`None`|产品 data_source 枚举列表，不是流水来源。|
|`member_user_id`|`int \| None`|`None`|按指定成员获分享的产品筛选，不突破当前用户可访问范围。|

返回：服务端原始对象，含 `products`、`total` 与 `permissions`；`products` 只保留当前用户可访问的产品。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`products`|产品列表|array（object 元素）|—|可访问产品数组，按创建时间倒序；元素为[产品配置](fields/products.md#product)|恒返回；元素字段由 `fields` 选择（省略时用服务端默认字段，恒保留 `id`），空数组表示当前范围内没有可见产品|
|`total`|产品条数|integer|条|`products` 的元素个数|恒返回；按客户端可见目录过滤后重新计数，始终等于 `products` 的长度|
|`permissions`|产品授权明细|array（object 元素）|—|网关按请求人权限产出的授权行；判断「我对这个产品能做什么」只用它，不要用资源能否读到推断|原样透传服务端响应；是否存在、元素结构及与 `products` 行的对应关系都不作保证，不能按同一行判断写权限|
|`permissions[].product_id`|产品 ID|string|—|该授权行对应的产品|随父级记录返回；客户端不校验该 ID，也不保证它出现在 `products` 中或与 `products` 行对齐|
|`permissions[].permission`|本人权限级别|string（枚举）|—|请求人在该产品上的权限，取值见[权限级别](permissions.md#权限级别)|随父级记录返回；取 `forbidden` 表示该产品对请求人不可读，不代表它不会出现在别人的列表里|
|`permissions[].is_owner`|是否本人资源|boolean|—|`true` 表示请求人是工作空间管理员或该产品创建者；`false` 表示仅通过他人分享获得|随父级记录返回；`true` 不等于权限更高，管理员对自己没有权限记录的产品也会得到 `true` 且 `permission` 为 `forbidden`|

结果检查：用 products 中的 ID 选择后续操作目标。指定 fields 时仍返回 id；total 是可访问范围内数量，member_user_id 筛选不会授予额外权限。需要判断写入或导出能否执行时，用 permissions 中的授权行（`write`/`admin` 才可改），但不要假设它与 `products` 逐行对齐，也不要用「能读到」推断「能改」。

```python
result = rqamsh.products.list()
```

```console
rqamsh products list 
```

## get
读取产品完整配置。

Python 签名：`rqamsh.products.get(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|当前工作空间可访问产品的唯一 ID 或名称。|

返回：服务端产品 JSON，返回根就是产品配置对象。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|产品配置|object|—|单个产品的配置对象，顶层键与嵌套结构见[产品字段](fields/products.md#product)|恒返回；返回根不是数组，也不含产品组与资产单元；完整释义、类型与单位只在字段页展开|

结果检查：核对返回的产品 ID、data_source、accounts 和日期配置。名称不唯一时改用 ID；无权限或未找到时，不应换用同名产品继续操作。

```python
result = rqamsh.products.get(resource='授权测试产品')
```

```console
rqamsh products get --resource "授权测试产品"
```

## create
创建产品，服务端按数据源校验配置并可能初始化估值。
完整字段及 accounts、benchmark、valuation_settings、exchange_rate_settings、shares 展开见 [产品字段](fields/products.md)。create 至少需要 data_source、name、investment_category、strategy_category、benchmark、calendar、start_date（基准行情见[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)、交易日见[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)）。start_date 对所有数据源都在运行期必填，缺席时服务端报「产品开始日期不能为空」，与按数据源的必填集合无关；纯 trade 与混合 trade_and_valuation_report 均另需 unit_policy。提交初始化估值表（init_valuation_report_file）时可省略 start_date，服务端取该估值表的日期，但已给的 start_date 不能晚于该日期。maturity_date 不能早于 start_date；trading_start_date 省略时取 start_date 且不能早于它。纯估值报告源由报告建立起点，不能上传交易流水。

创建或修改时不要提交只读字段 valuation_start_point、user_id、workspace_id、create_time、closing_date、product_state、id；用户和工作空间由连接身份确定。服务端不按字段白名单过滤请求体：提交**未声明的键**会直接失败（错误文案就是该键名，如 `'report_nam'`），而**已声明但业务上只读的状态字段**（如 `deleted`）会被接受并写入，受控字段集只能由调用方自己限制。初始化报告还可提供 init_valuation_report_file（Base64 文件内容）和 init_valuation_report_file_name（字符串文件名），这是产品初始化字段，不是 file_path。shares 键只能是单个英文字母，各项 effective_date 必填、费率非负。
创建最小交易源配置示例（供 create 的 data 使用；示例中的 `000300.XSHG` 是指数代码，校验见[指数基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)；请替换名称、日期与业务配置，并取得创建授权）：

```json
{"name":"授权测试产品","data_source":"trade","start_date":"2026-01-01","unit_policy":"manual","investment_category":"equity","strategy_category":"stock_long","benchmark":{"type":"index","id":"000300.XSHG"},"calendar":"exchange"}
```

Python 签名：`rqamsh.products.create(data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`data`|`dict[str, Any]`|必填|产品 JSON；必含 data_source、name、investment_category、 strategy_category、benchmark、calendar，其他必填字段依数据源而定。|

返回：服务端创建结果，含 `product_id` 与 `err_msgs`；`err_msgs` 非空即抛部分失败异常。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_id`|新建产品 ID|string|字符串 ID|新建产品的记录 ID，保存后供后续读取与导入使用|恒返回；产品记录先创建，估值表初始化失败不回滚已创建的产品|
|`err_msgs`|初始化逐项错误说明|array（string 元素）|—|初始化估值表解析失败的逐项说明，按项目或行给出原因|恒返回；未提交初始化估值表或全部解析成功时为空数组，非空即抛部分失败异常并保留完整结果，见[逐项失败容器](connection.md#item-errors)|

结果检查：保存 product_id 并检查 err_msgs，再用 get 读取配置。若创建或初始化报错，先查询产品是否已存在，避免直接重试造成重复；后续导入必须匹配 data_source。

```python
import json
from pathlib import Path

result = rqamsh.products.create(data=json.loads(Path("product.json").read_text(encoding="utf-8")))
```

```console
rqamsh products create --input @product.json
```

## update
局部修改产品；影响估值的字段由服务端触发重算。
update 为局部更新，但 null/空值不统一表示“保持不变”：部分字段会被清除。改估值参数、费率、起始日等可能重算；修改 auto_overwrite 会影响已保存报告的[估值表覆盖](reconciliation.md#valuation-report-overwrite-setting)；移除分类份额可能删除对应托管和份额事件，应先保存并核对关联数据。delete 是软删除，并移除相关访问权限；不保证物理删除历史业务数据或凭证，不能当作数据擦除接口。recompute 只提交，不等待；提交结果不代表重算完成。

创建和修改均不提交只读身份、状态字段，完整读写范围见[产品字段](fields/products.md)。名称与报告名可以改（改名也会触发服务端重算判断），改名后必须用返回的 `effect_count` 与 `get` 结果做变更前后对比，不要用改名前解析到的名称继续调用。分类份额键只能是单个英文字母，各项 effective_date 必填、费率非负。

Python 签名：`rqamsh.products.update(resource: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`data`|`dict[str, Any]`|必填|需修改的产品字段；未提供字段保持不变，显式 null 按服务端处理。|

返回：服务端原始修改结果。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际修改的产品记录数|恒返回；提交内容与现值相同时为 `0`，不代表产品不存在，见[写入结果](connection.md#write-result)|

操作检查：先读取原配置，只提交用户要求修改的字段；不要用 null 表示未修改。返回后核对 effect_count 和 get 结果；若影响估值，还需检查计算状态及受影响日期头寸报表，尤其是 auto_overwrite 和分类份额变更。

```python
import json
from pathlib import Path

result = rqamsh.products.update(resource='授权测试产品', data=json.loads(Path("update.json").read_text(encoding="utf-8")))
```

```console
rqamsh products update --resource "授权测试产品" --input @update.json
```

## delete
客户端只向产品端点发 DELETE，不附带任何清理；数据保留范围由服务端决定，不要据此假设可恢复（历史真机实测表现为软删产品与权限）。本客户端没有物理清理入口，也不提供恢复操作；列表不再可见也不代表历史数据已彻底清空。

Python 签名：`rqamsh.products.delete(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|待删除产品的唯一 ID 或名称。|

返回：服务端原始删除结果。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次被置为删除态的产品记录数|恒返回；记录已是删除态时为 `0`，此时不能据此宣称已删除，也不证明历史数据已物理擦除，见[写入结果](connection.md#write-result)|

操作检查：删除前以 ID 核对目标并确认不可通过本客户端恢复。返回后检查 effect_count 及 list；数量为 0 时不能宣称已删除，且任何结果都不证明历史数据已物理擦除。

```python
result = rqamsh.products.delete(resource='授权测试产品')
```

```console
rqamsh products delete --resource "授权测试产品"
```

## recompute
提交一个产品的重算，不表示估值已完成。

Python 签名：`rqamsh.products.recompute(resource: str, *, start_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略从产品起始日重算。|

返回：服务端原始提交结果；可用 compute_state 查询状态。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`submit_recompute_count`|实际提交重算的产品数|integer|个|本次实际提交重算的产品个数|恒返回；目标产品存在且已提交时为 `1`，`0` 表示服务端未找到该产品、没有提交任何重算；提交结果不代表重算完成|

完成条件：检查 submit_recompute_count 后继续调用 compute_state；只有状态为 normal 并核对重算起点后的头寸报表，才能将业务估值视为完成。失败或等待超时应保留 execution_id 和诊断，不能重复提交来代替状态检查。

```python
result = rqamsh.products.recompute(resource='授权测试产品')
```

```console
rqamsh products recompute --resource "授权测试产品"
```

## compute_state
读取产品估值任务状态，不自动等待业务重算完成。

Python 签名：`rqamsh.products.compute_state(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|

返回：服务端对状态端点的原始响应，客户端原样透传，不校验或补齐字段。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`state`|计算状态|string|—|服务端当前返回的表征计算状态的字段与取值|由数据决定；客户端原样透传，不校验取值、不补齐默认值，也不保证该键存在；与产品状态 `product_state` 不是同一枚举|
|`execution_id`|计算任务执行序号|integer / null|—|服务端计算任务的执行序号，用于区分同一产品的不同次计算|由数据决定；只读，客户端原样透传，不补齐缺失值|

结果检查：把返回状态与后续读取的头寸报表结合判断，状态未就绪时不要把相关估值当作已完成结果；保留 execution_id 并按[等待规则](connection.md)处理后续查询。此操作只查询一次状态，不等待、不轮询。

```python
result = rqamsh.products.compute_state(resource='授权测试产品')
```

```console
rqamsh products compute-state --resource "授权测试产品"
```

## name_exists
按产品名称查询是否已存在，不替代资源消歧或权限检查。

Python 签名：`rqamsh.products.name_exists(name: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`name`|`str`|必填|要检查的产品名称。|

返回：服务端原始对象，含布尔字段 exists。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`exists`|名称是否已存在|boolean|—|当前工作空间内是否已有同名产品|恒返回；`true` 表示名称已被占用，`false` 不保证随后创建一定成功|

结果检查：exists=true 表示名称已存在，应选择其他名称或通过 list/get 确认可访问目标；exists=false 不保证随后创建一定成功，创建仍需处理同名冲突。

```python
result = rqamsh.products.name_exists(name='授权测试产品')
```

```console
rqamsh products name-exists --name "授权测试产品"
```

## field_exists
检查产品名称、全称、账号名称或基金代码是否已被占用。四个参数必须且只能提供一个；同时提供多个会失败，不会按服务端固定顺序静默取第一个。

账号名称走检查 `accounts.name` 的专用路由：服务端通用检查把 `account_name` 映射到顶层同名字段，该分支恒为 false，因此本操作对该字段改用专用端点，避免把“未占用”误报为可用名称。

Python 签名：`rqamsh.products.field_exists(*, name: str | None=None, full_name: str | None=None, account_name: str | None=None, fund_code: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`name`|`str \| None`|`None`|产品名称。|
|`full_name`|`str \| None`|`None`|产品全称。|
|`account_name`|`str \| None`|`None`|账号名称，按 `accounts.name` 匹配。|
|`fund_code`|`str \| None`|`None`|基金代码。|

返回：服务端原始对象，含布尔字段 exists。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`exists`|取值是否已被占用|boolean|—|所选字段在当前工作空间内是否已有相同取值：`name`、`full_name`、`fund_code` 查顶层同名字段，`account_name` 查 `accounts.name`|恒返回；`true` 表示已被占用，`false` 不保证随后创建一定成功|

结果检查：exists=true 表示该字段已被占用，应另选取值；exists=false 不保证随后创建一定成功，创建仍需处理冲突。

```python
result = rqamsh.products.field_exists(fund_code='000001')
```

```console
rqamsh products field-exists --fund-code "000001"
```

## enable_shares
把未封账的历史产品转换为分类份额产品，并等待服务端算完。转换依据是原托管事件和份额事件的份额归属，不是按比例自动拆分。

`shares` 的键只能是单个英文字母，每项必含 effective_date，可含 management_fee、performance_pay、subscription_fee、redemption_fee，费率非负。`custodian_events` 与 `unit_events` 的键是**原事件 ID**（取自 [托管事件](custodian_events.md) 与 [份额事件](unit_events.md)），值是该事件在各份额上的归属：托管事件映射到金额，份额事件映射到份额，均为正数。

Python 签名：`rqamsh.products.enable_shares(resource: str, shares: dict[str, Any], custodian_events: dict[str, Any], unit_events: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`shares`|`dict[str, Any]`|必填|份额名到份额设置的映射，每项必含 effective_date 与可选费率。|
|`custodian_events`|`dict[str, Any]`|必填|原托管事件 ID 到「份额名 → 金额」的归属映射。|
|`unit_events`|`dict[str, Any]`|必填|原份额事件 ID 到「份额名 → 份额」的归属映射。|

返回：服务端任务终态 JSON；成功终态的 `data` 给出转换结果摘要。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示转换完成，`FAIL` 表示失败|恒返回；定义与结局见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例；任务终态为 `1`，失败终态为 `0`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|转换结果摘要|object / null|—|成功终态为对象，行内键：`custodian_event_count`(integer，条，按份额重建的托管事件条数)、`unit_event_count`(integer，条，按份额重建的份额事件条数)、`effect_count`(integer，条，改动的 `shares` 配置记录数)、`reparsed_valuation_report_count`(integer，个，按份额设置重新解析的估值报告条数)|随父级返回（`status` 为 `SUCCESS` 时）；不自动拆包，见[任务终态 JSON](connection.md#task-result)|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定（失败终态才返回）；见[任务终态 JSON](connection.md#task-result)|

完成条件：status 为 SUCCESS 才表示转换完成；任务失败抛错并保留服务端诊断，不自动重发写入体。完成后用 get 核对 shares 配置，并检查受影响的托管事件与份额事件归属。

调用后必须重新取 ID：转换会**删除传入的原事件**并按份额重建，原事件 ID 立即失效，后续 update/delete 要用 `custodian_events.list` / `unit_events.list` 重新取回新 ID（新事件的 `product_share` 为对应份额类别）。已封账产品或已是份额产品的产品会被服务端拒绝。

```python
import json
from pathlib import Path

result = rqamsh.products.enable_shares(
    resource='授权测试产品',
    shares=json.loads(Path("shares.json").read_text(encoding="utf-8")),
    custodian_events=json.loads(Path("custodian_mapping.json").read_text(encoding="utf-8")),
    unit_events=json.loads(Path("unit_mapping.json").read_text(encoding="utf-8")),
)
```

```console
rqamsh products enable-shares --resource "授权测试产品" --shares @shares.json --custodian-events @custodian_mapping.json --unit-events @unit_mapping.json
```

## valuation_report_missing_dates
列出各产品缺失估值表的交易日数量，用于批量核对哪些产品需要补表。起算点是产品封账日，未封账时使用交易起始日；截止为最近结算日，只统计其中的交易日。

这是工作空间级检查：服务端按当前身份返回数据，客户端再按目录过滤，只保留当前用户可见的产品。

Python 签名：`rqamsh.products.valuation_report_missing_dates()`。

返回：服务端原始数组，每项字段如下。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|单条缺表汇总|object|—|根数组元素，对应一个产品，子键见本表其余各行|恒返回；服务端按当前身份统计，客户端再按可见目录过滤后返回|
|`[].product_id`|归属产品 ID|string|字符串 ID|该汇总对应的产品记录 ID|恒返回；只读，可与 `list` 返回的 `id` 对照|
|`[].product_name`|产品名称|string|—|该产品名称|恒返回；只读|
|`[].product_full_name`|产品全称|string / null|—|产品全称，用于展示识别|恒返回；未填写全称时为 `null`|
|`[].missing_date_count`|缺失估值表交易日数|integer|个|自封账日（未封账取交易起始日）到最近结算日之间缺失估值表的交易日数量|恒返回；不含非交易日，`0` 表示该区间没有缺表日期|
|`[].newest_valuation_report_date`|最新报告日期|string / null|YYYY-MM-DD|该产品已导入估值报告的最新业务日期|恒返回；没有已导入报告时为 `null`|

结果检查：missing_date_count 大于 0 的产品需要补表；newest_valuation_report_date 是最新已导入报告的日期。缺少估值表不等于缺净值，混合或交易源产品的缺失日期应与流水录入情况一起核对。

```python
result = rqamsh.products.valuation_report_missing_dates()
```

```console
rqamsh products valuation-report-missing-dates 
```

## uploaded_file_hashes
按产品查询已上传文件的哈希，用于判断本地文件是否已经上传过。

`file_type` 取值见[可校验文件类型](#hashablefiletype)。三类都会为请求到的产品返回条目，`hash_list` 为空数组表示该产品没有该类型的已上传哈希；唯一会缺席的是估值报告分支的数据源过滤——非估值报告数据源产品被排除，不返回条目。

该路由不校验资源读取级别：他人产品只要在当前工作空间可见就能查询，不需要额外的导入数据或持仓读取权限。

Python 签名：`rqamsh.products.uploaded_file_hashes(product_ids: list[str], file_type: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`product_ids`|`list[str]`|必填|非空的产品 ID 或名称数组。|
|`file_type`|`str`|必填|valuation_report、paper_trading 或 trade。|

返回：服务端原始数组，每项字段如下。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|单条产品哈希|object|—|根数组元素，对应一个请求到的产品，子键见本表其余各行|恒返回；`valuation_report` 分支只返回估值报告与混合数据源产品，`paper_trading` 与 `trade` 分支为请求到的每个产品各返回一条|
|`[].product_id`|归属产品 ID|string|字符串 ID|该条哈希对应的产品记录 ID|恒返回；只读|
|`[].hash_list`|已上传文件哈希列表|array（string 元素）|—|该产品下指定 `file_type` 的已上传文件哈希值，用于与本地文件比对|恒返回；空数组表示该产品没有该类已上传文件|

结果检查：本地文件的哈希出现在 hash_list 中说明该文件已上传过，重复导入前应先判断是否需要覆盖；哈希不匹配说明文件内容与已上传的不同。

```python
result = rqamsh.products.uploaded_file_hashes(product_ids=['授权测试产品'], file_type='trade')
```

```console
rqamsh products uploaded-file-hashes --product-ids '["授权测试产品"]' --file-type "trade"
```

<a id="hashablefiletype"></a>
### 可校验文件类型

`products.uploaded_file_hashes` 的 `file_type` 取值，用于按产品查询已上传文件的哈希。

|值|含义|
|---|---|
|`valuation_report`|估值报告文件；只覆盖估值报告数据源产品的已上传哈希|
|`paper_trading`|模拟交易文件|
|`trade`|交易流水文件（含日内与结算通道导入的文件）|

## set_closing_entry
设置产品封账日，只更新字段，不触发重算。

封账日不得晚于今天、早于产品起始日或晚于到期日。设置后，缺表统计的起算点变为该日期；封账不改变已导入数据，也不会自动补齐其后的估值。

Python 签名：`rqamsh.products.set_closing_entry(resource: str, closing_date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`closing_date`|`str`|必填|YYYY-MM-DD，封账日。|

返回：空响应，客户端得到 `None`。

操作检查：用 get 读取 closing_date 核对；本操作不提交重算，如业务需要其后的估值，另用 recompute 指定起点。

```python
result = rqamsh.products.set_closing_entry(resource='授权测试产品', closing_date='2026-08-31')
```

```console
rqamsh products set-closing-entry --resource "授权测试产品" --closing-date "2026-08-31"
```

## clear_closing_entry
解除产品封账，并从产品起始日提交一次重算。

与 set_closing_entry 的区别：解封会清除封账日并提交重算，因此会重新计算产品起始日之后的估值。提交不代表计算完成。

Python 签名：`rqamsh.products.clear_closing_entry(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|

返回：空响应，客户端得到 `None`。

完成条件：用 get 确认 closing_date 已清除，用 compute_state 查询重算状态（该方法不等待、不轮询），再核对受影响日期的头寸报表；提交成功本身不表示估值已更新。产品已到期时解封不改变到期后的处理规则。

```python
result = rqamsh.products.clear_closing_entry(resource='授权测试产品')
```

```console
rqamsh products clear-closing-entry --resource "授权测试产品"
```

## create_example
创建一个范例产品，用于查看标准配置，并等待服务端算完。

无参数；服务端返回任务后再由客户端轮询到终态。范例产品会出现在产品列表中，可像普通产品一样读取或删除。

Python 签名：`rqamsh.products.create_example()`。

返回：服务端任务终态 JSON；`data` 是创建过程摘要。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示创建完成；同名范例产品已存在时服务端返回 `FAIL`|恒返回；定义与结局见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|任务终态为 `1`；任务异常结束时为 `0`|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|创建过程摘要|object / string / null|—|成功且无跳过项时为空对象 `{}`；有跳过项时为「产品(X)已存在」这类消息串|由数据决定（任务异常结束时不含该键）；不自动拆包，见[任务终态 JSON](connection.md#task-result)|

完成条件：status 为 SUCCESS 后用 list 确认新出现的产品。范例产品的名字带用户 ID，空间里已有同名产品时任务会被判为失败（status `FAIL`，`data` 逐条列出已存在的产品与产品组），此时没有任何新对象产生，客户端把该终态转成异常并保留诊断——这是可预期的结果，不要为它改用其他写法或重试去「凑成功」。范例产品同样需要通过 delete 处理，不会自动清理。

```python
result = rqamsh.products.create_example()
```

```console
rqamsh products create-example 
```
