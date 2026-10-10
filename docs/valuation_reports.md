# 估值报告 valuation_reports

估值报告是一份说明某个投资产品在某天值多少钱、持有哪些资产的报表，通常由托管或估值机构提供。把它导入 AMS，可以保存外部提供的结果并用于核对；是否用于调整 AMS 计算结果，见[估值表覆盖设置](reconciliation.md#valuation-report-overwrite-setting)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

报告、持仓明细、产品持仓表及文件信息见[估值报告字段](fields/valuation_reports.md)。

<a id="positions-sheet-input"></a>

## 估值表输入的两种形态

同一业务日的产品截面有两条写入路径，字段形状相同（`date`、`total_equity`、`units`、`unit_net_value`、`positions`），差别在路由、记录键、覆盖规则、对估值生效的条件与能表达的字段：

|形态|写入方法|记录键|凭证来源|覆盖规则|对估值生效的条件|
|---|---|---|---|---|---|
|结构化估值表上传|`rqamsh.valuation_reports.upload` 的 `data`|`id`|ValuationForm|已有同日报告时须 `replace_dates` 或 `is_overwrite=True`，并按[估值表覆盖设置](reconciliation.md#valuation-report-overwrite-setting)决定是否影响估值|需被产品采用：纯估值表数据源、混合数据源开启自动覆盖，或创建时的初始化报告；否则只保存供核对，不改头寸|
|产品持仓表|`rqamsh.positions_sheets.upsert`|`_id`|PositionsSheet|按产品与日期整体覆盖；当日已有估值表覆盖时该日期被跳过，原因写入 `error_messages`|无附加条件：当日没有估值表覆盖时，写入即成为该日截面输入|

两种截面能表达的内容也不同：报告截面还能带分类份额估值、持仓的结算币种公允价（如港币价格，按 [港币汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk) 折算）与应付金额按分类份额的拆分，产品持仓表截面没有这几个字段，提交了也不会落库——该日的分类份额保持计算结果。要覆盖分类份额或指定结算币种价格时只能走报告；只是要给出某日完整截面且不希望受产品「采用报告」设置约束时用产品持仓表。

两条路径对同一天互斥，估值表覆盖优先：当日已存在估值表覆盖时产品持仓表的写入被跳过，被跳过的日期出现在 `error_messages` 中，该日截面以估值表为准。两者都会按各自来源生成导入凭证，可用 `confirmations.latest('ValuationForm')` 与 `confirmations.latest('PositionsSheet')` 核对；产品持仓表的操作细节见[产品持仓表](positions_sheets.md)，与报告的逐项差别见其[与估值表输入的差别](positions_sheets.md#positions-sheet-vs-valuation-report)。

在估值计算中两者是同一位置的两种截面输入：计算按日期命中该日的估值表覆盖或产品持仓表，用命中的那一份作为当日持仓使用；因此写入产品持仓表同样会触发重算。

两者都与[资产单元持仓单](positions_statements.md)不同：资产单元持仓单挂在资产单元上，只服务数量核对，不参与估值，也不触发重算。

两种形态的删除也是各自独立的方法：[删除估值报告](#delete) 按日期删除报告、元数据并取消该日的自动估值表覆盖，[删除产品持仓表](positions_sheets.md#delete) 只删持仓表记录，不动报告与覆盖；两者都按日期而不是记录 ID 删除，都会触发必要重算，返回的 `effect_count` 都只统计自己那一类记录。

字段逐项见[估值报告字段](fields/valuation_reports.md)。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|核对某日是否有托管报告|`list` 明确日期范围；需要原始内容时取 valuation_report_id 调 `download`|元数据日期、source 和原文件一致；列表本身不包含完整报告持仓|
|建立或补充估值报告输入|核对产品数据源 → 准备一份 JSON 或受支持文件 → `upload` → `list`|检查 err_msg、返回日期和记录 ID，并确认报告存在；有效报告仍可能附有解析错误|
|替换已导入的错误报告|先 list/download 留存 → 核对文件实际日期 → 用 replace_dates 精确允许覆盖后 upload|目标日期报告已更新，其他日期不受白名单本身影响；再核对产品头寸报表|
|删除误导入报告|确认授权及日期 → `delete(dates=...)` → `list`|目标报告已移除，相关自动估值表覆盖影响已核对；删除参数不是报告 ID|
|定位需要补导的日期|`missing_dates` 取缺失交易日 → 与应覆盖区间核对 → 逐日 `upload` → 再次 `missing_dates` 复核|返回日期均已补导或被明确排除，且未把缺失日期当作零净值|

导入保存与采用估值表覆盖是两个完成条件。适用数据源、自动覆盖设置与初始化例外见[估值表覆盖设置](reconciliation.md#valuation-report-overwrite-setting)；覆盖的影响、核对流程与自动对账见[对账](reconciliation.md#valuation-report-overwrite)。


## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。替换示例产品、ID 与路径，写入、覆盖和删除须获得授权。网关上读取与下载要求 `read_import_data`，导入/删除要求目标产品 `write`（客户端不预判权限）；JSON 和文件按本页字段与覆盖规则准备。

## list
列出产品已导入估值报告元数据。

Python 签名：`rqamsh.valuation_reports.list(resource: str, *, start_date: str | None=None, end_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略使用产品起始日，并受交易起始日限制。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略为今日。|

返回：原始列表，每项是一份已导入估值报告的元数据；列表不含报告净值与持仓。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|报告元数据|object|—|一份已导入估值报告的元数据|恒返回；服务端固定只返回下列四个键，没有 `_id`|
|`[].date`|业务日期|string|YYYY-MM-DD|该报告的业务日期，不等同写入时间|恒返回；字段明细见[估值报告文件信息](fields/valuation_reports.md#valuationreportmetadata)|
|`[].file_name`|原上传文件名|string|—|该报告保存的源文件名|恒返回|
|`[].valuation_report_id`|估值报告业务记录 ID|string|字符串 ID|下载与比对这份报告时使用的 ID|恒返回|
|`[].source`|来源|string（枚举）|—|该报告的来源；取值见[估值报告来源](fields/valuation_reports.md#valuationreportsource)|恒返回|

结果检查：按 date 核对目标区间与缺失日期，保存 valuation_report_id 供下载使用。列表仅有元数据，不能据此断定报告净值或持仓正确；省略日期可能不覆盖用户要查的历史区间。

```python
result = rqamsh.valuation_reports.list(resource='授权测试产品')
```

```console
rqamsh valuation-reports list --resource "授权测试产品"
```

## upload
上传一个结构化估值报告或一个估值文件，二者互斥。
[顶层、嵌套positions、分类份额、元数据字段](fields/valuation_reports.md)。结构化 data 是**一份报告对象**，不要添加外层 valuation_report 包装。file_path 是一份 CSV/Excel 文件，二者必须且只能提供一个。结构化输入必填 date、total_equity、units、unit_net_value、positions；非类现金持仓须 quantity、cost_price；期货还须 sterilisation_market_value。结构化报告会生成 CSV 作为源文件保存，所以 download 也适用于结构化导入。

```json
{"date":"2026-01-05","total_equity":1000000.0,"units":1000000.0,"unit_net_value":1.0,"acc_unit_net_value":1.0,"positions":[{"order_book_id":"CNY","symbol":"活期存款","asset_class":"current_deposit","direction":"long","market_value":1000000.0}]}
```
上传默认 is_overwrite=False；同产品同日已有报告时拒绝（服务端文案：该产品在YYYY-MM-DD已存在估值表），除非该日位于 replace_dates 或显式 is_overwrite=True。replace_dates 是**允许覆盖的白名单**，不是要求删除这些日期全部报告；真实只处理当前上传报告日期。通过检查后按产品+日期 upsert报告，不是按positions逐条合并。

source 默认open_api，允许manual/open_api/client_upload，取值见[估值报告来源](fields/valuation_reports.md#valuationreportsource)。日期不能晚于到期日；封账和静态会计保护仍适用。是否写入估值表覆盖输入并触发重算，按[估值表覆盖设置](reconciliation.md#valuation-report-overwrite-setting)判断。
文件应采用所属托管/估值机构受支持的模板，不能上传任意 Excel 并假定可解析。若无法确认模板兼容性，可按字段契约准备结构化报告；无论采用哪种方式，都须核对返回日期、净资产和持仓是否符合原始业务数据。

有效报告也可能伴随解析错误；部分失败异常保留完整结果，不保证已保存内容回滚。

Python 签名：`rqamsh.valuation_reports.upload(resource: str, data: dict[str, Any] | None=None, *, file_path: str | None=None, replace_dates: list[str] | None=None, is_overwrite: bool=False, source: str='open_api')`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称，须支持估值报告数据源。|
|`data`|`dict[str, Any] \| None`|`None`|报告 JSON，必含 date、total_equity、units、unit_net_value、positions。|
|`file_path`|`str \| None`|`None`|本地估值文件路径，与 data 互斥。|
|`replace_dates`|`list[str] \| None`|`None`|允许覆盖已有报告的 YYYY-MM-DD 数组。|
|`is_overwrite`|`bool`|`False`|是否无条件允许覆盖同日报告，默认 false。|
|`source`|`str`|`'open_api'`|报告来源枚举，默认 open_api。|

返回：原始写入结果，`err_msg` 非空时抛部分失败异常并保留完整结果。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|返回根|object|—|一次导入的写入结果对象|恒返回|
|`err_msg`|解析错误说明|array（string 元素）|—|该报告解析过程中产生的错误文本|恒返回，结构化导入为空数组；非空即抛部分失败异常且已保存内容不回滚，见[逐项失败容器](connection.md#item-errors)|
|`confirmation_id`|导入凭证 ID|string|字符串 ID|本次导入生成的凭证 ID，可用 `confirmations` 核对|恒返回|
|`effect_count`|实际影响条数|integer|条|按产品与日期 upsert 实际命中的报告数|恒返回；新建报告时为 1，覆盖后内容未变化时为 0，不代表请求失败；见[写入结果](connection.md#write-result)|
|`valuation_report_id`|估值报告业务记录 ID|string|字符串 ID|本次写入的报告记录 ID，下载时使用|恒返回|
|`date`|业务日期|string|YYYY-MM-DD|本次实际写入的报告日期|恒返回；以服务端按报告内容解析出的日期为准|
|`is_modified`|是否覆盖已有报告|boolean|—|本次是否修改了同日已有报告|恒返回；新建同日报告时为 false，与 `effect_count` 一起解读|

操作检查：上传前查同日报告并明确是否允许替换；replace_dates 比全局 is_overwrite 更适合限定授权日期。返回或部分失败后先检查 err_msg、date、valuation_report_id，并 list/download 核对已保存内容，再决定是否重试；估值更新还需检查 auto_overwrite 和头寸报表。

```python
import json
from pathlib import Path

result = rqamsh.valuation_reports.upload(resource='授权测试产品', data=json.loads(Path("report.json").read_text(encoding="utf-8")))
```

```console
rqamsh valuation-reports upload --resource "授权测试产品" --input @report.json
```

文件入口及有范围的同日覆盖授权示例：

```python
result = rqamsh.valuation_reports.upload(resource="授权测试产品", file_path="valuation.xlsx", replace_dates=["2026-01-05"])
```

```console
rqamsh valuation-reports upload --resource "授权测试产品" --file-path valuation.xlsx --replace-dates '["2026-01-05"]'
```

replace_dates 仅放行上传文件实际日期的已有报告；并不删除白名单里的其他日期。

## delete
按日期删除估值报告、元数据和自动估值表覆盖头寸报表，并触发必要重算。

删除参数是日期而非记录 ID，会处理对应报告、元数据和相关自动估值表覆盖记录。封账前的报告管理范围与估值影响范围可能不同，删除后分别核对报告列表及受影响日期头寸报表。

Python 签名：`rqamsh.valuation_reports.delete(resource: str, dates: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`dates`|`list[str]`|必填|非空 YYYY-MM-DD 数组，不是估值报告 ID。|

返回：服务端原始 `effect_count`；删除不可撤销。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|返回根|object|—|只含 `effect_count` 一个键的对象|恒返回|
|`effect_count`|实际删除条数|integer|条|本次按日期实际删除的估值报告条数|恒返回；该日期没有报告时为 0，不代表请求失败；同一日期还会一并删除元数据与自动估值表覆盖记录，但计数只统计报告记录，见[写入结果](connection.md#write-result)|

操作检查：先 list/download 保存目标日期报告，确认 dates 是业务日期而非记录 ID。返回后检查 effect_count 和同日期列表；删除还可能移除自动覆盖头寸报表并触发重算，应核对受影响估值，不将报告删除结果当作重算完成证明。

```python
result = rqamsh.valuation_reports.delete(resource='授权测试产品', dates=['2026-01-05'])
```

```console
rqamsh valuation-reports delete --resource "授权测试产品" --dates '["2026-01-05"]'
```

## download
下载指定估值报告的源文件。

Python 签名：`rqamsh.valuation_reports.download(resource: str, valuation_report_id: str, output: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|归属产品唯一 ID 或名称。|
|`valuation_report_id`|`str`|必填|list 返回的估值报告 ID。|
|`output`|`str`|必填|必填本地输出文件路径。|

`valuation_report_id` 必须来自目标产品的报告列表；不匹配会返回 `resource_not_found`。确认产品和报告归属后再重试，不能仅更换产品名称来尝试读取其他产品的报告。

返回：客户端下载元数据；不依服务端文件名选择本地路径。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；与落盘文件核对，`0` 不代表内容完整|

交付检查：使用目标产品 list 返回的报告 ID，显式指定 output。确认下载元数据与文件已保存，打开文件核对日期及内容；结构化导入的源文件为生成的 CSV，不因本地扩展名而变成 Excel 格式。

```python
result = rqamsh.valuation_reports.download(resource='授权测试产品', valuation_report_id='0123456789abcdef01234567', output='export.xlsx')
```

```console
rqamsh valuation-reports download --resource "授权测试产品" --valuation-report-id "0123456789abcdef01234567" --output "export.xlsx"
```

## missing_dates
列出产品缺失估值表的交易日，用于定位需要补导的日期。

区间与 [`list`](#list) 相同：从产品起始日（受交易起始日限制）到最近结算日，只统计其中的交易日（见 [交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)）。结果由集合差集生成，**不保证按日期升序**，也不补全非交易日。

Python 签名：`rqamsh.valuation_reports.missing_dates(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|

返回：服务端原始 `YYYY-MM-DD` 字符串数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|缺失交易日|string|YYYY-MM-DD|区间内没有估值报告的交易日|恒返回；由集合差集生成，不保证按日期升序，也不补全非交易日|

结果检查：把返回日期与用户要求覆盖的区间、以及该产品实际应为纯估值表还是混合/交易源一起核对；缺失估值表不等于缺净值（交易源产品可由流水计算），不能把缺失日期当作零净值。读取需要导入数据权限。

```python
result = rqamsh.valuation_reports.missing_dates(resource='授权测试产品')
```

```console
rqamsh valuation-reports missing-dates --resource "授权测试产品"
```
