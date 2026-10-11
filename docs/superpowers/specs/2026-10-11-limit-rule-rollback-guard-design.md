# Spec：`limit_rule` 回退强卡控（P0）

**日期：** 2026-10-11  
**状态：** 设计中（待 plan）  
**范围：** `todo.md` P0 **`limit_rule` 回退**——yaml 切回 `vendor_fields` 后，库内残留 `limit_source=board_calc_v1` 仍被 fill 当限价用时的护栏。  
**后放（禁止混入本 slice）：** 自动清库脚本 / 批量 NULL 化 board_calc 限价；incomplete×asof（见姊妹 Spec）；改 `board_calc` 公式；静默改 `limit_rule` 却不 bump `cost_version`（既有禁令保留）；Protocol B 戳语义。

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
| 触发 | `limit_rule == vendor_fields` **且** 目标 `bars.db` 存在 ≥1 行满足 §3.1 |
| 门闩点 | 所有**走 fill 的入口**（§3.2）；共享同一检查函数 |
| 自动清库 | **不做**（本 slice）；stderr 提示人工清或改回 `board_calc_v1`（+ bump `cost_version`） |
| metrics / `daily_run` | **不**挂此门（截面不读限价成交）；除非同进程直接调 fill |

### 2.1 非目标

- 实现清库 SQL/脚本（可后放 ops 笔记一句示例）。  
- 在 `limit_rule=board_calc_v1` 时扫描「混有 vendor」——合法。  
- 改 fill 撮合公式 / `limit_up_unfillable`。  
- 给 `daily_run` 加限价一致性门。

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
  LIMIT 1
)
→ FAIL
```

- `limit_source` 常量与 Spec E / `LIMIT_SOURCE_BOARD_CALC` 一致（`board_calc_v1`）。  
- 仅一侧非空不算「有效 board_calc 限价行」（与 fill 需双侧可算对齐）；实现用同一 SQL。  
- `limit_rule` 缺省解析与 `EvalCosts` 今日一致（空 → `vendor_fields`）。

### 3.2 门闩点

共享：`scripts/eval/limit_rule_guard.py`（或 `scripts/common/` 等价）  
`check_limit_rule_bars(conn|bars_path, limit_rule: str) -> int`  # 0 ok, 1 fail

| 入口 | 行为 |
|------|------|
| `paper_book.main` | 打开 bars、load costs 后、首日 fill **之前**调用；fail → return 1 |
| `live_shadow_step.main`（及任何生产影子入口） | 同上 |
| 可选 CLI | `python scripts/check_limit_rule_bars.py` → 同函数，供本地/PR |

失败 stderr（须含可行动作，中英任一）：

```text
[limit_rule_guard] vendor_fields but bars still have board_calc_v1 limits —
clear those rows or set limit_rule=board_calc_v1 (+ bump cost_version)
```

### 3.3 与 `cost_version`

- 本门闩 **不**替代「改 `limit_rule` 须 bump `cost_version`」。  
- 切回 `vendor_fields` 且已清库后：须 bump `cost_version` 再宣称新成本语义（既有禁令；本 Spec 验收可加文档句，不强制新自动化）。

### 3.4 夹具

- 单测构造：yaml/costs `vendor_fields` + 一行 `board_calc_v1` 限价 → check 返回 1；无此类行 → 0。  
- `board_calc_v1` 规则下即使有 board_calc 行 → 0。  
- paper_book / shadow 入口集成测：不一致时进程非零且未写入成交结果（或未进入 fill 循环）。

---

## 4. 数据流

```text
load EvalCosts.limit_rule
  → open bars.db
  → check_limit_rule_bars(...)
       fail → stderr + exit 1
       ok   → fill_day / shadow 如常
```

sync / board_calc pass：**不变**（`vendor_fields` 时仍整 pass 跳过）。

---

## 5. 验收

| # | 断言 |
|---|------|
| 1 | `vendor_fields` + 存在双侧非空 `board_calc_v1` → `check_*` == 1 |
| 2 | `vendor_fields` + 无此类行 → 0 |
| 3 | `board_calc_v1` + 库内有 board_calc 行 → 0 |
| 4 | `paper_book`（或等价）在不一致时非零退出，且不产生新成交行 |
| 5 | `live_shadow` 入口同等门闩（或共享 helper 单测 + 一处接线测） |
| 6 | stderr 含「clear / board_calc_v1 / cost_version」类行动提示 |
| 7 | todo P0「`limit_rule` 回退」改写为已落地并链本 Spec |

---

## 6. 文档与待办

- `todo.md` P0 行更新。  
- Spec E §3 或 ops 短注：回退 `vendor_fields` 前须清 board_calc 限价，否则 fill 入口红。  
- 姊妹 Spec incomplete：交叉引用；实现可同 PR 或串行。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-11 | 初版：Approach 2 强卡控；EXISTS board_calc 限价；fill/影子入口；不清库 |
