# 项目事实（bootstrap 之后维护）

> 这是本仓库已核实事实的索引，不是模板默认值。没有证据的字段保持 `UNKNOWN`。需要产品或权限决定的字段写明等待维护者确认。

## 身份与约定

- 项目名称 / 一句话：`trending`。A 股趋势指标、日更运维与纸面评估。证据：仓库根 [`README.md`](../README.md)。
- 默认分支：`main`。证据：本仓库跟踪 `origin/main`；本次审阅的安装提交在 `main` 之上一个提交。
- 文档语言：中文。证据：`docs/superpowers/specs/`、`todo.md`，以及本次维护者指示。飞轮模板自带的英文路由与通用基线未改写成第二份规则。
- 时区：数据日更注释写明北京时间 19:00，对应 UTC 11:00。证据：[`.github/workflows/daily-trend.yml`](../.github/workflows/daily-trend.yml) 文件头。复盘调度时区：`UNKNOWN`（本次不配置调度）。
- 技术栈与平台：Python。CI 使用 Python 3.11、`ubuntu-latest`。依赖见 [`requirements.txt`](../requirements.txt)（含 pandas、numpy、PyYAML、pytest、requests、akshare、baostock）。
- 主要入口与运行形态：本地与 GitHub Actions 命令行脚本，不是常驻服务。日更入口是 `python scripts/daily_run.py`，由 workflow 的 metrics 作业调用。离线示例见 [`README.md`](../README.md)。

## 架构与验证

- 子系统索引：见 [`subsystems/README.md`](subsystems/README.md)。行为规格只指向 `docs/superpowers/specs/`，本次不另写当前行为页。
- 格式化 / 静态检查命令：`UNKNOWN`。仓库内未找到 black、ruff、mypy 或 flake8 的配置文件。
- 快速定向测试：`UNKNOWN`。没有单独的标记或子集命令；pytest 配置只设置了 `testpaths = tests`（[`pytest.ini`](../pytest.ini)）。
- 全量测试：在仓库根执行 `python -m pytest tests/ -q`。证据：[`pytest.ini`](../pytest.ini)；[`.github/workflows/daily-trend.yml`](../.github/workflows/daily-trend.yml) 的 Unit tests 步。
- 构建 / 打包：`UNKNOWN`。没有 `pyproject.toml` 或 `setup.cfg`。
- CI workflow 与必需检查：
  - [`daily-trend.yml`](../.github/workflows/daily-trend.yml)：工作日 UTC 11:00 的 schedule，以及 `workflow_dispatch`。权限是 `contents: write` 与 `issues: write`。`sync` 完成才进入 metrics。
  - [`probe-data-sources.yml`](../.github/workflows/probe-data-sources.yml)：仅 `workflow_dispatch`，注释写明用于诊断数据源可达性。
  - [`lesson-promotion-gate.yml`](../.github/workflows/lesson-promotion-gate.yml)：push、pull_request、手动。权限 `contents: read`。只运行 `python3 scripts/validate_lesson_promotions.py`。
  - 2026-10-18 查询 GitHub branch protection API，`main` 返回未保护（HTTP 404）。因此上述 workflow 存在，不等于它们是 required check。
- 集成 / 真实环境验证：日更会访问外部行情源并提交 `data/trend.db`。本次不跑该 workflow，也不读取该库。README 中的离线命令是 `python scripts/daily_run.py --asof <日期> --force-trade-day --offline-calendar --stub-coverage`。凭据与隔离方式：`UNKNOWN`。
- CI 中已知不跑的验证：`probe-data-sources.yml` 不会由 schedule 触发。离线 `daily_run` 命令不是 `daily-trend.yml` 的生产步。
- 测试隔离：`pytest.ini` 未设置独立数据目录。多个测试用 `tmp_path` 写 heartbeat。PR #16 说明曾有全量 pytest 改写 clone 内的 `data/heartbeat.json`。本次不跑全量 pytest。
- 平台 / 客户端矩阵：CI 只记录了 `ubuntu-latest` 与 Python 3.11。其他组合：`UNKNOWN`。
- 已知基线失败的负责人与处理渠道：`UNKNOWN`。

## 风险与权限边界

- 敏感路径：已跟踪的 `data/trend.db`、`data/heartbeat.json`、`data/cache/trade_dates.json`。`.gitignore` 忽略其他 `*.db` 与 `data/cache/*` 的其余内容。已跟踪路径中没有文件名含 credential、secret、`.env` 或 token 的文件。生产行情库内容本次不读。
- 高风险操作：`daily-trend.yml` 可写仓库内容与 Issues，并在 metrics 作业里执行 `python scripts/daily_run.py` 后提交 `data/trend.db` 与 `data/heartbeat.json`。`probe-data-sources.yml` 会访问外部网络。本次未授权运行它们。
- 本次维护者已明确的决定：
  - 文档用中文。
  - 子系统只指向 `docs/superpowers/specs/`，不另写当前行为。
  - 生成数据排除只加 `data/trend.db`。产出过程与理由见 [`automation/range-exclusions.json`](automation/range-exclusions.json)。
  - `LESSONS.md` 的初始排他下界由维护者定为根提交 `b818174d9d04a54909932e23112d0f066ae96d36`。2026-10-18 的日审写入器已把水位推进到该次冻结的 through。不配置复盘调度。
- 指标与运维的既有规格：见子系统索引中的 spec 链接。本次不把规格正文再抄一遍。
- Agent 写权限边界：`UNKNOWN`。本次只授权填写上述项目事实与这一条排除规则，未授权合并、发布、部署或运行日更。
- 是否允许直接合并、发布或部署：`UNKNOWN`。未确认前不视为已授权。
- 外部贡献的拒绝与升级规则：见 [`contributors.md`](contributors.md)。

## 已知限制与审计约定

> 以下为维护者确认可写入的项目记忆（2026-10-18）；细节仍以对应 spec / Lesson 为准，本段只做索引。

- **L2/L1 可信度审计尺子是中期趋势**（多日 FSM 的 T / RS / 右侧等），禁止用同日涨跌新闻或「涨跌榜体感」打假。凉/平 + 高 RS 在贵金属、航运、煤炭等板上可以正确。
- **`float_mv`：** tip / session asof 可用东财 f21 spot；**历史日 / 补旧日禁止今日 spot 回刷**。无历史市值源时全日 null 属 [`market-data-contract` §6](superpowers/specs/2026-10-01-market-data-contract-design.md) 预期，合成走 §6.3 `w_raw=1.0` 再归一（全缺时退化为等权）。勿把历史 asof 的 null 当回归失败。见 L-0020。
- **薄样本热/沸噪声：** `n` 很小（约 ≤3～4）且个别票主导时，L2 板面热/沸常是单票路径，不是行业级中期信号。根因是合成权重下单票占比高（等权 `1/n` 或大流通市值），**不是**成交额权重。接历史 `float_mv`（如 Tushare）主要修等权撕裂，**治不好**薄样本行业幻觉；展示侧用 `n`/集中度脚注或 Issues 降权。
- **board `w2h`：** 展示上的温转热计数来自 `warm_to_hot_member_count`，不等于引擎篮侧 `tag_warm_to_hot`。

## 复盘调度与水位

- 每日复盘的执行方式 / agent：未配置。本次维护者要求不配置调度。
- 运行时刻 / 时区：未配置。数据日更时区见上文，那不是复盘调度。
- 并发、失败重试、超时与部分写入恢复：`UNKNOWN`。没有已配置的复盘调度器。
- 复盘归档位置：`docs/reviews` 是固定根目录；只能在其下选择 Markdown 文件名与日期布局。2026-10-18 的写入器创建了 [`reviews/2026-10-18.md`](reviews/2026-10-18.md)。
- 审阅水位：唯一标记在 [`LESSONS.md`](../LESSONS.md) 第一行。2026-10-18 日审完成后为 `666c78c7cb05f98a33ffc6a1391c9e7c7e40905f`。
- 最近一次复盘日期：2026-10-18（Asia/Shanghai）。归档 [`reviews/2026-10-18.md`](reviews/2026-10-18.md)。
- 教训升格门槛：默认 3 个不同复盘日。见 [`LESSONS.md`](../LESSONS.md)。只有维护者可以明确调整。

## 更新要求

- bootstrap、CI、脚本或发布方式变化时，核实相关字段并更新本文件。
- 只写核实过的事实，并保留来源路径。
- 未知项不要因为反复抄写就变成事实。维护者确认过的决定要写明来源。
