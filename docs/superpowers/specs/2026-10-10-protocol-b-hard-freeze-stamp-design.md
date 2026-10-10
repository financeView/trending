# Spec：Protocol B 硬冻戳 + 强卡控（P0）

**日期：** 2026-10-10  
**状态：** 设计中（待实现）  
**范围：** `todo.md` P0 **Protocol B**——改 `hard_freeze_min_suspend_days` / bump `param_version` 与 `bars.hard_freeze_flag` 脱节时的运维护栏。  
**后放（禁止混入本 slice）：** `limit_rule` 回退护栏；incomplete + asof 限价产品抉择；metrics 侧自动补跑硬冻 pass；按日审计流水；改硬冻算法 / 默认 N。

交叉：Spec E [`2026-10-08-spec-e-fill-hard-freeze-design.md`](2026-10-08-spec-e-fill-hard-freeze-design.md) §4.3.1 · Spec F [`2026-10-08-workflow-split-jobs-design.md`](2026-10-08-workflow-split-jobs-design.md) · 待办 [`todo.md`](../../../todo.md) P0 Protocol B

产品对齐：配置声称的硬冻规则必须与库内旗一致，才能宣称新 `param_version` 下的 EXIT / 评估有效。

---

## 1. 问题

Spec E 将硬冻定为 **persist + 读列**：`hard_freeze_flag` 由 sync 全量 pass 按 yaml 的 N 写入；metrics / fill **不再**按 N 重算。

因此：

1. 只改 yaml（N 或 `param_version`）而**不**用新 N 重写旗 → 库内仍是旧阈值。  
2. `daily_run` / 纸面 / Issue 却带上**新** `param_version` → **新版本号 + 旧旗**。  
3. 今日 sync 虽已跑 `apply_hard_freeze_flags`，但 pass **失败仅 warn** 时仍可能 `sync_complete=true` 并进入 metrics，旗/戳不可信。  
4. 文档约定（方案 B）无代码护栏 → 人忘了就会静默错。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 护栏强度 | **强卡控档 1**：sync 上 pass 失败则红；metrics/`daily_run` 入口戳与 yaml 不一致则红 |
| 一致性信号 | **单行 stamp**（`bars.db`，UPSERT 覆盖，恒 1 行） |
| 自动修复 | **不做** metrics 侧自动触发 pass；不一致 → 失败并提示先跑完整 sync |
| 文档 | 短 runbook：改 N / bump → sync（写旗+戳）→ 再 metrics/评估 |
| 检查脚本 | 可选；与入口共用同一校验函数，供本地/PR；日更以硬门闩为准 |

### 2.1 非目标

- 不改 `apply_hard_freeze_flags` 的 streak / N 语义。  
- 不新建按日增长的审计表。  
- 不在本 slice 做 P0 另外两项（`limit_rule` 回退、incomplete×asof 限价）。  
- 不把「无戳」在绿场首次部署时永久卡死——见 §4.3 迁移。

---

## 3. 方案

### 3.1 单行戳表（`bars.db`）

表名（钉死）：`hard_freeze_pass_meta`

| 列 | 类型 | 含义 |
|----|------|------|
| `id` | `INTEGER PRIMARY KEY CHECK (id = 1)` | 单行约束 |
| `hard_freeze_min_suspend_days` | `INTEGER NOT NULL` | 本次 pass 使用的 N |
| `param_version` | `TEXT NOT NULL` | 本次 pass 时 yaml 的 `param_version` |
| `rewritten_at` | `TEXT NOT NULL` | UTC ISO8601 完成时间 |
| `rows_touched` | `INTEGER` | 可选；`apply_hard_freeze_flags` 返回值 |

- 写入时机：硬冻全量 pass **成功返回之后**（与 Spec E pass 同一 sync 会话）。  
- 语义：戳表示「库内旗已按该 N / 该 `param_version` 重写过」。  
- 增长速度：**O(1)**，每次覆盖。

实现：`ensure` 建表（idempotent）；提供 `write_hard_freeze_pass_meta` / `read_hard_freeze_pass_meta`。

### 3.2 sync 强卡控

现路径：`scripts/sync_bars_sample.py` → `run_spec_e_passes` → `apply_hard_freeze_flags`。

| 项 | 旧 | 新 |
|----|----|-----|
| hard_freeze 异常 | stderr warn，sync 继续 | **传播失败 → sync 非零退出**（在写 `sync_complete` 之前失败） |
| board_calc pass | 可保持既有 warn 级（本 slice **不**强制改 board_calc 失败策略） | 不变，除非实现时二者同 try 需拆开——**必须拆开**：仅 hard_freeze 升级为硬失败 |
| pass 成功后 | 只打日志 | **UPSERT 戳**（N、`param_version`、`rewritten_at`、`rows_touched`） |

N / `param_version` 来源：与 pass 相同——`config/metrics/a_share_daily.yaml`（`load_hard_freeze_min_suspend_days` + 读 `param_version`）。

**「跑硬冻全量 pass」定义（runbook 用语）：**  
对当前 `bars.db` 执行与日更 sync 相同的 `apply_hard_freeze_flags(conn, mapped_codes, n=yaml_N)`，覆盖写全宇宙相关行的 `hard_freeze_flag`，并写戳。正常完整 sync（OHLC 循环结束后的 Spec E 段）即包含此操作。

### 3.3 metrics / `daily_run` 强卡控

在 **开始算截面之前**（读 bars、写 `daily_*` 之前）调用共享校验：

```text
yaml_N, yaml_param_version  ← a_share_daily.yaml
stamp                       ← hard_freeze_pass_meta id=1

if stamp missing → fail（迁移例外见 §4.3）
if stamp.N != yaml_N → fail
if stamp.param_version != yaml_param_version → fail
else ok
```

失败：非零退出 + 明确 stderr（中英任一，须含：先跑完整 sync / 硬冻 pass 以刷新旗与戳）。

挂点（钉死）：

- `scripts/daily_run.py` 主路径（覆盖 Actions **metrics** job 与本地 `daily_run`）。  
- 不要求改 `live_shadow_step` 再挂一层（shadow 依赖已成功的 `daily_run` 日）；若单独跑 shadow 而跳过 `daily_run`，本 slice 不扩展。

### 3.4 可选 CLI

`python scripts/check_hard_freeze_stamp.py`（或 `scripts/taxonomy` 旁等价路径）：

- 退出 0 = 匹配；非 0 = 不匹配/无戳。  
- 与 `daily_run` 共用校验函数。  
- **不**在失败时自动跑 pass（档 1）。

### 3.5 Runbook（文档触点）

短节写入 Spec E 旁或 `docs/` 运维段（实现时二选一，避免重复长文）：

1. 改 `hard_freeze_min_suspend_days` 和/或 bump `param_version`。  
2. 对目标环境 `bars.db` 跑完整 sync（或文档注明的等价 pass 入口）。  
3. 确认戳与 yaml 一致（`check_hard_freeze_stamp` 或看表）。  
4. 再跑 metrics / `daily_run` / 评估。

---

## 4. 契约细节

### 4.1 比对键

**必须同时**比对 N 与 `param_version`。  
只 bump `param_version`、N 不变：仍须重新跑 pass 并写戳（方案 B：宣称新版本前旗须在同环境下按当前规则重写过——即使 N 数字未变，也刷新 `rewritten_at` / 与版本绑定）。

### 4.2 sync 失败与 `sync_complete`

- hard_freeze 失败 → **不得**调用 `write_sync_complete(true)`。  
- 进程非零退出；Spec F：metrics 因无完整成功 sync / 无 `sync_complete=true` 而不跑（或本 run 已失败）。  
- OHLC 已写入但 pass 失败：接受；修复后重跑 sync 再 pass + 写戳。

### 4.3 迁移 / 首次部署

绿场或旧 cache **无戳**：

| 场景 | 行为 |
|------|------|
| sync | 跑 pass → 写戳（自愈） |
| `daily_run` 且无戳 | **失败**（与「不一致」同级），迫使先 sync |

测试可注入戳或先跑 pass helper。不在 yaml 增加「跳过校验」永久开关；若 CI 夹具需要，仅测试 monkeypatch / 临时 env **测试专用**（生产 Actions 不设跳过）。

### 4.4 Actions

- **sync job：** 依赖 pass 硬失败即可，不必另加 step。  
- **metrics job：** 依赖 `daily_run` 入口校验即可。  
- 不新增第三 job。

---

## 5. 测试（最少集）

1. **写戳：** pass 成功后 `hard_freeze_pass_meta` 一行，N/`param_version` 正确。  
2. **匹配：** 戳=yaml → `daily_run` 校验通过（可 stub 后续）。  
3. **N 不一致：** 戳 N≠yaml → `daily_run` 非零。  
4. **param_version 不一致：** 同上。  
5. **无戳：** `daily_run` 非零。  
6. **pass 失败传播：** mock `apply_hard_freeze_flags` 抛错 → sync 非零，且不写 `sync_complete=true`、不写成功戳。  
7. **board_calc warn 隔离：** board_calc 仍 warn 时，不单独导致本 slice 要求的 hard_freeze 硬失败被吞（拆 try）。

---

## 6. Done-when

1. `hard_freeze_pass_meta` 单行表 + 读写 helper；pass 成功写戳。  
2. sync：hard_freeze 失败 → 非零；成功 → 戳与 yaml 一致。  
3. `daily_run`：校验失败 → 非零，且错误信息指向先 sync。  
4. §5 测试绿。  
5. 短 runbook 落盘；`todo.md` P0 Protocol B 行改为本 Spec / 完成后标完成。  
6. Spec E §4.3.1 加一句指向本 Spec（护栏已代码化）。

---

## 7. 风险与操作说明

| 风险 | 缓解 |
|------|------|
| 改 yaml 后只跑 metrics | 入口失败，迫使 sync |
| pass 慢 | 既有成本；本 slice 不加重算范围 |
| 旧 Actions cache 无戳 | 先 sync 自愈；仅 metrics 会红一次 |
| 与 Spec F incomplete | pass 在 OHLC 后；pass 失败整 sync 红，优于假绿进 metrics |

**`check_hard_freeze_stamp` 失败含义（操作者）：**  
yaml 的 N/`param_version` 与库内戳不一致或无戳 → 不要宣称新版本结果；对同一 `bars.db` 跑完整 sync（硬冻全量 pass + 写戳）后再检、再跑 `daily_run`。

---

## 8. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-10 | 初版：单行戳；sync pass 硬失败；daily_run 戳校验；档 1 不强行 metrics 自动 pass |
