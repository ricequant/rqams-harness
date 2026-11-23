# rqams-harness

`rqams-harness` 是 Agent 操作 AMS 的 Python API 与 CLI：发行包名 `rqams-harness`，导入名和命令名均为 `rqamsh`。它读取 AMS 业务数据并执行受控写入；估值与业务数据由 AMS 管理，报告加工与第三方系统对接由调用方完成。[业务指南与场景](#文档入口)随 SDK 安装。

## 安装

要求 Python >= 3.10。在本项目目录或按发布渠道安装：

```console
python -m pip install -e .
# 或安装发布包：python -m pip install rqams-harness

rqamsh --help
rqamsh docs
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

## Agent Skill

技能族位于 [ricequant-skills](https://github.com/ricequant/ricequant-skills) 的 `skills/basic/rqams` 下。安装或更新 SDK 后，由 Skill 安装流程运行 `rqamsh docs --skill-dir <rqamsh 子技能目录>`，文档写入该目录的 `sdk-docs/<docs_sha256>/`，不改动 `SKILL.md` 或覆盖其他修订。普通 `pip install` 只安装 Python 环境中的文档，不写用户的 Agent 目录；不需要复制时可直接读 `rqamsh docs` 返回的随包路径。

按当前目标阅读学习案例与共用判断；接入、目标拆解、任务完成条件和写入计划按需使用，不把新会话当作重走固定流程的理由。缺项或运行态进入等待诊断，写入前核对授权及目标操作规则。Skill 中的必读触发条件不替代这些业务权威页。

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
