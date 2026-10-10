# trades 字段字典

需要导入成交、核对资金变化或定位一笔流水时，使用[流水查询与写入](../trades.md)中的 `rqamsh.trades.upload/list/get/update`，本页用于选择输入字段和解释返回。

- 本页只列字段与业务含义；写入、必填、省略与覆盖规则见[流水查询与写入](../trades.md)，本页不逐行重复。`只读` 表示服务端生成，不作为写入输入。
- 查询列表 `trades[]` 的记录键可为 `_id`，结构化写入逐项结果使用 `id`；保留实际返回键名，不假设所有端点一致。

交易费用合计可按 `commission + tax + other_fees` 计算，但只有三项都有数值时才可相加；不保证返回 `transaction_cost` 字段。

表中使用 JSON 类型：日期为 `YYYY-MM-DD` 字符串，日期时间为字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值，不代表写入时允许省略或传 `null`；输入必填项和省略行为按对应操作规则执行。查询可能只返回部分字段，缺失或 `null` 均不等于 `0`、`false` 或空数组，不能自行补值参与估值。金额不自动缩放，比例 `0.01` 表示 `1%`；未声明单位的数字不要猜测为万元或百分数。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。

<a id="trade"></a>

## 交易流水记录

流水记录。上传和更新只接受对应操作开放的字段。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`product_id`|归属产品 ID|string|字符串 ID|归属产品 ID|由目标 resource 确定|
|`datetime`|成交时间|string|ISO 日期时间|流水成交时间|—|
|`trading_date`|交易日期|string|YYYY-MM-DD|所属交易日期；夜盘不必等于成交时间的自然日|—|
|`transaction_type`|交易类型|string（枚举）|—|决定一笔流水作用到哪个持仓（品种 × 方向）以及数量、现金与科目的变化；枚举[交易与资金事件类型](#transactiontype)，各类型的头寸影响与适用范围见[交易类型与头寸影响](../trades.md#transaction-type-effect)|—|
|`order_book_id`|[证券/合约代码](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)|string|—|不是自定义合约记录 ID|—|
|`symbol`|[标的/资产单元名称](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-all_instruments)|string|—|标的或资产单元显示名称|—|
|`asset_class`|资产类别|string（枚举）|—|枚举[资产品种与会计科目](others.md#assetclass)|—|
|`source`|来源|string（枚举）|—|流水或估值报告来源；枚举[流水来源](#tradesource)|—|
|`price`|成交价格|number / null|标的报价单位；setl_ccy 为结算币种|成交价格，按标的报价单位|填**不复权**实际成交价；持仓市值按不复权行情计算，混用复权价会与估值口径不一致|
|`quantity`|成交数量|number / null|股/份/合约单位；依品种|持仓/成交数量；股票为股、基金为份、衍生品按合约单位|—|
|`settlement_amount`|结算金额|number / null|金额；主估值人民币，交易/在途依币种|由交易类型决定现金影响；哪些类型要求该字段见[写入校验](../trades.md#transaction-type-write-rules)|—|
|`commission`|佣金|number|金额；主估值人民币，交易/在途依币种|佣金|—|
|`tax`|税费|number|金额；主估值人民币，交易/在途依币种|税费|—|
|`other_fees`|其他交易费用|number|金额；主估值人民币，交易/在途依币种|其他交易费用|—|
|`exchange_rate`|[汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk)|number|小数比例|交易/估值币种换算率|—|
|`currency`|币种|string（枚举）|—|币种；枚举[币种](balances.md#currency)|—|
|`foreign_id`|外部流水 ID|string / null|—|同产品非空值用于 upsert|—|
|`asset_unit_id`|归属资产单元 ID|string / null|字符串 ID|归属资产单元 ID|—|
|`account`|产品内账户名称|string / null|—|产品内账户名称，不是账户 ID|—|
|`estimated_delta_cash`|估计现金变动|number / null|金额；主估值人民币，交易/在途依币种|由流水解析计算|只读|
|`id`|记录 ID|string / null|字符串 ID|服务端记录 ID|只读|
|`inserted_datetime`|流水录入时间|string / null|—|流水录入时间|只读|
|`remarks`|备注|string / null|—|备注|—|
|`signal_id`|模拟交易信号 ID|string / null|字符串 ID|产生流水的模拟交易信号 ID|只读|
|`algo_name`|算法名称|string / null|—|算法名称|—|
|`algo_type`|算法类型|string / null|—|算法类型|—|
|`algo_time_span`|算法执行时段|string / null|—|算法执行时段|—|
|`auto_balance_edited`|自动权益流水已编辑标记|boolean / null|布尔|自动权益流水是否已被编辑|只读|
|`auto_balance_override_id`|自动权益覆盖记录 ID|string / null|字符串 ID|自动权益覆盖记录 ID|只读|

## 枚举取值

<a id="transactiontype"></a>

### 交易与资金事件类型

流水 `transaction_type` 的全部取值。各值影响的持仓品种与方向、数量与现金口径见[交易类型与头寸影响](../trades.md#transaction-type-effect)；各品种允许的组合与必填字段见[写入校验](../trades.md#transaction-type-write-rules)。

|值|含义|
|---|---|
|`buy`|买入|
|`sell`|卖出|
|`buy_open`|多头开仓|
|`sell_open`|空头开仓|
|`sell_close`|多头平仓|
|`buy_close`|空头平仓|
|`subscribe`|申购|
|`redeem`|赎回|
|`transfer_in`|划入|
|`transfer_out`|划出|
|`custodian_transfer_in`|托管划入|
|`custodian_short_transfer_in`|托管空头划入|
|`custodian_transfer_out`|托管划出|
|`custodian_short_transfer_out`|托管空头划出|
|`etf_subscription_transfer_in`|ETF申购划入|
|`etf_redeem_transfer_out`|ETF赎回划出|
|`etf_subscription_transfer_out`|ETF申购划出|
|`etf_redeem_transfer_in`|ETF赎回划入|
|`etf_cash_replacement_transfer_in`|ETF现金替代划入|
|`etf_cash_replacement_transfer_out`|ETF现金替代划出|
|`etf_cash_difference_transfer_in`|ETF现金差额划入|
|`etf_cash_difference_transfer_out`|ETF现金差额划出|
|`withdraw`|活期存款取出|
|`deposit`|活期存款存入|
|`loan`|活期存款借入|
|`loan_repayment`|活期存款借款归还|
|`interest_income`|利息收入|
|`interest_payment`|利息支出|
|`capital_gain_tax_payment`|转让增值税及附加税|
|`interest_tax_payment`|利息税支出|
|`hkt_portfolio_fee_payment`|港股通组合费支出|
|`covered_sell_open`|备兑空头开仓|
|`covered_buy_close`|备兑空头平仓|
|`holder_match`|多头对冲轧平|
|`seller_match`|空头对冲轧平|
|`ipo_subscribed`|新股申购|
|`shares_allotted`|新股中签|
|`subscription_fund_unfrozen`|申购款解冻|
|`shares_listed`|上市流通|
|`buy_on_margin`|融资买入|
|`short_sell`|融券卖出|
|`sell_to_repay`|卖券还款|
|`buy_to_return`|买券还券|
|`return_securities`|直接还券|
|`cash_repayment`|直接还款|
|`refund_securities`|多还退券|
|`interest_payment_on_borrowed`|支付券息|
|`dividend_on_borrowed`|借券红利|
|`bonus_share_on_borrowed`|借券红股|
|`dividend_payment`|红利入账|
|`dividend_reinvestment`|红利再投资|
|`dividend_tax_payment`|红利税支付|
|`bonus_share`|红股|
|`pre_dividend_payment`|分红预处理|
|`pre_bonus_share`|送股预处理|
|`convertible_sell_back`|可转债回售|
|`convertible_redemption`|可转债赎回|
|`cb_to_stock`|转债转股|
|`reverse_repo`|逆回购|
|`repo`|正回购|
|`reverse_repo_repurchase`|逆回购购回|
|`repo_repurchase`|正回购购回|
|`long_deliver`|期货多头交割|
|`short_deliver`|期货空头交割|
|`holder_exercise`|期权多头行权|
|`seller_exercise`|期权空头行权|
|`holder_expire`|期权多头到期|
|`seller_expire`|期权空头到期|
|`exercise_deposit_transfer_out`|期权行权资金拨出|
|`coupon_payment`|债券付息|
|`principal_payment`|债券偿付本金|
|`bond_expire`|债券到期|
|`pre_coupon_payment`|兑息预处理|
|`cash_in`|入金|
|`cash_out`|出金|

<a id="tradesource"></a>

### 流水来源

`source` 的全部取值。系统来源由导入通道或业务过程生成，不作为写入输入；允许写入的取值与文件流程见[上传流水](../trades.md#upload)。

|值|含义|
|---|---|
|`auto_balance`|自动权益|
|`manual`|手工录入|
|`open_api`|OPENAPI|
|`intraday_upload`|当日成交|
|`settlement_upload`|日终结算|
|`netting_derived_shadow`|轧差推导影子流水|
|`paper_trading`|模拟交易生成流水|
|`client_upload`|客户端流水上传|

表内的 `netting_derived_shadow` 由估值表覆盖在覆盖日按报告与系统的持仓差额生成，不参与当日估值计算；生成条件、数量与价格口径见[轧差推导影子流水](../reconciliation.md#netting-derived-shadow-trades)。
