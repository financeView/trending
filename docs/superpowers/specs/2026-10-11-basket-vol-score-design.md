# Spec：篮子 `VOL_score`（L2/L1 换手自身分位）

**日期：** 2026-10-11  
**状态：** 设计完成；plan [`2026-10-11-basket-vol-score.md`](../plans/2026-10-11-basket-vol-score.md)  
**范围：** 闭合 Spec C §2.3 后放——L2/L1 非 null `VOL_score`（达样本闸时）；合成篮日线附加 Σamount/Σfloat_mv；digest「量」列可填；在 Σ 可用后**启用 L2 `danger`**（止盈 Spec 已后放项）。  
**后放（禁止混入本 slice）：** 量进 RS；`engine_state` / 裸砍 lookback；成员个股 VOL 加权冒充篮 VOL；改合成**价**权重公式（除附加 Σ 字段外）；个股止盈三标签主逻辑（见姊妹 Spec）；节气 NN；L1 `tags` 非空。

交叉：Spec C [`2026-10-07-rs-c1-vol-design.md`](2026-10-07-rs-c1-vol-design.md) §2.3 · metrics [`2026-09-29-trend-metrics-engine-design.md`](2026-09-29-trend-metrics-engine-design.md) · L2 synth [`scripts/metrics/l2_synth.py`](../../../scripts/metrics/l2_synth.py) · 止盈标签 [`2026-10-11-exit-tags-design.md`](2026-10-11-exit-tags-design.md) · 待办 [`todo.md`](../../../todo.md) P1 篮子 VOL

产品对齐：量能旁路确认；与个股 `VOL_score` **同型同参**；**不**改写 RS。

**覆盖声明（钉死）：** 本 Spec **取代** Spec C §2.3「L2/L1 VOL 恒 null」及 digest 后放脚注；Spec C 其余（价格 RS、个股 VOL、peer）不变。

---

## 1. 问题

- Spec C 为避篮子换手时序成本，将 L2/L1 `VOL_score` 钉死 SQL NULL；digest「量」空并脚注后放。  
- 合成 `synthesize_basket_bars` 今日只写 OHLC，无 `amount`/`float_mv`，无法复用 `turnover_from_bar` → `compute_vol_scores`。  
- 用户已选与个股同型：\(\Sigma amount / \Sigma float\_mv\) → 自身历史分位。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 架构 | **Approach 1**：扩展合成 bar 字段 + 复用 `vol_score.py` |
| 公式 | 与个股同：`turnover_from_bar` → `compute_vol_scores`（`vol_hist` / `vol_score_min_samples`） |
| 实体 | **L2 + L1** 均可非 null（达闸） |
| RS | **不**因本 slice 改变 |
| 版本 | 实现序：止盈标签先（`p05-v4`）→ 本 Spec；本 Spec 落地时 bump → **`p05-v5`**（若两 Spec 同 PR，yaml **终值一次**写 `p05-v5` 且开旗，避免双 bump 冲突——plan 钉清） |
| Protocol B | 终值 `param_version` 生效前须 **硬冻 pass + 写戳** 与 yaml 一致（Protocol B §4.1；同 PR 只刷一次终值） |
| L2 danger | 合成序列具备配对 Σamount/Σfloat_mv 后，按止盈 Spec §3.2 危险定义对 **L2** 启用（个股 danger 仍属止盈 Spec） |

### 2.1 非目标

- 成员 `VOL_score` 市值加权均 / 中位。  
- 外部换手缓存或第二套 peer 量分。  
- 改 `normalize_weights` / 链收益价合成逻辑（仅**附加** Σ 字段）。  
- 全历史 `engine_state` 战役。  
- 重写个股 `vol_expand` / `champagne` / `danger`（只开 L2 `danger`）。

---

## 3. 方案

### 3.1 合成 bar 附加字段

`synthesize_basket_bars` 每个**已输出**交易日记录增加：

| 字段 | 定义 |
|------|------|
| `amount` | \(\sum_i amount_i\)，见下「配对成员」 |
| `float_mv` | \(\sum_i float\_mv_i\)，见下「配对成员」 |

**配对成员（钉死）：** 候选集 = 该日 **`r_members`**（与价收益合成相同）。成员 \(i\) **同时**满足 `amount_i` 有限 **且** `float_mv_i` 有限且 `>0` 时，才把该成员计入**双方** Σ；否则该成员对 amount/float_mv **都不计入**（禁止分子分母不同成员集）。

- 配对后无成员，或 Σ 后 `float_mv≤0` / 无有限 Σamount → 该日字段缺省或显式 null → `turnover_from_bar` → turnover **null**。  
- `r_members` 空则本就不输出该日（现有行为），无 VOL 点。  
- 既有 OHLC / `is_st` / `is_suspended` 行为不变。

### 3.2 计分与管线

```text
synth series (含 amount/float_mv)
  → turnovers = [turnover_from_bar(...) for bar in synth]
  → scores = compute_vol_scores(turnovers, vol_hist=..., min_samples=...)
  → asof VOL_score = score on trade_date D (else null)
```

- 删除「篮 VOL 恒 null」：**两处**——`_basket_asof_row` 默认 `VOL_score: None` 可留作占位，但 post-peer 循环中对 l2/l1 的强制 `None` **必须去掉**并由真实计分覆盖；回归测同步改。  
- 建议抽 `assign_vol_scores(rows, series_by_code, params)`：个股用 `bar_cache`，L2/L1 用本次合成序列；**缓存 `synth_by_code`** 供 VOL 与 `assign_exit_tags`（L2 danger / 香槟）共用，避免双倍合成。  
- **L2 `danger`：** 在 `assign_exit_tags` 中，当 L2 合成脊含配对 Σ `amount` 时，按止盈 Spec 危险定义写入 `danger`（与个股同参）；L1 仍不打标签。  
- `param_version` / `universe_id` 写入逻辑不变（版本号见 §2）。

### 3.3 Digest / Issue

- L2/L1「量」列：有分填 0–100 整数（与个股同格式化）；无分空。  
- **删除**脚注：`L2/L1「量」本 slice 为空——篮子 VOL 后放…`。  
- 替换为中性一句（L1/L2 表一处即可）：`量=VOL_score（篮换手自身分位；样本不足为空）。`  
- 排序键不变（不按量重排 L2 表若当前非 RS 序——保持 Spec C / 现网行为）。

### 3.4 与止盈 Spec 交叉

- 文档互链。  
- 实现串行：标签（个股三标签 + L2 无 danger）→ 本 Spec（Σ + 篮 VOL + **开 L2 danger**）。  
- 本 Spec **不**改 `exit_tags_*` 阈值键（可复用已开旗）；共享 `vol_hist` / `vol_score_min_samples` 只读。  
- 若同 PR：`param_version` 终值 `p05-v5`，`exit_tags_enabled: true`；Protocol B 戳按终值刷一次。

---

## 4. 数据流

```text
member bars → synthesize_basket_bars (+ amount/float_mv Σ)
  → replay_from_ohlc（价路径不变）
  → peer RS
  → assign VOL_score（stock + L2 + L1；同函数）
  → [exit_tags 若已落地]
  → upsert / digest「量」
```

---

## 5. 验收

| # | 断言 |
|---|------|
| 1 | 配对成员：仅双字段合法才进 Σ；单侧合法成员不计入任一侧；配对后可算 → turnover 非 null，否则 null |
| 2 | 金标：合成 turnover 序列喂 `compute_vol_scores` 与写入 asof 逐位一致 |
| 3 | `n < vol_score_min_samples` → null；达闸夹具 → 非 null |
| 4 | 回归：去掉 l2/l1 强制 null（含 `test_vol_score` 恒 null 断言）；改为达闸/未达闸双夹具 |
| 5 | 赋 VOL 前后 `RS` 不变 |
| 6 | digest：篮行「量」可非空；旧后放脚注原文不出现 |
| 7 | yaml 终值含本 slice 约定的 `param_version`（见 §2） |
| 8 | L2：合成含 amount 后，危险金标可打上 `danger`；L1 `tags` 仍 `[]` |
| 9 | Protocol B：终值 `param_version` 与 `hard_freeze_pass_meta` 一致后方可绿 `daily_run` |

---

## 6. 文档与待办

- `todo.md` P1「篮子 VOL」完成后改写。  
- Spec C §2.3 / 后放列表：划掉「L2/L1 非 null VOL」并链本 Spec；状态注「篮 VOL 见 2026-10-11」。  
- digest 注释代码中「baskets null this slice」同步删除。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-11 | 初版：合成 Σ 换手 + 复用 vol_score；L2+L1；覆盖 Spec C 恒 null；版本 p05-v5 |
| 2026-10-11 | CR：Σ 配对成员；Protocol B 戳；启用 L2 danger；双处 null 清除；synth 缓存共用 |
