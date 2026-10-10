# 交易流水 trades

交易流水是一笔笔记录已经发生的买卖、收付款等业务的明细。AMS 根据这些记录跟踪投资对象的变化。这里导入的是业务记录，不是向券商提交买卖委托；更改记录会影响后续计算结果。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](rqdata.md#rqdata-calls)。

## 字段说明

记录各项数据及交易类型见[流水字段](fields/trades.md)。导入、更新和删除各自的覆盖规则见对应 API。

<a id="transaction-type-effect"></a>

## 交易类型与头寸影响

`transaction_type` 决定一笔流水作用到哪个持仓以及数量、现金与科目的变化；写入和解释结果都用同一套语义，全部取值见[交易与资金事件类型](fields/trades.md#transactiontype)。引擎按 (`asset_class`, `transaction_type`) 找到该品种的持仓类，解析出受影响的多空方向，再对每个方向各取或新建一条持仓应用；多空是两条独立持仓（键为 `asset_class`、证券代码、方向）。

- 方向解析为空的类型（`ipo_subscribed`、`shares_listed`、`subscription_fund_unfrozen`）不建立持仓，也不产生现金或科目调整。
- 期权的 `custodian_transfer_in`、`custodian_transfer_out` 能通过写入校验，但方向解析为空，引擎跳过，实际不产生任何变化。
- 平仓数量超过持仓时会把数量减为负，引擎不阻止超平。
- 同日多笔流水按 `datetime` 与固定类型优先级排序应用：`buy`、`buy_open`、`sell_open` 为 1，`sell`、`sell_close`、`buy_close` 为 2，`long_deliver`、`short_deliver` 为 3，其余为 0。
- 部分类型不在成交时应用，而在日初权益流程处理：`dividend_payment`、`dividend_on_borrowed`、`bonus_share`、`bonus_share_on_borrowed`、`coupon_payment`。
- `long_deliver`、`short_deliver`（期货到期交割）、`holder_expire`、`seller_expire`（期权到期）、`repo_repurchase`、`reverse_repo_repurchase`（回购到期购回）除手工写入外，还会由系统在结算环节按合约与回购记录自动生成。

后文表格中「成交额」= `price × quantity`（期货、期权再乘[合约乘数](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)；股票、基金再乘 `exchange_rate`；债券、其他衍生品与回购不乘），「税费」= `commission + tax + other_fees` 之和；现金与成本公式中的正负号已含多空方向。

某类型没有出现在某品种家族的表里，代表该组合不通过写入校验（会被拒绝），不是「无效果」。

**股票与基金**（`stock`、`etf_fund`、`lof_fund`、`reits`、`open_end_fund`、`closed_end_fund`、`other_fund`、`money_market_fund`）：

|交易类型|方向|对持仓的影响|现金与科目|
|---|---|---|---|
|`buy`|long|开仓：`quantity += quantity`；均价、含费均价、开仓均价按成交价加权；`cost += 成交额 + 税费`|`−(price × quantity × exchange_rate + 税费)`|
|`sell`|long|平多：`quantity −= quantity`；`cost −= price × quantity × exchange_rate − 税费`|`+(price × quantity × exchange_rate − 税费)`|
|`buy_on_margin`|long|同 `buy`|现金同 `buy` 但不扣税费；另 `cash_debt += price × quantity × exchange_rate + 税费`（融资负债）|
|`sell_to_repay`|long|同 `sell`|现金不按成交额调整；`cash_debt −= price × quantity × exchange_rate`|
|`short_sell`|short|开空：`quantity += quantity`|`+(price × quantity × exchange_rate − 税费)`|
|`buy_to_return`|short|平空：`quantity −= quantity`|`−(price × quantity × exchange_rate + 税费)`|
|`return_securities`|long、short|直接还券：按 `fair_value`（[估值价](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)）计价，`quantity −= quantity`，税费按 0|无|
|`refund_securities`|long、short|多还退券：`quantity += quantity`，税费按 0|无|
|`transfer_in`、`transfer_out`|long|`quantity ± quantity`；开仓成本含费不变、单位成本平移；现金不按成交额调整（仅税费）|无（税费除外）|
|`custodian_transfer_in`、`custodian_transfer_out`|long|按开仓/平仓方向：`quantity ± quantity`，均价与成本按 `price` 重算；现金不按成交额调整（仅税费）；另按 `quantity × price` 计入 `net_cash_in`|口径见[现金盈亏调整](fields/others.md#cash-pnl-adjustment)|
|`custodian_short_transfer_in`|short|开空：`quantity += quantity`|无（税费除外）|
|`interest_payment_on_borrowed`|short|支付券息：含费均价、开仓均价按每单位金额乘方向系数调整（空头为下调）；`cost += settlement_amount`|`−settlement_amount × exchange_rate`|
|`dividend_on_borrowed`|short|借券红利（日初处理）：与借券红利支出在途对冲，数量不变；`acc_dividend_received` 减少。<br>&emsp;港股通空头不产生该在途，除权除息日按交易 ask 汇率直接生成该流水|`−settlement_amount`（人民币）|
|`dividend_payment`|long|现金分红（日初处理）：数量不变；有[应收分红](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)在途时先冲销，`acc_dividend_received` 增加|`+settlement_amount`（人民币；到账与在途的对冲口径见下）|
|`dividend_tax_payment`|long|红利税：含费均价、开仓均价按每单位金额上调；`cost += settlement_amount`|`−settlement_amount × exchange_rate`|
|`dividend_reinvestment`|long|分红再投资：`quantity += quantity`（按 0 价增仓，成本不变）|无|
|`bonus_share`|long|红股（日初处理）：`quantity += quantity`|无|
|`pre_bonus_share`|long|送股预处理：写入 `extras.preprocess_bonus`（红股预处理，不是红股拆分在途），下一交易日生效|无|
|`pre_dividend_payment`|long|分红预处理：写入 `preprocess_dividend`（付款日取下一交易日）；当天不调整持仓|无（到账日口径见下）|
|`bonus_share_on_borrowed`|short|借券红股（日初处理）：`quantity += quantity`|无|
|`subscribe`|long|申购：`quantity += quantity`，成本按成交价加税费|`−(price × quantity × exchange_rate + 税费)`|
|`redeem`|long|赎回：`quantity −= quantity`|`+(price × quantity × exchange_rate − 税费)`|
|`shares_allotted`|long|中签建仓：`quantity += quantity`，价格缺省补[发行价](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)|`−(price × quantity × exchange_rate + 税费)`|
|`ipo_subscribed`、`subscription_fund_unfrozen`、`shares_listed`|—|不作用于持仓|无|
|`etf_subscription_transfer_in`|long|ETF 申购份额划入：`quantity += quantity`|无（税费除外）|
|`etf_redeem_transfer_out`|long|ETF 赎回份额划出：`quantity −= quantity`|无（税费除外）|
|`etf_subscription_transfer_out`|long|成分券因 ETF 申购划出：`quantity −= quantity`|无（税费除外）|
|`etf_redeem_transfer_in`|long|成分券因 ETF 赎回划入：`quantity += quantity`|无（税费除外）|
|`cb_to_stock`|long|转债转股划入：`quantity += quantity`；价格取[当日收盘](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)（缺失用前收），税费按 0|无|

港股通补充：`.XHKG` 结尾且未指定[汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk)（`exchange_rate == 1`）时，开平仓流水不直接调整现金：买入（开仓类）记 `other_payable`、卖出（平仓类）记 `other_receivable`，金额按交易汇率口径（历史计算用结算 ask/bid）加税费计算，港币成交金额另记在结算币种金额中。当日 22:30 前该笔保留在途；22:30 后的当日结算按当日结算 ask/bid 汇率重算金额转入 `current_deposit`，同额冲回上述科目并清空在途记录。指定了汇率则走普通口径。

港股通持仓当日存在用户录入的权益流水（`dividend_payment`、`dividend_on_borrowed`、`bonus_share`、`bonus_share_on_borrowed`）时，当日自动权益处理整支跳过：红利与红股在途既不登记、也不重算或清理，持仓按用户流水调整；尚未处理的在途要等下一个没有用户录入权益流水的交易日才由自动权益处理。在途的科目归属与清理时点见[在途类字段共同口径](fields/balances.md#in-transit-fields)。

适用范围：`buy_on_margin`、`sell_to_repay`、`short_sell`、`buy_to_return`、`dividend_on_borrowed`、`return_securities`、`refund_securities` 对 `open_end_fund`、`closed_end_fund`、`money_market_fund` 会被拒绝；`bonus_share`、`pre_bonus_share`、`bonus_share_on_borrowed`、`cb_to_stock`、`etf_subscription_transfer_out`、`etf_redeem_transfer_in` 仅 `stock`；`subscribe`、`redeem`、`dividend_reinvestment`、`etf_subscription_transfer_in`、`etf_redeem_transfer_out` 适用于上述基金类、不适用于 `stock`。

`money_market_fund` 的盘前权益边界：货基不在盘前自动权益处理品种集合内，上传的 `dividend_payment` 会被持仓的「已在盘前处理」分支直接跳过，`pre_dividend_payment` 只写入 `preprocess_dividend` 而不会被消费——这两类流水在货基上不产生现金或持仓变化。

分红类到账口径：应收分红在途（`dividend_in_transit`）由自动权益在[除息日](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)登记。`dividend_payment` 与 `pre_dividend_payment`（到账日）在 `stock`、`etf_fund`、`lof_fund`、`reits`、`open_end_fund`、`closed_end_fund` 上按 `min(分红在途, 实收金额)` 增加现金，并同步冲减分红在途与应收分红——无在途时该笔金额不产生现金；`other_fund` 不对冲、直接按实收金额入账。`dividend_on_borrowed` 同理按 `min(借券红利支出在途, settlement_amount)` 冲销。到账日没有用户录入流水时，系统按同一口径自动增加现金、冲减在途与应收分红并生成 `dividend_payment` 自动权益流水；同日既有用户流水又有在途到期时，先用流水按上限抵扣在途，剩余在途仍由自动权益在当日入账（港股通持仓当日存在用户录入权益流水时不走自动权益，见下段）。**`dividend_reinvestment` 不在「用户录入权益流水」的跳过集合内**：到账日自己录入一条 `dividend_reinvestment`（数量入账、不动现金）并不会抑制自动权益，同日仍会生成 `dividend_payment` 现金流水，等于同一笔分红既加份额又加现金。要把分红做成再投资，应让自动分红按现金入账后用 `buy` 买回，不要同时录入 `dividend_reinvestment`。在途的科目归属与清理时点见[在途类字段共同口径](fields/balances.md#in-transit-fields)。

**债券与可转债**（`bond`、`convertible_bond`）：

|交易类型|方向|对持仓的影响|现金与科目|
|---|---|---|---|
|`buy`|long|开仓：`quantity += quantity`；均价、含费均价按成交额加权；`cost += quantity × price + 税费`|`−(quantity × price + 税费)`|
|`sell`|long|平仓：`quantity −= quantity`；`cost −= quantity × price − 税费`|`+(quantity × price − 税费)`|
|`custodian_transfer_in`、`custodian_transfer_out`|long|分别同 `buy`、`sell`|同 `buy`、`sell`；另按 `quantity × price` 计入 `net_cash_in`（口径见[现金盈亏调整](fields/others.md#cash-pnl-adjustment)）|
|`transfer_in`、`transfer_out`|long|`quantity ± quantity`；单位成本平移|无（仅可转债）|
|`convertible_sell_back`、`convertible_redemption`|long|`quantity −= quantity`；`cost −= settlement_amount`|`+settlement_amount`（仅可转债）|
|`cb_to_stock`|long|转股划出：`quantity −= quantity`；`cost −= quantity × 公允价`（[当日价](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)，缺失用前收）|无（仅可转债）|
|`coupon_payment`|long|付息（日初处理）：数量不变；均价、含费均价、公允价按[每单位利息](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_cash_flow)下调；`cost −= settlement_amount`|`+settlement_amount`（仅可转债）|
|`pre_coupon_payment`|long|兑息预处理：记入预处理，下一交易日生效|无（仅可转债）|

适用范围：`bond` 只接受 `buy`、`sell`、`custodian_transfer_in`、`custodian_transfer_out`，其余类型仅 `convertible_bond`。`principal_payment`、`bond_expire` 在任何品种都不通过写入校验，由债券结算环节按现金流自动生成（还本与到期清仓）。

**期货**（`commodity_futures`、`stock_index_futures`、`interest_rate_futures`、`otc_futures`）：

|交易类型|方向|对持仓的影响|现金与科目|
|---|---|---|---|
|`buy_open`|long|开多：`quantity += quantity`；均价、盯市均价、含费均价按 `price × quantity × 合约乘数`（[合约基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)）加权；`cost += 成交额 + 税费`|`−税费`（开仓不扣成交金额）|
|`sell_open`|short|开空：同上（空头方向）|`−税费`|
|`custodian_transfer_in`|long|按开仓处理：`quantity += quantity`；另按 `quantity × price` 计入 `net_cash_in`|`−税费`|
|`sell_close`|long|平多：`quantity −= quantity`；`cost += 税费 − price × quantity × 合约乘数`|`+((price − 均价) × quantity × 合约乘数 − 税费)`|
|`buy_close`|short|平空：`quantity −= quantity`；`cost += 税费 + price × quantity × 合约乘数`|`+((均价 − price) × quantity × 合约乘数 − 税费)`|
|`custodian_transfer_out`|long|按平仓处理：`quantity −= quantity`|同平仓；另按 `quantity × price` 计入 `net_cash_in`|
|`long_deliver`|long|多头交割（到期自动生成）：`quantity −= quantity`|同 `sell_close` 口径|
|`short_deliver`|short|空头交割（到期自动生成）：`quantity −= quantity`|同 `buy_close` 口径|
|`transfer_in`、`transfer_out`|long|`quantity ± quantity`；单位成本平移|无|

**期权**（`commodity_option`、`stock_index_option`、`otc_option`）：

|交易类型|方向|对持仓的影响|现金与科目|
|---|---|---|---|
|`buy_open`|long|开多：`quantity += quantity`；均价按 `price × quantity × 合约乘数`（[期权合约属性](https://www.ricequant.com/doc/rqdata/python/options-mod#rqdata-API-options-get-contract_property)）加权；`cost += 成交额 + 税费`|`−(成交额 + 税费)`|
|`sell_open`|short|开空：同上（空头方向）|`+(成交额 − 税费)`|
|`covered_sell_open`|short|备兑开仓：同 `sell_open`|`+(成交额 − 税费)`|
|`sell_close`|long|平多：`quantity −= quantity`；`cost −= 成交额 − 税费`|`+(成交额 − 税费)`|
|`buy_close`|short|平空：`quantity −= quantity`；`cost += 成交额 + 税费`|`−(成交额 + 税费)`|
|`covered_buy_close`|short|备兑平仓：同 `buy_close`|`−(成交额 + 税费)`|
|`holder_exercise`|long|多头行权：`quantity −= quantity`；`cost −= 结算价 × quantity × 合约乘数 − 税费`|`+(结算价 × quantity × 合约乘数 − 税费)`，取不到[结算价](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)按 0|
|`seller_exercise`|short|空头行权：`quantity −= quantity`；`cost += 结算价 × quantity × 合约乘数 + 税费`|`−(结算价 × quantity × 合约乘数 + 税费)`|
|`holder_expire`|long|多头到期（到期自动生成）：同 `holder_exercise`|同 `holder_exercise`|
|`seller_expire`|short|空头到期（到期自动生成）：同 `seller_exercise`|同 `seller_exercise`|
|`holder_match`|long|多头轧平：`quantity −= quantity`；`cost −= fair_value × quantity × 合约乘数`|无|
|`seller_match`|short|空头轧平：`quantity −= quantity`；`cost += fair_value × quantity × 合约乘数`|无|
|`transfer_in`、`transfer_out`|long|`quantity ± quantity`；单位成本平移|无|
|`custodian_transfer_in`、`custodian_transfer_out`|—|通过写入校验但方向为空，引擎跳过|无|

**其他衍生品**（`total_return_swap`、`interest_return_swap`、`other_derivatives`）：

|交易类型|方向|对持仓的影响|现金与科目|
|---|---|---|---|
|`buy_open`|long|开多：`quantity += quantity`；均价按成交额加权；`cost += 成交额 + 税费`|`−(成交额 + 税费)`|
|`sell_open`|short|开空：`quantity += quantity`；`cost −= 成交额 − 税费`（负债）|`+(成交额 − 税费)`|
|`sell_close`|long|平多：`quantity −= quantity`|`+(成交额 − 税费)`|
|`buy_close`|short|平空：`quantity −= quantity`|`−(成交额 + 税费)`|

**回购**（`repo`、`reverse_repo`，价格恒定 100）：

|交易类型|方向|对持仓的影响|现金与科目|
|---|---|---|---|
|`reverse_repo`|long|逆回购开仓（融出资金）：`quantity += quantity`；逐笔记录期限与每日应计利息|`−(100 × quantity + 税费)`；每日利息计入 `reverse_repo_accrued_interest`|
|`reverse_repo_repurchase`|long|购回（到期自动生成）：按逐笔核销 `quantity`；利息结清|`+(100 × 核销数量 + 实收利息)`；应计利息科目减少|
|`repo`|long|正回购开仓（融入资金）：`quantity += quantity`；逐笔记录期限与利息|`+(100 × quantity − 税费)`；每日利息计入 `repo_accrued_interest`（负债）|
|`repo_repurchase`|long|购回（到期自动生成）：按逐笔核销 `quantity`|`−(100 × 核销数量 + 支付利息)`；负债减少|

**现金与借款**（`current_deposit`、`cash_debt`，代码用 `CNY`）：

|交易类型|方向|对持仓的影响|现金与科目|
|---|---|---|---|
|`deposit`、`cash_in`、`interest_income`、`etf_cash_replacement_transfer_in`、`etf_cash_difference_transfer_in`|long|`current_deposit` 余额 `+= settlement_amount`|现金类科目余额增加；`cash_in` 另按 `+settlement_amount` 计入 `net_cash_in`|
|`withdraw`、`cash_out`、`interest_payment`、`interest_tax_payment`、`capital_gain_tax_payment`、`etf_cash_replacement_transfer_out`、`etf_cash_difference_transfer_out`、`exercise_deposit_transfer_out`、`hkt_portfolio_fee_payment`|long|`current_deposit` 余额 `−= settlement_amount`|余额减少；`cash_out` 另按 `−settlement_amount` 计入 `net_cash_in`|
|`loan`|long|`cash_debt` 余额 `+= settlement_amount`|同时 `current_deposit += settlement_amount`（借入资金入现金）|
|`loan_repayment`、`cash_repayment`|long|`cash_debt` 余额 `−= settlement_amount`|同时 `current_deposit −= settlement_amount`|

<a id="transaction-type-write-rules"></a>

### 写入校验与必填字段

导入与修改都先解析再校验；文件与结构化批量上传逐项返回错误，合法项照常写入（部分失败不回滚整批）。

- 组合合法性按解析出的 (`asset_class`, `transaction_type`) 判定；不合法时逐项报错「该资产类型({分类})合约({代码})不支持此交易类型({类型})」。
- `.XHKG` 结尾的港股通股票改用白名单：仅 `buy`、`sell`、`transfer_in`、`transfer_out`、`dividend_payment`、`bonus_share`、`dividend_tax_payment`；`stock` 的其余合法类型在港股通上仍会被拒。
- `custodian_short_transfer_out`、`principal_payment`、`bond_expire` 当前在任何品种上都不通过校验（后两者由结算自动生成）。
- `asset_class` 由服务端按 `order_book_id`（[合约基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)）解析并用于校验与计算：代码为 `CNY` 时按交易类型映射到 `current_deposit` 或 `cash_debt`（`loan`、`loan_repayment`、`cash_repayment`）；无法识别的代码用 `trading_asset_class` 兜底、新股申购兜底为 `stock`。请求里自带的 `asset_class` 不代表计算口径。

必填字段按类型决定，缺一即报错（文案含「数量或价格异常」「结算金额异常」）：

|要求的字段|交易类型|
|---|---|
|数量 + 价格|`buy`、`sell`、`buy_open`、`sell_open`、`sell_close`、`buy_close`、`subscribe`、`redeem`、`covered_sell_open`、`covered_buy_close`、`ipo_subscribed`、`shares_allotted`、`subscription_fund_unfrozen`、`shares_listed`、`buy_on_margin`、`short_sell`、`sell_to_repay`、`buy_to_return`、`reverse_repo`、`repo`、`reverse_repo_repurchase`、`repo_repurchase`、`long_deliver`、`short_deliver`、`etf_redeem_transfer_in`、`etf_redeem_transfer_out`、`etf_subscription_transfer_in`、`etf_subscription_transfer_out`、`custodian_transfer_in`、`custodian_transfer_out`|
|数量|`transfer_in`、`transfer_out`、`return_securities`、`refund_securities`、`dividend_reinvestment`、`bonus_share`、`bonus_share_on_borrowed`、`convertible_sell_back`、`convertible_redemption`、`cb_to_stock`、`holder_expire`、`seller_expire`、`pre_bonus_share`、`holder_exercise`、`seller_exercise`|
|结算金额|`withdraw`、`deposit`、`loan`、`loan_repayment`、`interest_income`、`interest_payment`、`capital_gain_tax_payment`、`interest_tax_payment`、`dividend_payment`、`dividend_tax_payment`、`dividend_on_borrowed`、`convertible_sell_back`、`convertible_redemption`、`cash_in`、`cash_out`、`pre_dividend_payment`、`pre_coupon_payment`、`etf_cash_replacement_transfer_in`、`etf_cash_replacement_transfer_out`、`etf_cash_difference_transfer_in`、`etf_cash_difference_transfer_out`、`coupon_payment`、`principal_payment`、`interest_payment_on_borrowed`、`cash_repayment`、`hkt_portfolio_fee_payment`|

同一类型可同时出现在多行（`convertible_sell_back`、`convertible_redemption` 既要求数量也要求结算金额）；未出现在任何一行的类型不额外校验这三个字段。

写入归一：

- `subscribe`、`redeem` 的 `price` 为空时按 `settlement_amount ÷ quantity` 推导；update 且金额或数量变化时同样重算。
- `shares_allotted` 的 `price` 缺失或为 0 时补该证券[发行价](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)。
- 非 `manual` 来源的回购流水 `price ≥ 0.5` 时按 `/100` 换算（利率小数口径；手工来源由前端换算）。
- 结算金额必填集合内的类型按绝对值写入（方向由交易类型决定，不靠正负号）。
- `estimated_delta_cash` 是服务端计算结果，不作为写入输入。

## 从用户需求到操作

|用户需求|操作顺序与输入|完成条件|
|---|---|---|
|查成交、资金事件或按资产/日期汇总|`list` 明确日期与筛选；单条详情用所属产品及记录 ID 调 `get`|核对 trades、total、分页和聚合口径；外部流水号不是记录 ID|
|导入逐笔结构化数据|核对产品数据源与已配置账户 → 准备非空数组及稳定 foreign_id → `upload(data=...)`|逐项结果无未处理错误，再 list/get 对照日期、数量、价格和费用；部分失败不等于全批回滚|
|导入券商日内或结算文件|确认账户通道、文件模板和覆盖日期，先导出旧数据 → 选择 `upload_intraday_file` 或 `upload_settlement_file`|等待导入完成，检查错误与合法行，再按日期/账户/来源重新查询；不能只核对导入数量|
|纠正或删除已有流水|`list/get` 确认目标 → `update`，或用 `delete` 按日期/筛选（默认）或按 `trade_ids` 指定记录|变更结果与重新查询一致，并检查受影响日期的估值；删除需独立授权|
|交付流水明细文件|`list` 确认范围 → 用相同筛选 `download` 到指定路径|文件已保存，内容日期、账户与筛选范围符合要求；分页参数可能缩小导出范围|
|修正自动生成的红利或红股|`list` 核对除权除息日结果 → `create_auto_balance_override` 提交修正字段 → 重新查询或读头寸报表；撤销用 `delete_auto_balance_override`|`effect_count` 与重新查询结果一致；结果已按修正值更新且未影响普通流水|

导入、修改和删除改变估值输入，不能据写入成功直接宣称净值已更新。完成流水核对后，再检查产品计算状态和受影响日期的头寸报表。








## API 使用约定

Python 与 CLI 完成相同业务操作，连接、任务等待及部分失败处理见[连接说明](connection.md)。替换示例资源、账户、ID 与路径；写入和删除须有授权。JSON 按[流水字段](fields/trades.md)准备，文件使用相应账户通道模板；省略可选筛选会扩大范围，不代表安全默认。
记录标识：`trades.list` 的 `trades[]` 中记录主键可为 `_id`，结构化写入逐项结果的记录 ID 为 `id`。调用 get/update/delete 时使用对应响应里的记录 ID 作为 trade_id/ID 数组，不要把 foreign_id 当作主键，也不要假设 list 记录必有 `id`。

## list
查询产品或产品组流水；聚合查询会等到服务端算完。

Python 签名：`rqamsh.trades.list(resource: str, start_date: str, end_date: str, *, sources: list[str] | None=None, order_book_id: str | None=None, symbol: str | None=None, asset_transaction_types: list[str] | None=None, account_names: list[str] | None=None, asset_unit_ids: list[str] | None=None, key_words: list[str] | None=None, group_by: str | None=None, remarks: str | None=None, is_query_assistant: bool=False, offset: int | None=None, limit: int | None=None, sort_key: str | None=None, start_inserted_date: str | None=None, end_inserted_date: str | None=None, algo_names: list[str] | None=None, algo_types: list[str] | None=None, algo_time_span: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|流水起始日期 YYYY-MM-DD，包含当日。|
|`end_date`|`str`|必填|流水截止日期 YYYY-MM-DD，包含当日。|
|`sources`|`list[str] \| None`|`None`|流水来源枚举数组（取值见[流水来源](fields/trades.md#tradesource)），如 open_api、settlement_upload。|
|`order_book_id`|`str \| None`|`None`|资产代码筛选。|
|`symbol`|`str \| None`|`None`|资产名称筛选。|
|`asset_transaction_types`|`list[str] \| None`|`None`|“交易资产类别-交易类型”数组。|
|`account_names`|`list[str] \| None`|`None`|账户名称数组。|
|`asset_unit_ids`|`list[str] \| None`|`None`|资产单元 ID 筛选数组。|
|`key_words`|`list[str] \| None`|`None`|服务端关键词数组。|
|`group_by`|`str \| None`|`None`|asset 或 trading_date；省略不聚合。|
|`remarks`|`str \| None`|`None`|备注筛选。|
|`is_query_assistant`|`bool`|`False`|是否查询副表，默认 false。|
|`offset`|`int \| None`|`None`|分页偏移。|
|`limit`|`int \| None`|`None`|单页数量。|
|`sort_key`|`str \| None`|`None`|“字段,1”升序或“字段,-1”降序。|
|`start_inserted_date`|`str \| None`|`None`|录入起始日，与 end_inserted_date 同时提供才生效。|
|`end_inserted_date`|`str \| None`|`None`|录入截止日，包含当日。|
|`algo_names`|`list[str] \| None`|`None`|算法名称数组。|
|`algo_types`|`list[str] \| None`|`None`|算法类型数组。|
|`algo_time_span`|`list[str] \| None`|`None`|算法时间段数组，按服务端格式校验。|

返回：服务端原始对象，含 `trades` 与 `total`；聚合查询由客户端等待到聚合结果，聚合失败抛异常，不将 FAIL 当成功。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`trades`|流水列表|array（object 元素）|—|本次查询返回的记录；元素为一条[流水记录](fields/trades.md#trade)，记录主键为 `_id`，不能假设自动改名为 `id`，也不要用 `foreign_id` 代替|恒返回；`offset` / `limit` 只缩小本数组，`group_by` 非空时元素是按聚合键合并后的结果，不是逐笔流水|
|`total`|匹配总条数|integer|条|该查询命中的总条数，不受 `offset` / `limit` 影响|恒返回；`group_by` 非空时为聚合后的条数；对照它和分页参数确认是否取得完整需求范围|

结果检查：对照 total 和分页参数确认是否取得完整需求范围；group_by 返回聚合而非逐笔明细。主表和副表由 is_query_assistant 区分，查询结算替换前流水时应明确需要哪一类数据。

```python
result = rqamsh.trades.list(resource='授权测试产品', start_date='2026-01-01', end_date='2026-01-31')
```

```console
rqamsh trades list --resource "授权测试产品" --start-date "2026-01-01" --end-date "2026-01-31"
```

## get
读取所属产品的一条流水；不支持产品组。

Python 签名：`rqamsh.trades.get(resource: str, trade_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|归属产品唯一 ID 或名称。|
|`trade_id`|`str`|必填|服务端流水记录 ID，不是 foreign_id。|

返回：服务端原样返回一条流水记录，根对象就是该记录。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|流水记录|object|—|一条[流水记录](fields/trades.md#trade)，键名与该字段表一致，其中记录 ID 键为 `id`|恒返回；`trades.list` 的 `trades[]` 主键是 `_id`，不能把两个键名互相套用|

结果检查：确认该记录属于目标产品，核对 account、日期、来源及金额字段。用响应主键进行修改或删除，不用 foreign_id 代替；未找到时先核对产品和 ID，不以同名标的推断记录。

```python
result = rqamsh.trades.get(resource='授权测试产品', trade_id='0123456789abcdef01234567')
```

```console
rqamsh trades get --resource "授权测试产品" --trade-id "0123456789abcdef01234567"
```

## upload
导入结构化流水数组；文件导入见 [upload_intraday_file](#upload-intraday-file) 与 [upload_settlement_file](#upload-settlement-file)。
[完整流水字段和枚举](fields/trades.md)。结构化输入是非空 JSON 数组，不需外层 trades 包装。例：

```json
[{"datetime":"2026-01-05 10:00:00","transaction_type":"buy","order_book_id":"000001.XSHE","asset_class":"stock","price":10.0,"quantity":100,"commission":5.0,"account":"授权测试账户","foreign_id":"demo-unique-001"}]
```

price/quantity/settlement_amount 的必要性依交易类型（见[写入校验](trades.md#transaction-type-write-rules)），不能把示例用于所有品种。**`price` 填实际成交价（不复权）**：持仓市值与净值按不复权行情计算，若用前复权/后复权价导入，买入金额与估值价格就不同口径，会凭空造出收益或亏损。输入缺 source 时补 open_api；已有 source 不覆盖。允许 manual/open_api/paper_trading/client_upload（见[流水来源](fields/trades.md#tradesource)）；日内和结算来源必须走文件流程。trade 和混合数据源可写，纯估值表产品拒绝（服务端文案：该产品不能导入交易流水）。上传前使用 products.get 确认账户已配置，每项 account 应与产品账户对应。

结构化上传不按日期清空，也不是文件覆盖：按同产品非空 foreign_id 更新或新增，空/空白外部 ID 不保证重复导入幂等；历史修改从旧/新日期最早日起重算。

Python 签名：`rqamsh.trades.upload(resource: str, data: list[dict[str, Any]], *, prefer_fill_fund_exchange_suffix: bool=True)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|目标产品唯一 ID 或名称，不支持产品组。|
|`data`|`list[dict[str, Any]]`|必填|非空流水对象数组；缺省 source 补 open_api，已有 source 保留。foreign_id 按产品做 upsert；整组提交，不自动拆批。|
|`prefer_fill_fund_exchange_suffix`|`bool`|`True`|默认 true 自动补[基金场内后缀](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-instruments)；false 不使用该兼容补全方式。|

返回：原始逐项 upsert 结果，根是数组，按提交顺序与输入项一一对应（长度等于提交项数）；任意部分失败抛异常并保留完整结果。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|单项写入结果|object|—|一项输入的处理结果，逐项结果原样透传；失败判定只看错误字段：`err`、`err_msg`、`err_msgs`、`failed`、`error_messages` 任一非空，或 `status` 为 `FAIL`/`failed`|恒返回；任一项被判为失败即抛部分失败异常并保留完整结果，见[逐项失败容器](connection.md#item-errors)|
|`[].err`|该项未写入原因|string|—|该项为何未写入：来源不在允许范围、解析或校验失败、该交易日已有日终结算流水|由数据决定；只是服务端可能返回的失败键之一，实际出现的键名随路由而定，非空即抛部分失败异常|
|`[].id`|该项记录 ID|string|—|该项落库后的流水记录 ID|由数据决定；`trades.list` 的记录主键是 `_id`，不是本键；结构化流水写入结果的记录 ID 为 `id`（见[输入、输出与文件](connection.md#输入输出与文件)）|

操作检查：逐项检查错误；出现部分失败或超时后先 list/get 查明已落入的数据，再决定重试内容；缺稳定 foreign_id 的整批重试可能重复。

```python
import json
from pathlib import Path

result = rqamsh.trades.upload(resource='授权测试产品', data=json.loads(Path("trades.json").read_text(encoding="utf-8")))
```

```console
rqamsh trades upload --resource "授权测试产品" --input @trades.json
```

<a id="upload-intraday-file"></a>

## upload_intraday_file
上传一个日内流水文件；按成功解析日期、产品、账户及可选资产单元，删除当前有效 intraday_upload/open_api 后插入合法行，同日已有结算流水时拒绝该日日内行。

省略 asset_unit_id **不保证仅影响无资产单元的记录**；需要限定单元时应显式提供。请先限定账户、核对目标日期并导出留存。文件模板取决于券商通道，不能把任意 CSV 列名视为受支持模板。报价币种、夜盘日期、基金后缀按相应文件规则解析；prefer_fill_fund_exchange_suffix=True 启用基金场内后缀自动补全，False 不使用该兼容补全方式；结算文件同理。上传后核对解析后的代码、币种和交易日。

Python 签名：`rqamsh.trades.upload_intraday_file(resource: str, file_path: str, account: str, *, asset_unit_id: str | None=None, prefer_fill_fund_exchange_suffix: bool=True)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|目标产品唯一 ID 或名称。|
|`file_path`|`str`|必填|本地日内流水文件路径。|
|`account`|`str`|必填|目标账户名称，必须显式提供。|
|`asset_unit_id`|`str \| None`|`None`|可选资产单元 ID。|
|`prefer_fill_fund_exchange_suffix`|`bool`|`True`|默认 true 自动补[基金场内后缀](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-instruments)；false 不使用该兼容补全方式。|

返回：服务端原始文件导入结果；任意部分失败抛异常并保留完整结果。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际写入条数|integer|条|本次插入的合法日内流水条数|恒返回；文件没有合法行时为 `0`，不代表文件已被整体接受；见[写入结果](connection.md#write-result)|
|`err_msg`|逐行错误|array（object 元素）|—|每个解析失败或被拒的行一项，元素含 `line_num`(integer，文件行号)与 `msg`(string，原因，如「不能在已上传过日终结算流水的日期上传日内流水」)|恒返回；无错误时为空数组，非空即抛部分失败异常，见[逐项失败容器](connection.md#item-errors)|
|`confirmation_id`|导入凭证 ID|string / null|字符串 ID|本次导入生成的凭证记录 ID|由数据决定；没有任何合法行与错误行时为 `null`|

操作检查：合法项可写入而其他项失败，异常中保留逐项结果，重试前先核对已成功项；导入后按日期、账户与来源重新查询当前有效流水，需要留存的被覆盖记录另查副表。

```python
result = rqamsh.trades.upload_intraday_file(resource="授权测试产品", file_path="intraday.xlsx", account="授权测试账户")
```

```console
rqamsh trades upload-intraday-file --resource "授权测试产品" --file-path intraday.xlsx --account "授权测试账户"
```

## update
修改指定产品流水，服务端校验字段并触发必要重算。

trade_id 必须是记录主键而非 foreign_id；普通 update 不能改变交易类型和 source，仍受封账及字段校验约束。

Python 签名：`rqamsh.trades.update(resource: str, trade_id: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|归属产品唯一 ID 或名称。|
|`trade_id`|`str`|必填|流水记录 ID。|
|`data`|`dict[str, Any]`|必填|修改字段 JSON；支持数量、价格、费用、时间、账户、标的、备注、 asset_unit_id 及算法字段等，不能改变交易类型或来源。|

返回：服务端原始修改结果，含 `effect_count` 与 `updated`。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际修改条数|integer|条|本次实际修改的流水条数|恒返回；提交内容与现值完全一致时为 `0`，不代表记录不存在；见[写入结果](connection.md#write-result)|
|`updated`|更新后的流水记录|object|—|服务端校验并落库的完整记录，键名同[流水记录](fields/trades.md#trade)|恒返回；按落库文档形态给出，记录 ID 键为 `_id`|

操作检查：先 get 保存原记录，确认修改字段不含交易类型和 source。返回后核对 effect_count 与 updated，并读取变更后的记录；交易日改变时，旧日和新日的估值都需核对。

```python
import json
from pathlib import Path

result = rqamsh.trades.update(resource='授权测试产品', trade_id='0123456789abcdef01234567', data=json.loads(Path("update.json").read_text(encoding="utf-8")))
```

```console
rqamsh trades update --resource "授权测试产品" --trade-id "0123456789abcdef01234567" --input @update.json
```

## delete
删除产品流水：默认按日期与筛选条件删除，也可用 trade_ids 指定记录；两种方式互斥。

按日期方式即使 HTTP 方法为 GET，也会执行不可撤销的删除；省略全部筛选会删除整个允许日期范围，受封账限制。按 ID 方式同步返回，封账范围同样由服务端限制。

Python 签名：`rqamsh.trades.delete(resource: str, *, trade_ids: list[str] | None=None, start_date: str | None=None, end_date: str | None=None, sources: list[str] | None=None, order_book_id: str | None=None, symbol: str | None=None, asset_transaction_types: list[str] | None=None, account_names: list[str] | None=None, asset_unit_ids: list[str] | None=None, key_words: list[str] | None=None, remarks: str | None=None, is_query_assistant: bool=False, algo_names: list[str] | None=None, algo_types: list[str] | None=None, algo_time_span: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称，不支持产品组。|
|`trade_ids`|`list[str] \| None`|`None`|可选非空流水记录 ID 数组（不是 foreign_id）；提供时按 ID 同步批量删除，不能再给日期或筛选参数。|
|`start_date`|`str \| None`|`None`|起始日 YYYY-MM-DD；省略从产品交易起始日开始，受封账限制。|
|`end_date`|`str \| None`|`None`|截止日 YYYY-MM-DD；省略至今日，包含当日。|
|`sources`|`list[str] \| None`|`None`|来源枚举数组；省略不限来源。|
|`order_book_id`|`str \| None`|`None`|资产代码筛选。|
|`symbol`|`str \| None`|`None`|资产名称筛选。|
|`asset_transaction_types`|`list[str] \| None`|`None`|“交易资产类别-交易类型”数组。|
|`account_names`|`list[str] \| None`|`None`|账户名称数组。|
|`asset_unit_ids`|`list[str] \| None`|`None`|资产单元 ID 数组。|
|`key_words`|`list[str] \| None`|`None`|关键词数组。|
|`remarks`|`str \| None`|`None`|备注筛选。|
|`is_query_assistant`|`bool`|`False`|是否删除副表流水，默认 false。|
|`algo_names`|`list[str] \| None`|`None`|算法名称数组。|
|`algo_types`|`list[str] \| None`|`None`|算法类型数组。|
|`algo_time_span`|`list[str] \| None`|`None`|算法时间段数组。|

返回：按 ID 方式同步返回 `effect_count`；按日期方式原样透传服务端任务终态 JSON，删除数量字段名与位置以实际响应为准（不保证是 `data.deleted_count`）。两种方式都可能触发重算。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|按 `trade_ids` 实际删除的流水条数|由参数选择（传入 `trade_ids` 时）；ID 不存在、不属于本产品或落在封账范围内都为 `0`，`0` 不代表删除范围已清空；见[写入结果](connection.md#write-result)|
|`status`|任务状态|string（枚举）|—|按日期删除的任务终态，`SUCCESS` 表示删除任务完成|由参数选择（按日期与筛选条件时）；失败终态由客户端抛 `task_failed`，不会当作成功返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例|由参数选择（按日期时）；成功终态为 `1`|
|`data`|任务结果|object / array / null|—|按日期删除的任务产物，结构随服务端路由，不自动拆包|由参数选择（按日期时）；`0` 表示没有命中可删除的流水，范围被封账限制收窄后也可能为 `0`；删除数量字段以实际响应为准|

操作检查：按日期删除前先用 list 以相同条件预览并留存，确认 is_query_assistant 的主/副表选择；按 ID 删除前核对每个 ID 的产品归属和删除授权，保留所需明细。返回后重新查询同一范围或记录；封账限制、零影响数量和任务超时都不代表删除范围已清空，受影响日期的估值需另行核对。

按日期与筛选条件删除（默认方式，未给出的筛选不参与限制）：

```python
result = rqamsh.trades.delete(resource='授权测试产品', start_date='2026-01-01', end_date='2026-01-31')
```

```console
rqamsh trades delete --resource "授权测试产品" --start-date "2026-01-01" --end-date "2026-01-31"
```

按记录 ID 删除（与日期/筛选参数互斥，二者不要在同一命令里混用）：

```python
result = rqamsh.trades.delete(resource='授权测试产品', trade_ids=['0123456789abcdef01234567'])
```

```console
rqamsh trades delete --resource "授权测试产品" --trade-ids '["0123456789abcdef01234567"]'
```

<a id="upload-settlement-file"></a>

## upload_settlement_file
上传一个日终结算流水文件并等待导入任务完成。

按合法行日期、产品、账户和可选资产单元，将当前日内/open_api 记录转入副表，删除当前 settlement_upload/intraday_upload/open_api 后插入结算行；还可能创建解析出的自定义标的。省略 asset_unit_id 不保证仅影响无单元记录，先按范围导出留存。结果可能含 SUCCESS/data；合法行可成功并附错误，不保证全文件回滚。文件模板及代码后缀处理同 [upload_intraday_file](#upload-intraday-file)，上传后核对实际日期、币种和代码。

Python 签名：`rqamsh.trades.upload_settlement_file(resource: str, file_path: str, account: str, *, asset_unit_id: str | None=None, prefer_fill_fund_exchange_suffix: bool=True)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|目标产品唯一 ID 或名称。|
|`file_path`|`str`|必填|本地结算流水文件路径。|
|`account`|`str`|必填|目标账户名称，必须显式提供。|
|`asset_unit_id`|`str \| None`|`None`|可选资产单元 ID。|
|`prefer_fill_fund_exchange_suffix`|`bool`|`True`|默认 true 自动补[基金场内后缀](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-instruments)；false 不使用该兼容补全方式。|

返回：服务端任务终态 JSON；部分失败抛异常。结算导入有覆盖旧流水副作用。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`status`|任务状态|string（枚举）|—|结算文件导入任务的终态，`SUCCESS` 表示任务完成|恒返回；失败终态由客户端抛 `task_failed`，不会当作成功返回；见[任务终态 JSON](connection.md#task-result)|
|`progress`|任务进度|number|0 到 1|服务端上报的进度比例|恒返回；成功终态为 `1`|
|`data`|导入结果|object|—|导入摘要，含 `effect_count`(integer，条)、`err_msg`(array，元素含 `line_num`(integer，文件行号)与 `msg`(string))、`confirmation_id`(string 或空)|恒返回；不自动拆包；`err_msg` 非空即抛部分失败异常，见[逐项失败容器](connection.md#item-errors)|

操作检查：上传前保存被替换日期的原流水，核对账户和可选资产单元。任务终态仍需检查错误；合法行可能已写入且旧日内数据已转入副表。分别查询当前有效流水和需要留存的副表记录，再检查估值；失败不保证回滚。

```python
result = rqamsh.trades.upload_settlement_file(resource='授权测试产品', file_path='settlement.xlsx', account='授权测试账户')
```

```console
rqamsh trades upload-settlement-file --resource "授权测试产品" --file-path "settlement.xlsx" --account "授权测试账户"
```

## download
生成并下载产品或产品组流水 Excel，等待任务后写入指定文件。

Python 签名：`rqamsh.trades.download(resource: str, start_date: str, end_date: str, output: str, *, sources: list[str] | None=None, order_book_id: str | None=None, symbol: str | None=None, asset_transaction_types: list[str] | None=None, account_names: list[str] | None=None, asset_unit_ids: list[str] | None=None, key_words: list[str] | None=None, group_by: str | None=None, remarks: str | None=None, is_query_assistant: bool=False, offset: int | None=None, limit: int | None=None, sort_key: str | None=None, start_inserted_date: str | None=None, end_inserted_date: str | None=None, algo_names: list[str] | None=None, algo_types: list[str] | None=None, algo_time_span: list[str] | None=None)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|流水起始日 YYYY-MM-DD，包含当日。|
|`end_date`|`str`|必填|流水截止日 YYYY-MM-DD，包含当日。|
|`output`|`str`|必填|必填本地输出文件路径，不使用服务端文件名推导路径。|
|`sources`|`list[str] \| None`|`None`|来源枚举数组。|
|`order_book_id`|`str \| None`|`None`|资产代码筛选。|
|`symbol`|`str \| None`|`None`|资产名称筛选。|
|`asset_transaction_types`|`list[str] \| None`|`None`|“交易资产类别-交易类型”数组。|
|`account_names`|`list[str] \| None`|`None`|账户名称数组。|
|`asset_unit_ids`|`list[str] \| None`|`None`|资产单元 ID 数组。|
|`key_words`|`list[str] \| None`|`None`|关键词数组。|
|`group_by`|`str \| None`|`None`|asset 或 trading_date；省略不聚合。|
|`remarks`|`str \| None`|`None`|备注筛选。|
|`is_query_assistant`|`bool`|`False`|是否查询副表，默认 false。|
|`offset`|`int \| None`|`None`|导出起始偏移；完整导出时不要沿用列表分页偏移，下载后核对实际范围。|
|`limit`|`int \| None`|`None`|导出数量限制；完整导出时不要沿用单页数量，下载后核对记录覆盖。|
|`sort_key`|`str \| None`|`None`|“字段,1”升序或“字段,-1”降序。|
|`start_inserted_date`|`str \| None`|`None`|录入起始日，须与录入截止日同时提供。|
|`end_inserted_date`|`str \| None`|`None`|录入截止日，包含当日。|
|`algo_names`|`list[str] \| None`|`None`|算法名称数组。|
|`algo_types`|`list[str] \| None`|`None`|算法类型数组。|
|`algo_time_span`|`list[str] \| None`|`None`|算法时间段数组。|

返回：客户端下载元数据；服务端成功时返回二进制文件而非 JSON，客户端把它写入 `output` 而不输出到 stdout。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；与落盘文件核对，`0` 不代表内容完整|

交付检查：确认 output 是预期的新文件路径，等待任务与下载完成后检查下载元数据及文件内容。核对日期、账户、来源、聚合和分页条件与用户需求一致；文件成功保存不证明筛选范围完整。

```python
result = rqamsh.trades.download(resource='授权测试产品', start_date='2026-01-01', end_date='2026-01-31', output='export.xlsx')
```

```console
rqamsh trades download --resource "授权测试产品" --start-date "2026-01-01" --end-date "2026-01-31" --output "export.xlsx"
```

## create_auto_balance_override

新增或覆盖一条自动权益编辑。自动权益编辑不是流水：它只修正服务端按除权除息自动生成的红利或红股结果，不影响手工录入的普通流水。

只支持四类交易，字段白名单和除权除息日的推导方式如下：

|`transaction_type`|可更新字段|除权除息日|
|---|---|---|
|`dividend_payment`|`settlement_amount`、`remarks`|按业务日（港股为 T+2 到账日）从[行情红利数据](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)反查除权除息日；查不到该到账日的红利数据时报错|
|`dividend_on_borrowed`|`settlement_amount`、`remarks`|等于 `trading_date`（借券红利流水到账日即除权除息日）|
|`bonus_share`|`quantity`、`remarks`|等于 `trading_date`（红股到账日即除权除息日）|
|`bonus_share_on_borrowed`|`quantity`、`remarks`|等于 `trading_date`|

`update` 至少一个字段；出现白名单外的字段、或其他交易类型都会被拒绝。除权除息日不得晚于产品到期日，超出范围时服务端拒绝写入。请求体不接受白名单外的顶层键。

Python 签名：`rqamsh.trades.create_auto_balance_override(resource: str, data: dict[str, Any])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`data`|`dict[str, Any]`|必填|自动权益编辑 JSON；必含 `asset_class`、`transaction_type`、`trading_date`、`order_book_id`、`update`，可选 `asset_unit_id`。|

返回：服务端原始 `effect_count`；写入会按除权除息日提交重算，若服务端返回任务则客户端等待到终态。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际写入条数|integer|条|本次新增或覆盖的自动权益编辑条数，只可能是 `1`（有新增或修改）或 `0`（内容与已有完全一致）|恒返回；`0` 不表示写入失败；见[写入结果](connection.md#write-result)|

操作检查：先用 `list` 核对目标证券在该除权除息日的自动权益结果，再提交修正；完成后重新查询或读取受影响日期的头寸报表确认结果，`effect_count` 不等于 1 时不要假定已生效。修正生效后，该笔自动权益流水在 `trades.list` 中会带 `auto_balance_edited` 为真与 `auto_balance_override_id`——删除这条修正时用的就是后者（见 [delete_auto_balance_override](#delete_auto_balance_override)）。

写入或删除都会先删除受影响的自动权益流水再重算，重算落地前按该日期与标的查询可能短暂为空，要读取 `auto_balance_override_id` 时应先确认重算已落地。

自动权益流水由计算引擎在除权除息日盘前、按该日盘前持仓（即除权日前一交易日的收盘持仓）生成：除权除息日当天才买入的产品不会产生这笔 `dividend_payment`。因此要修正某笔自动权益，必须在该除权除息日之前已持有标的。

判断「是否有自动权益流水」只看标的在该除权除息日是否真实发生分红/送转、且产品在该日盘前持有（除权除息日当天买入不算），与产品配置的「自动权益」开关无关。

```python
result = rqamsh.trades.create_auto_balance_override(
    resource='授权测试产品',
    data={
        'asset_class': 'stock',
        'transaction_type': 'dividend_payment',
        'trading_date': '2026-07-08',
        'order_book_id': '600000.XSHG',
        'update': {'settlement_amount': 1200.0, 'remarks': '按券商对账单修正'},
    },
)
```

```console
rqamsh trades create-auto-balance-override --resource "授权测试产品" --input @auto_balance_override.json
```

## delete_auto_balance_override

按记录 ID 删除一条自动权益编辑，并按该记录的除权除息日提交重算。记录 ID 不是流水 ID，也不能从 `create_auto_balance_override` 的返回取得（它只回 `effect_count`），Harness 与直连接口都没有独立的自动权益编辑查询操作；可用的取值来源是 `trades.list`：被编辑过的自动权益流水会带 `auto_balance_edited` 为真与 `auto_balance_override_id`（见[交易流水字段](fields/trades.md#trade)），用该值删除。自动权益流水只在标的真实发生分红/送转且产品当日持有该标的时生成，因此编辑记录可以先于任何自动权益流水存在（写入不做这类校验），但那时它的 ID 无法经 API 取得，只能使用外部渠道已知且属于该产品的记录 ID。记录不存在时返回 `effect_count=0`，不会提交重算。

删除只影响这一条修正，不删除自动生成的权益流水本身。

注意：写入与删除都会重写受影响的自动权益流水记录，其流水 ID 会变化，回归时要按日期与标的重新查询，不要复用编辑前的流水 ID。

Python 签名：`rqamsh.trades.delete_auto_balance_override(resource: str, override_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称。|
|`override_id`|`str`|必填|自动权益编辑记录 ID。|

返回：服务端原始 `effect_count`；提交重算时若服务端返回任务则客户端等待到终态。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次删除的自动权益编辑条数，只可能是 `1` 或 `0`|恒返回；记录不存在时为 `0` 且不提交重算；见[写入结果](connection.md#write-result)|

操作检查：`effect_count` 为 0 时不能宣称已删除，应先确认该 ID 是否属于本产品的自动权益编辑；删除后重新读取受影响日期的头寸报表，确认权益结果已回到自动计算结果。

```python
result = rqamsh.trades.delete_auto_balance_override(resource='授权测试产品', override_id='68a1b2c3d4e5f6a7b8c9d0e1')
```

```console
rqamsh trades delete-auto-balance-override --resource "授权测试产品" --override-id "68a1b2c3d4e5f6a7b8c9d0e1"
```
