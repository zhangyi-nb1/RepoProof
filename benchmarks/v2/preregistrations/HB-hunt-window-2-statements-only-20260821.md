# HB 猎取窗口 2 · **只补题面** · 窗口附则(2026-08-21 冻结)

> **冻结先于开窗。** 本附则挂在
> `HB-postcutoff-delta-hunt-prereg-20260816.md` §1(网络窗口纪律)之下,
> 只收窄、不放宽:窗口 1 允许的动作里,本窗口**只做其中一件**。
> 用户 2026-08-21 裁:走"窄窗口只补题面"。

## 0. 为什么需要这个窗口(全部是实测,不是推断)

第三轮盘点(`docs/evidence/d5_hunt/admission-round3-inventory.json`)测到:

- 封存池 14 个候选包全部裁完 —— 可出题池 = `click-3581` + `sqlglot-8042`
  (`click-3407` 已按 P1-b 因题面欠定退役);
- 窗口 1 的审计单里**还有 8 条已判合格但从未抽取的 sqlglot PR**;
- 这 8 条的 `parent_tree` / `delta_tests` / `answer` **三件都能离线抽出**
  —— 封存 clone 带 `.git`,`merge_sha` 逐条在审计单里;
- **唯题面抽不出**:窗口 1 只为选中的 10 条拉了 PR 正文;merge commit 消息
  只有 squash 摘要与中间提交列表,不含正文(逐条实查 760acbbd / f85ea4c2 /
  1a38c056)。

所以缺口精确到一件事:**8 条 PR 的正文原文**。

## 1. 窗口动作清单(白名单;清单外的一切网络动作都是违规)

窗口内**只允许**:

1. 对下列 8 条 PR,取 **PR 正文**;
2. 若正文引用了 issue,取该 **issue 原文**(与窗口 1 同规:题面 = 上游原文,
   出题方是上游维护者,不是我们)。

**明令不做**(逐条对应窗口 1 §1 的同一条纪律):

- 不做新的候选**选择** —— 选择在窗口 1 已由机械过滤器完成并留痕
  (`tobymao__sqlglot.json` 的 `qualifies` 位),本窗口一位不改、不重算;
- 不拉实现 diff、不拉测试件、不拉任何仓 —— 三件走离线抽取;
- 不跑盲攻、不评分、不看任何"这题好不好打"的信号;
- 不补下载任何轮子(**封存不重下**);轮仓复用窗口 1 的
  `d5-hunt/wheelhouse/sqlglot`,只读。

## 2. 名单(冻结;取自窗口 1 审计单 `qualifies=true` 中未抽取的全部)

| PR | merged_at | merge_sha | test+ | impl+ | impl_files[0] | body_len | issue_ref |
|---|---|---|---|---|---|---|---|
| 8018 | 2026-08-03 | 760acbbdb | 75 | 49 | sqlglot/typing/mysql.py | 305 | 否 |
| 7953 | 2026-07-27 | f85ea4c2d | 24 | 93 | sqlglot/executor/python.py | 1093 | 是 |
| 7924 | 2026-07-24 | 1a38c056a | 12 | 84 | sqlglot/optimizer/merge_subqueries.py | 1410 | 否 |
| 7892 | 2026-07-23 | 3cd3e58e1 | 15 | 48 | sqlglot/generators/duckdb.py | 753 | 否 |
| 7929 | 2026-07-22 | ee5a989cd | 8 | 35 | sqlglot/parser.py | 493 | 是 |
| 7883 | 2026-07-20 | c933fe330 | 42 | 63 | sqlglot/optimizer/merge_subqueries.py | 787 | 否 |
| 7847 | 2026-07-14 | 7099d896d | 17 | 61 | sqlglot/optimizer/merge_subqueries.py | 645 | 否 |
| 7855 | 2026-07-13 | 2d86a76bc | 36 | 30 | sqlglot/generators/bigquery.py | 12 | 是 |

全部字段为窗口 1 审计单原值,本窗口不重算。**7855 正文只有 12 字节**——
它的题面若成立只能来自引用的 issue;取回后仍不成立就按 §2 项 9(题面不存在)
判死,不许拿 diff 反推题面。

## 3. 封存去向:**新目录,旧池只读**

窗口 1 的 `~/RepoProofArchive/d5-hunt/` 是**只读封存对象**,本窗口一个字节
都不往里写。新件落 `~/RepoProofArchive/d5-hunt-w2/`:

```
d5-hunt-w2/
  statements/<cid>.md          窗口内唯一的网络产物
  candidates/<cid>/            窗口后离线抽取(parent_tree/delta_tests/answer/manifest.json)
  window2_manifest.json        审计链
```

轮仓与 clone **不复制**,按只读引用旧池(封存不重下的字面含义)。

## 4. 窗口后的离线流水线(与窗口 1 §3 同一条,不改判据)

① 离线抽件(parent = `merge_sha^`,`git archive` 无 `.git`;delta 测试件与
答案分区)→ ② 卫生电池 **H1–H6**(prereg-v2 判据;H6 = P1-c 新增的题面欠定
探测)→ ③ 基线双向实测 → ④ 盲攻(单发,另计 API)→ ⑤ 评分 → ⑥ 残差分类
→ ⑦ 判决(0.95 线;没量过 = 判死)。

**产率不预设**:上一轮 10 → 卫生 4 → 准入 3。本轮 8 条按同判据走完,合格
几条就是几条,**不因为池空而放宽任何一条线**。

## 5. held-out 预留(本附则冻结,合格后立即生效)

本轮准入合格的候选,按 `merged_at` 倒序编号,**奇数位进开发池、偶数位进
held-out**;held-out 候选:

- 只建包、不建宿主、不跑任何 harness 迭代发次;
- 题面/节点名/失败样本**不得**进入任何 harness 修复的依据链;
- 只在 harness 冻结后开考,且开考即公开其冻结时的 harness commit。

分配规则**在看到任何卫生/盲攻结果之前**冻结在此,防"挑好打的留给自己"。
