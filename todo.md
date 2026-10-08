# trending 待办（后放清单）

> 日期：2026-10-08  
> 已落地：P0 日更骨架 → P0.5 个股 FSM → P1 L1/Radar Issues → P2 纸面影子 → 申万 YAML 映射宇宙 → 2026-09-30 Actions 实跑（`run_meta=partial`，见 P1 缺口）。  
> **§0 已落地**（L2 同引擎 + digest 名称/亿元）。**§2.1 已落地**（L1 同引擎 — Spec B）。**§1.3 / §2.2 已落地**（价格 RS + S_temp/C1 + 个股旁路 VOL — Spec C）。**§2.3–2.4 已落地**（YAML 日拉 + unmapped 计数/IPO 告警 — Spec D）。  
> **落地顺序（已钉）：A → B → C → D → E**。**A–E 已落地**（§2.5 board_calc / limit_up_unfillable + §2.6 显式硬冻 — Spec E）。

---

## 切片路线（A–E）

| Spec | 范围 | 状态 |
|------|------|------|
| **A. Ops 日更止血** | §1.1 limit 软门禁；§1.2 heartbeat / only_date shadow | **已完成** — [`spec`](docs/superpowers/specs/2026-10-07-ops-daily-run-hemostasis-design.md) / [`plan`](docs/superpowers/plans/2026-10-07-ops-daily-run-hemostasis.md) |
| **B. L1 同引擎** | §2.1（replay 成本后放） | **已完成** — [`spec`](docs/superpowers/specs/2026-10-07-l1-same-engine-design.md) / [`plan`](docs/superpowers/plans/2026-10-07-l1-same-engine.md) |
| **C. RS + C1** | §2.2 + §1.3 表头/排序与真 RS 同发（旁路 VOL；量不进 RS） | **已完成** — [`spec`](docs/superpowers/specs/2026-10-07-rs-c1-vol-design.md) / [`plan`](docs/superpowers/plans/2026-10-07-rs-c1-vol.md) |
| **D. 宇宙扩张** | §2.3 unmapped 计数/IPO 告警 + §2.4 YAML 日拉（**不含**树外 bars 预热） | **已完成** — [`spec`](docs/superpowers/specs/2026-10-08-universe-expansion-design.md) / [`plan`](docs/superpowers/plans/2026-10-08-universe-expansion.md) |
| **E. 成交与冻旗** | §2.5 board_calc / limit_up_unfillable + §2.6 显式硬冻 | **已完成** — [`spec`](docs/superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md) / [`plan`](docs/superpowers/plans/2026-10-08-spec-e-fill-hard-freeze.md) |

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

### 1.3 ~~Issue 表 RS 全空~~（已完成 — Spec C）

- `daily_stock` / 篮子行写入真 RS + `S_temp`；个股 `VOL_score` 旁路已 ship；L2/L1 `VOL_score` 恒 null（篮子量分后放）。
- digest「右侧存续 Top（RS 高）」按 RS → VOL → 成交额；Spec：[`2026-10-07-rs-c1-vol-design.md`](docs/superpowers/specs/2026-10-07-rs-c1-vol-design.md) / plan [`2026-10-07-rs-c1-vol.md`](docs/superpowers/plans/2026-10-07-rs-c1-vol.md)

---

## 2. 中优先级（指标引擎补全，C5 的邻居）

### 2.1 ~~L1 同引擎合成~~（已完成 — Spec B）

- Spec：[`2026-10-07-l1-same-engine-design.md`](docs/superpowers/specs/2026-10-07-l1-same-engine-design.md) / plan [`2026-10-07-l1-same-engine.md`](docs/superpowers/plans/2026-10-07-l1-same-engine.md)
- 后放（CR）：L1 全历史 replay 成本 / `engine_state` 增量（与 L2 §0 后放同型）

### 2.2 ~~RS peer 宇宙 + Spearman / `test_C1`~~（已完成 — Spec C）

- Spec：[`2026-10-07-rs-c1-vol-design.md`](docs/superpowers/specs/2026-10-07-rs-c1-vol-design.md) / plan [`2026-10-07-rs-c1-vol.md`](docs/superpowers/plans/2026-10-07-rs-c1-vol.md)
- 纯价格 RS + 闭合分位；peer 隔离与 eligibility 测试；C1 allowlist；CI Spearman 金标+合成（实盘抽样日后放）。
- 旁路 `VOL_score`（个股）已 ship；**不做**量价混合进 RS；篮子非 null VOL **后放**（Spec C §2.3）。

### 2.3 ~~未映射计数 / IPO 告警~~（已完成 — Spec D）

- Spec：[`2026-10-08-universe-expansion-design.md`](docs/superpowers/specs/2026-10-08-universe-expansion-design.md) / plan [`2026-10-08-universe-expansion.md`](docs/superpowers/plans/2026-10-08-universe-expansion.md)
- **遗留（后放）：** 树外 bars 预热仍后放（Spec D 不做 `sync_bars` 预热）。

### 2.4 ~~成分 YAML 每日 vendor 拉新~~（已完成 — Spec D）

- Spec / plan 同上（Actions taxonomy 步：fetch + 语义 diff + `map_version` bump + push）。

### 2.5 ~~`board_calc_v1` 与 `limit_up_unfillable`~~（已完成 — Spec E）

- Spec：[`2026-10-08-spec-e-fill-hard-freeze-design.md`](docs/superpowers/specs/2026-10-08-spec-e-fill-hard-freeze-design.md) / plan [`2026-10-08-spec-e-fill-hard-freeze.md`](docs/superpowers/plans/2026-10-08-spec-e-fill-hard-freeze.md)
- hist `board_calc_v1` + `cost_version` v2；`limit_up_unfillable: false` 显式进 YAML/summary。

### 2.6 ~~`hard_frozen` 扩到显式冻旗~~（已完成 — Spec E）

- Spec / plan 同上（`bars.hard_freeze_flag` + sync streak N=20；metrics OR；`param_version` p05-v3）。

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
| RS / Spearman / C1 | §2.2 | 否（Spec C 已落地） |
| 未映射全 A、YAML 日拉 | §2.3–2.4 | 否 |
| board_calc、硬冻旗、止盈 tag | §2.5–2.7 | 否 |
| 因果 H、WF、P3、实盘 M | §3 | 否 |
