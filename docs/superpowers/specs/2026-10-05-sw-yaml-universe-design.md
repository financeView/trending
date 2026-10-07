# 申万 YAML 映射宇宙（非交易所全 A 代码表）

**日期：** 2026-10-05  
**状态：** 已接受设计；CR 真问题已打补丁  
**范围：** 用 Git 内申万映射替换 stub 5 / 代码内 `STUB_*`；Actions **分批** sync 映射宇宙 bars；修 `--date` 与 session asof 的混淆；完工后 **真实** 跑 2026-09-30 截面。  
**后放：** L2/L1 同引擎（metrics §10 C5）；无申万二级的交易所全 A 代码；因果 H / WF 两年门禁。

交叉：taxonomy [`2026-09-28-industry-taxonomy-design.md`](2026-09-28-industry-taxonomy-design.md) · market-data [`2026-10-01-market-data-contract-design.md`](2026-10-01-market-data-contract-design.md) §7.2 · ops [`2026-09-30-ops-action-and-eval-design.md`](2026-09-30-ops-action-and-eval-design.md)

---

## 1. 「映射宇宙」vs「全 A」

| | 申万 YAML 映射宇宙（本 slice） | 交易所全 A（后放） |
|--|--|--|
| 成员 | 有有效 `sw_l2_code` 且该二级落入 14 个 L1 桶的 `ts_code` | 代码表里全部 A 股（含未分行业、是否北交所等） |
| 票数 | 通常 ≈ 有行业的上市 A 股（四千量级），**不是** stub 5 | 略多一截 quarantine / 未映射 |
| bars | **必须** sync 这些成员 | 不把未映射票硬拉进分母 |

`sw_l2_code` **只能是** taxonomy §4 的申万 2021 **二级行业码**（6 位，如 `370100`、`480200`）。**禁止**把 BaoStock/指数风格 `801xxx` 当生产 `sw_l2_code`（那是指数码，对不上 §4 映射 → \(U\) 会被全部 quarantine）。fetch 必须归一到 §4；不能归一的票进 quarantine，不得写入 801xxx 充数。

差集主要是 quarantine。工程上「把映射宇宙 sync 齐」按全市场估工时，分母仍是映射集。

---

## 1.1 覆盖率：不要用缩小后的 \(U\) 冒充全量

现码 `members_tradable`：**无当日 bar / 无 `flag_source` → 不进 \(U\)**。于是 `bar_coverage` 的分母会缩成「已经 sync 到的几只」。stub 5 只满 252 根 K 仍可 `evaluate_ok=ok`，映射宇宙其余票从未出现在 `daily_stock`。

本 slice 增加门槛（写入 `run_meta`，挡 `ok`）：

- `mapped_size` = `|load_universe_codes()|`（映射且非 quarantine，**不**因缺 bar 缩小）
- `mapped_sync_coverage` = 当日有 bar **且** `flag_source` 非空的映射成员数 / `mapped_size`
- **所有日**（含历史）：`mapped_sync_coverage ≥ 0.90` 才允许 `ok`（与 `BAR_COVERAGE_MIN` 同量级）
- 现有 \(U\) 上的 `bar_coverage` / `computable_coverage` / asof `limit_coverage` **仍保留**（ST/停牌仍排除出 \(U\)）

未达标 → `partial`，`last_ok` 不前移。

---

## 2. YAML 权威源

Git（taxonomy §6.1），全文件同一 `map_version`：`sw2021-v1`（替换 `p05-v1`）：

| 文件 | 内容 |
|------|------|
| `config/taxonomy/l1_buckets.yaml` | 已有 14 桶；版本改 `sw2021-v1` |
| `config/taxonomy/sw_l2_to_l1.yaml` | 每个 **§4 二级码** → 恰好一个 `l1_id` + `sort_order` |
| `config/taxonomy/stock_sw_l2.yaml` | `ts_code → sw_l2_code`（生成后 **check-in**）；空或不在 §4 表 = quarantine |
| `config/taxonomy/universe_stub.yaml` | **仅测试夹具**（可挪到 `tests/fixtures/`）；生产默认不读 |

**成员列表不另维护：**  
`load_universe_codes()` = `sw_l2` 非空且能在 `sw_l2_to_l1` 命中 `l1_id` 的 `ts_code`。  
`load_quarantine_codes()` = 空码或不在映射表。  
`load_map_version()` 读 `sw_l2_to_l1.yaml`（或 l1_buckets）上的版本，不再读 stub members 文件。

覆盖不变量：每个 §4 `sw_l2_code` 恰好一行映射；抽样个股唯一 `(sw_l2, l1)` 或明确 quarantine。

生成脚本 `scripts/taxonomy/fetch_sw_members.py` 一次性拉成分后写 YAML。**归一算法（钉死）：**

1. 只保留 `^\d{6}\.(SH|SZ)$`；`.BJ` 及其它 → 丢弃或 quarantine，不进 `mapped_size`。  
2. 若 vendor 给出 6 位码且落在 taxonomy §4 集合 → 用该码。**申万官方个股表是三级码**（如 480301）：若 6 位不在 §4 且 `code[:4]+'00'` 在 §4，用该二级父码（禁止 801xxx）。  
3. 否则用申万二级 **中文名与 §4 表精确匹配**。  
4. 仍失败 → `sw_l2_code` 空（quarantine）。  
5. **禁止**把 `801xxx` 指数码写入生产 YAML。夹具：输入 801780 不得出现在 check-in 文件。

成分时点 = fetch 当日快照（非 PIT）；不在 cron 改映射。taxonomy「每日 vendor 同步」本 slice 不实施。

`aggregate.py` 的 `STUB_L2_MEMBERS` / `STUB_L1_TO_L2` **删除**。测试里允许 fixture 用 801xxx，**不得**作为生产默认。

---

## 3. `--date` 与 session asof（必须修）

**现码缺陷：** `--date D` 把 `session_asof` 设成 D → `D == asof` 恒真 → 卡 limit；Actions 历史日又 skip EM → 必 `partial`。

**目标语义：**

| 概念 | 定义 |
|------|------|
| `session_asof` | `latest_trade_day()`。测试/显式覆盖用 `--asof`。 |
| `--date D` | 重跑**起点**（失败首日）。D ≤ session_asof；交易日（除非 `--force-trade-day`）。无 `--only-date` 时队列 = `[D … session_asof]`。 |
| `--only-date` | **必须**与 `--date D` 联用：队列 = `[D]`。单独传 `--only-date` → 非 0 退出。 |

`evaluate_ok`：所有日卡 `mapped_sync_coverage`（本 slice，`ok_predicate_version` 现见 Spec A 的 **v1.2**）。**Limit：** 已由 Spec A / market-data §7.2 **修订**——`D == asof` 且 limit 不足 → `ok`+warn（不 partial，`last_ok` 前移）；不再「硬卡 asof ok」。权威：[`2026-10-07-ops-daily-run-hemostasis-design.md`](2026-10-07-ops-daily-run-hemostasis-design.md) §3。

「今日 / asof / sync end」一律 `latest_trade_day()`（上海交易日历），**不是**民用 `date.today()`（周末/节中会 sync 空日）。

2026-09-30 冻 asof 补洞缺 `limit_*`：在 v1.2 下可 `ok`+warn（须过 mapped_sync / bar / computable）。L 无 open+limits 则 skip。

### 3.1 Actions 三种模式（禁止一个 `date` 身兼 asof / 重跑日 / sync end）

| 模式 | 输入 | sync `--end` | limits | `daily_run` |
|------|------|----------------|--------|-------------|
| cron 日更 | 不传 date | `latest_trade_day()` | `--with-limits` | **无** `--date` |
| 单日补洞 | `date=D` + `only_date=true` | `D` | 仅当 `D==latest_trade_day()` | `--date D --only-date` |
| 从 D 追赶到 asof | `date=D`、only_date 关 | `latest_trade_day()` | asof 日 limits | `--date D` |

Sync 代码列表 = `load_universe_codes()`（映射宇宙），**禁止**生产仍 `--from-universe universe_stub.yaml`。

`sync_complete` 写入 **`GITHUB_OUTPUT`**（`sync_complete=true|false`），step `id: sync`。`daily_run` / L / commit trend.db 均 `if: steps.sync.outputs.sync_complete == 'true'`。两边都 **exit 0**（好让 cache 保存）。只 print 不算完成信号。

若本 job 已 `sync_complete` 但 sync 已耗 **>200 min**，本轮 **跳过** daily_run（`run_deferred`），下次 cron 再跑截面，避免 360 墙钟在 replay 中被杀。

`sync_incomplete` / `run_deferred` → 禁止 daily_run / L / commit `trend.db`。

---

## 4. Sync 分批（Actions 6h）

托管 job 上限 6h。冷启动会超；热 cache 单日多数不超，**限速 / cache miss / 复权重刷仍可能超**。每个 job 必须有预算 + 断点。

| 项 | 值 |
|----|-----|
| job `timeout-minutes` | 360 |
| sync step | ≤ 330 |
| `--time-budget-min` | ≤ 300（必须低于 step，好 `exit 0` 让 cache 写入） |
| `--max-codes` | 可配；与时间预算取先到 |

续跑：`ts_code` 稳定排序。OHLC 与 flags **分开**跳过：仅当 **end 当日已有 OHLC 行** 才 skip OHLC；仅当当日 `flag_source` 已写才 skip flags。`sync_meta.last_bar_date ≥ end` **不等于** 已有 9.30 行、也不等于 flags 齐（现码把 `last_bar_date` 写成请求的 `end`）。

历史 `--end D` 且 `D ≠ 上海今日`：skip `--with-limits`。

Resume **不得**因 `last_bar_date ≥ end` 跳过「已上市足够久但 `close_qfq` 计数 < 252 交易日」的票。**新股不够 252 是预期**：sync 拉满可得历史即可；**不要**把「映射全集每只 ≥252」当成 `ok` 条件。

9.30 `ok` = market-data §7.2：`mapped_sync_coverage≥0.90` + \(U\) 上 `bar_coverage≥0.90` + `computable_coverage≥0.50`（\(U\) 内一半满 252 即可）。252 是 **sync 续跑启发式**，不是第二套 computable 门槛。

sync 默认窗口保持 `end-400` 自然日（约覆盖 252 交易日）；预算中的「只补最后一天」不得把窗口收成 1 日除非该票历史已满 252。

---

## 5. 2026-09-30 真跑

1. YAML check-in（§4 码），测试绿。  
2. 映射宇宙 OHLC+flags 覆盖到 ≥ 2026-09-30（可分批；长历史票尽量拉满 ~252 交易日窗口）。  
3. `daily_run --date 2026-09-30 --only-date`。  
4. `run_meta(2026-09-30)`：`mapped_sync_coverage≥0.90` 且 \(U\) 上 bar/computable 达标 → **`ok`**（不因缺 limit；不要求每只满 252）。  
5. `daily_stock` 规模是映射宇宙量级，不是 5。  
6. L 无 limits → skip 可接受。

禁止假装 9.30 是上海今日去打 EM。

---

## 6. 非目标

- 合成 L2/L1 K 线再走同一 T/FSM  
- 未映射代码进 \(U\)  
- `board_calc_v1`、WF、cron 里重新 fetch 成分 YAML  

## 7. 修订

| 日期 | 内容 |
|------|------|
| 2026-10-05 | 初稿 |
| 2026-10-05 | CR2：GITHUB_OUTPUT；§4 归一算法；SH/SZ；252=sync 启发式；asof=latest_trade_day；sync>200min 推迟 daily_run |
