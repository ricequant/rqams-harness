# 日内到结算接管：同一交易日不重复计入成交

[返回流水处理场景](../../README.md)

一个已有估值起点的混合数据源产品，交易日 D 先收到两版日内成交文件，收盘后收到同账户的完整日终结算文件；结算已采用后，数据方又补送一份同日日内文件。托管估值报告迟于成交文件到达。业务问题是：如何证明当日由结算成交接管、原日内成交未重复计入、晚到的日内文件没有改坏结果？

## 1. 从写前证据确定接管对象

用 [products.get](../../../../products.md#get) 确认目标工作空间、产品 ID、`data_source=trade_and_valuation_report`、`auto_overwrite`、日期配置和交易账户；读回 D 日前有效头寸作为基线，沿用已有现金、证券与份额，不因来源切换再次建立起点。核对日内、结算、报告的业务日期分别来自各自原始资料，不按接收顺序指定估值日。

日内阶段按[两版完整日内文件](../intraday-file/README.md)逐次导入。第一版核对截至其截点的成交与估值；第二版必须包含第一版截至新截点仍有效的成交并带上新增或经确认的修订，不是差量。第二版核对完留存汇总和有效逐笔明细、原始文件、各版凭证与头寸。只有第二版已核对，才可将它用作结算接管前的对照。

收盘后将券商的结算工作簿与第二版日内文件逐笔对照，按实际业务口径解释新增成交、撤修、价格或税费不同；差异不一定是错误，但不能凭两个文件行数相同就认为两者等价。检查两类文件均使用该账户 `broker` 支持的各自模板，核对所属账号、交易日、币种、代码与后缀、方向和量价；没有确认的日期、账号、模板或结算版本就先停。

## 2. 让结算接管，不先删除也不另行拼接流水

依据[结算文件导入规则](../../../../trades.md#upload-settlement-file)，按合法行交易日、产品、账户及资产单元，用结算文件替换当前有效的 `intraday_upload`、`open_api` 和 `settlement_upload`。不先删除旧成交，也不把两套同日成交拼成一批。写前本地留存现有有效明细和文件版本，确认替换授权；夜盘按[自然日查询与交易日替换](../intraday-file/README.md#trade-date-coverage)查全可能自然日后再筛交易日，下文单日查询仅适用于本次股票日盘。指定单元先用 [asset_units.get](../../../../asset_units.md#get) 核验归属，替换仅匹配该单元；省略仅匹配未绑定单元旧记录，不表示整账户替换。接口不接受独立日期白名单，不能将其他交易日混入只批准 D 日的文件。

示例在[已连接的 Python 会话](../../../../connection.md#建立连接)中进行。`product_id`、`account` 分别来自已核对产品的 `id` 和 `accounts[].name`；`trade_date` 取 D 日；`asset_unit_id` 取已核对的单元 ID（仅在获准的账户范围内才用 `None`）。`settlement_file_path` 与 `late_intraday_file_path` 分别指向本地已核实的通道结算文件和晚到日内文件，不能互换。

```python
settlement_receipt = rqamsh.trades.upload_settlement_file(
    resource=product_id,
    file_path=settlement_file_path,
    account=account,
    asset_unit_id=asset_unit_id,
)
```

成功的结算任务仍需检查 `data.effect_count` 和 `data.err_msg`；用 `data.confirmation_id` 查[导入凭证](../../../../confirmations.md#get)。然后按原范围拿全有效逐笔流水，不要在查询中先筛掉日内或 OpenAPI，否则无法证明这些来源没有重复计入：

```python
effective_trades = rqamsh.trades.list(
    resource=product_id,
    start_date=trade_date,
    end_date=trade_date,
    account_names=[account],
    asset_unit_ids=[asset_unit_id] if asset_unit_id is not None else None,
)
```

期望是：目标范围内接管的成交以 `settlement_upload` 读回，逐笔与完整结算文件的方向、数量、价格、费用、币种和交易日匹配，没有原日内或 OpenAPI 成交重复计入。已有手工流水或其他合法来源不能靠行数混算进结算批次。需要证明范围外未变时，用先前留存的相邻日期、账户或单元作对照。产品估值不能用任务 `SUCCESS` 代替：检查 [products.compute_state](../../../../products.md#compute_state)，再读 [balances.get](../../../../balances.md#get) 的 D 日和后续可比较日期。按确认后的结算成交重新核对数量、现金和成本，再用实际估值价勾稽市值、净资产、份额及单位净值，字段口径见[头寸字段](../../../../fields/balances.md#balance-calculation)。

## 3. 处理晚到日内文件：先阻止误用，再判断有没有写入

已确认同日结算接管时，日常流程应在写入前拦住晚到的日内文件：保留文件和来件说明，通知来源方按日终结算核对差异。[日内文件导入](../../../../trades.md#upload-intraday-file)会拒绝已有日终结算流水日期的日内行。若它暴露了真实差异，取得券商确认的完整日终修订文件和替换授权后，才走结算修订；不把日内行改名为结算行，不改日期来绕过拒绝。

若必须在获明确授权的隔离演示产品上验证服务端拒绝，且已确认晚到文件只覆盖已结算的 D 日、同账户和同授权范围，可单独使用以下写入片段。不要在正常维护中为了查看错误而发送，也不要用包含其他日期的文件做拒绝试验。

```python
late_receipt = rqamsh.trades.upload_intraday_file(
    resource=product_id,
    file_path=late_intraday_file_path,
    account=account,
    asset_unit_id=asset_unit_id,
)
```

收到拒绝时，SDK 会抛 `partial_failure`，按 [错误详情](../../../../connection.md#item-errors)保存 `effect_count`、逐行 `line_num` 与 `msg`、`confirmation_id`（如有）。同日全部被拒是本例的预期，不是根据异常名称就能下的结论：核对登记数，再用同一范围重查有效流水，比较结算记录及业务字段是否保持不变。若读到合法行也已登记，不能说整份文件未写入；定位实际涉及的日期和账户，保留前后差异并停止追加操作。需要确认估值未被该请求改变时，历史截面用同日、同口径对照；实时行情可继续变化，不应以盘中净值是否逐值相同来判断是否成功拦截。

## 4. 接管不完整或结果不明时，不继续切换来源

- **结算部分失败：** 任务正常完成且含逐行错误时，有合法行的交易日仍会替换旧有效流水，只登记该日合法行；没有合法行的交易日不替换。被拒行不会保留对应旧成交，也不触发整份文件回滚。留存终态、错误行、凭证及写前快照，查现有哪些 `settlement_upload` 和其他有效流水。修复须基于券商确认的完整正确结算文件，并重新核对覆盖范围；不要补传个别失败行、同时重发日内文件，或用旧日内盘中头寸冒充结算结果。
- **超时、无回执或计算尚未就绪：** 保留请求、文件版本、提交时间、最后状态和任务标识（如有）。有凭证按 ID 查；没有凭证，用 [confirmations.list](../../../../confirmations.md#list) 按操作时间找候选记录，并以账户、日期、文件和有效流水确认本次结果。一次空查询不能证明接管未发生；未确认原操作结果前不重发，也不为看到新净值反复手动重算。按[未就绪与缺输入](../../../../connection.md#unready-inputs)给出已确认项和缺口。

## 5. 托管报告迟到：校准的是估值截面，不是成交来源

结算接管验收和[迟到报告校准](../valuation-report/README.md)要各留一条证据链。先记录结算后 D 日的有效流水、现金和持仓；报告到了，按报告自己的业务日读取同日头寸对比。若报告日早于 D、且获准采用，历史更新会从报告日沿头寸链向后推进，因此要复查 D 日及后续结果，区分报告调整了起点和结算成交本身被修订；若报告日就是 D，也不能将报告对 D 日头寸的调整解释成又一批结算成交。`auto_overwrite=false` 时只保存报告不等于采用，不为一日临时打开影响多日的开关，见[报告采用规则](../../../../reconciliation.md#valuation-report-overwrite-setting)。

## 6. 实际结果：数量不重复，结算费用进入，晚到日内被拒

本轮在独立混合教学产品上先执行[两版日内文件](../intraday-file/README.md)，再接入同日同账户的 RQ 结算文件。日内版本没有提供费用；结算版本为同一买入和卖出各明确提供 5 元佣金。没有新增入金、手工删除旧成交或切换产品自动采用配置。

|实际阶段|有效流水来源 / 条数|股票数量|持仓成本（元）|现金（元）|06-29 净资产（元）|
|---|---|---|---|---|---|
|完整日内文件后|`intraday_upload` / 2|60|520|999,480|1,000,094.40|
|结算文件接管后|`settlement_upload` / 2|60|530|999,470|1,000,084.40|
|晚到日内请求被拒后|`settlement_upload` / 2|60|530|999,470|1,000,084.40|

晚到日内回执的 `effect_count=0`，两行均明确报已有日终结算流水，SDK 抛 `partial_failure`；随后读回有效记录和各历史检查点业务投影未变。不是仅凭异常名称认定未写入。完整错误及明细见[证据](../../evidence.json)的 `lanes.files.receipts` 和 `lanes.files.stages`。

**验证边界。** 本次受控 SDK 执行验证的是历史日期顺序与输入接管，不是实际交易日全天实时观察，也不是自主 Agent 行为证明。迟到估值报告的保存与采用另用[独立产品验证](../valuation-report/README.md)；其他模板、多日文件、夜盘、跨币种、资产单元及部分成功异常未在本次逐项触发。
