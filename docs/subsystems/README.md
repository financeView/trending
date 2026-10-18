# 子系统索引

> 本次只把职责指向已有规格，不另写当前行为页。`TEMPLATE.md` 仍是空模板，没有按它复制新页。行为以 `docs/superpowers/specs/` 为准。

## 规格索引

| 职责 | 不在本页重述的边界 | 规格 |
| --- | --- | --- |
| 行业分类与股票池 | 成员、映射与宇宙扩张的当前规则 | [`2026-09-28-industry-taxonomy-design.md`](../superpowers/specs/2026-09-28-industry-taxonomy-design.md)、[`2026-10-05-sw-yaml-universe-design.md`](../superpowers/specs/2026-10-05-sw-yaml-universe-design.md)、[`2026-10-08-universe-expansion-design.md`](../superpowers/specs/2026-10-08-universe-expansion-design.md) |
| 行情合同与硬冻 | bars、戳、限价回退、asof 权限 | [`2026-10-01-market-data-contract-design.md`](../superpowers/specs/2026-10-01-market-data-contract-design.md)、[`2026-10-08-spec-e-fill-hard-freeze-design.md`](../superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md)、[`2026-10-10-protocol-b-hard-freeze-stamp-design.md`](../superpowers/specs/2026-10-10-protocol-b-hard-freeze-stamp-design.md)、[`2026-10-11-limit-rule-rollback-guard-design.md`](../superpowers/specs/2026-10-11-limit-rule-rollback-guard-design.md)、[`2026-10-11-incomplete-asof-authority-design.md`](../superpowers/specs/2026-10-11-incomplete-asof-authority-design.md) |
| 趋势指标 | FSM、L1/L2、RS、止盈标签、篮子量 | [`2026-09-29-trend-metrics-engine-design.md`](../superpowers/specs/2026-09-29-trend-metrics-engine-design.md)、[`2026-10-06-l2-same-engine-digest-design.md`](../superpowers/specs/2026-10-06-l2-same-engine-digest-design.md)、[`2026-10-07-l1-same-engine-design.md`](../superpowers/specs/2026-10-07-l1-same-engine-design.md)、[`2026-10-07-rs-c1-vol-design.md`](../superpowers/specs/2026-10-07-rs-c1-vol-design.md)、[`2026-10-11-exit-tags-design.md`](../superpowers/specs/2026-10-11-exit-tags-design.md)、[`2026-10-11-basket-vol-score-design.md`](../superpowers/specs/2026-10-11-basket-vol-score-design.md) |
| 日更作业 | sync 与 metrics 的分工 | [`2026-10-07-ops-daily-run-hemostasis-design.md`](../superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md)、[`2026-10-08-workflow-split-jobs-design.md`](../superpowers/specs/2026-10-08-workflow-split-jobs-design.md) |
| 纸面评估 | 回测与影子账 | [`2026-09-30-backtest-eval-design.md`](../superpowers/specs/2026-09-30-backtest-eval-design.md)、[`2026-09-30-ops-action-and-eval-design.md`](../superpowers/specs/2026-09-30-ops-action-and-eval-design.md) |
| Issue 与榜单展示 | digest 与雷达的展示合同 | [`2026-10-10-digest-radar-ux-design.md`](../superpowers/specs/2026-10-10-digest-radar-ux-design.md) |

实现入口仍在 `scripts/`。验收命令见 [`../project-profile.md`](../project-profile.md)。

## 修改约定

行为、接口、状态、失败或兼容性变了，改上表对应的 spec。不要在 `docs/subsystems/` 再写一份当前行为。本索引只在规格文件增删或职责归属变化时一起改。

未核实的边界保持 `UNKNOWN`，不按目录名拆分模块。
