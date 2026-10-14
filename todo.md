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
| **Protocol B** | **已落地**（戳 + sync/`daily_run` 强卡控；Actions cache B） | Spec [`2026-10-10-protocol-b-hard-freeze-stamp-design.md`](docs/superpowers/specs/2026-10-10-protocol-b-hard-freeze-stamp-design.md) · plan [`2026-10-10-protocol-b-hard-freeze-stamp.md`](docs/superpowers/plans/2026-10-10-protocol-b-hard-freeze-stamp.md) · runbook [`hard-freeze-stamp-runbook.md`](docs/ops/hard-freeze-stamp-runbook.md) |
| **`limit_rule` 回退** | **已落地**（强卡控；不清库） | 切回 `vendor_fields` 前须全库清 `board_calc_v1` 限价，否则 `live_shadow.run_asof` 非零 · Spec [`2026-10-11-limit-rule-rollback-guard-design.md`](docs/superpowers/specs/2026-10-11-limit-rule-rollback-guard-design.md) · plan [`2026-10-11-limit-rule-rollback-guard.md`](docs/superpowers/plans/2026-10-11-limit-rule-rollback-guard.md) · CLI `scripts/check_limit_rule_bars.py` |
| **incomplete + asof 限价** | **已落地**（不拆耦；SoT + 强卡控） | `sync_status.json`；`session_asof≥fill_asof`；门在 limit_rule 之前 · Spec [`2026-10-11-incomplete-asof-authority-design.md`](docs/superpowers/specs/2026-10-11-incomplete-asof-authority-design.md) · plan [`2026-10-11-incomplete-asof-authority.md`](docs/superpowers/plans/2026-10-11-incomplete-asof-authority.md) · runbook [`hard-freeze-stamp-runbook.md`](docs/ops/hard-freeze-stamp-runbook.md) |

---

## P1 — 指标 / 成交功能（下一份 feature 候选）

| 项 | 现状 | 要做什么 |
|----|------|----------|
| **止盈辅助标签**（原 §2.7） | **已落地**（只展示）；三标签（个股 `vol_expand` / `champagne` / `danger`；L2 含 `danger`（合成 Σ 可用时）；L1 恒空）；digest「止盈」列；yaml `exit_tags_enabled=true` / `param_version=p05-v5` | 开旗后**不得**改 R / 右侧天数 / 节气；fill / **减仓语义后放**；merge 后 **Protocol B**：目标 `bars.db` 硬冻 pass + 戳对齐 `p05-v5` 再跑 metrics · [`2026-10-11-exit-tags-design.md`](docs/superpowers/specs/2026-10-11-exit-tags-design.md) |
| **节气非线性打分**（原 §2.8） | 个股已有**线性** scorer + 金标；L2 已同引擎纯函数 | NN / 额外 KPI 标定战役后放；勿 silently 改线性默认 |
| **篮子 `VOL_score`** | **已落地**；L2/L1 合成 Σamount/Σfloat_mv → 自身分位；digest「量」可填；`param_version=p05-v5` | 量**不进** RS；merge 后 **Protocol B** 戳一次终值 · [`2026-10-11-basket-vol-score-design.md`](docs/superpowers/specs/2026-10-11-basket-vol-score-design.md) |
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

## 2026-09-30 生产审计（中期趋势尺 · L1+L2）

> 审计日：2026-10-14 · 数据：`/tmp/trend_0930_audit.db`（自 tip `trend.db`；`run_meta` `trade_date=2026-09-30` `status=ok` `git_sha=b8957ce` `param=p05-v5`）· board `/tmp/l2_0930_board.json`  
> Issues 已本地 `--live` 刷成 9.30（非 Actions metrics 步；当时 `skip_issue_update`）  
> **尺子（已纠正）**：T / RS / 右侧 = 多日 FSM **中期**读盘；**不用**同日涨跌/新闻打假。「凉/平 + 高 RS」可以正确。  
> 可信度衡量「Issues/看板 vs 中期角色好不好读」，**不是**「公式有没有算错」。  
> L1：[指标定义](d67ef5dd-4755-4a29-a6fc-7426c1a59f1e) · [医药食品农林](2c34005c-3d2a-4762-9efd-d0131c774588) · [科技传媒电新](ff1bedfd-5291-40c2-9106-2b6566f6274b) · [地产金融可选](fe65dd1a-0d05-42d7-8fd6-ab552d52b1f7) · [制造材料等](181578dd-0852-4180-9cae-460d05fe8b37)  
> L2 中期重审（7 组）：[农林综合](ccd0f715-fd90-4b2c-b277-674002e5daf7) · [医药食品](8137555f-abc6-4211-a8df-6ea55fd09422) · [可选消费](9fda008f-3990-4b7e-b001-9c8c793f4b1f) · [科技传媒电新](5dff2850-863c-4865-a1b0-fa3310c516ab) · [金融地产基建](afc9ed30-cfa2-4fa9-9233-5414a2711ae0) · [制造军工汽车](60393dbf-2576-4aca-b64b-4964b7eae315) · [材料能源交运](5db73542-48ac-424c-9111-a4ae0225d6ef)

### L1（中期尺下）

多数 L1 中期角色与成分/节后轨迹一致。旧尺「食品饮料=2（白酒误导当日体感）」**撤销**：白酒Ⅱ `凉/RS7` 中期冷正确。仍注意：

- L1 合成稀释：地产链沸→L1 温；国有行热→金融凉——默认下钻 L2
- Issues 易把 RS 读成「今日强弱」（如科技硬件 `T=平 RS=100`）
- 日频无日内路径（深 V 只见收盘态）

### L2 硬不符合（DB 已核对）

| 严重度 | L2 | 板面 | 问题 | 处置 |
|--------|-----|------|------|------|
| **已修** | `801120` / `801180` / `801780` | 有 T；RS/amount 空；`801180` 沸+右侧+小暑 | 旧管线残留幽灵板（`universe_id` null）；非现行 taxonomy | `l2_members_map` 仅 §4；`purge_invalid_daily_l2` 每 asof 清非 §4；本地 tip 已清 |
| **预期空** | `460700` 本地生活服务Ⅱ（及 `720800` 社交Ⅱ、`480600` 其他银行Ⅱ） | 缺席 | §4 有码、A 股成员 0（多在港股/无标的） | **不删税表**；无成员 → 不写 `daily_l2` 属正确 |
| **已修** | `240600` 能源金属（脏额） | `寒/RS1` 角色对 | C力勤 `T/RS` 全空却占额 ~58% | `_basket_asof_row`：**T=null 不计入篮 amount** |
| 展示 | `330700` 其他家电Ⅱ | 沸 R=1，n=3 | 奥佳华占额 92% 单票推沸 | **不改引擎**；薄板/浓度提示 |
| 展示 | `330500` 照明设备Ⅱ | 热 RS97 R=1 | 热板冷宽（12 票仅 2 热+） | 同上 |
| 展示 | `340600` 非白酒 | 沸 RS87 R=1 | 会稽山+古越龙山占额 73%；节后仍沸 | 窄结构噪声；浓度提示，勿读成宽度行情 |
| 展示 | `220900` 非金属材料Ⅱ | 凉 RS75，n=8 | 两龙头抬 RS；邻日 75→47 | 薄样本不稳；展示降权 |
| 展示 | `750100` 油气开采Ⅱ | 凉 RS82，n≈3–4 | ≈中国海油（74%） | 同上 |
| 可选 | `620100` 房屋建设Ⅱ | 温 RS33 | 额王中建凉；次日温→平×3 | 边缘日伪温；优先 UX，不必为一日改阈值 |
| 一般不改 | `630600` 风电设备 | 温 S=48.6（温档最低）RS21 | 档内 S/T 拧；「温+低 RS」中期合法 | 不改 FSM |

### L2 结构撕裂（符合中期 · 仅易误读）

篮 T/RS/右侧相对成分众数与节后轨迹**成立**；问题是额王/龙头 T ≠ 篮 T，Issues 一行易误读。**勿当错板改引擎**。

| L2 | 说明 |
|----|------|
| `430100` 房地产开发 | 温+右侧连续；额峰万科/保利已沸 |
| `610100` 水泥 | 0930 温无右侧，次日热+右（进右侧前夜） |
| `110500` 农产品加工 | 平+RS84，金健半仓抬相对强度 |
| `110700` 养殖业 | 宽基凉正确；牧原/温氏温、东瑞沸同屏 |
| `620600` 工程咨询服务Ⅱ | 平；额王太极凉+RS96 |
| `280400` 摩托车及其他 | 轻度虚温，次日回平 |
| `720500` 广告营销 | 边缘温，次日回凉 |

### 明确不算错（旧尺易误伤）

白酒凉/RS7；半导体·通信·电子化学品「平/凉+高 RS」；元件温+RS100+右侧；贵金属/航运/煤炭「凉+高 RS」；航海/地面温+右侧；林业热；种植业平+高 RS；自动化/通用「凉|平+高 RS」。

### 工程债（全日共性）

| # | 项 | 现状 | 要做什么 |
|---|----|------|----------|
| 1 | **`801*` 幽灵板** | **已修**（map 过滤 + purge；tip 已清 3 行） | 下一次完整 metrics 重放即可保持干净 |
| 2 | **`daily_stock.close` 全日 NULL** | 旧库残留 `close` 列；引擎写 `close_qfq` | **已修**：upsert 同步写 `close=close_qfq` |
| 3 | **`float_mv` 全日 null** | sina OHLC 不写市值；asof spot 未接 | **已接**：`--with-limits` 同期拉东财 f21 → `bars.float_mv`；**历史 9.30 不可 spot 回刷**，需等下一日 asof sync + metrics |
| 4 | **`signal_event`「双写」** | **误报**：113 组为 supersede（旧 RS=null → 新有 RS）；**active 重复=0** | 无需改；读盘用 `superseded_by IS NULL` |
| 5 | **高额 `T/RS` null** | 次新/缺史票 | **已修**（篮 amount 排除 T=null） |

### 产品/UX（非算错）

- digest：薄板（n 小）与成交浓度（top1/top2 占比）脚注，避免把窄沸读成宽度行情
- 结构撕裂位：下钻额王 + 成分 T/RS，勿把篮 T 当成龙头 T
- `凉/平 + 高 RS` 文案：强调「相对强、绝对未点火/未确认右侧」

### 下一步

- [x] L1 9.30 体感走查
- [x] L2 中期尺重审（7 组）+ DB 核对汇总
- [x] **必修**：`801*` 过滤+purge；空 §4 板定性；高额 null 剔出篮额
- [x] 工程债：`close` 镜像；`float_mv` asof spot 接入；`signal_event` 误报关闭
- [ ] UX：薄板/浓度脚注；结构撕裂下钻提示（不改 FSM）
- [ ] 下一交易日 asof：确认 `bars.float_mv` / `daily_stock.float_mv` 非空后再看 VOL/权重质量

---


## 不做 / 已钉边界（避免回潮）

- 静默改 `limit_rule` 却不 bump `cost_version`
- asof 日用 board_calc 补限价
- 量价混合进 RS
- 未开旗时实现止盈标签却改动 R / 天数 / 节气
