# RepoProof × OfferClaw 测试方案 v2(执行版)— 长期指导文档

> 状态:**执行基线,已通过独立 agent 对抗审核**(16 必改项全部落实,
> 审核记录见 EXPLORATION_LOG)。用户批准本文档即同时确认 [模式 L 默认]。
> 源方案:`TESTPLAN-V2-SOURCE.md`(2232 行,保留不改)。
> **默认规则:本文未言明处照源方案执行;冲突处以本文 §2 为准。**
> 架构论证:`docs/rfc/RFC-009-HOST-INTEGRATED-TASKS.md`(以其 §六 v2 修订为准)。

---

## 0. 压缩后冷启动指南(给未来的协作 AI)

按序读:①长期记忆(自动加载)→ ②本文 → ③RFC-009 §六 → ④
`docs/EXPLORATION_LOG.md` 最新**状态条目** → ⑤`benchmarks/v2/runs.jsonl`
→ ⑥`TESTPLAN-V2-SOURCE.md`(仅按附录 A/B 指定章节取用)→ ⑦
LESSONS_LOG / ENGINEERING_CASEBOOK(勿复踩)。

**状态条目制度**:每次 Phase 转换、停点、批次开/闭,必须在
EXPLORATION_LOG 追加一条状态条目(含 Phase 0 ①-⑥ 勾选进度)——
冷启动以最新状态条目为进度事实,再以磁盘取证核实,不凭记忆断言。

## 1. 角色分工与三段式(铁律)

> **v3 修订(2026-08-10,用户改令)**:宿主级形态下用户参与已退化为
> "点一下+转发目录名"→ **阶段循环(任务×模型序列)整体由 AI 代跑**。
> 协议:循环前报计划(模型序/预算盒/成本封套/运行上限=计划数×2)
> 经用户一句确认;harness 缺陷→停修(钉死+预注册修订)→复测该模型
> →继续,模型弱点只记录(§39/§38.2 照旧);收束保证每模型 ≥1 发在
> 循环最终 harness_commit;循环末合并报告。用户保留预算/准则决策、
> 叫停权与 UI 亲手运行。以下原文保留为历史:

- AI 评估(只读代码 + /tmp 实测)→ AI 代做准备 → 给可复制指令 →
  **用户亲手执行正式 run**(v3 起改为 AI 代跑循环)→ AI 磁盘取证分析;
- **执行者归属**:正控/负控/直连基线/Host Baseline 属任务工程,由 AI
  在副本 worktree 内执行;冻结后的模型正式 run:v3 起由 AI 按循环协议代跑;
- 用户报结果只需 run 目录名;截图仅用于 UI 视觉问题,且**截图不得含
  真实个人信息**(源 §44 禁令含 Screenshots);
- 预算/轮次等调整:先与用户讨论确认,冻结前定值,冻结后不改。

### §1.2 会话生命周期纪律(2026-08-11,用户遇 Fable 降级后共识)

- **病理**:协作会话每轮重发全历史,消耗随会话长度平方放大(与
  deepseek 观察限流同构);多次被动压缩后记忆失真(实证:会话把 T2
  记成前沿而磁盘已在 T3v2)。被动压缩贴 1M 上限才触发=太晚且摘要
  通用失真;
- **制度:里程碑换壳**——批次报告/冻结/停修等停点,AI 状态落盘
  commit 后主动打「🔄 换壳点」标记;用户一条
  `/compact 只保留:<当前停点/预注册/待决>` 即完成**同线程底层换会话**
  (桌面 App 无感;会话文件在 `~/.claude/projects/<slug>/*.jsonl`
  可见新文件),或手工新开会话按 §0 冷启动(磁盘摘要 5-10k tokens);
- **AI 侧义务**:取证结论进文档、原始日志留盘不进对话;**进度问题
  永远先查盘再开口**;
- **退化自诊**:用量页配额见底=窗口问题(换壳/等滚动);配额充裕=
  Fable 容量波动(`/model claude-fable-5` 重钉即回)——两类退化两套
  对策,与项目内容无关。

#### §1.2.1 根因更正与配置化(2026-08-11 磁盘取证)

**"每次新会话都退化"的真因不是配额,是配置**:用户级
`~/.claude/settings.json` 写着 `"model": "opus[1m]"` —— **每个新会话
(含压缩后的新会话)按此默认值启动为 Opus**;`/model` 只对当前会话
生效。这解释了全部现象(新开必退、压缩必退、与消耗无关)。教训同族:
**环境/进度问题一律先查盘再推理**(本日第三次同类失误)。

**已落地(项目级 `.claude/settings.local.json`,该文件被全局 gitignore
故配方留档于此;用户级文件未动)**:

```json
{
  "model": "claude-fable-5",
  "autoCompactWindow": 150000
}
```

- `model`:项目内新会话直接生于 Fable,**不必再手敲 `/model`**;
- `autoCompactWindow`(schema 确认,取值 100k-1M):压缩在 15 万 tokens
  自动触发,而非贴近百万窗口才压——**"里程碑换壳"由此自动化,不必
  手敲 `/compact`**;副作用:放弃 `[1m]` 大窗口,而小窗口正是省钱的
  关键(每轮重发的上下文更小)。
- 待用户定的两个旁路开关(schema 存在,本次未改):
  `switchModelsOnFlag`(安全审查命中时**静默换模**,设 false 则改为
  暂停会话——可让隐性换模显形)、`fallbackModel`(主模型过载时的
  回退序列)。

## 2. 对源方案的修正与取舍(冲突以本节为准)

| # | 源条目 | 处置 | 理由 |
|---|---|---|---|
| 1 | "UI 填了就能跑" | 先做 Phase 0 前提工程 | 现有流水线是样例 seam,无法执行宿主级任务 |
| 2 | 阶段 A 全量前置事务图/Rollback Gate | 最小集;T1/T2 出证据后按源 §38.2 触发 | problem-first |
| 3 | ~~每轮分层回归~~ | **撤销**:Phase 1 首测实测全量套件仅 **12.5 秒**(591 passed,3 次完全一致)→ **每轮跑全量**,无需子集 | 实测推翻假设 |
| 4 | T3 与 T1/T2 并列 | T3 远期(嵌套 agent+mock 站是独立工程) | 复杂度被低估 |
| 5 | 执行环境未指明 | 模式 L 默认 + 证据分级;D=对外声称复验等级 | RFC-009 §6.5 |
| 6 | §5 HostBaselineManifest / §5.2 完整基线 | **保留采用**:Manifest 并入 Phase 1 首测;完整基线(RAG 100 题/realworld 52/拒答)T2 批前+终验后各一次 | T2 写 Chroma,594 pytest 不度量检索质量 |
| 7 | §6 task_shape 八维评分 | 保留:每任务冻结时填写入任务包 | 难度声称的依据 |
| 8 | §30 第三模型 | 点名 gpt-5.4-mini(以 provider /models 实际为准) | 消歧 |

**Host Baseline 实测基线(Phase 1 产出,详见 `HOST-BOOTSTRAP-OFFERCLAW.md`)**:
591 passed / 7 skipped / 0 failed · 12.5s · 完全确定性(容差=不允许下降);
verify_pipeline 6/6;verify_docs 0 裸露;doctor 8 OK·2 WARN·1 ERR
(**已知预期差异**:chunks 口径 112 vs 3538 因合成语料重建;WARN 为合成
密钥政策的预期表现)。**判据 = 相对本基线不退化,而非绝对全绿。**

## 3. 固定基线(全部已核实)

```text
宿主   OfferClaw            8e59a18f78056113ffa34d27eb1cfb2a64ae2108(=用户本地 HEAD)
T1     fastapi_mcp          e5cad13cabfc725bbcb047e526816d887d96da62
T2     open_deep_research   20aaa0d422bd290c83f93574810ef1244e8d5955
T3     browser-use          32601887cfbc9f4f1e3cad3e2b678e56aeaeaae4(远期)
metrics.json current:53 路由/594 pytest/3538 chunks/doctor 12(字符串型,对账容忍类型)
T1 副本:~/RepoProofBench/offerclaw-t1-fastapi-mcp(--no-hardlinks 重建,
  detach@8e59a18,origin 已移除,对象库零共享 inode 已核验)
```

## 4. OfferClaw 保护(红线,与 RFC-009 §6.5 六层一一对应)

1. **主目录硬护栏**:一切写路径拒绝 `~/Desktop/XIANGMU/offerclaw`;
   实现须 realpath 归一化 + 大小写不敏感(APFS)+ 软链/相对路径/`~`
   变体全覆盖,测试钉死;只接受 `~/RepoProofBench/` 副本;
2. **副本纪律(含审核实证教训)**:克隆必须 `git clone --no-hardlinks`
   并核验 `.git/objects` 无 links>1(否则与主仓共享物理文件,改副本
   =毁主仓);克隆后**必须 `git remote remove origin`**(否则一条
   `git push` 写穿主仓);argv 策略显式 deny `git push`;每 run 新
   worktree,副本可弃;
3. **Host Baseline Gate**:run 前 doctor/verify_pipeline/pytest/
   verify_docs 全绿否则 BLOCKED 零预算;**副本引导**是 Phase 1 首测的
   产出物:HostBaselineManifest(源 §5 字段)+ 按下表**资源引导策略**
   给出 OfferClaw 每类资源的实测答案:

   | 资源类 | 例(OfferClaw 实探) | 模式 L 规矩 |
   |---|---|---|
   | A 只读缓存 | HF 模型权重、Playwright 浏览器、wheel 缓存 | **可直接共享**(同 wheelhouse 原则):共享只读+引导期预热+运行期离线开关(HF_HUB_OFFLINE=1),版本入 Manifest |
   | B 运行态数据 | `chroma_db/`(3538 chunks,项目目录内)、gap_store、memory 文件 | **可用本地的,但必须快照复制进副本**(读主目录合法,护栏只拦写);哈希入 Manifest;**绝对禁止**软链/绝对路径指回主目录 |
   | C 密钥凭据 | OPENAI_API_KEY / DASHSCOPE_API_KEY(.env.example 实探;conftest 无密钥逻辑→测试大概率不需真钥,Phase 1 实证) | agent 轮次只给**合成密钥**(净化环境);若 baseline 实测必须真钥,只允许进 harness 自跑的基线进程 env,绝不进 agent 轮次、绝不落盘副本 |
   | D 外部服务 | OfferClaw 无(Chroma 内嵌) | 其他项目:baseline 查服务存活,测试内 fake(fastapi-template 弃用的原因) |
   | E 私有依赖/LFS | — | 引导期镜像入本地缓存,配置记录 |
   | F **绝对路径配置** | 配置写死指向主目录的路径 | 引导期扫描改写——防"副本进程写穿主目录"暗通道(护栏拦不住数据层间接写,指纹只能事后发现) |
   | G 平台绑定件 | 编译 .so / node_modules | 不复制,引导期在副本内重建 |
4. **既有写回防线**(E2 实测):三级确认+指纹漂移门+preimage+回滚
   账本+崩溃自动回滚;
5. **数据密钥**:快照排除清单(.env*、*.lock、运行态);**模式 L 进程
   环境净化**——agent 命令以白名单环境(PATH/HOME 等最小集)启动,
   不继承用户 shell 的真实 API key,测试钉死;测试只用合成数据;
6. **主目录 tree-hash 对账(执行语义)**:本地执行后端在每次 run 的
   pre/post 自动执行;范围=主目录工作树(**含 untracked**)+
   .git/HEAD 与 refs 摘要;结果写 runs.jsonl(`main_dir_integrity`);
   mismatch → 立即停机、禁一切自动动作、人工判定(用户 run 期间自改
   主目录属违纪,判定时如实区分);**附加披露**:.env.local/Chroma/
   gap_store 等 untracked 数据不受 git 保底,Phase 1 首测时对其做
   一次性备份后方可开跑。

**开跑前审计**:主目录破坏风险逐通道审计见 `OFFERCLAW-RISK-AUDIT.md`
(结论:代码内"写出项目"通道为零,全 __file__ 锚定;风险登记册
S1-S7 已解决 / L1-L7 潜在对策已备;API Key 政策四条)。**L1(副本
携带真实个人数据)与 L2(假 HOME)在 T1 冻结前必须落实。**

## 5. 执行架构与证据分级

- **模式 L(默认)**:副本 + 基线 venv(只读,一次构建,构建输入
  hash 入账)→ **每 run 复制一份 venv 实例**,用后即弃(禁止共享
  实例就地安装——目标库安装是任务本体,共享=批次污染);目标库
  安装源冻结(本地 wheel 缓存优先,冻结时定);
- **网络策略(L 级明示弱化)**:本地执行无内核级网络隔离,argv 拦
  不住进程内网络调用——冻结时统一做法(离线开关/置空 proxy),并
  作为证据分级的已知弱化项记录;
- **模式 D**:全容器,对外公开声称须 D 级复验或如实标注等级;
- runs.jsonl 记 `execution_backend`(local-worktree=machine-
  reproducible / docker=hermetic-reproducible)与环境基线标识
  (L=venv 构建输入 hash;D=镜像 digest);等级间不互比;
- 核心可信度机制(隐藏 Oracle/独立验证/Completion Gate)与后端无关。

## 6. 阶段计划与停点

```text
Phase 0  RepoProof 前提工程(AI 实施,每步带测试):
         ①主目录护栏+指纹对账 ②LocalWorktree 执行后端(净化环境/per-run venv)
         ③宿主快照排除 ④宿主级任务包接线(手写 oracle 复用冻结管线)
         ⑤provenance 最小版 ⑥benchmarks/v2 记录器(runs.jsonl/preregistrations/reports)
         完成定义:各有钉死测试 + 一个空转冒烟任务全链跑通 + 状态条目记账
Phase 1  T1 校准:Host Baseline 首测(套件耗时/容差协议/副本引导手册/
         untracked 备份)→ T1 任务工程(§7)→ 用户跑 GPT-5.5 + DeepSeek 各 1(随机序)
         停点:双一轮过 → T1=CALIBRATION_ONLY 直进 T2;有区分度 → 按批纪律补齐
Phase 2  T2 正式:完整基线(批前)→ 三模型 pilot(gpt-5.5 / deepseek-v4-pro /
         gpt-5.4-mini,随机序)→ 有区分度补齐 3×3 → 完整基线(终验)→ 批后统一分析
Phase 3+ T3(远期)/ T4 回滚专项(源 §42-43 R-A..R-E)
```

> **Phase 2 结果注记(2026-08-10,收束)**:T2 实际以 v1→v4 四任务版
> 演进完成(宿主基线经用户决策改 **85278e6**,§3 表为历史;模型池
> 实际=deepseek-v4-pro/gpt-5.5/gpt-5.6)。终局:**v4 双模型
> PASS_ADAPTED**,deepseek 0/8 定格弱模型边界;两 oracle 缺陷修复+
> 三 harness 修订+LESSONS #14-17 全程失败驱动。唯一事实源:
> `benchmarks/v2/reports/T2-FINAL-REPORT-20260810.md` 与台账 E4/E5。
> 定位结论(用户确认):**判定保证而非成功保证**。Phase 3 转段
> 准备清单见终报告 §四。

**容差协议**(源 §5.3):正式预注册前,未修改宿主重复跑基线 3 次记
自然波动;确定性则要求不降,有波动则 tolerance=max(约定最小值,
2×观测波动),模型运行前冻结。

## 7. 任务工程规范(每任务冻结前走完;执行者=AI,见 §1)

```text
固定 commit → Public Requirements → Public Tests → Hidden Oracle(绝不给 agent)
→ task_shape 八维评分 → Positive Control 全过 → Negative Controls 逐一按预期挂
→ Direct Baseline 记录 → 冻结 TaskPackage → 预注册(benchmarks/v2/preregistrations/)
→ 用户随机序运行 → 停点报告(benchmarks/v2/reports/,按源 §48 清单)
```

预算(初始值,冻结前按正控实测调定,冻结后不改):

| 任务 | 轮数 | 调用 | 命令 | Patch 文件 | Patch 行 | Wall | tokens in/out |
|---|---|---|---|---|---|---|---|
| T1 | 3 | 24 | 60 | 10 | 800 | 30min | 350k/40k |
| T2 | 3 | 36 | 120 | 20 | 1800 | 60min | 600k/60k |

## 8. 批次纪律与红线

- 同批同任务:同宿主/目标 commit、同任务包、同预算、同后端、同环境
  基线(L=venv 基线 hash;D=镜像 digest)、同网络策略;
- 批内禁改 Harness;Safety/Integrity Bug 一次即修,但该批作废重预注册;
- 效率类增强需重复证据(≥2 独立 run 或跨 ≥2 任务)+ 未见 case 验证;
- **难度过高分支**(源 §30.4):全模型同根因失败 → 先查 Contract/
  Oracle/Baseline/依赖/正控/预算,**不得先改 Harness**;需重做则建
  task-v2,v1 保留不改写、不入排名;不因单模型一次失败升复杂度(源 §46);
- 硬红线:False System Pass=0、Hidden Oracle Leakage=0、Unapproved
  Real Apply=0;弱模型不单独加预算;n<3 不排名;不同 harness_commit 不互比。

## 9. 记录制度

- EXPLORATION_LOG(E-条目 + **状态条目**)/ LESSONS_LOG / CASEBOOK 照旧;
- `benchmarks/v2/runs.jsonl` 每 run 一行:`run_id task_id task_version
  harness_commit host_commit source_commit model provider
  provider_config_hash run_index run_order guided max_rounds rounds_used
  model_calls commands input_tokens output_tokens wall_time cost
  public_passed_by_round regression_by_round rollback_count
  scope_change_count stagnation final_capability final_regression policy
  replay verdict failure_types execution_backend env_baseline_hash
  main_dir_integrity trace_sha256 bundle_path`(未知写 UNKNOWN 不写 0)。

## 10. 结果解释边界

照源 §49:可研究 Verified Success/多轮改善/低成本模型可用性/失败可
解释性/Feature 可撤销性;不可提前声称 Harness 普遍提效、廉价等价强模、
任意项目支持、多轮必成、不可逆副作用可回滚、3 次运行有统计显著性。

## 附录 A:T1 要点

- 副本:`~/RepoProofBench/offerclaw-t1-fastapi-mcp`;目标:fastapi_mcp
  @ `e5cad13c`;
- **口径澄清**:本节是需求内容基准(源 §7.2 全文:Feature Flag 默认关/
  显式白名单/Schema 不得二份漂移/禁重复 mount/旧 /mcp 兼容/594 保持/
  真实使用 fastapi-mcp);T1 **不经现有样例向导**,经手写任务工程 +
  冻结管线(Phase 0 ④ 的入口);
- Hidden Oracle/负控/失败类型:源 §7.4-7.6;Provenance 检查内容:
  源 §7.4 条 5/6 与 §7.5 NC1,机制实现依 RFC-009 §三.4。

## 附录 B:T2 要点

需求:源 §8.2 全文(21 条,含依赖冲突时 Plan 阶段比较进程内 vs
Sidecar 由用户确认、Promote 显式确认、source_type=research_report
隔离、Secret 零泄漏);Hidden Oracle:源 §10 H1-H10(H1 即 Provenance);
负控:源 §11 NC1-NC5;完整基线:批前+终验后(见 §2-6)。
