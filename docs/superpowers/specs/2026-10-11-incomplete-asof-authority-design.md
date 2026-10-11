# Spec：incomplete × asof 非权威强卡控（P0）

**日期：** 2026-10-11  
**状态：** 设计中（待 plan）  
**范围：** `todo.md` P0 **incomplete + asof 限价**——OHLC 未完成时跳过 `--with-limits`、asof 禁 board_calc；本地绕过 Actions 仍可能对 partial bars 跑**当日影子成交**。  
**后放（禁止混入本 slice）：** asof 东财限价与 OHLC 预算**拆耦**；asof 日 `board_calc`；改 Spec F job 图；`limit_rule` 回退（姊妹 Spec）；付费 `stk_limit`；给 `paper_book` / Audit H 默认硬门。

交叉：Spec E [`2026-10-08-spec-e-fill-hard-freeze-design.md`](2026-10-08-spec-e-fill-hard-freeze-design.md) · Spec F [`2026-10-08-workflow-split-jobs-design.md`](2026-10-08-workflow-split-jobs-design.md) · Protocol B [`2026-10-10-protocol-b-hard-freeze-stamp-design.md`](2026-10-10-protocol-b-hard-freeze-stamp-design.md) · sync [`scripts/sync_bars_sample.py`](../../../scripts/sync_bars_sample.py) · 姊妹 limit_rule [`2026-10-11-limit-rule-rollback-guard-design.md`](2026-10-11-limit-rule-rollback-guard-design.md) · 待办 [`todo.md`](../../../todo.md) P0

产品对齐：**不拆耦**；incomplete / 无新鲜完成信号时，**当日影子成交非权威** → 强卡控。

**覆盖声明（钉死）：**  
- Spec F「`sync_complete=false` → metrics job 跳过」**保持**。  
- Spec E「asof 禁 board_calc；`--with-limits` 仅 complete ∧ end==asof」**保持**。  
- Protocol B「incomplete 仍硬冻+写戳、失败不得写 `sync_complete=true`、成功路径末写 complete 标志、sync exit 0 on incomplete」**保持**。  
本 Spec 只补：**持久化 SoT + 本地 `live_shadow` 硬门闩（含 freshness）**。

---

## 1. 问题

1. sync OHLC 预算不够 → `complete=false` → **跳过** `--with-limits`。  
2. asof 日禁止 board_calc → 当日常无限价。  
3. Actions 上 Spec F 已跳过 metrics；本地 `live_shadow` 不读 `GITHUB_OUTPUT`，仍可对半截库写 `paper_fill`。  
4. 若 SoT 只在成功末尾写 `true`、检查又不看 asof，则 hard_freeze 红退 / 中途崩溃会留下**陈旧 true** → 假绿。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 拆耦 asof 限价 | **否** |
| 护栏强度 | **Approach 2**：无新鲜 `sync_complete=true` → `live_shadow` **非零** |
| 权威入口 | **仅** `live_shadow_step.run_asof`（写 `paper_fill`）；**不**默认门 `paper_book` |
| Actions | 依赖 Spec F；不改 workflow `if:` |
| SoT | `data/cache/sync_status.json`；**悲观写入 + asof 校验**（§3.1–3.2） |
| sync 进程 | incomplete 仍可 exit 0；与 Protocol B / Spec E 一致 |

### 2.1 非目标

- incomplete 时仍拉东财 asof 限价。  
- asof 日启用 board_calc。  
- 改 hard_freeze / 戳失败策略（只声明失败时 SoT 行为）。  
- 默认门 `paper_book` / `daily_run`。  
- 把 SoT 迁入 `bars.db`（后放选项；本 slice 用 cache 文件）。

---

## 3. 方案

### 3.1 本地 SoT：`sync_status.json`（钉死）

路径：`data/cache/sync_status.json`（仓库根相对；`data/cache/*` 已 gitignore，**不入库**）。

#### 3.1.1 悲观写入时序（钉死）

```text
sync main 在 OHLC 循环 / Spec E 之前（打开 bars 之后尽早）：
  write_sync_status(sync_complete=false, session_asof=..., elapsed_min=0)   # 悲观

… OHLC / flags / optional limits …

try:
  run_spec_e_passes(...)   # hard_freeze + stamp
except:
  write_sync_status(sync_complete=false, session_asof=..., ...)  # 失败路径仍落盘 false
  return 1                 # 与 Protocol B：不得暗示 complete=true

# 成功到达末尾：
write_sync_complete(complete, elapsed_min, session_asof=...)
  → GITHUB_OUTPUT（若有）+ 文件最终值 sync_complete=complete
```

- **禁止**只写 `GITHUB_OUTPUT` 不写文件。  
- **原子写：** temp + `os.replace`（或等价），避免半截 JSON。  
- hard_freeze/戳失败：**必须**使文件为 `sync_complete=false`（或删除文件；二选一钉死为 **写 false**），不得留下旧 `true`。  
- 进程在悲观写之前被杀：无文件 → check FAIL（缺文件 = FAIL）。

#### 3.1.2 文件 schema

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
| `sync_complete` | bool |
| `elapsed_min` | float |
| `written_at` | UTC ISO8601 |
| `session_asof` | 本次 sync 的 `session_asof`（`YYYY-MM-DD`）；**必填** |

### 3.2 入口检查（仅 live_shadow）

`check_sync_complete_for_fill(*, status_path=None, require_asof: str) -> int`  # 0 ok, 1 fail  

`require_asof` = 本次影子成交日 `T`（`YYYY-MM-DD`）。

```text
status ← read sync_status.json
if missing or invalid JSON → FAIL
if sync_complete is not true → FAIL
if status.session_asof != require_asof → FAIL
→ ok
```

| 入口 | 挂点 |
|------|------|
| `live_shadow_step.run_asof` | 入口、`fill_day` 之前；传入 `require_asof=T` |
| `live_shadow_step.main` | 薄封装；**禁止**只挂 `main` |

**不门：** `paper_book`（历史 Audit H；冷 clone / 无 SoT 须仍可绿）。后放：显式 `--require-sync-complete`。

失败 stderr 示例：

```text
[sync_authority] no fresh sync_complete for asof=YYYY-MM-DD
(missing/stale/false data/cache/sync_status.json) — partial bars non-authoritative;
re-run full sync for that session_asof before live_shadow
```

**调试旁路（钉死）：** 仅 `TRENDING_ALLOW_INCOMPLETE_FILL=1` 可跳过本检查。默认未设。文档标危险。**CI 主路径测试禁止**依赖该变量变绿（验收 #）。

### 3.3 sync / limits 行为（不变，仅重申）

| 项 | 行为 |
|----|------|
| `--with-limits` | 仅 `complete ∧ end == session_asof` |
| asof board_calc | 禁止 |
| incomplete + 硬冻/戳成功 | 仍写戳；文件最终 `sync_complete=false`；sync exit 0 |
| Spec F metrics | `sync_complete != true` → job skip |

### 3.4 产品句（文档）

> Incomplete sync 或 SoT 显示非 complete / asof 不匹配时，**禁止**宣称当日 `live_shadow` / `paper_fill` 有效。须对该 `session_asof` 完整 sync 后再跑影子。`paper_book` 历史审计不在本门默认范围内。

---

## 4. 数据流

```text
sync:
  early write sync_status(false, session_asof)
  → OHLC / limits? / Spec E
  → on hard_freeze fail: write sync_status(false); exit 1
  → on success end: write_sync_complete(complete, session_asof) → GITHUB_OUTPUT + file

live_shadow.run_asof(T):
  → check_sync_complete_for_fill(require_asof=T)
       fail → exit 1
       ok   → limit_rule 门（姊妹）→ fill_day → paper_fill
```

---

## 5. 验收

| # | 断言 |
|---|------|
| 1 | 悲观写后、成功完成前：文件 `sync_complete=false`；`check_*(require_asof=…)` == 1 |
| 2 | `write_sync_complete(True, session_asof=D)` 后 `check_*(require_asof=D)` == 0 |
| 3 | 缺文件 / 非法 JSON → 1 |
| 4 | 陈旧：文件 `true` 且 `session_asof=D1`，`require_asof=D2≠D1` → 1 |
| 5 | 模拟 hard_freeze 失败：文件为 `false`（非残留 `true`）；`check_*` == 1 |
| 6 | `run_asof` 在失败时不写 `paper_fill`；直调 `run_asof` 不可旁路 |
| 7 | `paper_book` **无**本门时：无 `sync_status` 夹具仍可跑通既有 Audit 测 |
| 8 | 默认未设 env 时旁路无效；设 `TRENDING_ALLOW_INCOMPLETE_FILL=1` 可放行（单测）；主路径套件不依赖该 env |
| 9 | `with_limits` 在 `not complete` 时不拉东财（回归） |
| 10 | workflow 仍含 `needs.sync.outputs.sync_complete == 'true'`（回归） |
| 11 | 落地时 todo P0 行改写为已落地并链本 Spec |

---

## 6. 文档与待办

- `todo.md` / README 产品句。  
- `docs/ops/hard-freeze-stamp-runbook.md` 或短节：incomplete → 非权威影子；先完整 sync。  
- Protocol B 失败路径与本 Spec §3.1.1 交叉一句。

---

## 7. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-11 | 初版：不拆耦；sync_status；fill/影子门 |
| 2026-10-11 | CR：悲观写 + 失败写 false；检查 `session_asof`；仅门 `run_asof`；不门 `paper_book`；env/陈旧验收 |
