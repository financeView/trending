# Spec：`limit_rule` 回退强卡控（P0）

**日期：** 2026-10-11  
**状态：** 设计中；plan [`2026-10-11-limit-rule-rollback-guard.md`](../plans/2026-10-11-limit-rule-rollback-guard.md)  

**范围：** `todo.md` P0 **`limit_rule` 回退**——yaml 切回 `vendor_fields` 后，库内残留 `limit_source=board_calc_v1` 仍被 fill 当限价用时的护栏。  
**后放（禁止混入本 slice）：** 自动清库脚本 / 批量 NULL 化 board_calc 限价；incomplete×asof（见姊妹 Spec）；改 `board_calc` 公式；静默改 `limit_rule` 却不 bump `cost_version`（既有禁令保留）；Protocol B 戳语义；env 旁路本门。

交叉：Spec E [`2026-10-08-spec-e-fill-hard-freeze-design.md`](2026-10-08-spec-e-fill-hard-freeze-design.md) §3 · costs [`config/eval/costs.yaml`](../../../config/eval/costs.yaml) · fill [`scripts/eval/fill_day.py`](../../../scripts/eval/fill_day.py) · 姊妹 incomplete [`2026-10-11-incomplete-asof-authority-design.md`](2026-10-11-incomplete-asof-authority-design.md) · 待办 [`todo.md`](../../../todo.md) P0

产品对齐：配置声称「只用交易所 vendor 限价」时，不得静默继续用估算板价成交。

**覆盖声明（钉死）：** 本 Spec **不**改变 Spec E「fill 只读 bars `limit_*`、不按 `limit_rule` 重算板价」；只加 **入口一致性硬失败**。

---

## 1. 问题

1. Spec E 启用 `board_calc_v1` 后，历史缺 vendor 日被写入 `limit_*` + `limit_source=board_calc_v1`。  
2. 若运维把 `costs.limit_rule` 切回 `vendor_fields`：sync 的 board_calc pass **整段跳过**，不再新写估算限价。  
3. 库内旧 `board_calc_v1` 行仍在；fill **只读列** → 纸面/影子仍按估算板价成交。  
4. summary 可写当前 `limit_rule=vendor_fields`，看起来像 vendor-only，实际混用历史估算 → **配置与库内事实脱节**。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 护栏强度 | **Approach 2 强卡控**：不一致 → **非零退出**（非仅 warn） |
| 触发 | `limit_rule == vendor_fields` **且** 目标 `bars.db` **全库**存在 ≥1 行满足 §3.1（**故意不做**成交窗过滤） |
| 门闩点 | §3.2  enumerated 入口；共享同一检查函数；**无** env 旁路 |
| 自动清库 | **不做**（本 slice）；stderr 提示人工清或改回 `board_calc_v1`（+ bump `cost_version`） |
| metrics / `daily_run` | **不**挂此门（截面不读限价成交） |
| ops | 现网 `costs.yaml` 为 `board_calc_v1` 时本门不触发；**切回 `vendor_fields` 前**须清库内 `board_calc_v1` 限价，否则 fill/影子全红 |

### 2.1 非目标

- 实现清库 SQL/脚本（ops 示例句见 §3.1；本 slice 不交付脚本）。  
- 按 `--from/--to` 窗口过滤 EXISTS（回退后只要库内任一 board_calc 限价即红）。  
- 在 `limit_rule=board_calc_v1` 时扫描「混有 vendor」——合法。  
- 改 fill 撮合公式 / `limit_up_unfillable`。  
- 给 `daily_run` / `paper_book` 加限价一致性门（本门仅 `live_shadow_step.run_asof`，见 §3.2）。

---

## 3. 方案

### 3.1 不一致判定（钉死）

```text
costs.limit_rule == "vendor_fields"
AND EXISTS (
  SELECT 1 FROM bars
  WHERE limit_source = 'board_calc_v1'
    AND limit_up IS NOT NULL
    AND limit_down IS NOT NULL
)
→ FAIL
```

- **全库扫描故意为之**：不按 fill 日期窗过滤。长期开过 `board_calc_v1` 后切回 `vendor_fields`，须人工清（例：`UPDATE bars SET limit_up=NULL, limit_down=NULL, limit_source=NULL WHERE limit_source='board_calc_v1'`——ops 笔记级；是否动 `preclose_raw` 后放）后才能绿。  
- `limit_source` 常量 = `LIMIT_SOURCE_BOARD_CALC`（`board_calc_v1`）。  
- 仅一侧非空不算有效行（与 `fill_day._limits` 双侧可算对齐）。  
- `limit_rule` 缺省解析与 `EvalCosts` 一致（空 → `vendor_fields`）。

### 3.2 门闩点

共享：`scripts/eval/limit_rule_guard.py`（或 `scripts/common/` 等价）  
`check_limit_rule_bars(bars_path: str, limit_rule: str) -> int`  # 0 ok, 1 fail  

**同源（钉死）：** `bars_path` **必须**为本次 fill/影子打开的同一路径（尊重 `--bars-db`）；禁止检查默认库、成交读另一库。

| 入口 | 挂点 | 行为 |
|------|------|------|
| `live_shadow_step.run_asof` | 与姊妹 Spec 同序：**0-skip 之后**、`fill_day` **紧前**（limit_rule 在 sync_complete 门之后） | fail → 非零 / 不写 `paper_fill` |
| `live_shadow_step.main` | 仅薄封装；**不得**只挂 `main` 而让直调 `run_asof` 旁路 | — |
| 可选 CLI | `python scripts/check_limit_rule_bars.py --bars-db …` | 同函数 |

**本 Spec 不门：** `paper_book`（Audit H；不写 `paper_fill`）。若 Audit 也要 vendor-only 语义，后放或显式 flag——默认不加。

**无** `TRENDING_*` / 其它 env 旁路本门。

失败 stderr（须含可行动作）：

```text
[limit_rule_guard] vendor_fields but bars still have board_calc_v1 limits —
clear those rows (whole DB) or set limit_rule=board_calc_v1 (+ bump cost_version)
```

### 3.3 与 `cost_version`

- 本门闩 **不**替代「改 `limit_rule` 须 bump `cost_version`」。  
- 切回且已清库后：须 bump `cost_version` 再宣称新成本语义（文档句；**不**新增自动化 CI 门）。

### 3.4 夹具

- `vendor_fields` + 一行双侧非空 `board_calc_v1` → check == 1。  
- `vendor_fields` + 无此类行 → 0。  
- `board_calc_v1` + 库内有 board_calc 行 → 0。  
- `--bars-db` 指向含残留行的库、costs 为 vendor → fail（同源）。  
- `run_asof`：不一致时不调用 `fill_day` / 不写 `paper_fill`。

---

## 4. 数据流

```text
load EvalCosts.limit_rule
  → resolve bars_path (--bars-db or default)
  → check_limit_rule_bars(bars_path, limit_rule)
       fail → stderr + non-zero
       ok   → fill_day / shadow 如常
```

建议与姊妹 Spec 同 PR 时：先 sync_complete 门（shadow），再本门。  
sync / board_calc pass：**不变**。

---

## 5. 验收

| # | 断言 |
|---|------|
| 1 | `vendor_fields` + 全库存在双侧非空 `board_calc_v1` → `check_*` == 1 |
| 2 | `vendor_fields` + 无此类行 → 0 |
| 3 | `board_calc_v1` + 库内有 board_calc 行 → 0 |
| 4 | `run_asof` 不一致时非零（或等价失败返回），**未调用** `fill_day` / **未写** `paper_fill` |
| 5 | 直调 `run_asof`（绕过 `main`）仍触发门闩 |
| 6 | `check_*` 使用的 `bars_path` 与 `--bars-db` 一致（夹具双库可证） |
| 7 | stderr 含 clear / board_calc_v1 / cost_version 类提示 |
| 8 | 无 env 旁路可放行本门 |
| 9 | 落地时 todo P0「`limit_rule` 回退」改写为已落地并链本 Spec |

---

## 6. 文档与待办

- `todo.md` P0 行（落地时）。  
- Spec E §3 或 ops 短注：回退前须**全库**清 board_calc 限价。  
- 姊妹 Spec incomplete：交叉引用。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-11 | 初版：Approach 2；EXISTS；fill/影子入口；不清库 |
| 2026-10-11 | CR：全库 EXISTS 钉死；挂点 `run_asof`；不门 `paper_book`；`--bars-db` 同源；无 env 旁路；修验收措辞 |
| 2026-10-11 | 复审：门序与 incomplete 对齐（0-skip 后、sync 门后）；收紧 §2.1 措辞 |
