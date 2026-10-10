# others 其他数据结构

本页收纳没有更合适归属的跨块结构与取值口径：[资产品种与会计科目](#assetclass)的 `asset_class` 中文字典与会计归属、[交易资产属性](#tradingassetclass)的 `asset_class` 归并分组，以及[现金盈亏调整](#cash-pnl-adjustment)。字段取值枚举不集中在本页：产品配置类见[产品字段](products.md)的「枚举取值」，头寸类见[头寸字段](balances.md)的「枚举取值」，导入来源见[导入凭证字段](confirmations.md)的「枚举取值」，各业务块自己的枚举写在其字段页。

JSON 中传值本身，例如 `"trade"`、`"long"`，不要传标题名称或中文含义。枚举中存在某个值不代表每个写入动作都允许，允许范围写在承载该枚举的页面。字段缺失或 `null` 不等于默认枚举，也不等于 `0`；保留实际结果并按所属字段和操作解释。

<a id="assetclass"></a>

## 资产品种与会计科目

`asset_class` 的中文含义及计算归属如下。“类现金”是本地计算和报告校验使用的固定分类，即下表「是否类现金」列为「是」的品种；它不是通用金融概念，也不能与头寸指标 `cash` 混用。

<a id="deposit-like-classification"></a>

### 类现金、非类现金与 `cash` 指标

类现金在科目调整时按该 `asset_class`、`CNY`、`long` 建或取存款类持仓后调整，且不参与逐仓盈亏累计（其盈亏走下面的现金盈亏调整）。报告输入校验中，非类现金必须提供 `cost_price` 和 `quantity`；类现金不触发这两项“非类现金必填”校验。

`cash` 是单独累计的指标：只累计下表备注标注「计入 `cash` 指标」的 `asset_class` 的 `market_value`。不要以名称或会计分类推断它的成员——`money_market_fund` 计入 `cash` 但属于非类现金；部分应收、应付和负债虽属类现金，却不计入 `cash`。

|`asset_class`|中文分类归属|是否类现金|备注|
|---|---|---|---|
|`stock`|股票|--|—|
|`convertible_bond`|可转债|--|—|
|`bond`|债券|--|—|
|`repo`|正回购|--|会计分类可为现金类负债，但不属于类现金。|
|`repo_accrued_interest`|回购应计利息|是|不计入 `cash` 指标。|
|`reverse_repo`|逆回购|--|会计分类可为现金等价物，但不属于类现金。|
|`reverse_repo_accrued_interest`|逆回购应计利息|是|计入 `cash` 指标。|
|`closed_end_fund`|封闭式基金|--|—|
|`open_end_fund`|开放式基金|--|—|
|`etf_fund`|ETF 基金|--|—|
|`lof_fund`|LOF 基金|--|—|
|`reits`|REITS|--|—|
|`other_fund`|其他基金|--|—|
|`commodity_futures`|商品期货|--|—|
|`commodity_option`|商品期权|--|—|
|`stock_index_futures`|股指期货|--|—|
|`stock_index_option`|股指期权|--|—|
|`interest_rate_futures`|利率期货|--|—|
|`otc_futures`|场外期货|--|—|
|`otc_option`|场外期权|--|—|
|`total_return_swap`|收益互换|--|—|
|`interest_return_swap`|利率互换|--|—|
|`other_derivatives`|其他衍生品|--|—|
|`asset_unit`|资产单元|--|—|
|`current_deposit`|活期存款|是|计入 `cash` 指标。|
|`reservation_deposit`|结算备付金|是|计入 `cash` 指标。|
|`refundable_deposit`|存出保证金|是|计入 `cash` 指标。|
|`securities_settlement_accounts`|证券清算款|是|计入 `cash` 指标。|
|`money_market_fund`|货币基金|--|计入 `cash` 指标，但属于非类现金。|
|`dividend_receivable`|应收股利|是|计入 `cash` 指标。|
|`other_interest_receivable`|其他应收利息|是|计入 `cash` 指标。|
|`subscription_receivable`|应收申购款|是|计入 `cash` 指标。|
|`other_receivable`|其他应收款|是|计入 `cash` 指标。|
|`other_asset`|其他资产|是|计入 `cash` 指标。|
|`cash_debt`|现金类负债|是|不计入 `cash` 指标。|
|`other_interest_payable`|其他应付利息|是|不计入 `cash` 指标。|
|`management_fee_payable`|计提管理费|是|不计入 `cash` 指标。|
|`sales_and_service_fee_payable`|计提销售服务费|是|不计入 `cash` 指标。|
|`custodian_fee_payable`|计提托管费|是|不计入 `cash` 指标。|
|`performance_pay_payable`|计提业绩报酬|是|不计入 `cash` 指标。|
|`operation_fee_payable`|计提运营费|是|不计入 `cash` 指标。|
|`tax_payable`|应付税|是|不计入 `cash` 指标。|
|`other_payable`|其他应付款|是|不计入 `cash` 指标。|
|`other_liability`|其他负债|是|不计入 `cash` 指标。|

<a id="tradingassetclass"></a>

### 交易资产属性（`asset_class` 归并）

交易资产属性把 `asset_class` 归并成 11 个分组，只出现在返回结果的键名与展示字段里，不作为请求参数。同一分组有两种形态：

- 英文值（[asset_weight](../analytics.md#asset_weight)）：`classifiers` 含 `trading_asset_class` 时 `classifier_weight[].weight[].name` 的值，以及 `trading_asset_class_weight_series` 的 `series_names`、`series[].{交易属性名}` 键名；
- 中文名（[组合对比](../analytics.md#组合对比) 的 `group_allocation`、[交易分析](../analytics.md#交易分析) 的 `trading_analysis`）：`data` 的键名与 `asset_category` 字段值。

|交易资产属性（英文值）|中文名|归入的 `asset_class`|备注|
|---|---|---|---|
|`stock`|股票|`stock`|—|
|`convertible`|可转债|`convertible_bond`|—|
|`bond`|债券|`bond`|—|
|`repo`|回购|`repo`、`reverse_repo`|正回购与逆回购合并为一个属性，不区分方向|
|`fund`|基金|`closed_end_fund`、`open_end_fund`、`etf_fund`、`lof_fund`、`reits`、`other_fund`、`money_market_fund`|货币基金归本属性；头寸指标 `cash` 把货币基金计入现金类，两者口径不同|
|`futures`|期货|`commodity_futures`、`stock_index_futures`、`interest_rate_futures`、`otc_futures`|—|
|`option`|期权|`commodity_option`、`stock_index_option`、`otc_option`|—|
|`total_return_swap`|收益互换|`total_return_swap`|—|
|`interest_return_swap`|利率互换|`interest_return_swap`|—|
|`cash`|现金|`current_deposit`、`reservation_deposit`、`refundable_deposit`、`securities_settlement_accounts`|只有这 4 个存款与清算科目，不含货币基金，也不含应收应付与负债科目|
|`other_derivatives`|其他衍生品|—|预留值：当前没有任何 `asset_class` 归入本属性，不会出现在上述返回里|

不在「归入的 `asset_class`」列里的持仓——回购应计利息、应收应付、计提费用与负债科目、资产单元等——按下列口径处理：`group_allocation` 与 `asset_weight` 的 `trading_asset_class_weight_series` 直接跳过，既不进分子也不进键名；`asset_weight` 的 `trading_asset_class` 分类只跳过未归并的持仓（「现金」属性保留）；`trading_analysis` 不按本表过滤，未归并的资产类别照常成组，其 `asset_category` 取固定文案「其他资产」。

<a id="cash-pnl-adjustment"></a>

### 现金盈亏调整

资产单元的日盈亏先汇总非类现金持仓盈亏，再加下面的现金盈亏调整；该部分只识别下表列出的 `transaction_type`，其余现金变动不应据常识补入。

|`transaction_type`|中文含义|实际计算|备注|
|---|---|---|---|
|`interest_income`|利息收入|现金盈亏 `+= settlement_amount`|现金盈亏增加类型。|
|`interest_payment`|利息支出|现金盈亏 `−= settlement_amount`|现金盈亏减少类型。|
|`capital_gain_tax_payment`|转让增值税及附加税|现金盈亏 `−= settlement_amount`|现金盈亏减少类型。|
|`interest_tax_payment`|利息税支出|现金盈亏 `−= settlement_amount`|现金盈亏减少类型。|
|`exercise_deposit_transfer_out`|期权行权资金拨出|现金盈亏 `−= settlement_amount`|现金盈亏减少类型。|

这不同于出入金和托管划转：`cash_in`/`cash_out` 按 `settlement_amount` 计入交易现金变动与 `net_cash_in`；`custodian_transfer_in`/`custodian_transfer_out` 按 `quantity × price` 计入这两个值，不使用 `settlement_amount`。四种类型都不属于现金盈亏调整，不能补入。
