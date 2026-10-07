# Spec A：Ops 日更止血（limit 软门禁 + heartbeat / only_date）

**日期：** 2026-10-07  
**状态：** 已落地；plan [`2026-10-07-ops-daily-run-hemostasis.md`](../plans/2026-10-07-ops-daily-run-hemostasis.md)  
**范围：**（1）`D == session_asof` 时限价不足 → `run_meta=ok`+`warn`，**`last_ok` 前移**；（2）统一 heartbeat 嵌套读写（含 catch-up `days` 与 skip）；（3）Actions `only_date` 时 shadow 钉交易日。  
**后放（禁止混入）：** Spec B L1 同引擎；Spec C RS；Spec D 全 A / YAML 日拉；Spec E `board_calc` / 历史限价 vendor / 自动重拉 limit；L2 replay 性能。

交叉（**均须同步修订，权威 ok 谓词以 market-data 为准**）：

- market-data [`2026-10-01-market-data-contract-design.md`](2026-10-01-market-data-contract-design.md) §7.2–7.3 / 验收#7（本 slice 已改稿）  
- YAML 宇宙 [`2026-10-05-sw-yaml-universe-design.md`](2026-10-05-sw-yaml-universe-design.md) §3（本 slice 已改稿）  
- ops [`2026-09-30-ops-action-and-eval-design.md`](2026-09-30-ops-action-and-eval-design.md)  
- 待办 [`todo.md`](../../../todo.md) 切片 A · 实证 Actions run `37500945431`（2026-10-06）

---

## 1. 问题（已查证）

### 1.1 `lim=0` → `partial`（§1.1）

`run_meta(2026-09-30)`（本地 `trend.db` 与 Actions 一致）：

- `mapped_sync≈0.95`、`bar≈1`、`comp≈0.98` → 过门槛  
- `limit_coverage_asof=0`、`status=partial`、`warn=limit_coverage_asof<0.80`  
- `D == session_asof == 2026-09-30`（国庆期间 `latest_trade_day()` 冻在 9.30）→ `evaluate_ok` **打开** limit 硬门禁  

Actions 日志（非猜测）：

```text
[sync_bars] warn: limits skipped: call failed after 2 attempts: em_f51f52:
  clist 全部 host 失败: ... RemoteDisconnected(...)
[daily_run] D=2026-09-30 asof=2026-09-30 status=partial
  reason=limit_coverage_asof<0.80 limit_gate=True lim=0.000
```

要点：

1. Workflow 在 `DATE == ASOF` 时**会带** `--with-limits`（未走 skip 分支）。  
2. `sync_em_limits_asof` 调的是东财 **clist 当日 spot**（`f51/f52`）；失败则 **catch → warn → 0 行写入**。  
3. 覆盖率算出 **0 是诚实的**（本 slice **不改**该语义）。  
4. `partial` → `last_ok` 不前移、队列停在该日；`live_shadow` 要 `status=ok` → L 轨跳过。

旧 market-data §7.2「asof limit 不达标 ⇒ status≠ok」与 YAML「缺 limit 仍可 ok」在冻 asof 场景冲突——**以本 spec + 已修订的 market-data v1.2 为准**。

### 1.2 heartbeat / only_date（§1.2）

- `write_heartbeat` 写在 **`daily_run` 嵌套**下；`statuses` 与 `days` 平行，均为 **list**（见生产 `data/heartbeat.json`）。  
- `trade_date_from_heartbeat` 读顶层 → `no_date`；`heartbeat_asof_dates` 另读顶层 `days`；`live_publish_allowed` skip 只看顶层。Issues cron `--from-heartbeat` 与 shadow **同等中招**。  
- Issues `only_date` 已 `--date`；shadow 始终 `--from-heartbeat`。

---

## 2. 对「catch 后 warn、0 行 → 覆盖=0」要不要改？

**不要改覆盖语义；要改的是门禁 + warn 落库 + 续跑合同。**

| 行为 | 本 slice |
|------|----------|
| clist 失败 → catch → stderr warn → **不写假 limit** | **保持** |
| 0 行 → `limit_coverage_asof = 0` | **保持** |
| 仅 limit 不足 → `partial` | **改掉** → `ok`+`warn`，`last_ok` 前移 |
| 失败后自动再拉 limit / 第三态 | **不做**（后放 Spec E 或人工 `only_date` 重跑） |

---

## 3. Limit 门禁新口径（钉死）

`ok_predicate_version` → **`v1.2`**。

### 3.1 仍硬挡 `partial` 的（不变）

- `mapped_sync_coverage < 0.90`  
- `bar_coverage` / `computable_coverage` 既有下限  
- `trade_date > session_asof` → `fail`  
- 分批预算用尽等既有 `partial` 原因  

### 3.2 Limit：软门禁（全局，非仅假日）

**有意全局软化：** 凡 `trade_date == session_asof`（正常收盘 cron **与** 假日冻 asof 补洞），limit 不足都走软门禁。

- 覆盖 ≥ 0.80 → 硬 ok：`reason == "passed"`，`warn` 空。  
- 覆盖不足（含 0）→ **`status=ok`**，`reason == "limit_coverage_asof<0.80"`（**单字符串**；本 slice 不定义多 reason 拼接），`apply_limit_gate=True`，**禁止** `partial`。  

`D < session_asof`：不评估 limit 门槛。

### 3.2.1 `run_meta.warn` 落库（必须改 `daily_run`）

现码：`"warn": decision.reason if not decision.ok else ""` → `ok` 时 warn 恒空。  
改为：`reason != "passed"` 时写入 `warn`（含软 ok）。

### 3.2.2 续跑 / `last_ok`（拍板：前移）

**选定 (a)：** 软 ok 与硬 ok 一样：

- `last_ok_trade_date` **计入**该日（连续 ok 前缀前进）。  
- `daily_run` 队列：`st == "ok"` → **不**因仅缺 limit 停闸。  
- `first_unfinished_trade_date` 不再因「仅 limit」停在该日。  

**接受的后果：** 正常交易日 EM 宕机也会放行 asof `ok` 并前移 `last_ok`；**不**自动重拉 limit。补限价 = 人工/后续 job 对同一 `D` 再 `only_date`（或 Spec E）。个股无 limit 时 L fill 仍 skip/`data_gap`。

**明确拒绝：** (b) 双轨 status（实现复杂）；(c) 第三态（本 slice 非目标）。

### 3.3 Sync（保持）

`--with-limits` 仅 `end == latest_trade_day()`；失败 soft-fail、0 行；禁止假日 spot 回刷历史日。

### 3.4 shadow / Issues

- intent 日 `status==ok`（含软 ok）→ 可进 L；limit warn 不否决。  
- Issues：既有 `partial`/`ok` 策略；嵌套 skip 见 §4。

### 3.5 文档权威

| 文档 | 动作 |
|------|------|
| market-data §7.2–7.3 / 验收#7 | **已改**（v1.2 软门禁 + last_ok 前移） |
| YAML 宇宙 §3 | **已改**（指向本文件，删除「limit 硬卡不变」） |

### 3.6 既有测试合同翻转

- `test_ok_asof_requires_limits` → ok + reason/warn 含 `limit_coverage`。  
- `test_asof_low_limit_run_meta_partial` → 期望 `ok`+warn（或更名）。  
- `test_queue_stops_and_resume_from_gap`：若夹具靠「asof 低 limit → partial」造缺口 → **改为**用 mapped/bar/computable 不足造 `partial`；并加「asof 仅低 limit → ok 且 last_ok 前进」正例。

---

## 4. Heartbeat 合同（钉死）

### 4.1 权威形状（生产）

```json
{
  "updated_at": "...",
  "daily_run": {
    "status": "ok|partial|skip|error|...",
    "asof": "YYYY-MM-DD",
    "days": ["2026-09-30"],
    "statuses": ["ok"]
  }
}
```

- `days` 与 `statuses` 均为 **list**，等长、按下标对齐（见 `daily_run.write_heartbeat`）。  
- **禁止**把 `statuses` 写成 `{date: status}` dict。  
- `write_heartbeat` 保持按 `job` 嵌套。

### 4.2 读路径（必须修）

`_heartbeat_job_view(data)`：有 `daily_run` dict 则用之，否则顶层扁平。

全部经 view：`trade_date_from_heartbeat`、`heartbeat_asof_dates`（**全** `days` 列表）、`live_publish_allowed` 的 skip 门。

### 4.3 测试

嵌套正例（日期、`days` 全列表、skip）；扁平回退；消灭假绿。

---

## 5. Actions `only_date` 与 shadow

| 消费者 | `only_date=true` | cron / catch-up |
|--------|------------------|-----------------|
| Issues | 已有 `--date "$DATE"` | `--from-heartbeat` |
| shadow | **仅** `--asof "$DATE"`（**不要**再叠 `--from-heartbeat`，否则 CLI 优先 heartbeat） | `--from-heartbeat`（依赖 §4） |

语义：only_date 时 shadow intent 日 `T = DATE`，与 Issues 同日。

---

## 6. 非目标

- 历史限价 API / `board_calc` / **自动重拉 limit**  
- 改 mapped/bar/computable 阈值；引擎 / RS / Issue 表头  
- 第三态；仅假日特判；提交 `trade_dates.json` 噪声  

---

## 7. 验收

1. `evaluate_ok`：`D==asof`、其它过、limit=0 → `ok`，`reason` 含 `limit_coverage_asof`，`apply_limit_gate`。  
2. 经 `process_day`：`run_meta.status=ok` 且 **`warn` 非空**。  
3. 同上：`last_ok_trade_date` **等于**该 asof 日（前移）。  
4. `D < asof`、limit=0 → 仍 ok（回归）。  
5. 嵌套 heartbeat：非 `no_date`；`heartbeat_asof_dates` 返回完整 `days`；嵌套 skip 生效。  
6. Workflow：`only_date` 下 shadow **只有** `--asof`（无 `--from-heartbeat`）。  
7. 翻转：`test_ok_asof_requires_limits`、`test_asof_low_limit_run_meta_partial`、resume/queue 夹具。  
8. Offline pytest 绿；`ok_predicate_version=v1.2`。

---

## 8. 实现落点（供 plan，非代码）

| 区域 | 文件 |
|------|------|
| 软门禁 | `scripts/common/coverage.py` |
| warn + 队列 | `scripts/daily_run.py` |
| 测试 | `tests/test_p0_core.py`、`tests/test_daily_run_metrics_wire.py`、heartbeat 测 |
| heartbeat | `update_l1_issues.py`、`live_shadow_step.py` |
| workflow | `.github/workflows/daily-trend.yml` |
| 文档 | 本文件；market-data；YAML 宇宙 §3；`todo.md` |

---

## 9. Spec CR follow-up

| Finding | Verdict | Action |
|---------|---------|--------|
| 软 ok 推进 `last_ok` / 与 market-data 冲突 | **真** | 拍板 (a) 前移；改 market-data §7.2–7.3 / 验收#7；§3.2.2 |
| 只改 YAML 不改 market-data → 合同分裂 | **真** | §3.5；两文档已改稿 |
| `ok` 清空 warn | **真** | §3.2.1 |
| `heartbeat_asof_dates` / Issues cron 顶层读 | **真** | §4.2 |
| §4.1 `statuses` 写成 dict | **真（形状错）** | 改为与 `days` 平行的 list |
| wire/resume 测未点名翻转 | **真** | §3.6 / 验收 #7 |
| 全局软化低估正常日 EM 宕机 | **真** | §3.2.2 接受后果；非目标写明不自动重拉 |
| only_date 勿叠 `--from-heartbeat` | **真** | §5 |
| 多 reason 拼接约定 | **真歧义** | 钉单字符串，不拼接 |
| 标题「假日」易误导 | **真 nit** | 标题改为 limit 软门禁 |
| §1.1 覆盖率精确数字 | **待核实** | 不挡落地；以 Actions `lim=0`/`partial` 为准 |
| clist soft-fail 保持 | **真（保持）** | §2 |
