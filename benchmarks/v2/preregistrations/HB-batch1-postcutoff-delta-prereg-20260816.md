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
- [x] **出题工程**:3 个任务包/契约由 `scripts/build_hb1_task_packages.py`
      唯一产出(封存池 `~/RepoProofArchive/d5-hunt` 零写);delta 接线为
      harness 自写驱动器 + 上游测试原文(判据内容 100% 上游,D1 严口径);
      干净重放路径通(F0 正控三题重放一致);
- [x] **可搬运性审查**(#43)每题一次 —— 判 **"有 blocking"**,两条零实现
      伪绿通道(根级 `sitecustomize.py` / 子目录 conftest 全局插件),
      已修完并落钉,详见**附录一第 9 条**;
- [x] **F0 电池**每题:正控(`--fake` 施 answer/full.patch → 必须 PASS:
      delta 全绿 + 回归零破坏 + 重放一致)+ 负控 **3**(惰性提交 →
      `IMPL_INCOMPLETE`;只破坏回归的 patch → `REGRESSION_BROKEN`;
      根级 sitecustomize 伪绿 → `INSTRUMENT_TAMPERED`,附录一第 9 条)。
      首题全链兼任本形态实弹彩排,撞出的管线缺陷修完才进下一题;
      **实测(批 `HB-PCDELTA1-F0-R2`,12 发,`hb_batch_criteria.py` 裁定)**:
      3581 `3/3 · 0/3 · 3/3 · 0/3`、3407 `1/1 · 0/1 · 1/1 · 0/1`、
      8042 `5/5 · 0/5 · 5/5 · 0/5`,四形态归因逐发对位,零例外;
      篡改负控三题均由 `GUARDED_FILE_MODIFIED:sitecustomize.py` 拦下
      (拦的是篡改,不是"没写实现")。
      **R3 重跑(附录一第 11 条修复后,批 `HB-PCDELTA1-F0-R3`,12 发)**:
      四形态判据落点与 R2 逐发一致,零例外;三题正控轮末读数与契约基线
      **逐字对齐**:3581 `passed=1588 / failed=0 / skipped=26`、3407
      `passed=1868 / failed=0 / skipped=25`、8042 `passed=1150 / failed=0
      / skipped=0`(R2 时 3581/3407 的 skip 被误记进 failed —— 判据不读
      该字段故落点未变,但轮内反馈通道是坏的);
- [x] 变异闸门 **195/195**(声明归因 195、未声明 0)+ 全量测试
      **906 passed / 20 skipped** + `check_public_claims` `{"ok": true}`
      + 红绿证据 `docs/evidence/redgreen/ba770705a0fe.txt` VERDICT VALID。
      **如实标注**:该红绿件的 RED 段是"驱动器文件在 base 上不存在"型的
      import 红,证的是"件是新的";**真正隔离本次缺陷的证据是变异闸门
      M72a-j** —— 它们把修复逐条变异掉,由声明的那条钉死当场抓住。
      **附录一第 11 条修复后重验**:变异闸门 **204/204**(+M73a-c、
      M74a-f,声明归因 204,证据 `docs/evidence/mutation_gate/
      b34c01d19e21.json`),全套件 exit=0,`check_public_claims`
      `{"ok": true}`;
- [x] `verify_sealed` 等效项:`prepare_hb1_hosts.py --hosts` 幂等复验,
      三宿主 host **verify-only 逐字节对得上**(139/152/354 条构造自证
      恰好相等,攻击者残迹留痕不变),封存池只读未动;**并附带证明 F0
      电池未污染 bench 宿主**(含篡改负控 —— 载荷只落会话副本);
      R3 电池后再次幂等复验,同样 verify-only 全绿;
- [x] 受测模型知识截止核录(§5 尾注):gpt-5.5 = **2025-12-01**、
      gpt-5.6 = **2026-02-16**(用户 2026-08-16 提供),双双早于三题
      merge 下界 2026-06-01 → **硬门通过,两模型均不出局**;
      明细见附录一第 10 条。**§10 七项全绿,可开跑。**

## §11 跑法与成本封套

- 按 v3 协议 AI 代跑循环:循环前报计划(模型序/预算盒/成本封套/运行
  上限 = 计划数 × 2)经用户一句确认;harness 缺陷 → 停修(钉死 + 预注册
  附录)→ 复测该模型 → 继续;模型弱点只记录;
- pilot 段计划 6 发(A 案口径,B/C 案按裁决改写),运行上限 12;补齐段
  (若触发)另报计划再跑;
- 批报唯一事实源:`benchmarks/v2/reports/HB-PCDELTA-1-report-<date>.md`,
  数字只出脚本。

---

## 附录一(2026-08-16,出题工程侦察后;正文一字不动,判据 J1–J7 与停批线未触碰)

1. **测量协议统一 pytest**。§3 表格"钦定跑法 click=pytest / sqlglot=
   `python -m unittest`"一行按此读:发次侧公开面/回归/隐藏 delta 判定
   **全部走 pytest**(pytest 原生收集 unittest 用例)。依据:冻结的 delta
   节点 ID(`docs/evidence/d5_hunt/hygiene/*.json`)与全部准入基线数字均为
   pytest 形态产出;`python -m unittest` 仅是 v2 卫生判据 120s 计时线的
   测量出处,不是发次协议。
2. **harness 冻结点语义**。§8"本预注册定稿提交时的 HEAD"按 PQ 先例
   (修订 A/B)读:出题工程必然新增任务包与接线代码,**开跑前**的修订
   允许且逐条留痕(本附录 + 状态条目);冻结自**报计划开跑**那一刻的
   HEAD 起绝对生效,批期间一字不动。判据措辞(§6)自初版起未改。
3. **§7 分类块补显式声明**:`host_modification_mode: PRISTINE`(交付树
   = 盲攻 delivery 树逐字节,零挖空零改动)。台账联判代码里 PRISTINE 在
   放行集,此前靠缺省值通过,现改为显式写。
4. **§4"delta 测试的存在…隐藏"的语义澄清**:指工作区与可见面不含任何
   delta 试件线索(文件/节点名/内容),**不指**向模型隐瞒"存在隐藏验收"
   这一事实 —— 契约与提示明说"验收由上游同 PR 自带的隐藏测试判定,
   回归须全绿"(先教后杀:验收语义类别公开,验收实例隐藏)。盲攻者
   同样知道此协议(method.txt 在案),视野等价不破。
5. **sqlglot-8042 泄漏扫描补跑入 §10 前置**:`leak-scan-round2.json` 仅
   含两条 click 记录,8042 的 method.txt 所称扫描查无记录 —— 补跑剥离
   自证并落盘,绿了才算 J4 前置满足。
6. **负控"空提交"的实现形态**:采用**惰性提交**(patch 只创建一个与题
   无关的标记文件)而非零字节 patch —— 零字节 patch 会撞 harness 冻结/
   重放边界,产生与判据无关的 HARNESS_FAILURE 噪声;惰性提交同样满足
   "不解题的提交必 FAIL"的负控语义(delta 全红)。控制组 docstring 逐条
   声明期望红点。
7. **交付树的权威来源更正**(部署自证抓出,2026-08-16):封存的
   `attacks/<id>/delivery` 实为**盲攻者的提交终态树**(含攻击者自笔的
   实现尝试,3581 的 decorators.py 内有完整攻击件),不是给攻击者的输入。
   照它部署会把失败攻击连同交付给受测模型(8042 等于站在 4/5 起跑)。
   **交付树 := 盲攻输入视野重构 V** —— 路径集 = delivery ∩ parent_tree
   (剔除攻击者新建),内容一律取 parent_tree 版;两条交叉验证:V 路径集
   须恰等于 parent − `.github/**` − manifest.test_files(8042 另减
   CHANGELOG.md),且 delivery 与 V 的全部差异逐条归因为攻击者自笔
   (`attacker_residue` 留痕)。泄漏扫描按 round2 自校准法(parent 已有
   指纹剔除)后须零命中。受污染树上的首轮基线测量作废,重构后重测。
   **字节码条款**(交叉验证绊线首触发,2026-08-16):两条推导双双剔除
   `__pycache__/**` 与 `*.pyc`,V 一律不含字节码 —— 被剥测试文件的
   parent 侧 .pyc 是指向隐藏 oracle 的结构性箭头且可反编译;攻击者实际
   视野本就无字节码,会话快照排除清单亦同向。
8. **量具面守卫入契约公开面**(先教后杀):隐藏 oracle 起跑时核验
   tests/ 子树与根级 pytest 扩展点(conftest.py、pyproject.toml、
   setup.cfg、setup.py、pytest.ini、tox.ini)与出题态逐字节一致 ——
   守的不只是改测试,还有"根 conftest 猴补丁致全套件假绿"这条伪造路。
   这些路径在契约 forbidden 与提示里**先教**,教了才有资格杀;判红归
   attribution=agent,reason=TESTS_TREE_MODIFIED/GUARDED_FILE_MODIFIED,
   J3 归因落**附录新增类 `INSTRUMENT_TAMPERED`**(attribution=agent)。
   它不落 §6 六类任何一格,也不触发"说不清作废"条款 —— 该条款针对的是
   harness 说不清,而量具面被动是说得清的攻击形态;契约
   `failure_taxonomy_expected` 已声明此类(先教后杀闭环)。
9. **可搬运性审查(#43)判定"有 blocking",两条零实现伪绿通道已封堵**
   (2026-08-16,§10 第 3 项的产出;**发生在任何计分发次之前**)。

   审查方(只读、独立)实测:零实现即可把真红的隐藏 delta 测试压成
   `1 passed`,且过干净重放与 J4 零泄漏检。两条通道互相独立:

   - **[1a] 宿主根级 `sitecustomize.py`**(三题全中)。外层 `_run_oracle`
     给判卷进程注 `PYTHONPATH=<宿主根>`,判卷子进程继承后,宿主根在
     **site 处理期**上 `sys.path` —— 解释器一启动就自动 import 它,先于
     pytest 的一切配置,连 H1 守卫自己都在被污染的解释器里跑。该文件不在
     附录第 8 条的守卫清单里,受追踪、进适配补丁、过重放。
   - **[1b] 子目录 `conftest.py` 伪造全局插件**(仅 sqlglot-8042)。
     `pytest_configure` + `config.pluginmanager.register()` 注册的插件是
     **全局作用域**,不受目录过滤约束;8042 无 `testpaths` 且判卷跑裸
     `pytest` 收整棵树,于是任何新建目录 + 一个 conftest + 一个占位测试
     即可入场。click 两题恰因 `testpaths=["tests"]` 幸免 —— **是运气,
     不是设计**。

   **根因**(与 #43 论点同型):附录第 8 条的守卫清单编码了"pytest 代码
   执行面 = tests/ + 6 个根文件"这一**宿主局部假设**,首宿主上成立,换到
   上游树后静默失去覆盖。守卫面与执行面脱钩,是可搬运性缺陷的一般形。

   **修复**(两道互不依赖的独立防线 + 三处归因/纪律修正):
   - 守卫扩面:第 8 条清单增 `sitecustomize.py` / `usercustomize.py`,
     出题态 `ABSENT` 亦逐字节钉死(三题出题态均 ABSENT,已入 manifest);
   - env 净化:判卷子进程剥 `PYTHONPATH`/`PYTHONSTARTUP` +
     `PYTHONNOUSERSITE=1`;外层由契约新字段 `host.oracle_env_sanitized`
     控制,**缺省 false** → OfferClaw 等既有宿主行为逐字节不变;
   - 收集面限定:判卷改跑 `pytest <tests_subdir>`,且守卫子树与收集子树
     同取 `manifest["tests_subdir"]` **单一来源** —— 消除"守 A 收 B";
   - 归因修正:`LAY_TARGET_OCCUPIED`(agent 在剥离路径上写同名文件)由 h0
     改挂 h1。原先 h0 优先级更高,agent 篡改反被记成 `HARNESS_FAILURE`;
   - **`SUITE_TIMEOUT` 自 `HARNESS_FAILURE` 单列成一类且不入连败计数**
     (§6 停批线 1 的加固):agent 代码能拖慢套件,超时若记 harness 连败,
     受测方蓄意拖慢即可把整批停掉 —— 判据不许可被受测方操纵。处置:
     一次重跑,复发按模型侧 FAIL 人工裁定;
   - **负控三 `nc_instrument_tamper`** 进 §10 F0 电池(每题负控由 ≥2 增至
     3):[1a] 攻击载荷原样复现(零实现 + 真伪造,非空壳),期望 J3 落
     `INSTRUMENT_TAMPERED` 而非 `IMPL_INCOMPLETE` —— 证明拦下的是篡改,
     不是"没写实现"。该载荷不含答案,故入 git(证据可见)。

   **为什么不是"整批作废、出新版重预注册"**(§6 停批线 4):停批线 4 的
   适用面是**批期间**发现判据缺陷 —— 那时已有发次按错判据计过分,故须
   作废重来。本次由 §10 前置的第 3 项(可搬运性审查)在**开跑前**抓出,
   正是该前置存在的目的;此刻计分发次数 = 0,无任何数据需要作废,冻结
   (附录第 2 条:自"报计划开跑"那一刻的 HEAD 起绝对生效)尚未起算。
   两项用户裁决(公开面 A / 模型序 A)与 §6 判据主文均未触碰,故无需
   重新裁决。按附录第 2 条留痕,不另起版本号。**若用户认为应从严按
   停批线 4 出新版文书,以用户裁定为准。**

   **自证**:U9/U9b/U10/U11 分别单考守卫、env 净化、收集限定、守收同源;
   G8c/G8d 钉分支行为与接线(**不读源码文本** —— 首版 g8c 断言源码含
   `oracle_env_sanitized`,而该词在注释里也有,被 M72f 当场逃逸);P4b 钉
   manifest 守卫面与子树字段;V12b 钉 selftest **真去遍历**合成表(表在
   ≠ 考了,M72h 逃逸);P5b 钉盘上件逐字节等于生成器常量(M72i 逃逸);
   V13 钉超时单列。变异闸门 +10 条(M72a-j)逐条声明归因,**195/195**。
   修复后 F0 电池三题全量重跑,12 发四形态零例外(见 §10)。

   **用户裁定(2026-08-16)**:本条按**附录制留痕,不另起版本号** ——
   停批线 4 的适用面是批期间发现缺陷,本次由 §10 前置在开跑前抓出,
   计分发次数 = 0,无数据需作废。
10. **pilot 开跑方式(用户裁定 2026-08-16):先跑第 1 发再报**。§11 的
   "循环前报计划经用户一句确认"按此执行:计划整体已报并获裁,但**先只
   执行执行序第 1 发**(click-3581 × gpt-5.5),把首发全链实况(轨迹 /
   判据落点 / 成本)报给用户,由用户决定余下 5 发是否照序续跑。
   执行序(模型交替,防 provider 时段状态与模型对齐):

   | 序 | 任务 | 模型 | 准入盲攻上界 |
   |---|---|---|---|
   | 1 | click-3581 | gpt-5.5 | 0/3 |
   | 2 | click-3581 | gpt-5.6 | 0/3 |
   | 3 | click-3407 | gpt-5.6 | 0/1 |
   | 4 | click-3407 | gpt-5.5 | 0/1 |
   | 5 | sqlglot-8042 | gpt-5.5 | 4/5 |
   | 6 | sqlglot-8042 | gpt-5.6 | 4/5 |

   成本封套:6 发 ≤ 3.6M 读入 / ≤ 480K 产出 / ≤ 6 小时墙钟;运行上限
   12(计划数 × 2)。**harness 冻结自首发开跑那一刻的 HEAD 起生效。**

   **知识截止硬门的落实方式(用户裁定)**:两个受测模型的公开知识截止
   日期**由用户直接提供**,原样记入本附录与批报,核对早于 2026-06-01
   后方可开跑。**日期未到手之前,任何计分发次不得起跑。**

   **核录结果(用户 2026-08-16 提供,原样记录)**:

   | 模型 | 公开知识截止 | 早于 2026-06-01 | 距最早 merge 余量 |
   |---|---|---|---|
   | gpt-5.5 | 2025-12-01 | ✅ | ≥ 6 个月 |
   | gpt-5.6 | 2026-02-16 | ✅ | ≥ 3.5 个月 |

   两者均早于三题 merge 日期下界 2026-06-01(该下界由猎取普查的 GitHub
   API 查询条件 `merged>=2026-06-01` 保证,见 hunt 预注册 §判据 1)。
   **§5 知识截止硬门通过,两模型均不出局。**
   记忆通道前提(delta 合并于知识截止之后 → 权重里不可能有)成立。
11. **首发中止并停修:量具三分法塌陷(skipped 被当成 failed)**。按 §11
   "harness 缺陷 → 停修(钉死 + 预注册附录)→ 复测该模型 → 继续"归档。

   **发现现场**:执行序第 1 发(click-3581 × gpt-5.5,run
   `hb1-click-3581-20260816-174209`)第 1 轮轮末读数
   `public_passed=1588 / public_failed=26 / regression_passed=1588 /
   regression_failed=0`。**同一棵树、同一套件,公开面报 26 红而回归面报
   0 红**;契约基线原文即 `1588 passed, 26 skipped, 0 failed`。

   **真因**(`src/repoproof/runner/host_guided.py` 轮内统计):
   `failed_nodes = [n for n in nodes if n["outcome"] != "passed"]` ——
   `skipped` 不是 `"passed"`,于是 26 个 Windows-only 用例(macOS 上恒
   skip)被计成失败,经 `build_failure_packets` 变成 **26 个凭空捏造的
   `FailurePacket`** 喂回模型(要求其"修正 `getchar windows[True-h]`
   的断言语义适配"—— 在 macOS 上无从修起)。第 1 轮 30 次模型调用打满
   `LimitsExceeded`,第 2 轮开局仍 26 包、退出 `TokenBudgetExhausted`。
   **受测模型的真实预算被本 harness 引去追不存在的失败**,故该发不是
   对模型的有效测量。

   **处置**:当场中止(`pkill`),**无 `report.json`、未入 `runs.jsonl`、
   成本封套不计**,记录未被污染;修复后**从零重跑第 1 发**。

   **为什么第一宿主没炸(可搬运性,#43 同科第三例)**:OfferClaw 的公开面
   是手写 `public_tests/`,公开面 skip 数 = 0,故 `!= "passed"` 恒等于
   `== "failed"`;HB 的公开面**就是上游自带回归套件**(3581 = 26 skip /
   3407 = 25 skip),假设静默失效。与本日两条 blocking(根 `sitecustomize`、
   子目录 `conftest` 全局插件)同一病理:**首宿主上成立的隐含前提,换棵
   上游树即失效,且失效时不报错、只出错数**。

   **修复**:公开面轮内改为 passed / failed / **skipped 三分**,skipped
   两边都不沾;并把 `public_skipped` 记入 `RepairRoundRecord` 与
   `repair.round.end` trace —— **排除但不静默丢弃**,否则"跳过数暴涨"
   (把失败用例改成 skip)将从证据里消失,等于把刚拆的洞换个地方开。
   `public_skipped` 取 `int | None`,默认 `None` = 未测量,**不追溯改写
   旧发次读数**。

   **不开新洞的依据**:制造一个 skip 必须改 `tests/` 或根 `conftest.py`,
   二者均已在契约 `forbidden` 中**先教**,且被 H1 逐字节守卫与
   `tampered_public_tests` 双杀 —— 排除 skipped 不给受测方任何新手段。

   **自证**:钉死 G9a(三分法:skipped 既不入 passed 也不入 failed)、
   G9b(不为 skip 捏造 `FailurePacket`)、G9c(跳过数留痕入轮记录);
   变异 +3(M73a-c),其中 M73b 钉的是**另一侧塌陷** —— 把 skip 洗成
   passed 让跳过冒充通过。全套件 909 绿。

   **同病扫查(不止修被撞到的那一处)**:按 `outcome` 判别式全仓扫查,
   另找到两处同科:

   - **v1 修复路(`guided_repair.py` 轮内)**同式同病。两条修复路现共用
     `verification/junit.py::split_public_outcomes` **单一口径**(带
     `PublicOutcomes.skipped` 计数),不留两份拷贝;
   - **负控电池(`controls_battery.py`)是反方向的同一个病**:原式把
     "非 passed"一律记作失败,于是一个因平台标记 / 导入失败而**被跳过**
     的必红用例会冒充 `FAILED_AS_EXPECTED` —— 该负控这一轮**根本没考**,
     却发了一张"已验证"的证书。这比首发那条更危险:首发那条制造噪声,
     这条制造**没有验证过的信心**。改为必须真红(`failed`/`error`),
     必红用例被跳过时单列判词 `MUST_FAIL_NODE_SKIPPED:[...]`,既不算
     合格也不混进 `NOT_REJECTED`(病名要说出口)。

   **审过但明确不改的一处**:`baseline.py::_junit_failed` 同样用
   `!= "passed"`,但它跑的是 **harness 自己手写的 oracle**
   (`test_capability.py` / `test_regression.py`),那里出现任何 skip 都
   意味着 oracle 没干活,记作不通过正是应有的 fail-closed 语义 —— 与
   "上游套件的平台性 skip"不是一回事,故不动。

   **钉法**:接线钉用 **AST** 而非源码字符串(M72f 的教训:文本断言会被
   注释里的同名词喂饱)—— 断言两条修复路**都调**共享函数、且 AST 里
   **不再存在** `!= "passed"` 这条比较式。变异 +6(M74a-f),含"共享函数
   还在、调用点已旁路"这一最易滑回的形态。

   **对既有证据的影响**:§10 F0 电池 12 发的判据落点不受影响(判定走
   `passed` / 回归面 / policy,不读 `public_failed`),但**电池在修复后
   的 HEAD 上全量重跑**以保证"冻结的 harness"与"跑过电池的 harness"
   逐字节同一;结论见 §10(R3:落点与 R2 逐发一致,正控读数与契约基线
   逐字对齐,宿主复验 verify-only 全绿)。**首发从零重跑自修复后 HEAD
   起算,harness 冻结点随之重立。**
