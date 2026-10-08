# Spec D：宇宙扩张（YAML 日拉 + unmapped 可见）

**日期：** 2026-10-08  
**状态：** 设计已审（待 plan）  
**范围：** todo §2.4 成分 YAML 每日 vendor 拉新（Actions 直推 main）+ §2.3 未映射计数与 IPO 告警（软门、**不做**树外 bars 预热）。  
**后放（禁止混入本 slice）：** 树外票 `sync_bars` 预热；fetch 失败杀死日更；PR 审合后再用新宇宙；`unmapped_count>0` → `evaluate_ok` partial；Spec E `board_calc` / `limit_up_unfillable` / 显式硬冻；L2/L1 `engine_state`；改温度 / RS / peer 语义；北交所进树。

交叉：taxonomy [`2026-09-28-industry-taxonomy-design.md`](2026-09-28-industry-taxonomy-design.md) §5.2 / §6.1 · SW YAML [`2026-10-05-sw-yaml-universe-design.md`](2026-10-05-sw-yaml-universe-design.md) · ops [`2026-10-07-ops-daily-run-hemostasis-design.md`](2026-10-07-ops-daily-run-hemostasis-design.md) · 待办 [`todo.md`](../../../todo.md) §2.3–2.4 / Spec D

产品对齐：映射宇宙仍是 Git 权威快照（可复现）；D 解决的是 **快照如何按日从 vendor 刷新并发布**，以及 **树外缺口可见**，不是取消快照、也不是把全 A 算进行业树。

---

## 1. 问题

- `stock_sw_l2.yaml` 为 check-in 快照；`fetch_sw_members.py` 仅手工 one-shot；cron **不**改映射 → 新股/调行业滞后。  
- `run_meta.unmapped_count` **硬编码 0**；taxonomy「应归属未归属 = 0 / IPO 三日告警」未接。  
- 曾讨论「daily_run 内实时 HTTP 拉行业、不落 Git」→ 破坏 `map_version` / `git_sha` 复现 → **否决**。  
- 树外票无 L2，**没有** Issue/雷达挂载点；为其预热 bars 只省日后冷启动，本 slice **默认不做**。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 架构 | **Approach 1：同 job 前置**——`daily-trend` 在 sync 前 refresh YAML → 有 diff 则 commit+push `main` → 同 job `daily_run` 读工作区新文件 |
| §2.4 | `fetch_sw_members`（§4 归一不变）；可选 `patch_stock_names`；直推 main |
| §2.3 | `unmapped_count` + IPO≥3 日告警；**软门**（只 warn）；**无**树外 bars 预热 |
| fetch 失败 | 保留旧 YAML，继续 sync / `daily_run`；heartbeat `taxonomy_fetch=fail` |
| `map_version` | 任一 `ts_code↔sw_l2_code` 变更（含进出 quarantine）→ bump；仅 `name_zh`/note → 不 bump 仍可 commit |

### 2.1 流水线顺序

```text
1. checkout
2. Taxonomy refresh（新）
   a. fetch_sw_members → 候选 stock_sw_l2.yaml（§4 归一；BJ 丢弃；禁 801xxx）
   b. 可选 patch_stock_names（只补 name_zh，不加 ts_code）
   c. diff vs HEAD：
      - membership / sw_l2 变更 → bump map_version 后写盘
      - 仅 name_zh/note → 不 bump，仍可写盘
      - 无实质 diff → 跳过 commit
   d. 有 diff → git commit + push main（仅 taxonomy YAML）
   e. vendor/fetch 失败 → 不改文件、不 push；taxonomy_fetch=fail；继续 3
3. Sync mapped-universe bars（codes = load_universe_codes()，不含树外）
4. daily_run → shadow → commit trend.db/heartbeat → Issues
```

同 job 内步骤 4 读的是步骤 2 之后工作区 YAML。`run_meta.map_version` = `load_map_version()`（刷新后）。

冷启动提醒（与本 slice 预热无关）：票 **首次进入 mapped U** 时，`sync_symbol_bars` 默认窗口为 `end − 400` 自然日，以便攒够 metrics §3.3 的 **~252 交易日**（温度 / `ROC_252` / `vol_hist`）。日常少量 IPO 可接受；调树导致大批 quarantine→mapped 时可能顶满 sync 200min budget（既有 `run_deferred`），不在本 slice 另做摊销除非实现期证明必要。

### 2.2 `unmapped_count` 与 IPO 告警

| 集合 | 定义 |
|------|------|
| `clist` | 东财 `FS_ALL_A` 沪深 A；只保留 `^\d{6}\.(SH\|SZ)$` |
| `mapped` | `load_universe_codes()` |
| **`unmapped_count`** | `|clist − mapped|`（含 YAML 空码 quarantine，以及 clist 有但 YAML 无行） |

北交所 / 非 SH|SZ **不计入** unmapped（本就不进树）。

**IPO 告警（软）：**

- 对每个 unmapped 码估计上市以来 **交易日数**：优先 vendor `list_date` → 交易日历；若无，则用「首次被本流水线记为 unmapped」的 asof（状态文件 `data/cache/unmapped_first_seen.json`，随仓库或 Actions 产物保留——实现钉 **check-in 该 cache** 以便本地/CI 复现）。  
- `ipo_unmapped_alert_count` = 交易日数 **≥ 3** 仍无合法 `sw_l2` 的个数。  
- **不**使 `evaluate_ok` 变为 `partial`。

**写入：**

| 位置 | 字段 |
|------|------|
| `run_meta` | `unmapped_count` = 上式（禁止再硬编码 0） |
| heartbeat（嵌套） | `taxonomy_fetch`: `ok` \| `fail` \| `skipped_no_diff`；`unmapped_count`；`ipo_unmapped_alert_count`；`map_version`；可选 `taxonomy_commit` |
| 日志 / `run_meta.warn` 附加 | fetch fail 或 `ipo_unmapped_alert_count>0` 时短文案（status 仍可为 ok） |

**明确不给树外票：** `daily_stock` 产品路径、L2/L1 合成、`local_stock` RS peer、Issue 表挂载。树外在归属前对选筹 **无下游**；§2.3 只服务 ops 可见性。

### 2.3 `map_version` bump

比较候选与 HEAD `stock_sw_l2.yaml` 成员：

- **Bump 若：** 新增/删除 `ts_code`，或同一码 `sw_l2_code` 变化（含 `null`↔码）。  
- **不 bump：** 仅 `name_zh` / note / 行序。  
- 格式：`sw2021-vN` → `sw2021-v(N+1)`（解析失败 → `sw2021-v2` + 日志）。  
- 写入时 **三文件头同值**：`stock_sw_l2.yaml`、`sw_l2_to_l1.yaml`、`l1_buckets.yaml`（即使 L2→L1 表体未改，也同步改版本字符串，避免 `load_map_version()` 与成员文件分叉）。  
- Commit 示例：`chore(taxonomy): refresh stock_sw_l2 (map_version=sw2021-v2)`；无 diff 不 commit。

---

## 3. 架构要点

1. Canonical 仍是 Git YAML；禁止「只在 Actions 内存里用、不落库」的平行宇宙。  
2. Taxonomy 步需要 `contents: write`（或等价 token）才能 push；失败降级不得阻塞步骤 3–4。  
3. `fetch_sw_members` 归一算法 **不改**（SW YAML spec §2）；本 slice 只接 cron 与版本/diff/门禁。  
4. `mapped_size` / `mapped_sync_coverage` / bar 门禁 **分母不变**（仍 mapped）；不得把 U 缩成「有 bar 子集」刷 coverage。  
5. Spec C peer 资格与温度路径 **不动**。

---

## 4. 测试与 Done-when

### 4.1 测试

| 测试 | 断言 |
|------|------|
| normalize（已有可保留） | BJ / 801xxx 不进生产 YAML |
| bump | membership diff → 版本 +1；仅 name_zh → 版本不变 |
| fetch fail | vendor 抛错 → 工作区 YAML 不变；后续可继续 |
| `unmapped_count` | clist 夹具 − mapped → 非恒 0 的正确计数 |
| IPO≥3 | first_seen/list_date 夹具 → `ipo_unmapped_alert_count`；`evaluate_ok` 可为 ok |
| wire（可选） | `run_meta.unmapped_count` 来自计算而非字面 0 |

### 4.2 Done-when

1. `daily-trend.yml`：taxonomy refresh 在 sync 之前；有 diff 可直推 main；fail 不杀日更。  
2. `run_meta.unmapped_count` 为真值；heartbeat 含 §2.2 taxonomy 字段。  
3. 无树外 bars 预热；sync 列表仍为 mapped。  
4. `todo.md` Spec D → **已完成**；Next = Spec E；README Still out 去掉「unmapped 全A sync」或改为注明「计数/告警已做、预热未做」。  
5. 上表测试绿。

---

## 5. 文件影响（预期）

| 路径 | 变更 |
|------|------|
| `.github/workflows/daily-trend.yml` | 前置 taxonomy 步 + permissions |
| `scripts/taxonomy/fetch_sw_members.py`（或新 `refresh_taxonomy.py`） | CLI：写盘 / diff / bump / 退出码约定 |
| `scripts/taxonomy/` 或 `scripts/common/` | `unmapped_count` / IPO 计数；first_seen cache |
| `scripts/daily_run.py` | 写入真 `unmapped_count`；heartbeat 字段 |
| `data/cache/unmapped_first_seen.json` | 新建（或等价） |
| `tests/` | bump / unmapped / fetch-fail / IPO |
| `todo.md` / `README.md` | done-when |

---

## 6. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-08 | 初版：Approach 1 同 job YAML 日拉直推；§2.3 计数+告警软门、无预热；fetch 失败降级；map_version bump 规则 |
