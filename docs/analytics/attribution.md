# 业绩归因 analytics

归因把区间收益拆解到基准、行业与风格等维度：先提交归因任务，再按归因 ID 读取结果，需要归档时导出工作簿；实时截面走 `realtime_factor_exposure` 与 `realtime_risk_attribution`。归因结果是服务端算好的分析结果，不是新的估值数据；指标口径见[净值与收益指标](metrics.md#indicators-returns)。

本页是 [analytics 总览](index.md) 的子页：用户需求与完成条件见[总览的场景表](index.md#从用户需求到操作)，`resource`/`resources` 语义与阻塞式调用等公共约定见[总览](index.md#api-使用约定)；本页涉及的外部数据调用与官方页面见 [RQData 官方调用来源](../rqdata.md#rqdata-calls)。
- `attribution` 与 `export_attribution` 依赖已存在的归因 ID；删除归因按 ID 直接删除，网关要求 `read_position`，权限不足时以服务端错误返回。

## create_attribution

提交区间业绩归因计算，直接返回归因 ID。
- create_attribution：基准必填且格式为「类型,代码」；模板与「仅收益拆解」至少给一个，都不给时无法确定分解方式。

Python 签名：`rqamsh.analytics.create_attribution(resource: str, *, start_date: str, end_date: str, benchmark: str, template: str | None=None, industry_standard: str | None=None, drilldown: bool=False, only_returns_decomposition: bool=False, need_market_value_weights: bool=False)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`start_date`|`str`|必填|YYYY-MM-DD。|
|`end_date`|`str`|必填|YYYY-MM-DD。|
|`benchmark`|`str`|必填|「类型,代码」格式的基准。|
|`template`|`str \| None`|`None`|归因模板，取 `equity/brinson`、`equity/factor`、`equity/factor_v2` 之一；服务端按枚举校验，其他值直接失败。|
|`industry_standard`|`str \| None`|`None`|行业分类标准，取 `sws`、`sws_second`、`citics`、`citics_second` 之一；省略时由服务端按模板决定。|
|`drilldown`|`bool`|`False`|是否对资产单元穿透。|
|`only_returns_decomposition`|`bool`|`False`|是否只做收益拆解。|
|`need_market_value_weights`|`bool`|`False`|是否同时返回市值权重。|

返回：服务端新建的归因记录对象，只含归因 ID；提交成功只代表任务已排队，必须用 [`attribution`](#attribution) 轮询到终态。记录里服务端会把 `benchmark` 归一化为 `{"type": ..., "id": ...}`，并在未指定时填入默认行业分类标准。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|新建归因记录|object|—|服务端直接返回的归因记录，只含归因 ID，不含归因结果|恒返回；`benchmark` 归一化与默认行业分类标准体现在记录的读取结果中，见 `attribution` 的返回表|
|`id`|归因 ID|string|字符串 ID|新建归因记录的 ID，供 [`attribution`](#attribution)、[`export_attribution`](#export_attribution)、[`delete_attribution`](#delete_attribution) 使用|恒返回；`attribution` 查询结果里同一值落在 `_id`|

结果检查：`id` 只是任务标识；区间内没有产品交易日历时服务端直接拒绝提交，不要用重放创建来换取结果。提问的粒度就是提交的粒度：只要某一天的结果就按单日提交（区间、基准与模板一一对应），先提交大区间再改单日等于重新排队。

## attribution

按归因 ID 查询归因结果。
- attribution：运行中的归因会持续返回进行中状态，Harness 在同一查询路由重复读取，不会重新提交计算。

Python 签名：`rqamsh.analytics.attribution(resource: str, attribution_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`attribution_id`|`str`|必填|`create_attribution` 返回的归因 ID。|

返回：任务成功后是服务端原样的归因记录对象，运行中则是任务状态对象（`status`、`progress`、`message`，见[任务终态 JSON](../connection.md#task-result)）；失败终态会抛出错误并保留服务端诊断。归因结果体的形状随参数变化：`only_returns_decomposition=True` 时 `result` 本身就是收益拆解数组，否则是按模板组织的对象（`result[].factor` 里的 `{资产类别}` 是资产类别中文名的占位，不是 JSON 键）；它由归因引擎产出、服务端原样返回（只不含导出附件与 Brinson 日度序列），下表只列服务端与导出实际读写的键，引擎版本变化可能带来其它键。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|归因记录对象|object|—|服务端直接返回的归因记录；任务成功时才带归因结果|恒返回；运行中返回任务状态对象，不含归因记录字段|
|`_id`|归因 ID|string|字符串 ID|与 [`create_attribution`](#create_attribution) 返回的 `id` 相同|随归因记录返回|
|`product_or_group_id`|产品或产品组 ID|string|字符串 ID|本次归因的对象|随归因记录返回|
|`product_or_group_name`|对象名称|string|—|本次归因的产品或产品组名称|随归因记录返回|
|`user_id`|提交人 ID|integer|—|提交该归因任务的用户|随归因记录返回|
|`start_date`|区间起始日|string|—|提交时的分析起始日|随归因记录返回|
|`end_date`|区间截止日|string|—|提交时的分析截止日|随归因记录返回|
|`benchmark`|归一化基准|object|—|由提交的「类型,代码」拆分成的对象，含 `type` 与 `id`|随归因记录返回|
|`benchmark.type`|基准类型|string（枚举）|—|归一化后的基准类型取值|随父级返回|
|`benchmark.id`|基准 ID|string|字符串 ID|指数代码或自定义基准 ID|随父级返回|
|`template`|归因模板|string|—|提交时选择的模板，取值同提交参数|由参数选择；仅做收益拆解时该键缺席|
|`create_time`|创建时间|string|—|服务端记录的任务创建时间|随归因记录返回|
|`drilldown`|是否对资产单元穿透|boolean|—|与提交参数一致|随归因记录返回|
|`industry_standard`|行业分类标准|string（枚举）|—|提交时未指定时由服务端填入默认值|随归因记录返回|
|`only_returns_decomposition`|是否仅收益拆解|boolean|—|与提交参数一致|随归因记录返回|
|`status`|任务状态|string（枚举）|—|任务完成时由服务端写入 `SUCCESS`|由数据决定；见[任务终态 JSON](../connection.md#task-result)|
|`message`|任务提示|string / null|—|任务完成时由服务端写入的说明文案|由数据决定；成功时可能为空字符串|
|`result`|归因结果主体|object / array|—|按 `only_returns_decomposition` 与 `template` 组成的归因结果：模板分支下是含下列键的对象，仅收益拆解分支下根对象就是收益拆解数组|由数据决定；任务成功后才返回；不含导出附件键，Brinson 模板下也不含日度归因序列|
|`result[]`|收益拆解节点|object|—|仅收益拆解分支的数组元素；树形结构由 `children` 递归，字段见下列 `result[].…` 各行|由参数选择：`only_returns_decomposition=True`|
|`result[].factor`|节点名称|string|—|节点名：`总收益`、`交易收益`、`杠杆收益`、`持仓收益`、`超额收益`、`基准持仓收益`、`基准收益`、`穿透效应`，以及各类资产的`{资产类别}收益`／`{资产类别}配置收益`／`{资产类别}选择收益`|随父级返回|
|`result[].value`|节点收益|number|小数|该节点的区间累计收益（多期连接后累计，不是逐日求和）|随父级返回|
|`result[].children`|子节点列表|array / null|—|下一层拆解节点；叶子节点为 `null`|由数据决定：叶子节点为 `null`|
|`result.returns_decomposition`|收益拆解树|array（object）|—|元素结构同 `result[]` 三行；对象分支下各模板都有|由参数选择：`template` 为 `equity/brinson`、`equity/factor`、`equity/factor_v2` 之一时返回|
|`result.attribution`|模板归因结果|object|—|该模板的归因结果容器，键由模板决定|由参数选择：同上三模板；实时与仅收益拆解分支没有该键|
|`result.attribution.brinson`|行业归因|array（object）|—|每行一个行业，按引擎的行业排序输出|由参数选择：`template=equity/brinson`|
|`result.attribution.brinson[].industry`|行业|string|—|[行业名](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)；基准为现金时为 `其他`，为国债收益率时为 `债券`|随父级返回|
|`result.attribution.brinson[].allocation_return`|行业配置收益|number|小数|区间累计的行业配置收益|随父级返回|
|`result.attribution.brinson[].selection_return`|选股收益|number|小数|区间累计的选股收益|随父级返回|
|`result.attribution.brinson[].active_return`|主动收益|number|小数|配置收益与选股收益之和|随父级返回|
|`result.attribution.brinson[].portfolio_weight`|组合权重|number|小数|区间均值权重|随父级返回|
|`result.attribution.brinson[].benchmark_weight`|基准权重|number|小数|区间均值权重|随父级返回|
|`result.attribution.brinson[].allocation_risk`|行业配置风险贡献|number|小数|该行业配置对日频主动收益标准差的贡献（未年化，不是金额）|随父级返回|
|`result.attribution.brinson[].selection_risk`|选股风险贡献|number|小数|同口径的选股风险贡献|随父级返回|
|`result.attribution.factor_attribution`|因子归因|array（object）|—|5 个固定类别元素：`style`、`industry`、`country`、`specific_return`、`other`；服务端按 `style`、`specific_return`、`industry`、`country`、`other` 排序|由参数选择：`template=equity/factor` 或 `equity/factor_v2`|
|`result.attribution.factor_attribution[].type`|因子类别|string|—|取值即上一行的五个类别名|随父级返回|
|`result.attribution.factor_attribution[].factors`|因子项列表|array（object）|—|该类别下的因子项，字段见下列各行；可能为空数组|随父级返回|
|`result.attribution.factor_attribution[].factors[].factor`|因子名|string|—|风格、行业、国别因子名或 `specific_return`／`other`|随父级返回|
|`result.attribution.factor_attribution[].factors[].portfolio_return`|因子组合收益|number|小数|区间累计因子收益|随父级返回|
|`result.attribution.factor_attribution[].factors[].benchmark_return`|因子基准收益|number|小数|同口径的基准因子收益|随父级返回|
|`result.attribution.factor_attribution[].factors[].active_return`|因子主动收益|number|小数|组合与基准因子收益之差|随父级返回|
|`result.attribution.factor_attribution[].factors[].portfolio_exposure`|组合暴露度|number / null|—|区间均值暴露度；`specific_return` 与 `other` 两类恒为 `null`|随父级返回|
|`result.attribution.factor_attribution[].factors[].benchmark_exposure`|基准暴露度|number / null|—|同口径的基准暴露度；该类别不适用时为 `null`|随父级返回|
|`result.attribution.factor_attribution[].factors[].active_exposure`|主动暴露度|number / null|—|组合与基准暴露度之差|随父级返回|
|`result.attribution.factor_attribution[].factors[].portfolio_risk`|因子组合风险贡献|number / null|小数|对日频组合收益标准差的贡献（未年化，不是金额）|随父级返回|
|`result.attribution.factor_attribution[].factors[].benchmark_risk`|因子基准风险贡献|number / null|小数|同口径的基准风险贡献|随父级返回|
|`result.attribution.factor_attribution[].factors[].active_risk`|因子主动风险贡献|number / null|小数|同口径的主动风险贡献|随父级返回|
|`result.attribution.factor_exposure`|因子暴露序列|array（object）|—|每项一个因子的逐日[暴露度](https://www.ricequant.com/doc/rqdata/python/risk-factors-mod#rqdata-API-get_factor_exposure)|由参数选择：`template=equity/factor` 或 `equity/factor_v2`|
|`result.attribution.factor_exposure[].factor`|因子名|string|—|与因子归因里的因子名一致|随父级返回|
|`result.attribution.factor_exposure[].data`|逐日暴露度|array（object）|—|元素见下列各行|随父级返回|
|`result.attribution.factor_exposure[].data[].date`|暴露度日期|string|—|取该日的前一交易日，`YYYY-MM-DD`|随父级返回|
|`result.attribution.factor_exposure[].data[].portfolio`|组合暴露度|number|—|按组合权重加权的暴露度|随父级返回|
|`result.attribution.factor_exposure[].data[].normalized`|权益部分暴露度|number|—|按归一化权重（权重 ÷ 权重合计）加权的暴露度|随父级返回|
|`result.attribution.factor_exposure[].data[].active`|主动暴露度|number|—|组合暴露度与基准暴露度之差|随父级返回|
|`result.attribution.sensitivity`|净值回归|array（object）|—|最多 3 个时间段，每段一项|由参数选择：`template=equity/factor` 或 `equity/factor_v2`|
|`result.attribution.sensitivity[].date`|区间结束日|string|—|该段结束日，`YYYY-MM-DD`|随父级返回|
|`result.attribution.sensitivity[].data`|逐因子回归结果|array（object）|—|元素见下列各行|随父级返回|
|`result.attribution.sensitivity[].data[].factor`|因子名|string|—|与因子归因里的因子名一致|随父级返回|
|`result.attribution.sensitivity[].data[].portfolio`|因子敏感度|number|—|组合日收益对因子收益回归的系数|随父级返回|
|`result.attribution.sensitivity[].data[].t_statistics`|敏感度 t 值|number|—|该回归系数的 t 统计量|随父级返回|
|`result.is_benchmark_weight_daily`|基准权重是否按日更新|boolean|—|按基准类型与权重来源判定；服务端不消费该键|由参数选择：`template` 为 `equity/brinson`、`equity/factor`、`equity/factor_v2` 之一时返回|

结果检查：用 `_id` 做后续查询与导出；运行态由客户端在同一查询路由自动轮询到终态，不必重新提交；若已返回归因记录却缺 `result`，按同一归因 ID 重查该读取，不要重新提交 `create_attribution`，也不要把缺失当作空归因结果。

## delete_attribution

删除归因记录。
- delete_attribution：按归因 ID 直接删除，返回 null；网关要求 `read_position`，客户端不预判权限。

Python 签名：`rqamsh.analytics.delete_attribution(resource: str, attribution_id: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`attribution_id`|`str`|必填|要删除的归因 ID。|

返回：空响应，客户端得到 `None`；删除成功与「记录本就不存在」都是这个结果，删除不改变历史估值结果。

## export_attribution

导出归因结果（生成文件并落盘）。
- export_attribution：先有终态归因，再导出到新文件；目标文件已存在时抛错。

Python 签名：`rqamsh.analytics.export_attribution(resource: str, attribution_id: str, output: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`attribution_id`|`str`|必填|已终态的归因 ID。|
|`output`|`str`|必填|输出文件路径；父目录须存在且目标文件不得已存在。|

返回：客户端下载元数据，含 `path`、`size`；先有终态归因、任务完成后才写入本地新文件。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`path`|落盘路径|string|绝对路径|本次实际写入的本地文件路径|恒返回；由 `output` 决定，不复用服务端文件名；见[下载元数据](../connection.md#download-result)|
|`size`|文件字节数|integer|字节|本次实际写入的字节数|恒返回；`0` 不代表内容完整；见[下载元数据](../connection.md#download-result)|

已知服务端缺陷：`equity/brinson` 归因结果的日度序列表为空时，导出任务会失败且不给出可读业务错误，而同样区间下 `equity/factor` 结果可正常导出；遇到该失败应改用因子模板，或先确认该区间确实没有可导出的 Brinson 日度序列。

## realtime_risk_attribution

读取实时风险归因。
- realtime_risk_attribution：仅单产品；模板决定分解方式，因子模板与 Brinson 模板的行业标准参数分别可选，只有提供时才下发。

Python 签名：`rqamsh.analytics.realtime_risk_attribution(resource: str, *, template: str='equity/factor', benchmark: str | None=None, factor_industry_standard: str | None=None, brinson_industry_standard: str | None=None, drilldown: bool=False)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称；不支持产品组。|
|`template`|`str`|`equity/factor`|分解模板，取 `equity/factor` 或 `equity/factor_v2`；服务端在同一次任务内同时计算 Brinson 结果。|
|`benchmark`|`str \| None`|`None`|可选基准。|
|`factor_industry_standard`|`str \| None`|`None`|因子模板下的[行业分类](https://www.ricequant.com/doc/rqdata/python/stock-mod#rqdata-API-get-instrument-industry-stockmod)标准。|
|`brinson_industry_standard`|`str \| None`|`None`|Brinson 模板下的行业分类标准。|
|`drilldown`|`bool`|`False`|是否对资产单元穿透。|

服务端不接受日期参数，固定以北京时间当天作为归因区间，因此当天不是交易日时该操作必然失败（报错为「分析区间内没有交易日」），调用方无法通过参数换区间——需要指定区间时必须用 `create_attribution`。实时因子暴露 `realtime_factor_exposure` 走另一套实时序列检查，不受此限制。

返回：首发 202 返回 `task_id`，随后轮询同一路由得到终态 JSON，归因结果在 `data` 内。`data` 是当次实时因子归因结果，服务端在同一次任务内把实时行业归因并入 `attribution.brinson`；键集合固定，但因子列表随当日持仓与暴露度数据变化。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`task_id`|任务 ID|string|—|首发响应给出的任务标识，Harness 用它在同一路由轮询到终态|首发 202 时恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`status`|任务状态|string（枚举）|—|`SUCCESS` 表示任务完成，`FAIL` 表示失败，运行中为 `DOING`、`PENDING` 等|轮询响应恒返回；见[任务终态 JSON](../connection.md#task-result)|
|`data`|实时风险归因结果|object|—|实时因子归因结果与同一次任务内合入的实时行业归因；字段见下列各行|由数据决定；`status` 为 `SUCCESS` 时返回|
|`data.attribution`|实时归因结果容器|object|—|只含 `factor_attribution` 与 `brinson` 两个键；没有 `returns_decomposition`、`excel_report`、`factor_exposure`、`sensitivity`|随父级返回|
|`data.attribution.factor_attribution`|因子归因|array（object）|—|5 个固定类别元素，排序与区间归因一致|随父级返回|
|`data.attribution.factor_attribution[].type`|因子类别|string|—|`style`、`industry`、`country`、`specific_return`、`other`|随父级返回|
|`data.attribution.factor_attribution[].factors`|因子项列表|array（object）|—|该类别下的因子项；可能为空数组|随父级返回|
|`data.attribution.factor_attribution[].factors[].factor`|因子名|string|—|风格、行业、国别因子名或 `specific_return`／`other`|随父级返回|
|`data.attribution.factor_attribution[].factors[].portfolio_return`|因子组合收益|number|小数|当日口径的因子收益（实时归因只用当天数据）|随父级返回|
|`data.attribution.factor_attribution[].factors[].benchmark_return`|因子基准收益|number|小数|同口径的基准因子收益|随父级返回|
|`data.attribution.factor_attribution[].factors[].active_return`|因子主动收益|number|小数|组合与基准因子收益之差|随父级返回|
|`data.attribution.factor_attribution[].factors[].portfolio_exposure`|组合暴露度|number / null|—|按当日持仓权重与前一交易日个股[暴露度](https://www.ricequant.com/doc/rqdata/python/risk-factors-mod#rqdata-API-get_factor_exposure)算出；算不出暴露度的因子保持 `null`|随父级返回|
|`data.attribution.factor_attribution[].factors[].benchmark_exposure`|基准暴露度|number / null|—|按基准权重与同一批暴露度算出|随父级返回|
|`data.attribution.factor_attribution[].factors[].active_exposure`|主动暴露度|number / null|—|组合暴露度与基准暴露度之差|随父级返回|
|`data.attribution.brinson`|实时行业归因|array（object）|—|同一次任务内算出的行业归因，只有收益与权重，没有风险贡献两项|随父级返回|
|`data.attribution.brinson[].industry`|行业|string|—|行业名；基准为现金时为 `其他`，为国债收益率时为 `债券`|随父级返回|
|`data.attribution.brinson[].allocation_return`|行业配置收益|number|小数|当日口径的行业配置收益|随父级返回|
|`data.attribution.brinson[].selection_return`|选股收益|number|小数|当日口径的选股收益|随父级返回|
|`data.attribution.brinson[].active_return`|主动收益|number|小数|配置收益与选股收益之和|随父级返回|
|`data.attribution.brinson[].portfolio_weight`|组合权重|number|小数|当日权重|随父级返回|
|`data.attribution.brinson[].benchmark_weight`|基准权重|number|小数|当日权重|随父级返回|
|`message`|任务提示|string / null|—|服务端说明文案|由数据决定；运行中或失败时出现，成功终态可能没有该键；提示级别见 `message_type` 行|
|`message_type`|提示级别|string|—|`error`／`warning`：区分失败原因与可继续解读的提示（基准权重按月度近似时为 `warning`）|由数据决定；与 `message` 同时出现|

结果检查：`data` 的键固定为因子归因与实时行业归因两族，但因子列表随当日持仓与暴露度数据变化，解读前先看实际键；当天不是交易日时任务必然失败，这不是数据缺口。

## realtime_factor_exposure

读取实时因子暴露序列。
- realtime_factor_exposure：仅单产品；模板必填，客户端不校验该参数，非法值由服务端拒绝。返回 `exposure_series`（逐时点暴露）与 `start`/`end`；持仓内没有股票或暴露度尚未就绪时只返回区间信息。

Python 签名：`rqamsh.analytics.realtime_factor_exposure(resource: str, *, template: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品唯一 ID 或名称；不支持产品组。|
|`template`|`str`|必填|因子模板，取 `equity/factor` 或 `equity/factor_v2`；其他值由服务端拒绝。|

返回：服务端原始时序对象，含 `exposure_series`、`start`、`end`；持仓内没有股票或暴露度尚未就绪时只返回区间信息。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|（根对象）|实时因子暴露结果|object|—|服务端直接返回的暴露时序对象，含 `exposure_series`、`start`、`end`，另有告警时附带告警键|恒返回；持仓无股票或无暴露数据时只含 `start`、`end`|
|`exposure_series`|逐时点暴露序列|array（object）|—|每个实时时点一条，元素含 `datetime` 与各因子名键，值为持仓加权暴露减基准暴露|由数据决定；无股票持仓或全部标的无暴露数据时不返回该键|
|`exposure_series[].datetime`|时点|string|—|该条记录的实时时点|随父级记录返回|
|`exposure_series[].{因子名}`|该因子主动暴露|number|—|该时点该因子的[主动暴露](https://www.ricequant.com/doc/rqdata/python/risk-factors-mod#rqdata-API-get_factor_exposure)，键名为英文因子名|由数据决定；键随模板与暴露数据，同一条内并非所有因子都有值|
|`start`|区间起点|string|—|本次实时序列的起点时点|恒返回|
|`end`|区间终点|string|—|本次实时序列的终点时点|恒返回|
|`message_type`|提示级别|string（枚举）|—|基准等依赖数据不可用时的提示级别|由数据决定；只在有告警时与 `warning_message` 一起返回|
|`warning_message`|告警文案|string|—|基准等依赖数据不可用时的说明|由数据决定；只在有告警时返回|

结果检查：只有 `start`、`end` 时表示没有股票持仓或暴露度未就绪，不是零暴露；先核对是否确有股票持仓，确有持仓却只返回区间信息时，稍后重试同一读取。因子键名以实际返回为准，不要按模板名推断完整因子集合。

