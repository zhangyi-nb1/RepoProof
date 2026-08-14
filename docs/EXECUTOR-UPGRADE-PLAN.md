# 执行侧升级计划(E 代际)——DeepSeek Harness 分析报告 × 本仓现状(2026-08-14)

来源:`~/Downloads/deepseek_harness_repoproof_report.md`(对旧快照 `98f98f7`
写的静态审查)。本文是它与**盘上当前状态**的逐条对照与落地方案。
执行路线:**先在 GPT 系模型上做执行侧改造并验证成效,DeepSeek 系后置**
(用户 2026-08-14 决定)。

报告的中心判断本仓采纳:**验证侧已比通用 Agent 项目严谨,执行侧仍薄** ——
通用 provider 适配、非持久单 Bash、完整历史重发、弱工作状态,会放大一切
模型在复杂任务上的缺陷。改造原则也采纳:**外层裁决不动,只换内层执行器;
执行器可替换,裁决器必须独立**。

---

## §0 报告核对表:哪些断言已过时(先核盘,再动手)

报告写于 `98f98f7` 快照。以下断言**已被本仓修掉**,不得重复立项:

| 报告断言 | 报告定级 | 盘上现状(2026-08-14 逐条核实) |
|---|---|---|
| "token 预算是事后计量,0.41% 越界事后才发现"(§14.7/§38) | P0 | **已修**:`token_budget.py` 调用前投影(`used + projected > limit` 即拒发),输出侧 `max_tokens_request_cap`。LESSONS #39,`d9d676d`。批 12/13 **两次现场兑现**:四发全部贴到 95%+ 停线内,零越界。剩一半未验:"投影不过度保守以致误杀"(批 12 诚实边界原文) |
| "隐藏门禁要求公开规范未定义的条件(h2 并发)"(§24) | P0 | **已修**:T2v5 增 R15/R16 + 公开用例(#33 先教后杀);T3v6 增 R12 可验证形式。**但批 13 补了一课**:教之前先审判据可伪造性 —— 教一条可伪造的判据等于发蓝图(LESSONS #43 坑五) |
| "preflight 只验一次简单工具调用"(§14.5) | P0 | **部分过时**:`scripts/model_preflight.py`(Gate 3B.F)做 2 次调用的 micro-run + usage 记账 + 轨迹密钥泄漏扫描。但它是**手动脚本**,未纳入 host-run 强制门;字段面确实窄(见 §3-S1) |
| "预算固定 20 次调用"(§25) | P1 | 过时:v2 任务 36(T2)/45(T3)次,每轮重置 |
| "68 runs / 9 passes"(§13.2) | — | 现 74 runs;有效 T1 2 / T2 5 / T3 3,invalidated 5(裁定走旁挂) |
| "task/harness/model 失败要分开统计"(§0.3) | P0 | **已做**:adjudications.jsonl 旁挂裁定 + batch_criteria.py 机器判 + 批报三分归因(批 10 起) |

以下断言**仍然准确**,是本计划的主体:

| 报告断言 | 报告定级 | 盘上验证 |
|---|---|---|
| 完整历史重发 → 输入平方膨胀(§21/§33) | **P0,高置信** | `repoproof_env.py:41` 注释原文承认;实测:T2v5 单轮吃到 547k/600k(91%),T3 每一发 r1 都撞 800k 线(759k–776k),T3 两轮总输入 0.95M–1.33M。`clip_observation` 只截单条,不去重复 |
| 每条命令新 shell,状态不连续(§22) | P1 | `repoproof_env.py` 每 action 独立执行,cwd 每次传参,env 不延续 |
| 无结构化编辑器(§22) | P1 | 属实,唯一动作协议是 bash |
| coverage_ledger 实验性、模型自报、可忽略(§23) | P1 | 文件头自述 "STATUS: experimental, default OFF" |
| provider hash 字段不足以复现语义(§14.6/§54) | P1 | `provider_config_hash` 存在,但 sampling 只有 temperature,无 tool schema hash / 上下文策略指纹 |
| 无重复调用治理(§40) | P2 | 属实 |
| DeepSeek 原生协议未验(§19/§31/§32) | P0(DS 侧) | 属实,**按用户决定后置到 P-D 阶段**(§6) |

---

## §1 逐条采纳判定

**A 类·已完成,不再立项**:调用前预算(#39)、先教后杀(#33 已在 T2v5/T3v6
落地)、三分归因、n<3 不排名、预注册纪律、闸门数字只出脚本。

**B 类·GPT 阶段采纳(本计划 §3)**:

| 报告条目 | 本仓落点 | 步骤 |
|---|---|---|
| §33 事件日志与模型视图分离、spill、确定性 prune | `repoproof_env.py` + 新 `context_projector.py` | S2 |
| §34 持久 Bash(显式重建式,方案 2) | `repoproof_env.py` | S3 |
| §40 重复调用提醒(确定性,非 LLM 判) | `repoproof_env.py` | S3 |
| §35 受限结构化编辑器 | 新工具 + 策略 | S4 |
| §33.3 contract capsule | task prompt 结构化 | S5 |
| §36 harness-owned requirement state board | 新 `requirement_state.py` | S5 |
| §37 单 Agent 阶段机(轮内) | backend 提示协议 | S6(最后,可选) |
| §54 profile hash 拆分(provider/tool/context/budget) | run manifest | S1 |
| §32 preflight 升格为强制门 + 长观测 canary | `model_preflight.py` → host-run | S1 |
| §50.3 Wilson 区间进批报 | `batch_criteria.py`/批报 | S0 |

**C 类·DeepSeek 阶段(P-D,见 §6)**:deepseek-native 适配器、reasoning
passback canary、thinking/effort/采样消融(报告 §31/§32/§45/§55)、DSH
minimal bridge(§30 方案 B)。

**D 类·明确不做**(报告 §61–66 与本仓纪律一致,新增两条本仓特有):
多 Agent / critic;只加 prompt 长度;**修上下文之前不提任何预算**(§63,
与 #39 纪律叠加:改预算=全模型同改+批作废+重预注册);为通过率弱化隐藏
验证;DSH standard 全能力;把官方 Flash 参数当 Pro 的答案。本仓补充:
**教判据前先过可搬运性审查**(#43:金丝雀/密度/工件结构全可搬运,锚只能
是 harness 侧独立观测或"做不了"的能力);**优先用真实发次做负控**,别自造。

---

## §1.5 本计划在测试模式体系中的位置(2026-08-14 补,读本文前先读这条)

模式体系见 `docs/testplans/TESTPLAN-V2-OFFERCLAW.md` §11。本计划覆盖
**F0 / E0 / E1** 三个模式,P-D 段属 **DQ**。三条由模式体系带来的修正:

1. **S0 属 E0,S1–S6 每步先过 F0**(fake-scripted 正控 + 控制组 + 变异),
   再进 E1 消融批 —— "测模型之前先排除 harness 自身 bug"。
2. **E1 的结论只能是机制结论,不能是模型能力结论**。T2v5 是开发套件
   (已用于 oracle 开发,继续在其上优化会过拟合),故 E1 批报**不得**写成
   "某模型变强了";要谈能力必须换未见任务(WH/HB,需第二宿主)。
3. **本计划的 T 轨(§4)属 AR 模式**,其结果不计模型表现 —— 批 13 因此
   不构成对 gpt-5.6 的能力判断,只构成对判据的判断。

## §2 E 代际与可比性规则(改执行器 = 改被测系统,先立规矩)

- **E0** = 当前执行器(mini-swe 全历史重发 + 非持久 bash + clip)。
  批 1–13 全部数据属 E0。
- **E1** = E0 + S2(投影/spill/prune)± S3/S4(按消融格子)。
- **规则 1**:E0 与 E1 的发次**永不互比**;E1 起新批次系列,预注册里写明
  `exec_generation`。
- **规则 2**:执行侧指纹 = `src/repoproof/**` 的内容哈希(发次路径上的
  唯一代码面;scripts/ 里的闸门工具不在路径上,已核:`build_control_tree`
  `mutation_gate` 变动不影响发次)。S1 把它落成 run manifest 字段
  `exec_fingerprint`。已核:**0d35856..HEAD 的 src/ 逐字节相同**,故批 11
  的 T2v5 格子可在 HEAD 直接补到 n=3,仍算同一 E0 格。
- **规则 3**:每个 E1 特性上线前照旧走完整流程:冻结判据 → 红绿证据 →
  变异条目 → (行为改动)fake-scripted 正控冒烟在 E1 下必须先绿。
- **规则 4**:消融车辆固定 **T2v5**(最快,~10 分钟/发;T3v6 的 h7 在批 13
  被裁定"修好前不得再发批",T3 暂不做消融车辆)。
- **规则 5**:任务包在整个 E 系消融期间**一字不动**(§39:把任务改简单
  = 基准过拟合)。

---

## §3 分步计划(每步:改什么 / 判据先冻结 / 怎么验 / 产出)

### S0 基线测量(不改任何行为;先有数,后动刀)

**做什么**:新建 `scripts/exec_metrics.py`,从**现有** run bundle 的
`trajectory_round*.json`(已核:逐消息全量在盘,25 对 assistant/tool +
usage 可得)计算:

1. 逐调用输入构成:第 k 次调用的输入 ≈ 前缀消息和(全历史重发下可精确
   重构),输出"重复输入占累计输入的比例";
2. 整文件读次数(observation > 20k 字符的 cat/sed 全文形态);
3. 规范化重复命令数(同命令+同 cwd 出现 ≥3 次);
4. 每调用输入 token 中位数 / P95 / 累计(与台账 `input_tokens` 对账,
   偏差 >10% 要解释)。

对象:orders 64–69 全部 6 个 bundle。**数字只出自本脚本**,填进 §5 基线表。

**判据(冻结)**:M1 重构的累计输入与台账实测偏差 ≤10%;M2 报告的每一个
指标都能指回 bundle 内的具体消息序号(可复核)。
**验**:`.venv/bin/python scripts/exec_metrics.py --runs runs/t2-*v5-2026* runs/t3-*v6-*`
输出 JSON 落 `docs/evidence/exec_metrics/`。
**顺带**:`batch_criteria.py` 或批报模板加 Wilson 区间函数(n≥3 格子用)。

### S1 归因基建(**2026-08-14 已完成**)

落地:`src/repoproof/agents/profiles.py` + `host_guided._exec_profile_fields()`
+ 台账 5 个新字段。11 条钉死(判据 P1–P4 见 `tests/test_exec_profiles.py`)、
红绿 **VALID**(`docs/evidence/redgreen/91da6138a70a.txt`)、变异 **72/72**。

**与原计划的三处偏差(都有理由,记在此)**:

1. **"preflight 升格为强制门"—— 核盘发现它早就是强制门**
   (`run_host_guided_cli`:`if not pf.ready: return blocked` + 零模型调用)。
   不重做,改为**钉死防回归**(`test_preflight_failure_blocks_the_run`)。
2. **长观测 canary —— 不做,推到 P-D**。理由是 S0 给了更强的证据:6 发
   227 次调用的 usage 记账**精确相等(0.00%)**,真实规模的实测比合成
   canary 更有说服力。它的独特价值只在**未知 provider**上,那正是 P-D
   Canary 3 的位置。为一件已被真实数据证实的事每发烧 ~12k token,不值。
3. **代际标签改为从内容推导**(原计划只说"记 exec_generation")。手填标签
   会漂移 —— 上了 spill 却忘了改,E0/E1 数据就混池了。现在
   `exec_generation()` 从 context/tool profile 的实际取值推出 `E0` /
   `E1-S2` / `E1-S2+S4` …,并有钉死执法。

**顺带修的一处钉死退化**:变异闸门抓到 M42e 逃逸 —— C5 改动让
`verify()` 先做挂载发现,该钉死的合成控制组没有 `def mount_*`,于是在到达
逐字节比对**之前**就 SystemExit,用例仍绿但**绿的理由变了**。合成数据补上
挂载函数后复现:掏空比对必红。这正是变异闸门存在的意义。

**已知缺口(记录,不在 S1 内修)**:`--fake positive` 冒烟脚本写死了 T1 的
控制组文件名(`sdk_mcp.py` / `mount_sdk_mcp` / fastapi-mcp 钉版),对 T2/T3
不可用。S1 的 F0 验证改用 `--fake noop` 完成(字段端到端落地已确认)。

<details><summary>原计划正文(保留备查)</summary>

#### S1 归因基建:profile hash 拆分 + preflight 升格(非行为改动,先行)

**做什么**:
1. run manifest 增四个指纹:`provider_profile_hash`(现 provider_config_sha256
   扩字段:sampling 全量、action protocol、adapter 版本)、`tool_profile_hash`
   (工具集 + schema 顺序)、`context_profile_hash`(投影策略 id + 参数;
   E0 记 `full-history-clip@<obs_cap>`)、`exec_fingerprint`(§2 规则 2)。
   台账新增字段只增不改,旧行不动。
2. `model_preflight.py` 纳入 host-run 强制前置(有缓存:同
   provider_profile_hash 当日结果可复用),并加**长观测 canary**:一条
   受控 50k 字符工具输出,断言 usage 记账、无未知截断。
   (reasoning passback canary 属 DS 语义,留在 P-D。)

**判据(冻结)**:P1 同一配置两次 preflight 的四个 hash 逐字节相同;
P2 host-run 在 preflight 缺失/失败时拒开(拒开理由独立,不与 H9-a 混);
P3 长观测 canary 在 E0 下通过(它测的是记账不是投影)。
**验**:钉死 + 变异条目照常;跑一发 fake-scripted 冒烟确认台账新字段落地。

</details>

### S2 上下文治理第一刀:spill + 确定性 prune(E1 的定义性改动)

**做什么**(报告 §33,砍到最小可归因集):
1. **spill**:observation 超阈值(起点 8k token 级,实验值不写死)→ 全文
   落 run 目录 artifact,模型只见 头 N 行 + 尾 M 行 + `artifact_id` +
   "用 `sed -n 'a,bp' <artifact>` 可回读"提示。替换现 clip(clip 只截不
   留回读路径,被截中段不可恢复 —— 报告 §14.4 指出的正是这个)。
2. **确定性 prune**(不动用模型总结,零随机):对**历史**消息,(a) 重复
   成功且零输出的命令折叠为一行;(b) 同一文件的旧版全文读被新版覆盖时,
   旧条替换为"已被消息 #k 覆盖 + artifact 引用";(c) 相同命令+相同输出的
   重复对折叠。完整原文永在 trace/artifact,**只改模型视图**。
3. trace 增 `projection.applied` 事件:每次调用记录被折叠的消息号区间与
   节省的估计 token —— 证据链不断。

**明确不做**(第一刀内):模型生成的受控摘要(§33.6)、contract capsule
(挪 S5)、DS reasoning 特殊处理(P-D)。

**判据(冻结,反例先行)**:
- C1 **正确性**:fake-scripted 正控在 E1 下公开+隐藏全绿(冒烟);
  T2v5 正控树五物验证结论与 E0 完全一致。
- C2 **无信息害**:prune 只许折叠(a)(b)(c) 三型;折叠必须留可回读引用。
  反例:clip 截掉中段后模型无法回读 —— E1 不许再有"不可回读的丢失"。
- C3 **有效性**:S0 基线上重复输入占比显著下降(方向性判据,具体数出
  脚本;不预设百分比,防事后挪门槛)。
- C4 **证据完整**:重放/审计用的 trace 与 artifact 全量不减;
  `projection.applied` 可逐条对回。

**验(消融批,预注册后跑)**:
- 格子:T2v5 × {gpt-5.5, gpt-5.6} × {E0, E1-S2} × n=3。
- E0 格现有 n=1(orders 64/65),**在 HEAD 补 2 发/模型**(§2 规则 2 已核
  可比)——这四发同时补掉批 11 欠的 S1 稳定性数据,一石二鸟。
- E1 格 6 发。共 10 发新增,~2h 机时。
- 判读:主看 C3(重复输入占比、累计输入、预算余量)与 verdict 分布不劣化;
  Wilson 区间入批报;n=3 只报区间不下强结论。

### S3 持久 shell(显式重建式)+ 重复调用提醒

**做什么**:
1. 报告 §34 的**方案 2**(harness 显式保存 cwd/env-allowlist,每次执行时
  重建;不养常驻 worker——确定性优先,也符合"策略逐动作执法"红线)。
  trace 逐动作记 `cwd_before/after`、env delta。
2. §40 重复调用提醒:同规范化命令第 3 次 → observation 头部加一行提醒;
  第 5 次 → 要求说明新信息目标;第 8 次 → 拒执行(policy denied,走 #33
  已有的 denied-not-scored 通道,**不扣分**)。纯确定性实现。

**判据(冻结)**:B1 `cd` 后下一动作的默认 cwd 已变(钉死);B2 提醒/拒执
的阈值行为可红绿复现;B3 拒执行走 denied 通道且 `policy_violations` 不增
(批 7 Q1 判据复用)。
**验**:消融格 T0(E1-S2)vs T1(+S3),n=3 × 双模型;主看重复命令数、
路径错误型失败、每任务命令数。

### S4 受限结构化编辑器(str_replace 型)

**做什么**:报告 §35。新动作 `edit`:查看行范围 / 唯一匹配替换 / 应用
unified diff / 新建文件;仅限 adaptation 可写区;多处匹配即拒;symlink
逃逸拒;每次修改回传局部 diff。策略与预算照常逐动作执法。

**判据(冻结)**:E1 越界路径拒(复用 H9 系判据组);E2 模糊匹配拒;
E3 每次 edit 的 diff 进 trace。
**验**:消融格 T1 vs T2(+editor);主看编辑失败率、整文件读次数、
patch 质量(逐字节 diff 审查抽样)。

### S5 contract capsule + 需求状态板(harness-owned)

**做什么**:
1. **capsule**(§33.3):从冻结契约生成带 hash 的不可变摘要(目标/必须
   采用的上游/禁止替代/交付路径/预算摘要),固定进每次调用前缀;全文以
   artifact 引用可回读。
2. **状态板**(§36):从 R1–Rn 自动生成,状态机
   `UNKNOWN → ATTEMPTED → EVIDENCED / FAILED → STALE`,**只由公开证据
   更新**(公开测试结果、diff 路径、导入探针);模型可读不可写;修改相关
   文件后旧证据自动置 STALE。`coverage_ledger` 改名 `agent_claimed_coverage`
   降级为模型自述,与状态板并列展示、不一致时以公开证据为准(§53.9)。

**先过 #43 审查(这一步的特殊风险)**:状态板会把"哪些需求还没做"喂给
模型 —— 这正是 #33 要的"教"。但批 13 的教训适用:板上每一条的
public_evidence 探针必须先过**可搬运性审查**(探针不得绑在被测系统可提供
的名字上)。审查记录随判据一起冻结。

**判据(冻结)**:R1 状态只能由列名探针更新(钉死:模型写"我完成了"不
改变状态);R2 STALE 触发正确(改文件后旧证据失效);R3 隐藏面结果不进
状态板(oracle 零泄漏,复用现有隔离判据组)。
**验**:消融格(+S5)vs(−S5);主看需求遗漏型失败(Chonkie 31/33 型)
与语义替代型失败的发生率。

### S6 单 Agent 阶段机(轮内;可选,最后做)

报告 §37。**注意本仓已有轮间结构**(host-run ≤3 轮 + 轮间 failure packet
公开反馈),S6 只是轮内加 EXPLORE→PLAN→IMPLEMENT→PUBLIC_VERIFY→
PRE_SUBMIT 的提示协议与按阶段预算预留(§38.3:给最终验证/修复留配额)。
是否立项**取决于 S2–S5 消融后仍存在的失败形态**:若需求遗漏与"没跑公开
测试就提交"已被 S5 压下去,S6 缓议。判据届时冻结。

---

## §4 双轨并行:任务侧欠账不因执行侧改造而停

执行侧(E 轨)之外,任务侧(T 轨)有三笔批 12/13 记下的欠账,**与 E 轨
互不阻塞,可穿插做**:

| T 轨事项 | 出处 | 约束 |
|---|---|---|
| T3v7:h7 换**结构型锚** —— 首选 **Harness-owned Sidecar / Typed RPC**(harness 自己固定并运行 browser-use,agent 只能写 Adapter 去调它;"是否用上游"从足迹推断变成**执行拓扑约束**),次选能力型锚(真渲染执行 JS 才算得出的字段值)。二者都属 #43 冻结判据的合法锚型;sidecar 更彻底但会改变任务语义(从"集成库"变成"集成 RPC"),`task_shape` 须重评、决定要留痕。另加 `new_browsers` 公开教(#33 违规补齐) | 批 13 + 测试模式方案 §9.4 | 走 v7 新包;v6 冻结;修好前 T3 不发批 |
| T2v5 h1 同族加固(`open_deep_research` 也可被自带同名包满足) | 批 13 待办 | 若改 oracle 走 v6;现有 v5 发次不受影响 |
| h4 扫系统临时目录的脆弱性(撞别人 .pkg 权限炸) | nc8 验证时发现 | 小修,随 T3v7 一起 |

T 轨的每一步同样走:冻结判据(先过可搬运性审查)→ 控制对象(**正控 +
不动脑伪造负控 + 有意规避负控 + 误杀侧正控**,四件套,批 11–13 定型)→
红绿/变异 → 预注册 → 发批。

---

## §5 对照检验总表(每步做完,拿这张表核)

| 步 | 完成定义(全部满足才算完) | 检验命令 / 证据位置 |
|---|---|---|
| S0 | exec_metrics.py 对 6 个 bundle 出数;对账偏差 ≤10%;基线表填入本文档 | `scripts/exec_metrics.py` → `docs/evidence/exec_metrics/baseline-E0.json` |
| S1 | 四 hash 入台账;preflight 强制 + 长观测 canary;钉死+变异过 | fake 冒烟一发,查台账新字段;`verify_integrity.sh` 全绿 |
| S2 | C1–C4 判据全过;消融批 10 发入账;批报含 Wilson 区间 | 预注册 → 批报 `batchN-exec-ablation-*.md`;`projection.applied` 事件抽查 |
| S3 | B1–B3 过;T0/T1 消融入账 | 同上格式 |
| S4 | E1–E3 过;T1/T2 消融入账 | 同上 |
| S5 | R1–R3 过 + #43 可搬运性审查记录在案;遗漏/替代型失败率对比入批报 | 审查记录附在判据冻结提交里 |
| S6 | (若立项)阶段可追踪、预算分区生效 | 届时冻结 |
| 全程 | 闸门数字只出 `gate_report.py`;E0/E1 不互比;任务包零改动 | `check_public_claims.py` 常绿 |

### S0 基线(**2026-08-14 已完成**;数字全部出自 `scripts/exec_metrics.py`)

证据:`docs/evidence/exec_metrics/baseline-E0.json`。M1 对账 **6/6 通过,
偏差全部 0.00%** —— 逐调用 `prompt_tokens` 累加与台账 `input_tokens` 精确
相等(不是"≤10%",是恰好相等),故基线可信。

| order | 任务 | 调用 | 累计输入 | **重复率** | 缓存率 | 整文件读 | 丢弃字符 | 重复命令 |
|---|---|---|---|---|---|---|---|---|
| 64 | T2v5 | 25 | 547,192 | **93.0%** | 90.2% | 0 | 57,609 | 0 |
| 65 | T2v5 | 15 | 541,580 | **89.9%** | 81.5% | 3 | 111,828 | 0 |
| 66 | T3v5 | 43 | 1,013,341 | **92.8%** | 90.4% | 3 | 173,734 | 0 |
| 67 | T3v5 | 51 | 1,332,189 | **94.0%** | 90.7% | 1 | 85,380 | 0 |
| 68 | T3v6 | 55 | 1,307,160 | **94.6%** | 91.2% | 4 | 137,399 | 0 |
| 69 | T3v6 | 38 | 954,055 | **91.8%** | 86.8% | 3 | 112,518 | 0 |

**读数**:

1. **重复输入占 89.9%–94.6%** —— 报告 §21 的"平方膨胀"在本仓被量化了。
   定义(冻结):全历史重发下 `prompt_tokens` 严格单调(六发实测均单调),
   故 `unique = max(prompt_tokens)`、`repeated = sum − unique`。这是 S2 的
   直接靶子。
2. **丢弃字符 57k–174k 且不可回读** —— 这些是 `clip_observation` 头尾截断
   后**永久丢失**的中段(原文只在 artifact,模型无回读路径)。S2 的 spill
   应把它降到 **0**(改为可回读引用),这是比省 token 更硬的收益。
3. **缓存率 81.5%–91.2%** —— provider 侧前缀缓存命中很高,说明**成本**
   已被缓存吸收大半;S2 的价值主要不在省钱,而在**腾出预算余量**与
   **让关键信息不被淹没**。这一条要写进 S2 批报,避免把"省钱"当卖点。
4. **重复命令全 0** —— 六发都没有 ≥3 次的重复命令。**S3 的重复调用治理
   在当前证据下缺乏靶子**,按 §17 停止规则,S3 应降级为"S2 后复测再定",
   不要因为报告里有就照做。
5. **整文件读 0–4 次** —— 靶子存在但不大;S4 编辑器的优先级同样待 S2 后复评。

| 指标 | E0 实测 | E1-S2 目标方向 |
|---|---|---|
| 重复输入占比 | 89.9%–94.6% | ↓↓(主指标) |
| 丢弃字符(不可回读) | 57k–174k | **→ 0**(改为可回读) |
| 预算余量(r1 末) | T2 ~9% / T3 ~4% | ↑ |
| 缓存率 | 81.5%–91.2% | 不显著劣化即可 |
| verdict 分布 | 见台账 | 不劣化 |

**量具自身的两个 bug(实录,已修并做进自证)**:首跑时"整文件读/丢弃字符/
重复命令"三项**全零**,差点被当成"没发生"。实为 (a) 按 `raw > seen` 长度比
判截断 —— 而 `content` 外包了 `<returncode>/<output>` 标记,比长度必然失效;
(b) `extra.raw_output` **不是**未截断原文(实测标记称原文 35,289、落盘仅
7,758),用它判整文件读会因永远够不到阈值而恒报 0。两处都改为按 clip 标记
`[...RepoProof obs-cap: N of M chars omitted.` 解析,并加了 `selfcheck()`:
喂合成缺陷,四项指标必须全部报警,否则拒绝出基线(`exit 3`)。

---

## §6 P-D:DeepSeek 阶段(GPT 阶段收效后启动,本阶段冻结不做)

进入条件:S2(至少)在 GPT 双模型上 C3 成立且 verdict 不劣化。届时按
报告第六/八部分执行,要点存档:

1. `deepseek_native.py` 适配器(直连官方,SSE、稳定错误分类、不在 stream
   内重试)+ `deepseek-official` provider profile(报告 §31.1 的 YAML 字段
   全量入 manifest,alias 与 resolved release 分开记);
2. 三层 canary(§32):单轮工具 / **多轮 reasoning passback**(思考模式下
   工具轮的 `reasoning_content` 回传;不发不兼容 `tool_choice`;assistant
   content 非 null)/ 长观测(S1 已有,复用);
3. 双候选 profile 消融(§55):DS-NATIVE-HIGH-DET(temp0/high)vs
   DS-NATIVE-MAX-OFFICIAL-LIKE(temp1.0/top_p0.95/max)——官方 Flash 参数
   只是候选,**不是** Pro 的答案(§66);
4. DSH minimal bridge(§30 方案 B)最后做,且 DSH 只提工具动作、执行仍走
   本仓 policy 环境,不碰 oracle / Docker socket。

**P-D 的对照基线就是 GPT 阶段建成的 E1**:届时换 provider 适配器是单变量。
这正是"先 GPT 后 DS"路线的方法论价值 —— 不是偏好,是消融顺序。

---

## §7 风险与回退

- 每个 S 步一个 feature 开关,按 profile 选择;E1 出问题可整体退回 E0
  (E0 代码路径保留到 P-D 结束)。
- S2 最大风险:prune 折叠掉模型后续要用的信息 → C2 判据(只折叠三型 +
  必留回读引用)就是为此;消融批若见"回读频繁但仍失败"形态,判 prune
  过激,收窄折叠型别再跑(判据不挪,参数可调,调参记录进预注册)。
- S5 最大风险:状态板探针被照着造(批 13 同型)→ 上线前可搬运性审查 +
  有意规避负控,不过不上。
- 全程红线(不因任何收益松动):oracle 隔离、答案不在盘上(H9)、
  runs.jsonl 只追加、裁定旁挂、闸门数字只出脚本。
