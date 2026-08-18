# E1-DSH-MINIMAL-BRIDGE-1 预注册(冻结,2026-08-18)

**状态:FROZEN(2026-08-18 12:3x,冻结点 = 本文件所在提交)。** 开跑后判据
一字不改。冻结前置已满足:阶段 7 DQ-SDK-1 通过,
`rt-dsh-minimal-0.1.0rc6-v1` **qualified**(0396153:G6=2 模型 + G6b=1
诚实通过 + G7 清);注入纪律 = 用户授权的 `source .env` 前缀(值不进
上下文,DQ 附录一)。层 1/层 2 机械面钉齐:`dsh_bridge` + `run_dsh_round`
+ M88×4 + M89a。

**API 窗口规则(冻结时预登记,不是事后挪门)**:用户告知 DeepSeek 通道
**14:00 硬止**。①不启动"预计墙钟(同型同臂观测峰值 + 5 分)越过 14:00"
的发次;②窗口关闭即暂停,判据 / 发次序 / 预算零改动,窗口重开按序续跑;
③暂停期间只做零 API 工作(收口文书、门、台账);④在途发次不得跨窗启动。
观测峰值基线:H0(mini-swe)16.3 分、H1×pro 31.3 分、H1×flash 23.7 分。

## 1. 批名与代际

- 批名:`E1-DSH-MINIMAL-BRIDGE-1`
- 代际族:**B-dsh**(全新族,不派生 E0/E1 的分析池;两臂**永不**与历史
  E0/E1 发次合池)
- 臂:
  - **H0**:mini-swe 环(仓内缺省 AgentBackend,`backend_id=mini-swe`)
  - **H1**:封存 DSH minimal runtime 作不可信 AgentBackend
    (`backend_id=dsh`,`runtime_profile_id=rt-dsh-minimal-0.1.0rc6-v1`,
    lifecycle=**qualified**,0396153)

## 2. 研究问题(只此一问)

同一模型、同一任务、同一总额预算下,**把 agent 循环从 mini-swe 换成官方
DSH minimal 组合**,对"能不能把这道修复任务做绿"的机制效应是什么?

**不回答**:模型多能干(counts_toward_model_capability=false)、held-out
表现(backend 第三锁在 `bench_records.classify_runs`,分类旁挂自述不能
自证)、DSH 是否"更好用"(单任务 n=3 没有这个统计力)。

## 3. 任务与分类旁挂(逐发次)

- 任务:`sqlglot-8042`(**seen task**;与 HB-DSENTRY-1 同宿主同 base commit)
- `test_mode=E1` · `run_purpose=MECHANISM_ABLATION` · `task_seen=true`
- `counts_toward_model_capability=false` · `counts_toward_heldout_benchmark=false`
- `counts_toward_mechanism_effect=true` · `counts_toward_treatment_effect`
  仅送达发次填(见 §7)

## 4. 臂间同一性(相同项清单)

同:模型 profile(**用户 2026-08-18 定:双模型都进** —— deepseek-v4-pro
与 deepseek-v4-flash 各跑满 n,两模型内部两臂对照,模型是分层因子不是
自变量;两名均在 DQ-SDK-1 达成 qualified 的同一封存组合上跑过真发次)、
任务包(一字不动)、宿主 base commit、提示知识面
(同一份 host prompt 文本)、上游工件与 wheelhouse、网络策略(provider API
为正常通道)、**总额预算**(§5)、验证器与隐藏 oracle、干净重放、计分与
Completion Gate。

**唯一自变量**:AgentBackend 运行组合(mini-swe 环 ↔ DSH minimal 组合)。

## 5. 等总额预算(映射即代码:`dsh_bridge.bridge_budget`,M88c 钉)

| 轴 | H0(HostBudgets) | H1(DshBudget) |
|---|---|---|
| 模型调用 | max_model_calls | max_logical_requests(周期计数,E5) |
| 输入 tokens | max_input_tokens_total | max_input_tokens |
| 输出 tokens | max_output_tokens_total | max_output_tokens |
| 墙钟 | max_wall_time_minutes | max_wall_seconds = 分 × 60 |
| 物理尝试 | —(litellm 内部重试) | max_llm_attempts = logical × 3(C8 实测:500 恰 2 重试) |

- 只接受 `semantics="total"`;per_round 在准入即拒(等总额无从定义)。
- patch 轴(files/lines)在裁决面执法,天然臂中立;H1 命令数如实记
  bash tool/call 计数,不写 0 冒充。
- **契约:`contract-e1-total.yaml`(task_version=v1-e1-total)**,与
  DQ 的 v1-dsh-total 唯一差异 = **max_model_calls 90→500,两臂同值**。
  依据(DQ-SDK-1 附录五实证):四次真跑逐发 91 撞 90 上限(含 PASS 发),
  彼时 token 信封仅用 3-4% —— 90 来自 mini-swe 的机制常数(30/轮×3),
  把它当资源上限强加给请求重 / token 轻的 DSH 臂,恰是臂中立的反面。
  500 > 墙钟可及的 ~180-240 请求,calls 轴退为**两臂同值的逃逸后备**,
  运营约束回到真正的资源轴:in 1.8M / out 240K / 墙 60 分 / commands 300
  ——四轴两臂逐字同值。跑飞保护仍在(attempts=logical×3)。**不回头改
  DQ 批判据**(附录五原话),这是 E1 自己的冻结决定。

## 6. H1 组合冻结(`dsh_bridge.composition_fingerprint`,M88b 钉)

- 封存 runtime:`rt-dsh-minimal-0.1.0rc6-v1`(SDK 0.1.0rc6 /
  runtime-bin 0.1.0rc6 / cordis 上游钉 commit 47f94385…,现物 sha256
  与封存清单比对,不符拒跑)
- 组合三缺省(逐字):
  - system prompt:`You are a helpful software engineer assistant.`
  - maxTokens:`256000`
  - reasoningEffort:`high`(SDK 0.1.0rc6 内部缺省;我们的配置面设不了
    它,声明进指纹的意义是换 SDK 版本必换 sdk_version,批不可混)
- 严格最小首轮:工具面**恰** bash + str_replace_editor;无 compaction /
  子代理 / 联网工具 / skills(fidelity ④⑤ 执法)
- 指纹整份入 exec context 面哈希(`_exec_profile_fields(backend="dsh")`)

## 7. Treatment fidelity(九项,§17.3;`treatment_fidelity`,M88d 钉)

①backend 身份 ②封存版本 ③组合一致 ④工具面白名单 ⑤无扩展面
⑥runtime 事件存在 ⑦会话唯一 ⑧预算生效 ⑨workspace 出处。

- 任何一项缺失 → 该发次 `TREATMENT_NOT_DELIVERED`,**只能读作"治疗未
  送达",不得读作 H0/H1 无差异**;仅送达发次进臂间比较。
- **停批线:H1 送达率 < 80% 即停批**,修 instrument,新代际重跑,不回填。

## 8. 发次序(instrument 坏 = 停批,不回填)

1. **F0(收窄声明,零 API)**:fake-positive 一发过 E1 契约全链
   (batch=E1-DSH-MINIMAL-BRIDGE-1-F0)。四形负控不重跑:同判据面四形
   已于 2026-08-17 全量证过 + DQ-SDK-1 对 total 语义变体重证过正形,
   本变体与 v1-dsh-total 的差异只有一个整数字段;负控形与 calls 上限
   无交互。附:`bridge_budget(E1 契约)` 机械核映射数(附录一)。
2. **H1 彩排(收窄声明,零 API)**:full-runner × dsh 集成已由 DQ-SDK-1
   发 3/发 4 在**同一 HEAD 代码**(313f9a6,其后零 src 改动)× 同任务
   × 真端点全链产线证过(含 PASS + replay);round 级活钉
   `test_r1_run_dsh_round_end_to_end_over_fake_endpoint` 在全量套件常驻。
   独立 full-runner×fake-endpoint 常驻钉**批后补**(登记为欠账,不挡本批)。
3. **计分序(双模型,n=3/臂/模型,金丝雀计入 n,共 12 发)**:
   序 1 H0×pro → 序 2 H1×pro → **pro 对 fidelity 闸** → 序 3 H0×flash →
   序 4 H1×flash → **flash 对 fidelity 闸** → 序 5-12 = 每模型每臂再 2 发
   (顺序 H0×pro ×2 → H1×pro ×2 → H0×flash ×2 → H1×flash ×2,窗口规则
   优先于顺序:预计越窗的发次跳过等窗,不改判据)。
4. 任何 instrument 问题:停批 → 修 → 登记新代际 → 全序重跑,**不回填**
5. **运行上限 16**(12 计分 + 4 缺陷重跑位);成本封套:in ≤14M tok /
   out ≤1.5M tok / API 墙钟累计 ≤7h;超封套中止请示。

## 9. 批层变异面(已入登记簿,随层 1 提交 `007a422`)

- M88a = M-DSH-13:backend 第三锁死(DSH 发次混进能力池)
- M88b = M-DSH-14:组合指纹掉字段
- M88c = M-DSH-15:两臂预算不等(分钟当秒)
- M88d = M-DSH-16:fidelity 判读死(未送达读作无差异)

四枚手验"杀死,凶手正确";批开跑前置:全量变异闸门在冻结 HEAD 全捕
(与批首发次**并行**跑 —— 门在临时 worktree(HEAD)施变、PYTHONPATH
压 editable、主树零触碰,隔离性为设计保证 + DQ 附录四实录;若未全捕,
当场停批修复)。最近全捕基线:257/257 @ 313f9a6,其后 src 唯二改动 =
bench_records 登记集加一常量 + profile lifecycle 翻牌,均不在任何变异
体靶行上。

## 10. 台账与判读边界

- H1 行:`backend_id=dsh`、`runtime_profile_id=rt-dsh-minimal-0.1.0rc6-v1`、
  `dsh` 回执块(逐轮归因/会话/用量/fidelity)、`cost=UNKNOWN`(无费率
  读数不写 0)
- `final_response`/`finish_reason`/会话 JSONL 永不产生 PASS —— 裁决只走
  隐藏 oracle + 验证器 + 干净重放 + Completion Gate(ADR 既定)
- qualified 只证真模型全链诚实跑通且一发真过(DQ-SDK-1 划界 §8),
  **不是能力主张**;本批结论措辞的上界:单任务、seen task、n=3/臂/模型
  的机制效应读数,不得读成"DSH 更好/更差"的一般结论

## 附录一(冻结时工程留痕,2026-08-18)

1. **preflight 双探活(12:31,冻结前)**:deepseek-v4-pro
   PROVIDER_READY(378/53,1.6s);deepseek-v4-flash PROVIDER_READY
   (378/60,1.1s)。
2. **DS 旋钮**:两臂 `REPOPROOF_DS_PROFILE=DS-NATIVE-HIGH-DET`。H0 臂
   旋钮生效(temp 0 / top_p unset / effort high / tool_loop);H1 臂
   旋钮惰性(DQ 预注册 §2 如实声明,有效组合 = composition_fingerprint
   九键)。这是臂间已知的不可消除差异,属"换循环 = 换执行语义"的一部分,
   记入判读边界。
3. **bridge_budget 机械核**(冻结时现场):E1 契约 → logical_requests
   500 / attempts 1500 / in 1,800,000 / out 240,000 / wall 3,600s。

## 附录二(2026-08-18 · 代 1 停批:序 2 worker 越区改写宿主母树)

**判决:§8 规则 4 触发 —— 仪器完整性事故,代 1 中止,已跑发次一律不计分,
修复后新一代从序 1 整段重跑,不回填。**

### 事实链(全部出自 run 130403 事件流 + 磁盘 mtime/birth 对时,秒级吻合)

1. 窗口内三发:F0 fake-positive(123618,12:36)→ 序 1 H0×pro
   (124741,12:47-13:03,PASS_ADAPTED 9/9)→ 序 2 H1×pro(130403,
   13:04-13:44,台账 FAIL 4/9,attribution ok)。14:00 API 硬止,13:44
   合规暂停(序 3 预计越线未发车)。
2. 暂停期收口跑全量套件,唯一红:
   `test_leak_guardrail_is_reverified_not_promised` ——
   `~/RepoProofBench/hb1-sqlglot-8042/host` 摘要与建包清单不符。
3. 取证定位(dsh_events_round1.jsonl,133 步命令逐条重建):序 2 模型
   (deepseek-v4-pro)第 1 步 `cd /` 自毁 cwd 信息(worker cwd 本已正确
   指向会话区 `~/RepoProofBench/_sessions/<run>/rp-host-agent-*/`,与 DQ
   发 3/发 4 同机制;那两发第一步猜错路径后靠 `pwd && ls` 自纠回正区),
   随后 `find /Users … -maxdepth 4 -name sqlglot` —— 深度 4 只够到**母树**
   `hb1-sqlglot-8042/host`(会话区在深度 6,找不到)。此后 116 次 cd 全部
   指向母树:步 70 建 `.venv`(13:19:57,= pyvenv.cfg birth)、步 73-77
   跑 pytest(13:20:09,= tests/__pycache__ birth)、步 78/81 两次改写
   `sqlglot/lineage.py`(13:23:12/13:23:45,= 文件 mtime 13:23:42)。
4. 判决面诚实无恙:判决工作区零改动 → adaptation.patch **0 字节**,隐藏
   oracle 4/9 恰为零适配基线(9 道里 5 道链式 pivot 新增点 = delta_nodes 5,
   其余 4 道本就绿),FAIL 标注正确。**但该发测到的是"无",此前"首次自然
   终止、松请求墙后得分反降"的机制判读作废收回** —— 133 请求是迷路轨迹,
   不是臂行为读数。
5. 破坏面收口:写入仅限母树(venv 重建 + lineage.py 改写 + pytest 缓存);
   `/tmp` 一次无害;**未触碰封存池** —— d5-hunt(内含带 git 历史的上游仓
   = 藏着本题正解)只在 find 输出里露过路径,序 2 与 DQ 发 3/发 4 三发命令
   流均零次读取(答案泄漏轴排除,DQ 资格不受染)。`.ssh`/`.env`/history
   零触碰。
6. 传播面收口:会话装配(快照母树)总在破坏之前 —— F0/序 1/序 2 三发
   快照均取自净树;破坏(13:19+)之后零发车。**无任何发次跑在污染快照上。**

### 修复(全部零 src 改动,变异闸门 257/257 @ efbf076 继续有效)

- 母树按既定幂等管线整树重建:`prepare_hb1_hosts.py --all` 第 2 轮 ——
  sqlglot-8042 **redeployed** 逐字节对上 V,回归基线 1150/1150,泄漏扫描
  45 指纹零命中双自证绿;两 click 宿主 verify-only 原样(反证破坏面单一)。
  **host_digest 与建包时逐字节同值** —— F0/序 1 跑的树与新一代将跑的树
  完全同一。全量套件回绿。
- 发车纪律新增绊线 `scripts/check_host_digest.py`:每次发车**前**核母树
  摘要(不符拒发,停批先查),每发**后**再核一次(发前绿+发后红唯一归因
  刚结束那发)。模型残迹已封存 `runs/…-130403/forensics_host_escape/`。

### 登记的结构性危害(本批不修,修 = 换代重资格)

- **执行面无越区约束**:两臂 worker 均以本机用户身份跑,母树可写、封存池
  可读(后者是答案泄漏通道,本次未被走过)。写侧本批用摘要绊线检测收口;
  读写硬隔离(快照落权归一 + 母树锁写 / 池锁读,或 worker 沙箱)登记为
  后续代际工程 —— 动 worker 执行语义即换代,需重走资格,不在停批修复内。

### 代 2 规则(冻结序不变)

- 计分序列 12 发照 §8 原序整段重跑(序 1 起);代 1 的 F0/序 1/序 2 行
  留台账不删,分类旁挂四口径全 false + 本附录为据。F0 不重跑:树摘要
  同值、零 harness 改动、F0 所证的管线四形与本事故正交(如需可加发,
  占缺陷重跑位)。运行上限 16 已用 2(序 1/序 2),余 14 ≥ 12 够额;
  成本封套按累计继续记账。
- 发车封装升级:`check_host_digest.py sqlglot-8042` 前后各一道,退出码
  非 0 即停批。其余(窗口规则①-④、fidelity 闸、判读边界)一字不动。
