# 历史流水补录与更正（historical-trade-correction）

> 学习案例，不是接口清单。产品、账户、证券、日期、数量和价格均为构造输入，不代表真实回执或行情；字段、枚举、公式与返回结构以 [`docs/`](../../index.md) 和当前 `rqamsh schema` 为准。

## 学习目标

- 从“补一笔/改一笔成交”定位唯一的产品、账户、交易日与流水来源。
- 根据已有流水、外部流水号与导入凭证，判断新增、更新还是文件导入；不默认“删掉重导”。
- 写前说明授权与影响日期，写入后处理逐项结果、部分失败和结果未知。
- 区分成交价、估值价与费用，用计算状态和实际头寸验证目标日、后续日期与未受影响边界。

## 构造场景

业务用户说：产品“示例产品”在 2026-06-29 有两笔买入，第二笔正确；第一笔实际是 120 股、成交价 11 元，系统里却是 100 股、10 元。请只改这一笔，不要动另一笔，也不要影响 06-29 之前的日期。

|别名|构造值|
|---|---|
|`P`|“示例产品”，交易流水数据源，产品内账户 `A`＝“示例交易账户”|
|`T1`|2026-06-29 10:00，`buy`，`000001.XSHE`，系统值 100 股×10；外部流水号 `demo-20260629-001`|
|`T2`|2026-06-29 10:05，`buy`，另一标的 100 股×20；本次不能动|
|目标|只把 `T1` 改为 `quantity=120`、`price=11`；类型、来源、日期、账户、标的均不变|

日期、数量、价格是构造的；不要把示例价格当成估值价，也不要据此推断真实盈亏。

## 读写与权限边界

- 读取：`products.get`、`trades.list/get`、`confirmations.list/get`、`products.compute_state`、`balances.get`。
- 写入：`trades.upload`、`trades.update`、`trades.upload_intraday_file`、`trades.upload_settlement_file`、`trades.delete`。本案例只计划 `trades.update`；其他写入单独授权。
- 写权限看 `products.list` 返回的 `permissions`：按 `product_id` 匹配本人的 `permission`；`is_owner=true` 是创建者/空间管理员，按最高级别处理。遇到 `permission=forbidden` 先看同一行的 `is_owner`，不能一概判为不可读/不可写；也不能用“能查到流水”推断可写。定位产品不要先靠全量 `products.list`。
- 不要用一次试探写入判断权限。权限不足、产品/账户/日期不能唯一确认、目标日已封账时，停止。

## 第 1 步：定位产品、账户与日期

**为什么。** 同名产品、产品组和跨空间对象都会让请求落错目标；数据源决定能否导入交易流水。

**查什么。** 先按唯一 ID 或唯一名称调用 `rqamsh.products.get(resource="<P 的产品 ID 或唯一名称>")`，读取 `id`、`name`、`data_source`、`accounts`、`start_date`、`closing_date`、`maturity_date`。只有名称有歧义时，才用 `products.list` 展示候选并由用户确认，不先做无筛选的全空间扫描。

`workspaces.list()` 只返回当前用户的成员空间，**不表示当前请求已经路由到哪个空间，也不表示产品归属**；需要显式选择时调用 `rqamsh.workspaces.use(workspace="<成员空间 ID>")`，并核对返回的 `id` 与后续请求使用的空间一致。空间选择只决定分区，不授予产品读写权限。

**判断。** 纯估值报告数据源不能导入流水；账户必须在 `accounts` 中；目标日要在业务区间内且不处于封账范围。产品列表里的可见性只说明能读，写权限仍需按上面的 `permissions` 行确认。

## 第 2 步：查已有流水、来源和导入凭证

**为什么。** “补录”可能是真的没有，也可能是已有记录错了，或文件批次只导入了一部分。不同结论对应不同写法。

**查什么。** 用 `rqamsh.trades.list(resource="<P 的产品 ID>", start_date="2026-06-01", end_date="2026-06-30", account_names=["示例交易账户"], order_book_id="000001.XSHE")` 收窄范围；分页时对照 `total` 与 `offset`/`limit`，确认没有漏读。重点读每条记录的 `_id`、`datetime`、`trading_date`、`transaction_type`、`order_book_id`、`quantity`、`price`、`commission`、`tax`、`other_fees`、`account`、`source`、`foreign_id`、`estimated_delta_cash`。`datetime` 是成交时间，`trading_date` 是所属交易日；夜盘/跨日不要用自然日代替。`estimated_delta_cash` 是服务端只读结果，不是写入输入。

用 `rqamsh.trades.get(resource="<P 的产品 ID>", trade_id="<记录 ID>")` 保存原记录。列表记录的 `_id` 或写入回执的 `id` 才是记录 ID，不能用 `foreign_id` 代替。查询结算替换前的旧流水时，要明确 `is_query_assistant` 的主表/副表选择；默认主表不含已转副表的历史记录。

再用 `rqamsh.confirmations.list(resource="<P 的产品 ID>", start_date=..., end_date=...)` 看导入批次、`total_parsed`、`total_registered`，按凭证 ID 调 `confirmations.get(..., status="failed")`。日期筛选是凭证操作时间，不是业务日期；刚导入时按实际操作时间放宽区间。

**判断。** 列表或凭证没查到，只说明“在当前日期、来源、主/副表和分页条件下没有看到”，不能直接断言确实缺一笔。先核对外部回报、账户、日期、来源和分页是否完整，再决定是否新增。

|观察|判断|
|---|---|
|目标日/账户/标的无记录，材料也支持确实没有|可考虑新增导入|
|恰好一条匹配，数量/价格错|优先 `trades.update`|
|记录与提交值一致|无需写入，保留读回证据|
|同一证券/账户/数量有多条候选，外部流水号不同|停止，要求业务按回报号/成交时间确认|
|凭证 `total_registered < total_parsed`|该批有解析/登记失败；先查失败项和已落库项|
|来源是 `intraday_upload`/`settlement_upload`|先判断是否应重传对应文件，不用结构化上传模拟文件覆盖|

## 第 3 步：选择写入方式

|场景|动作|边界|
|---|---|---|
|目标日无记录，来源是手工/接口数据|`trades.upload`|按同产品非空 `foreign_id` upsert；不按日期清空；空白外部流水号不保证幂等|
|已有记录，只改数量/价格/费用/时间/账户/标的/备注|`trades.update`|不能改 `transaction_type` 或 `source`；内容与现值一致时 `effect_count=0`|
|外部系统按稳定外部 ID 同步同一笔|`trades.upload` 带同一 `foreign_id`|先证明外部 ID 唯一且不会新增；否则可能“更正”成新记录|
|券商日内文件|`trades.upload_intraday_file`，显式给账户和模板|模板取决于券商通道；同日已有结算流水时该日被拒绝|
|日终结算文件|`trades.upload_settlement_file`，显式给账户和模板|按日期/产品/账户/资产单元替换当前有效流水，旧记录转副表；不是“只加一行”|
|原记录不可修复或用户明确要求删除重录|只有单独授权的 `trades.delete`|按日期/筛选可能命中多条；重录会换记录 ID、断开原审计链|

结构化上传缺 `source` 时补 `open_api`，已有 `source` 不覆盖；可写来源是 `manual`/`open_api`/`paper_trading`/`client_upload`，日内与结算来源必须走文件流程。不要默认删除重导：删除不可撤销，范围容易扩大，还会改变记录 ID 和重算范围。

## 第 4 步：写前授权、快照与价格口径

按指南的[写操作计划卡](../../guide.md#6-写操作计划卡)执行通用授权流程；本例填入的范围与快照如下，不另列空白模板。

本例计划是：在 `P` 的账户 `A` 中，按实际记录 ID 将 06-29 的 `T1` 从 100 股、10 元更正为 120 股、11 元；`T2`、交易类型、来源、日期、账户和标的都不改，不影响 06-29 之前的状态。写前保存 `T1`、`T2` 原记录、06-26 基线及 06-29 起受影响日期的 `balances.get` 结果、`compute_state` 的 `state`/`execution_id` 和产品账户/费率/封账配置，供后续逐项对照。

`price` 是实际成交价（不复权），不是估值价；`commission`、`tax`、`other_fees` 按该交易类型的口径进入现金/成本。不要为了凑现金变动改价格，也不要把费用摊进 `price`。`estimated_delta_cash` 是服务端计算结果，不能作为输入。后续日期市值/净资产使用行情/估值价 `fair_value`，不要用成交价解释。

## 第 5 步：写入、逐项结果与未知结果

字段形状取自 [`trades.upload` 示例](../../trades.md#upload)，业务值换成构造值：

```json
[{"datetime":"2026-06-29 10:00:00","transaction_type":"buy","order_book_id":"000001.XSHE","asset_class":"stock","price":11.0,"quantity":120,"commission":5.0,"account":"示例交易账户","foreign_id":"demo-20260629-001"}]
```

```python
result = rqamsh.trades.upload(resource="<P 的产品 ID>", data=items)
```

`upload` 返回按提交顺序排列的逐项结果；每项看 `id` 和错误键。任一项错误（错误键和判定规则见[逐项失败容器](../../connection.md#item-errors)）会抛 `partial_failure`，合法项可能已写入且不回滚。部分失败时保留完整结果，按 `foreign_id`/日期/账户只读查明已落库项，只修复失败项，不整批重发。

本场景已有 `T1`，且已能唯一定位，使用更窄的更新：

```python
result = rqamsh.trades.update(
    resource="<P 的产品 ID>",
    trade_id="<T1 的记录 ID>",
    data={"quantity": 120, "price": 11.0},
)
```

返回 `effect_count` 和 `updated`；`updated` 的完整记录主键为 `_id`。`effect_count=1` 表示实际修改了一条；`0` 表示提交内容与现值一致，不能据此判断记录不存在，也不能直接说已修好。超时、连接中断或响应不完整时结果未知：先按日期/外部流水号/记录 ID 只读确认是否已落库，确认前不发出第二次写，也不自动重试。

## 第 6 步：计算状态、实际读回与边界

`products.compute_state(resource="<P 的产品 ID>")` 只查询一次，不等待、不轮询。公开产品计算状态为 `computing`（计算中）、`normal`、`error`；`error` 立即停止并诊断，`computing` 在总截止时间内只读重查。未知状态或字段缺失先核实，不自行当作完成。`normal` 也可能对应旧结果，必须结合写入前后的 `execution_id` 和目标内容是否更新，不能只看 `normal` 就宣称本次更正已生效。状态正常但目标内容仍未就绪时，按[等待规则](../../connection.md#unready-inputs)有界重读同一结果，不重发写入。

```python
before = rqamsh.balances.get(resource_or_resources="<P 的产品 ID>", date="2026-06-26", fields=["total_equity", "units", "unit_net_value", "positions"])
target = rqamsh.balances.get(resource_or_resources="<P 的产品 ID>", date="2026-06-29", fields=["total_equity", "units", "unit_net_value", "positions"])
after = rqamsh.balances.get(resource_or_resources="<P 的产品 ID>", date="2026-06-30", fields=["total_equity", "units", "unit_net_value", "positions"])
```

`balances.get` 当前签名的第一个关键字参数是 `resource_or_resources`，不要用位置参数。核对：`T1` 读回为 120×11；`T2` 的记录 ID、字段、持仓数量/方向/成本未变（市值随行情变化正常）；06-26 等目标日之前的日期未变；目标日及之后的持仓、现金类资产和净资产按实际估值价推进。顶层 `cash` 为 `null` 时不是 0，按[现金类资产](../../fields/balances.md#cash-classes)从持仓解释。

交付条件：目标记录与授权字段一致且原 ID 保留；未授权记录/日期未变；`normal` 后头寸读回且本次执行/内容可确认；部分失败、`effect_count=0`、未知结果都有只读证据。任一不成立或状态失败，停止并说明未证明项。

## 停止与失败

|情况|动作|
|---|---|
|产品/账户/日期/名称不唯一，或 `permissions` 无法确认可写|停止；不试探写入、不换产品|
|列表/凭证未命中但材料或分页/来源不完整|先补证据，不直接断言“缺失”|
|`partial_failure` / 结果未知|保留逐项结果和 ID，只读核实已落库项，不整批重发|
|`compute_state` 为 `error`，或状态无法解释|停止并诊断，不无限轮询或继续写入|
|目标日封账、数据源不支持、来源批次不明|停止，取得业务确认/授权|

## 可选受控演示

`docs/demo/historical-trade-correction/run.py` 是固定演示：显式给出目标部署/空间、确认口令和新证据/日志路径后，创建一只专用模拟交易产品，导入两笔构造买入，只更正一笔，读回头寸，再按创建回执删除该产品；同名产品或目标日已有流水会拒绝，清理只按创建回执的产品 ID。它只覆盖“模拟交易产品 + 结构化导入 + 单条 update”的固定路径，不覆盖券商文件、权限拒绝、封账、部分失败或未知结果；具体参数与 guard 以脚本说明和 `--help` 为准，不要把它当生产可重放或完整 E2E。

## 变式问题

1. 同一天已有日终结算文件，还要补一笔日内成交：改结构化流水、重传日内文件还是结算文件？哪一步会拒绝？
2. 两条候选记录只有 `foreign_id` 不同：如何唯一定位？为什么不能都改一遍？
3. `update` 返回 `effect_count=0`：如何只读区分“已经一致”和“记录不存在”？
4. 更正后净资产变了但持仓数量没变：费用、估值价、现金类资产分别需要哪些字段才能解释？

## 证据不足时怎么交付

- 先列已确认：产品/账户/日期如何唯一确认、记录 ID、哪些字段一致、哪些日期未变、`compute_state` 实际值。
- 再列未确认：写入未知、部分成功、封账、无权限读头寸、后续日期未重算。不要用“应该没问题”补齐。
- 保留逐项结果、`execution_id`、记录 ID、错误码/HTTP 状态；不粘贴令牌或完整异常堆栈。
- 缺少头寸读回或影响边界时，明确说“尚未证明”，不要用接口成功或脚本退出码代替验收。

## 权威页

- [流水操作与写入校验](../../trades.md)、[流水字段](../../fields/trades.md)
- [写入结果](../../connection.md#write-result)、[逐项失败容器](../../connection.md#item-errors)、[等待与未就绪](../../connection.md#unready-inputs)
- [产品与 permissions](../../products.md)、[资源权限](../../permissions.md)
- [头寸读取](../../balances.md)、[头寸字段](../../fields/balances.md)
- [工作空间](../../workspaces.md)、[导入凭证](../../confirmations.md)

下一步：还要核对托管报告或对账差异时，看[估值表导入与报告核对](../valuation-report-reconciliation/README.md)与[对账控制案例](../reconciliation-controls/README.md)。
