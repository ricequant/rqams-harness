# 产品持仓表 positions_sheets

产品持仓表是某个产品在某一天持有哪些资产、各有多少的截面清单。它是估值计算的输入之一，与[资产单元持仓单](positions_statements.md)不同：持仓单挂在资产单元上、只服务数量核对，不参与估值；产品持仓表挂在产品上、按日期整体覆盖，且当日已有估值表覆盖时不再写入。产品持仓表是估值表截面输入的 JSON 形态，字段见[估值表字段](fields/valuation_reports.md)，与报告的差别见[估值表输入的两种形态](valuation_reports.md#positions-sheet-input)与本页[与估值表输入的差别](#positions-sheet-vs-valuation-report)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

持仓表与持仓明细字段见[估值表字段](fields/valuation_reports.md#positionssheet)。

<a id="positions-sheet-vs-valuation-report"></a>

## 与估值表输入的差别

同一业务日的产品截面有两条写入路径，字段形状相同（`date`、`total_equity`、`units`、`unit_net_value`、`positions`），在估值计算中占同一位置；差别在生效条件与能表达的内容。本页是 `rqamsh.positions_sheets` 这一组操作，报告侧是 `rqamsh.valuation_reports.upload`：

|差别|产品持仓表|结构化估值表上传|
|---|---|---|
|写入后是否影响头寸|当日没有估值表覆盖时即成为该日截面输入，不依赖产品设置|需被产品采用：纯估值表数据源、混合数据源开启自动覆盖，或创建时的初始化报告；否则只保存供核对|
|能否覆盖分类份额|不能：截面结构里没有分类份额估值字段，提交了也不落库|能：可带分类份额估值，覆盖时按分类逐字段处理（`null` 不覆盖，显式 `0` 覆盖）|
|持仓可带字段|`order_book_id`、`symbol`、`asset_class`、`direction`、`market_value`、数量、成本价、成本、公允价、[应计利息](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_accrued_interest_eod)与期货平衡项市值|同左，另含结算币种公允价（如港币价格，按 [港币汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk) 折算）与应付金额按分类份额的拆分|
|记录与文件|无元数据层、无源文件、无下载；删除只删持仓表记录|有报告元数据与源文件可下载；按日期删除会一并删除元数据并取消该日的自动估值表覆盖|

因此按意图选入口：需要覆盖分类份额、指定结算币种价格，或要受产品「采用报告」设置约束时用[估值报告](valuation_reports.md#upload)；只需要给出某日的完整持仓截面、且希望写入即按当日截面生效时用本页的 `upsert`。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|查看某产品已有持仓表|`get` 限定日期区间|返回的日期、净资产、份额与持仓符合目标区间；同日只有一份持仓表|
|导入或更正某日持仓表|准备 JSON，必含 date、total_equity、units、unit_net_value、positions → `upsert` → `get` 读回|成功计数与预期一致、error_messages 为空；同日旧表被覆盖而不是追加|
|确认某个日期为什么没写进去|读取 upsert 返回的 error_messages|该日期已存在估值表覆盖时按跳过处理；此时产品头寸以估值表为准|
|移除误导入的持仓表|`get` 确认日期并取得授权 → `delete(dates=...)` → 重新查询|effect_count 与所选日期数一致；删除参数是日期，不是记录 ID|

## API 使用约定

Python 与 CLI 完成相同业务操作，连接、任务等待及部分失败处理见[连接说明](connection.md)。替换示例产品与日期；写入、覆盖和删除须获得授权。网关上读取要求 `read_import_data`，写入要求目标产品 `write`；客户端不预判权限。

日期为 YYYY-MM-DD。写入按产品与日期 upsert：同一日期再次写入是整体覆盖，不是按持仓逐条合并，因此提交内容必须是该日完整的持仓集合。当日的估值表覆盖优先级更高，被跳过的日期会出现在 error_messages 中并触发部分失败异常；成功写入的日期会生成一张来源为 PositionsSheet 的导入凭证，可用 `confirmations.latest('PositionsSheet')` 核对。

## get
读取产品持仓表。

Python 签名：`rqamsh.positions_sheets.get(resource: str, *, start_date: str | None=None, end_date: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`start_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设下界。|
|`end_date`|`str \| None`|`None`|YYYY-MM-DD；省略不设上界。|

返回：原始持仓表数组，每个元素是一份持仓表。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|持仓表|array（object 元素）|—|该产品在查询区间内的持仓表，元素键为 `date`、`total_equity`、`units`、`unit_net_value`、`positions`、`product_id` 与只读 `_id`，键名与[持仓表字段](fields/valuation_reports.md#positionssheet)一致|恒返回；无记录时为空数组；元素不含 `id`，记录键是 `_id`|

结果检查：核对日期区间与每份持仓表的净资产、份额是否与输入文件一致；本方法读的是输入侧持仓表，不代表 AMS 计算出的头寸，需要计算结果时用[头寸报表](balances.md)。

```python
result = rqamsh.positions_sheets.get(resource='授权测试产品', start_date='2026-01-01', end_date='2026-01-31')
```

```console
rqamsh positions-sheets get --resource "授权测试产品" --start-date 2026-01-01 --end-date 2026-01-31
```

## upsert
按日期新增或覆盖产品持仓表。与[估值报告上传](valuation_reports.md#upload)相比：两者载荷形状相近，但持仓表**不做产品起始日与封账日校验**，被跳过的日期只按[估值表覆盖](reconciliation.md#valuation-report-overwrite-setting)冲突处理。

传入单份持仓表或其非空数组；两种写法发送完全相同的请求体（JSON 数组）。每份持仓表必含 date、total_equity、units、unit_net_value 与 positions；每条持仓必含 order_book_id、symbol、asset_class、direction、market_value，可选 quantity、cost_price、cost、fair_value、accrued_interest；期货类资产还必须提供 sterilisation_market_value，缺少时服务端以 500 拒绝（不是参数校验错误）。

读取返回的记录键 `_id` 只用于识别：持仓表与持仓明细都不接受 `id`/`_id` 回传（服务端会把 `id` 改写成不可变的 `_id` 再 set），带这些键的请求在发出前被客户端以 `invalid_argument` 拒绝。原样回传读取结果前请先删除这两个键。

Python 签名：`rqamsh.positions_sheets.upsert(resource: str, data: dict[str, Any] | list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`data`|`dict \| list[dict]`|必填|单份持仓表对象或其非空数组。|

返回：服务端原始写入结果，含四项计数与未写入原因。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`inserted_expected_count`|预计新增数|integer|条|提交内容里日期尚不存在的持仓表数|恒返回|
|`modified_expected_count`|预计覆盖数|integer|条|提交内容里日期已存在的持仓表数|恒返回|
|`inserted_success_count`|实际新增数|integer|条|实际新增的持仓表数|恒返回；提交内容全部被跳过时为 `0`|
|`modified_success_count`|实际覆盖数|integer|条|内容实际发生变化的持仓表数|恒返回；重复提交完全相同的内容时为 `0`，不代表失败|
|`error_messages`|未写入原因|array（string 元素）|—|每个未写入日期的原因，形如「产品X在YYYY-MM-DD已存在估值表覆盖」|恒返回；无跳过日期时为空数组，非空即抛部分失败异常，见[逐项失败容器](connection.md#item-errors)|

结果检查：先看 error_messages 是否为空，再比较 expected 与 success 计数；同一日期重复提交完全相同的内容时 modified_success_count 为 0，这不是错误（记录没有变化），但同样会生成一份凭证；存在被跳过的日期时抛部分失败异常，异常详情保留完整结果。写入完成后用 `get` 读回该日期确认内容，不要只看计数。

```python
sheet = {
    "date": "2026-01-05",
    "total_equity": 1000000.0,
    "units": 1000000.0,
    "unit_net_value": 1.0,
    "positions": [
        {"order_book_id": "CNY", "symbol": "活期存款", "asset_class": "current_deposit", "direction": "long", "market_value": 1000000.0},
    ],
}
result = rqamsh.positions_sheets.upsert(resource='授权测试产品', data=sheet)
```

```console
rqamsh positions-sheets upsert --resource "授权测试产品" --input @positions_sheet.json
```

## delete
按日期批量删除产品持仓表。

Python 签名：`rqamsh.positions_sheets.delete(resource: str, dates: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`dates`|`list[str]`|必填|非空 YYYY-MM-DD 数组，不是持仓表记录 ID；空数组在发送前即被拒绝。|

返回：服务端原始写入结果，只含删除条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次按日期实际删除的持仓表条数|恒返回；参数是日期而不是记录 ID，该日期没有持仓表时为 `0`，不代表请求失败；见[写入结果](connection.md#write-result)|

结果检查：删除前用 `get` 确认这些日期确实存在；删除不可撤销并触发必要重算，随后重新查询确认目标日期已消失、无关日期未受影响。

```python
result = rqamsh.positions_sheets.delete(resource='授权测试产品', dates=['2026-01-05'])
```

```console
rqamsh positions-sheets delete --resource "授权测试产品" --dates '["2026-01-05"]'
```