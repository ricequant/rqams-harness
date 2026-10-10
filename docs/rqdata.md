# RQData 官方调用来源 rqdata

AMS 的行情、合约、日历与市场统计来自 RQData（rqdatac）。本页集中维护文档里用到的调用与官方页面的对应关系：**调用名的官方链接只在本页定义**，业务页与字段页在使用处直接链到官方页面，并指回本页查看全量清单；新增或调整调用时同步本页。

本页只列外部数据调用。产品自身估值、托管报告、导入凭证、自定义标的与资产单元账务不是 RQData；行情与合约口径以官方页面为准，本仓库只说明用到了哪一部分。

<a id="rqdata-calls"></a>

## 通用行情、合约与日历

|调用|官方文档|用到的地方|
|---|---|---|
|RQData Python API 手册|[入口](https://www.ricequant.com/doc/rqdata/python/index-rqdatac)|本页与各业务页的总入口|
|`get_price`|[合约行情](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-genericapi)——日线与分钟线，支持前复权 `adjust_type` 与 `close`、`total_turnover`、`settlement` 等 `fields`|[头寸字段](fields/balances.md)的估值价与结算价、[指标公式](analytics.md#indicators-returns)与[组合对比](analytics.md)的基准收益、[市场数据](market_data.md)的基准与指数期货基差、[看板数据](risk_monitor.md)的 ETF 折溢价与份额对应指数、[流水](trades.md)的估值价与行权结算价、[产品配置](fields/products.md)的估值口径、[资产单元](asset_units.md)的独立估值|
|`get_price` 返回字段|[返回字段](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_price-return)——含 `iopv`（场内基金实时估算净值）与涨跌停价|[看板数据](risk_monitor.md)的分时折溢价率、[产品配置](fields/products.md)的 ETF 估值口径|
|`current_snapshot`|[当前行情快照](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-current_snapshot)——最新价、昨收、涨跌停价与 IOPV|[实时行情](market_data.md)、[头寸字段](fields/balances.md)的实时价格、[资产单元](asset_units.md)的穿透估值|
|`instruments`|[合约基础信息](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-instruments)——合约乘数、发行价、到期日、板块类型等|[流水](trades.md)与[流水字段](fields/trades.md)的合约乘数与发行价、[指标公式](analytics.md#indicators-returns)的合约乘数、[市场数据](market_data.md)的标的详情与到期日、[交易分析](analytics.md)的交易属性细分|
|`all_instruments`|[全部合约](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-all_instruments)——按资产类型取全量合约清单|[标的检索](market_data.md)的名称换代码、[看板数据](risk_monitor.md)的 A 股清单与板块归属、[期货持仓](analytics.md#futures_holdings)的合约池|
|`get_trading_dates`|[交易日历](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_trading_dates)——区间内的交易所交易日|[指标公式](analytics.md#indicators-returns)与[组合对比](analytics.md)的交易日序列、[市场数据](market_data.md)的交易日历、[估值报告](valuation_reports.md)的缺失交易日、[对账](reconciliation.md)的日期集合、[产品配置](fields/products.md)的交易所日历|
|`get_previous_trading_date`|[前一交易日](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_previous_trading_date)——取起点前一交易日，用于回看收益起点|[指标公式](analytics.md#indicators-returns)的 T-20/T-1 窗口与基准起点、[市场数据](market_data.md)的基准累计起点|
|`get_yield_curve`|[国债收益率曲线](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_yield_curve)——中债国债收益率，用于无风险利率|[指标公式](analytics.md#indicators-returns)的年化无风险利率与国债基准、[市场数据](market_data.md)的国债基准|
|`get_open_auction_info`|[开盘集合竞价](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_open_auction_info)——集合竞价成交信息|[交易分析](analytics.md)的算法绩效标记价|
|`get_live_ticks`|[实时逐笔成交](https://www.ricequant.com/doc/rqdata/python/generic-api#rqdata-API-get_live_ticks)——盘中逐笔，用于开盘 tick|[市场数据](market_data.md)的开盘基差口径|

## 股票

|调用|官方文档|用到的地方|
|---|---|---|
|`get_dividend`|[股票分红](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_dividend)——除权除息与分红到账|[头寸字段](fields/balances.md)的复权与应收分红、[流水](trades.md)的分红到账、[对账](reconciliation.md)的轧差推导、[指标公式](analytics.md#indicators-returns)的股票分红率|
|`get_split`|[股票拆分](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_split)——拆分折算比例|[头寸字段](fields/balances.md)的复权与数量调整、[对账](reconciliation.md)的轧差推导|
|`get_share_transformation`|[股票换股](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_share_transformation)——换股比例与换股日|[头寸字段](fields/balances.md)的换股调整、[交易分析](analytics.md)的单标的买卖点处理|
|`get_factor`|[因子值](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_factor)——按因子名取截面序列|[头寸字段](fields/balances.md)的市值与估值因子、[股票持仓](analytics.md#equity_holdings)的市盈率因子、[看板数据](risk_monitor.md)的流通市值（`market_cap_2`）与商誉（`goodwill`）、[可转债持仓](analytics.md#convertible_holdings)的正股市值权重|
|`get_securities_margin`|[融资融券信息](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get_securities_margin)——沪深两市融资余额|[看板数据](risk_monitor.md)的两融余额与占比|
|`get_instrument_industry`|[股票行业分类](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)——申万与中信行业归属|[股票持仓](analytics.md#equity_holdings)与[可转债持仓明细](analytics.md#convertible_positions)的行业字段、[业绩归因](analytics.md#attribution)与[实时风险归因](analytics.md#realtime_risk_attribution)的申万/中信行业口径|
|`is_st_stock`|[股票是否 ST](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-is_st_stock)——按日期判断 ST 状态|[违规公告](risk_monitor.md)的标的筛选、[风险条款](risk_monitor.md)的 ST 预警|
|`get_announcement`|[公司公告数据](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-announcement)——公告标题与日期|[违规公告](risk_monitor.md)筛选标题含「违规」「违法」的标的、[风险条款](risk_monitor.md)的违规公告预警|

## 基金

|调用|官方文档|用到的地方|
|---|---|---|
|`fund.instruments`|[基金基础信息](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-instruments)——基金类型、场内后缀等|[流水](trades.md)的基金场内后缀补齐、[流水字段](fields/trades.md)的基金标识|
|`fund.all_instruments`|[全部基金信息](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-all_instruments)——按类型取公募基金清单|[头寸字段](fields/balances.md)的风险敞口口径（货币基金排除）、[组合对比](analytics.md)的权益基金识别|
|`fund.get_instrument_category`|[基金投资类别](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_instrument_category)——基金类别划分|[头寸字段](fields/balances.md)的基金类别字段|
|`fund.get_nav`|[基金净值](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_nav)——单位净值与累计净值，可取复权净值|[头寸字段](fields/balances.md)的资产份额与复权净值、[交易分析](analytics.md)的单标的复权净值价格分支、[指标公式](analytics.md#indicators-returns)的复权净值|
|`fund.get_dividend`|[基金分红](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_dividend)——基金分红到账|[头寸字段](fields/balances.md)的应收分红与复权、[对账](reconciliation.md)的轧差推导|
|`fund.get_split`|[基金拆分](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_split)——拆分折算比例与除权除息日|[头寸字段](fields/balances.md)的份额调整、[看板数据](risk_monitor.md)的 ETF 拆分记录|
|`fund.get_daily_units`|[基金日度份额](https://www.ricequant.com/doc/rqdata/python/fund-mod#rqdata-API-fund-get_daily_units)——期末总份额|[看板数据](risk_monitor.md)的 ETF 份额序列|

## 期货

|调用|官方文档|用到的地方|
|---|---|---|
|`futures.get_basis`|[期货基差](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_basis)——结算基差与年化基差|[头寸字段](fields/balances.md)的基差指标、[指标公式](analytics.md#indicators-returns)的基差变化与标的收益、[市场数据](market_data.md)的基差序列|
|`futures.get_current_basis`|[期货当前基差](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_current_basis)——当日/当前时点基差|[市场数据](market_data.md)的指数期货基差快照|
|`futures.get_contracts`|[期货合约列表](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_contracts)——按品种取可交易合约|[市场数据](market_data.md)的指数期货基差合约池|
|`futures.get_dominant`|[主力合约](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_dominant)——主力与次主力合约序列|[期货持仓](analytics.md#futures_holdings)的主力合约基差序列|
|`futures.get_predicted_dividend_point`|[预测分红点数](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_predicted_dividend_point)——分红调整基差所用点位|[市场数据](market_data.md)的基差分红调整|
|`futures.get_trading_parameters`|[期货交易参数](https://www.ricequant.com/doc/rqdata/python/futures-mod#rqdata-API-futures-get_trading_parameters)——保证金比例、涨跌停与手续费参数|[流水](trades.md)的期货交易校验|

## 期权

|调用|官方文档|用到的地方|
|---|---|---|
|`options.get_contract_property`|[期权合约属性](https://www.ricequant.com/doc/rqdata/python/options-mod#rqdata-API-options-get-contract_property)——合约乘数、行权价、到期日等|[头寸字段](fields/balances.md)的期权合约口径、[流水](trades.md)的期权合约乘数与行权|
|`options.get_greeks`|[期权希腊字母](https://www.ricequant.com/doc/rqdata/python/options-mod#rqdata-API-options-get_greeks)——Delta、Gamma、Vega 等|[期权持仓](analytics.md#option_holdings)的希腊字母拆分|

## 可转债

|调用|官方文档|用到的地方|
|---|---|---|
|`convertible.instruments`|[可转债合约信息](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-instruments)——转股价、到期日、剩余规模等|[头寸字段](fields/balances.md)的可转债合约口径、[可转债持仓明细](analytics.md#convertible_positions)的转股与溢价率口径|
|`convertible.get_indicators`|[可转债指标](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_indicators)——转股价值、转股溢价率、强赎与回售触发进度|[可转债持仓明细](analytics.md#convertible_positions)的转股价值、溢价率与强赎回售进度|
|`convertible.get_cash_flow`|[可转债现金流](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_cash_flow)——利息与兑付现金流|[头寸字段](fields/balances.md)的应计利息与现金流、[流水](trades.md)的付息处理|
|`convertible.get_accrued_interest_eod`|[可转债日终应计利息](https://www.ricequant.com/doc/rqdata/python/convertible-mod#rqdata-API-convertible-get_accrued_interest_eod)——每张债券的应计利息|[头寸字段](fields/balances.md)的应计利息字段、[估值报告](positions_sheets.md)与[对账](reconciliation.md)的应计利息对照|

## 指数

|调用|官方文档|用到的地方|
|---|---|---|
|指数列表|[指数列表](https://www.ricequant.com/doc/rqdata/python/indices-mod#rqdata-API-indices_list)（另有米筐特色指数页）——按代码查指数名称|[市场数据](market_data.md)的内置基准代码（如沪深300 对应 `000300.XSHG`）|
|`index_components`|[指数成分](https://www.ricequant.com/doc/rqdata/python/indices-mod#rqdata-API-index-components)——区间内的成分股|[可转债持仓](analytics.md#convertible_holdings)的成分识别、[业绩归因](analytics.md#attribution)的成分解析|
|`index_weights_ex` / `index_weights`|[指数权重](https://www.ricequant.com/doc/rqdata/python/indices-mod#rqdata-API-index_weights_ex)——成分权重，`index_weights` 为单一权重指数口径|[指标公式](analytics.md#indicators-returns)的组合基准加权|
|`get_price`（米筐特色指数）|[米筐特色指数行情](https://www.ricequant.com/doc/rqdata/python/ricequant-index#rqdata-API-get_price)——VIX 等特色指数的日线与分钟线|[看板数据](risk_monitor.md)的 VIX 序列|
|VIX 指数口径|[米筐期权波动率指数（VIX）](https://www.ricequant.com/doc/rqdata/python/ricequant-index#ricequant-vix)——编制规则、指数代码与基日|[看板数据](risk_monitor.md)的指数代码取值与起点|

## 港股

|调用|官方文档|用到的地方|
|---|---|---|
|`get_exchange_rate`|[港币汇率](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_exchange_rate_hk)——港币中间价与结算价|[头寸字段](fields/balances.md)的结算币种价、[产品配置](fields/products.md)的汇率来源设置、[流水](trades.md)的港股通汇率、[估值报告](valuation_reports.md)的港币公允价、[自定义标的](custom_instruments.md)的折算|
|`get_price`（港股）|[港股行情](https://www.ricequant.com/doc/rqdata/python/stock-hk#rqdata-API-get_price_hk_function)——港股通标的行情|[市场数据](market_data.md)的港股基准收益|

## 风险因子

|调用|官方文档|用到的地方|
|---|---|---|
|`get_factor_exposure`|[因子暴露](https://www.ricequant.com/doc/rqdata/python/risk-factors-mod#rqdata-API-get_factor_exposure)——风险模型的因子暴露与因子收益|[业绩归因](analytics.md#attribution)、[实时风险归因](analytics.md#realtime_risk_attribution)与[实时因子暴露](analytics.md#realtime_factor_exposure)的因子口径|
