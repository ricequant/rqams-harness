# 工作空间 workspaces

工作空间是 AMS 的数据分区：产品、产品组、权限、标签、风控条款与自定义标的等记录都带 `workspace_id`，业务请求的 `X-AMS-Workspace` 决定读写落在哪个分区。一个身份可以同时属于多个工作空间，本块用于列举当前身份可见的工作空间，并在同一客户端会话内切换。

列举走 AMS 用户接口（与业务接口同源、前缀为 `/api/user`），需要与业务接口相同的认证入口：本项目不代办登录，认证入口请由管理员提供，或按[连接说明](connection.md)的联调做法注入登录会话；工作空间 ID 不必由外部提供：不指定时默认使用当前身份可见空间中的第一个，需要换分区时再切换，见下节。切换只改变后续请求的数据分区，不改变用户身份，也不影响其他客户端或进程。

## 默认工作空间与切换

不指定工作空间时，默认使用当前身份可见空间中的第一个：客户端在首次业务调用时自行列举并确定，之后一直沿用该分区，不再重复列举。可见空间用 [`list`](#list) 查看；需要换分区时用 [`use`](#use)，可传 ID 或名称，切换后客户端的 `workspace_id` 与请求头同步，后续业务调用都落到新空间。

确定默认分区时，若当前身份没有可见的工作空间，业务调用报 `resource_not_found`（当前身份没有可见的工作空间，无法确定默认分区）；若可见空间的首条记录缺少合法 ID，报 `invalid_response`。两种情况都不会把业务请求发到未知分区。`list` 与 `use` 走用户接口、始终可用，也不触发默认选择。显式传入 `workspace_id` 的调用方行为不变。

```python
with Client(
    base_url="http://127.0.0.1:21015",
    cookies={"sid": "<令牌>"},
) as client:
    for workspace in client.workspaces.list()["data"]:
        print(workspace["id"], workspace["name"])
    client.workspaces.use("目标空间的 ID 或名称")   # 需要换分区时才切换；此后本节所有操作都落到该空间
```

CLI 与 Python 一致：只有 `--base-url` 必需，不指定时同样默认使用可见空间中的第一个；需要指定非默认分区时再带全局 `--workspace-id`：

```console
rqamsh --base-url http://127.0.0.1:21015 --cookie sid=<令牌> products list
rqamsh --base-url http://127.0.0.1:21015 --workspace-id <目标空间的 ID> --cookie sid=<令牌> products list
```

## 从用户需求到操作

|用户需求|操作顺序|完成条件|
|---|---|---|
|确认当前身份能看到哪些工作空间|`list`|返回 `data` 数组，元素含 id、name、admin、capacity、ctime、description、tags、users；空数组表示没有可用空间，未登录会抛 `not_logged_in` 而不是空数组|
|需要换分区时|`list` 记下目标 `id` → `use` 传 ID 或名称 → 切换后先复读目标空间内的资源|返回被选中的空间记录，且客户端 `workspace_id` 与后续请求头都指向它|
|对多个工作空间循环处理|逐个建 `Client`，或在一个客户端上 `use` 逐个切换|每次切换后重新解析资源；不要跨空间复用已解析的资源 ID 或名称|

## API 使用约定

Python 与 CLI 完成相同业务操作，连接与公共错误处理见[连接说明](connection.md)。CLI 每个进程只执行一个操作，`use` 的效果限于该进程；需要指定非默认分区时用全局 `--workspace-id` 选择工作空间。`list` 需要登录会话：未登录时服务端返回 HTTP 200 与 `code` 非 0，客户端映射为 `not_logged_in`。

## list

列举当前身份可见的工作空间。

Python 签名：`rqamsh.workspaces.list()`。无参数。

返回：用户接口原始响应，工作空间数组在 `data` 下。

|英文字段|中文名称|JSON 类型|单位|业务含义|备注|
|---|---|---|---|---|---|
|`data`|工作空间数组|array（object 元素）|—|当前身份可见的工作空间；元素含下列键|恒返回；空数组表示没有可用空间，未登录不会走到这里|
|`data[].id`|工作空间 ID|string|24 位十六进制|工作空间唯一 ID，即业务请求 `X-AMS-Workspace` 的取值|只读|
|`data[].name`|名称|string|—|工作空间名称，可在 [`use`](#use) 中代替 ID|只读；不同空间可能重名|
|`data[].admin`|管理员用户 ID|integer|—|该工作空间的管理员用户 ID|只读|
|`data[].capacity`|成员容量|integer|人|该工作空间允许的成员数上限|只读|
|`data[].ctime`|创建时间|string|YYYY-MM-DD|工作空间创建时间|只读|
|`data[].description`|说明|string|—|工作空间说明|只读|
|`data[].tags`|标签|array（string 元素）|—|服务端给该工作空间打的标签|只读；常见取值 `default`|
|`data[].users`|成员用户 ID|array（integer 元素）|—|属于该工作空间的用户 ID|只读；决定谁可以被授权访问空间内资源|

结果检查：后续判定一律用 `id`，不要用名称做键；`users` 是空间成员名单，与资源上的授权行（见[资源权限](permissions.md)）不是一回事。

```python
result = rqamsh.workspaces.list()
for workspace in result["data"]:
    print(workspace["id"], workspace["name"])
```

```console
rqamsh workspaces list
```

## use

把客户端切到指定工作空间，返回被选中的记录。

Python 签名：`rqamsh.workspaces.use(workspace: str)`。

|参数|类型|默认/必填|语义|
|---|---|---|---|
|`workspace`|`str`|必填|工作空间 ID 或名称；先按 [`list`](#list) 精确匹配，唯一命中才切换。|

返回：被选中的工作空间记录，结构同 [`list`](#list) 的 `data` 元素（见该表）。

结果检查：切换后先用目标空间内的查询复读一次（例如 `products.list`），确认数据分区已改变再写入；未命中报 `resource_not_found` 且不切换，同名多个报 `ambiguous_resource` 并给出候选 ID；空白 `workspace` 在发出请求前报 `invalid_argument`，用户接口 `data` 非数组时报 `invalid_response`。切换作用于共享客户端：切换前取得的资源块后续调用同样落到新空间，原空间的名称/ID 会在新空间重新解释；其他进程不受影响。

```python
record = rqamsh.workspaces.use("一个测试空间")
print(record["id"], record["name"])
```

```console
rqamsh workspaces use --workspace "一个测试空间"
```
