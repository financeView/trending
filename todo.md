# trending 待办（后放清单）

> 日期：2026-10-06  
> 已落地：P0 日更骨架 → P0.5 个股 FSM → P1 L1/Radar Issues → P2 纸面影子 → 申万 YAML 映射宇宙 → 2026-09-30 Actions 实跑（`run_meta=partial`，见 P1 缺口）。  
> **§0 已落地**（L2 同引擎 + digest 名称/亿元）。**§2.1 已落地**（L1 同引擎 — Spec B）。  
> **落地顺序（已钉）：A → B → C → D → E**。**A、B 已落地**；**Spec C plan 就绪**（§2.2 价格 RS + C1/Spearman 夹具 + 旁路 VOL）。

---

## 切片路线（A–E）

| Spec | 范围 | 状态 |
|------|------|------|
| **A. Ops 日更止血** | §1.1 limit 软门禁；§1.2 heartbeat / only_date shadow | **已完成** — [`spec`](docs/superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md) / [`plan`](docs/superpowers/plans/2026-10-07-ops-daily-run-hemostasis.md) |
| **B. L1 同引擎** | §2.1（replay 成本后放） | **已完成** — [`spec`](docs/superpowers/specs/2026-10-07-l1-same-engine-design.md) / [`plan`](docs/superpowers/plans/2026-10-07-l1-same-engine.md) |
| **C. RS + C1** | §2.2 + §1.3 表头/排序与真 RS 同发（旁路 VOL；量不进 RS） | **plan 就绪** — [`spec`](docs/superpowers/specs/2026-10-07-rs-c1-vol-design.md) / [`plan`](docs/superpowers/plans/2026-10-07-rs-c1-vol.md) |
| **D. 宇宙扩张** | §2.3 未映射全 A + §2.4 YAML 日拉 | 后放 |
| **E. 成交与冻旗** | §2.5 board_calc / limit_up_unfillable + §2.6 显式硬冻 | 后放 |

§2.7–2.8、§3.* 仍不进 A–E。

---

## 0. ~~下一份 spec~~（已完成）

范围钉死三件事 — **已实现**。  
- Spec：[`docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md`](docs/superpowers/specs/2026-10-06-l2-same-engine-digest-design.md)  
- Plan：[`docs/superpowers/plans/2026-10-06-l2-same-engine-digest.md`](docs/superpowers/plans/2026-10-06-l2-same-engine-digest.md)  
- 遗留：`stock_sw_l2.yaml` 的 `name_zh` 需有网时跑 `python3 scripts/taxonomy/patch_stock_names.py --in config/taxonomy/stock_sw_l2.yaml --out config/taxonomy/stock_sw_l2.yaml`（loader/digest 已就绪）
- 后放（CR）：asof 日对 ~131 L2 各全历史 `synth+replay`；截断历史会改 FSM，需引擎状态/增量缓存后再做，勿裸砍 lookback

### 0.1 同引擎 L2：行业温转热 vs 成分密度拆开

**现状（错误混用）**

- `scripts/metrics/aggregate.py`：P0.5 interim。T = 成分 `float_mv` 加权多数票；右侧 = 成分 `right_side` 加权均值 ≥0.5；节气 = 权重最大且有节气的成分；**`tag_warm_to_hot` = 任意一只成分 tag=1（tag-any）**。
- Issue「行业（L2）扫描」把篮子 T 和 tag-any 写在同一行 → 出现「凉 / 右侧=0 / 温转热=1」（例：[issue #1](https://github.com/financeView/trending/issues/1) `370100`，实际只有 `300016.SZ` 带 tag）。
- metrics [`2026-09-29-trend-metrics-engine-design.md`](docs/superpowers/specs/2026-09-29-trend-metrics-engine-design.md) **§10 / C5** 要求：成分日收益按流通市值加权合成序列，再调用与个股相同的温度/RS/右侧/节气纯函数。`test_C5_same_engine_on_synthetic` 未写。

**权重（已钉，沿用）**

- 成员集：`members_tradable`。
- `w_raw = float_mv if 有值且>0 else 1.0`，再对成员集归一（market-data-contract §6.3）。禁止今日 spot 回刷历史市值。

**目标口径（已口头对齐，写入 spec 时钉死）**

1. **行业自身温转热（0/1）**  
   合成 L2 价格指数 → 与个股同一套 T / FSM / 节气。  
   仅当**行业自己**进入右侧，或右侧内存续「温→热/沸」再确认，才 `tag_warm_to_hot=1`。  
   T=凉且右侧=0 时该列必须为 0。进入日仍只发 `ENTER_RIGHT`，不另发 `WARM_TO_HOT`（metrics §6.0）。
2. **成分温转热密度**  
   另列：该 L2 内个股 `tag_warm_to_hot=1` 的 **个数**（及可选流通市值加权占比）。  
   这是雷达「赚钱效应」，不是行业 FSM 事件。禁止再用 OR 顶行业 tag。
3. **本 slice 只做 L2。** L1 同引擎合成仍走下面 §2.1，Radar 的 L1 `T*` 可暂留 interim，但不得把 L1 的 tag-any 改名义冒充同引擎。

**明确不进本 spec：** 全 A、RS peer、Spearman、WF、board_calc、成分 YAML 日拉。

### 0.2 中文名称

**L2 行业**

- YAML 已有：`config/taxonomy/sw_l2_to_l1.yaml` 的 `name_zh`（如 `370100` → 化学制药）。Issue 表「名称」列现在写的是 6 位码。
- 展示：`化学制药`（可保留码作次要列或括号，spec 钉一种）。

**个股**

- `config/taxonomy/stock_sw_l2.yaml` 目前只有 `ts_code` + `sw_l2_code`，**没有中文名**。
- 展示：`ts_code` 后加中文名（例 `300016.SZ 康拓医疗`）。
- spec 须钉名称源（东财 clist / 现有 sync 字段 / 独立 YAML）、缺失时回退（只显示代码）、是否落 `daily_stock` 或仅渲染层 join。

### 0.3 成交额单位：亿元

- `daily_stock.amount` 现为元；Issue 表直接打印科学计数（`1.065e+09`）。
- 渲染层：`亿元 = amount / 1e8`，固定小数位（spec 钉，例如 2 位）。空值仍空。
- L2 行成交额列今日为空（篮子无 amount）；本 spec 若要填，只允许「成分成交额求和 / 1e8」，不得假装有行业指数成交额。不填则继续空，须在 spec 写死。

---

## 1. 高优先级（本 spec 之后、仍影响已上线日更）

### 1.1–1.2 → Spec A（已完成）

见 [`2026-10-07-ops-daily-run-hemostasis-design.md`](docs/superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md) / plan。  
`ok_predicate_version=v1.2`：asof limit 不足 → `ok`+warn、`last_ok` 前移；heartbeat 读嵌套 `daily_run`；`only_date` shadow 钉 `--asof`。

### 1.3 Issue 表 RS 全空

- `daily_* .RS` 列为 stub/null；「右侧存续 Top（RS 高）」实际在按空 RS + 成交额排。
- 正式 RS 见 §2.2，不要在 §0 用成交额冒充 RS 而不改表头。

---

## 2. 中优先级（指标引擎补全，C5 的邻居）

### 2.1 ~~L1 同引擎合成~~（已完成 — Spec B）

- Spec：[`2026-10-07-l1-same-engine-design.md`](docs/superpowers/specs/2026-10-07-l1-same-engine-design.md) / plan [`2026-10-07-l1-same-engine.md`](docs/superpowers/plans/2026-10-07-l1-same-engine.md)
- 后放（CR）：L1 全历史 replay 成本 / `engine_state` 增量（与 L2 §0 后放同型）

### 2.2 RS peer 宇宙 + Spearman / `test_C1`

- metrics §9：`RS = percentile_rank(RS_raw among peer)`；`local_stock` / `local_l2` / `local_l1` 隔离；ST/停牌不进 stock peer。
- `test_RS_peer_universes`、`test_RS_eligibility_tradable`、`test_C1_temp_feature_allowlist`、Spearman(`rank(T)`, `S_temp`) ≥ 0.55 均未做。
- 量价混合 RS v1.1 可跟本条。README 已列为 still out of ship。

### 2.3 未映射全 A sync

- 当前 U = YAML 已映射 SH/SZ。quarantine、无二级、北交所不进树、不进全量 bars。
- taxonomy：`unmapped_count` 生产门禁、IPO 三日未归属告警未接。
- **不要**把 U 缩成「有 bar 的子集」来刷 coverage。

### 2.4 成分 YAML 每日 vendor 拉新

- `stock_sw_l2.yaml` 是 check-in 快照；fetch 脚本一次性归一 §4 码。cron 不改映射。后续 `map_version` bump。

### 2.5 `board_calc_v1` 与 `limit_up_unfillable`

- 缺 vendor `limit_*` → `data_gap`，不成交、不猜板。显式 `limit_rule=board_calc_v1` 且 bump `cost_version` 才允许推算。
- 涨停买不进：`limit_up_unfillable`（P2 Out）。

### 2.6 `hard_frozen` 扩到显式冻旗

- MVP = `is_st`。`explicit_hard_freeze_flag` 列、软冻≠硬冻的完整数据路径仍缺。

### 2.7 止盈辅助标签 §11

- `exit_tags_enabled=false`：波动放大 / 开香槟 / 危险信号。开旗后不得改 R/天数/节气。

### 2.8 节气：非线性打分与标定战役

- 个股路径已有线性 scorer + 金标夹具。L2 interim 节气是「最重成分」。同引擎后 L2 走纯函数；NN/额外 KPI 战役仍后放。

---

## 3. 低优先级（评估门禁与产品形态）

### 3.1 因果 Audit H

- 冻 `param_version` 重放 OHLC → 事件 → fill。P2 只有合成 Fri–Mon 窗口，不是因果 H。

### 3.2 Walk-forward / `vs_random` / `vs_hs300` 硬门禁

- backtest-eval §4.8。全样本一条曲线不作数。两年 WF 未接。

### 3.3 实盘 track M、P3 页面、`output/eval/live_shadow/` 切片

- P1 Out：P3 pages。P2 Out：实盘 M、snip files。

### 3.4 Tushare Pro 升级

- 现免费栈（sina / 东财）。付费限价表可替代部分 `data_gap`，须新 `limit_rule` 标注。

### 3.5 `trend.db` 体积

- ops：年增量可控则不动；必要时按年分库或 git-lfs。现不阻塞。

### 3.6 日历级缺行挖洞

- 正常全日重放不需要。P0.5 Out。

---

## 对照（避免漏项）

| 项 | 优先级 | 进下一份 spec？ |
|----|--------|-----------------|
| L2 同引擎 + 温转热/密度拆列 | §0 | 是 |
| L2 `name_zh`、个股中文名 | §0 | 是 |
| 成交额亿元 | §0 | 是 |
| L1 同引擎 | §2.1 | 否 |
| 假日 asof / limit → partial | §1.1 | 否 |
| only_date heartbeat/Issues | §1.2 | 否 |
| RS / Spearman / C1 | §2.2 | 否 |
| 未映射全 A、YAML 日拉 | §2.3–2.4 | 否 |
| board_calc、硬冻旗、止盈 tag | §2.5–2.7 | 否 |
| 因果 H、WF、P3、实盘 M | §3 | 否 |
