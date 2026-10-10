# 资产单元持仓单 positions_statements

持仓单是一份记录某天持有哪些资产、各有多少的清单。在这里，它用于核对资产单元的持有数量，不是一份计算基金价值的估值报告，也不是向券商下单的指令。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

单据及数量明细见[持仓单字段](fields/asset_units.md)。

## 从用户需求到操作

|用户需求|操作顺序与输入|完成条件|
|---|---|---|
|查看某单元收到了哪些持仓单|先用 asset_units.get 确认单元与产品 → `list` 限定日期|返回日期、文件名和 positions_statement_id 符合目标范围|
|按证券、方向核对数量|`list(is_detail=True)` → 读取 positions|按品种、方向、代码核对合并后的数量；不把合并记录条数当作原文件行数|
|导入或更正某日持仓单|选择匹配文件的 broker，保存同日原文件及详情 → `upload` → `list(is_detail=True)`|任务完成、错误已处理，目标日完整数量符合文件；同日旧单被整体替换|
|移除误导入持仓单|`list` 取得单据 ID 并确认授权 → `delete` → 重新查询|目标单据已移除，effect_count 与查询一致；删除不可撤销|
|核对系统保存的原文件|`list` 取得单据 ID → `download` 到新路径 → 与本地原始文件比对|文件内容与导入时保存的一致；不覆盖既有本地文件|
|排查哪些单元没有上传持仓单|`latest` 取各产品单元状态 → 对缺失或过期的单元用 `list` 确认日期|待补单元已定位；结论不来自本地文件，也不代表数量已核对|

本组完成的是单据导入和数量对账，不保证触发产品估值重算，也不保证改写 [balances.get](balances.md#get) 中的计算持仓。若用户要求改变估值，应另外核对产品数据源及对应输入流程。




## API 使用约定

Python 与 CLI 完成相同业务操作，连接、任务等待及部分失败处理见[连接说明](connection.md)。替换示例单元、记录 ID 与文件路径；上传、覆盖和删除须获授权。先确认 broker 与文件模板匹配，单元资源不能填归属产品名称。

## list
读取资产单元持仓单，自动解析归属产品。

Python 签名：`rqamsh.positions_statements.list(resource: str, *, start_date: str | None=None, end_date: str | None=None, is_detail: bool=False)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略不限制起始日期。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略不限制截止日期。|
|`is_detail`|`bool`|`False`|是否返回 positions；默认 false，仅返回单据元数据。|

返回：原始列表，每个元素是一张持仓单记录。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|持仓单记录|array（object 元素）|—|该资产单元在查询区间内的持仓单，元素键为 `positions_statement_id`、`date`、`file_name`，`is_detail=True` 时另含 `positions`；元素结构与[持仓单记录](fields/asset_units.md#positionstatement)、[持仓单数量明细](fields/asset_units.md#positionstatementposition)一致|恒返回；无记录时为空数组；记录 ID 的键是 `positions_statement_id`（字段页写作 `id`），元素不含 `product_id`、`asset_unit_id`、`fs_id`|

结果检查：核对日期和单据 ID；数量对账必须显式 is_detail=True。日期范围省略时不设该端限制，不能将默认全量列表误作某个期间的结果。

```python
result = rqamsh.positions_statements.list(resource='授权测试资产单元')
```

```console
rqamsh positions-statements list --resource "授权测试资产单元"
```

## upload
上传一个资产单元持仓单文件并等待导入任务完成。
[持仓单与 positions[] 字段](fields/asset_units.md)。所有 resource 必须是资产单元 ID 或 symbol，归属产品自动确定。upload 只支持文件；broker 默认 ricequant，可选 cicc_dma/citic_dma/ricequant/cms_dma。文件必须符合相应通道模板，不能拿任意 Excel 直接上传。

同资产类型+direction+order_book_id 的行会合并数量；存在合法 positions 时，同产品/资产单元/日期旧持仓单被删除，再保存新记录及原文件，所以同日导入为整体覆盖而非流水式 upsert。解析异常项可与合法项并存；部分失败后旧单也可能已被替换。持仓单导入不应被当作产品估值已更新的证明。

Python 签名：`rqamsh.positions_statements.upload(resource: str, file_path: str, *, broker: str='ricequant', prefer_fill_fund_exchange_suffix: bool=True)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称；归属产品自动解析。|
|`file_path`|`str`|必填|本地持仓单文件路径。|
|`broker`|`str`|`'ricequant'`|持仓单通道类型，默认 ricequant。|
|`prefer_fill_fund_exchange_suffix`|`bool`|`True`|默认 true 按 [基金基础信息](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-instruments) 自动补基金场内后缀；false 不使用该兼容补全方式。|

返回：客户端等待到任务终态后交回的服务端任务 JSON；失败或逐项错误抛异常，不自动重传文件。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示导入任务完成|恒返回；失败终态由客户端转成异常，见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例|恒返回；见[任务终态 JSON](connection.md#task-result)|
|`data`|任务结果|object|—|本次导入产物：`effect_count`(integer，`1` 表示写入了持仓单、`0` 表示没有可写入行)、逐行解析错误 `err_msg`(array，元素含 `line_num` 与 `msg`)、凭证 `confirmation_id`(string 或 null) 与业务日期 `date`(YYYY-MM-DD 或 null)|恒返回；`err_msg` 非空即抛部分失败异常，见[逐项失败容器](connection.md#item-errors)|

操作检查：上传前留存同日旧单和数量，文件应包含当天希望保留的完整持仓。检查任务终态中的解析错误，再 list(is_detail=True) 核对日期、代码、方向与合并数量；失败或超时先查已保存结果，不盲目重传造成再次覆盖。

```python
result = rqamsh.positions_statements.upload(resource='授权测试资产单元', file_path='positions.xlsx')
```

```console
rqamsh positions-statements upload --resource "授权测试资产单元" --file-path "positions.xlsx"
```

## delete
按记录 ID 删除资产单元持仓单，归属产品自动解析。

Python 签名：`rqamsh.positions_statements.delete(resource: str, positions_statement_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称。|
|`positions_statement_ids`|`list[str]`|必填|非空持仓单记录 ID 数组。|

返回：服务端原始写入结果，只含删除条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的持仓单记录条数|恒返回；ID 不存在或不属于该资产单元时为 `0`；见[写入结果](connection.md#write-result)|

操作检查：从目标单元 list 取得并确认各单据 ID，保存需留存的文件与明细。返回后核对 effect_count 及同范围列表；零影响数量不代表目标已成功删除，也不能通过此操作撤销已发生的其他业务变更。

```python
result = rqamsh.positions_statements.delete(resource='授权测试资产单元', positions_statement_ids=['0123456789abcdef01234567'])
```

```console
rqamsh positions-statements delete --resource "授权测试资产单元" --positions-statement-ids '["0123456789abcdef01234567"]'
```

## download
下载一份资产单元持仓单的源文件，用于核对上游文件与系统保存的明细是否一致。

下载前客户端先用同一单元的 `list` 校验该持仓单 ID 确实属于目标单元，避免用错单元的产品路由取到其他单元的文件；ID 不属于该单元时报错且不请求源文件。

Python 签名：`rqamsh.positions_statements.download(resource: str, positions_statement_id: str, output: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称。|
|`positions_statement_id`|`str`|必填|list 返回的持仓单 ID。|
|`output`|`str`|必填|本地输出文件路径，父目录须存在且目标文件不得已存在。|

返回：客户端下载元数据，不返回文件内容。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](connection.md#download-result)|

交付检查：确认 output 是新文件且 `size` 与保存结果一致，打开文件核对日期与数量；抓取的是导入时保存的原始文件，不是按当前计算重新生成的报表。目标文件已存在时客户端直接报错，不覆盖既有文件。读取需要导入数据权限。

```python
result = rqamsh.positions_statements.download(resource='授权测试资产单元', positions_statement_id='0123456789abcdef01234567', output='statement.xlsx')
```

```console
rqamsh positions-statements download --resource "授权测试资产单元" --positions-statement-id "0123456789abcdef01234567" --output "statement.xlsx"
```

## latest
读取工作空间中各产品资产单元的最新持仓单状态，用于快速发现哪些单元长期没有上传或上传已过期。

无参数的工作空间级读取：服务端按产品返回全部资产单元，客户端再按目录过滤，只保留当前身份可见的资产单元；过滤后没有剩余项的产品不会出现在结果中。没有资产单元的产品本来就不在此结果内。

Python 签名：`rqamsh.positions_statements.latest()`。

返回：数组，每个元素是一个产品及其可见资产单元的最新上传状态。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品 ID|恒返回；按此字段与产品列表对照|
|`product_name`|产品名称|string|—|产品名称|恒返回|
|`positions_statement_items`|资产单元状态列表|array（object 元素）|—|该产品下可见资产单元的最新上传状态|恒返回；不表示数量已核对|
|`positions_statement_items[].asset_unit_name`|资产单元名称|string|—|资产单元显示名称|随父级返回|
|`positions_statement_items[].asset_unit_id`|资产单元 ID|string|字符串 ID|资产单元记录 ID|随父级返回|
|`positions_statement_items[].update_time`|最近上传日期|string|YYYY-MM-DD|该单元最近一次上传持仓单的业务日期|随父级返回；从未上传时为字符串「未上传持仓单」，不是发生时刻|

结果检查：`update_time` 是该单元最近一张持仓单的业务日期，不是上传发生的时刻，也不代表这些数量已核对；用它定位待补单元后，应改用 `list` 确认目标日期与单据。

```python
result = rqamsh.positions_statements.latest()
```

```console
rqamsh positions-statements latest 
```
