# Spec：Protocol B 硬冻戳 + 强卡控（P0）

**日期：** 2026-10-10  
**状态：** 已落地；plan [`2026-10-10-protocol-b-hard-freeze-stamp.md`](../plans/2026-10-10-protocol-b-hard-freeze-stamp.md)  
**范围：** `todo.md` P0 **Protocol B**——改 `hard_freeze_min_suspend_days` / bump `param_version` 与 `bars.hard_freeze_flag` 脱节时的运维护栏。  
**后放（禁止混入本 slice）：** `limit_rule` 回退护栏；incomplete + asof 限价产品抉择；metrics 侧自动补跑硬冻 pass；按日审计流水；改硬冻算法 / 默认 N。

交叉：Spec E [`2026-10-08-spec-e-fill-hard-freeze-design.md`](2026-10-08-spec-e-fill-hard-freeze-design.md) §2.1 / §4.3.1 · Spec F [`2026-10-08-workflow-split-jobs-design.md`](2026-10-08-workflow-split-jobs-design.md) · 待办 [`todo.md`](../../../todo.md) P0 Protocol B

产品对齐：配置声称的硬冻规则必须与库内旗一致，才能宣称新 `param_version` 下的 EXIT / 评估有效。

**覆盖声明（钉死）：** 本 Spec **取代** Spec E §2.1 中「hard_freeze pass 异常 → warn、不抛死整个 sync」的句子；**仅**针对 hard_freeze。board_calc 仍可按 Spec E 保持 warn 级。Spec F 的 incomplete / `sync_complete` 门闩不变，但 sync job **bars cache 保存策略**按本 Spec §4.5（选择 B）调整。

---

## 1. 问题

Spec E 将硬冻定为 **persist + 读列**：`hard_freeze_flag` 由 sync 全量 pass 按 yaml 的 N 写入；metrics / fill **不再**按 N 重算。

因此：

1. 只改 yaml（N 或 `param_version`）而**不**用新 N 重写旗 → 库内仍是旧特征值。  
2. `daily_run` / 纸面 / Issue 却带上**新** `param_version` → **新版本号 + 旧旗**。  
3. 今日 sync 虽已跑 `apply_hard_freeze_flags`，但 pass **失败仅 warn** 时仍可能 `sync_complete=true` 并进入 metrics，旗/戳不可信。  
4. 文档约定（方案 B）无代码护栏 → 人忘了就会静默错。  
5. 若将 hard_freeze 改为硬失败而仍用 `actions/cache@v4` 默认 `post-if: success()`，则 **当夜已写入的 OHLC 不会进 `bars-${{run_id}}`**，下一 run 只能从更旧的 `bars-` restore（CR 核实为真）。

---

## 2. 目标口径（已钉）

| 决策 | 选择 |
|------|------|
| 护栏强度 | **强卡控档 1**：sync 上 pass 失败则红；metrics/`daily_run` 入口戳与 yaml 不一致则红 |
| 一致性信号 | **单行 stamp**（`bars.db`，UPSERT 覆盖，恒 1 行） |
| 自动修复 | **不做** metrics 侧自动触发 pass；不一致 → 失败并提示先跑完整 sync |
| Actions cache | **选择 B**：hard_freeze 硬失败时 sync job 仍须保存本 run 的 `bars-${{ github.run_id }}`（见 §4.5） |
| 文档 | 短 runbook：改 N / bump → sync（写旗+戳）→ 再 metrics/评估 |
| 检查脚本 | 可选；与入口共用同一校验函数，供本地/PR；日更以硬门闩为准 |

### 2.1 非目标

- 不改 `apply_hard_freeze_flags` 的 streak / N 语义。  
- 不新建按日增长的审计表。  
- 不在本 slice 做 P0 另外两项（`limit_rule` 回退、incomplete×asof 限价）。  
- 不把「无戳」在绿场首次部署时永久卡死——见 §4.3 迁移。  
- **不**给 `paper_book` / 离线评估入口加戳门闩（本 slice 仅 `daily_run` + 可选 CLI；纸面若跳过 `daily_run` 仍可能读旧旗——接受，写入 runbook「评估前须先绿 `daily_run`」）。  
- **不**用戳代替「改 N 必须 bump `param_version`」的 runbook；戳只证明「旗已按戳上的 N/版本重写过」。

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

- 写入时机：硬冻全量 pass **成功返回之后**（与 Spec E pass 同一 sync 会话），且满足 §4.2 写戳前置条件。  
- 语义：戳表示「库内旗已按该 N / 该 `param_version` 对传入宇宙重写过」。  
- 增长速度：**O(1)**，每次覆盖。

实现：`ensure` 建表（idempotent）；提供 `write_hard_freeze_pass_meta` / `read_hard_freeze_pass_meta`。

### 3.2 sync 强卡控

现路径：`scripts/sync_bars_sample.py` → `run_spec_e_passes` → `apply_hard_freeze_flags`。

| 项 | 旧 | 新 |
|----|----|-----|
| hard_freeze 异常 | stderr warn，sync 继续 | **传播失败 → sync 非零退出**（见 §4.2：禁止先写 `sync_complete=true`） |
| board_calc pass | warn 级 | **保持 warn**；与 hard_freeze **必须分 try**——不得因 board_calc 的 except 吞掉 hard_freeze 硬失败 |
| pass 成功后 | 只打日志 | **UPSERT 戳**（N、`param_version`、`rewritten_at`、`rows_touched`）；写戳失败 → 同硬失败 |
| 空 `codes` | `apply_*([])` 返回 0、不抛 | **不写戳**。判定（钉死）：未传 `--from-universe` 且 `codes_from_universe()`（默认 mapped U）为空 → sync **非零**；`--from-universe` 夹具路径仅保证不 UPSERT（夹具可故意空，由测试断言） |

N / `param_version` 来源：与 pass / 校验 **同一解析函数**——默认 `config/metrics/a_share_daily.yaml`，且须尊重 `METRICS_PARAMS_YAML`（若设）。禁止 sync 写戳读默认路径、而 `daily_run` 校验读另一路径。`param_version` 与 N 同文件同次 load。

**「跑硬冻全量 pass」定义（runbook 用语）：**  
对当前 `bars.db` 执行与日更 sync 相同的 `apply_hard_freeze_flags(conn, mapped_codes, n=yaml_N)`，覆盖写全宇宙相关行的 `hard_freeze_flag`，并写戳。正常完整 sync（OHLC 循环结束后的 Spec E 段）即包含此操作。

**incomplete OHLC（`sync_complete=false`）：** 与 Spec E 一致——两 pass **仍执行**。hard_freeze 成功 → **仍写戳**；然后 `write_sync_complete(false)`（exit 0）。metrics 因 Spec F 跳过。不得因 incomplete 而跳过写戳，也不得因「只写了戳」就把 `sync_complete` 打成 true。

### 3.3 metrics / `daily_run` 强卡控

在 **开始算截面之前**（读 bars、写 `daily_*` 之前）调用共享校验：

```text
yaml_N, yaml_param_version  ← 与 sync 同一 yaml 解析（含 METRICS_PARAMS_YAML）
stamp                       ← hard_freeze_pass_meta id=1（同一 bars.db）

if stamp missing → fail（迁移例外见 §4.3）
if stamp.N != yaml_N → fail
if stamp.param_version != yaml_param_version → fail
else ok
```

失败：非零退出 + 明确 stderr（中英任一，须含：先跑完整 sync / 硬冻 pass 以刷新旗与戳）。

挂点（钉死）：

- **`scripts/daily_run.py` 的 `main()`**：在 **交易日 / empty-queue skip 之后**、**首次 `process_day` 之前**做一次校验（覆盖 Actions **metrics** job 与本地会真正算截面的路径）。  
- 现有 `[skip] non-trading-day` / empty-queue `return 0` 路径 **不要求**戳（周末本地 skip 不得因无戳失败）。  
- **不**挂在 `process_day` 内（避免每个 asof 日重复查戳、也避免「部分日已写再失败」的半截日更）。  
- 不要求改 `live_shadow_step` 再挂一层（shadow 依赖已成功的 `daily_run` 日）；若单独跑 shadow 而跳过 `daily_run`，本 slice 不扩展。

本地多库：`--bars-db`（已有）与校验/写戳必须针对**同一路径**；默认与现 sync/`daily_run` 一致。

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
5. 纸面/离线评估：先确保该环境已绿过带戳校验的 `daily_run`（本 slice 不拦 `paper_book`）。  
6. Actions：hard_freeze 失败后若需刷新同 key 下的 `bars.db`（含新戳），**开新 workflow run**（cron / `workflow_dispatch`）；**不要**依赖「Re-run failed jobs」覆盖已存在的 `bars-${{ github.run_id }}`（cache key 不可变，见 §4.5）。

---

## 4. 契约细节

### 4.1 比对键

**必须同时**比对 N 与 `param_version`。  
只 bump `param_version`、N 不变：仍须重新跑 pass 并写戳（方案 B：宣称新版本前旗须在同环境下按当前规则重写过——即使 N 数字未变，也刷新 `rewritten_at` / 与版本绑定）。

### 4.2 sync 失败、写戳与 `sync_complete`

顺序（钉死）：

```text
OHLC/flags 循环
→ hard_freeze（硬失败路径，无吞异常）
→ 写戳（失败则硬失败）
→ board_calc（warn，不挡 sync 退出码）
→ write_sync_complete(complete)   # 仅进程即将成功退出时
→ exit 0
```

硬约束：

1. hard_freeze **或** 写戳失败 → **不得**调用 `write_sync_complete(true)`；**不得**先写 `sync_complete=true` 再非零退出（禁止「输出已绿、进程已红」导致 Spec F metrics 误跑）。推荐：失败路径直接 `raise` / `return 1`，成功路径末尾再写 output。  
2. 写戳前置：`apply_hard_freeze_flags` 无异常 **且** `len(codes) > 0`。空 codes → 不 UPSERT；默认 mapped 空宇宙 → 非零（§3.2）。  
3. 进程非零退出时：本 run 的 metrics job 因 Spec F `needs`/门闩不跑（或整 run 已失败）。  
4. OHLC 已写入但 pass/戳失败：接受；靠 §4.5 仍保存 bars cache；修复后用 **新 workflow run**（或本地）再 sync + 写戳——同 `run_id` 的 Re-run 不能覆盖已上传 key（§4.5）。

### 4.3 迁移 / 首次部署

绿场或旧 cache **无戳**：

| 场景 | 行为 |
|------|------|
| sync | 跑 pass → 写戳（自愈） |
| `daily_run` 且无戳 | **失败**（与「不一致」同级），迫使先 sync |

测试可注入戳或先跑 pass helper。不在 yaml 增加「跳过校验」永久开关；若 CI 夹具需要，仅测试 monkeypatch / 临时 env **测试专用**（生产 Actions 不设跳过）。

### 4.4 Actions（job 级）

- **sync job：** 依赖 pass/戳硬失败即可；**另须**落实 §4.5 cache B。  
- **metrics job：** 依赖 `daily_run` 入口校验即可。  
- 不新增第三 job。

### 4.5 Actions bars cache（选择 B，钉死）

**问题：** 单体 `actions/cache@v4` 的 post 步 `if: success()`；sync 因 hard_freeze 非零退出时 **不** upload，当夜 OHLC 丢失于 runner。

**Key（钉死，与 Spec F 一致）：** 两 job 均为 `bars-${{ github.run_id }}`。  
**禁止**把 `github.run_attempt` 拼进 key——否则「sync 已在 attempt 1 成功、只 Re-run metrics」会精确 miss。  
**禁止**依赖已废弃且无效的 `save-always:`（actions/cache#1452）。

**钉死写法（sync job）：** 拆成 restore + save（伪代码精神；路径/`id` 可按实现微调）：

```yaml
- name: Restore bars cache
  id: bars-restore
  uses: actions/cache/restore@v4
  with:
    path: data/cache
    key: bars-${{ github.run_id }}
    restore-keys: |
      bars-

# … unit tests / taxonomy / sync …

- name: Save bars cache
  if: ${{ always() && steps.bars-restore.outputs.cache-hit != 'true' }}
  uses: actions/cache/save@v4
  with:
    path: data/cache
    key: bars-${{ github.run_id }}
```

要点：

1. `always()`（或 `success() || failure()`）使 hard_freeze 红时仍尝试 save。  
2. `cache-hit != 'true'` 避免对**已存在**的精确 key 再 save（GitHub cache key 不可变；强行 save 会失败/告警）。  
3. **同 `run_id` 的 Re-run failed jobs：** 若 attempt 1 已 save 过该 key，attempt 2 restore 得 `cache-hit=true` → **不会**再 upload 修通后的戳。接受；恢复方式 = **新 workflow run**（新 `run_id`）。attempt 1 已 save 的 OHLC 仍可经下一 run 的 `restore-keys: bars-` 接到。  
4. metrics job：仍单体或 restore-only + 精确 `cache-hit` 门闩；key 仍为 `bars-${{ github.run_id }}`（无 `run_attempt`）。

**不变：** `sync_complete=false` 且 exit 0 时既有 Spec F 行为保留。  
**文档：** Spec F §4.3.1 交叉本条。

### 4.6 yaml / tip 漂移（接受边界）

- sync 写戳与 `daily_run` 校验必须同解析路径（§3.2）。生产 Actions 通常不设 `METRICS_PARAMS_YAML`；本地/CI 若设，两边必须一致。  
- metrics job checkout **默认分支 tip**（Spec F）：若 tip 上 yaml 的 N/`param_version` 已变、而本 run sync 用的是触发 SHA 的旧 yaml，可能戳≠ tip → metrics 红。接受；下一轮以 tip 跑 sync 自愈。不在本 slice 做「metrics 冻结触发 SHA 的 yaml」。

---

## 5. 测试（最少集）

1. **写戳：** pass 成功后 `hard_freeze_pass_meta` 一行，N/`param_version` 正确。  
2. **匹配：** 戳=yaml → `daily_run` 校验通过（可 stub 后续）。  
3. **N 不一致：** 戳 N≠yaml → `daily_run` 非零。  
4. **param_version 不一致：** 同上。  
5. **无戳：** `daily_run` 非零。  
6. **pass 失败传播：** mock `apply_hard_freeze_flags` 抛错 → sync 非零，且不写 `sync_complete=true`、不写成功戳。  
7. **写戳失败：** mock `write_hard_freeze_pass_meta` 抛错 → sync 非零，不写 `sync_complete=true`。  
8. **空 codes：** 不写戳；默认 mapped（无 `--from-universe`）空 → 非零；`--from-universe` 空仅断言不 UPSERT。  
9. **board_calc warn 隔离：** board_calc 仍 warn 时，hard_freeze 硬失败不被吞（拆 try）。  
10. **yaml 同源：** 设 `METRICS_PARAMS_YAML` 临时文件时，写戳与校验读到同一 N/`param_version`（相对默认路径文件可区分）。  
11. **挂点：** 校验在 skip 门闩之后、`process_day` 之前；非交易日 skip 不要求戳；进入算截面时校验恰好 1 次（spy）。  
12. **incomplete + 戳：** OHLC 未跑完但 hard_freeze 成功 → 有戳、`sync_complete=false`、进程 exit 0。  
13. **workflow 静态（扩 `test_p2_workflow_order` 或等价）：** sync 含 `actions/cache/restore` + `actions/cache/save`；save 的 `if` 在失败时仍可执行（含 `always()` 或 `failure()`）；**无** `save-always:`；两 job key 均为 `bars-${{ github.run_id }}`（**无** `run_attempt`）。

---

## 6. Done-when

1. `hard_freeze_pass_meta` 单行表 + 读写 helper；pass 成功且非空 codes 写戳。  
2. sync：hard_freeze 或写戳失败 → 非零；成功 → 戳与 yaml 一致；默认 mapped 空宇宙不写假戳且非零。  
3. `daily_run`：将算截面时校验失败 → 非零；非交易日 skip 不因无戳失败。  
4. Actions：§4.5 cache B 落地（restore/save；失败仍可 save；禁 `save-always` / 禁 `run_attempt` key）。  
5. §5 测试绿（含 12–13）。  
6. 短 runbook 落盘（含「失败后开新 run」）；`todo.md` P0 Protocol B 行改为本 Spec / 完成后标完成。  
7. Spec E §2.1（含 N 加载同源）/ §4.3.1 与本 Spec 一致。  
8. Spec F §4.3.1 与本 §4.5 一致。

---

## 7. 风险与操作说明

| 风险 | 缓解 |
|------|------|
| 改 yaml 后只跑 metrics | 入口失败，迫使 sync |
| pass 慢 | 既有成本；本 slice 不加重算范围 |
| 旧 Actions cache 无戳 | 先 sync 自愈；仅 metrics 会红一次 |
| hard_freeze 硬失败丢当夜 OHLC | §4.5 cache B（首次失败可 save） |
| 同 run_id Re-run 无法覆盖已 save 的 key | runbook：开新 workflow run；勿依赖 Re-run 刷新戳 |
| tip yaml 超前于本 run sync | §4.6；下轮 sync 自愈 |
| 与 Spec F incomplete | incomplete 仍 pass+写戳；`sync_complete=false`；metrics 跳过 |
| pass 持续抛错卡住 catch-up | 真故障须修代码/数据；非「改 N」常态；修后 **新 run** sync |

**`check_hard_freeze_stamp` 失败含义（操作者）：**  
yaml 的 N/`param_version` 与库内戳不一致或无戳 → 不要宣称新版本结果；对同一 `bars.db` 跑完整 sync（硬冻全量 pass + 写戳）后再检、再跑 `daily_run`。

---

## 8. 修订

| 日期 | 说明 |
|------|------|
| 2026-10-10 | 初版：单行戳；sync pass 硬失败；daily_run 戳校验；档 1 不强行 metrics 自动 pass |
| 2026-10-10 | CR 核查并修：覆盖 Spec E §2.1；cache B；写戳/空 codes/`sync_complete` 顺序；yaml 同源；`main` 挂点；paper_book 非目标；incomplete 仍写戳 |
| 2026-10-10 | 二次 CR 核查并修：§4.5 钉 restore/save、禁 save-always/run_attempt；Re-run→新 run；§5.12–13；skip 后挂点；空宇宙操作化；E N 加载同源 |

---

## 9. CR 核查摘要（已并入正文）

| 项 | 判定 | Spec 落点 |
|----|------|-----------|
| sync 红 → cache 不 upload | **真**（`post-if: success()`） | §4.5 B |
| 与 Spec E §2.1 warn-continue 冲突 | **真** | 文首覆盖声明 + E §2.1 修订 |
| 空 codes 仍可能写戳 | **真（边角）** | §3.2 / §4.2 |
| 写戳失败若仍 warn-try | **真（实现坑）** | §3.2 / §4.2 |
| 先 `sync_complete=true` 再非零 | 现网未如此；**须禁止** | §4.2 |
| loader / `METRICS_PARAMS_YAML` 不同源 | **真（本地）** | §3.2 / §4.6 / E N 加载 / 测 §5.10 |
| tip checkout yaml 漂移 | **真但少见** | §4.6 |
| incomplete 仍 pass+戳 | **真（须测）** | §3.2 / 测 §5.12 |
| 挂点相对日历 skip | **真**（`daily_run.py` skip 在 `process_day` 前） | §3.3 / 测 §5.11 |
| paper_book 无门闩 | **真 → 非目标** | §2.1 |
| §4.5 未钉官方写法 / Re-run 不可覆盖 key | **真** | §4.5 / runbook §3.5.6 |
| 用 `run_attempt` 进 key 修 Re-run | **否——别用**（破坏只重跑 metrics） | §4.5 禁止 |
| 「每天 freeze 挂会永久卡 catch-up」 | **过头**（仅持续抛错） | §7 弱化 |
