# products 字段字典

产品是独立估值边界；账户嵌套在产品中，分类份额是同一母产品的份额类别。产品组用于组合分析，不是写入广播目标。

本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。

- 设置数据源、账户、费用或估值口径：先按[产品操作](../products.md)选择 `rqamsh.products.create/update`，再查本页产品与嵌套字段。
- 配置多产品组合：按[产品组操作](../product_groups.md)使用 `rqamsh.product_groups.create/update`，查本页产品组字段；成员使用产品 ID。
- 核对修改：用相应 `get` 读取名称、日期及配置。修改成功不等于估值重算完成，计算结果另按[头寸报表查询](../balances.md)核对。
- 本页只列举字段与业务含义；创建与修改的必填、条件与省略规则见[产品操作](../products.md)与[产品组操作](../product_groups.md)，不在本页重复。
- 标注 `只读` 的字段由服务端维护：可作为查询结果读取，不作为写入输入。
- `{份额}`、`{product_id}` 等花括号键是动态字典键，不是实际 JSON 键；`{份额}` 代入单个英文字母，`{product_id}` 代入成员产品 ID。

不要依赖本页未明确承诺的缺省值。

表中使用 JSON 类型：日期为 `YYYY-MM-DD` 字符串，日期时间为字符串，ID 为字符串，枚举传字符串值。`/ null` 表示需能解释空值，不代表写入时允许省略或传 `null`；输入必填项和省略行为按对应操作规则执行。查询可能只返回部分字段，缺失或 `null` 均不等于 `0`、`false` 或空数组，不能自行补值参与估值。金额不自动缩放，比例 `0.01` 表示 `1%`；未声明单位的数字不要猜测为万元或百分数。

<a id="product"></a>

## 产品配置

产品配置。字段路径中的点号表示嵌套层级，`accounts[]` 表示数组元素；`benchmark` 对象由产品与产品组共用。创建与更新要求见[产品操作](../products.md)。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`name`|产品名称|string|—|产品或产品组名称；资源选择器按此名称消歧|—|
|`report_name`|报告名称|string|—|对外展示与导出文件名使用的名称：周报文件名取它，其他导出在 `name` 为空时兜底；不参与估值计算，与估值报告内容无关|—|
|<a id="data-source"></a>`data_source`|数据来源|string（枚举）|—|数据源类型：`trade` 交易流水、`valuation_report` 估值报告、`trade_and_valuation_report` 混合；决定可导入数据与估值起点（纯估值报告源由报告建立起点，不能上传交易流水）。枚举[产品数据源](#productdatasource)|—|
|`start_date`|起始日期|string|YYYY-MM-DD|产品估值与收益序列的起点；省略日期的指标与报告查询以起始日为默认起点，`recompute` 省略时从此重算；起始日收益率按 `AccNAV[当日]−1` 口径（见[头寸 daily_returns](balances.md#daily-returns)）|—|
|`trading_start_date`|交易起始日期|string|YYYY-MM-DD|交易流水相关默认起点：按日期删除流水省略日期时从交易起始日算起，报告起始受其限制；指标指增特殊口径以它为基点（见[净值与收益指标](../analytics/metrics.md#indicators-returns)）|—|
|`valuation_start_point`|估值计算起点|string / null|YYYY-MM-DD|混合数据源的估值计算起点，由服务端维护；创建与修改不提交|只读；服务端取它与 `start_date`、`closing_date`、`share_calc_start_date` 中的最早日期作为重算与估值起点，并参与起始日变更校验|
|`investment_category`|投资类别|string（枚举）|—|产品投资类别分类标签；取值与中文含义（权益类、固收类等 12 项）见[产品投资类别](#productinvestmentcategory)|—|
|`strategy_category`|策略类别|string（枚举）|—|产品策略类别；`index_enhanced` 会触发指标的指增特殊口径（见[净值与收益指标](../analytics/metrics.md#indicators-returns)），取值见[投资策略类别](#strategycategory)|—|
|<a id="productbenchmark"></a>`benchmark`|业绩比较基准|object|—|产品业绩比较基准，供指标比较与基准序列使用；基准行情见[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)|—|
|`benchmark.type`|基准种类|string（枚举）|—|基准种类：`index` 指数基准（配合指数代码，[指数基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)可校验）、`customized_index` 自定义基准（配合自定义基准 ID）。枚举[基准类型](#productbenchmarktype)|—|
|`benchmark.id`|基准标识|string|—|index 时为指数 order_book_id（行情由[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)取），customized_index 时为自定义基准 ID|与 benchmark.type 一致|
|`calendar`|日历类型|string（枚举）|—|估值日历：`exchange` 交易所日历、`natural` 自然日；决定估值与指标序列的日期集合（指标整理时交易日产品只保留交易所日历，自然日产品保留自然日）；交易所日历的交易日序列见[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)。枚举[估值日历](#calendartype)|—|
|<a id="productaccount"></a>`accounts`|产品账户列表|array（object 元素）|—|产品嵌套交易/托管账户；无独立全局 ID|—|
|`accounts[].name`|账户名称|string|—|产品内账户名称；流水 account 引用此值，不参与独立 resource 选择|—|
|`accounts[].is_custodian`|托管账户标记|boolean|—|是否托管账户|—|
|`accounts[].account_number`|账户号码|string|—|券商/托管账户号码|—|
|`accounts[].broker`|账户通道/券商|string（枚举）|—|账户所属券商/通道标识；完整通道清单见[账户券商与通道](#accountbroker)|—|
|<a id="feesettings"></a>`fee_settings`|费用年费率配置|object（费用枚举键 → number）|小数年费率|产品费用年费率配置，按费用枚举键映射；枚举[产品费用类别](#productcosttype)|—|
|`fee_settings.management_fee`|管理费年费率|number|小数年费率|管理费年费率；有生效分类份额时按各份额 `昨日分类净资产×(产品管理费率+该份额管理费率)/365` 逐份额取分计提，形成 `management_fee_payable` 应付科目与分类明细；没有生效分类份额时按 `昨日产品净资产×产品管理费率/365` 计入母产品 `management_fee_payable`，不取分、不产生分类明细（见[头寸费用应付字段](balances.md#payablepositionextra)）|—|
|`fee_settings.custodian_fee`|托管费年费率|number|小数年费率|托管费年费率；作为自动年费按 `昨日产品净资产×年费率/365` 计提，形成 `custodian_fee_payable` 应付科目（见[头寸费用应付字段](balances.md#payablepositionextra)）|—|
|`fee_settings.sales_and_service_fee`|销售服务费年费率|number|小数年费率|销售服务费年费率；作为自动年费按 `昨日产品净资产×年费率/365` 计提，形成 `sales_and_service_fee_payable` 应付科目（见[头寸费用应付字段](balances.md#payablepositionextra)）|—|
|`fee_settings.operation_fee`|运营费年费率|number|小数年费率|运营费年费率；作为自动年费按 `昨日产品净资产×年费率/365` 计提，形成 `operation_fee_payable` 应付科目（见[头寸费用应付字段](balances.md#payablepositionextra)）|—|
|`fee_settings.performance_pay`|业绩报酬费率|number|小数比例|业绩报酬费率；不套用固定年费率，按业绩计算/事件输入计提，形成 `performance_pay_payable` 应付科目（见[头寸费用应付字段](balances.md#payablepositionextra)）|—|
|`user_id`|创建/所属用户 ID|number（整数）|—|由请求身份确定|只读|
|`workspace_id`|所属工作空间 ID|string|—|由请求身份确定|只读|
|`realtime_period_type`|实时监控时段配置|string（枚举）|—|实时监控时段：`daytime` 仅白天 09:30 - 15:00、`valuation_day` 估值表日 21:00 - 15:00（+1）。枚举[实时监控时段](#realtimeperiodtype)|—|
|<a id="valuationsettings"></a>`valuation_settings`|估值口径配置|object / null|—|估值价格及累计净值口径配置|—|
|`valuation_settings.etf`|ETF 估值价格口径|string（枚举） / null|—|ETF 估值价格口径：`close` 当日收盘价、`iopv` 当日净值（IOPV）；行情见[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)，`iopv` 字段见[合约行情返回字段](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-return)。枚举[ETF 估值价格](#etfvaluationaccordingfield)|—|
|`valuation_settings.fut_opt`|期货期权估值价格口径|string（枚举） / null|—|期货期权估值价格口径：`close` 当日收盘价、`settlement` 当日结算价；行情见[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)。枚举[期货期权估值价格](#futoptvaluationaccordingfield)|—|
|`valuation_settings.acc_net_value`|累计净值口径|string（枚举） / null|—|累计单位净值口径：`last_unit_net_value` 按昨日累计净值递推、`acc_unit_dividend` 按起始日至今累计单位份额分红。枚举[累计净值口径](#accunitvaluevaluationaccordingfield)|—|
|<a id="exchangeratesettings"></a>`exchange_rate_settings`|汇率配置|object / null|—|港币折人民币汇率来源配置|—|
|`exchange_rate_settings.HKD`|港币汇率来源|string（枚举） / null|—|港币折人民币汇率来源（港股汇率见[港币汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk)）：`sh` 沪港通中间价、`sz` 深港通中间价。枚举[港币汇率来源](#exchangeratetype)|—|
|`label`|产品标签|string（枚举）|—|产品标签：`live` 实盘、`paper` 模拟、`paper_trading` 模拟交易。枚举[产品标签](#productlabel)|—|
|<a id="auto-equity"></a>`auto_equity`|自动处理权益事件|boolean / null|—|已废弃：名义上控制是否自动处理权益事件，实际不生效|已废弃——估值引擎与实时计算都接收该开关但不读取，自动权益流水由标的权益数据与持仓驱动生成；写入该字段仍会触发一次产品重算。实测口径见[自动权益修正](../trades.md#create_auto_balance_override)|
|<a id="auto-overwrite"></a>`auto_overwrite`|自动覆盖计算结果|boolean / null|—|是否自动采用后续导入报告调整估值；适用数据源、历史影响及初始化例外见[估值表覆盖设置](../reconciliation.md#valuation-report-overwrite-setting)|—|
|<a id="unit-policy"></a>`unit_policy`|份额策略|string（枚举） / null|—|份额策略：`auto_prev_unit_net_value` 自动份额（按前一日净值申赎）、`manual` 手工修改份额；决定份额事件来源（见[头寸份额字段](balances.md#balance-inputs)）。枚举[份额调整方式](#productunitpolicy)|—|
|`full_name`|产品全称|string / null|—|产品全称，用于展示识别；创建/修改校验长度上限；不参与估值计算，也不在数据库唯一约束内（同工作空间唯一约束覆盖产品名称、账户名称、基金代码）|—|
|`create_time`|创建时间|string / null|日期时间|业务对象创建时间|只读|
|`fund_code`|基金备案/产品代码|string / null|—|基金备案/产品代码|—|
|`manager`|管理人|string / null|—|管理人|—|
|`invest_advisor`|投资顾问|string / null|—|投资顾问|—|
|`invest_manager`|投资经理|string / null|—|投资经理|—|
|`operating_expenses_md`|运营费用说明|string / null|—|运营费用说明 Markdown|—|
|<a id="maturity-date"></a>`maturity_date`|到期日期|string / null|YYYY-MM-DD|产品到期日期；指标与报告查询的截止日期受其限制|—|
|`closing_date`|封账日期|string / null|YYYY-MM-DD|产品封账日期；封账日前输入的修改操作受封账限制|只读|
|`product_state`|产品状态|string（枚举）|—|产品状态：`normal` 正常、`terminated` 已终止。枚举[产品状态](#productstate)|只读|
|`description`|对象说明|string|—|对象说明|—|
|`id`|记录 ID|string / null|—|服务端记录 ID|只读|
|<a id="productsharesettings"></a>`shares`|分类份额配置|object（string 键 → object） / null|—|分类份额配置，键为单个英文字母|生效日期晚于当日的份额不参与当日计算|
|`shares.{份额}.effective_date`|分类份额生效日期|string|YYYY-MM-DD|分类份额配置生效日期|—|
|`shares.{份额}.management_fee`|管理费年费率|number|小数比例|分类管理费年费率；与产品管理费率相加参与每日分类管理费计提（见[头寸费用应付字段](balances.md#payablepositionextra)）|—|
|`shares.{份额}.performance_pay`|业绩报酬费率|number|小数比例|分类业绩报酬费率；参与分类业绩报酬计提（见[头寸费用应付字段](balances.md#payablepositionextra)）|—|
|`shares.{份额}.subscription_fee`|申购费率|number|小数比例|申购费率|—|
|`shares.{份额}.redemption_fee`|赎回费率|number|小数比例|赎回费率|—|

分类份额费率必须非负。

<a id="productgroup"></a>

## 产品组配置

产品组配置。必填项和成员权限要求见[产品组操作](../product_groups.md)。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`name`|产品组名称|string|—|产品或产品组名称；资源选择器按此名称消歧|—|
|`report_name`|报告名称|string|—|对外展示与导出文件名使用的名称：周报文件名取它，其他导出在 `name` 为空时兜底；不参与估值计算，与估值报告内容无关|—|
|<a id="group-product-ids"></a>`product_ids`|成员产品 ID 列表|array（string 元素）|—|产品组成员产品 ID 列表|—|
|`benchmark`|业绩比较基准|object|—|产品业绩比较基准（与产品共用对象）；<br>&emsp;展开见 [业绩比较基准](products.md#productbenchmark)|—|
|`description`|对象说明|string|—|对象说明|—|
|`create_time`|创建时间|string|日期时间|业务对象创建时间|只读|
|`user_id`|创建/所属用户 ID|number（整数）|—|由请求身份确定|只读|
|`workspace_id`|所属工作空间 ID|string|—|由请求身份确定|只读|
|`trading_start_date`|交易起始日期|string|YYYY-MM-DD|组交易起始日；不能早于组估值起始日 `start_date`；沿用产品的交易起始日语义（按日期查询的默认起点）。完整规则见[起始日规则](../product_groups.md#group-date-constraints)|—|
|<a id="group-start-date"></a>`start_date`|估值起始日期|string / null|YYYY-MM-DD|产品组估值与序列起点：组结果只在 `[start_date, 成员最早到期日]` 内可见，区间外不返回也不回退旧结果；该日与再平衡日同样按成员目标权重起算；取值受成员净值与到期日约束（见[起始日规则](../product_groups.md#group-date-constraints)）|—|
|`label`|产品标签|string（枚举）|—|产品组标签：`live` 实盘、`paper` 模拟、`paper_trading` 模拟交易。枚举[产品标签](#productlabel)|—|
|<a id="group-product-weights"></a>`product_weights`|成员产品权重映射|object（产品 ID 键 → number） / null|小数权重|产品组成员 ID 到权重的映射|—|
|`product_weights.{product_id}`|成员产品权重|number|小数权重|—|—|
|<a id="group-rebalance-frequency"></a>`rebalance_frequency`|调仓频率|string（枚举） / null|—|产品组调仓频率；枚举[产品组调仓频率](#rebalancefreq)|—|
|`id`|记录 ID|string / null|—|服务端记录 ID|只读|

费用计提形成 `*_payable` 应付科目，列入[数量即负债金额的负债科目](balances.md#liability-accounts)；计提方式见[头寸费用应付字段](balances.md#payablepositionextra)，分类净资产分配见[分类份额估值](balances.md#productsharevalue)。

<a id="missing-date-summary"></a>

`products.valuation_report_missing_dates` 与 `products.uploaded_file_hashes` 都是操作输出，返回字段随操作页：缺表汇总见[估值表缺失日期](../products.md#valuation_report_missing_dates)，文件哈希见[已上传文件哈希](../products.md#uploaded_file_hashes)。

## 枚举取值

<a id="accunitvaluevaluationaccordingfield"></a>
### 累计净值口径

|值|含义|
|---|---|
|`last_unit_net_value`|T-1日累计净值+T日单位净值-T-1日单位净值+T日产品单位份额分红|
|`acc_unit_dividend`|T日单位净值+产品起始日至今累计单位份额分红|

<a id="accountbroker"></a>
### 账户券商与通道

|值|含义|
|---|---|
|`caitong`|财通证券通道|
|`changjiang`|长江证券通道|
|`cicc`|中金财富通道|
|`cicc_returns_swap`|中金收益互换通道|
|`citic`|中信证券通道|
|`citic_construction`|中建投通道|
|`citic_returns_swap`|中信收益互换通道|
|`donghai`|东海通道|
|`everbright`|光大证券通道|
|`galaxy`|银河证券通道|
|`guolian`|国联证券通道|
|`guosen`|国信证券通道|
|`guotou`|国投证券通道|
|`guotaijunan`|国泰君安证券通道|
|`haitong`|海通证券通道|
|`hengtai`|恒泰通道|
|`huatai`|华泰证券通道|
|`kingstar`|金仕达通道|
|`minsheng`|民生期货通道|
|`ricequant`|RQ通道|
|`rqfof`|RQ-FOF通道|
|`sealand`|国海证券通道|
|`tianfeng`|天风证券通道|
|`wukuang`|五矿证券通道|
|`zheshang`|浙商证券通道|
|`zhongtai`|中泰通道|

<a id="calendartype"></a>

### 估值日历

|值|含义|
|---|---|
|`exchange`|交易所日历|
|`natural`|自然日|

<a id="etfvaluationaccordingfield"></a>
### ETF 估值价格

|值|含义|
|---|---|
|`close`|当日收盘价（close)|
|`iopv`|当日净值（IOPV）|

<a id="exchangeratetype"></a>
### 港币汇率来源

|值|含义|
|---|---|
|`sh`|沪港通中间价|
|`sz`|深港通中间价|

<a id="futoptvaluationaccordingfield"></a>
### 期货期权估值价格

|值|含义|
|---|---|
|`close`|当日收盘价|
|`settlement`|当日结算价|

<a id="productbenchmarktype"></a>

### 基准类型

|值|含义|
|---|---|
|`index`|指数基准，配合指数代码|
|`customized_index`|自定义基准，配合自定义基准 ID|

<a id="productcosttype"></a>
### 产品费用类别

产品配置中按费用计提比例使用的费用类别；与[托管事件费用类别](custodian_events.md#custodianeventcosttype)不是同一枚举，后者用于产品费用实付事件；两者取值前 5 项同名，但互相独立。

|值|含义|
|---|---|
|`management_fee`|管理费|
|`custodian_fee`|托管费|
|`sales_and_service_fee`|销售服务费|
|`operation_fee`|运营费|
|`performance_pay`|业绩报酬|

<a id="productdatasource"></a>

### 产品数据源

|值|含义|
|---|---|
|`trade`|交易流水数据源|
|`valuation_report`|估值报告数据源|
|`trade_and_valuation_report`|交易流水与估值报告混合数据源|

<a id="productinvestmentcategory"></a>
### 产品投资类别

|值|含义|
|---|---|
|`equity`|权益类|
|`fixed_income`|固收类|
|`derivatives`|商品及金融衍生品类|
|`hybrid`|混合类|
|`cash_management`|现金管理类|
|`stock`|股票型|
|`bond`|债券型|
|`commodity`|商品型|
|`money_market`|货币市场型|
|`other`|另类投资类|
|`fof`|FOF|
|`insurance`|保险资管|

<a id="productlabel"></a>

### 产品标签

|值|含义|
|---|---|
|`live`|实盘|
|`paper`|模拟|
|`paper_trading`|模拟交易|

<a id="productstate"></a>
### 产品状态

|值|含义|
|---|---|
|`normal`|正常|
|`terminated`|已终止|

<a id="productunitpolicy"></a>
### 份额调整方式

|值|含义|
|---|---|
|`auto_prev_unit_net_value`|自动份额：按前一日净值申赎|
|`manual`|手工修改份额|

<a id="rebalancefreq"></a>

### 产品组调仓频率

产品组 `rebalance_frequency` 的取值。

|值|含义|
|---|---|
|`daily`|日度|
|`weekly`|周度|
|`monthly`|月度|
|`quarterly`|季度|
|`yearly`|年度|

<a id="realtimeperiodtype"></a>

### 实时监控时段

|值|含义|
|---|---|
|`daytime`|仅白天 09:30 - 15:00|
|`valuation_day`|估值表日 21:00 - 15:00 (+1)|

<a id="strategycategory"></a>
### 投资策略类别

|值|含义|
|---|---|
|`index_enhanced`|指数增强|
|`equity_market_neutral`|市场中性|
|`stock_long`|股票多头|
|`commodity_trading_advisor`|CTA|
|`mixed`|混合策略|
|`long_short_stock`|股票多空|
|`stock_leverage_neutral`|股票杠杆中性|
|`stock_leverage_long_short`|股票杠杆多空|
|`unconventionality`|其他|
