# 行情 / 日历 / 涨跌停数据契约

> 状态：草案  
> 日期：2026-10-01  
> 参考：`economy-strategy`（日历门禁、限速重试、`bars.db` Actions cache、源互斥）；本仓库运维 / 回测 / 指标 spec  
> 依赖：  
> - [`2026-09-30-ops-action-and-eval-design.md`](./2026-09-30-ops-action-and-eval-design.md)  
> - [`2026-09-30-backtest-eval-design.md`](./2026-09-30-backtest-eval-design.md)  
> - [`2026-09-29-trend-metrics-engine-design.md`](./2026-09-29-trend-metrics-engine-design.md)  
> - [`2026-09-28-industry-taxonomy-design.md`](./2026-09-28-industry-taxonomy-design.md)  

本文钉死：**免费栈默认数据源、字段口径、缺口续跑、涨跌停缺失策略、流通市值落库**。算法语义仍以 metrics / backtest 为准；本文件管「数据从哪来、缺了怎么办」。

---

## 0. 已拍板决策（全貌速查）

| 决策 | MVP 结论 | 将来可选 |
|------|----------|----------|
| 缺 vendor `limit_*` | **严格 `data_gap`**（不成交、不猜限价） | 加厚历史样本时可显式开 **`board_calc_v1`**（须新 `cost_version` / summary 标注，不得静默冒充 vendor） |
| `float_mv` | **落库**；当日 sync 可写 spot；**历史禁 spot 回刷**；空则 \(w=1\) 再归一 | 市值 vs 等权 A/B（metrics V4） |
| 标的主键 | **Tushare 式** `ts_code`：`000001.SZ` / `600000.SH` | 北交所 `.BJ` 若扩宇宙再定 |
| 调度 | 交易日 **北京 19:00**（UTC `0 11 * * 1-5`） | 可再延，不可早于 18:00 当「齐套」假设 |
| 历史回填 | **分批回填** + **`next_trade_date(last_ok)` 续跑**；`ok` 谓词见 §7.2 | — |
| 默认栈 | 免费：AkShare 日历 / 新浪+东财 bars / BaoStock ST·停牌 / 东财当日涨跌停 | Tushare Pro `stk_limit` 等仅作升级路径 |

---

## 1. 目标与非目标

**目标**

1. 支撑每日因果重算：日历、`prev/next_trade_date`、qfq 信号价、raw 成交价、ST/停牌、当日涨跌停。  
2. Actions 可跑：无交互登录；限速重试；`data/cache/bars.db` 可 cache。  
3. 与 backtest「vendor 涨跌停 / 禁止静默 10%」一致；缺字段行为可预期。

**非目标（本期）**

- 分钟级行情；盘中实时温度。  
- MVP 默认付费 Tushare。  
- 用「日历空洞」单独推断停牌。  
- 历史多年完整 vendor 涨跌停表（接受 data_gap 或日后 board_calc）。

---

## 2. 标识与交易日历

### 2.1 `ts_code`

- 库内、截面、事件、账本：**统一** `XXXXXX.SH` | `XXXXXX.SZ`（Tushare 式）。  
- 指数例：`000300.SH`（与 `costs.yaml` `hs300_series` 一致）。  
- 对接 AkShare / BaoStock / 东财时，仅在 `market_client` 做 `to_ts_code` / `to_vendor_symbol`；禁止业务层混用六位裸码或 `sz000001`。

### 2.2 交易日历

| 项 | MVP |
|----|-----|
| 主源 | `ak.tool_trade_date_hist_sina()`（与 economy-strategy 同源） |
| 缓存 | 进程缓存 + `data/cache/trade_dates.json` 降级 |
| API | `is_trade_day` / `latest_trade_day` / `prev_trade_date` / `next_trade_date`（**交易日**滞后，非自然日 +1） |

非交易日：流水线 `exit 0`，不写正式截面、不改 Issue（ops 已定）。

---

## 3. 推荐免费栈（字段 → 源）

| 字段 / 能力 | 主源 | 备源 / 备注 |
|-------------|------|-------------|
| 日历 | 新浪 via AkShare | 文件缓存 |
| OHLC **qfq**（信号） | 新浪 `stock_zh_a_daily(..., adjust="qfq")` | 东财 `stock_zh_a_hist(..., adjust="qfq")`；**同源互斥**，禁 em/sina 混拼同一票序列 |
| OHLC **raw**（成交/盯市） | 同上 `adjust=""` | BaoStock `adjustflag="3"` 可作核对 |
| `is_suspended` | BaoStock 日线 `tradestatus`（0=停） | 勿把「无 bar」直接当停牌 |
| `is_st` | BaoStock 日线 `isST` | 当日可用名称/`stock_zh_a_st_em` 兜底快照 |
| `limit_up` / `limit_down`（**当日**） | 东财 quote `f51` / `f52` | 写入当日 bar；`limit_source=em_f51f52` |
| `limit_*`（**历史**） | MVP：**允许空** → 成交层 `data_gap` | 日后可选 `board_calc_v1`（§5） |
| `float_mv` | 东财 spot「流通市值」（元） | 见 §6；可空 |

工程习惯继承 economy-strategy：`RateLimiter` + `call_with_retry`；`BARS_SOURCE` 钉死；全量冷启动靠分批，不靠单次拉完全宇宙多年。

**BaoStock 官方入库（北京）**：日 K ≈17:30；复权因子 ≈18:00 → 正式日更 **19:00**。

---

## 4. 缓存 schema（草图）

`data/cache/bars.db`（gitignore + Actions cache）。正式截面/事件仍在 `data/trend.db`。

```text
trade_calendar (
  calendar_date TEXT PK,      -- YYYY-MM-DD
  is_trading_day INTEGER      -- 0/1
)

bars (
  ts_code TEXT, trade_date TEXT,
  open_qfq, high_qfq, low_qfq, close_qfq,
  open_raw, high_raw, low_raw, close_raw,
  preclose_raw,
  volume, amount, turnover,
  float_mv,                 -- 可空；元；§6
  limit_up, limit_down,     -- 可空；§5
  is_suspended INTEGER,     -- 0/1
  is_st INTEGER,            -- 0/1
  bar_source, flag_source, limit_source,
  fetched_at,
  PRIMARY KEY (ts_code, trade_date)
)

sync_meta (
  ts_code TEXT PK,
  last_bar_date TEXT,
  qfq_rebuild_token TEXT,   -- 除权后整票重刷 qfq
  preferred_source TEXT
)

-- trend.db.run_meta 另记：trade_date 级 status / 覆盖率（断点续跑用）
```

**复权纪律（MVP 三句，收窄）**

1. `qfq_rebuild_token`：每票每 sync 写入可比较指纹（建议 `hash(源名 + 最近可知除权/复权因子摘要)` 或源返回的 adjust 标识）；与库内旧 token 不同即触发重刷。  
2. 触发后：**只重写该票 `*_qfq` 列**，**不**改 `*_raw` / `limit_*` / flags；禁止「只增量 10 日永不回写 qfq」。  
3. **H** 始终读当前 `bars` 的 qfq 做信号重算；**L** 不改写已有 `paper_fill`/`signal_event`（qfq 重刷后 H↔L 漂移视为预期，不是 bug）。历史 `daily_*` 不因 qfq 重刷强制全表重发 Issue（全量重算属 P2+）。

---

## 5. 涨跌停缺失策略（`limit_*`）

### 5.0 价格空间（写死）

`limit_up` / `limit_down` **一律未复权（raw）价格空间**；成交判定 **只**与 `open_raw`（及同口径 raw 字段）比较，**禁止**与 qfq open/close 比较。

### 5.1 MVP：`limit_rule = vendor_fields` + 严格 `data_gap`

与 backtest `costs.yaml` 一致：

- 仅当存在 vendor（或当日东财 f51/f52）写入的 `limit_up`/`limit_down` 时，才做开盘涨跌停可成交判定。  
- **字段缺失** → 该票该意图日 **`data_gap`**，不得用收盘价顶开盘价，**不得**静默套用主板 10%（含 300/688）。  
- 历史 H 轨 / 追赶日（`D < session asof`）：多年无 vendor 限价属预期；**不**因缺 `limit_*` 拒绝该日 `ok`（见 §7.2）。  
- 仅 **session asof** 日：`limit_*` 覆盖率过低则 **不得**标 `ok`（§7.2），避免半截影子日。

### 5.2 将来：`board_calc_v1`（未启用）

当需要加厚历史纸面样本时，可另开版本（**不是**改 MVP 默认偷换）：

- 规则示意：按板块/ST 对 `preclose_raw` 乘板幅并取整，得到推算涨跌停价。  
- **必须同时** `limit_rule=board_calc_v1` **且** bump `cost_version`；summary 两者都写；禁止混称「交易所限价」。  
- 启用前补夹具与修订记录；全样本拟合式「先算限价再调参」仍禁止。

业界对照（备忘）：付费表（如 Tushare `stk_limit`）≈ vendor；开源回测常用 board_calc；更糙的用一字板形态代理。本项目路径是 **先 data_gap，后可选显式 board_calc**。

---

## 6. 流通市值 `float_mv`

### 6.1 含义

**流通市值**（circulating / free-float market cap），不是总市值。

\[
\mathrm{float\_mv} \approx \text{流通股本（股）} \times \text{价格}
\]

MVP 优先落东财（或等价）**「流通市值」**（单位：**元**），meta 记 `float_mv_source`。

### 6.2 As-of 与历史（因果）

| 场景 | 规则 |
|------|------|
| **当日同步 trade_date=T** | 允许用同步时刻 spot 流通市值写入 **`bars.float_mv` 且必须写入 `daily_stock.float_mv`**（可空若 spot 失败） |
| **历史回填 / 补旧日** | **禁止**用「今天的 spot」回刷过去的 `trade_date`；旧日无历史市值源则 **`float_mv=null` → 等权** |
| 重放 | 合成权重只读该日已落库的 `daily_stock.float_mv`（或 bars 同日值），不现场再拉 spot |

### 6.3 缺省加权公式（钉死）

对参与合成的成员集合 \(M\)（tradable 且当日有收益）：

```text
w_i_raw = float_mv_i  if float_mv_i is not null and float_mv_i > 0 else 1.0
w_i     = w_i_raw / sum(w_j_raw for j in M)
```

即：缺市值成分用 **1.0 占位再全体归一**，不是「一缺全员改等权」，也不是静默权重 0。夹具：一票 null、其余有市值 → null 票权重 = \(1/\sum w_{\mathrm{raw}}\)。

---

## 7. 日更、缺口交易日与分批回填

### 7.1 调度

- Cron：**北京 19:00** = UTC `0 11 * * 1-5`（Actions `cron`；见 ops YAML）。  
- 门禁：非交易日 skip；交易日以日历为准。  
- `BARS_SOURCE` 默认 `sina`；单票失败重试后标记该票缺口，**禁止**中途改源拼同一票历史序列。

### 7.2 `run_meta.status=ok` 谓词（续跑硬闸）

**Session `asof`**：本轮 Actions / `workflow_dispatch` 要收尾的**最新已收盘交易日**（19:00 日更通常即「今天」对应交易日；手动 `--date` 时即为该参数日）。  
缺口队列里的中间日记为 `D`；**仅当 `D == asof` 时**施加「asof 专用」门槛；**`D < asof` 的历史/追赶日不要求当日 `limit_*` 覆盖率**。

分母 \(U\) = 当日 taxonomy **tradable** 宇宙（非 quarantine；ST/停牌规则与 metrics 一致）。  
下列写入该日 `run_meta`：`bar_coverage`, `computable_coverage`, `limit_coverage_asof`, `open_raw_coverage_asof`, `ok_predicate_version=v1`。  
（历史日仍可填 `limit_coverage_asof` 作监控，**不参与**该日 ok 判定。）

#### 所有日 `D` 均须满足（含历史追赶）

| 条件 | 初阈 | 说明 |
|------|------|------|
| `D` 为交易日且该日流水线无致命错 | — | |
| `bar_coverage` | ≥ **0.90** | \(U\) 中具备当日 raw+qfq OHLC 及 `is_suspended`/`is_st` 的比例（已含 `open_raw`） |
| `computable_coverage` | ≥ **0.50**（冷启动可配置更低，正式评估前须达标） | \(U\) 中历史长度已够 metrics 门禁（§3.3）的比例 |

#### 仅当 `D == asof` 额外满足

| 条件 | 初阈 | 说明 |
|------|------|------|
| `limit_coverage_asof` | ≥ **0.80** | 当日 `limit_up` 与 `limit_down` 均非空的比例（影子/成交需要） |

**明确不挡历史日 `ok`（`D < asof`）：** 缺 `limit_*`、缺 `float_mv`。  
**明确挡 asof `ok`：** `limit_coverage_asof` 不达标；半截失败不得把 `last_ok` 越过失败日。  
**说明：** 不再单列 `open_raw_coverage_asof`（已含于 `bar_coverage`）；字段可保留为监控别名，数值应与 bar 内 raw open 覆盖一致。

影子 L：意图成交日对应的 **session asof**（或该成交日本身曾为某次 session 的 asof 且 `ok`）须曾 `ok`；确认日可以是历史 `ok` 日。MVP 不拆 `ok_shadow`。

### 7.3 缺口交易日（断点续跑）

**禁止**「上次成功日期的自然日 +1」。

```text
session_asof = 本轮收尾的最新已收盘交易日
last = 最近一个 run_meta.status=ok 的 trade_date
若无 last → 从冷启动策略决定的首个交易日起
否则 gap_start = next_trade_date(last)
待跑 = 交易日序列 [gap_start, …, session_asof]
for D in 待跑:
  sync + metrics + …
  if D < session_asof:
    用 §7.2「所有日」门槛判定 ok   # 不要求 limit_coverage
  else:  # D == session_asof
    用 §7.2「所有日」+「仅 asof」门槛判定 ok
  通过 → status=ok，last=D
  否则 status=partial（覆盖率/预算不足）或 fail（致命异常），下次仍从该 D 起（不跳过）
```

`partial`：覆盖率未达标或分批预算用尽。`fail`：未捕获异常 / 源全挂等致命错。二者均不前移 `last_ok`。

冷启动若暂时降低 `computable_coverage`：对应日标 `partial` 或单独 `backfill_ok` **不得**写入可被正式评估当作 `last_ok` 的 `status=ok`；升到正式阈后须重跑校验再标 `ok`。
### 7.4 分批回填

- 冷启动不要求单次 Actions 拉满全宇宙 ≥252 交易日。  
- 每 run：有限只数 × 有限日期（具体上限写入 `config`；超时则当日 `partial`，不标 ok）。  
- 正式「可评估」：`computable_coverage` 达 §7.2 正式阈之后，才把层 C/L 当决策输入。  
- 回填历史日：`float_mv` 按 §6.2，不得刷 spot。

---

## 8. 与其它 spec 的边界

| 主题 | 权威文档 |
|------|----------|
| 温度 / FSM / 节气 / 合成用市值语义 | metrics |
| ENTER/EXIT、涨跌停成交、`data_gap` 账本状态 | backtest-eval |
| Actions、`trend.db`、Issue、`paper_fill` 不可变 | ops |
| 宇宙是否含北交所、tradable | taxonomy |
| **源、限价缺失、float_mv as-of、ok 谓词、续跑、ts_code、19:00** | **本文** |

---

## 9. 验收（数据层）

1. `ts_code` 抽样均为 `^\d{6}\.(SH|SZ)$`。  
2. `next_trade_date(周五)` → 下周一（或节后）夹具。  
3. 跳过一交易日 → 下次从缺口日续跑，不从自然日 +1。  
4. 无 `limit_*` → `data_gap`；`limit_*` 与 `open_raw` 同为 raw 空间。  
5. `float_mv` 加权夹具：null 用 1.0 再归一；历史回填不得出现「用今日 spot 填旧日」。  
6. qfq 重刷：raw 不变；L fills 不变；H 可读新 qfq。  
7. 人为压低 **session asof** 的 `limit_coverage` → 该 asof 日 `status≠ok`，`last_ok` 不前移；同队列中 `D < asof` 且仅缺 `limit_*` 仍可 `ok`。  
8. 冷启动降低 `computable_coverage` 的日不得写入正式 `last_ok`。

---

## 10. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-10-01 | 初版：免费栈；data_gap 默认；board_calc 预留；float_mv 落库空则等权；Tushare 式 ts_code；19:00；交易日断点续跑；分批回填 |
| 2026-10-01 | review 修补：ok 覆盖率谓词；float_mv as-of/禁回刷；qfq 三句；limit 只对 open_raw；limit 覆盖并入 ok；cron UTC 11:00 |
| 2026-10-01 | 澄清 session asof：仅 asof 日卡 limit 覆盖率；历史追赶日不要求 limit；fail/partial；冷启动不进 last_ok |