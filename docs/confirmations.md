# 导入凭证 confirmations

导入凭证是一次导入的留痕记录：从哪个来源、什么时候导入、解析了多少条、登记了多少条，逐项结果与原始文件都能追查。它用于回答「这批流水到底导进去了没有、哪几行被拒了」，不用来修改业务数据。

## 字段说明

凭证列表项、明细、统计与源文件字段见[导入凭证字段](fields/confirmations.md)。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|查某产品导入过哪些批次|`list` 限定资产单元与日期|items 中的来源、时间与解析/登记条数符合目标区间|
|定位某批次里失败的具体条目|`list` 取得凭证 ID → `get(status='failed')`|失败项逐条给出原因；total 随 status 变化，读的是对应子集|
|回看导入用的原始文件|`list`/`get` 确认 src_file 存在 → `download` 到新文件|下载文件与当时提交的文件内容一致；目标文件已存在时不会覆盖|
|查各产品最近一次导入状态|`latest(source)`|按来源返回产品级或账户级最新状态；没有记录的产品或账户不会当成过期|

## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。替换示例产品、凭证 ID 与输出路径；本组只读，不写业务数据。`list`/`get`/`download` 在网关上要求 `read_import_data`（客户端不预判，越级由网关拒绝）；工作空间级的 `latest` 在**服务端路由**上只需登录（不校验资源级别），但客户端为把结果过滤成当前身份可见的产品，会在取回结果后再构建一次资源目录，因此产品列表、每个产品详情、产品组列表与详情、资产单元列表都必须成功：顶层请求失败会让 `latest` 整体失败，产品组列表/详情或资产单元列表等非 403/404 错误同样如此，只有产品详情与产品组详情的 403/404 会被跳过。下载是服务端保存的一次性源文件，不覆盖已有本地文件，也不按服务端文件名选择路径。

### 凭证来源

`latest` 的 `source` 传展示名（`OpenAPI`、`IntraDayTrades`、`ValuationForm`、`EODTrades`、`CustodianEvents`、`PositionsStatement`、`PositionsSheet`），`list`/`get` 返回的 source_enum 使用同一组值；各值的业务含义见[导入凭证来源](fields/confirmations.md#confirmationsource)。

## list
列出产品导入凭证。

Python 签名：`rqamsh.confirmations.list(resource: str, *, asset_unit_id: str | None=None, start_date: str | None=None, end_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`asset_unit_id`|`str \| None`|`None`|只看该资产单元的批次；省略返回产品全部批次。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设下界。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设上界。|

返回：服务端原始对象，含凭证数组与条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`items`|凭证列表|array（object 元素）|—|该产品在筛选范围内的导入凭证，元素键为 `id`、`source_enum`、`name`、`fund_account`、`asset_unit_id`、`operation_time`、`total_parsed`、`total_registered`、`earliest_registered_date`、`latest_registered_date`，含义见[凭证列表项](fields/confirmations.md#confirmationlistitem)|恒返回；无凭证时为空数组|
|`total`|凭证条数|integer|条|筛选条件下的凭证条数|恒返回；等于 `items` 的长度|

结果检查：先看 total_registered 是否等于 total_parsed；不相等表示存在解析或登记失败项，用 `get(status='failed')` 定位。日期区间按凭证操作时间过滤，不是被导入数据本身的业务日期。

```python
result = rqamsh.confirmations.list(resource='授权测试产品', start_date='2026-01-01', end_date='2026-01-31')
```

```console
rqamsh confirmations list --resource "授权测试产品" --start-date 2026-01-01 --end-date 2026-01-31
```

## get
读取一份导入凭证的明细。

Python 签名：`rqamsh.confirmations.get(resource: str, confirmation_id: str, *, status: str='all', offset: int | None=None, limit: int | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称，必须与凭证归属一致。|
|`confirmation_id`|`str`|必填|`list` 返回的凭证 ID。|
|`status`|`str`|`'all'`|全部、成功或失败子集，取值 all、succeeded、failed。|
|`offset`|`int \| None`|`None`|跳过条数；省略由服务端按 0 处理。|
|`limit`|`int \| None`|`None`|返回条数上限；省略由服务端按全部处理。|

返回：服务端原始对象，根对象就是这份凭证的统计、逐项结果与源文件信息。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|凭证明细|object|—|一份[凭证明细](fields/confirmations.md#confirmationdetail)的统计与元数据键：`id`、`source_enum`、`asset_unit_id`、`fund_account`、`is_successful`、`operation_time`、`total_parsed`、`total_registered`、`earliest_registered_date`、`latest_registered_date`|恒返回；统计字段之间可互相推导，不要用 `items` 长度代替|
|`items`|逐项结果|array（object 元素）|—|按 `status` 取出的条目，元素键为 `data` 与 `fail_reason`，含义见[逐项结果](fields/confirmations.md#confirmationitem)|恒返回；受 `status` 与分页影响，只含所选子集；业务条目与失败原因可能同批出现|
|`src_file`|源文件信息|object / null|—|导入时保存的原始文件，对象键为 `filename` 与 `content`，含义见[源文件](fields/confirmations.md#confirmationsourcefile)|恒返回；结构化写入（如产品持仓表）的凭证为 `null`，此时 `download` 取不到文件|
|`total`|当前子集条数|integer|条|按 `status` 统计的条数：`all` 为解析总数，`succeeded` 为登记总数，`failed` 为两者之差|恒返回；与 `items` 属于同一子集，分页不影响本键|

结果检查：is_successful 为 true 表示解析总数与登记总数相等，这是这批导入的完成条件；items 给出逐项数据或失败原因。status 传错值会被拒绝，分页只影响 items，不影响统计字段。

```python
result = rqamsh.confirmations.get(resource='授权测试产品', confirmation_id='6a1f4c2e9b3d4f5a6b7c8d90', status='failed')
```

```console
rqamsh confirmations get --resource "授权测试产品" --confirmation-id 6a1f4c2e9b3d4f5a6b7c8d90 --status failed
```

## latest
按来源读取工作空间内各产品的最新导入状态。

Python 签名：`rqamsh.confirmations.latest(source: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`source`|`str`|必填|来源展示名，见上方凭证来源表。|

返回：原始数组，只保留当前身份在目录中可见的产品；每项的形状随 `source` 不同。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_id`|产品 ID|string|字符串 ID|归属产品|恒返回|
|`product_name`|产品名称|string|—|归属产品名称|恒返回|
|`account_items`|账户导入状态|array（object 元素）|—|逐账户的最近导入状态，元素键为 `account_name`、`is_custodian`、`update_time`、`message`，含义见[账户导入状态](fields/confirmations.md#confirmationaccountitem)；其中 `update_time` 是日期时间字符串，该账户从未导入时这个键不出现，`message` 是「导入成功/部分成功/导入失败/从未导入」的结论枚举|由参数选择：`source` 不是 CustodianEvents 时返回；产品没有账户时为空数组|
|`custodian_item`|托管事件导入状态|object|—|该产品托管事件文件的最近导入状态，对象键为 `update_time`（日期时间字符串），含义见[托管事件导入状态](fields/confirmations.md#confirmationcustodianitem)|由参数选择：仅 `source` 为 CustodianEvents 时返回；该产品从未导入过托管事件文件时为空对象，此时没有 `update_time` 键|

服务端按「产品 ID + 账户名」匹配导入记录，而估值报告、产品持仓表与资产单元持仓单的凭证都以空账户名保存，因此这三种来源的账户项恒为「从未导入」、不给 update_time；产品没有账户时 `account_items` 是空数组而不是带「从未导入」的条目。要看资产单元持仓单的上传状态请用 [positions_statements.latest](positions_statements.md#latest)，托管事件用 `custodian_events.latest`。

message 的取值只有 导入成功（解析数大于 0 且与登记数相等）、部分成功（登记数小于解析数且大于 0）、导入失败（其余情形）与 从未导入。

结果检查：这是「最近一次导入的时间/日期」，不代表数据完整或估值已就绪；需要完整性判断时回到 `list` 与 `get` 的解析、登记条数。

```python
result = rqamsh.confirmations.latest(source='CustodianEvents')
```

```console
rqamsh confirmations latest --source CustodianEvents
```

## download
下载一份导入凭证的源文件。

源文件是导入当时保存的原件（例如估值表、流水文件、托管事件文件）；估值报告这类结构化写入也会保存导出的 CSV 源文件，但产品持仓表写入的凭证不保存文件。目标路径必须是一个尚不存在的文件，父目录需自行创建，避免覆盖本地已有文件。

Python 签名：`rqamsh.confirmations.download(resource: str, confirmation_id: str, output: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|凭证归属产品的唯一 ID 或名称。|
|`confirmation_id`|`str`|必填|`list` 返回的凭证 ID，必须属于该产品。|
|`output`|`str`|必填|本地输出文件路径，目标文件不得已存在。|

返回：客户端下载元数据，不返回文件内容本身。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](connection.md#download-result)|

结果检查：确认输出文件大小非零再打开；目标文件已存在时请求不会发出，需换路径或先自行备份。产品持仓表写入产生的凭证没有源文件（`get` 返回的 `src_file` 为 `null`），对它调用 download 时服务端返回 500（报错文字即键名 `src_file`），这不是本地路径问题也不应重试；文件导入与估值报告这类结构化写入产生的凭证才有源文件。

```python
result = rqamsh.confirmations.download(resource='授权测试产品', confirmation_id='6a1f4c2e9b3d4f5a6b7c8d90', output='confirmation.xlsx')
```

```console
rqamsh confirmations download --resource "授权测试产品" --confirmation-id 6a1f4c2e9b3d4f5a6b7c8d90 --output confirmation.xlsx
```
