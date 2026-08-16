# 预注册:HB 首批 · post-cutoff delta 模型发次(HB-PCDELTA-1,2026-08-16 冻结)

> **状态:定稿。** 两项待裁已由用户 2026-08-16 裁定:**公开面 = A 案
> (盲攻同视野)、模型序 = A 案(GPT 双模型 pilot)**。本文提交即冻结
> → §10 前置全绿 → 开跑。冻结后改动一律附录制,开跑后改动 = 整批作废。
>
> 上游文书:猎取与准入按 `HB-postcutoff-delta-hunt-prereg-20260816.md`(v1)
> 与 `…-prereg-v2-20260816.md`(v2)执行完毕,判决
> `docs/evidence/d5_hunt/admission-round2.json`。**本预注册只管模型发次。**

**测试模式:HB(TESTPLAN §11)—— 第一次真实使用。**

- 与批 11/12 的"名义 HB"的区别:判据是**上游自带测试**(裁决 D1 严口径,
  `UPSTREAM_OWN_TEST_SUITE`,我们只接线、一个字不改),出题方(题面作者与
  验收作者)均非本人;
- 与 PQ 的区别:**计模型表现**(`counts_toward_heldout_benchmark: true`,
  台账 heldout 分母第一次非零);
- 与 AR 的区别:不是攻击判据,是测模型;
- 与 WH 的区别:无 H0/H2 两臂(D4 未裁,WH 另立)。

---

## §1 要回答的问题(只有一个)

> 在"**记忆不可能**(delta 合并于受测模型知识截止之后)、**先验推不出**
> (盲攻实测上界)、**判据上游自写**(D1 严口径)"的 held-out 任务上,
> 真实模型能不能交出被上游隐藏验收语义接受的实现?

这是**存在性**问题。本批**不**回答:哪个模型更强(不排名)、成功率多少
(不出率)、harness 有无增益(那是 WH)、DeepSeek 行不行(未过 DQ 不进场)。

## §2 任务池(冻结,一字不增删)

来自 admission-round2,共 3 题。**引用纪律:任何发次数字必须与本表盲攻
上界并排出现** —— "模型 delta 全绿"的意义只有对照"盲攻拿回多少"才成立。

| 任务 | delta 节点 | 盲攻上界 | 备注(随档,引用时必带) |
|---|---|---|---|
| click-3581 | 3 | **0/3 = 0%** | 主力档案;题面容纳两案,唯隐藏测试知道答案 |
| sqlglot-8042 | 5 | **4/5 = 80%** | 净判别余量 **1 节点**(盲攻已拿回 4);模型全绿的增量信息集中在该节点 |
| click-3407 | 1 | **0/1 = 0%** | **1 bit 单薄档**:不单独立论,数字只随档;题面作者自列三选项歧义大 |

- 盲攻者为最强可用模型(Fable 子代理),与受测 GPT 系**不同族**;上界按
  "最强攻击者"读,对较弱受测模型是保守上界。
- 任务执行序(冻结):**3581 → 8042 → 3407**(判别力大的先跑,薄档最后;
  若停批线中途触发,损失最小化)。

## §3 出题构造(每题同构)

| 件 | 来源(封存池 `~/RepoProofArchive/d5-hunt/`,封存不重下) |
|---|---|
| 交付树 | `candidates/<id>/parent_tree`(无 `.git`,已过剥离+泄漏扫描+自证) |
| 题面 | `candidates/<id>/statement.md`(PR/issue **原文**,上游作者) |
| 隐藏 oracle | `candidates/<id>/delta_tests`(FAIL_TO_PASS 已在准入实测;发次侧只接线) |
| 回归面 | parent 树既有套件,钦定跑法(click=pytest / sqlglot=`python -m unittest`),必须保持全绿 |
| 答案 | `candidates/<id>/answer/full.patch` —— **永不进交付面**;仅作 F0 正控素材与事后残差核对 |

契约要素(出题工程按此生成,见 §10):

- `host.setup_commands`:离线 wheelhouse 建 venv + 上游 extras 声明装测试
  依赖(准入量具同配方;sqlglot 需 env `SETUPTOOLS_SCM_PRETEND_VERSION`,
  是 harness 旋钮不动树);
- `acceptance.public_test_command`:按 §4 裁决落定;
- 隐藏验收:delta 节点级 FAIL_TO_PASS(评分语义与
  `blind_attack_admission.py` delta 模式一致:分母 = delta 集,回归破坏
  单列不掺 ratio);
- 干净重放:新鲜 venv + 冻结 adaptation → 回归 + delta 双跑;
- 终局 verdict 沿 harness 现行词表(PASS = delta 全绿 ∧ 回归零破坏 ∧
  干净重放一致;新增 verdict 词一律不许 —— 台账与闸门读现行词表)。

Agent 全程禁网(与所有正式发次同一条铁律);联网只发生在已关的 D5 窗口。

---

## §4 公开面(已裁:A 案 · 盲攻同视野;2026-08-16 用户裁定)

- **模型可见** = 题面原文 + 交付树 + 依赖源码(deps venv)—— 与准入盲攻
  **逐项相同**;
- **公开反馈** = 回归套件(每轮跑,红了给 FailurePacket);delta 测试的
  存在、节点名、内容**全部隐藏**,终局才判。

裁定理由(记录在案):

- **效力**:准入盲攻数字(0/3、0/1、4/5)就是在这个视野下测的 —— 视野
  不变,上界继续有效;公开面加任何 delta 信息,上界作废,三题的判别力
  声明失去实测根据;
- **公平性**:题面是上游自己公开写的需求(不是我们藏了自己写的条件,
  与 h2 伏击不同型);隐藏的部分 = 多个合理设计间的选择,失败按 §6 归因
  字典单列 `DESIGN_MISMATCH`,措辞不得写成泛化能力缺陷;
- **代价(如实,批报必抄)**:模型对 delta 行为**零反馈**,修复循环只
  保护回归面;实验实质 = "单次设计承诺 + 多轮实现修复"。

未采行案(记录):B 案(公开 delta 节点名)因强制盲攻重测、池子缩水
风险(8042 的 `test_chained_pivots_mixed` 名字即泄"混合链")与工期
未采行;C 案(撰写验收摘要)违 D1 严口径、粒度不可冻结、必然泄答案,
未采行。

## §5 模型序(已裁:A 案 · GPT 双模型 pilot;2026-08-16 用户裁定)

- 模型:**gpt-5.5 + gpt-5.6**(现行通道);3 题 × 2 模型 × 1 发 =
  **6 发 pilot**;执行序内模型交替(防 provider 时段状态混入);
- **pilot 规则**(方案文档 §8.3,冻结):某题两模型**全部首发 PASS** →
  该题标 **Calibration**(可判但无区分度),不补发;有区分度(有 PASS
  有 FAIL)→ 该题补齐到每模型 n=3(全批补齐上限 +12 发);全 FAIL →
  不补,留给能力阶梯与 v3 素材;
- **DeepSeek 不进本批**:DQ 三 canary(单轮工具 / 多轮 reasoning
  passback / 长 observation)未建未过,"Canary 未 100% 不进任务
  benchmark"是方案文档 §6.4/§17 的红线。DeepSeek 另立 DQ 预注册;
- 未采行案(记录):B 案(纳入 DeepSeek)因 DQ 工期押后 HB 首批未采行;
  C 案(单模型探路)因缺模型间对照、N=3 null 分量弱未采行;
- **知识截止硬门**:受测每个模型的公开知识截止日期必须记录进批报,且
  早于三题最早 merge 日期(2026-06-01);无法确认截止的模型出局
  (post-cutoff 前提是本形态的存在理由)。

---

## §6 判据(先冻结,措辞此后不改)

### 主判据

- **J1 可判性**:每一发都产出 delta 节点级判定(收集不得中断;评分器
  拒测路径 B2/B7 触发 → 该发记 `HARNESS_FAILURE`,不计模型);
- **J2 存在性**:≥1 发 PASS(§3 三条合取)→ §1 的问题答"能";全 FAIL
  → 答"本批未见",如实入档(N=6 的 null 有分量,N=3 弱);
- **J3 归因字典**(每一发 FAIL 必须落且只落一类,出现"说不清"该发作废
  记 harness 缺陷):

| 类 | 定义 |
|---|---|
| `DESIGN_MISMATCH` | 交付完整、可跑、回归零破坏,delta 未全绿 —— 设计与上游验收分岔。**单列,不得写成泛化能力缺陷**;引用必须并排该题盲攻上界 |
| `IMPL_INCOMPLETE` | 交付不完整 / 不可跑 / 公开面(回归)未过 |
| `REGRESSION_BROKEN` | delta 有转绿但回归破坏 > 0 |
| `NO_SUBMISSION` | 预算内未提交 |
| `HARNESS_FAILURE` | 量具/管线故障(含 J1 拒测),不计模型 |
| `PROVIDER_FAILURE` | provider 侧故障,不计模型 |

- **J4 零泄漏**:发次工件与模型上下文里捞不出 delta 测试内容与答案 patch
  (发次前 `verify_sealed` + 剥离自证仍绿;发现泄漏 → 停批,该题判死)。

### 副判据(不阻断,必进批报)

- **J5 部分转绿**:每发记录 delta 转绿数 / delta 集(8042 尤其:哪个节点
  转了绿,与盲攻残差节点是否同一个);
- **J6 单薄档纪律**:click-3407 的数字只随档出现,不单独立论;
- **J7 回执/采纳类判据不适用声明**:本形态无上游采纳语义,U1–U4 不在场
  —— 批报不得把本批与 sidecar/adoption 形态的通过混排比较。

### 停批线(任一触发即停批不补发)

1. 连续 2 发 `HARNESS_FAILURE`;
2. 封存件摘要在批期间变化(`verify_sealed` 报被动过);
3. J4 泄漏;
4. 发现安全/判据缺陷(HB 铁律:不修完出新版不续跑,整批作废重预注册)。

## §7 发次分类(先写死,发完照此登记)

```
run_purpose: HELDOUT_MODEL_EVALUATION
test_mode: HB
task_seen: false
oracle_authorship: UPSTREAM_OWN_TEST_SUITE
counts_toward_model_capability: true
counts_toward_heldout_benchmark: true
counts_toward_mechanism_effect: false
counts_toward_profile_qualification: false
classification_timing: PRE_REGISTERED
host_id: click | sqlglot        # M60c:缺 host_id 不落账
```

台账效应(预告,防惊讶):heldout 分母第一次非零,`v2_gate.json` 的
"第二宿主未建,恒为 0"说明串由 `hosts_covered` 推导自动改写(K11 在验)。
task_id 前缀 `hb1-*`,不进 stages.T*(M60b 修后按分类字段,不按前缀)。

## §8 HB 冻结纪律(方案文档 §8.1,全文照办)

- harness / oracle 接线 / 任务包 / 契约:**本预注册定稿提交时的 HEAD 冻结**,
  批期间一字不动;
- **不根据模型失败改执行器**;失败只观察、只归因、只记录;
- 发现 safety/判据 bug → 整批作废,修完出新版重预注册;
- n 小不排名:批报只报 逐发判定 / delta 转绿 / 回归 / 归因类 / token 与
  轮次消耗;**不出现通过率、不出现模型排序**。

## §9 额度(冻结值,三题两模型全同 —— 同预算铁律)

```
semantics: per_round
max_rounds: 3
max_model_calls: 30
max_commands: 100
max_patch_files: 15
max_patch_lines: 1500
max_wall_time_minutes: 60
max_input_tokens_total: 600000
max_output_tokens_total: 80000
```

依据:实现 diff ≥30 行、单模块,规模与 sidecar 题同级;探索面更大
(sqlglot 全仓)但无依赖安装/浏览器开销。token 执法沿现行调用前投影
(#39)。**开跑后不改;要改 = 全模型同改 + 批作废 + 重预注册。**

## §10 前置条件(全绿才开跑,逐条勾)

- [x] 待裁 A/B 落定(2026-08-16 用户裁 A/A),本文定稿;冻结 = 本文
      提交之时(harness commit 记台账);
- [ ] **出题工程**:3 个任务包/契约从封存件生成(封存件只读引用,一个
      字节不动);delta 接线;干净重放路径通;
- [ ] **可搬运性审查**(#43)每题一次 —— 公开面按裁决 A 冻结后审:
      金丝雀/密度/工件结构类判据不得可搬运;
- [ ] **F0 电池**每题:正控(`--fake` 施 answer/full.patch → 必须 PASS:
      delta 全绿 + 回归零破坏 + 重放一致)+ 负控 ≥2(空提交 → FAIL;
      只破坏回归的 patch → `REGRESSION_BROKEN`)。首题全链兼任本形态
      实弹彩排,撞出的管线缺陷修完才进下一题;
- [ ] 变异闸门 100% + 全量测试绿 + `check_public_claims` 绿 + 红绿证据
      (新钉死随出题工程入册);
- [ ] `verify_sealed`:d5-hunt 封存件完好,数字与 admission-round2 一致;
- [ ] 受测模型知识截止核录(§5 尾注)。

## §11 跑法与成本封套

- 按 v3 协议 AI 代跑循环:循环前报计划(模型序/预算盒/成本封套/运行
  上限 = 计划数 × 2)经用户一句确认;harness 缺陷 → 停修(钉死 + 预注册
  附录)→ 复测该模型 → 继续;模型弱点只记录;
- pilot 段计划 6 发(A 案口径,B/C 案按裁决改写),运行上限 12;补齐段
  (若触发)另报计划再跑;
- 批报唯一事实源:`benchmarks/v2/reports/HB-PCDELTA-1-report-<date>.md`,
  数字只出脚本。
