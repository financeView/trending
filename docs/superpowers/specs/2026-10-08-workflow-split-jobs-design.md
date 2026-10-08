# Spec F：daily-trend 拆成 sync + metrics 两 job

> 状态：草案  
> 日期：2026-10-08  
> 依赖：  
> - [`2026-09-30-ops-action-and-eval-design.md`](./2026-09-30-ops-action-and-eval-design.md)（`sync_complete` / Actions 骨架）  
> - [`2026-10-05-sw-yaml-universe-design.md`](./2026-10-05-sw-yaml-universe-design.md)（`run_deferred` 原文将被本文件取代）  
> - [`2026-10-08-universe-expansion-design.md`](./2026-10-08-universe-expansion-design.md)（taxonomy 步顺序）  
> - [`2026-10-08-spec-e-fill-hard-freeze-design.md`](./2026-10-08-spec-e-fill-hard-freeze-design.md)（sync 内 Spec E passes；「同 job」指 sync **进程**，非整个 workflow）  
> 相关：`todo.md` P0/P3 `run_deferred` 错位

---

## 1. 问题

单 job `trend`（`timeout-minutes: 360`）内串行：单测 → taxonomy → sync（步超时 330）→ daily_run / shadow / commit / Issues。

| 机制 | 行为 | 痛点 |
|------|------|------|
| `--time-budget-min` 200/300 | OHLC 循环提前停 → `sync_complete=false` | 宇宙未齐时跳过 metrics（有意） |
| `run_deferred`（complete ∧ elapsed>200） | **仍 success**，但跳过 daily_run / shadow / commit / Issues | **假绿**：bars 已更新（含 Spec E），指标与 Issue 未跑；运营误判「日更完成」 |

GitHub-hosted：**每个 job 独立最多 6h**。拆 job 后 sync 与 metrics **不再抢同一 6h 桶**，不必再用 `run_deferred` 饿死 metrics。

---

## 2. 目标与非目标

**目标**

1. `daily-trend.yml` 拆为两 job：`sync` → `metrics`（`needs: sync`）。  
2. **废除**「`run_deferred` 跳过 metrics」门闩；`sync_complete=true` 则 **必须** 进入 metrics job（除非 dispatch 显式跳过 Issue 等既有开关）。  
3. sync 在 job 超时内尽量跑满：生产 cron / only_date **不再**用 200/300 min 的 `--time-budget-min` 主动截断（见 §4.2）；未完成宇宙仅因硬超时/进程被杀或显式失败。  
4. 假绿治理：**废除**「complete 却跳过 metrics」；`sync_complete=false` 时 sync 步打 `::warning::` + README 写清「仅 sync 绿 ≠ 日更完成」（GitHub 对 skipped metrics 仍可能整 run success——本 slice 用 warning/文档区分，不强制把 incomplete 改成 job failure）。  
5. bars 交接：同 `github.run_id` 的 cache（或等价 artifact）保证 metrics 读到本轮 sync 写入的 `data/cache`。

**非目标**

- 改 Spec E pass 语义、board_calc / hard_freeze 算法。  
- 改 daily_run / fill 业务逻辑。  
- 自建 runner、突破 hosted 6h。  
- 把 taxonomy 挪出 sync job（仍：单测 → taxonomy → sync bars）。  
- Radar T\* / `name_zh` 等展示问题（另项）。

---

## 3. 方案（已选）

**Approach：同一 workflow、两个 job（推荐，已锁定）**

```text
job sync (timeout 360)
  checkout → python → cache restore
  → unit tests → taxonomy refresh
  → sync_bars (+ Spec E passes) → GITHUB_OUTPUT sync_complete
  → cache save（actions/cache 在 job 结束时按 key 保存）

job metrics (timeout 360, needs: sync)
  if: sync_complete == 'true'
  checkout → python → cache restore（同 run_id key）
  → daily_run → live_shadow → commit trend.db+heartbeat → Issues
```

| 备选 | 为何不选 |
|------|----------|
| A. 保持单 job + 仅抬 deferred 阈值 | 仍共抢 6h；假绿可复发 |
| B. sync 末 `gh workflow run` 另起 workflow | 鉴权/并发/传库更绕；两 job 已天然新 runner |
| C. 本方案 | 独立 6h；语义清晰；cache key=`bars-${{ github.run_id }}` 同 run 可 restore |

---

## 4. 契约

### 4.1 Job 与超时

| Job | `timeout-minutes` | 职责 |
|-----|-------------------|------|
| `sync` | **360** | 单测、taxonomy、`sync_bars_sample`（含 Spec E）、写出 `sync_complete` |
| `metrics` | **360** | 仅当 `needs.sync.outputs.sync_complete == 'true'`：daily_run → shadow → 一次 commit → Issues |

- sync 步 **不再**单独 `timeout-minutes: 330`（避免低于 job 帽）；依赖 job 360。  
- `permissions` / `concurrency.group: daily-trend` / `cancel-in-progress: false` **保持**（整次 run 串行；不拆两组，避免补跑与 cron 交错写 main）。

### 4.2 Sync 预算（取代 200/300 截断）

| 项 | 旧 | 新 |
|----|----|-----|
| cron `--time-budget-min` | 200 | **省略或 0**（无预算截断） |
| only_date `--time-budget-min` | 300 | **省略或 0** |
| OHLC 未跑完宇宙 | `complete=false` → 跳过 metrics | **仅**在硬超时/杀进程导致未调用 `write_sync_complete(true)`，或代码显式 `complete=false`（若保留 max-codes 等测试开关）时跳过 metrics |
| `run_deferred` 门闩 | complete ∧ elapsed>200 → skip metrics | **删除** |

`write_sync_complete`：

- 继续写 `sync_complete` / `sync_elapsed_min`。  
- **停止**写 `run_deferred`，或恒写 `false` 一版后删除（实现选一；测试与 yml **不得**再读该输出做 `if`）。  
- 日志可保留 `elapsed_min=` 供观测。

Spec D / sw-yaml 文中「预算 200/300 + run_deferred」→ 改为指向本 Spec F。

### 4.3 产物交接（bars）

| 机制 | 规则 |
|------|------|
| Cache path | `data/cache`（含 `bars.db` 等，与现一致） |
| Cache key | `bars-${{ github.run_id }}`（两 job **相同**） |
| restore-keys | `bars-`（冷启动） |
| metrics | **必须**在跑 daily_run 前 restore；禁止假定 runner 磁盘上有 sync 的本地文件 |

taxonomy 若 push 了 YAML：metrics job **重新 checkout**（默认）即可读到 remote；`TAXONOMY_HEAD_SHA` / `TAXONOMY_FETCH` 经 **job outputs** 从 sync 传入 metrics（与现 env 同名）。

`trend.db` / heartbeat：**仅 metrics job** commit（保持「一次 commit」）。

### 4.4 Job outputs 与门闩

**sync outputs（最少）：**

- `sync_complete`: `true` \| `false`  
- `taxonomy_head_sha` / `taxonomy_fetch`（taxonomy 步已有则透出）

**metrics `if`：**

```yaml
needs: sync
if: ${{ needs.sync.outputs.sync_complete == 'true' }}
```

- `skip_issue_update` 仅影响 Issues 步（不变）。  
- **禁止**再出现 `run_deferred` 条件。

**`sync_complete=false`：** metrics job 整 job skip；sync job 本身仍 exit 0（便于 cache 保存）——与现「incomplete 不红 sync」一致。

### 4.5 结论语义（反假绿）

| 情况 | sync job | metrics job | 期望认知 |
|------|----------|-------------|----------|
| sync_complete + metrics 全绿 | success | success | **日更闭环成功** |
| sync_complete=false，metrics skipped | success | skipped | **未闭环**；须在 sync 步打 `::warning::`（或 job summary）写明 `sync_incomplete`，README/注释同步 |
| sync 失败 | failure | skipped | 失败 |
| sync_complete + metrics 失败 | success | failure | **workflow 失败**（指标未落地） |

本 slice **不要求**把 `sync_complete=false` 改成 sync job failure（以免打断 cache / 续跑习惯）；但 **必须** `::warning::sync_incomplete`（或等价），且文档写清「绿 sync ≠ 日更完成」。整 run 在 metrics skipped 时仍可能显示 success——接受，靠 warning + 看 metrics job 是否执行区分。

废除 deferred 后，**不再出现**「complete=true 却跳过 metrics」的假绿（那是本次要打死的形态）。

### 4.6 步序（metrics job 内）

钉死顺序（与现一致）：

1. `daily_run`  
2. `live_shadow`（only_date → `--asof "$DATE"`；否则 `--from-heartbeat`）  
3. **一次** `git commit`（`trend.db` + `heartbeat.json`）  
4. Update L1 / Radar Issues（`continue-on-error: true`）

`daily_run` / shadow 的 date / only_date / force_trade_day 输入语义不变。

### 4.7 Spec E / Spec D 交叉

- Spec E passes 仍在 **sync 进程**内、`write_sync_complete` 前；「Approach 1 同 job」= 同 **sync job**，不要求与 metrics 同 runner。  
- Spec D：taxonomy 仍在 sync job、sync bars 之前；unmapped/IPO 不因拆 job 退回只放 daily_run。  
- incomplete sync：Spec E passes 仍跑（既有）；metrics 仍跳过。

---

## 5. 测试与验收

### 5.1 工作流静态测试（更新 `tests/test_p2_workflow_order.py` 等）

1. 存在 job id `sync` 与 `metrics`；`metrics.needs` 含 `sync`。  
2. `metrics.if` 含 `sync_complete == 'true'`，**不含** `run_deferred`。  
3. sync job 内顺序：Unit tests → Refresh taxonomy → Sync mapped-universe。  
4. metrics 内顺序：daily_run → live_shadow → commit → Issues；整文件仅 **一次** trend.db commit。  
5. 两 job 均 `timeout-minutes: 360`（或 metrics≥180 且 pin 为 360）。  
6. cache key 两处均为 `bars-${{ github.run_id }}`（或计划钉死的同一表达式）。  
7. only_date → shadow `--asof` 断言保留。

### 5.2 `write_sync_complete` 单测

- 不再因 `elapsed_min > 200` 产生可被 workflow 消费的 deferred 门闩。  
- 仍写出 `sync_complete`。

### 5.3 手工 / Actions

- `workflow_dispatch` only_date 历史日：sync 长跑后 metrics **仍启动**（只要 complete）。  
- cron 常态：两 job 皆绿；Issue 更新。

### 5.4 文档

- `README.md`：删除「Sync >200 min → run_deferred」句；改为两 job + incomplete 语义。  
- `2026-10-05-sw-yaml-universe-design.md` §相关：run_deferred 段标废弃并链本 Spec。  
- Spec E / Spec D 中「同 job / run_deferred 预算」歧义句：补一句「workflow 两 job；sync 进程内…」。  
- `todo.md`：P3 `run_deferred` 行改为本 Spec 或标完成。

---

## 6. 明确不做

- sync 成功后由脚本 `gh workflow run` 另起 workflow。  
- 保留 `run_deferred` 作为 metrics `if` 条件。  
- 生产继续默认 `--time-budget-min` 200/300。  
- 拆 concurrency 为两组（本 slice 不拆）。

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-08 | 初版：两 job；废 deferred 门闩；废生产 time-budget 截断；cache 同 run_id；反假绿 warning |
