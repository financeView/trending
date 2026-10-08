# Spec D：宇宙扩张（YAML 日拉 + unmapped 可见）

**日期：** 2026-10-08  
**状态：** 设计稿（indep-CR 真项已补丁；待用户审）  
**范围：** todo §2.4 成分 YAML 每日 vendor 拉新（Actions 直推 main）+ §2.3 未映射**计数与 IPO 告警**（软门、**不做**树外 bars 预热）。  
**后放（禁止混入本 slice）：** 树外票 `sync_bars` 预热（仍留 todo §2.3 一行遗留，**不**算 Spec D 做完就消失）；fetch 失败杀死日更；PR 审合后再用新宇宙；`unmapped_count>0` → `evaluate_ok` partial；Spec E `board_calc` / `limit_up_unfillable` / 显式硬冻；L2/L1 `engine_state`；改温度 / RS / peer 语义；北交所进树（本 slice **丢弃** BJ，收窄 SW YAML「丢弃或 quarantine」）。

交叉：taxonomy [`2026-09-28-industry-taxonomy-design.md`](2026-09-28-industry-taxonomy-design.md) §5.1–5.2 / §6.1 / §9.1 · SW YAML [`2026-10-05-sw-yaml-universe-design.md`](2026-10-05-sw-yaml-universe-design.md) · ops [`2026-10-07-ops-daily-run-hemostasis-design.md`](2026-10-07-ops-daily-run-hemostasis-design.md) · 待办 [`todo.md`](../../../todo.md) §2.3–2.4 / Spec D

产品对齐：映射宇宙仍是 Git 权威快照（可复现）；D 解决的是 **快照如何按日从 vendor 刷新并发布**，以及 **树外缺口可见**，不是取消快照、也不是把全 A 算进行业树。

### 相对既有文档的覆盖（钉死）

| 来源 | 原句要旨 | 本 slice |
|------|----------|---------|
| taxonomy §5.2 | `unmapped_count=0` 才生产就绪 | **`evaluate_ok` 不生效**；软门 warn；字段仍暴露真值 |
| taxonomy §5.1 / §9.1 | 宇宙变更须新 spec / 不静默扩；切 active 不原地覆盖 | **例行 IPO 量级** diff 允许 cron 直推 + `map_version` bump；**超护栏**视为 fail、保留旧快照（见 §2.1.c′）。无 DB `taxonomy_map_version` active 切换——Git 头即权威 |
| taxonomy §6.1 + SW 2026-10-05 附注 | check-in；当时不在 cron 拉；「每日 vendor 同步留待后续」 | **本 slice 即该后续**：cron 拉 + push；**取代** SW YAML §2/§6「cron 不改映射 / Out: cron fetch」仅就本条 |
| SW YAML §2 BJ | 丢弃或 quarantine | **丢弃**（与现 `normalize_member` 一致） |

---

## 1. 问题

- `stock_sw_l2.yaml` 为 check-in 快照；`fetch_sw_members.py` 仅手工 one-shot；cron **不**改映射 → 新股/调行业滞后。  
- `run_meta.unmapped_count` **硬编码 0**；taxonomy「应归属未归属 / IPO 三日告警」未接。  
- 曾讨论「daily_run 内实时 HTTP 拉行业、不落 Git」→ 破坏 `map_version` / `git_sha` 复现 → **否决**。  
- 树外票无 L2，**没有** Issue/雷达挂载点；为其预热 bars 只省日后冷启动，本 slice **默认不做**。  
- `tests/test_universe_yaml_map.py` 钉死 `map_version == "sw2021-v1"` → 首次 bump 会挡次日 cron pytest（必须同期改测试）。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 架构 | **Approach 1：同 job 前置**——refresh → 护栏通过且有实质 diff 则 commit+push → sync/`daily_run` 读工作区 |
| §2.4 | `fetch_sw_members`（§4 归一不变）；成功后 `patch_stock_names`（失败软、**保留**旧 `name_zh`）；直推 main |
| §2.3 | `unmapped_count` + IPO≥3 告警；软门；**无**树外 bars 预热 |
| 告警范围 | 仅：`taxonomy_fetch`/`clist_fetch` 失败，或 `ipo_unmapped_alert_count>0`；**不**因单纯 `unmapped_count>0` warn |
| fetch / 护栏 / push 失败 | 保留（或恢复）旧 YAML，继续 sync/`daily_run` |
| `map_version` | `ts↔sw_l2` 变更 → bump；仅 `name_zh` → 不 bump 可 commit |

### 2.1 流水线顺序

对 **每次** `daily-trend` 运行都执行步骤 2（含 `only_date`）：分类快照是 vendor「今日」截面，非 PIT。  
**接受：** catch-up 用**今日** YAML/`clist` 重算队列内历史日的成员与引擎行；但 **`unmapped_count` / IPO 字段只写入 `session_asof` 那一行 `run_meta`**，不拿今日 clist 去盖历史日的计数（clist 失败时历史行保持原值）。

```text
1. checkout（既有 permissions.contents: write，不另开凭证）
2. Taxonomy refresh（新；步骤始终 exit 0，见 §3.6）
   a. fetch_sw_members → 候选成员（§4 归一；BJ 丢弃；禁 801xxx）
      - 异常 / 空帧 → taxonomy_fetch=fail；不改文件；跳到 f
   b. fetch 成功后：patch_stock_names
      - 失败 → warn；**保留**候选/旧文件上已有 name_zh；不回滚 membership 结果
   c. 语义 diff（见 §2.3）：按 ts_code 排序后比较多重集
      (ts_code, sw_l2_code, name_zh) + 三文件 map_version 头
   c′. 护栏（相对 HEAD mapped；任一失败 → 等同 fetch fail：不写盘不 push，
      taxonomy_fetch=fail，继续 3）：
      - candidate |mapped| ≥ 0.80 × HEAD |mapped|
      - |adds| + |deletes| + |sw_l2 变更| ≤ 80（实现常量；日志打出三计数）
   d. 护栏通过且有实质 diff：
      - membership/sw_l2 变更 → bump（§2.3）后 **只改三文件头行**（禁止整文件
        YAML dump 打乱 sw_l2_to_l1 / l1_buckets 表体）
      - 仅 name_zh → 不 bump
      - git config user（taxonomy 步自备，勿依赖后置 db 步）
      - git add 仅：config/taxonomy/stock_sw_l2.yaml、sw_l2_to_l1.yaml、
        l1_buckets.yaml，以及 data/unmapped_first_seen.json（若更新）
      - git commit；git pull --rebase --autostash；冲突 → rebase --abort，
        工作区恢复为 HEAD 旧 YAML，taxonomy_fetch=push_fail，继续 3
      - git push（**禁止** --force）；成功则记 taxonomy_commit=HEAD
   e. 无实质 diff → 不 commit；taxonomy_fetch=skipped_no_diff
   f. merge 写 heartbeat.taxonomy；若将 run_deferred / 无 db commit：
      **本步单独** commit+push data/heartbeat.json（及已更新的
      data/unmapped_first_seen.json），保证 main 上可见
3. Sync mapped bars（load_universe_codes()；无树外预热）
4. daily_run → shadow → commit trend.db + heartbeat → Issues
```

步骤 3–4 读步骤 2 后工作区 YAML。`run_meta.map_version` = `load_map_version()`（`sw_l2_to_l1` 头）。

**`run_meta.git_sha`：** taxonomy push **成功**后，`daily_run` 写入 `git rev-parse HEAD`（非启动时的 `GITHUB_SHA`）。push 失败 / unpushed：保留 checkout SHA，heartbeat `taxonomy_commit=unpushed`。

**双 commit：** 步骤 4 的 db commit **只** `git add data/trend.db data/heartbeat.json`（既有），不得 restage taxonomy。步骤 2 已推 YAML 而 3/4 失败 → 可接受。

冷启动：票首次进 mapped U 时 sync 默认 `end−400` 自然日（≈盖 252 交易日）。预算仍走既有 `run_deferred`（200/300 min）；**本 slice 不另做摊销**。

### 2.2 `unmapped_count` 与 IPO 告警

| 集合 | 定义 |
|------|------|
| `clist` | 东财 `FS_ALL_A`；只保留 `^\d{6}\.(SH\|SZ)$` |
| `mapped` | `load_universe_codes()` |
| **`unmapped_count`** | **权威公式** `|clist − mapped|`（示例：空码 quarantine、YAML 无行、YAML 有非法/非 §4 码而未进 mapped） |

北交所不计入。  
**不算 unmapped：** 仅 YAML quarantine、不在 `clist` 的残留 → 只报 `yaml_quarantine_size=|load_quarantine_codes()|`。

**clist 失败：** asof 行 `unmapped_count` / `ipo_unmapped_alert_count` = **SQL NULL**（列可空；禁止省略列与假 0）；`clist_fetch=fail`；不 partial。

**IPO 告警（软）：**

- 上市日源：东财 clist **上市日期字段**（实现钉具体 `fxx`；**不用**申万 hist `start_date`）。  
- 交易日数 = 上海日历上 `[list_date, session_asof]` **含两端** 的交易日个数；≥ 3 → 计入告警。  
- 无 list_date：`data/unmapped_first_seen.json`（**路径钉死，不在 `data/cache/`**——该目录 gitignore 且被 bars cache 覆盖）存 `ts_code → first_asof`；`first_asof` **永远是首次观察时的 `session_asof`**（不是补洞 `D`）；天数 = `[first_asof, session_asof]` 含端。  
- `ipo_unmapped_alert_count` = 仍落在 unmapped 且天数 ≥ 3 的个数。  
- **不**使 `evaluate_ok` → partial。

**写入：**

| 位置 | 字段 |
|------|------|
| `run_meta`（**仅 `session_asof` 行**更新计数） | `unmapped_count` 真值或 NULL |
| `heartbeat.taxonomy`（顶层对象，与 `daily_run` 并列） | `taxonomy_fetch`: `ok` \| `fail` \| `skipped_no_diff` \| `push_fail`；`clist_fetch`；`unmapped_count`；`ipo_unmapped_alert_count`；`yaml_quarantine_size`；`map_version`；`taxonomy_commit`（sha 或 `unpushed`） |
| `run_meta.warn` | 将 taxonomy 短文案 **追加**到既有 `decision.reason`（Spec A limit warn），分隔符 `; `；**不替换** |

`write_heartbeat(job=daily_run)` **不得抹掉**顶层 `taxonomy`。`run_deferred` 时靠步骤 2.f 单独提交 heartbeat。

### 2.3 `map_version` bump 与实质 diff

- **实质 diff：** 排序后多重集 `(ts_code, sw_l2_code, name_zh)` 或任一 taxonomy 头 `map_version` 与 HEAD 不同。纯行序/空白 ≠ 实质（比较前规范化）。  
- **Bump 若：** 新增/删除 `ts_code`，或 `sw_l2_code` 变化（含 null↔码）。  
- **不 bump：** 仅 `name_zh`。  
- **N 来源：** `load_map_version()`（unset `UNIVERSE_YAML`）解析 `sw2021-vN` → 写 `sw2021-v(N+1)`。  
- **解析失败：** refresh **fail**，保留旧文件；**禁止**跳到 `sw2021-v2`（防版本回退）。  
- 写盘：`stock_sw_l2` 可重写成员（按 `ts_code` 排序）；`sw_l2_to_l1` / `l1_buckets` **仅改首行 `map_version:`**（及 note 中字面版本若存在则顺手改，可选）。  
- writer **禁止**把默认 `sw2021-v1` 盖掉已 bump 的头；bump 前传入当前/新版本。  
- name patch 失败时合并：**不得**提交「剥光 name_zh」的文件。

---

## 3. 架构要点

1. Canonical = Git YAML；禁止平行内存宇宙。  
2. 复用既有 `contents: write`；**禁止** `push --force`。  
3. 归一算法不改（SW YAML §2）。  
4. coverage 分母仍 mapped。  
5. Spec C 不动。  
6. **Exit 码（唯一合同）：** taxonomy 步 / CLI **始终 exit 0**；状态只经 `GITHUB_OUTPUT` + 日志（`taxonomy_fetch=...`）。**不用** `continue-on-error` 表达预期失败（否则后续 `if: success()` 会跳过 daily_run）。仅当包装脚本在写出 status **之前**崩溃才允许非 0（此时整 job 停——可接受）。  
7. 单元测试：`test_universe_yaml_map` 改为断言三文件头同为某一 `sw2021-vN`，**删除**对 `sw2021-v1` 字面钉死。

---

## 4. 测试与 Done-when

### 4.1 测试

| 测试 | 断言 |
|------|------|
| normalize | BJ / 801xxx 不进生产 YAML |
| bump | membership → +1 且三头同值；仅 name_zh → 不变；header-only 不搅 L2 表体 |
| 护栏 | 过小/过大 diff → fail 路径，HEAD YAML 不变 |
| fetch fail | 异常 → 文件不变；步骤 exit 0；后续可跑 |
| clist fail | asof `unmapped_count` IS NULL，不得 0 |
| unmapped | `|clist−mapped|`；YAML-only quarantine 不计入 |
| IPO≥3 | list_date / first_seen；evaluate_ok 可为 ok；first_asof=session_asof |
| heartbeat | taxonomy 并列；daily_run 写入后仍在；deferred 路径可单独提交 |
| map 测试 | 不再 `== "sw2021-v1"` |
| wire | `unmapped_count` 非字面 0；warn 追加不覆盖 limit reason |

### 4.2 Done-when

1. workflow：taxonomy 在 sync 前；始终 exit 0；护栏+直推；fail/push_fail 不杀日更。  
2. `run_meta.unmapped_count` 真值/NULL；`heartbeat.taxonomy` 在 main 上可见（含 deferred）。  
3. 无树外 bars 预热；sync 仍 mapped。  
4. `todo.md`：Spec D 行 → **YAML 日拉 + unmapped 计数/IPO 告警已完成**；§2.3 留「树外 bars 预热仍后放」；Next = Spec E。README Still out 同步。  
5. 上表测试绿（含 unpin `sw2021-v1`）。

---

## 5. 文件影响（预期）

| 路径 | 变更 |
|------|------|
| `.github/workflows/daily-trend.yml` | 前置 taxonomy 步（复用 permissions；git config） |
| `scripts/taxonomy/refresh_taxonomy.py`（或扩展 fetch） | fetch/diff/护栏/bump/exit0+GITHUB_OUTPUT |
| `scripts/taxonomy/` / `scripts/common/` | unmapped/IPO；first_seen |
| `scripts/daily_run.py` | asof 真 unmapped；git_sha；warn 追加；heartbeat 不抹 taxonomy |
| `data/unmapped_first_seen.json` | 新建（**非** `data/cache/`） |
| `tests/test_universe_yaml_map.py` 等 | unpin + 新测 |
| `todo.md` / `README.md` | done-when + 预热遗留 |

---

## 6. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-08 | 初版：Approach 1；§2.3 软门无预热；fetch 降级；bump 规则 |
| 2026-10-08 | self-review：§5.2 覆盖；heartbeat 并列；clist≠假0；双 commit |
| 2026-10-08 | indep-CR 真项：exit0+GITHUB_OUTPUT；first_seen 移出 cache；护栏；unpin v1；deferred 提交 heartbeat；git_sha；asof-only 计数；语义 diff/保留 name_zh；warn 追加；rebase abort；文档覆盖表；todo 预热遗留；push_fail 枚举 |
