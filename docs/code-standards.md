# Code standards

This document defines the minimum review standards applicable to all projects, as well as project-specific conventions continuously maintained by the agent based on **current project evidence**. The two kinds of rules must remain in separate sections; do not treat template placeholders, another repository's habits, or unverified assumptions as this project's rules.

## A. General baseline (does not change with the project stack)

### Change correctness

- Understand existing behavior and the single source of truth before changing anything; trace the complete entry points, state/data flow, error paths, and observable side effects, and check analogous entry points and compatibility paths.
- Keep changes to the minimum necessary scope of the request. Avoid opportunistic refactoring, unrelated formatting, and unrequested product behavior changes.
- When fixing a defect, add a regression test that expresses externally observable behavior; where feasible, confirm that the test fails against the old implementation or when the fix is removed. If an automated test cannot be established, record the specific reason and alternative validation; do not describe it as covered.
- Validate the contract, including normal inputs, boundary/exception inputs, state persistence or restart, compatibility with older configuration, and failure handling (as relevant to the change).

### Data, security, and compatibility

- Do not put secrets, user data, or real credentials in test fixtures, logs, screenshots, commits, or reports; use isolated environments for external services and destructive operations.
- Do not mistake unreadable configuration/data for empty configuration and overwrite user data; for stateful writes, prefer preserving existing atomicity, rollback, and recovery conventions.
- Make clear whether the change affects interfaces, serialization formats, migrations, permissions, authentication, network boundaries, observability fields, dependencies, or release artifacts; cover compatible behavior and failure modes.
- Retries, degradation, or fallback must have explicit trigger conditions, idempotency/safety rationale, ordering, and termination conditions; do not silently change the semantics of user input.
- Logs and traces must be sufficient to explain decisions and errors, while following minimization principles and avoiding unnecessary content or sensitive fields.

### Testing and review

- Use the project's actual formatter, static checks, targeted tests, and necessary full-suite tests; report only commands and results that were actually run.
- Test inputs should preserve the structure of real requests, configuration, or disk formats as far as possible, and cover missing and boundary values relevant to the change; fixtures must remove secrets and real personal data.
- For important defect fixes, where feasible revert the fix, inject a fault, or break the protected behavior to confirm that the regression test actually fails; explain limitations preventing this check, and do not treat the mere existence of a test as proof of effective coverage.
- Clean up child processes, asynchronous tasks, temporary directories, ports, and other resources started by tests; check that failure and cancellation paths also terminate or release resources.
- Select platform, client, and alternative-implementation validation according to the change's impact and the project's support scope; explicitly list untested combinations, and do not require unrelated projects to run a nonexistent matrix.
- Check the implementation, tests, documentation, migrations/examples, and adjacent paths together; preserve validation of important compatibility constraints.
- The final report must state clearly: validated items, unvalidated items and reasons, affected subsystems, and the reviewed commit SHA. Checks not run must not be described as passing.
- If the code HEAD changes during validation, review and validate the final HEAD again; before merging, confirm that required checks target the version under review.

## B. Project-specific standards (continuously maintained by the agent)

> Bootstrap must complete this section from the project's source code, tool configuration, CI, existing rules, and real retrospectives; mark unknowns as `UNKNOWN` and include questions requiring confirmation. Do not copy template examples.

### 技术与仓库约定

- 语言、框架与目录：Python。CI 为 Python 3.11。命令行脚本在 `scripts/`，测试在 `tests/`，行为规格在 `docs/superpowers/specs/`。证据：[`requirements.txt`](../requirements.txt)、[`.github/workflows/daily-trend.yml`](../.github/workflows/daily-trend.yml)、[`pytest.ini`](../pytest.ini)。
- 格式化、lint、类型检查与构建：`UNKNOWN`。仓库内没有 black、ruff、mypy 或 flake8 配置，也没有打包配置。
- 依赖、代码生成、迁移与发布：依赖版本钉在 [`requirements.txt`](../requirements.txt)。发布流程：`UNKNOWN`。

### 验收与验证

- 全量测试：仓库根目录 `python -m pytest tests/ -q`。没有单独的定向测试命令。证据：[`pytest.ini`](../pytest.ini) 与 `daily-trend.yml` 的 Unit tests 步。
- CI：`daily-trend.yml`、`probe-data-sources.yml`、`lesson-promotion-gate.yml` 的触发方式与权限见 [`project-profile.md`](project-profile.md)。2026-10-18 查询到 `main` 未被 GitHub branch protection 保护，所以上述 workflow 不是从保护规则读到的 required check。
- 集成与真实环境：日更访问外部行情源并提交 `data/trend.db`。本次不跑、不读该库。全量 pytest 曾改写过 clone 内的 `data/heartbeat.json`（见 PR #16 说明），本次不跑全量 pytest。
- 项目特定的正常、边界、失败与兼容：行为合同以 `docs/superpowers/specs/` 为准，见 [`subsystems/README.md`](subsystems/README.md)。本次不把规格正文抄进本节。

### 项目风险与稳定规则

- 敏感路径与高风险操作：已跟踪 `data/trend.db`、`data/heartbeat.json`、`data/cache/trade_dates.json`。`daily-trend.yml` 拥有 `contents: write` 与 `issues: write`，并会提交数据库。未授权不运行。
- 已确认的设计决定及来源：本次维护者指示——文档用中文；子系统只指向现有 spec；生成数据排除只加 `data/trend.db`；水位保持 `UNKNOWN`；不配置复盘调度。指标与运维的其余决定见对应 spec，不在这里重述。
- Stable rules promoted from Lessons are listed in the block below. Give each rule a unique `PS-0001` ID and cite one or more promoted `L-0001` lesson IDs. The cited lessons must collectively contain at least three distinct, structured review-evidence dates as defined in [`LESSONS.md`](../LESSONS.md).

#### Stable promoted rules

The following bounded block is the authoritative location for project-specific stable promoted rules. Do not count one-off temporary safeguards as stable promotions.

<!-- PROMOTED_RULES:START -->
<!-- PROMOTED_RULES:END -->

If the block is empty, no project-specific stable rule is currently promoted.

Each rule in the block above uses this format:

```markdown
##### PS-0001 — <one executable rule>
- **Scope:** <where the rule applies>
- **Evidence lessons:** `L-0001`, `L-0002`
```

## Maintaining this standard

- The agent may update section B using evidence from `LESSONS.md` and the distinct-date promotion rule; each new convention must state its scope and include an evidence link. Stable promoted rules must use the IDs and cross-references above.
- The read-only Lesson-promotion CI gate validates the persisted record structure and distinct-date threshold. It does not calculate review ranges, create archives, or read or update the `reviewed-through` watermark; humans remain responsible for assessing the cited evidence's authenticity and meaning.
- Section A is the general baseline. If removal or relaxation is needed, first propose a maintainer decision with a risk explanation; do not quietly expand a one-off local exception into a default.
- Whenever CI, test commands, the toolchain, architecture, or an approved policy changes, check whether this section and `docs/project-profile.md` remain accurate.
