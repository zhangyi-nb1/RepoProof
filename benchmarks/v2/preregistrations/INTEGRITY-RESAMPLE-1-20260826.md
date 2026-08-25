# INTEGRITY-RESAMPLE-1:主仓完整性干净复样批(冻结,待批准开跑)

> 2026-08-26 · 目的不是成功率,也不是模型对比,而是回答一个被
> **限定句**挂账的问题:那 8 个 ACTIVE 工具的冻结任务,在**完整性闸
> 真正参与判定**的今天,还能不能干净地过全链?

## 一、动机(一条挂账的限定句)

2026-08-25 修好 `apply_integrity_to_verdict`(完整性进最终判定)后,
2026-08-26 清点存量发现:**19 发 PRODUCT 记 PASS 而
`main_dir_integrity=MISMATCH`**,其中 10 发绑定已导出工具、**8 个当时
ACTIVE**。旧发次 `self_ok` 全为 `None`(当时未接自写窗),按本项目自身
规则「不传窗口 = 无归因依据 = 一律不免罪」,按现行闸应记
`BLOCKED/MAIN_DIR_INTEGRITY_UNATTRIBUTED`。

mismatch 一律是 `offerclaw[tree|git_refs]` —— 邻仓活写手(实测每
7–28 秒一次 `logs/llm_usage.jsonl`),不是执行缺陷。

用户 2026-08-26 裁决为**记事实 + 强制限定句,不撤回、不重跑**,并把
"干净环境复样"挂账。本批就是兑现这笔挂账。

**本批不改变的东西(先说清楚,防止事后越界解读)**:

- 复样**不追改**任何历史 verdict —— 旧发次的 PASS 与其 MISMATCH 都
  原样留在台账里(判据 K1);
- 复样**不替换**已导出工具包、不动 registry、不动 release ledger ——
  同 task_id 覆盖被 `tool_export` 硬拒(需 `-vN+1` 谱系升级),而升级
  会把 8 个工具全部打回 `REVIEW_REQUIRED`,那是另一件事、另一次授权;
- 因此复样能证明的是:**"这道冻结题 + 这个钉版上游,在完整性闸下确实
  能干净通过"**;它不能、也不声称能证明"当初那一发是干净的"。
  限定句因此从「无复样」升级为「有干净复样」,措辞见 §六。

## 二、冻结配置

| 轴 | 值 |
|---|---|
| 模型 | `gpt-5.6-terra`(`.env` 现行缺省;不做模型对比,不加发 luna) |
| 后端 | mini-swe(与原发一致);provider = `.env` 缺省 openai 通道 |
| 入口 | `repoproof host-run --contract contracts/<task_id>.yaml`(直接跑既有冻结任务包,**不走 `tool build`** —— 物化闸会因任务包已存在而拒,且本批本就不该重新物化) |
| 任务 | 8 个**原样冻结**的 v1 契约,一字不改;`--allow-retired` 不使用 |
| 发制 | 每任务一发;`--run-index 1`;失败=数据,不重发刷绿 |
| run_order | `product-85..92`(现行 product-* 最大号 84,连续续编) |
| batch | `INTEGRITY-RESAMPLE-1` |
| 批帽 | 名义 in **1,200,000**(估算 ~724K,留 ~65% 余量);发前判定触顶即停 |
| 口径 | `test_mode=PRODUCT`;真发 `PRODUCT_ONBOARDING`、彩排 `HARNESS_SELFCHECK`;**不充闸、不计模型能力、不进 held-out 分母**(RFC-010 [G4]) |

## 三、任务清单(8 个,换任务禁止;不可行=如实放弃行)

按原发 in tokens 升序执行(便宜的先跑,早暴露环境问题):

| # | run_order | task_id | 原发 in | 原发 calls | 原发 mismatch |
|---|---|---|---:|---:|---|
| 1 | product-85 | `tool-phonenumbers-tool-v1` | 37,877 | 8 | offerclaw[tree] |
| 2 | product-86 | `tool-opencc-tool-v1` | 60,991 | 11 | offerclaw[tree] |
| 3 | product-87 | `tool-filetype-tool-v1` | 63,252 | 10 | offerclaw[tree] |
| 4 | product-88 | `tool-jieba-tool-v1` | 63,822 | 11 | offerclaw[tree] |
| 5 | product-89 | `tool-xmltodict-tool-v1` | 81,249 | 13 | offerclaw[tree] |
| 6 | product-90 | `tool-pypinyin-tool-v1` | 117,847 | 14 | offerclaw[tree] |
| 7 | product-91 | `tool-inflect-tool-v1` | 135,611 | 20 | offerclaw[tree] |
| 8 | product-92 | `tool-emoji-tool-v1` | 171,440 | 20 | offerclaw[tree] |

原发全部 `rounds=1`(首轮即过),模型为 `gpt-5.5`;本批换 terra 属
**已知的非受控变量**,故本批不得用于任何模型间比较(§五 D)。

## 四、执行前提(硬前提,不满足即不开跑)

这批的**唯一目的**就是拿到干净的完整性,所以前提比通常更硬:

- **P1 静默窗**:开跑到收批期间,`offerclaw` / `localflow` /
  `RepoProof` / `RepoProof-studio-ui`(= `structural_protected()` 的
  全集)**不得有任何人为或后台写入**。含:编辑器自动保存、offerclaw
  的 `logs/llm_usage.jsonl` 活写手、任何并行 AI 会话、`git` 操作。
  开跑前用 `find -newermt` 三次采样确认静默。
- **P2 AI 侧禁写**:执行期间助手不得编辑仓内任何文件(含文档、台账)。
  所有落账动作推迟到全批结束之后统一进行。
- **P3 彩排先行**:8 个任务先各跑一次 `--fake positive` 彩排
  (零模型预算)。**彩排本身也必须拿到 `main_dir_integrity=ok`**
  —— 彩排若已经脏,说明静默窗没成立,此时立即停,不烧真实预算。
  这是本批把彩排门用作"环境验证"而非仅"链路验证"的地方。
- **P4 预算**:发前核对累计 in 未触 §二 批帽。

## 五、判据(本批要回答的问题,发前冻结)

- **A(主判据)**:8 发中有多少发拿到 `main_dir_integrity=ok`
  **且** verdict ∈ `PASS_ADAPTED`/`PASS_DIRECT`。这类发次即为该任务的
  **干净复样样本**。
- **B**:任何一发若 `ok=false`,必须能从 `self_ok` 与 attribution 读出
  是谁写的;若归因为外部写手 → 说明 P1 静默窗被破,该发作废重跑不计
  预算争议(记 HARNESS/环境层,勘误如实写);若归因为本链 → 那是**真
  发现**,说明 harness 自己在写保护目录,必须停批排查。
- **C**:复样 verdict 与原发 verdict 一致性如实报。**不一致不算失败**
  —— 换了模型(gpt-5.5 → terra),原发 rounds=1 的题在 terra 上可能
  走不同路径。不一致时记录终止码与 FailureAssessment 投影即可。
- **D**:**本批不产出模型能力结论**。terra vs gpt-5.5 的任何差异不得
  被解读为模型对比(任务已见 + 单发 + 非受控),违者即 F14。

## 六、收批后的落账动作(冻结在此,防事后改口径)

对每个拿到干净复样(判据 A)的任务:

1. 在 `run_classifications.jsonl` 追加该新发次的分类行(常规
   PRODUCT 口径),并在**原交付发次**的勘误链上再追加一条覆盖行,
   注明"同题干净复样已取得,run_id=<新 run_id>,
   `main_dir_integrity=ok`";
2. `docs/product_summary.json` 重建(新增字段
   `clean_resample_for` 映射:原交付 run_id → 干净复样 run_id);
3. 限定句措辞升级(README / PROJECT_MAP / CLAIMS_MATRIX C8 /
   HANDOFF_STATE / RESUME_CLAIMS / INTERVIEW_GUIDE 同步),从

   > 其中 8 个的交付发次在现行完整性闸下应判 BLOCKED

   升级为

   > 其中 N 个的交付发次在现行完整性闸下应判 BLOCKED;同题冻结任务
   > 已于 2026-08-26 取得完整性干净的复样(见 INTEGRITY-RESAMPLE-1)

   **注意**:`check_public_claims.py` 的 `INTEGRITY_CAVEAT` 常量是
   逐字匹配的前半句,升级措辞时**保留该子串**,只在其后追加复样事实
   —— 否则限定句的机器钉死会被静默绕过(这正是它存在的理由)。

对**没有**拿到干净复样的任务:限定句保持原样,如实记未取得。

## 七、停点

- 彩排阶段任一任务 `main_dir_integrity` 不 ok → 停批(P3);
- 真发阶段出现判据 B 的"归因为本链" → 停批排查;
- 累计 in 触 §二 批帽 → 停批;
- 任一发出现 `BLOCKED` 且非完整性原因 → 停批,先排障。

## 八、勘误/执行记录(append-only)

(待执行后填写)
