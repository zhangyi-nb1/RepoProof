# Interview guide — answers, red lines, likely follow-ups

Ground rules for every answer: numbers only from
[benchmark_summary.json](benchmark_summary.json); never merge
Agent / Harness / Host-Guard contributions; negative results are
features, not embarrassments.

## 30 秒介绍

"RepoProof 验证 coding agent 的开源库适配是否真的可用。Agent 在隔离容器里
对着冻结合同写 adapter,但判定完全独立:能力测试、宿主回归、策略审计、干净
容器重放,四项全过才有 PASS_ADAPTED——agent 的'我做完了'从不是输入。12 次
记录运行,1 次 PASS,11 次带失败复现的诚实 FAIL,包括一个 31/33 仍被拒绝的
案例。"

## 90 秒介绍

30 秒版 + :"最有价值的产出是失败分类学。真实运行暴露了 9 类失败,其中两类
是 harness 自己的 bug——prompt 污染和合同欠规范——被同一条证据链抓出来。
首个 PASS 的路径也因此不是调 prompt,而是把合同修到机器可判充分:typed
RequirementSpec、公开真值表、13 项确定性准入门、宿主输入守卫。修好规格后,
同一个模型单次预注册运行拿到 18/18 含 held-out,并在全新容器重放通过。"

## 5 分钟深讲(结构)

1. 问题定义:agent 自述 ≠ 可采用(31/33 案例开场)
2. 协议:合同冻结 → 充分性准入 → 单 agent 受控执行 → 四重独立验证 → 证据闭环
3. 失败分类学与两次自查自证(prompt 污染 / 合同欠规范)
4. 修复哲学:Specification & Responsibility over prompting
5. PASS_ADAPTED 解剖:agent 拿到什么、host guard 负责什么、gate 怎么判
6. 边界与负结果(null ablation、被忽略的 ledger、范围限制)

## 高频追问

**为什么不用 Codex / Claude Code 直接做?**
- 答:它们是更强的 agent,但本项目做的是 agent 之外的判定协议——任何 agent
  接进来都需要独立 verdict。项目刻意用低成本模型证明"约束域内、合同充分时,
  判定协议比模型能力更是瓶颈"。
- 不能说:低成本模型达到 Codex/Claude Code 能力(F10)。
- 追问预判:"那接上更强模型会怎样?"→ 诚实答:未测,是自然下一步。

**这不就是 CI Runner 吗?**
- 答:CI 假设测试对被测者可见且信任提交者;这里 oracle 对 agent 保密、
  存在 held-out 输入、有行为参考校准、有干净重放,且准入门在 agent 之前
  拒绝不充分的题目——是"考试院",不是"流水线"。

**Agent 和 Harness 的区别?**
- 答:系统里只有一个自主循环(mini-swe-agent DefaultAgent);其余全是确定
  性代码。PASS 里 agent 的贡献是 67 行 adapter;harness 的贡献是让这 67 行
  可被信任。

**为什么 31/33 仍然 FAIL?**
- 答:挂掉的 2 项是上游异常包装合同——生产里这是数据管道炸掉的那类缺陷。
  gate 无部分学分,失败在新容器确定性复现,所以 FAIL 是事实而非苛刻。

**Contract Adequacy 为什么重要?**
- 答:Gate 7 实测:一条规则只写在 YAML 注释里,agent 选了一个说得通的错误
  解读——这是任务作者的锅。若不把"合同充分"变成机器可判,失败归因就永远
  混乱。13 项检查里含"HARD 规则必须逐字进 prompt""布尔字段必须有真值表"。

**Input Guard 为什么不交给 Agent?**
- 答:text=None 这类确定性校验在两个域被 agent 反复遗漏(n=2)。它本就该是
  宿主契约的一部分——稳定错误码、进 adapter 前拦截。把它下沉后,agent 专注
  真正需要理解的语义映射。
- 不能说:guard 的工作是 agent 能力(F9)。

**PASS_ADAPTED 如何产生?**
- 答:Capability(含 held-out)∧ HostRegression ∧ Policy ∧ clean_adoption
  Replay,四个独立 verifier 的结构化结果进决策表;`demo verify` 可现场复算。

**Docker 安全吗?**
- 答:non-root、cap-drop ALL、network=none、digest 锁定——用于隔离/销毁/
  重放。不是恶意代码沙箱,SECURITY.md 明说(F6)。

**Trace 不可伪造吗?**
- 答:tamper-EVIDENT:hash 链能暴露事后篡改;拥有仓库写权限者可整链重写。
  诚实边界(F7)。

**Budget Awareness 无效为什么还保留?**
- 答:预注册单变量实验得到 null——这正是方法论工作的证明。删负结果的
  benchmark 不可信。

**Coverage Ledger 为什么不做成功率声称?**
- 答:两次真实检验:一次带来首次主动 Submit 但结果不变,一次被完全忽略
  (0/9)。跨任务效应 unsupported,默认关闭(F5)。

**为什么只有一个 Agent?**
- 答:归因。多 agent 时你无法回答"这个失败是谁的"。单循环 + 全确定性外围
  让每个失败可归因到 agent / task-author / harness 三者之一。

**不能泛化到什么范围?**
- 答:非 Python/需 GPU/私有仓库/大型应用全量融合/任意仓库(F1/F12);每个
  任务都需要人工合同+oracle+控制组工程。

**进企业生产还缺什么?**
- 答:多租户与鉴权、任务队列与并发调度、secrets 管理、oracle 生产流水线、
  更强沙箱(gVisor 级)、模型路由与重试策略、审计存储。这些是工程,不是
  研究缺口——当前定位是 research-grade MVP。
