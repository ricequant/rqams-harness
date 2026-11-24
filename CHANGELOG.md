# 变更记录

| **rqamsh 版本** | **发布日期** | **新增** | **改善** | **不兼容改动** |
|---|---|---|---|---|
| 0.0.1 | 待发布 | Python API 与 CLI，覆盖 AMS 查询、导入、分析及模拟交易，支持离线 `schema` 与 `--help`；见[业务导航](docs/index.md)与[模拟交易](docs/paper_trading.md)。<br>支持 Bearer 令牌、本机浏览器登录、保存身份复用与成员空间选择；见[连接与认证](docs/connection.md)及[工作空间](docs/workspaces.md)。<br>可独立安装 [Agent Skill](README.md#agent-skill)，并离线查阅随 SDK 提供的[业务文档与学习案例](docs/demo/README.md)。 | 减少资源解析中的详情请求，完善归因参数校验与产品组结果的缺项提示。<br>[批量实时头寸](docs/balances.md#批量实时截面)有界续查原集合，只返回最后一轮金额并逐项报告截止缺项。<br>补充资源创建、[估值结果判断](docs/index.md#valuation-readiness)及分析异常处理的使用指引；细化写入、重算、删除和失败处理契约，区分预期效果与已确认的实现偏差。<br>[流水场景](docs/demo/trades/README.md)覆盖首次历史接入、持续同步、文件结算接管和迟到报告校准，保留单笔更正实测及估值影响核验；明确稳定外部键重发不重复记账但仍触发计算，业务说明聚焦有效流水与替换结果。 | |
