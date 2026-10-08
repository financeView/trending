# Spec D：宇宙扩张（YAML 日拉 + unmapped 可见）

**日期：** 2026-10-08  
**状态：** 设计稿（self-review 已补丁；待用户审）  
**范围：** todo §2.4 成分 YAML 每日 vendor 拉新（Actions 直推 main）+ §2.3 未映射计数与 IPO 告警（软门、**不做**树外 bars 预热）。  
**后放（禁止混入本 slice）：** 树外票 `sync_bars` 预热；fetch 失败杀死日更；PR 审合后再用新宇宙；`unmapped_count>0` → `evaluate_ok` partial；Spec E `board_calc` / `limit_up_unfillable` / 显式硬冻；L2/L1 `engine_state`；改温度 / RS / peer 语义；北交所进树。

交叉：taxonomy [`2026-09-28-industry-taxonomy-design.md`](2026-09-28-industry-taxonomy-design.md) §5.2 / §6.1 · SW YAML [`2026-10-05-sw-yaml-universe-design.md`](2026-10-05-sw-yaml-universe-design.md) · ops [`2026-10-07-ops-daily-run-hemostasis-design.md`](2026-10-07-ops-daily-run-hemostasis-design.md) · 待办 [`todo.md`](../../../todo.md) §2.3–2.4 / Spec D

产品对齐：映射宇宙仍是 Git 权威快照（可复现）；D 解决的是 **快照如何按日从 vendor 刷新并发布**，以及 **树外缺口可见**，不是取消快照、也不是把全 A 算进行业树。

**覆盖 taxonomy §5.2：** 该节「`unmapped_count` 必须为 0 才生产就绪」对本 slice 的 **`evaluate_ok` 不生效**；改为软门（warn only）。健康度字段仍暴露真值，便于日后再收紧。

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
| §2.4 | `fetch_sw_members`（§4 归一不变）；成功后 `patch_stock_names`（失败软）；直推 main |
| §2.3 | `unmapped_count` + IPO≥3 日告警；**软门**（只 warn）；**无**树外 bars 预热 |
| fetch 失败 | 保留旧 YAML，继续 sync / `daily_run`；heartbeat `taxonomy_fetch=fail` |
| `map_version` | 任一 `ts_code↔sw_l2_code` 变更（含进出 quarantine）→ bump；仅 `name_zh`/note → 不 bump 仍可 commit |

### 2.1 流水线顺序

对 **每次** `daily-trend` 运行都执行步骤 2（含 `workflow_dispatch` / `only_date`）：行业分类快照是 vendor「今日」截面，非 PIT；与补洞日 `D` 无关。

```text
1. checkout
2. Taxonomy refresh（新）
   a. fetch_sw_members → 候选 stock_sw_l2.yaml（§4 归一；BJ 丢弃；禁 801xxx）
   b. fetch 成功后：patch_stock_names（只补 name_zh，不加 ts_code）
      - name patch 失败 → warn，不回滚 a；不因此失败步骤 2
   c. diff vs HEAD：
      - membership / sw_l2 变更 → bump map_version 后写盘
      - 仅 name_zh/note → 不 bump，仍可写盘
      - 无实质 diff → 跳过 commit；taxonomy_fetch=skipped_no_diff
   d. 有 diff → git commit + push main（**仅** config/taxonomy/*.yaml，可含
      data/cache/unmapped_first_seen.json 若同步更新）
      - push 前若 behind origin：pull --rebase（仅 taxonomy 相关）再 push
   e. vendor/fetch 失败 → 不改 YAML、不 push；taxonomy_fetch=fail；继续 3
   f. **无论 3/4 是否 deferred/skip**：merge 写入 heartbeat.taxonomy（见 §2.2）
3. Sync mapped-universe bars（codes = load_universe_codes()，不含树外）
4. daily_run → shadow → commit trend.db + heartbeat（及既有路径）→ Issues
```

同 job 内步骤 3–4 读的是步骤 2 之后工作区 YAML。`run_meta.map_version` = `load_map_version()`（读 `sw_l2_to_l1.yaml` 头；故 bump 必须三文件同值）。

**双 commit：** 步骤 2d 可能已 push taxonomy；步骤 4 末的 db/heartbeat commit **不得**再次改写已推送的 taxonomy 文件（工作区保持与 origin 一致或不再 stage 它们）。步骤 2 已 push 而 3/4 失败 → main 上已有新 YAML、当日可能无新 `trend.db`：可接受；下次 cron 用新映射续跑。

冷启动提醒（与本 slice 预热无关）：票 **首次进入 mapped U** 时，`sync_symbol_bars` 默认窗口为 `end − 400` 自然日，以便攒够 metrics §3.3 的 **~252 交易日**（温度 / `ROC_252` / `vol_hist`）。日常少量 IPO 可接受；调树导致大批 quarantine→mapped 时可能顶满 sync 200min budget（既有 `run_deferred`），不在本 slice 另做摊销除非实现期证明必要。

### 2.2 `unmapped_count` 与 IPO 告警

| 集合 | 定义 |
|------|------|
| `clist` | 东财 `FS_ALL_A` 沪深 A；只保留 `^\d{6}\.(SH\|SZ)$` |
| `mapped` | `load_universe_codes()` |
| **`unmapped_count`** | `|clist − mapped|`（含：clist∩YAML 空码 quarantine，以及 clist 有但 YAML 无行） |

北交所 / 非 SH|SZ **不计入**。  
**不算进 unmapped：** 仅存在于 YAML quarantine、但已不在 `clist` 的退市/摘牌残留（可另计 `yaml_quarantine_size=|load_quarantine_codes()|` 写入 heartbeat，**不**进 `unmapped_count`）。

**clist 拉取失败：** `unmapped_count` / `ipo_unmapped_alert_count` 写 **SQL NULL / JSON null**（或省略字段），heartbeat `clist_fetch=fail`；**禁止**再写字面 `0` 假装健康。`evaluate_ok` 仍按既有 coverage 门禁，不因 clist 失败而 partial。

**IPO 告警（软）：**

- 对每个 **unmapped** 码估计上市以来 **交易日数**：优先 vendor `list_date` → 交易日历；若无，则用「首次被本流水线记为 unmapped」的 asof。  
- 状态文件：**check-in** `data/cache/unmapped_first_seen.json`（`ts_code → first_asof`）；码进入 `mapped` 后可删键或保留无关紧要。  
- `ipo_unmapped_alert_count` = 交易日数 **≥ 3** 仍落在 unmapped 集合中的个数。  
- **不**使 `evaluate_ok` 变为 `partial`。

**写入：**

| 位置 | 字段 |
|------|------|
| `run_meta` | `unmapped_count` = 上式或 null（禁止成功路径硬编码 0） |
| `heartbeat.taxonomy`（与 `daily_run` **并列**） | `taxonomy_fetch`: `ok` \| `fail` \| `skipped_no_diff`；`clist_fetch`: `ok` \| `fail`；`unmapped_count`；`ipo_unmapped_alert_count`；`yaml_quarantine_size`；`map_version`；可选 `taxonomy_commit` |
| 日志 / `run_meta.warn` 附加 | fetch/clist fail 或 `ipo_unmapped_alert_count>0` 时短文案（status 仍可为 ok） |

步骤 2 结束即 merge `heartbeat.taxonomy`（即使步骤 3 `run_deferred` 跳过 daily_run）。步骤 4 的 `write_heartbeat` **不得抹掉** `taxonomy` 键。

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
2. 既有 workflow 已有 `permissions.contents: write`（trend.db push）；taxonomy 步复用同一 token。push 失败 → 视同 fetch 降级路径的变体：`taxonomy_fetch=fail`（或 `push_fail`），**不**阻塞 3–4；工作区若已写盘则当日 daily_run 仍可用新文件，但 main 可能未更新——须在日志标明，下次 job 会重试 commit。  
3. `fetch_sw_members` 归一算法 **不改**（SW YAML spec §2）；本 slice 只接 cron 与版本/diff/门禁。  
4. `mapped_size` / `mapped_sync_coverage` / bar 门禁 **分母不变**（仍 mapped）；不得把 U 缩成「有 bar 子集」刷 coverage。  
5. Spec C peer 资格与温度路径 **不动**。  
6. Exit 码约定（实现钉死）：taxonomy CLI `0`=成功（含 no-diff）；`2`=vendor/fetch 失败（job 继续）；`1`=未预期错误（job 继续但打 error 日志；不得 `exit 1` 杀整 job——workflow 用 `continue-on-error: true` 或脚本始终 0+输出 status）。

---

## 4. 测试与 Done-when

### 4.1 测试

| 测试 | 断言 |
|------|------|
| normalize（已有可保留） | BJ / 801xxx 不进生产 YAML |
| bump | membership diff → 版本 +1；三文件头同值；仅 name_zh → 版本不变 |
| fetch fail | vendor 抛错 → 工作区 YAML 不变；CLI/workflow 不杀后续 |
| clist fail | `unmapped_count` 为 null，不得写 0 |
| `unmapped_count` | clist 夹具 − mapped → 正确计数；YAML-only quarantine 不计入 |
| IPO≥3 | first_seen/list_date 夹具 → `ipo_unmapped_alert_count`；`evaluate_ok` 可为 ok |
| heartbeat | 写 `taxonomy` 后模拟 daily_run heartbeat → `taxonomy` 键仍在 |
| wire | `run_meta.unmapped_count` 来自计算而非字面 0 |

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
| 2026-10-08 | self-review：覆盖 taxonomy §5.2 硬门；heartbeat.taxonomy 并列且 anti-clobber；clist fail≠0；name patch 软失败；双 commit / deferred；exit 码；YAML-only quarantine 不计 unmapped |
