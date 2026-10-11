# Spec：incomplete × asof 非权威强卡控（P0）

**日期：** 2026-10-11  
**状态：** 设计中（待 plan）  
**范围：** `todo.md` P0 **incomplete + asof 限价**——OHLC 未完成时跳过 `--with-limits`、asof 禁 board_calc，导致 partial 日无限价却仍可能被本地 fill/影子当权威。  
**后放（禁止混入本 slice）：** asof 东财限价与 OHLC 预算**拆耦**（单独拉 limits）；asof 日 `board_calc`；改 Spec F job 图；`limit_rule` 回退（见姊妹 Spec）；付费 `stk_limit`。

交叉：Spec E [`2026-10-08-spec-e-fill-hard-freeze-design.md`](2026-10-08-spec-e-fill-hard-freeze-design.md) · Spec F [`2026-10-08-workflow-split-jobs-design.md`](2026-10-08-workflow-split-jobs-design.md) · Protocol B [`2026-10-10-protocol-b-hard-freeze-stamp-design.md`](2026-10-10-protocol-b-hard-freeze-stamp-design.md) · sync [`scripts/sync_bars_sample.py`](../../../scripts/sync_bars_sample.py) · 姊妹 limit_rule [`2026-10-11-limit-rule-rollback-guard-design.md`](2026-10-11-limit-rule-rollback-guard-design.md) · 待办 [`todo.md`](../../../todo.md) P0

产品对齐：**不拆耦**；incomplete 日 = **非权威**；强卡控禁止本地绕过 Actions 门闩宣称当日成交有效。

**覆盖声明（钉死）：**  
- Spec F「`sync_complete=false` → metrics job 跳过」**保持**。  
- Spec E「asof 禁 board_calc；`--with-limits` 仅 complete ∧ end==asof」**保持**。  
- Protocol B「incomplete 仍硬冻+写戳、`sync_complete=false`、sync exit 0」**保持**。  
本 Spec 只补：**持久化完成信号 + 本地 fill/影子硬门闩**。

---

## 1. 问题

1. sync OHLC 预算不够 → `complete=false` → **跳过** `--with-limits`。  
2. asof 日禁止 board_calc → 当日常 **无** vendor 限价也 **无** 估算限价。  
3. Actions 上 Spec F 已跳过 metrics；但**本地** `paper_book` / `live_shadow` 不读 `GITHUB_OUTPUT`，仍可对半截 `bars.db` 跑成交并产出看起来完整的结果。  
4. 产品未钉「partial 日非权威」时，易把影子当正式。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 拆耦 asof 限价 | **否**（Approach A） |
| 护栏强度 | **Approach 2 强卡控**：未 complete → fill/影子入口 **非零退出** |
| Actions | 依赖既有 Spec F；本 Spec 不改 workflow `if:` |
| 完成信号 | sync 在写 `GITHUB_OUTPUT` 的**同时**落盘本地 SoT（§3.1） |
| sync 进程 | incomplete 仍 exit 0；行为与 Protocol B / Spec E 一致 |

### 2.1 非目标

- incomplete 时仍拉东财 asof 限价。  
- asof 日启用 board_calc。  
- 改 hard_freeze / 戳失败策略。  
- 给 `daily_run` 再挂一层（Actions 已跳过整 job；本地若跑 `daily_run` 可不读限价——**不**要求本 Spec 门 `daily_run`，除非 plan 发现同进程 fill）。

---

## 3. 方案

### 3.1 本地 SoT：`sync_status` 文件（钉死）

路径（钉死）：`data/cache/sync_status.json`（相对仓库根；与 trade_dates 等 cache 同级）。

`write_sync_complete(complete, elapsed_min=...)` **扩展**为：

1. 保持现有：若设 `GITHUB_OUTPUT` 则追加 `sync_complete` / `sync_elapsed_min`。  
2. **始终**（含本地）原子写 `data/cache/sync_status.json`：

```json
{
  "sync_complete": true,
  "elapsed_min": 12.3,
  "written_at": "2026-10-11T08:00:00Z",
  "session_asof": "2026-10-10"
}
```

| 字段 | 规则 |
|------|------|
| `sync_complete` | bool；与今日 `complete` 参数一致 |
| `elapsed_min` | float |
| `written_at` | UTC ISO8601 |
| `session_asof` | sync 本次 `session_asof` 的 `YYYY-MM-DD`（`write_sync_complete` 须能拿到；签名可增可选参数，plan 钉） |

- 目录不存在则创建。  
- **禁止**只写 GITHUB_OUTPUT 不写文件（本地无 Actions 时否则无信号）。

### 3.2 入口检查

共享：`check_sync_complete_for_fill(status_path=None) -> int`  # 0 ok, 1 fail

```text
status ← read sync_status.json
if missing or invalid JSON → FAIL
if sync_complete is not true → FAIL
→ ok
```

| 入口 | 行为 |
|------|------|
| `paper_book.main` | fill 循环前；fail → return 1 |
| `live_shadow_step.main` | 同上 |
| 可选 CLI | `python scripts/check_sync_complete.py` |

失败 stderr 示例：

```text
[sync_authority] sync_complete!=true (or missing data/cache/sync_status.json) —
incomplete / partial bars are non-authoritative; re-run full sync before fill/shadow
```

**测试豁免（钉死）：** 单测可 monkeypatch `check_*` 或写入临时 `sync_status.json` 且 `sync_complete=true`；**禁止**生产默认旁路 flag。若需本地强行调试，仅允许显式环境变量 `TRENDING_ALLOW_INCOMPLETE_FILL=1`（默认未设；文档标危险；CI 测试不得依赖此变量绿主路径）。

### 3.3 sync / limits 行为（不变，仅重申）

| 项 | 行为 |
|----|------|
| `--with-limits` | 仅 `complete ∧ end == session_asof` |
| asof board_calc | 禁止 |
| incomplete + 硬冻/戳 | 仍执行；`sync_complete=false`；sync exit 0 |
| Spec F metrics | `sync_complete != true` → job skip |

### 3.4 产品句（文档）

README / todo / Spec E 交叉一句：

> Incomplete sync（`sync_complete=false`）日的 bars **非权威**；禁止宣称当日 fill / 影子成交有效。须完整 sync 后再跑成交入口。

---

## 4. 数据流

```text
sync OHLC/flags [(limits if complete∧asof)] → Spec E passes → write_sync_complete(complete)
  → GITHUB_OUTPUT (if any) + data/cache/sync_status.json

paper_book / live_shadow
  → check_sync_complete_for_fill()
       fail → exit 1
       ok   → （可再跑姊妹 Spec limit_rule 门）→ fill
```

建议接线顺序（同 PR 时）：**先** sync_complete 门，**再** limit_rule 门。

---

## 5. 验收

| # | 断言 |
|---|------|
| 1 | `write_sync_complete(False)` 后文件存在且 `sync_complete=false`；`check_*` == 1 |
| 2 | `write_sync_complete(True)` 后 `check_*` == 0 |
| 3 | 缺文件 → `check_*` == 1 |
| 4 | `paper_book` 在 false/缺文件时非零，不进入成交写入 |
| 5 | `live_shadow` 同等（或 helper + 一处接线） |
| 6 | 仍断言：`with_limits` 在 `not complete` 时不拉东财（既有测保留/补强） |
| 7 | workflow 仍含 `needs.sync.outputs.sync_complete == 'true'`（不回归） |
| 8 | todo P0「incomplete + asof 限价」改写为已落地并链本 Spec |

---

## 6. 文档与待办

- `todo.md` P0 行更新。  
- `docs/ops/` 可加一句到 hard-freeze runbook 或新短节：incomplete → 非权威 → 先完整 sync。  
- Protocol B / Spec E 后放列表：本项划掉并链本 Spec。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-11 | 初版：不拆耦；`sync_status.json` SoT；fill/影子强卡控；Spec F 不变 |
