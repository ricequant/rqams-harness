# 头寸字段字典

头寸报表、持仓及分类份额合并在下方一张表；顶层同名字段只列一次。唯一单日入口为 [`balances.get`](../balances.md)：`balances.get(resource_or_resources, *, date=None, fields=None, classifier=None, show_futures_sterilisation=True, benchmark_id=None, drilldown=True, include_component_weight_view=False)`；[`series`](../balances.md) 保持独立的时序查询语义。

- `date=None` 或等于北京时间当天时查询实时结果；未来日期被拒绝。其他允许日期查询历史结果。
- `fields=None` 返回含 `positions` 的完整报表；非空 `fields` 只投影顶层返回字段，不能传 `positions.quantity` 等嵌套字段路径。
- `classifier=None` 时持仓平铺；非空分类时沿 `children[]` 找实际持仓叶子，不把分类小计与叶子重复相加。`benchmark_id` 始终传纯 ID。
- 历史结果不支持 `drilldown=False` 或成员权重视图；实时结果中，`show_futures_sterilisation=False` 与 `drilldown=False`、成员视图或自定义基准的组合若底层不支持即报错。成员权重视图仅适用于产品组，返回成员 ID→成员对象，不摊平成单一报表。

字段路径从结果对象开始：`positions[].extras.…` 表示某条持仓内的扩展字段；`share_values.{份额}.…` 表示以分类份额名称为键的估值。不同层级的 `quantity`、`amount`、`cost` 不是同一个值。

<a id="formula-notation"></a>

## 公式阅读约定

- `P`：当前报表实际参与计算的完整持仓集合。
- `x`：集合中的一仓；逐仓公式中未加前缀的字段取这一仓的同名值，不取产品顶层同名字段。
- `p`：本表 `positions[].fair_value` 字段中的估值价格。
- `q`：本表 `positions[].quantity` 字段中的数量。
- `s`：多空方向因子，`long` 为 `+1`，`short` 为 `−1`。
- `m`：当日合约乘数，具体来源在相应字段中说明。
- `r`：仅用于回购本金及利息方向；`reverse_repo` 为 `+1`，`repo` 为 `−1`，不按 `direction` 推断。

产品级变量每个对应本表一个字段：

- `Equity[当日]`：`total_equity`，当日净资产。
- `PnL[当日]`：`daily_pnl`，当日盈亏金额。
- `Units[当日]`：`units`，当日产品份额。
- `NAV[当日]`：`unit_net_value`，当日单位净值。
- `AccNAV[当日]`：`acc_unit_net_value`，当日累计单位净值。
- `AdjNAV[当日]`：`adjusted_net_value`，当日复权净值。
- `Return[当日]`：`daily_returns`，当日收益率；不等于上面的回购方向因子 `r`。
- `CustodianFlow[当日]`：[估值表覆盖](../reconciliation.md#valuation-report-overwrite)时的托管净现金调整；不是返回字段，逐笔组成见本表 `daily_pnl` 字段。

产品级变量中的日期方括号表示取值时点：`AccNAV[上一估值日]` 是上一估值状态的累计净值，不是“当日累计净值减 1”。
`AccNAV[当日] - 1` 才表示减去基点 1；例如当日累计净值为 1.08，结果为 0.08。
“昨日”和“上一估值日”均指当前分支采用的上一估值状态，不保证是上一自然日或上一交易日；实时昨收口径另行注明。
分类份额用 `[分类i]` 标识类别，不是日期；定义见本表 `share_values` 字段。
所有计算分支与数据来源保留在字段中，较长的资产枚举移至[文末清单](#calculation-asset-classes)。

查询字段只读；修正估值应修改[流水](../trades.md)、[报告](../valuation_reports.md)或[产品配置](../products.md)，等待计算完成。覆盖的业务定义与对账流程见[对账](../reconciliation.md#valuation-report-overwrite)，适用设置见[估值表覆盖设置](../reconciliation.md#valuation-report-overwrite-setting)。复算需要同一日期/版本的历史状态、人工公允价、权益、汇率及日历；接口名称如 [RQData get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi) 只是原始来源说明，不是 Harness 新增方法。

JSON 日期为 YYYY-MM-DD 字符串，枚举传英文值；金额不自动缩放，通常主估值为人民币，原币及在途金额在字段行注明。比例 0.01 表示 1%。缺字段、null、0、false、空数组不同；缺历史或外部数据时应指出缺口，不能补零、假设初仓为零或用统一“输入端口径”跳过公式。与头寸无关的指标外部数据另见[指标特殊来源](../analytics/metrics.md#external-inputs)；[资产品种与会计科目](others.md#assetclass)和[现金盈亏类型](others.md#cash-pnl-adjustment)可交叉查阅。

### RQData 官方调用来源

本页及[指标公式](../analytics/metrics.md#indicators-returns)引用的 rqdata 调用、对应官方页面与各自的使用位置，集中列在 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。字段行中的调用名仍直接链接到对应官方页面，本页不再重复清单；新增或调整调用时同步那一处。

## 在途类字段共同口径

<a id="in-transit-fields"></a>

在途类字段都挂在 `positions[].extras` 下，表示已发生但未到账或未结算的业务，由服务端按日维护、查询只读。判断它们对报表的影响按下列共同口径：

|在途字段|报表归属|对净资产的影响|
|---|---|---|
|`positions[].extras.dividend_in_transit`、`positions[].extras.hkt_dividend_in_transit`|应收股利（`dividend_receivable`）|按记录中的人民币应计金额计入总资产；该科目已在持仓市值清单中排除，不要在 `market_value` 上再相加一次。|
|`positions[].extras.borrowed_dividend_in_transit`|无独立科目|只在除权除息日当天冲销，不形成独立的应收或应付科目。|
|`positions[].extras.split_in_transit`|无科目|只表示尚未入账的新增数量，不改资产与负债金额。|
|`positions[].extras.hkt_payable_in_transit`|其他应付款（`other_payable`）|按记录中的人民币金额计入总负债。|
|`positions[].extras.hkt_receivable_in_transit`|其他应收款（`other_receivable`）|按记录中的人民币金额计入总资产。|

- 数组只保留当前业务日期尚未到期的记录：到账或结算日期（`arrival_date`）盘前处理完成后，该条即从数组移除。「在途为空数组」表示当日没有未结事项，不代表该权益从未登记。
- 多条在途同时存在时按登记顺序冲减：先登记的先用完再动下一条；部分冲减把记录金额改小而不是删除。
- 到账由服务端生成对应自动权益流水并同步调整现金与数量：现金分红生成 `dividend_payment`，红股到账生成 `bonus_share`，空头对应 `dividend_on_borrowed`、`bonus_share_on_borrowed`。港股通红利的换汇与红利税、港股通当日结算款在途的重算，见本表 `positions[].extras.hkt_dividend_in_transit`、`positions[].extras.hkt_payable_in_transit` 字段行。
- 多空分支不同：A 股空头在除权除息日登记 `positions[].extras.borrowed_dividend_in_transit` 并在同日冲销；港股通空头不登记在途，除权除息日按交易 ask 汇率直接生成 `dividend_on_borrowed` 自动流水。
- 港股通持仓当日存在用户录入的权益流水时，当日整支自动权益处理被跳过：在途记录既不登记、也不重算或清理，持仓按用户流水调整；尚未处理的在途要等下一个没有用户录入权益流水的交易日才由自动权益处理。
- `positions[].extras.preprocess_dividend`、`positions[].extras.preprocess_bonus` 是未来到账事件的预处理记录，与本类不同：它们不构成当期应收应付科目，也不影响净资产。
- 这些记录的权益源数据来自 rqdatac：分红取 [RQData get_dividend](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)（股票、ETF/LOF/REITs，港股加 market=hk）与 [fund.get_dividend](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_dividend)（公募基金），按 ex_dividend_date→payable_date 建表；拆分取 [get_split](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_split) 与 [fund.get_split](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_split)，按拆分生效日建表。字段行里的 payable_date、ex_dividend_date 与每单位税前分红均出自这些调用。

|英文字段|中文名称|JSON 类型|计算公式|备注|
|---|---|---|---|---|
|<a id="balance"></a>`product_id`|产品 ID|string|归属产品 ID|—|
|`date`|业务日期|string|业务日期，不等同写入时间|—|
|`market_value`|持仓市值|number|从当前报表的实际持仓集合 `P` 筛选 `x.asset_class` 不属于下列值的持仓：[持仓市值排除科目（12 类）](#market-value-exclusions)。<br>&emsp;对保留的每个 `x`，按本表 `total_assets` 字段中说明的规则计算其资产贡献、按本表 `total_liabilities` 字段中说明的规则计算其负债贡献，然后 `sum(资产贡献−负债贡献)`。<br>&emsp;逐仓市值的底层式见本表 `positions[].market_value` 字段；<br>&emsp;期货还须加 `positions[].extras.sterilisation_market_value`。|不是 `sum(positions[].market_value)`：这里只排除明确列出的 12 类；<br>&emsp;现金、回购利息、other_asset/other_liability 并未全部排除。|
|<a id="balance-calculation"></a><a id="total-assets"></a>`total_assets`|总资产|number|遍历 `P`，不做市值排除筛选，每仓资产贡献相加：<br>&emsp;① [按多空计入资产负债的证券（10 类）](#asset-securities)：`direction=long` 时加 `fair_value×quantity`，空头加 0；<br>&emsp;股票/基金缺价格的实现分支加 0。<br>&emsp;② [期货品种（4 类）](#asset-futures)：加 `market_value+extras.sterilisation_market_value`。<br>&emsp;③ [按带符号市值计入资产的品种（7 类）](#asset-signed-market-value)：加 `market_value`（保留正负号）。<br>&emsp;④ 本表 `cash` 字段中列出的 11 类去掉 `money_market_fund` 后的 10 个存款/应收科目：加 `quantity`，此处数量直接代表金额。<br>&emsp;⑤ `repo` 及 本表 `total_liabilities` 字段中列出的负债科目加 0。|不把负资产搬到负债侧；<br>&emsp;期权空头或期货平衡后金额可以为负。<br>&emsp;每项价格、数量和平衡项继续查本表对应的 `positions[]` 字段，不假设响应中有 assets_value 字段。|
|`total_liabilities`|总负债|number|遍历 `P`，逐仓负债贡献相加：<br>&emsp;① 本表 `total_assets` 字段中的第①类证券，`direction=short` 时加 `fair_value×quantity`，多头加 0；<br>&emsp;股票/基金缺价格的实现分支加 0。<br>&emsp;② `asset_class=repo`：加 `−market_value`，即 `100×quantity`。<br>&emsp;③ [数量即负债金额的科目（11 类）](#liability-accounts)：加 `quantity`，此处数量是负债金额。<br>&emsp;④ 其余本表支持品种加 0；<br>&emsp;特别是期货、期权和收益互换不另记负债。|不是把全部负 market_value 取绝对值相加。<br>&emsp;科目数量由流水、托管事件和[估值表覆盖](../reconciliation.md#valuation-report-overwrite)更新。<br>&emsp;展开见本表 `positions[].quantity` 字段。|
|<a id="total-equity"></a>`total_equity`|净资产|number|普通估值：`total_assets−total_liabilities`，两侧逐仓贡献在本表 `total_assets`、`total_liabilities` 字段中展开。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：以[报告](valuation_reports.md) `total_equity` 为目标；<br>&emsp;报告值减当前逐仓资产负债净额的差值绝对值达到 0.01 时，加到 `asset_class=other_asset` 的金额中调平，再计算净资产。|适用条件见[估值表覆盖设置](../reconciliation.md#valuation-report-overwrite-setting)。<br>&emsp;差额不是一笔买卖收益。<br>&emsp;资产单元结果也使用资产减负债，但没有产品份额与单位净值。|
|<a id="daily-pnl"></a>`daily_pnl`|当日盈亏|number|普通估值：从 `P` 排除 `asset_class` 属于 [逐仓盈亏排除科目（21 类）](#pnl-exclusions) 的持仓，并跳过累计盈亏不可计算的记录，累加剩余 `x.daily_pnl`（逐仓公式见本表 `positions[].daily_pnl` 字段）。<br>&emsp;再加当日流水 `transaction_type=interest_income` 的 `settlement_amount` 合计，减 `interest_payment`、<br>&emsp;`capital_gain_tax_payment`、<br>&emsp;`interest_tax_payment`、<br>&emsp;`exercise_deposit_transfer_out` 的 `settlement_amount` 合计。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：`Equity[当日] − Equity[上一估值日] − CustodianFlow[当日]`；`CustodianFlow[当日]` 加当日托管 `subscription_fund_received.amount`，减 `effective_date=t` 的 `redemption_paid.amount` 和 `product_dividend_paid.amount`。|上述 21 类是精确排除集合，不是 cash 的 11 类。<br>&emsp;出入金、托管划转不是现金盈亏；<br>&emsp;CustodianFlow[当日] 按事件生效日而不是付款日计算，不能换成 net_cash_in。|
|<a id="daily-returns"></a>`daily_returns`|当日收益率|number / null|有份额的普通日收益率：非起始日 `(AccNAV[当日] - AccNAV[上一估值日]) / NAV[上一估值日]`；<br>&emsp;昨日累计/单位净值缺失时取基点 1；<br>&emsp;零分母按此分支返回 0。<br>&emsp;起始日为 `AccNAV[当日] - 1`，空累计净值按此分支为 0<br>&emsp;无份额产品：`PnL[当日] / abs(Equity[上一估值日])`；<br>&emsp;零分母为 0<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：报告已有累计净值时用净值差法；<br>&emsp;没有时先补累计净值，再用 `PnL[当日] / abs(Equity[上一估值日])`，此除法不沿用无份额分支的补零规则；<br>&emsp;起始日有份额时用 `AccNAV[当日] - 1`<br>&emsp;资产单元：首日 `PnL[当日] / abs(net_cash_in)`，随后 `PnL[当日] / abs(Equity[上一估值日])`，零分母为 0。<br>&emsp;实时截面：有份额时按累计净值变化/昨日单位净值；<br>&emsp;无份额时按当日盈亏/昨日净资产，具体起始日分支见实时计算。<br>&emsp;聚合产品组：成员当日日盈亏合计除以 `abs(成员昨日净资产合计+当日申赎出入金调整)`，缺昨日时可用成员 `Equity[当日] / (1 + Return[当日])` 反推起点；<br>&emsp;成员收益不完整时分母不可用。<br>&emsp;加权产品组：`sum(成员 daily_returns×盘初有效权重)`；<br>&emsp;首日与再平衡日权重取设定的 `product_weights`，周期内取上一日成员净资产（`unit_net_value×该成员再平衡份数`）占比；<br>&emsp;成员缺权重或收益时该项按 0 计入。|按成员盘初权重加权，不是成员收益的算术平均；<br>&emsp;首日与再平衡日的分母为当日可用组权益，周期内为成员盘初净资产合计。|
|<a id="balance-inputs"></a>`units`|份额|number / null|普通估值：`昨日 units+sum(subscription_units)−sum(redemption_units)`，无旧份额时以当日增量建立。<br>&emsp;按产品 `unit_policy` 选定手工或自动[份额事件来源](products.md)，不能两套重复相加。<br>&emsp;自动事件：托管申购/赎回按 `amount/事件 unit_net_value` 生成份额；<br>&emsp;现金流水按净出入金金额/昨日单位净值生成，昨日净值缺失传 1、为 0 时直接使用金额作为份额增量；<br>&emsp;证券托管划转也由对应流水生成份额。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：报告 `units` 直接建立/覆盖状态。|需选定来源的份额事件及历史起点，不保证仅凭查询区间流水重建；<br>&emsp;没有份额的产品保持空值，资产单元不生成产品份额。|
|<a id="unit-net-value"></a>`unit_net_value`|单位净值|number / null|`NAV[当日] = Equity[当日] / Units[当日]`；<br>&emsp;Units[当日] 为零或无份额时返回空值|产品净资产和有效份额；<br>&emsp;不能假设 units=1|
|<a id="acc-unit-net-value"></a>`acc_unit_net_value`|累计单位净值|number / null|普通估值：累计分红模式分别舍入 `NAV[当日]` 和 `acc_unit_dividend` 后相加再舍入；<br>&emsp;昨日净值模式为 `AccNAV[上一估值日] + 当日每份分红 + (NAV[当日] - NAV[上一估值日])`，求和跳过空值。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)：报告累计净值可直接覆盖；<br>&emsp;未提供时按配置补算。|[产品估值设置](products.md)选择模式，不是所有情况下都等于收益连乘。|
|<a id="adjusted-net-value"></a>`adjusted_net_value`|复权净值|number / null|`AdjNAV[当日] = AdjNAV[上一估值日] × (1 + daily_returns)`，空日收益按 0|历史复权净值和上述日收益；<br>&emsp;与累计分红净值不是一条曲线|
|`acc_unit_dividend`|累计每份分红|number / null|`昨日 acc_unit_dividend+当日每份分红`；<br>&emsp;当日每份分红为托管事件 `custodian_event_type=product_dividend_paid` 且 `effective_date=t` 的 `amount` 合计除以本日 `units`，无有效除数时增量为 0。|这是产品向份额持有人的分红，不取证券 [get_dividend](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)；<br>&emsp;支付日才冲应付并减少 cash/net_cash_in，可能晚于本字段累计日。|
|`positions`|持仓明细|array（object 元素）|当前估值状态下的证券、合约及会计科目列表。<br>&emsp;普通平铺结果可直接作为本页 `P`；<br>&emsp;分类结果须沿 `children[]` 取实际持仓叶子，不把中间分类汇总当成另一仓。|需要完整字段和完整持仓集合；<br>&emsp;只请求部分字段或只取分类小计不能据此复算全产品。|
|<a id="position"></a>`positions[].order_book_id`|证券或合约代码|string|证券/合约代码；<br>&emsp;不是自定义合约记录 ID|—|
|`positions[].symbol`|名称|string|标的或资产单元显示名称|—|
|`positions[].asset_class`|资产品种与会计科目|string（枚举）|枚举[资产品种与会计科目](others.md#assetclass)；[类现金分类](others.md#deposit-like-classification)|—|
|`positions[].product_accounting_major_subject`|产品会计总科目|string（枚举）|由 `(asset_class, direction)` 先归入 `asset_category`，再映射为总科目：资产类资产科目为 `asset`，负债类科目为 `liability`。|由参数选择：`classifier=asset_class`（默认分类）时返回；换成申万/中信等分类后该键不出现。|
|`positions[].industry`|所属行业|string / null|股票按中信 2019 一级行业归属，港股改用申万 2021 一级；其余 `asset_class` 为 `null`。|恒返回该键（值可为 `null`），与请求的 `classifier` 无关；行业分类缓存构建中服务端会要求稍后重试。|
|`positions[].direction`|多空方向|string（枚举）|多空方向；<br>&emsp;枚举[多空方向](#direction)|—|
|`positions[].quantity`|数量|number|证券/合约：承接昨日持仓，按[流水交易类型](../trades.md#transaction-type-effect) 应用买入/开仓增加、卖出/平仓减少以及划转、借还券、行权和到期，不从当前成交量净额猜初始仓位。<br>&emsp;送股/拆分按权益数据改变数量：股票 [get_split](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_split) 的 split_coefficient_to/split_coefficient_from，公募基金 [fund.get_split](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_split) 的 split_ratio；<br>&emsp;换股由 [get_share_transformation](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_share_transformation) 的承接证券和比例形成新仓。<br>&emsp;回购：`sum(extras.repos[].quantity)`。<br>&emsp;本表顶层 `daily_pnl` 字段中排除的 21 个科目：quantity 直接是人民币金额，由各笔业务产生的现金/应收应付变化累加；<br>&emsp;托管 subject_adjusted 根据 adjust_target 和 increase/decrease/adjust_to 更新目标。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：取报告 quantity；<br>&emsp;未列出的原持仓按清仓处理，不是报告再追加买入。<br>&emsp;自动费用与负债：托管 product_cost_paid 冲对应应付；<br>&emsp;签约费直接扣现金。<br>&emsp;分类负债明细见 extras.product_share_quantities.{份额}；<br>&emsp;科目调到目标与增量调整不能混用。|保留历史初始化、在途权益和自动权益开关；<br>&emsp;自动与手工权益不能重复记。<br>&emsp;负债科目扣减超过原负债时，超额转活期存款，负债归零。|
|`positions[].cost`|累计成本|number|普通估值（股票/基金）：开仓 `cost += 成交价×成交量×汇率×s + 税费`；<br>&emsp;平仓 `cost -= 成交价×成交量×汇率×s - 税费`。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)（股票/基金、债券、期货、期权）：使用报告 `cost`，空值按该覆盖分支取 0。<br>&emsp;期货/期权开仓增加 `price×quantity×m×s+transaction_cost`，平仓扣减相应带方向成交金额并加税费；<br>&emsp;债券买入增加 `price×quantity+transaction_cost`，赎回/回售等按 settlement_amount 减成本。<br>&emsp;回购成本来自逐笔 open_cost 及结算状态；<br>&emsp;其他衍生品按成交/报告状态保存。|这里 transaction_cost=commission+tax+other_fees。<br>&emsp;成本可以在清仓后保留已实现盈亏对应余额；<br>&emsp;不是当前数量×买入均价。<br>&emsp;报告各品种规则不同，必须保留历史和业务事件。|
|`positions[].avg_price`|不含费平均开仓价|number|股票/基金开仓：`(旧均价×旧数量+成交price×成交quantity×成交exchange_rate)/新数量`；<br>&emsp;期货/期权按对应合约乘数与带方向成交额加权；<br>&emsp;债券按全价成交额加权。<br>&emsp;平仓一般保留剩余仓均价；<br>&emsp;分红/拆分会调整。<br>&emsp;报告：股票/基金取非空 cost_price（0 有效），缺失取 fair_value；<br>&emsp;债券取 cost_price 或 0；<br>&emsp;期货有数量时取 −sterilisation_market_value/(q×m×s)；<br>&emsp;期权非零 cost_price 优先，否则 cost/(q×m×s)。<br>&emsp;回购本金均价固定 100。|需上一个状态及权益事件，不从当前 cost/q 统一反推。|
|`positions[].avg_price_include_fee`|含费平均开仓价|number|普通估值（股票/基金开仓）：`(旧均价×旧数量×s + 成交价×成交量×汇率×s + 税费)/(新数量×s)`；<br>&emsp;分红可下调均价。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)：股票/基金使用报告 `cost_price`，非空的 0 也接受，缺失时用报告 `fair_value`；<br>&emsp;债券用 `cost_price` 或 0；<br>&emsp;期货数量非零时为 `-sterilisation_market_value/(q×m×s)`；<br>&emsp;期权用非零 `cost_price`，否则用 `cost/(q×m×s)`。|依赖昨日均价和数量、当笔流水及权益金额；<br>&emsp;报告成本价不必保留原成交流水的含费与不含费差别。|
|`positions[].last_avg_price_include_fee`|昨日含费平均开仓价|number|昨日含税费平均开仓价格|—|
|`positions[].last_quantity`|昨日数量|number / null|昨日持仓数量|—|
|`positions[].money_fund_remain_quantity`|货基再投资剩余份额|number|需要整份记账的货基再投资：`z=每份收益×(quantity+旧余数)+旧余数`；<br>&emsp;取 z 整数部分作为再投资份额，小数部分保存到本字段。<br>&emsp;每份收益来自 [fund.get_nav](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_nav).daily_profit/10000；[估值表覆盖](../reconciliation.md#valuation-report-overwrite)时余数归零。|非整份限制分支可直接按每份收益×数量生成份额。|
|<a id="position-inputs"></a>`positions[].fair_value`|估值价格|number / null|用户[公允价](custom_instruments.md)按品种、代码、日期命中时采用人工价格；<br>&emsp;否则按品种和[估值设置](products.md)选择行情，不统一取 close：<br>&emsp;股票/一般场内证券取 [RQData get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi) 日频未复权 close（港股 market=hk），上市前可用 instruments().issue_price；<br>&emsp;ETF 取 close/iopv，默认 iopv，零/缺失 IOPV 用 close，再向前填零；<br>&emsp;公募基金带交易所后缀可用 get_price，其余 fund.get_nav 的 unit_net_value；<br>&emsp;期货/期权取 settlement 或 close，默认 settlement。<br>&emsp;可转债全价/净价来源见本表 `positions[].clean_price` 字段；<br>&emsp;普通债券需要可用人工公允价、报告或既有价格，不能承诺自动有中债估值。<br>&emsp;实时取 [RQData current_snapshot](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot) 的 last/settlement/iopv，分钟序列用 get_price(frequency="1m",adjust_type="none")，仍结合历史状态；<br>&emsp;收益互换有绑定资产单元时还接受单元估值输入。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：取报告价格；<br>&emsp;股票/基金、期货价格与市值不一致时分别按报告 market_value/(q×s)、market_value/(q×m×s)反推；<br>&emsp;债券报告 fair_value 为空/零按 0。|外部接口不是 Harness API；<br>&emsp;缺少价格时有保留旧价的分支，不等于人工输入 0。<br>&emsp;持仓已处理分红送股，不能再用复权行情重复调整。<br>&emsp;人民币主估值价与 fair_value_setl_ccy 区分。|
|`positions[].fair_value_setl_ccy`|结算币种估值价格|number / null|结算币种原始估值价；<br>&emsp;港股通常为未换汇的港币价格，人民币 fair_value 在估值阶段按 exchange_rate 换算。[估值表覆盖](../reconciliation.md#valuation-report-overwrite)还可能按报告人民币市值与原币价格反推汇率，再重新取得对应原币价格。|不是在所有报告分支都能简单用当前 fair_value/exchange_rate 重建；<br>&emsp;股票分红除息也会下调此价格。|
|`positions[].clean_price`|债券净价|number / null|债券每单位净价。<br>&emsp;可转债：[RQData get_price](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)(close)、[convertible.get_accrued_interest_eod](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_accrued_interest_eod) 及 [convertible.instruments](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-instruments).trade_type 决定净价交易还是全价交易：净价交易的全价=close+单位应计利息，全价交易的净价=close−单位应计利息。<br>&emsp;非交易日返回负应计利息的分支，用已保留全价减其绝对值。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：`(报告 market_value−(报告 accrued_interest 或 0))/报告 quantity`，零数量时取 fair_value；<br>&emsp;无独立净价但有本次公允价时取该价。|普通债券不能套用可转债自动接口。|
|<a id="position-calculation"></a>`positions[].market_value`|持仓市值|number|按 x.asset_class 分支，取同仓 `p=fair_value`、`q=quantity`、`s=long:+1/short:−1`：<br>&emsp;股票/基金、债券及三类收益互换/其他衍生品：<br>&emsp;衍生品包括 `total_return_swap`、<br>&emsp;`interest_return_swap`、`other_derivatives`。<br>&emsp;这些品种均为：`p×q×s`；<br>&emsp;股票/基金价格缺失时返回 0。<br>&emsp;期货/期权：`p×q×m×s`；<br>&emsp;期货 m 取 [RQData instruments](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments).contract_multiplier，期权 m 取本表 `positions[].extras.contract_multiplier` 字段的同仓值（按日期 [options.get_contract_property](https://www.ricequant.com/doc/rqdata/python/options-mod#rqdata-API-options-get-contract_property) 的 contract_multiplier，缺失回退合约属性）。<br>&emsp;逆回购：`q×100`；<br>&emsp;正回购：`−q×100`，不使用 direction 或流水利率作本金价格。<br>&emsp;本表 `cash` 字段中去掉货币基金后的 10 个存款/应收科目：q；<br>&emsp;本表 `total_liabilities` 字段中的 11 个负债科目：−q。|人民币估值价格 p 已按 exchange_rate 换算，不能再次乘汇率；<br>&emsp;流水 price 仍依结算币种。<br>&emsp;期货名义市值不等于资产贡献；<br>&emsp;汇总必须继续按本表 `total_assets`、`total_liabilities` 字段中的分支计算。|
|`positions[].market_value_setl_ccy`|结算币种市值|number / null|股票/基金：`fair_value_setl_ccy×quantity×s`；<br>&emsp;原币价格为空时返回 null。|原币金额，与 market_value 的人民币口径区分。|
|`positions[].clean_price_market_value`|债券净价市值|number / null|债券：`clean_price×quantity`。|该实现不乘多空方向因子；<br>&emsp;不是 market_value 的统一换名。|
|`positions[].acc_pnl`|累计盈亏|number|股票/基金：`round(market_value−cost,2)`；<br>&emsp;债券、期货、期权、其他衍生品：`market_value−cost`；<br>&emsp;回购：`sum(extras.repos[].pnl)×r`，逆回购 r=+1/正回购 r=−1。|价格、数量、成本及逐笔回购来源见本表对应字段；<br>&emsp;类现金会计科目不参与普通逐仓日盈亏。|
|`positions[].last_acc_pnl`|昨日累计盈亏|number|昨日累计盈亏|—|
|`positions[].acc_pnl_rate`|累计盈亏率|number|通常 `acc_pnl/abs(cost)`；<br>&emsp;回购用逐笔 open_cost 合计的绝对值；<br>&emsp;零分母返回 0。|累计盈亏率；<br>&emsp;累计成本状态或回购本金及费用|
|`positions[].daily_pnl`|当日盈亏|number|通常 `acc_pnl−last_acc_pnl`；<br>&emsp;回购取 `sum(extras.repos[].daily_accrued_interest)×r`，不是累计盈亏差。<br>&emsp;上层按 (asset_class,order_book_id,direction) 对齐历史。|计算跳过 本表顶层 `daily_pnl` 字段中列出的 21 类科目和 acc_pnl 不可计算的仓；[估值表覆盖](../reconciliation.md#valuation-report-overwrite)可能改变产品日盈亏而不逐仓覆盖一致。|
|`positions[].daily_pnl_rate`|持仓当日盈亏率|number|`daily_pnl / abs(昨日market_value-daily_payment_amount + daily_open_amount)`；<br>&emsp;昨日市值按持仓键匹配、缺仓取 0，零分母返回 0。|当日持仓盈亏率，不等于产品收益率贡献；<br>&emsp;昨日市值；<br>&emsp;当日权益支付/收取金额；<br>&emsp;开仓含费金额。<br>&emsp;零分母按服务端非有限值处理，不代表零收益|
|`positions[].contribute_returns`|当日收益贡献|number / null|`daily_pnl / 分母`，优先昨日 total_equity，为零时改用当日 net_cash_in；<br>&emsp;再为零返回空值|持仓对产品当日收益的贡献；<br>&emsp;分母不是本持仓成本，来源见[头寸报表计算](balances.md#balance-calculation)。<br>&emsp;负的昨日权益不取绝对值|
|`positions[].floating_pnl`|浮动盈亏|number|股票/基金 `(p-avg_price_include_fee)×q×s`；<br>&emsp;债券 `(p-avg_price)×q`；<br>&emsp;期货 `(p-avg_price_mtm)×q×m×s`；<br>&emsp;期权 `(p-avg_price)×q×m×s`；<br>&emsp;回购为 `sum(extras.repos[].pnl)×r`，其他衍生品为 `(p−avg_price)×q×s`。|浮动盈亏；<br>&emsp;不同品种均价含义不同；<br>&emsp;期货使用盯市均价。<br>&emsp;债券此公式本身没有再乘空头方向，不能擅自补符号|
|`positions[].floating_pnl_percentage`|浮动盈亏率|number|股票/基金：`(fair_value/avg_price_include_fee - 1)×s`；<br>&emsp;债券：`fair_value/avg_price - 1`；<br>&emsp;期货：`(fair_value/avg_price_mtm - 1)×s`；<br>&emsp;期权及其他衍生品：`(fair_value/avg_price - 1)×s`。<br>&emsp;这些分支数量或均价为 0 时返回 0。<br>&emsp;回购：`floating_pnl/market_value×r`，零数量或零市值为 0。|这是比例，不是百分数数值；<br>&emsp;其他缺值处理依具体品种，不用统一补零。|
|`positions[].accrued_interest`|应计利息|number|债券：`(fair_value−clean_price)×quantity`；<br>&emsp;回购：`sum(extras.repos[].accrued_interest)×r`，逆回购 r=+1，正回购 r=−1。|应计不等于已到账；<br>&emsp;回购利息还对应独立应收/应付科目，不在本金市值里加一次。|
|`positions[].exchange_rate`|汇率|number|CNY 为 1；<br>&emsp;HKD 从 [RQData get_exchange_rate](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk) 的 HKDCNY 按产品 sh/sz 设置取结算 bid/ask，中间价为二者均值，缺结算时回退 referrence（源字段实际拼写），再依可用日期选取。<br>&emsp;港股通流水汇率为 1 时，开仓取系统交易 ask、平仓取 bid；<br>&emsp;日内 provider 可改用参考中间价。<br>&emsp;显式交易汇率使用该笔值。|历史成交汇率与当前估值汇率不能替换；<br>&emsp;自动通路不代表支持任意外币。|
|`positions[].currency`|币种|string（枚举）|币种；<br>&emsp;枚举[币种](#currency)|—|
|`positions[].bonus_share_receivable`|应收红股数量|number|应收红股数量字段；<br>&emsp;当前本地计算实现未找到主动更新该字段的路径，不能承诺等于某个在途数组的数量和。|实际送股/拆分状态查 extras.split_in_transit 及真实数量变动；<br>&emsp;保留返回值，不自行构造。|
|`positions[].extras`|品种扩展数据|object / null|品种相关扩展数据，按 asset_class 选择分支|—|
|<a id="futurespositionextra"></a>`positions[].extras.sterilisation_market_value`|期货平衡项市值|number|期货：`−positions[].avg_price×positions[].quantity×m×s`；<br>&emsp;m 是该期货合约乘数，s 为多空方向。<br>&emsp;报告非零数量时由报告平衡项反推 avg_price，因此代入可还原报告平衡项。|只对期货分支；<br>&emsp;与名义 market_value 相加才是计入资产的金额，不代表另一个现金头寸。|
|<a id="stockfundpositionextra"></a>`positions[].extras.dividend_in_transit`|应收分红在途|array（object 元素）|已登记未到账的应收分红；<br>&emsp;展开见 [应收分红](balances.md#dividendintransit)；<br>&emsp;科目归属与清理见[在途类字段共同口径](#in-transit-fields)|—|
|<a id="dividendintransit"></a>`positions[].extras.dividend_in_transit[].arrival_date`|到账或结算日期|string|分红源记录的 payable_date（实际权益支付日）：股票、ETF/LOF/REITs 取 [RQData get_dividend](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)（港股 market=hk），公募基金取 [fund.get_dividend](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_dividend)。|按历史权益和日历处理，不能用同一来源的 ex_dividend_date 替代。|
|`positions[].extras.dividend_in_transit[].amount`|金额|number|除息时的数量×每单位税前分红×汇率；<br>&emsp;每单位税前分红来自 rqdatac 分红数据：股票、ETF/LOF/REITs 为 dividend_cash_before_tax/round_lot，公募基金为 dividend_before_tax（调用见上一行）；<br>&emsp;人工自动权益覆盖有 settlement_amount 时用该金额。|人民币应收金额；<br>&emsp;详细源字段与税费/开关见本表 `positions[].daily_payment_amount` 字段。|
|`positions[].extras.borrowed_dividend_in_transit`|借券红利支出在途|array（object 元素）|已登记未扣款的借券红利支出；<br>&emsp;展开见 [借券红利支出](balances.md#borroweddividendintransit)；<br>&emsp;只有 A 股空头产生该记录，科目与清理见[在途类字段共同口径](#in-transit-fields)|—|
|<a id="borroweddividendintransit"></a>`positions[].extras.borrowed_dividend_in_transit[].arrival_date`|到账或结算日期|string|当前借券红利处理分支取 rqdatac 分红数据（[get_dividend](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)）的除权除息日 ex_dividend_date，先记在途供用户流水抵扣；<br>&emsp;登记与冲销都在该日盘前完成，日终结果通常为空。|不同于多头红利的 payable_date。|
|`positions[].extras.borrowed_dividend_in_transit[].amount`|金额|number|借券仓按数量×每单位税前分红×汇率形成红利支出；<br>&emsp;每单位税前分红来源同本表 `positions[].extras.dividend_in_transit[].amount` 字段；<br>&emsp;允许对应人工权益金额覆盖。|人民币应付金额；<br>&emsp;不是当前持仓 cost。|
|`positions[].extras.split_in_transit`|红股拆分在途|array（object 元素）|红股拆分在途；<br>&emsp;展开见 [红股拆分在途](balances.md#splitintransit)；<br>&emsp;只有股票、ETF、LOF、开放式与封闭式基金、REITs 会产生该记录；<br>&emsp;清理时点见[在途类字段共同口径](#in-transit-fields)|—|
|<a id="splitintransit"></a>`positions[].extras.split_in_transit[].arrival_date`|到账或结算日期|string|rqdatac 拆分数据的拆分生效日（即除权除息日）：股票、ETF/LOF/REITs 取 [get_split](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_split)，公募基金取 [fund.get_split](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_split) 的 ex_dividend_date；<br>&emsp;登记当日即并入持仓，日终结果通常为空。|不是现金分红到账日；<br>&emsp;股票拆分记录的 payable_date（送转股上市日）不参与。|
|`positions[].extras.split_in_transit[].quantity`|数量|number|本次登记的新增红股数量，由拆分比例与登记时持仓数量形成；<br>&emsp;拆分比例来自 rqdatac 拆分数据：股票、ETF/LOF/REITs 为 split_coefficient_to/split_coefficient_from，公募基金为 split_ratio；<br>&emsp;到账后并入 `positions[].quantity`。|这是单笔在途数量，不是持仓 quantity。|
|`positions[].extras.hkt_dividend_in_transit`|港股通红利在途|array（object 元素）|港股通红利在途；<br>&emsp;展开见 [港股通红利在途](balances.md#hktdividendintransit)；<br>&emsp;科目归属与清理见[在途类字段共同口径](#in-transit-fields)|—|
|<a id="hktdividendintransit"></a>`positions[].extras.hkt_dividend_in_transit[].arrival_date`|到账或结算日期|string|rqdatac 港股分红数据的 payable_date 后第 2 个港股通交易日；<br>&emsp;该 payable_date 取 [RQData get_dividend](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend) 的港股数据（market=hk）；<br>&emsp;到账日盘前完成换汇与红利税折算，记录随即移除。|需港股通交易日历，不能直接把除息日或源 payable_date 当此值。|
|`positions[].extras.hkt_dividend_in_transit[].exchange_rate_date`|换汇日期|string|同到账日期行的源 payable_date：为港股通交易日时取该日，否则取其后第一个港股通交易日。|用于结算换汇，与除息参考汇率日期区分。|
|`positions[].extras.hkt_dividend_in_transit[].amount`|金额|number|港币每单位税前分红×除权除息日数量；<br>&emsp;每单位税前分红来自 rqdatac 港股分红数据（get_dividend 的 dividend_cash_before_tax/round_lot，market=hk）。|港币源金额；<br>&emsp;最终到账人民币按换汇日结算 bid 汇率折算并扣 20% 港股通红利税；<br>&emsp;人工覆盖的到账金额替换该现金结果，不改变除权日的应收与成本口径。|
|`positions[].extras.hkt_dividend_in_transit[].cny_amount`|人民币金额|number|本记录 amount×当日适用汇率，逐日重算：<br>&emsp;换汇日之前、以及换汇日 22:30 之前用除权除息日 HKD 参考汇率；<br>&emsp;换汇日 22:30 之后及其后用换汇日的结算 bid 汇率。<br>&emsp;逐日差额计入应收股利。|当日的人民币在途应计，与应收股利同口径；<br>&emsp;不等于最终到账人民币金额。|
|`positions[].extras.hkt_payable_in_transit`|港股通买入结算款在途|array（object 元素）|港股通买入结算款在途；<br>&emsp;展开见 [港股通买入结算在途](balances.md#hktseltpayableintransit)；<br>&emsp;科目与清理见[在途类字段共同口径](#in-transit-fields)|—|
|<a id="hktseltpayableintransit"></a>`positions[].extras.hkt_payable_in_transit[].amount`|金额|number|仅来自开仓（买入类）的港股通流水：`流水 price×quantity×交易ask汇率+transaction_cost`。|人民币应付结算款，成交日先记 `other_payable` 科目；<br>&emsp;当日 22:30 前保留在途，之后按当日结算 ask 汇率重算转入现金并同额冲回该科目。|
|`positions[].extras.hkt_payable_in_transit[].setl_ccy_amount`|结算币种金额|number|`流水 price×quantity`。|港币成交金额，不包含人民币税费。|
|`positions[].extras.hkt_payable_in_transit[].cost`|交易税费|number|`流水 commission+tax+other_fees`（transaction_cost）。|本笔人民币交易税费，不是 positions[].cost，也不是 price×quantity。|
|`positions[].extras.hkt_receivable_in_transit`|港股通卖出结算款在途|array（object 元素）|港股通卖出结算款在途；<br>&emsp;展开见 [港股通卖出结算在途](balances.md#hktseltreceivableintransit)；<br>&emsp;科目与清理见[在途类字段共同口径](#in-transit-fields)|—|
|<a id="hktseltreceivableintransit"></a>`positions[].extras.hkt_receivable_in_transit[].amount`|金额|number|仅来自平仓（卖出类）的港股通流水：`流水 price×quantity×交易bid汇率−transaction_cost`。|人民币应收结算款，成交日先记 `other_receivable` 科目；<br>&emsp;当日 22:30 前保留在途，之后按当日结算 bid 汇率重算转入现金并同额冲回该科目。|
|`positions[].extras.hkt_receivable_in_transit[].setl_ccy_amount`|结算币种金额|number|`流水 price×quantity`。|港币成交金额，不包含人民币税费。|
|`positions[].extras.hkt_receivable_in_transit[].cost`|交易税费|number|`流水 commission+tax+other_fees`（transaction_cost）。|本笔人民币交易税费，不是 positions[].cost，也不是 price×quantity。|
|`positions[].extras.preprocess_dividend`|分红预处理|array（object 元素）|分红到账预处理，不构成当期净资产科目；<br>&emsp;展开见 [分红预处理](balances.md#preprocessdividend)|—|
|<a id="preprocessdividend"></a>`positions[].extras.preprocess_dividend[].arrival_date`|到账或结算日期|string|对应手工流水 trading_date 的下一交易日（通过计算日历确定）。|不是固定加一个自然日。|
|`positions[].extras.preprocess_dividend[].amount`|金额|number|手工 pre_dividend 流水的 settlement_amount。|预处理记录，不套用证券累计数量或持仓成本公式；<br>&emsp;在对应到账日处理。|
|`positions[].extras.preprocess_bonus`|红股预处理|array（object 元素）|红股预处理；<br>&emsp;展开见 [红股预处理](balances.md#preprocessbonus)|—|
|<a id="preprocessbonus"></a>`positions[].extras.preprocess_bonus[].arrival_date`|到账或结算日期|string|对应手工流水 trading_date 的下一交易日（通过计算日历确定）。|不是固定加一个自然日。|
|`positions[].extras.preprocess_bonus[].quantity`|数量|number|手工 pre_bonus_share 流水的 quantity，表示本次新增红股数量。|预处理记录，不套用证券累计数量或持仓成本公式；<br>&emsp;在对应到账日处理。|
|<a id="repopositionextra"></a>`positions[].extras.repos`|逐笔回购明细|array（object 元素）|各笔回购明细；<br>&emsp;展开见 [逐笔回购](balances.md#singlerepo)|—|
|<a id="singlerepo"></a>`positions[].extras.repos[].quantity`|数量|number|本笔回购未购回数量，创建时取流水 quantity，部分购回时扣减；<br>&emsp;汇总为 positions[].quantity。|本笔数量为 0 后仍可能有未结计息，是否保留由计息到期日判断。|
|`positions[].extras.repos[].interest_per_day`|每日利息|number|`本笔 quantity×100×开仓流水 price/365`。|流水 price 是年化利率（小数），非本金价格；<br>&emsp;部分购回按剩余数量比例缩减。<br>&emsp;报告构造的记录不凭本金重建历史利率。|
|`positions[].extras.repos[].interest_start_date`|开始计息日|string|开仓流水 trading_date 的下一交易日。|按 [RQData 交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)。|
|`positions[].extras.repos[].interest_maturity_date`|结束计息日|string|通常为 repo_maturity_date 的下一交易日；<br>&emsp;提前购回等业务可调整。|[估值表覆盖](../reconciliation.md#valuation-report-overwrite)构造的哨兵到期日记录不正常计息，不能据其日期推算真实期限。|
|`positions[].extras.repos[].repo_maturity_date`|回购结束日|string|开仓日期加合约回购期限并按该品种到期规则处理；<br>&emsp;期限由合约信息取得。|回购到期日与资金可用日可能不同。|
|`positions[].extras.repos[].accrued_interest`|应计利息|number|计息交易日为 `interest_per_day×(下一交易日−interest_start_date).days`；<br>&emsp;到期后非交易日补计分支设为 interest_per_day；<br>&emsp;购回、结算可能冲减。|累计应计状态，不是简单自然日天数×日利息。|
|`positions[].extras.repos[].open_cost`|开仓成本|number|创建时 `100×开仓流水 quantity×r+transaction_cost`，逆回购 r=+1、正回购 r=−1。|逐笔历史现金成本，不是当前回购全部成本。|
|`positions[].extras.repos[].pnl`|盈亏|number|计息交易日更新为 `interest_per_day×(下一交易日−interest_start_date).days`；<br>&emsp;购回/到期处理中按对应记录更新。|与 accrued_interest 为两个独立状态；<br>&emsp;到期非交易日只更新应计的分支不同时更新 pnl。|
|`positions[].extras.repos[].daily_accrued_interest`|当日应计利息|number|未开始计息或[估值表覆盖](../reconciliation.md#valuation-report-overwrite)构造的记录为 0；<br>&emsp;交易日为 `interest_per_day×(下一交易日−当日).days`；<br>&emsp;非交易日若当日已超过 repo_maturity_date，为 interest_per_day，否则为 0。|逐笔值在上层再乘正/逆回购方向；<br>&emsp;节假日前会一次计多天，并有到期对冲/补计处理。|
|<a id="optionpositionextra"></a>`positions[].extras.contract_multiplier`|合约乘数|number|期权合约乘数，交易所期权按 [RQData options.get_contract_property](https://www.ricequant.com/doc/rqdata/python/options-mod#rqdata-API-options-get-contract_property)(fields="contract_multiplier") 对应日期取得，缺失可回退 [instruments](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments).contract_multiplier；<br>&emsp;场外合约取其定义。|数量/价格乘数应取当日值，不固定为 1，也不把历史乘数全部替换为当前值；<br>&emsp;期货 m 通常来自合约信息而非此 extras 字段。|
|<a id="bondpositionextra"></a>`positions[].extras.preprocess_payments`|付息预处理|array（object 元素）|债券付息预处理，下一交易日前不影响资产；<br>&emsp;展开见 [付息预处理](balances.md#preprocesspayment)|—|
|<a id="preprocesspayment"></a>`positions[].extras.preprocess_payments[].arrival_date`|到账或结算日期|string|对应手工流水 trading_date 的下一交易日（通过计算日历确定）。|不是固定加一个自然日。|
|`positions[].extras.preprocess_payments[].amount`|金额|number|手工 pre_coupon_payment 流水的 settlement_amount。|预处理记录，不套用证券累计数量或持仓成本公式；<br>&emsp;在对应到账日处理。|
|<a id="payablepositionextra"></a>`positions[].extras.product_share_quantities`|分类份额应付金额|object（string 键 → number）|管理费/业绩报酬应付负债按分类份额拆分的金额。只在当日有生效分类份额的产品上出现（判定：`shares` 已配置且至少一个份额的 `effective_date` 不晚于查询日，见[分类份额配置](products.md#productsharesettings)）：没有生效分类份额的产品不产生本字段，管理费直接按母产品口径计入 `management_fee_payable`（见[产品费用配置](products.md#feesettings)）|—|
|`positions[].extras.product_share_quantities.{份额}`|分类份额应付金额|number|该管理费/业绩报酬应付科目对指定分类的金额；<br>&emsp;随分类计提、托管 product_cost_paid/subject_adjusted 增减或调整到目标。<br>&emsp;分类管理费按 `昨日分类净资产×(产品管理费率+该份额管理费率)/365` 逐份额取分，不足一分不计提；<br>&emsp;托管费、销售服务费、运营费不按分类拆分，始终按 `昨日产品净资产×年费率/365` 计入母产品应付科目，有生效分类份额时同样取分、不足一分不记账。|金额而非份额；<br>&emsp;没有生效分类份额时不产生本字段，全部费用按母产品口径计提，且逐日不取分。<br>&emsp;业绩报酬使用其业务计算/事件输入，不套用固定年费率。<br>&emsp;对应事件、费率、生效配置及历史应付缺一不可。|
|`positions[].open_date`|建仓日期|string / null|建仓日期|—|
|`positions[].trade_date_latest`|最近交易日期|string / null|最近交易日期|—|
|`positions[].acc_dividend_received`|累计已收股息|number / null|承接历史已收股息；<br>&emsp;普通多头到账增加实际分红金额，借券红利支付扣减；<br>&emsp;港股通到账增加换汇后的人民币实收，人工权益流水可改实际支付。|不是累计 dividend_in_transit.amount：在途未到账、借券支付、自动权益覆盖和历史状态都影响结果。|
|`positions[].acc_interest_received`|累计已收利息|number / null|债券承接历史值，加本次已收票息金额；<br>&emsp;本金兑付不计入本字段。<br>&emsp;可转债自动现金流取 [convertible.get_cash_flow](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_cash_flow) 及合约本金信息，手工流水取对应付息金额。|不能用 accrued_interest 的变化替代实收票息。|
|`positions[].open_avg_price`|买入含费均价|number|股票/基金开仓按含费成交额加权；<br>&emsp;自动或手工股息分红会扣减每份分红，拆分按比例调整；[估值表覆盖](../reconciliation.md#valuation-report-overwrite)取 cost_price（非空，包括 0）或 fair_value。|原文“不随分红变化”不符合当前代码。|
|`positions[].avg_price_mtm`|逐日盯市均价|number|期货开仓按旧盯市均价、旧数量及新成交额加权；<br>&emsp;更新估值价格后设为本次 fair_value（没有新价格时仍使用保留价格）。|因此浮动盈亏为当前价格相对盯市均价，不等于累计盈亏；<br>&emsp;不能仅理解成现金清算完成标志。|
|`positions[].daily_payment_amount`|当日自动权益收益金额|number|每天重置。<br>&emsp;股票/场内基金股息数据来自 [RQData get_dividend](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)：每单位税前分红=dividend_cash_before_tax/round_lot，按 ex_dividend_date/payable_date；<br>&emsp;公募基金取 [fund.get_dividend](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_dividend).dividend_before_tax。<br>&emsp;自动权益按数量×每单位分红×汇率×s 形成金额；<br>&emsp;人工权益覆盖可替换应收金额。<br>&emsp;港股通多头除息金额按源股息×数量×参考汇率记入，在途到账时再按结算规则调整；<br>&emsp;编辑最终到账金额不等于改写除息成本。<br>&emsp;货基按 [fund.get_nav](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_nav)(fields="daily_profit")/10000 得每份收益；<br>&emsp;债券付息取实际现金流，见本表 `positions[].acc_interest_received` 字段。|除息日形成金额不保证当日现金到账；<br>&emsp;自动权益开关、人工事件、税费及日期须匹配。<br>&emsp;产品分红不是本字段。|
|`positions[].daily_open_amount`|当日开仓金额|number|每天盘前重置为 0，累计开仓成本增加：股票/基金 `price×quantity×exchange_rate×s+transaction_cost`；<br>&emsp;债券 `price×quantity+transaction_cost`；<br>&emsp;期货/期权 `price×quantity×m×s+transaction_cost`；<br>&emsp;回购 `100×quantity×r+transaction_cost`。|当日开仓金额包含费用且可带方向；<br>&emsp;不是期货实际支付的保证金或手续费。|
|`positions[].price_limit`|涨跌停标记|string / null|涨停 limit_up 或跌停 limit_down，取自 [RQData current_snapshot](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot) 快照|—|
|`positions[].price_change`|价格涨跌额|number / null|有当前价和 [RQData current_snapshot](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot) 快照的 tick 时：fair_value 减基准价；<br>&emsp;基准优先 price_change_baseline，缺失时取 tick.prev_settlement 的非零值，否则 tick.prev_close；<br>&emsp;港股在后一分支按 exchange_rate 换成人民币。|缺 tick/价格时不强制新算；<br>&emsp;不要与日收益率混用。|
|`positions[].price_change_percentage`|价格涨跌幅|number / null|price_change 除以 本表 `positions[].price_change` 字段中选定的基准价，零分母分支返回 0。|比例；<br>&emsp;行情 NaN 不由这个公式自动当零。|
|`positions[].price_change_baseline`|涨跌幅比较基价|number / null|盘前权益等调整后的已保留估值价，按两位小数保存，作为日内价格涨跌基准。|可反映场外估值覆盖，不固定等于原始昨收行情。|
|`positions[].has_settlement`|是否已取得结算价|boolean|实时数据提供器检查对应期货/期权 tick.settlement 是否非 NaN，写入布尔结果。|表示有结算报价，不表示现金交割/清算完成。|
|`positions[].update_time`|数据更新时间|string / null|实时更新价格时取对应 tick.datetime。|行情时间不是请求时间；<br>&emsp;缺 tick 可为空。|
|`positions[].etf_discount_premium_rate`|ETF 折溢价率|number / null|实时 ETF（last、iopv 取自 [RQData current_snapshot](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot) 快照）：last 无有效值时为空；<br>&emsp;16:10 后优先用有效基金单位净值作分母，取 last/unit_net_value - 1；<br>&emsp;其余情况或净值不可用时用有效 iopv，取 last/iopv - 1；<br>&emsp;都不可用为空。|是市场价相对净值的折溢价，不一定等于按估值设置选出的 fair_value 与 IOPV 之比。|
|`etf_discount_premium_positions`|异常折溢价 ETF 持仓|array（object 元素） / null|实时从产品与资产单元持仓中筛选 `asset_class=etf_fund`、折溢价率非空且非 NaN、`abs(etf_discount_premium_rate)>=0.1` 的记录，按 order_book_id 去重；<br>&emsp;逐项包含 order_book_id、symbol、etf_discount_premium_rate。|10% 恰在边界内；<br>&emsp;这是异常 ETF 子集，不是全部 ETF，折溢价率原式见本表 `positions[].etf_discount_premium_rate` 字段。|
|`year_init_unit_net_value`|年初单位净值|number / null|跨年时保存上一估值状态的 `unit_net_value`，年内沿用；<br>&emsp;实时起始日分支以 1 建立基点。|来源是上年末/初始化历史状态，不是查询区间首日值；<br>&emsp;缺历史不应由客户端补 1。|
|`year_init_acc_net_value`|年初累计净值|number / null|跨年时保存上一估值状态的 `acc_unit_net_value`，年内沿用；<br>&emsp;实时起始日分支以 1 建立基点。|来源是上年末/初始化历史状态，不是查询区间首日值；<br>&emsp;缺历史不应由客户端补 1。|
|`year_init_adjusted_net_value`|年初复权净值|number / null|跨年时保存上一估值状态的 `adjusted_net_value`，年内沿用；<br>&emsp;实时起始日分支以 1 建立基点。|来源是上年末/初始化历史状态，不是查询区间首日值；<br>&emsp;缺历史不应由客户端补 1。|
|`returns_this_year`|本年收益率|number / null|实时头寸：若 `year_init_unit_net_value` 非零且当日累计净值非空，取 `(acc_unit_net_value − year_init_acc_net_value) / year_init_unit_net_value`；<br>&emsp;否则若 `year_init_adjusted_net_value` 非零，取 `adjusted_net_value/year_init_adjusted_net_value - 1`；<br>&emsp;无有效基点时为空。|各基点及当日净值公式见本表同名字段；<br>&emsp;不要用净资产增长率代替。<br>&emsp;指标 API 的期间处理另见[指标公式](../analytics/metrics.md#indicators-returns)。|
|`pnl_this_year`|本年累计盈亏|number / null|当年每日 `daily_pnl` 相加；<br>&emsp;跨年首日取当日 daily_pnl。<br>&emsp;实时反复刷新时用 `昨日 pnl_this_year+本次 daily_pnl`，不在本次结果上反复累加。|原始日盈亏需完整年内历史；<br>&emsp;不是年底净资产减年初净资产。|
|`returns_from_establish`|成立以来收益率|number / null|实时头寸：与 `returns_this_year` 使用同一分支条件；<br>&emsp;年初单位净值非零且当日累计净值非空时为 `acc_unit_net_value - 1`，否则为 `adjusted_net_value - 1`。|减 1 是服务端既定基点，并不意味着实际初始投入金额为 1；<br>&emsp;累计净值和复权净值不是同一序列。|
|`daily_pnl_on_close`|昨收口径当日盈亏|number / null|按本表顶层 `daily_pnl` 字段中相同的逐仓排除条件，逐仓重算并合计日盈亏；<br>&emsp;通常取 `当前 acc_pnl−昨日收盘价口径 acc_pnl`，回购仍取当日逐笔计息。|本字段未像 daily_pnl 再加现金盈亏调整。<br>&emsp;昨日收盘口径累计盈亏是另一份历史计算输入，不应改用当前 pos.last_acc_pnl；<br>&emsp;不会覆盖持仓原 daily_pnl。|
|`daily_returns_on_close`|昨收口径当日收益率|number / null|产品起始日取 `unit_net_value - 1`，缺净值为空；<br>&emsp;其余日取 `daily_pnl_on_close/abs(昨日收盘口径 total_equity)`，该除法零分母分支为 0。|不使用普通历史 daily_returns 的累计净值差分母；<br>&emsp;只有实际计算提供时读取，不能把缺字段补零。|
|`daily_equity_long_returns`|权益多头当日收益率|number / null|日内序列：从可计算逐仓盈亏中筛选 `direction=long` 且 `asset_class` 属于 [日内权益多空收益品种（21 类）](#intraday-equity-classes)，累加 `daily_pnl` 得到分子。<br>&emsp;[绑定资产单元](../asset_units.md#asset-unit-binding)的 `total_return_swap` 若有对应分钟数据，则改用其内部同方向盈亏。<br>&emsp;产品首日除以 `abs(net_cash_in)`，之后除以 `abs(昨日 total_equity)`；<br>&emsp;除法零分母分支为 0。|名称含「权益」，但集合包含债券、回购和衍生品，不等于 `equity_net_exposure` 的筛选条件。<br>&emsp;内部分钟盈亏不是当前单张报表全部提供的输入。|
|`daily_equity_short_returns`|权益空头当日收益率|number / null|日内序列：从可计算逐仓盈亏中筛选 `direction=short` 且 `asset_class` 属于 [日内权益多空收益品种（21 类）](#intraday-equity-classes)，累加 `daily_pnl` 得到分子。<br>&emsp;[绑定资产单元](../asset_units.md#asset-unit-binding)的 `total_return_swap` 若有对应分钟数据，则改用其内部同方向盈亏。<br>&emsp;产品首日除以 `abs(net_cash_in)`，之后除以 `abs(昨日 total_equity)`；<br>&emsp;除法零分母分支为 0。|名称含「权益」，但集合包含债券、回购和衍生品，不等于 `equity_net_exposure` 的筛选条件。<br>&emsp;内部分钟盈亏不是当前单张报表全部提供的输入。|
|<a id="net-cash-in"></a>`net_cash_in`|当日净投入|number|当日从零开始：流水 `cash_in` 加 `settlement_amount`，`cash_out` 减 `settlement_amount`；`custodian_transfer_in` 加 `quantity×price`，`custodian_transfer_out` 减 `quantity×price`。<br>&emsp;再加当日托管 `subscription_fund_received.amount`，减支付日 `date=t` 的 `redemption_paid.amount` 和 `product_dividend_paid.amount`。|不按全部买卖现金流求和；<br>&emsp;不是现金余额变化。<br>&emsp;托管赎回/分红的 effective_date 与 date 可能不同：此字段按支付日，而 daily_pnl 的报告现金调整按生效日。|
|<a id="equity-net-exposure"></a>`equity_net_exposure`|权益净敞口|number / null|从 `P` 保留 `asset_class` 为 [权益净敞口直接纳入品种（4 类）](#equity-direct-classes)，或为 [五类基金品种（5 类）](#equity-fund-classes) 且代码被识别为权益基金的持仓，累加带符号的 `market_value`。<br>&emsp;权益基金代码取 RQData [fund.all_instruments()](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-all_instruments) 中 `fund_type` 为 stock/hybrid/stock_index 的基金，另含 [fund.get_instrument_category](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_instrument_category)(category_type="universe") 中 `category=fund_of_etf` 的基金；<br>&emsp;有 exchange 时给代码加交易所后缀。|不按基金名称猜测类别；<br>&emsp;此指标不把[绑定](../asset_units.md#asset-unit-binding)收益互换替换成单元内权益敞口。<br>&emsp;期货累加的是名义市值，不是保证金。|
|`cn_stock_market_value`|A 股持仓市值|number / null|从 `P` 筛选 `asset_class=stock` 且 `order_book_id` 后缀为 `.XSHG`、`.XSHE`，累加 `market_value×s`；<br>&emsp;市值本身为 `fair_value×quantity×s`，所以正常数量下此项累加的是不区分多空的正金额。|不穿透收益互换；<br>&emsp;不同于沪/深分项的带符号市值，不能假设本表 `cn_sh_stock_market_value` 与 `cn_sz_stock_market_value` 字段之和等于 `cn_stock_market_value`。|
|`cn_sh_stock_market_value`|沪市 A 股持仓市值|number / null|从 `P` 筛选 `asset_class=stock` 且 `order_book_id` 以 `.XSHG` 结尾，累加 `market_value`，不再乘方向因子。<br>&emsp;遇到 `total_return_swap` 且有[绑定资产单元](../asset_units.md#asset-unit-binding)的非空持仓集合时，改遍历该单元持仓、用相同股票和后缀条件筛选累加；<br>&emsp;不再把收益互换本身加一次。|需同日资产单元绑定关系与实际持仓；<br>&emsp;仅当前不穿透报表可能无法复算。|
|`cn_sz_stock_market_value`|深市 A 股持仓市值|number / null|从 `P` 筛选 `asset_class=stock` 且 `order_book_id` 以 `.XSHE` 结尾，累加 `market_value`，不再乘方向因子。<br>&emsp;遇到 `total_return_swap` 且有[绑定资产单元](../asset_units.md#asset-unit-binding)的非空持仓集合时，改遍历该单元持仓、用相同股票和后缀条件筛选累加；<br>&emsp;不再把收益互换本身加一次。|需同日资产单元绑定关系与实际持仓；<br>&emsp;仅当前不穿透报表可能无法复算。|
|`hk_stock_market_value`|港股持仓市值|number / null|从 `P` 筛选 `asset_class=stock` 且 `order_book_id` 后缀为 `.XHKG`，累加 `market_value×s`；<br>&emsp;市值本身为 `fair_value×quantity×s`，所以正常数量下此项累加的是不区分多空的正金额。|不穿透收益互换；<br>&emsp;不同于沪/深分项的带符号市值，不能假设本表 `cn_sh_stock_market_value` 与 `cn_sz_stock_market_value` 字段之和等于 `cn_stock_market_value`。|
|<a id="cash"></a>`cash`|现金类资产金额|number / null|从 `P` 筛选 `asset_class` 属于 [现金类资产统计品种（11 类）](#cash-classes)，累加各仓 `market_value`。<br>&emsp;前 10 类 `market_value=quantity`；<br>&emsp;货币基金按 `fair_value×quantity×s`。|11 类精确集合，既不是活期可用资金，也不是盈亏排除的 21 类。<br>&emsp;货币基金虽计入 cash，仍计算逐仓盈亏。|
|<a id="total-risk-market-value"></a>`total_risk_market_value`|风险资产总市值|number|遍历 `P`；`total_return_swap` 有[绑定资产单元](../asset_units.md#asset-unit-binding)且该单元有持仓时，用其内部持仓代替该收益互换。<br>&emsp;筛选 `asset_class` 属于 [风险资产统计品种（23 类）](#risk-classes)，并排除 `order_book_id` 在 RQData [fund.all_instruments()](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-all_instruments) 的货币基金代码集合中（含对应场内后缀代码）的记录。<br>&emsp;最终累加 `abs(x.market_value)`。|上述 *_sterilisation 为计算分类映射中保留的字符串；<br>&emsp;普通期货平衡项在 extras 中，不另外构造一条持仓。<br>&emsp;缺少单元持仓或货基分类数据时不能用“全部证券”替代筛选。|
|<a id="net-risk-market-value"></a>`net_risk_market_value`|风险资产净市值|number|使用本表 `total_risk_market_value` 字段中完全相同的逐仓替换、asset_class 集合和货基排除条件，但最终累加 `x.market_value`，不取绝对值。|多空抵消后的名义净敞口；<br>&emsp;不等于 total_equity 或顶层 market_value。|
|<a id="long-market-value"></a>`long_market_value`|多头名义市值|number|遍历当前持仓，只取 `asset_class` 属于 [风险资产统计品种（23 类）](#risk-classes) 的持仓，累加 `market_value >= 0` 的部分，不取绝对值。|恒返回；不排除货币基金，所以通常大于 `total_risk_market_value`，两者差额就是货基市值；不受 `fields` 过滤影响。|
|<a id="short-market-value"></a>`short_market_value`|空头名义市值|number|使用本表 `long_market_value` 字段完全相同的筛选，累加其中 `market_value < 0` 的部分（保留负号，不取绝对值）。|恒返回；无空头风险持仓时为 0；应付、正回购等负债科目不在此项。|
|<a id="risk-exposure"></a>`risk_exposure`|风险资产总敞口|number / null|`total_risk_market_value / total_equity`，分母为零或缺失时返回空值。|由参数选择：省略 `fields` 时恒返回；传了 `fields` 时必须显式包含 `risk_exposure`、`net_risk_exposure`、`long_leverage`、`long_net_risk_exposure` 之一，这四个字段才一起返回。分子是毛敞口（风险类持仓市值绝对值之和，排除货基）。|
|<a id="net-risk-exposure"></a>`net_risk_exposure`|风险资产净敞口|number / null|`net_risk_market_value / total_equity`，分母为零或缺失时返回空值。|由参数选择：出现条件同 `risk_exposure`；与它取值相同表示当日没有空头或负市值的风险持仓。|
|<a id="long-leverage"></a>`long_leverage`|多头股票市值占净资产比|number / null|只取 `asset_class=stock` 且 `direction=long` 的持仓，累加 `market_value` 后除以 `total_equity`，分母为零或缺失时返回空值。|由参数选择：出现条件同 `risk_exposure`；不含可转债、基金、期货、期权，也**不是**资产杠杆 `total_assets/total_equity`（后者是[指标序列](../analytics/metrics.md#series-inputs)里的 `leverage_ratio`）。|
|<a id="long-net-risk-exposure"></a>`long_net_risk_exposure`|多头净风险敞口|number / null|对 stock、stock_index_futures、commodity_futures、commodity_option、stock_index_option、otc_futures、otc_option 按方向分别累加市值，再分段取值：多空都为 0 返回 `0`；空头为 0 且多头非 0 返回 `1`；多头为 0 且空头非 0 返回 `−1`；否则 `long/abs(short) − 1`。|由参数选择：出现条件同 `risk_exposure`；取值可越出 [−1,1]，`1` 表示只有多头。|
|<a id="contribute-returns-denominator"></a>`contribute_returns_denominator`|收益贡献分母|number / null|产品组当日收益率与成员[收益贡献](../analytics/portfolio_analysis.md)的分母：聚合组为 `abs(前日成员净资产合计 + 当日出入金)`，无前日截面时用 `Σ total_equity/(1+daily_returns)` 反推；加权组在再平衡日或起始日取组可用净资产，平日为 `Σ(前日单位净值 × 当日持有份额)`。|由数据决定：只有产品组响应带该键，单产品估值没有；任一成员当日收益率缺失时为空值，不能用其它字段补算。|
|<a id="buy-amount"></a>`buy_amount`|买入金额|number|普通估值：`stock_buy_amount+bond_buy_amount+fund_buy_amount`，每个分项的流水筛选及逐笔公式见本表对应字段。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)后额外倒推：以 `(asset_class,order_book_id,direction)` 对齐当日与昨日持仓，缺仓当 0；<br>&emsp;仅取 stock、convertible_bond 和 [五类基金品种（5 类）](#equity-fund-classes)。<br>&emsp;令 `PositionCost=quantity×avg_price_include_fee`；<br>&emsp;数量增加时把 `PositionCost[当日] − PositionCost[上一估值日]` 加入倒推买入，其余把 `PositionCost[上一估值日] − PositionCost[当日]` 加入倒推卖出。<br>&emsp;最后取 `max(流水三分项买入合计,倒推买入金额)`。|倒推集合实际不含普通 bond，且只改变总额、不改三个分项；<br>&emsp;因此[估值表覆盖](../reconciliation.md#valuation-report-overwrite)后总额不一定等于三分项和。<br>&emsp; `analytics.series` 重新合计三类流水分项，可能不同。<br>&emsp;覆盖日还会按持仓数量差额写出[轧差推导影子流水](../reconciliation.md#netting-derived-shadow-trades)，那是逐条流水记录，与本行倒推成交额不是同一结果，也不要求相等。|
|<a id="sell-amount"></a>`sell_amount`|卖出金额|number|普通估值：`stock_sell_amount+bond_sell_amount+fund_sell_amount`。<br>&emsp;[估值表覆盖](../reconciliation.md#valuation-report-overwrite)：按本表 `buy_amount` 字段中的持仓对齐与倒推方法，取 `max(流水三分项卖出合计,倒推卖出金额)`。|cb_to_stock 不在买卖交易类型集合，不能仅因使用 settlement_amount 就纳入成交额。<br>&emsp; `analytics.series` 重新合计三类流水分项，可能不同。|
|`stock_buy_amount`|股票买入金额|number|遍历当日已应用的流水，筛选 `asset_class` 属于 `stock`、`transaction_type` 属于 `buy`、`buy_to_return`、`subscribe`、`buy_on_margin`。<br>&emsp;每笔累加 `quantity × price × exchange_rate + (commission + tax + other_fees)`。|这是流水合计，不从当前净持仓数量倒推；<br>&emsp;基金分项的本地集合不含 reits/money_market_fund。|
|`stock_sell_amount`|股票卖出金额|number|遍历当日已应用的流水，筛选 `asset_class` 属于 `stock`、`transaction_type` 属于 `sell`、`short_sell`、`redeem`、`sell_to_repay`、`convertible_redemption`、`convertible_sell_back`。<br>&emsp;其中 convertible_redemption/convertible_sell_back 累加 settlement_amount；<br>&emsp;其余累加 `quantity × price × exchange_rate − (commission + tax + other_fees)`。|这是流水合计，不从当前净持仓数量倒推；<br>&emsp;基金分项的本地集合不含 reits/money_market_fund。|
|`bond_buy_amount`|债券买入金额|number|遍历当日已应用的流水，筛选 `asset_class` 属于 `bond`、`convertible_bond`、`transaction_type` 属于 `buy`、`buy_to_return`、`subscribe`、`buy_on_margin`。<br>&emsp;每笔累加 `quantity × price × exchange_rate + (commission + tax + other_fees)`。|这是流水合计，不从当前净持仓数量倒推；<br>&emsp;基金分项的本地集合不含 reits/money_market_fund。|
|`bond_sell_amount`|债券卖出金额|number|遍历当日已应用的流水，筛选 `asset_class` 属于 `bond`、`convertible_bond`、`transaction_type` 属于 `sell`、`short_sell`、`redeem`、`sell_to_repay`、`convertible_redemption`、`convertible_sell_back`。<br>&emsp;其中 convertible_redemption/convertible_sell_back 累加 settlement_amount；<br>&emsp;其余累加 `quantity × price × exchange_rate − (commission + tax + other_fees)`。|这是流水合计，不从当前净持仓数量倒推；<br>&emsp;基金分项的本地集合不含 reits/money_market_fund。|
|`fund_buy_amount`|基金买入金额|number|遍历当日已应用的流水，筛选 `asset_class` 属于 [五类基金品种（5 类）](#equity-fund-classes)、`transaction_type` 属于 `buy`、`buy_to_return`、`subscribe`、`buy_on_margin`。<br>&emsp;每笔累加 `quantity × price × exchange_rate + (commission + tax + other_fees)`。|这是流水合计，不从当前净持仓数量倒推；<br>&emsp;基金分项的本地集合不含 reits/money_market_fund。|
|`fund_sell_amount`|基金卖出金额|number|遍历当日已应用的流水，筛选 `asset_class` 属于 [五类基金品种（5 类）](#equity-fund-classes)、`transaction_type` 属于 `sell`、`short_sell`、`redeem`、`sell_to_repay`、`convertible_redemption`、`convertible_sell_back`。<br>&emsp;其中 convertible_redemption/convertible_sell_back 累加 settlement_amount；<br>&emsp;其余累加 `quantity × price × exchange_rate − (commission + tax + other_fees)`。|这是流水合计，不从当前净持仓数量倒推；<br>&emsp;基金分项的本地集合不含 reits/money_market_fund。|
|`update_time`|数据更新时间|string / null|服务端因流水等输入变化重算该头寸报表时记录的时间。|与 positions[].update_time 的行情 tick 时间不同。|
|`all_futures_options_has_settlement`|期货期权是否全部已结算|boolean / null|筛选当前计算数据提供器支持的期货/期权持仓；<br>&emsp;有记录时对其 `has_settlement` 取 all，无记录返回 null；<br>&emsp;必要时包含传入的资产单元内部持仓。|是否取得行情结算价，不是资金已清算。|
|`id`|记录 ID|string / null|服务端记录 ID|—|
|`share_values`|分类份额估值|object（string 键 → object） / null|有效分类配置产生的分类份额估值字典，i 为分类名称。<br>&emsp;`Units[分类i]`：本表 `share_values.{份额}.units`，分类份额。<br>&emsp;`Equity[分类i]`：本表 `share_values.{份额}.total_equity`，分类净资产。<br>&emsp;`NAV[分类i]`：本表 `share_values.{份额}.unit_net_value`，分类单位净值。<br>&emsp;`NetFlow[分类i]`：当日分类托管净申赎金额。<br>&emsp;`FeeDelta[分类i]`：分类管理费/业绩报酬应付变化。<br>&emsp;`EquityAdjust[分类i]`：分类净资产调整。<br>&emsp;`Weight[分类i]`：分类分配权重，公式如下。<br>&emsp;`Weight[分类i] = (昨日 Equity[分类i] + NetFlow[分类i]) / (昨日母产品 total_equity + sum(NetFlow[分类i]))`，零分母 Weight[分类i]=0。|无有效上下文不生成分类；<br>&emsp;报告仅覆盖已存在分类的五个字段，null 不覆盖、显式 0 覆盖，各字段独立。<br>&emsp;所有分类查询字段只读，报告可按上传规则提交。|
|<a id="productsharevalue"></a>`share_values.{份额}.units`|分类份额|number / null|普通估值：`昨日 Units[分类i] + 当日分类净申购份额`，无昨日份额按 0。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)：已有该分类结果时，用报告同字段非空值覆盖。|净申购份额来自选定策略的分类份额事件，不直接等于净申赎金额。|
|`share_values.{份额}.total_equity`|分类净资产|number / null|普通估值：`(母产品 total_equity + sum(FeeDelta[分类i])) × Weight[分类i] - FeeDelta[分类i] + EquityAdjust[分类i]`；`Units[分类i] = 0` 时为 0。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)：已有该分类结果时，用报告同字段非空值覆盖。<br>&emsp;变量与 Weight[分类i] 在本表 `share_values` 字段中定义。<br>&emsp;NetFlow[分类i] 按分类托管申购到账减生效日赎回；<br>&emsp;EquityAdjust[分类i] 来自 product_share_equity_adjusted 事件；<br>&emsp;FeeDelta[分类i] 包含分类费用和科目调整。|有效分类、生效日期、昨日分类状态、申赎事件、费用和科目调整共同决定；<br>&emsp;分类管理费原式见本表 `positions[].extras.product_share_quantities.{份额}` 字段。|
|`share_values.{份额}.unit_net_value`|分类单位净值|number / null|普通估值：`Equity[分类i] / Units[分类i]`；`Units[分类i] = 0` 时为 0。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)：已有该分类结果时，用报告同字段非空值覆盖。|与母产品零份额返回空值的分支不同；[估值表覆盖](../reconciliation.md#valuation-report-overwrite)五个字段相互独立，不能假设覆盖后必然仍满足此除法。|
|`share_values.{份额}.acc_unit_net_value`|分类累计单位净值|number / null|普通估值：累计分红模式分别舍入 `NAV[分类i]` 和分类累计每份分红后相加再舍入；<br>&emsp;昨日净值模式用 `昨日分类累计净值 + 当日分类每份分红 + (NAV[分类i]-昨日 NAV[分类i])`，无昨日单位净值时差额取 `NAV[分类i]`，求和跳过空值；`Units[分类i] = 0` 时为 0。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)：已有该分类结果时，用报告同字段非空值覆盖。|累计净值口径与母产品设置一致，不是收益率连乘。|
|`share_values.{份额}.acc_unit_dividend`|分类累计每份分红|number / null|普通估值：`昨日分类累计每份分红 + 母产品当日分红金额 × Weight[分类i] / Units[分类i]`；<br>&emsp;无旧值按 0，`Units[分类i] = 0` 时保留旧值。<br>&emsp;[估值表估值](../reconciliation.md#valuation-report-overwrite)：已有该分类结果时，用报告同字段非空值覆盖。|指产品向份额持有人分红，不是持仓股票分红；<br>&emsp;全部分类字段在头寸查询中只读。|
|<a id="assetunitbalance"></a>`asset_unit_id`|资产单元 ID|string / null|归属资产单元 ID|仅资产单元结果。|
|<a id="balancedailysummary"></a>`stock_dividend_amount`|股票分红到账金额|number|每日摘要：从 `P` 筛选 `asset_class=stock` 且 `direction=long`，累加 `daily_payment_amount`；<br>&emsp;金额非有限时报错。<br>&emsp;逐仓金额如何从权益源数据形成，见本表 `positions[].daily_payment_amount` 字段。|不含基金分红或产品分红；<br>&emsp;字段名虽称到账金额，但直接使用的 daily_payment_amount 可在除息日形成应收、尚未到账，不能据此确认现金已到账。|

<a id="settlement"></a>

### 「结算」在本页与流水里的四种含义

读到「结算」先按下面四种之一理解，它们不互相替代：

|出现位置|含义|依据|
|---|---|---|
|期货/期权行情与估值|是否已取到**结算价**（行情 `settlement`），与资金是否清算无关|`positions[].has_settlement`；根级/组级汇总看 `all_futures_options_has_settlement`|
|流水金额|现金类流水的**结算金额** `settlement_amount`|见[交易类型的必要字段](../trades.md#transaction-type-write-rules)|
|文件导入|**结算文件**＝日终结算流水（同日已有结算流水时拒绝日内行）|见[上传日终结算流水](../trades.md#upload-settlement-file)|
|概览与实时|**日终估值是否就位**：`previous_summary` 只给上一交易日的已就位概览，实时截面可能尚未结算|见[上一交易日概览](#previous-summary)|

同时区分三个「未」：`pending_valuation` 是估值未就绪，`has_settlement` 是有无结算价，流水是否生效由 `transaction` 状态决定——三者不可互相推断。

<a id="calculation-asset-classes"></a>

## 计算使用的资产分类集合

以下逐项列出本表公式引用的 `asset_class` 值；只抽出枚举清单，纳入、排除、方向、穿透和求和规则仍在对应字段中。不同清单不能互相替代。中文含义见[资产品种与会计科目](others.md#assetclass)。

<a id="market-value-exclusions"></a>

### 持仓市值排除科目

- `other_interest_receivable`
- `dividend_receivable`
- `subscription_receivable`
- `other_receivable`
- `other_interest_payable`
- `management_fee_payable`
- `custodian_fee_payable`
- `operation_fee_payable`
- `sales_and_service_fee_payable`
- `performance_pay_payable`
- `tax_payable`
- `other_payable`

<a id="asset-securities"></a>

### 按多空计入资产负债的证券

- `stock`
- `etf_fund`
- `lof_fund`
- `closed_end_fund`
- `open_end_fund`
- `reits`
- `money_market_fund`
- `other_fund`
- `bond`
- `convertible_bond`

<a id="asset-futures"></a>

### 期货品种

- `commodity_futures`
- `stock_index_futures`
- `interest_rate_futures`
- `otc_futures`

<a id="asset-signed-market-value"></a>

### 按带符号市值计入资产的品种

- `commodity_option`
- `stock_index_option`
- `otc_option`
- `total_return_swap`
- `interest_return_swap`
- `other_derivatives`
- `reverse_repo`

<a id="liability-accounts"></a>

### 数量即负债金额的科目

- `repo_accrued_interest`
- `cash_debt`
- `other_interest_payable`
- `management_fee_payable`
- `sales_and_service_fee_payable`
- `custodian_fee_payable`
- `performance_pay_payable`
- `operation_fee_payable`
- `tax_payable`
- `other_payable`
- `other_liability`

<a id="pnl-exclusions"></a>

### 逐仓盈亏排除科目

- `repo_accrued_interest`
- `reverse_repo_accrued_interest`
- `current_deposit`
- `reservation_deposit`
- `refundable_deposit`
- `securities_settlement_accounts`
- `dividend_receivable`
- `other_interest_receivable`
- `subscription_receivable`
- `other_receivable`
- `other_asset`
- `cash_debt`
- `other_interest_payable`
- `management_fee_payable`
- `sales_and_service_fee_payable`
- `custodian_fee_payable`
- `performance_pay_payable`
- `operation_fee_payable`
- `tax_payable`
- `other_payable`
- `other_liability`

<a id="intraday-equity-classes"></a>

### 日内权益多空收益品种

- `stock`
- `convertible_bond`
- `bond`
- `etf_fund`
- `lof_fund`
- `open_end_fund`
- `closed_end_fund`
- `reits`
- `money_market_fund`
- `other_fund`
- `repo`
- `reverse_repo`
- `commodity_option`
- `stock_index_option`
- `otc_option`
- `commodity_futures`
- `stock_index_futures`
- `interest_rate_futures`
- `otc_futures`
- `total_return_swap`
- `interest_return_swap`

<a id="equity-direct-classes"></a>

### 权益净敞口直接纳入品种

- `stock`
- `stock_index_futures`
- `stock_index_option`
- `reits`

<a id="equity-fund-classes"></a>

### 五类基金品种

- `etf_fund`
- `lof_fund`
- `open_end_fund`
- `closed_end_fund`
- `other_fund`

<a id="cash-classes"></a>

### 现金类资产统计品种

- `current_deposit`
- `reservation_deposit`
- `refundable_deposit`
- `securities_settlement_accounts`
- `dividend_receivable`
- `other_interest_receivable`
- `subscription_receivable`
- `other_receivable`
- `other_asset`
- `reverse_repo_accrued_interest`
- `money_market_fund`

前 10 类是数量直接代表金额的存款/应收科目；最后的 `money_market_fund` 是按价格和份额估值的货币基金。

<a id="risk-classes"></a>

### 风险资产统计品种

- `bond`
- `closed_end_fund`
- `commodity_futures`
- `commodity_futures_sterilisation`
- `commodity_option`
- `convertible_bond`
- `etf_fund`
- `interest_rate_futures`
- `interest_rate_futures_sterilisation`
- `interest_return_swap`
- `lof_fund`
- `open_end_fund`
- `otc_futures`
- `otc_futures_sterilisation`
- `otc_option`
- `other_derivatives`
- `other_fund`
- `reits`
- `stock`
- `stock_index_futures`
- `stock_index_futures_sterilisation`
- `stock_index_option`
- `total_return_swap`

`*_sterilisation` 是计算分类映射保留的字符串；普通期货平衡项仍在 `extras` 中，不据此另造持仓。

<a id="previous-summary"></a>

## 上一交易日概览

`balances.previous_summary` 与 `balances.previous_summaries` 返回的字段与单日报表顶层字段同名同义，计算口径见上方主表；区别是概览不包含 `positions`，并按服务端规则附带基准收益与超额收益字段。

批量结果的键是资源 ID，`error_messages` 也以资源 ID 为键记录失败原因；估值未就位的资源既不出现也不记入 `error_messages`。字段缺失或为 `null` 仍不等于 `0`，不能据此推断零头寸。

## 枚举取值

<a id="direction"></a>

### 多空方向

|值|含义|
|---|---|
|`long`|多头|
|`short`|空头|

<a id="currency"></a>

### 币种

|值|含义|
|---|---|
|`CNY`|人民币|
|`HKD`|港币|
