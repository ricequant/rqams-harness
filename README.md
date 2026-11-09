# rqams-harness

`rqams-harness` 是 Agent 操作 AMS 的 Python API 与 CLI：发行包名 `rqams-harness`，导入名和命令名均为 `rqamsh`。它取回 AMS 已算好、已落库的业务数据，并执行受控写入；估值与业务数据由 AMS 管理，分析、报告渲染、第三方系统对接由 Agent 或第三方完成。业务主线、业务块导航、常见场景和能力边界见 [AMS 业务与 API 使用指南](https://github.com/ricequant/rqams-harness/blob/dev/docs/index.md)；问题拆解、能力组织与业务验收见[学习案例与共用判断](https://github.com/ricequant/rqams-harness/blob/dev/docs/demo/README.md)。

## 安装

要求 Python >= 3.10。在本项目目录或按发布渠道安装：

```console
python -m pip install -e .
# 或安装发布包：python -m pip install rqams-harness

rqamsh --help
rqamsh schema
```

`schema` 和 `--help` 离线可用，`schema` 是当前安装版本的运行时契约。终端找不到 `rqamsh` 时，先激活安装该包的 Python 环境，或改用 `python -m rqamsh`。

## 认证与连接

未指定地址时优先使用已保存的部署地址，没有保存地址才连接 RQAMS 官方地址 `https://www.ricequant.com`；首次连接私有化部署或切换部署时用 `--base-url` / `base_url` / `RQAMSH_BASE_URL` 指定目标地址。完整地址优先级见[建立连接](docs/connection.md#建立连接)。认证只有 Bearer 令牌，随每个请求发送；令牌由 AMS 平台或管理员签发。

**本机首次使用默认由 Agent 发起网页登录。** 用户要求接入或查询自己的业务数据时，Agent 在安装与离线 `schema` 检查后继续首个相关 CLI 只读查询；没有已保存或已提供的令牌时，命令会打开本机页面，用户在页面填写 key（Bearer 令牌），校验并保存后继续原查询。只问概念或安装方法时不触发登录。不要停在“请提供 token”，也不要让用户把 key 贴进对话。按需接入见[接入与已有上下文](docs/demo/README.md#使用方式用户说业务agent-读文档)。

已有登录设置直接复用；需要重新登录时由 Agent 执行 `rqamsh auth`。默认地址和空间不必让新用户手工填写。Python 的 `rqamsh.init()` / `Client` 不会自动打开登录页，首次使用 Python 前先完成 CLI 登录，再省略 `token` 复用设置。

仅在明确的远程、无图形或无人值守环境中，设 `RQAMSH_AUTO_LOGIN=0`，从权限受限文件或运行环境注入令牌。Agent 调用命令、捕获输出或非交互终端本身不代表没有本机浏览器。令牌不要进入对话、命令字面参数或日志：

```console
rqamsh --token @token.txt products list
# 或由运行环境注入 RQAMSH_TOKEN
```

令牌关联用户而不是某个空间：同一用户可以属于多个工作空间，`rqamsh workspaces list` 读取自己的成员空间。未指定目标空间时，先沿用设置文件里保存的最后空间；没有保存空间就使用服务端成员列表首项（按服务端原序取第一项，不排序、不按 AMS 权益筛选），一个成员空间都没有时直接报错。首项缺少所需权益由服务端拒绝，不会自动换下一个；需要读其他分区时用 `--workspace-id` 或 `workspaces use`。选择空间只改请求路由，能否读写仍由服务端按成员关系、AMS 权益与资源权限判定，不要通过修改请求头扩大授权。令牌、设置文件与工作空间规则见[连接、身份、错误与等待](https://github.com/ricequant/rqams-harness/blob/dev/docs/connection.md)，成员空间的读取与选择见[工作空间](https://github.com/ricequant/rqams-harness/blob/dev/docs/workspaces.md)。

## 更新本地版本

**包：**

- 从仓库 editable 安装：`git pull` 后重跑 `python -m pip install -e .`；依赖有变化时也必须重装。
- 从包索引安装：`python -m pip install --upgrade rqams-harness`。
- 同版本覆盖发布后，普通 `--upgrade` 不会替换已安装包；在已配置内网索引的环境中运行 `python -m pip install --no-cache-dir --force-reinstall --no-deps rqams-harness==0.0.1`。
- 更新后运行 `rqamsh schema`，确认当前操作和参数。

**文档：**

- 本地克隆：切到 `dev` 后运行 `git pull --ff-only`，不要继续读旧副本。
- 直接读 GitHub：本次内网发布对应 `dev` 分支，重新获取该分支的 raw 页面。
- wheel 不含 `docs/`；需要文档时使用仓库或 sdist。学习案例、脚本及必要材料统一放在 `docs/demo/`，获取完整 `docs/` 才能保留树内相对链接；只复制单页不会自动带上它引用的页面和附件。
- 文档与安装版本不一致时，以 `rqamsh schema` 为准；版本级变化见 [CHANGELOG.md](https://github.com/ricequant/rqams-harness/blob/dev/CHANGELOG.md)。

## Agent Skill

技能族位于 [ricequant-skills](https://github.com/ricequant/ricequant-skills) 的 `skills/basic/rqams` 下。它只做入口导航和判断规则，不复制文档；参数、返回和业务口径仍以本仓库 `docs/` 与 `rqamsh schema` 为准。更新技能时重新获取技能族并覆盖本地副本；已安装的技能副本不会自动跟随远端。技能、包和文档分别更新，本包版本变化只记录在 `CHANGELOG.md`，不再在文档里维护历史兼容说明。

按当前目标阅读学习案例与共用判断；接入、目标拆解、任务完成条件和写入计划按需使用，不把新会话当作重走固定流程的理由。缺项或运行态进入等待诊断，写入前核对授权及目标操作规则。Skill 中的必读触发条件不替代这些业务权威页。发布或更新时分别同步技能、包与文档；只修改本地文档不会自动改变其他用户安装的技能或在线读取的内容。

## 文档入口

- [AMS 业务与 API 使用指南](https://github.com/ricequant/rqams-harness/blob/dev/docs/index.md)：业务主线、业务块导航、常见场景、口径速查和必要边界。
- [学习案例与共用判断](docs/demo/README.md)：从流水更正、估值表导入、对账、收益诊断、简报和规模汇总学习问题拆解、能力组织与证据判断；共用的接入、授权与验收边界按需使用，不是全量功能目录或执行台账。
- [连接、身份、错误与等待](https://github.com/ricequant/rqams-harness/blob/dev/docs/connection.md)：认证、工作空间、调用约定、返回结构、任务等待和错误处理。
- [测试与联调](https://github.com/ricequant/rqams-harness/blob/dev/tests/README.md)：契约测试范围、只读联调配方和实测量级。
- [变更记录](https://github.com/ricequant/rqams-harness/blob/dev/CHANGELOG.md)：按版本记录用户可见改动。

具体 API 的参数、默认值和返回结构在对应业务页的单个 `##` 操作；字段口径查 `docs/fields/`。

## 许可

本软件为米筐科技双许可：

- **非商业用途**（个人出于非商业目的，或高校、研究所等非营利机构出于教育、科研目的）：遵守 [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0)；本软件分发时需保持当前许可“原样”不变，且不得附加任何条件。
- **商业用途**（个人出于任何商业目的，或法人及其他组织出于任何目的）：须先获得米筐科技授权，并在此前提下同样遵守 Apache 2.0 许可；两者冲突之处以当前许可为准。

完整条款见仓库根目录的 [LICENSE](https://github.com/ricequant/rqams-harness/blob/dev/LICENSE)，授权流程请联系 public@ricequant.com。
