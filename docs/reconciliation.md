# 对账 reconciliation

对账是把同一产品同一天的 AMS 计算/记账结果与外部资料（托管估值表、资产单元持仓单）放在相同口径下比较：找出缺件与差异、记录人工确认状态，必要时用估值表覆盖当日结果。对账本身不产生新的交易或事件数据，比较结果不会自动修改持仓、净值或指标。

本页覆盖四类操作：

- **状态**：区间内每天是否有估值表、是否有持仓单、是否已自动对账、人工标记与缺件提示。
- **差异**：产品级按分组比较 AMS 结果与当日估值表；资产单元级比较 AMS 持仓与已导入持仓单。
- **人工标记**：为某天写入完成状态与备注，不触发重算。
- **自动对账**：把某日估值表写入估值表覆盖并提交重算（`auto`），或撤销覆盖并提交重算（`undo_auto`）。

相关对象字段见[估值报告字段](fields/valuation_reports.md)、[资产单元与持仓单字段](fields/asset_units.md)、[头寸字段字典](fields/balances.md)；差异分组与缺件类型枚举见[对账差异分组](#reconciliationdiffgroup)与[对账缺件类型](#reconciliationlacktype)。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

<a id="valuation-report-overwrite"></a>

## 估值表覆盖

**估值表覆盖**是把某日托管估值报告作为该日估值状态的依据，替换或调整 AMS 原先按流水、行情和业务事件计算的持仓、份额及净值；不是追加一笔交易，也不是只保存附件。调整后的状态还可能影响后续日期的盈亏与净值。

例如托管报告与 AMS 同日净资产有差异：只保存报告可用于比较；采用估值表覆盖后，AMS 会按报告持仓和净值重建或调整该日状态。结果一致不代表原流水已经核对无误，差异来源仍需解释。

是否采用报告由产品自身的 `data_source` 与 `auto_overwrite` 决定，规则见下节。自动对账 `auto` 与报告导入路径写的是同一份估值表覆盖输入，`undo_auto` 只删除该输入，不替代报告本身。

<a id="valuation-report-overwrite-setting"></a>

### 采用报告的设置

- 纯估值表产品（`data_source=valuation_report`）：后续有效报告导入会写入估值表覆盖输入，并提交从报告日开始的重算。
- 混合产品（`data_source=trade_and_valuation_report`）：后续报告是否自动进入估值表覆盖由 `auto_overwrite` 控制；关闭时保存报告不等于校准净值。
- 创建时的初始化报告另有规则：纯估值表或混合产品提供有效初始化报告时，会作为估值起点写入估值表覆盖输入，不要求先开启 `auto_overwrite`。不能据此推断以后每份报告都自动覆盖。
- 修改 `auto_overwrite=True` 会把已保存的报告批量写入估值表覆盖输入；改为 `False` 会移除已有估值表覆盖输入。开关不是只影响未来上传，变更前需保留历史配置与核对结果。

上传参数 `is_overwrite` / `replace_dates` 与这里的设置是两件事：它只允许**替换同日已保存的报告记录**（范围见[报告上传](valuation_reports.md#upload)），不自动开启估值表覆盖；开启估值表覆盖也不等于每次上传都允许替换同日报告。字段本身见[产品字段](fields/products.md)。

### 估值表覆盖的影响与核对方法

1. 报告的持仓截面不是增量买入；原持仓未列入报告时按相应估值表覆盖分支清仓。价格、数量、成本及在途状态依品种处理，不是把所有 JSON 字段机械复制。
2. 产品净资产以报告值为目标，可能通过其他资产科目调平；日盈亏与收益率采用估值表覆盖分支。逐仓盈亏合计不保证等于产品日盈亏。具体公式见[头寸字段](fields/balances.md#balance-calculation)。
3. 估值表覆盖时，分类份额只覆盖已存在分类的相应字段：`null` 不覆盖，显式 `0` 覆盖，各字段独立；详见[分类份额](fields/balances.md#productsharevalue)。
4. 对账前保存原报告、同日头寸与产品配置；导入后检查逐项错误和报告日期，再用 `products.compute_state` 等待估值就绪，并通过 `balances.get/series` 核对报告日及后续受影响日期。

封账、静态会计与权限限制仍适用。关闭估值表覆盖或删除报告不是恢复某份旧结果的承诺；需等待重新计算并核对。**报告保存成功、重算完成、业务对账通过是三个不同结论。**

<a id="netting-derived-shadow-trades"></a>

### 轧差推导影子流水

**轧差推导影子流水**是覆盖日按「报告持仓数量与系统持仓数量的差额」补写的买入/卖出记录，来源取[流水来源](fields/trades.md#tradesource)中的 `netting_derived_shadow`。它解释报告数量与系统数量的差异，不是真实成交：当日持仓、成本、现金与净资产都直接取报告值，影子流水不参与计算，也不带入后续日期。

生成条件与数量：

- 覆盖日逐仓比对；数量差额 = 报告数量 − 上一估值日数量 − 当日已发生的同一持仓数量变动（用户录入流水、当日自动权益的[分红与送股](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)、[拆分](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_split)送股、划入划出、代码转换等）。差额为 `0` 的持仓不生成记录，但该持仓的数量、成本与公允价仍按报告改写。
- 差额为负时仍只写一条减少记录，数量取差额的绝对值。
- 报告有、上一估值日没有或已清仓的持仓视为当日开仓（开仓日期按覆盖日给出，报告信息有限，不保证是真实开仓日）；系统有、报告没有的持仓视为当日清仓，同样按差额写出一条减少记录。
- 有[产品持仓表](positions_sheets.md)、没有同日估值表的日期同样走该分支，覆盖来源取该产品持仓表。

类型与价格：

- 数量增加时多头记 `buy`、空头记 `short_sell`；<br>&emsp;价格由「报告数量×报告成本单价 − 上一估值日数量×(上一估值日含费均价 − 当日每股已发生分红) − 当日已发生的变动金额合计」按差额绝对值反解。<br>&emsp;反解价格完全取决于报告的数量与成本单价：报告缺成本单价时价格按 0 记录（只影响这条记录），报告自身矛盾时会得到负数或明显偏离当日区间的价格——核对时价格与数量要一起看。
- 数量减少时多头记 `sell`、空头记 `buy_to_return`，价格取报告公允价；报告未列出的持仓取当日系统公允价。

记录形态：`trading_date` 为覆盖日、时间固定当日 `20:00`、数量取绝对值、币种与汇率取该持仓当日值、来源为「轧差推导影子流水」，并按通用规则带预估现金变动。现状下这类记录的 `asset_class` 一律记为股票，基金类持仓的影子流水也按股票记录（字段见[交易流水字段](fields/trades.md#trade)）。

生成范围：只有按股票与基金类持仓处理的品种会生成——股票、ETF、LOF、开放式、封闭式、REITs、其他基金、货币基金；债券、可转债以及期货、期权、回购、存款和科目类持仓在覆盖时按各自口径改写数量、成本与公允价，不产生这类记录。

与同日倒推成交额的区别：覆盖日系统还会按当日与上一估值日的持仓成本倒推买卖成交额，用于成交额与换手率类指标（见[头寸字段](fields/balances.md#buy-amount)）。倒推成交额只进指标，影子流水是逐条记录，两者不是同一结果，也不要求互相相等。

落库与重算：影子流水与当日自动权益流水写入同一批流水记录，可按 `sources=['netting_derived_shadow']` 查询。从覆盖日起重算会先删除该日起的自动权益流水与轧差推导影子流水、再按新结果重建，记录 ID 会变化；核对时按日期与标的重新查询，不要复用重算前的 ID。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|查看哪些日期缺估值表或持仓单|`reconciliation.list` 给出产品与区间 → 按 `lack`、`have_position_statement`、`done` 筛出待办|缺件与人工状态明确；状态只说明上传与标记情况，不判断差异金额|
|核对某日 AMS 与估值表的差异|确认数据源与当日报告 → 按需选择分组 `reconciliation.diff`|差异行逐组解释，或确认该组无差异；无差异行不等于业务无差错|
|核对某日资产单元数量|`asset_units.list/get` 确认单元 → `reconciliation.asset_unit_diff` 看逐行差异，或 `positions_statement` 取一致性结论|差异行或结论与持仓单、头寸报表一致；拆分/送股提示需人工确认|
|记录人工对账结果|`reconciliation.mark` 写入 `done`/`description` → `reconciliation.list` 读回|读回结果与写入一致；标记不触发重算|
|采用或撤销估值表自动对账|确认授权与目标日期 → `reconciliation.auto` 或 `undo_auto` → `products.compute_state` → `balances.get`|计算状态为 `normal`，覆盖影响按[估值表覆盖](#valuation-report-overwrite)解释；调用返回不代表计算完成|

## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。示例产品、日期需替换为已获授权的目标；`auto`、`undo_auto` 与 `mark` 写入前须确认授权与影响范围。

读取操作（`list`、`diff`、`asset_unit_diff`、`positions_statement`）在网关上要求 `write`（对账相关路由按写入级别授权），返回含持仓口径比较；产品处于计算中或计算失败时，差异读取按计算状态报错，应先用 `products.compute_state` 确认。写入操作（`mark`、`auto`、`undo_auto`）要求 `write`。日期参数只校验 `YYYY-MM-DD` 格式，未来日期、产品起始日与封账等业务限制由服务端按操作校验。等待、超时与错误沿用客户端统一协议，写入不会被重放。

## list
批量查询多个产品的区间对账状态。

Python 签名：`rqamsh.reconciliation.list(resources: list[str], *, start_date: str, end_date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resources`|`list[str]`|必填|非空产品 ID 或名称数组；一次目录快照解析、去重并保持首现顺序，不支持产品组和资产单元。|
|`start_date`|`str`|必填|起始日期 YYYY-MM-DD。|
|`end_date`|`str`|必填|截止日期 YYYY-MM-DD。|

返回：数组，每个产品一项 `{product_id, product_name, reconciliation_list}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|产品对账项|array（object 元素）|—|每个产品一项，键为 `product_id`（字符串 ID）、`product_name`（string）与 `reconciliation_list`（日度对账项数组）|恒返回；日期集合为区间 [交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates) 与已导入报告日期的并集|
|`[].reconciliation_list`|日度对账项|array（object 元素）|—|元素结构见下方「日项字段」表|恒返回|

日项字段（`reconciliation_list` 的元素）：

|字段|含义|
|---|---|
|`date`|对账日期。|
|`closed`|封账标记：该日不晚于产品封账日期时为 true（修改受封账限制）；未设封账日期为 false。|
|`auto_reconciled`|该日是否存在自动对账（估值表覆盖）记录。|
|`unit_net_value`、`acc_unit_net_value`|该日有估值表时的净值对照 `{ams, valuation_report}`；没有估值表时不出现。|
|`have_position_statement`|该日已有持仓单的资产单元 ID 数组；没有时不出现。|
|`description`、`done`|人工标记；未写时为 `""` 与 `false`。|
|`lack`|缺件提示：当日有估值表且持仓单齐备时为空对象；缺件时给出 `type`（取值见[对账缺件类型](#reconciliationlacktype)），缺持仓单时附 `asset_unit_list`（资产单元名称）。|

结果检查：先核对返回的产品与日期区间是否符合用户要求。`have_position_statement` 是资产单元 ID，`lack.asset_unit_list` 是资产单元名称，两者不能混用。`reconciliation_list` 为空时先核对区间内是否已有头寸报表，而不是直接判定已对上。

```python
result = rqamsh.reconciliation.list(resources=['授权测试产品'], start_date='2026-01-01', end_date='2026-01-31')
```

```console
rqamsh reconciliation list --resources '["授权测试产品"]' --start-date 2026-01-01 --end-date 2026-01-31
```

<a id="reconciliationdiffgroup"></a>

## 对账差异分组

`reconciliation.diff` 的 `fields` 取值。

|值|含义|
|---|---|
|`positions`|持仓数量与多空方向对照；回购按市值÷100 折算数量口径|
|`prices`|持仓估值价格对照；比较 `fair_value` 或结算币种价 `fair_value_setl_ccy`|
|`payable`|应付项目对照|
|`receivable`|应收项目对照|
|`cash`|现金与存款类科目对照|
|`shares_payable`|分类份额名下应付项目对照|
|`net_asset`|净资产、份额、单位净值与累计单位净值对照|

<a id="reconciliationlacktype"></a>

## 对账缺件类型

`reconciliation.list` 日项 `lack.type` 的取值。

|值|含义|
|---|---|
|`none`|当日无估值表，且当日已生效、绑定持仓的资产单元都没有可用持仓单（含没有这类资产单元的情况）|
|`valuation_report`|当日无估值表，但持仓单不缺（无需提交或已齐）|
|`positions_statement`|当日有估值表，但部分资产单元缺持仓单；日项另附 `asset_unit_list`（资产单元名称）|
|`both`|当日无估值表，且部分（非全部）资产单元缺持仓单|

`lack` 只在缺件时携带 `type`；当日有估值表且持仓单齐备时 `lack` 为空对象。

## diff
按差异分组比较产品某日的 AMS 结果与当日估值表。

仅“交易流水 & 估值表”（`data_source=trade_and_valuation_report`）产品支持；当日没有估值表、或产品处于计算中/计算失败状态时，服务端报错。此操作只比较，不写入。

Python 签名：`rqamsh.reconciliation.diff(resource: str, *, date: str, fields: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`date`|`str`|必填|对账日期 YYYY-MM-DD。|
|`fields`|`list[str]`|必填|非空差异分组数组；重复项去重并保持首现顺序，取值见[对账差异分组](#reconciliationdiffgroup)。|

返回：对象，键为请求的差异分组名，值为该分组的差异行数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`（根对象）`|分组差异|object|—|键为请求 `fields` 中的分组名（取值见[对账差异分组](#reconciliationdiffgroup)），值为该分组的差异行数组|由参数选择；按键顺序只返回请求的分组，分组无差异时为空数组|

分组行字段：

|分组|每行字段|
|---|---|
|`positions`|`order_book_id`、`direction`（多空方向中文；回购方向单列为“正回购/逆回购”）、`symbol`、`asset_class`、`quantity{ams, valuation_report}`；回购以市值÷100 作为数量口径。|
|`prices`|`order_book_id`、`symbol`、`asset_class`、`price{ams, valuation_report, field}`；`field` 为 `fair_value` 或 `fair_value_setl_ccy`；只比较两来源都有的非现金类、非回购持仓，且估值表数量不为 0。|
|`payable`、`receivable`、`cash`|`key`（asset_class 值）、`name`、`ams`、`valuation_report`；负债类金额按正数展示。|
|`shares_payable`|`product_share`、`name`、`ams`、`valuation_report`，即分类份额名下的应付项目。|
|`net_asset`|`key`（`acc_unit_net_value`、`unit_net_value`、`total_equity`、`units`）、`name`、`ams`、`valuation_report`；产品有分类份额时附 `children[{name, ams, valuation_report}]`。|

`positions`、`prices` 行中该持仓同时属于产品内资产单元时附 `is_asset_unit: true`。

结果检查：差异行是两个来源的对照，不是自动判定；数量口径（如回购市值÷100）、负债正数展示与是否枚举类现金都会影响解读。分组无差异行不代表其他分组或后续日期无问题；解释差异时同时核对报告日期与 `products.compute_state` 的估值状态。

```python
result = rqamsh.reconciliation.diff(resource='授权测试产品', date='2026-01-05', fields=['positions', 'net_asset'])
```

```console
rqamsh reconciliation diff --resource "授权测试产品" --date 2026-01-05 --fields '["positions","net_asset"]'
```

## asset_unit_diff
比较资产单元某日的 AMS 持仓与已导入持仓单数量。

Python 签名：`rqamsh.reconciliation.asset_unit_diff(resource: str, *, date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称。|
|`date`|`str`|必填|对账日期 YYYY-MM-DD。|

返回：差异行数组；该品种当日发生拆分或送股时附 `warnings`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|持仓差异行|array（object 元素）|—|每行 `asset_class`（资产类别枚举）、`direction`（多空方向枚举值）、`order_book_id`（标的代码）、`symbol`（string）与 `quantity`（对象，含 `ams`、`valuation_report`，number，数量）|恒返回；按 `(asset_class, direction, order_book_id)` 对齐两侧，单边缺失时该侧为 `0`；当日没有 AMS 头寸时返回不报错的空数组|
|`[].warnings`|拆分或送股提示|string|—|该品种当日发生拆分或送股时的说明：拆分系数、登记日、除权除息日及基于登记日持仓计算的预估变动数量|由数据决定；只有该品种当日有拆分或送股时才出现|

结果检查：按 `(asset_class, direction, order_book_id)` 对齐两侧数量；`ams` 或 `valuation_report` 为 0 表示单边缺失。带 `warnings` 的差异先按拆分/送股业务确认，再决定是否需要修正输入。

```python
result = rqamsh.reconciliation.asset_unit_diff(resource='测试资产单元', date='2026-01-05')
```

```console
rqamsh reconciliation asset-unit-diff --resource "测试资产单元" --date 2026-01-05
```

## positions_statement
判断资产单元某日的 AMS 持仓与已导入持仓单数量是否一致。

Python 签名：`rqamsh.reconciliation.positions_statement(resource: str, *, date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|资产单元唯一 ID 或名称。|
|`date`|`str`|必填|对账日期 YYYY-MM-DD。|

返回：`{is_consistence}`，只含一个布尔结论。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`（根对象）`|持仓一致性结论|object|—|只含一个键 `is_consistence`（boolean：两侧 `(asset_class, direction, order_book_id) → quantity` 集合完全相等时为 `true`）|恒返回；AMS 侧排除类现金科目并剔除零数量仓位，持仓单侧剔除零数量仓位，不做金额容差|

边界：未来日期被拒绝；不晚于最近结算日的历史日期要求该资产单元当日已有头寸，否则报错；当天不读取 AMS 头寸，AMS 侧按空集合参与比较（通常只在持仓单也为空时为 true）。该结论不能代替 `asset_unit_diff` 的逐行差异与拆分提示。

```python
result = rqamsh.reconciliation.positions_statement(resource='测试资产单元', date='2026-01-05')
```

```console
rqamsh reconciliation positions-statement --resource "测试资产单元" --date 2026-01-05
```

## mark
写入产品某日的人工对账标记（`done`、`description` 的 upsert）。

Python 签名：`rqamsh.reconciliation.mark(resource: str, *, date: str, done: bool | None=None, description: str | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`date`|`str`|必填|对账日期 YYYY-MM-DD。|
|`done`|`bool \| None`|`None`|是否完成对账；省略时不写该字段。|
|`description`|`str \| None`|`None`|备注；省略时不写该字段。|

至少提供 `done` 或 `description` 之一，否则客户端拒绝。

返回：服务端原始 `{effect_count}`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际修改的既有对账标记记录数|恒返回；只统计被修改的既有记录，新建记录时为 `0`，不能据此断定状态未变；见[写入结果](connection.md#write-result)|

写入边界：只写对账标记，不触发重算，也不改变估值表覆盖或报告；已封账日期仍可标记。结果检查：用 `reconciliation.list` 读回该日 `done` 与 `description`，确认与写入一致；标记是人工确认，不构成对账通过的技术判定。

```python
result = rqamsh.reconciliation.mark(resource='授权测试产品', date='2026-01-05', done=True, description='托管差异已确认')
```

```console
rqamsh reconciliation mark --resource "授权测试产品" --date 2026-01-05 --done true --description "托管差异已确认"
```

## auto
用该日估值表写入估值表覆盖并提交重算（自动对账）。

Python 签名：`rqamsh.reconciliation.auto(resource: str, *, date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`date`|`str`|必填|对账日期 YYYY-MM-DD。|

边界：当日没有估值表时服务端报错；日期早于产品起始日或处于封账限制范围时被拒绝。写入会改变该日及之后的估值结果，执行前保存原报告、同日头寸与产品配置并取得授权。

返回：空响应，客户端得到 `None`（服务端返回空串）。

返回只表示覆盖已写入且计算已提交，**不代表计算完成**。结果检查：用 `products.compute_state` 等待计算，再以 `balances.get` 核对报告日及后续日期；`reconciliation.list` 中该日 `auto_reconciled` 应变为 true。

```python
result = rqamsh.reconciliation.auto(resource='授权测试产品', date='2026-01-05')
```

```console
rqamsh reconciliation auto --resource "授权测试产品" --date 2026-01-05
```

## undo_auto
撤销产品某日的自动对账覆盖并提交重算。

Python 签名：`rqamsh.reconciliation.undo_auto(resource: str, *, date: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`date`|`str`|必填|对账日期 YYYY-MM-DD。|

边界：与 `auto` 相同，受产品起始日与封账限制。

返回：服务端原始 `{effect_count}`，即删除的覆盖记录数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的估值表覆盖记录数|恒返回；`0` 只表示本次未删除到记录，不证明该日从未自动对账；见[写入结果](connection.md#write-result)|

结果检查：撤销同样要等待重算并用 `balances.get` 读回该日及后续日期；`undo_auto` 删除的是自动对账写入的覆盖输入，不是报告记录，也不是恢复覆盖前某份旧结果的承诺。

```python
result = rqamsh.reconciliation.undo_auto(resource='授权测试产品', date='2026-01-05')
```

```console
rqamsh reconciliation undo-auto --resource "授权测试产品" --date 2026-01-05
```
