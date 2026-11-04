# 工作空间 workspaces

工作空间是 AMS 的数据分区：产品、产品组、权限、标签、风控条款与自定义标的等记录都带 `workspace_id`。Bearer 令牌是用户级凭据，一个用户可以是多个工作空间的成员；本块读取当前用户全部成员空间，并为后续业务请求确定目标空间：未显式指定且没有可沿用的保存空间时，默认使用成员列表首项。选择空间只决定请求落到哪个分区，不增加业务权限：成员关系、AMS 权益与资源级权限仍由服务端在业务请求上判定。

认证入口是 `Authorization: Bearer <token>`；人工首次可使用浏览器登录，Agent 与自动化场景用 `--token @文件` 或 `RQAMSH_TOKEN` 注入，不代办账号密码登录。成员空间来自同一部署的用户服务 `GET <部署>/api/user/v1/workspaces`（官方地址即 `https://www.ricequant.com/api/user/v1/workspaces`，私有化部署保留自己的部署路径前缀，例如 `https://ams.example.com/api/user/v1/workspaces`）。该请求只带 `Authorization`，不携带 `X-AMS-Workspace`、Cookie 或伪造的用户头，也不跟随重定向；客户端不会把令牌发到其他 origin，也不提供单独的用户服务地址配置。地址规则是：把业务地址去掉固定尾缀 `/api/rqams/v2` 后接 `/api/user`，两套接口必须同 origin、同部署前缀。旧的令牌上下文接口已不再提供，客户端也没有对应回退。

<a id="默认工作空间与切换"></a>
## 默认工作空间与切换

不指定工作空间时，按身份来源与成员空间列表决定目标分区；没有任何成员空间时业务请求不会发出：

|情形|行为|
|---|---|
|显式提供 `workspace_id` / `--workspace-id` / `RQAMSH_WORKSPACE_ID`|直接作为请求路由，不查成员列表；不是成员或没有 AMS 权益时由服务端拒绝|
|复用同部署保存的令牌，设置文件已保存最后选择的空间|直接使用该空间，不请求成员列表|
|未指定，当前令牌没有任何成员空间|报 `resource_not_found`，不发业务请求；该结果表示当前用户没有成员空间，不是令牌无效|
|未指定，当前令牌有成员空间|使用服务端当次返回的首项 `data[0]`，继续本次调用|

“首项”严格指服务端当次返回数组的第一个元素：客户端不排序、不按名称或 ID 取最小项，也不按 AMS 权益筛选。首项缺少本次请求所需权益时，业务请求由服务端拒绝，客户端不会改用第二项重试；服务端也不保证列表顺序稳定，自动默认只按当次返回决定。人工浏览器登录保存目标空间的规则见[认证与令牌](connection.md#token-auth)。

复用保存身份时，显式指定、`use` 成功以及自动选中首项都会写回“最后空间”；后续启动沿用该空间，不因成员列表后来增减而自动换空间。它不是授权缓存：成员被移除或权益变化后，服务端仍会拒绝请求，客户端也不会自动改选其他空间。显式、环境或文件注入的令牌不继承该空间，也不会写回设置文件；策略与设置文件规则见[认证与令牌](connection.md#token-auth)。

```python
rqamsh.init(token="<令牌>")
for workspace in rqamsh.workspaces.list()["data"]:
    print(workspace["id"], workspace.get("name"))
selected = rqamsh.workspaces.use(workspace="<成员空间 ID>")
print(selected["id"])
rqamsh.close()
```

CLI 的人工首次业务命令缺少设置时会尝试浏览器登录并继续该命令；Agent 与无图形环境应注入令牌。不指定 `--workspace-id` 时按上表解析目标空间：

```console
rqamsh workspaces list                              # 只列出成员空间，不改变当前空间
rqamsh --workspace-id <成员空间 ID> products list    # 本次调用指定目标空间
rqamsh workspaces use --workspace "<成员空间 ID>"    # 切换当前客户端的目标空间
```

## 相关学习案例

先读[定位空间与目标产品](demo/workspace-routing/README.md)，确认成员空间、目标产品和权限，再进入具体业务案例。

## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。CLI 每次进程执行一个操作；仅复用保存身份时，`use` 与自动选中的首项都会把目标空间写回设置文件，注入临时令牌不会改写该设置。切换空间会作废该客户端的资源索引与详情缓存，下次解析按新分区重建；失败的选择不改变当前空间、请求头、缓存或设置。

`client.use_workspace(workspace_id)` 是低层路由设置：只校验 24 位十六进制格式并更新请求头与缓存，不核对成员列表，也不代表授权成功；需要先确认成员关系时用 `workspaces.use`。`workspace_id` 只选择请求分区，不是凭证；成员空间列表也不等于 AMS 订阅权益或某个产品的读写权限，见[资源权限](permissions.md)。

## list

读取当前 PAT 用户的成员工作空间，不要求、也不改变当前目标空间。

Python 签名：`rqamsh.workspaces.list()`。无参数。

返回：`{"data": [记录]}`，数组由服务端按当前用户的成员关系生成；空数组合法。每次调用都读取服务端，客户端不缓存成员列表。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`data`|成员空间数组|array（object 元素）|—|当前用户所属的全部工作空间|恒返回；未指定目标时默认取本数组首项，但顺序不保证稳定，跨次指认一律按 `id`；缺失或非数组时抛 `invalid_response`|
|`data[].id`|工作空间 ID|string|24 位十六进制|空间唯一 ID，也是业务请求 `X-AMS-Workspace` 的取值|恒返回；只读；重复或格式非法时抛 `invalid_response`|
|`data[].name`|工作空间名称|string|—|可读名称，供展示与让用户确认目标|恒返回；名称不唯一，不能当键|
|`data[].admin`|管理员用户 ID|integer|—|该空间管理员的用户 ID|恒返回；只读；整数用户 ID，不是邮箱或姓名|
|`data[].capacity`|成员数上限|integer|人|该空间允许的成员数量上限|恒返回；只读；已满不代表不能读取|
|`data[].users`|成员用户 ID|array（integer 元素）|—|该空间当前成员的用户 ID|由数据决定；元素是整数用户 ID，不是用户资料|
|`data[].ctime`|创建日期|string|`YYYY-MM-DD`|空间创建日期|恒返回；只到日期，不含时刻与时区|
|`data[].tags`|空间标签|array（string 元素）|—|服务端给空间打的标签|由数据决定；可为空数组；`default` 标记用户注册时创建的默认空间|
|`data[].description`|空间描述|string / null|—|空间说明文本|由数据决定；未填写时缺键或为 `null`，不要用空字符串代替|

结果检查：指认空间一律用 `id`，不要用名称；数组顺序只在未指定目标时决定自动默认（取首项），不代表排序或优先级。成员列表只证明当前用户属于这些空间，不证明能读写其中任何产品。

```python
result = rqamsh.workspaces.list()
for workspace in result["data"]:
    print(workspace["id"], workspace.get("name"))
```

```console
rqamsh workspaces list
```

## use

按成员空间 ID 选择后续业务请求的目标空间，返回实际命中的成员记录。

Python 签名：`rqamsh.workspaces.use(workspace: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`workspace`|`str`|必填|当前用户所属工作空间的精确 ID（区分大小写）；不按名称匹配，也不接受其他空间的 ID。|

返回：被选中的成员空间记录，结构同 [`list`](#list) 的 `data` 元素（见该表）。

结果检查：核对返回 `id`、客户端 `workspace_id` 与后续请求头都是所选 ID；选择只改目标分区，读写是否获准仍由服务端判定，写入前复读目标资源。非成员或不存在报 `resource_not_found`（HTTP 404），空白 `workspace` 在发出请求前报 `invalid_argument`，成员列表响应不合法报 `invalid_response`；这些失败都不改变当前空间、请求头、缓存与设置文件。成功切换只影响当前共享客户端，其他已运行进程不受影响。

```python
record = rqamsh.workspaces.use(workspace="<成员空间 ID>")
print(record["id"])
```

```console
rqamsh workspaces use --workspace "<成员空间 ID>"
```
