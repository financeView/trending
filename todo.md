# trending 待办

> 日期：2026-10-08  
> **A–E 已落地**（Ops 止血 / L1 同引擎 / RS+C1 / 宇宙扩张 / board_calc+硬冻）。下文**只列未实现与可优化项**。  
> 已完成 spec 索引：  
> [A](docs/superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md) ·
> [B](docs/superpowers/specs/2026-10-07-l1-same-engine-design.md) ·
> [C](docs/superpowers/specs/2026-10-07-rs-c1-vol-design.md) ·
> [D](docs/superpowers/specs/2026-10-08-universe-expansion-design.md) ·
> [E](docs/superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md) ·
> [F](docs/superpowers/specs/2026-10-08-workflow-split-jobs-design.md) ·
> [L2 同引擎](docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md)

---

## P0 — Spec E 运维闭环（正确性风险）

改配置却不重写 bars，会让 `param_version` / `cost_version` 与库内事实脱节。

| 项 | 现状 | 要做什么 |
|----|------|----------|
| **Protocol B** | `hard_freeze_min_suspend_days` / `param_version` 无代码护栏 | 钉 runbook：改 N 或 bump `param_version` 前，同环境必须跑完 hard_freeze 全量重写；可选 CI/校验「宣称新版本前旗已重算」 |
| **`limit_rule` 回退** | 切回 `vendor_fields` 只停写，旧 `limit_source=board_calc_v1` 仍被 fill 读 | 文档 + 清库脚本，或 fill/summary 在 YAML 与 `limit_source` 不一致时告警 |
| **incomplete + asof 限价** | `sync_complete=false` 时跳过 `--with-limits`，board_calc 又不补 asof | 产品抉择：是否把 asof 东财限价与 OHLC 预算解耦；未解耦前勿把 partial 当日影子成交当权威 |

---

## P1 — 指标 / 成交功能（下一份 feature 候选）

| 项 | 现状 | 要做什么 |
|----|------|----------|
| **止盈辅助标签**（原 §2.7） | `exit_tags_enabled=false`；波动放大 / 开香槟 / 危险信号未实现 | 开旗后**不得**改 R / 右侧天数 / 节气；只做辅助标签 + 可选减仓语义；对齐 metrics §11 |
| **节气非线性打分**（原 §2.8） | 个股已有**线性** scorer + 金标；L2 已同引擎纯函数 | NN / 额外 KPI 标定战役后放；勿 silently 改线性默认 |
| **篮子 `VOL_score`** | 个股旁路 VOL 已 ship；L2/L1 恒 null（Spec C §2.3） | 若要做：单独切片，量**不进** RS |
| **树外 bars 预热** | Spec D 未做 `sync_bars` 预热 | 宇宙扩张后新成分首日历史不足时再开；非日更阻塞 |

---

## P2 — 评估门禁与产品形态

| 项 | 现状 | 要做什么 |
|----|------|----------|
| **因果 Audit H** | P2 仅有合成 Fri–Mon 窗口 | 冻 `param_version`（+ 对齐 `cost_version` / bars SoT）重放 OHLC → 事件 → fill |
| **Walk-forward 硬门禁** | 全样本一条曲线；两年 WF 未接 | backtest-eval §4.8：`vs_random` / `vs_hs300` 等硬门槛 |
| **实盘 track M / P3 / 影子切片** | 纸面影子在跑；P3 页、实盘 M、`output/eval/live_shadow/` snip 未齐 | 按 ops / backtest Out 清单分批 |

---

## P3 — 可优化 / 不阻塞日更

| 项 | 现状 | 要做什么 |
|----|------|----------|
| **`run_deferred` vs metrics** | **已落地 Spec F**（`sync`+`metrics` 两 job；无 deferred / 生产 time-budget 截断） | 盯 Actions：metrics 在 sync_complete 后必跑；incomplete 仅 warning |
| **fill 审计字段** | summary 有 `limit_rule`/`cost_version`；fill 行无 `limit_source` | 行级或影子摘要带 `limit_source`，方便 Audit H |
| **L1/L2 全历史 replay 成本** | asof 日对全 L2/L1 `synth+replay` 贵；截断 lookback 会改 FSM | `engine_state` / 增量缓存后再做，**勿裸砍 lookback** |
| **个股中文名补全** | loader/digest 已就绪；`stock_sw_l2.yaml` 的 `name_zh` 偶发需有网重跑 | `python3 scripts/taxonomy/patch_stock_names.py --in … --out …` |
| **Spearman 实盘抽样** | CI 金标 + 合成已过；实盘抽样日后放 | Spec C 后放项 |
| **Tushare Pro 限价** | 免费栈（sina / 东财） | 付费表可减 `data_gap`；须新 `limit_rule` + bump `cost_version` |
| **`trend.db` 体积** | 年增量可控则不动 | 必要时按年分库或 git-lfs |
| **日历级缺行挖洞** | 正常全日重放不需要 | P0.5 Out；非阻塞 |
| **pass / cache 可观测** | Spec E 已打非零行数日志；Actions bars cache 按 run_id | 近超时 warn；盯 restore 命中率 |

---

## 不做 / 已钉边界（避免回潮）

- 静默改 `limit_rule` 却不 bump `cost_version`
- asof 日用 board_calc 补限价
- 量价混合进 RS
- 未开旗时实现止盈标签却改动 R / 天数 / 节气
