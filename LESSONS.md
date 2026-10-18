<!-- reviewed-through: 666c78c7cb05f98a33ffc6a1391c9e7c7e40905f -->
# Project Lessons and Retrospectives (Lessons)

This is the target project's living incident and learning log, not a collection of generic examples. Except for the maintenance protocol defined in this file, every entry must come from commits, issues/PRs, CI output, reproduction records, or verifiable maintainer feedback inspected for this project; do not copy specific technical rules from templates or other projects.

## Maintenance protocol

- Daily review scope: run `scripts/freeze-review-range.py` and use its canonical manifest as the sole range authority; do not calculate the range from this marker or a later HEAD. If the marker is `UNKNOWN`, stop and ask a maintainer to choose the first target-branch commit to include; because the boundary is exclusive, use that commit's target-branch parent (the target-branch/first parent for a merge). Do not infer or auto-initialize this starting boundary; after explicit establishment, only the normal completed-review writer advances it to `through`. Review every commit in the manifest, but skip only the contents of each commit/parent/path recorded in `excluded_paths`; exclusions do not remove commits or their other paths. Record excluded paths and reasons in the archive. The `generated-data-paths` rule accepts only explicit literal paths and defaults empty; do not guess a target project's generated-data locations.
- Focus on errors in development, code review (CR), merge/release, and verification: **fixed and then reworked**, **merged/released when they should not have been**, and **insufficient validation or an untrusted validation baseline**. Do not review contents of generated-data snapshots excluded by the frozen manifest as Lessons, regardless of whether they came from training, an intermediate stage, ETL, a script, runtime behavior, or another generation process. A workflow or generated-data anomaly may be recorded as an automation-health/verification issue only with independent workflow, CI, validator, or similar evidence. Also record `Done right` to preserve effective practices.
- Write rules as short, executable constraints for next time; include the incident cause, impact, fix/follow-up action, and evidence links. When evidence is insufficient, phrase it as an open question, not as a confirmed causal claim.
- Count recurrence by **distinct completed review dates** on which the lesson appeared. Multiple commits or repeated events on the same day count as one day; do not inflate the count through repeated edits or by splitting a review.
- By default, only after a generalized stable rule has appeared independently in reviews on **at least 3 different dates** may it be promoted to the project-specific section of [`docs/code-standards.md`](docs/code-standards.md). During promotion, move the complete lesson record to promotion history, preserve its ID, dates, and citations, and note the promoted rule ID; do not lose the source.
- For a serious one-time security, data-loss, or release incident, an agent may immediately propose a temporary safeguard. Mark the proposal `Temporary rule / pending maintainer confirmation`; this does not count as a three-day promotion or authorize an unapproved product policy.
- After updating a rule, check AGENTS routing, relevant subsystem pages, tests, and other entry points for conflicts; keep one authoritative definition and do not duplicate it by copy-paste.
- Even when nothing is found that day, archive the frozen scope, excluded-path summary, sources checked, and “no new evidence-backed lesson”. Do not directly edit this file or advance the marker during a review; pass archive and Lessons content to `scripts/write-frozen-review.py`, which verifies the updates and advances `reviewed-through` to the manifest's `through` as its final durable write. A first-run `UNKNOWN` marker is not writer input: obtain the maintainer's starting-commit decision separately and keep this marker unchanged until an explicitly approved boundary is established.
- The Lesson-promotion CI check is read-only and checks only the persisted `LESSONS.md` and `docs/code-standards.md` records. It does not calculate or select a review range, inspect commits for a retrospective, create review archives, or read or update `reviewed-through`.

When recording a specific event, evidence may support checking whether it can be reproduced using the reporter's surface, scenario, and inputs; whether test fixtures preserve the shape of the real request or disk data; whether processes, asynchronous tasks, and temporary resources started by tests are cleaned up on both success and failure paths; and whether existing baseline failures were investigated and the conclusion recorded. These are review leads, not assumptions that this project already has these problems or must adopt a particular response; in particular, do not generalize one project's policy for handling red tests into a rule for all projects.

## Record identity and evidence schema

- Give every lesson a stable ID of the form `L-0001` (the numeric suffix has at least four digits). Assign the next unused ID; never change it when wording, dates, or status change, and never reuse an ID. IDs must be unique across the active-lessons and promotion-history blocks.
- Keep active records between `ACTIVE_LESSONS:START` and `ACTIVE_LESSONS:END`, and promoted records between `PROMOTED_LESSONS:START` and `PROMOTED_LESSONS:END`. Each record heading starts `### L-0001 —` followed by the executable rule.
- Under **Review evidence**, each row begins with a backtick-delimited ISO date, followed by an em dash and a Markdown link to specific inspected project evidence. The date is the date of the completed review that observed the lesson, not a commit timestamp, event date, or promotion date. Each row must cite concrete evidence inspected for that date. Multiple rows or citations from the same review date count once.
- A promoted standard uses a stable ID of the form `PS-0001`. Its standards entry must cite one or more lesson IDs, and the union of those lessons' structured review-evidence rows must contain at least three different valid dates. The corresponding promoted lesson record names that `PS-` ID.
- A promotion date is traceability metadata, not evidence. Legacy `Seen N×` text or a generic Evidence field without structured date-specific citations does not count toward the threshold. Migrate only dates and citations supported by repository evidence; do not infer review dates from commit dates, repeated mentions, or the date of this migration. If the evidence cannot be verified, leave the rule unpromoted and state the migration gap.
- CI checks ID syntax/uniqueness, cross-references, date syntax/distinctness, and citation shape. It cannot determine whether a cited artifact is genuine, whether the reviewer actually inspected it, whether the observations are semantically the same lesson, or whether the evidence justifies the rule; those remain human-review responsibilities.

## Active lessons

<!-- ACTIVE_LESSONS:START -->
<!-- frozen-review-lessons: sha256:a0fff8321f1f34aa4f37e738cfffcabb4f49dea8273f5a5ca8775ae74668122b -->
### L-0001 — 代码或文档评审提交不得改写 data/trend.db
- **Why:** `40d15113e6` 的主题写着去掉误带的库，但该提交仍然修改了 `data/trend.db`。下一笔 `c919c176c0` 写明这覆盖了 Spec E 的 9.30 库，并恢复了库和 heartbeat。本次没有读取库内容。
- **Review evidence:**
  - `2026-10-18` — [40d15113e6 仍修改 data/trend.db](https://github.com/financeView/trending/commit/40d15113e64c1cd5af5bfff66b1b0058f189d910)
  - `2026-10-18` — [c919c176c0 恢复被 digest CR 覆盖的库](https://github.com/financeView/trending/commit/c919c176c0f4e74ab817c210d36c152d4fd3149a)
- **Fix or follow-up:** 恢复提交 `c919c176c0`。之后的复盘排除规则只排除该路径的内容，不阻止提交本身被看见。
- **Done right:** 无。
- **Status:** active

### L-0002 — 不要把 sync 作业超时改回 360 分钟
- **Why:** `a154e8af` 将 `.github/workflows/daily-trend.yml` 的 sync `timeout-minutes` 从 360 改为 720。该提交说明 360 会在约 5500 只股票的冷启动中把作业杀掉，并引用 Actions run `38443732944`。本次没有打开该 run 的日志。规格 `2026-10-08-workflow-split-jobs-design.md` 仍写 360，不能据此把 workflow 改回去。
- **Review evidence:**
  - `2026-10-18` — [a154e8af 将 sync 超时从 360 改为 720](https://github.com/financeView/trending/commit/a154e8af7842de31341b8ba70106cdd47111e79f)
- **Fix or follow-up:** workflow 已是 720。metrics 作业仍是 360。索引已标明差异。
- **Done right:** 超时上调后，文件头保留了 360 会杀作业的原因。
- **Status:** active
### L-0003 — 含 *ST 的股票名写入 YAML 前必须加引号
- **Why:** `43f387c` 说明裸写 `*ST美丽` 会被 YAML 当成别名，`safe_load` 失败，刷新和 sync 在上次快照推送后断开。该提交给含 `*` 等特殊字符的名称加引号，并在发布前拒绝无法加载的 dump。
- **Review evidence:**
  - `2026-10-18` — [43f387c 为 *ST 名称加引号](https://github.com/financeView/trending/commit/43f387cedd472eb733d4e0e4698b1e0a6644f39a)
- **Fix or follow-up:** 已有 `tests/test_fetch_sw_normalize.py`。
- **Done right:** 发布前检查 dump 能否加载。
- **Status:** active

### L-0004 — only_date 的 sync --end 必须绑定请求日期
- **Why:** `b80a391405` 让 sync 始终把 `--end` 指到 tip asof，只把 metrics 绑到 DATE。`3b374fe` 说明这样补 9 月 30 日会去填整个 tip 宇宙。后一笔把 only_date 的 `--end` 改回 DATE，cron 仍用 tip asof。
- **Review evidence:**
  - `2026-10-18` — [b80a391405 把 only_date 的 end 指到 tip asof](https://github.com/financeView/trending/commit/b80a391405)
  - `2026-10-18` — [3b374fe 改回 DATE](https://github.com/financeView/trending/commit/3b374fe44ef32268dfe14e2285c246711de67122)
- **Fix or follow-up:** `tests/test_p2_workflow_order.py` 锁了 workflow 顺序。
- **Done right:** 无。
- **Status:** active

### L-0005 — 生产拉取申万分类表不得使用 verify=False
- **Why:** `5c1eaf2` 为绕过 GitHub Actions 的证书签发者检查，给申万 XLS 下载加了局部 `verify=False`。`f760ab1` 删掉该测试，改为 certifi 根证书加上单独的 GeoTrust 中间证书，并保留 180 秒、3 次重试。
- **Review evidence:**
  - `2026-10-18` — [5c1eaf2 使用 verify=False](https://github.com/financeView/trending/commit/5c1eaf2c0c)
  - `2026-10-18` — [f760ab1 改为显式 CA 包](https://github.com/financeView/trending/commit/f760ab14fd)
- **Fix or follow-up:** 生产路径以 `f760ab1` 为准。probe workflow 里的实验步骤不是日更生产拉取。
- **Done right:** 无。
- **Status:** active

### L-0006 — 东财限价拉取失败不得让已完成的 OHLC 同步整次失败
- **Why:** `c99053c` 说明 GitHub runner 访问东财 f51/f52 会失败。OHLC 和 flags 已经同步时，限价改为尽力而为；历史 `--date` 不再回补当天限价。
- **Review evidence:**
  - `2026-10-18` — [c99053c 限价失败不再失败整次 Actions](https://github.com/financeView/trending/commit/c99053c542)
- **Fix or follow-up:** 已有 `tests/test_sync_from_universe.py`。
- **Done right:** 失败记到 stderr，而不是让作业非零退出。
- **Status:** active

### L-0007 — taxonomy YAML 发布失败必须回到提交前的 SHA
- **Why:** `9f99d00` 在 commit 之后如果 push 或 rebase 失败，不能靠 `ORIG_HEAD` 留下未推送的 YAML。它在提交前记下 HEAD，失败时 `git reset --hard` 回到该 SHA。
- **Review evidence:**
  - `2026-10-18` — [9f99d00 发布失败硬重置](https://github.com/financeView/trending/commit/9f99d00ecc)
- **Fix or follow-up:** 无未关闭项。
- **Done right:** `tests/test_refresh_taxonomy.py` 覆盖这条失败路径。
- **Status:** active
### L-0008 — 日历警告必须写到 stderr
- **Why:** `00406b1e08` 之前 `latest_trade_day` 的警告打在 stdout。workflow 用 `ASOF=$(python ...)` 取日期，警告会混进这个值。
- **Review evidence:**
  - `2026-10-18` — [00406b1e08 把日历警告改到 stderr](https://github.com/financeView/trending/commit/00406b1e08f78bd926abd07789c27f57274f5ea9)
- **Fix or follow-up:** 捕获日期时加了 `2>/dev/null`，警告改为 `print(..., file=sys.stderr)`。
- **Done right:** 无。
- **Status:** active

### L-0009 — 单只股票的行情或标志异常不得中止整次 mapped sync
- **Why:** `00406b1e08` 说明空的 sina 响应会中止 mapped-universe sync。该提交按股票捕获 `sync_symbol_bars` 和 `sync_baostock_flags` 的异常，只把跳过写到 stderr。
- **Review evidence:**
  - `2026-10-18` — [00406b1e08 单票失败不再中止 sync](https://github.com/financeView/trending/commit/00406b1e08f78bd926abd07789c27f57274f5ea9)
- **Fix or follow-up:** 已有 `tests/test_sync_budget.py`。
- **Done right:** 无。
- **Status:** active

### L-0010 — only_date 的 live_shadow 必须传 --asof DATE
- **Why:** `2be57ab352` 之前，`only_date` 仍调用 `live_shadow_step.py --from-heartbeat`。该提交在 `only_date` 时改为 `--asof "$DATE"`。
- **Review evidence:**
  - `2026-10-18` — [2be57ab352 给 only_date 的 live_shadow 钉上 --asof](https://github.com/financeView/trending/commit/2be57ab352df839afb617155552774ee2ae6810f)
- **Fix or follow-up:** `tests/test_p2_workflow_order.py` 锁了这条命令。
- **Done right:** 无。
- **Status:** active

### L-0011 — L1 digest 的 L2 成分必须来自当日 daily_stock
- **Why:** `e37edc5ae3` 之前 `_l2_codes_for_l1` 读 `STUB_L1_TO_L2`。该提交改为按 `trade_date` 和 `l1_id` 查询 `daily_stock`。
- **Review evidence:**
  - `2026-10-18` — [e37edc5ae3 停止用 stub map 扫 L2](https://github.com/financeView/trending/commit/e37edc5ae3f269baf5dab73c5deb94578fc89008)
- **Fix or follow-up:** 已有 `tests/test_l1_digest.py`。
- **Done right:** 无。
- **Status:** active

### L-0012 — heartbeat skip 测试必须先写入会被跳过的 run_meta
- **Why:** `e37edc5ae3` 说明缺行时，heartbeat-skip 测试也能通过。该提交先插入当日 `run_meta`，再断言 `live_publish_allowed` 因 skip 拒绝。
- **Review evidence:**
  - `2026-10-18` — [e37edc5ae3 给 skip 测试种下 run_meta](https://github.com/financeView/trending/commit/e37edc5ae3f269baf5dab73c5deb94578fc89008)
- **Fix or follow-up:** 无未关闭项。
- **Done right:** 断言发生在发布桩之前。
- **Status:** active

### L-0013 — 数字形式的 YYYYMMDD 不得先按 Unix 时间解析
- **Why:** `3c4a54d1f4` 在把 f26 当成秒或毫秒之前，先识别 `19000101` 到 `21001231` 的整数日期。标成可发布的提交 `36f2c2878a` 是它的祖先。
- **Review evidence:**
  - `2026-10-18` — [3c4a54d1f4 先解析 YYYYMMDD](https://github.com/financeView/trending/commit/3c4a54d1f45d62015499bf2a55662ed75a6b9613)
- **Fix or follow-up:** 已有 `tests/test_unmapped_metrics.py`。
- **Done right:** 无。
- **Status:** active

### L-0014 — 有上游时，YAML 发布失败必须重置到 @{upstream}
- **Why:** `9f99d00ecc` 先捕获提交前的 HEAD。`3c4a54d1f4` 把恢复顺序改成先 `@{upstream}`，没有上游时才用那个 SHA。提交之后的 `ORIG_HEAD` 仍然不能用。
- **Review evidence:**
  - `2026-10-18` — [3c4a54d1f4 优先重置到 upstream](https://github.com/financeView/trending/commit/3c4a54d1f45d62015499bf2a55662ed75a6b9613)
- **Fix or follow-up:** `tests/test_refresh_taxonomy.py` 覆盖恢复顺序。
- **Done right:** 无。
- **Status:** active

### L-0015 — continue-on-error 的 Issues 步骤必须带 success()
- **Why:** `cd932dd209` 拆 sync 和 metrics 时拿掉了 Issues 步骤的 `success()`。下一步 `11f8ed4943` 补回，避免失败的 daily_run、shadow 或 commit 仍改写 L1/Radar Issues。
- **Review evidence:**
  - `2026-10-18` — [cd932dd209 拆 job 时拿掉 success()](https://github.com/financeView/trending/commit/cd932dd209167396e26f907bfa45798ade823818)
  - `2026-10-18` — [11f8ed4943 补回 success()](https://github.com/financeView/trending/commit/11f8ed49438109fbee1fe7a9fcab2937452fcbe4)
- **Fix or follow-up:** workflow 条件已是 `skip_issue_update != 'true' && success()`。
- **Done right:** 无。
- **Status:** active

### L-0016 — BaoStock 批量会话失败或中毒后不得退回按票登录
- **Why:** `5d7dd4be93` 删掉批量登录失败后的按票登录。剩余 flags 关掉；会话中毒只做有限次 backoff 重开，超过则跳过。
- **Review evidence:**
  - `2026-10-18` — [5d7dd4be93 禁止按票登录风暴](https://github.com/financeView/trending/commit/5d7dd4be93a3fdb0d6e93b0d7cd1158eb6bb7dbb)
- **Fix or follow-up:** 已有 `tests/test_baostock_poison.py`。同笔其余审计硬修已拆为 L-0017–L-0020。
- **Done right:** 无。
- **Status:** active

### L-0017 — daily_l2 不得保留 801* 或非 §4 幽灵板；空 §4 不得伪造板面
- **Why:** upsert 不删孤儿时，旧的 `801xxx` / 非税表码会留在 `daily_l2`。`5d7dd4be93` 增加 `purge_invalid_daily_l2`，并把 `l2_members_map` 钉在 §4；成员数为 0 的 §4 码（如 460700/720800/480600）不应出现板面行。
- **Review evidence:**
  - `2026-10-18` — [5d7dd4be93 提交说明含 Purge non-§4/801](https://github.com/financeView/trending/commit/5d7dd4be93a3fdb0d6e93b0d7cd1158eb6bb7dbb)
  - `2026-10-18` — [tests/test_purge_daily_l2.py](tests/test_purge_daily_l2.py)
  - `2026-10-18` — [tests/test_l2_members_section4.py](tests/test_l2_members_section4.py)
- **Fix or follow-up:** 已合入 purge 与 §4 夹具；日更路径见 `daily_run` 写 L2 后的 purge。
- **Done right:** 空 §4 用税表成员计数断言，而不是靠板面缺席猜测。
- **Status:** active

### L-0018 — 篮 amount 不得计入成分 T is null 的成交额
- **Why:** 短史/IPO 等未入 FSM 的票 `T=null` 但成交额可极大（如能源金属 C力勤），会把 L2 篮额与读数带偏。`5d7dd4be93` 在 `_basket_asof_row` 只累加 `T is not None` 的 amount。
- **Review evidence:**
  - `2026-10-18` — [5d7dd4be93 提交说明含 exclude T=null from basket amount](https://github.com/financeView/trending/commit/5d7dd4be93a3fdb0d6e93b0d7cd1158eb6bb7dbb)
  - `2026-10-18` — [tests/test_basket_asof_row.py::test_amount_excludes_members_without_T](tests/test_basket_asof_row.py)
- **Fix or follow-up:** `scripts/daily_run.py` `_basket_asof_row` 已闸。
- **Done right:** 夹具直接锁「高额 null-T + 低额有 T → 篮额=有 T 侧」。
- **Status:** active

### L-0019 — daily_stock.close 必须与 close_qfq 同源落库
- **Why:** 只写 `close_qfq` 而 `close` 全日 NULL 时，下游读 `close` 的路径会误判无价。`5d7dd4be93` 将 `close` 镜像为 `close_qfq`。
- **Review evidence:**
  - `2026-10-18` — [5d7dd4be93 提交说明含 mirror close_qfq](https://github.com/financeView/trending/commit/5d7dd4be93a3fdb0d6e93b0d7cd1158eb6bb7dbb)
  - `2026-10-18` — [daily_run.py stock row close←close_qfq](scripts/daily_run.py)
- **Fix or follow-up:** `_stock_asof_row`（或等价落库路径）保持 `close` 与 `close_qfq` 同值。
- **Done right:** 无。
- **Status:** active

### L-0020 — 历史日 float_mv 为 null 属契约预期，不得当回归失败；禁 spot 回刷
- **Why:** market-data §6 只允许 tip/session asof 写东财 f21 spot；历史补旧日无历史市值源则保持 null，权重走 §6.3 `w_raw=1.0`。`5d7dd4be93` 增加 asof 写入路径，但 probe/workflow 仍不能也不应用今日 spot 回刷旧日。
- **Review evidence:**
  - `2026-10-18` — [5d7dd4be93 提交说明含 asof float_mv via EM f21](https://github.com/financeView/trending/commit/5d7dd4be93a3fdb0d6e93b0d7cd1158eb6bb7dbb)
  - `2026-10-18` — [tests/test_float_mv_asof.py](tests/test_float_mv_asof.py)
  - `2026-10-18` — [market-data-contract §6](docs/superpowers/specs/2026-10-01-market-data-contract-design.md)
- **Fix or follow-up:** tip 日需 `end==session_asof` 且带 limits/f21 路径才可能非空；接历史源（如 Tushare `daily_basic.circ_mv`）前保持 null 预期。
- **Done right:** 夹具只测 asof upsert，不把历史回刷写进生产路径。
- **Status:** active
<!-- /frozen-review-lessons: sha256:a0fff8321f1f34aa4f37e738cfffcabb4f49dea8273f5a5ca8775ae74668122b -->
<!-- ACTIVE_LESSONS:END -->

## Promotion history

> Preserve each promoted lesson's original ID, explanation, dated evidence, and follow-up here; record the promotion date and standards rule ID.

<!-- PROMOTED_LESSONS:START -->
<!-- PROMOTED_LESSONS:END -->

## Entry format

The following is a format template, not evidence and not a record to copy as a factual lesson:

```markdown
### L-0001 — <one executable rule>
- **Why:** <cause and consequence confirmed by the review; clearly mark uncertain parts>
- **Review evidence:**
  - `YYYY-MM-DD` — [specific inspected project evidence](URL-or-repository-path)
  - `YYYY-MM-DD` — [specific inspected project evidence](URL-or-repository-path)
  - `YYYY-MM-DD` — [specific inspected project evidence](URL-or-repository-path)
- **Fix or follow-up:** <fix commit, or owner if unresolved>
- **Done right:** <if any, record a counterexample or effective practice>
- **Status:** active | promoted
- **Promoted rule:** PS-0001 (required only after promotion)
- **Promotion date:** YYYY-MM-DD (required only after promotion; not evidence)
```
