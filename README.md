# rqams-harness

`rqams-harness` 是 Agent 操作 AMS 的 Python API 与 CLI：发行包名 `rqams-harness`，导入名和命令名均为 `rqamsh`。它读取 AMS 业务数据并执行受控写入；估值与业务数据由 AMS 管理，报告加工与第三方系统对接由调用方完成。[业务指南与场景](#文档入口)随 SDK 安装。

## 安装 SDK 与 CLI

要求 Python >= 3.10。在 Agent 或调用方实际使用的 Python 环境中，先从已配置的包索引安装：

```console
python -m pip install rqams-harness
```

没有可用索引，或索引版本未提供 `docs` 命令时，从本仓库选择包含该命令的修订，在仓库根目录运行 `python -m pip install .`（开发时可用 `python -m pip install -e .`）。装好后，切到实际使用的工作区（不要留在 SDK 源码目录），用同一个 Python 自检：

```console
python -m rqamsh --help
python -m rqamsh docs
```

`docs`、`schema` 和 `--help` 离线可用。`rqamsh docs` 返回当前 SDK 的文档目录 `path`、`sdk_version` 和 `docs_sha256`；查某个操作优先用 `rqamsh <块> <操作> --help`，需要完整签名才用 `rqamsh schema`。终端找不到 `rqamsh` 时，先激活安装该包的 Python 环境，或改用 `python -m rqamsh`。

## 认证与连接

未指定地址时优先使用已保存的部署地址，没有保存地址才连接 RQAMS 官方地址 `https://www.ricequant.com`；首次连接私有化部署或切换部署时用 `--base-url` / `base_url` / `RQAMSH_BASE_URL` 指定目标地址。完整地址优先级见[建立连接](docs/connection.md#建立连接)。认证只有 Bearer 令牌，随每个请求发送；令牌由 AMS 平台或管理员签发。

**本机首次使用默认由 Agent 发起网页登录。** 用户要求接入或查询自己的业务数据时，Agent 在安装与离线 `schema` 检查后继续首个相关 CLI 只读查询；没有已保存或已提供的令牌时，命令会打开本机页面，用户在页面填写 key（Bearer 令牌），校验并保存后继续原查询。只问概念或安装方法时不触发登录。不要停在“请提供 token”，也不要让用户把 key 贴进对话。按需接入见[接入与已有上下文](docs/demo/README.md#使用方式用户说业务agent-读文档)。

已有登录设置直接复用；需要重新登录时由 Agent 执行 `rqamsh auth`。默认地址和空间不必让新用户手工填写。Python 的 `rqamsh.init()` / `Client` 不会自动打开登录页，首次使用 Python 前先完成 CLI 登录，再省略 `token` 复用设置。

仅在明确的远程、无图形或无人值守环境中，设 `RQAMSH_AUTO_LOGIN=0`，从权限受限文件或运行环境注入令牌。Agent 调用命令、捕获输出或非交互终端本身不代表没有本机浏览器。令牌不要进入对话、命令字面参数或日志：

```console
rqamsh --token @token.txt products list
# 或由运行环境注入 RQAMSH_TOKEN
```

令牌关联用户而不是某个空间：同一用户可以属于多个工作空间，`rqamsh workspaces list` 读取自己的成员空间。未指定目标空间时，先沿用设置文件里保存的最后空间；没有保存空间就使用服务端成员列表首项（按服务端原序取第一项，不排序、不按 AMS 权益筛选），一个成员空间都没有时直接报错。首项缺少所需权益由服务端拒绝，不会自动换下一个；需要读其他分区时用 `--workspace-id` 或 `workspaces use`。选择空间只改请求路由，能否读写仍由服务端按成员关系、AMS 权益与资源权限判定。随包文档的 `connection.md` 和 `workspaces.md` 说明完整连接与空间规则。

## 更新本地版本

**包：**

- 从仓库 editable 安装：`git pull` 后重跑 `python -m pip install -e .`；依赖有变化时也必须重装。
- 从包索引安装：`python -m pip install --upgrade rqams-harness`。
- 同版本覆盖发布后，普通 `--upgrade` 不会替换已安装包；在已配置内网索引的环境中运行 `python -m pip install --no-cache-dir --force-reinstall --no-deps rqams-harness==0.0.1`。
- 更新后运行 `rqamsh docs`，确认当前文档目录和摘要。

**文档：**

- wheel 和 sdist 都包含公开文档、学习案例及其附件，原稿只在仓库 `docs/` 维护。使用安装版本时从 `rqamsh docs` 返回的目录读文档，无须每次任务拉取仓库。
- 在线 `dev` 用于浏览开发中内容，不替代已安装 SDK 随附的文档；版本级变化见 [CHANGELOG.md](https://github.com/ricequant/rqams-harness/blob/dev/CHANGELOG.md)。

<a id="agent-skill"></a>

## 安装 Agent Skill

1. 先[安装并自检 SDK](#安装-sdk-与-cli)。只用 CLI 或 Python API 时，到这一步即可。
2. 从本仓库源码或解压的源码发行包（`.tar.gz`）取出完整的 `skills/rqamsh/` 目录；没有源码时可从 [GitHub 获取 Skill](https://github.com/ricequant/rqams-harness/tree/dev/skills/rqamsh)。按宿主的 Skill 安装方式添加该目录；手工安装时保持 `rqamsh/SKILL.md` 结构。以 OMP 为例，把 `rqamsh/` 复制到**使用 AMS 的工作区**的 `.omp/skills/` 下，形成 `.omp/skills/rqamsh/SKILL.md`。如果已装过旧版同名 Skill，按宿主的方式移除或停用旧版，避免同时加载两份。无需安装 `ricequant-skills`。
3. 在该工作区启动新会话，让 Agent 使用 `rqamsh`，例如「用 rqamsh 说明实时快照和历史估值的区别，不连接 AMS」。Agent 应从 `python -m rqamsh docs` 返回的 `path` 读取当前 SDK 的业务文档。需要查询实际数据时，再按[认证与连接](#认证与连接)操作。

普通 `pip install` 不安装 Skill，也不写 Agent 目录。只有宿主无法读取 Python 环境中的随包文档时，才运行 `python -m rqamsh docs --skill-dir "<已安装的 rqamsh Skill 目录>"`；该路径必须含 `SKILL.md`。文档同步到其 `sdk-docs/<docs_sha256>/`，不会覆盖 Skill 正文或其他文档修订。更新 Skill 时重新安装本仓库的 `skills/rqamsh/`；更新 SDK 后重跑 `docs`，仅使用同步目录的宿主需要再同步一次。

## 文档入口

从 `rqamsh docs` 返回的目录打开以下入口：

- `index.md`：AMS 业务主线、场景和操作导航。
- `demo/README.md`：学习案例，以及接入、授权与验收。
- `connection.md`：认证、工作空间、调用约定、任务等待和错误处理。

未安装时也可在仓库浏览[业务指南](docs/index.md)、[变更记录](CHANGELOG.md)和[测试与联调](tests/README.md)。

具体 API 的参数、默认值和返回结构在对应业务页的单个 `##` 操作；字段口径查 `docs/fields/`。

## 许可

本软件为米筐科技双许可：

- **非商业用途**（个人出于非商业目的，或高校、研究所等非营利机构出于教育、科研目的）：遵守 [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0)；本软件分发时需保持当前许可“原样”不变，且不得附加任何条件。
- **商业用途**（个人出于任何商业目的，或法人及其他组织出于任何目的）：须先获得米筐科技授权，并在此前提下同样遵守 Apache 2.0 许可；两者冲突之处以当前许可为准。

完整条款见仓库根目录的 [LICENSE](https://github.com/ricequant/rqams-harness/blob/dev/LICENSE)，授权流程请联系 public@ricequant.com。
