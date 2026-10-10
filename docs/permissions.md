# 资源权限 permissions

权限决定谁能看、谁能改一个产品或产品组。AMS 把授权存成「资源 + 用户 + 级别」的授权行：一条授权行让某个用户在该资源上获得一个权限级别；没有授权行的用户按资源归属与空间管理员身份判断，`forbidden` 表示明确不授权。本页是资源访问权限的权威页：级别划分、逐路由的级别下限与授权行的读写都在这里；连接、身份与错误处理见[连接说明](connection.md)。

## 权限级别

六个级别按下列顺序从低到高比较：`forbidden` < `read_net_value` < `read_position` < `read_import_data` < `write` < `admin`；路由要求的是下限，持有更高一级即可通过更低级别要求的读取，注意 `read_import_data`（三级）高于 `read_position`（二级）。工作空间管理员与该资源的创建者按最高级别处理，不通过授权行表达；`permission_id` 是授权行 ID，不是本枚举的取值。

逐路由的级别下限见[逐路由最低权限级别](#逐路由最低权限级别)，授权行的读取与写入见下面四个操作；查询到资源不等于可写，判据见[可见不等于可写](#可见不等于可写)。

|值|含义|
|---|---|
|`forbidden`|无权限：明确不授权该用户访问该资源|
|`read_net_value`|可查看一级：产品与产品组配置、净值与收益指标、组合对比、头寸摘要与概览、风险条款读取|
|`read_position`|可查看二级：持仓分析各视图、业绩归因与实时归因、实时因子暴露|
|`read_import_data`|可查看三级：头寸报表完整结果与历史序列、流水、估值报告、持仓单、托管与份额事件、导入凭证、资产权重与交易分析|
|`write`|可编辑：在只读范围之外可写入与修改数据（含对账状态写入）|
|`admin`|管理员：最高级别，含分享与删除等管理动作；不能通过授权接口授予|

## 逐路由最低权限级别

下表是 AMS 网关的逐路由最低权限级别，用于确认需要申请哪一档权限。级别按路由判定，因此同一个业务块可以跨多档：`analytics` 的净值收益指标操作在 `read_net_value`，持仓分析在 `read_position`，可转债持仓明细在 `read_import_data`。

|操作范围|网关最低权限级别|
|---|---|
|登录即可（不校验资源级别）：市场数据与基准 `market_data.instruments`/`trading_dates`/`realtime_quotes`/`benchmarks`/`benchmark_returns`/`realtime_benchmark_returns`/`index_futures_basis` 与自定义基准增删改查、看板数据 `risk_monitor.vix`/`margin_balance`/`etf_shares`/`etf_premium_rate`/`goodwill_ratio`、违规公告 `risk_monitor.illegal_announcements`、条款 `update_clause`/`delete_clauses`（实时预警见下一行）、标签 `tags.list`/`tags.upsert`/`tags.delete`、空间级查询（`products.compute_state`/`name_exists`/`field_exists`/`create_example`/`valuation_report_missing_dates`/`uploaded_file_hashes`、`positions_statements.latest`、`confirmations.latest`）|登录即可；`positions_statements.latest` 与 `confirmations.latest` 客户端可见性过滤另需资源目录构建成功，见下方说明|
|产品/组普通配置与指标：`products.list`/`products.get`、`analytics.indicators`/`analytics.series`/`analytics.win_rate`/`analytics.long_short_returns`/`analytics.download_series_file`（原 `indicators` 块，已并入 `analytics`）|read_net_value|
|头寸报表 `previous_summary`/`previous_summaries`、`balances.get` 的 `balance_summary` 简字段摘要路由与 `asset_snapshot_summary` 实时概览路由、盘中序列 `series`（省略 `end_date`）|read_net_value|
|字段最早日期查询 `balances.field_earliest_date`/`field_earliest_dates`|read_net_value|
|实时快照导出 `balances.export_snapshot` 的多资源形态（概览文件）|read_net_value|
|组合对比 `analytics.group_indicators`/`group_returns`/`group_capital_size`/`group_allocation`/`group_returns_correlation`/`group_excess_correlation`/`group_overview_file`|read_net_value|
|风险条款读取 `risk_monitor.clauses`|read_net_value|
|实时预警 `risk_monitor.realtime_warnings`|路由登录即可；服务端对每条预警所属资源要求不低于 `read_import_data`，资源权限低于该级别的预警会被静默跳过（结果里不出现）|
|头寸报表 `balances.get` 的完整 `balance` 端点（历史查询、产品组、分类、自定义基准、成员权重、不展示期货冲销项的实时查询等）与历史序列 `series`|read_import_data|
|头寸全景导出 `balances.export_file`、实时快照导出 `balances.export_snapshot` 的单资源形态|read_import_data|
|资产权重视图 `analytics.asset_weight`|read_import_data|
|交易分析 `analytics.trading_analysis`/`single_trading_analysis`/`algo_trading_performance`|read_import_data|
|可转债持仓明细 `analytics.convertible_positions`|read_import_data|
|持仓分析导出 `analytics.holdings_summary_file`|read_position；`template=convertible` 时 read_import_data|
|持仓分析 `analytics.equity_holdings`/`futures_holdings`/`option_holdings`/`convertible_holdings`|read_position|
|业绩归因 `analytics.create_attribution`/`attribution`/`delete_attribution`/`export_attribution`、实时归因 `realtime_risk_attribution`、实时因子暴露 `realtime_factor_exposure`|read_position|
|对账状态、差异与持仓单一致性（`reconciliation` 读取）|write|
|托管事件、份额事件、产品持仓表与导入凭证（读取）|read_import_data|
|流水明细导出 `trades.download`、流水读取|read_import_data|
|估值报告与持仓单读取、缺表日期查询（`valuation_reports.list/missing_dates`、`positions_statements.list/download`）|read_import_data|
|风险条款写入 `risk_monitor.create_clauses`|read_import_data|
|空间级写入与业务写入：流水导入与编辑、估值报告与持仓单导入、托管事件、份额事件、快照与公允价写入、产品封账、份额转换、对账的全部动作|write|
|产品与产品组删除|admin|

上表「登录即可」一行里的 `positions_statements.latest` 与 `confirmations.latest`，指的是**服务端路由**的最低级别不校验资源级别；客户端还会在取回结果后按当前身份可见的资源再过滤一遍，这一步要求资源目录整体构建成功：产品列表、每个产品详情、产品组列表与详情、资产单元列表都必须成功。顶层请求失败会让接口整体失败，产品组列表/详情或资产单元列表等非 403/404 错误同样如此，只有产品详情与产品组详情的 403/404 会被跳过。因此「路由登录即可」不等于「客户端一定拿得到结果」。

## 可见不等于可写

查询到对象不表示可以修改。对已有产品、产品组和资产单元写入，需要所有者身份或 `write` / `admin` 权限；资产单元继承归属产品权限。创建对象也必须在当前用户获授权的工作空间进行；可见性本身由空间与权限共同决定，见[工作空间是什么](connection.md#workspace)。

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|确认某个产品/组当前授权给了谁|`list` 选定资源|逐行核对 `user_id` 与 `permission`；空数组表示没有授权行，不代表调用者没有访问权|
|把产品或组分享给同事|`list` 记录现有授权行 → `grant` 提交授权项 → 需要清理时按返回的 `error_messages` 修正后重试失败项|`effect_count` 覆盖该项且无 `error_messages`；对方能在该资源上执行相应级别的操作|
|调整已分享用户或撤回分享|`list` 取授权行 `id` → `grant` 带 `permission_id` 改级别，或 `revoke` 提交授权行 `id`|改级别后 `list` 中出现新的 `permission`；撤权后该授权行不再出现|
|把同一批人一次性加到多个产品或组|先按类型分组（产品与组不能混批）→ `grant_many` 提交资源 ID 数组与授权项|`effect_count` 与「预期资源数 × 授权项数」扣除逐项失败与未命中后的条数核对一致，且无 `error_messages`|
|确认某个操作需要申请什么级别|按操作范围查[逐路由最低权限级别](#逐路由最低权限级别)，再对照自身在该资源上的级别（`permissions.list` 或 `products.list` 的 `permissions`）|目标操作的级别下限不高于自身级别；不够时请资源所有者或管理员授权，不要更换为猜测的用户 ID|

## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。`resource` 只接受单个产品或产品组的唯一 ID 或名称；批量授权接受数组，且必须是同一类型。客户端只校验参数形状，不比较权限级别、也不在本地拦截：被服务端拒绝的调用原样返回错误（HTTP 403 映射为 `permission_denied`）。

服务端对每个授权项单独校验，失败项不影响其余项，原因随该项返回；`admin` 级别不能通过本接口授予，只能由工作空间管理员或资源创建者身份获得。

## list
读取单个产品或产品组的授权明细。

Python 签名：`rqamsh.permissions.list(resource: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|

返回：服务端原始授权行数组，根对象就是数组；没有授权行时为空数组。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`[]`|授权行数组|array（object 元素）|—|该资源当前的授权行；元素含下列键|恒返回；空数组不等于调用者无权限|
|`[].id`|授权行 ID|string|字符串 ID|该授权行的唯一 ID，用于 `revoke` 与 `grant` 的 `permission_id`|只读|
|`[].resource_id`|资源 ID|string|字符串 ID|该授权行所属产品或产品组的唯一 ID|只读；与请求的 `resource` 同源|
|`[].resource_type`|资源类型|string（枚举）|—|`product` 产品或 `product_groups` 产品组|只读；两种类型的取值写法不一致，产品组带复数后缀|
|`[].user_id`|被授权用户 ID|integer|—|获得该权限的用户 ID|只读|
|`[].permission`|权限级别|string（枚举）|—|该用户在该资源上的级别，取值见[权限级别](#权限级别)|只读；`forbidden` 表示明确不授权|
|`[].workspace_id`|工作空间 ID|string|—|授权生效的工作空间；同一用户在其他工作空间另有授权行|只读|
|`[].shared_by`|授权操作者 ID|integer|—|写下该授权行的用户 ID|只读|

结果检查：先按 `user_id` 找到目标用户所在行，再用该行的 `id` 做调整或撤回；`workspace_id` 不是当前工作空间的授权行不属于本次共享范围。不要用 `products.list` 的 `permissions` 字段替代本操作：那是列表接口顺带返回的本人在各产品上的级别，不是完整的被授权人名单。

```python
result = rqamsh.permissions.list(resource="0123456789abcdef01234567")
```

```console
rqamsh permissions list --resource 0123456789abcdef01234567
```

## grant
为单个产品或产品组新增或调整授权。

Python 签名：`rqamsh.permissions.grant(resource: str, entries: list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`entries`|`list[dict]`|必填|非空授权项数组，元素为下表三键的对象；省略 `permission_id` 时按 `user_id` 新增或覆盖，给出时按该授权行原地调整级别。|

|授权项键|类型|默认/必填|语义|
|---|---|---|---|
|`user_id`|`int`|必填|被授权用户 ID，必须是正整数且不能是布尔值（`true`/`false`）——否则客户端本地抛 `invalid_argument`，请求不会发出。|
|`permission`|`str`|必填|要授予的级别，取值见[权限级别](#权限级别)。|
|`permission_id`|`str`|省略|要调整的授权行 ID，取自 [`list`](#list)；省略时按用户匹配既有授权行。给出时必须为非空白字符串，否则客户端本地抛 `invalid_argument`，请求不会发出。|

返回：服务端原始响应，含实际影响条数与逐项未生效原因。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际影响条数|integer|条|本次新增或调整实际命中的授权行数|恒返回；`0` 表示没有命中，不代表请求失败；见[写入结果](connection.md#write-result)|
|`error_messages`|逐项未生效原因|array（object 元素）|—|按项说明哪一项为何未生效，元素含 `resource_id`、`user_id` 与 `err_msg`|恒返回；非空即抛 `partial_failure`，已生效项不回滚；见[逐项失败容器](connection.md#item-errors)|

结果检查：`effect_count` 与 `error_messages` 可以同时出现，失一项不回滚其他项；按 `err_msg` 修正后只重试失败项。典型原因：被授权用户没有使用该工作空间的权限、授予的级别高于调用者在该资源上的级别、对产品组授权时被授权人是空间管理员或组创建者而其级别高于其在成员产品上的最低级别。

```python
result = rqamsh.permissions.grant(
    resource="0123456789abcdef01234567",
    entries=[{"user_id": 100001, "permission": "read_net_value"}],
)
```

```console
rqamsh permissions grant --resource 0123456789abcdef01234567 --entries '[{"user_id":100001,"permission":"read_net_value"}]'
```

## grant_many
对多个同类型资源批量授权。

Python 签名：`rqamsh.permissions.grant_many(resources: list[str], entries: list[dict[str, Any]])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resources`|`list[str]`|必填|非空资源数组，元素为产品或产品组唯一 ID 或名称；必须是同一类型，产品与产品组混在一批会在本地拒绝。|
|`entries`|`list[dict]`|必填|非空授权项数组，元素只含 `user_id` 与 `permission`；批量形态不接受 `permission_id`。|

返回：服务端原始响应，与 [`grant`](#grant) 相同（`effect_count` 与逐项 `error_messages`；非空即抛 `partial_failure`）。

结果检查：`effect_count` 是命中的「资源 × 授权项」条数，不等于资源数；混批与带 `permission_id` 的输入不会发到服务端，先按类型分组再提交。一次调用只服务一种资源类型。

```python
result = rqamsh.permissions.grant_many(
    resources=["0123456789abcdef01234567"],
    entries=[{"user_id": 100001, "permission": "read_position"}],
)
```

```console
rqamsh permissions grant-many --resources '["0123456789abcdef01234567"]' --entries '[{"user_id":100001,"permission":"read_position"}]'
```

## revoke
撤销单个产品或产品组上指定的授权行。

Python 签名：`rqamsh.permissions.revoke(resource: str, permission_ids: list[str])`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`resource`|`str`|必填|产品或产品组唯一 ID 或名称。|
|`permission_ids`|`list[str]`|必填|非空授权行 ID 数组，取自 [`list`](#list) 返回元素的 `id`；请求体为裸数组。数组为空、或其中任一元素不是非空白字符串时，客户端本地抛 `invalid_argument`，请求不会发出。|

返回：服务端原始响应，含实际删除条数。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`effect_count`|实际删除条数|integer|条|本次实际删除的授权行数|恒返回；`0` 表示没有命中，不代表请求失败；见[写入结果](connection.md#write-result)|

结果检查：授权行不属于该资源时服务端拒绝整批，先核对 `list` 结果再提交；删除自己的授权行需要谨慎，撤销后本人可能失去该资源的访问权。

```python
result = rqamsh.permissions.revoke(resource="0123456789abcdef01234567", permission_ids=["6a1f4c2e9b3d4f5a6b7c8d90"])
```

```console
rqamsh permissions revoke --resource 0123456789abcdef01234567 --permission-ids '["6a1f4c2e9b3d4f5a6b7c8d90"]'
```
