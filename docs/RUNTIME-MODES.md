# RepoProof 最终运行模式(RT)与 Profile 生命周期 — 长期指导文档

> 立于 2026-08-14。来源:`~/Downloads/RepoProof_测试模式_执行器升级与最终
> 稳定运行方案.md` §11–15,已按盘上现状逐条核对。
> 配套:测试模式体系见 `docs/testplans/TESTPLAN-V2-OFFERCLAW.md` §11;
> 执行器升级见 `docs/EXECUTOR-UPGRADE-PLAN.md`。

**总纲(第一原则)**:**产品运行必须复用测试中通过的同一条代码路径。**
不允许"测试走严格 harness、产品运行绕过 harness"。RT 模式不是新写的产品
逻辑,而是给既有管线的三种**出口**。

---

## §0 盘上现状核对(来源文档有一处与盘不符)

来源文档把 apply/rollback、offline recheck 列为"最终必须内置"的待建项。
**盘上已有相当部分**,不得重复立项:

| 组件 | 盘上位置 | 状态 |
|---|---|---|
| ApplyManifest / 暂存 / 应用 | `adoption/delivery/apply_manifest.py`、`staging.py`、`apply.py`、`apply_flow.py` | **已有** |
| 回滚 | `adoption/delivery/apply.py::rollback` + `_rollback_written` | **已有** |
| UI 应用服务 | `ui/services/apply_service.py` | 已有 |
| 证据包导出 / 校验 | CLI `export-bundle` / `verify-bundle` / `verify-trace` | **已有** = RT-3 内核 |
| 干净重放 | host-run 内 `replay` 阶段(批 11–13 均出 `replay: PASS`) | 已有 |
| 完成闸门 | `gate_report.py` + `bench_records.count_passes()` | 已有 |
| 主目录护栏 / 一次性 worktree | `harness/host_guard.py`、`runner/host_guided.py`(`main_dir_integrity`) | 已有 |
| Provider preflight | `scripts/model_preflight.py` | 有,但**是手动脚本、非强制门**(S1 修) |
| Profile Registry | — | **无**,需新建(§3) |
| Overlay Venv / Import Provenance / Data Namespace / Drift Gate | — | **无**,需新建(§2.2) |
| `LOCAL_VERIFIED_PENDING_REPLAY` 状态 | `bench_records.PASS_VERDICTS` 只有 PASS/PASS_ADAPTED | **无**,需新增词汇(§1.1) |

---

## §1 三种运行模式

### RT-1 Guarded Local Adoption(默认交互模式)

面向"用户本机已有一个健康运行的项目"这一主用例。

```text
Host Baseline(先量,后动)
  → Disposable Worktree(原项目只读)
  → Qualified Agent Profile(见 §3)
  → Bounded Repair(公开测试反馈,轮数有界)
  → Public Tests
  → Local Host Regression
```

**唯一允许的输出状态**:

```text
LOCAL_VERIFIED_PENDING_REPLAY
```

**不得**直接输出 `PASS_ADAPTED` —— 本机环境有残留、有隐藏依赖、有用户
本地漂移,不构成采用依据。

用途:快速开发、低延迟、本机已有完整环境、不想从零搭宿主。

#### §1.1 需要新增的状态词汇(改动 `bench_records.py` 时的红线)

`LOCAL_VERIFIED_PENDING_REPLAY` **绝不可**进入 `PASS_VERDICTS`。闸门统计
仍只认 `{PASS, PASS_ADAPTED}` ⋈ 裁定后的 `effective_verdict`。新增词汇要
配钉死:喂一条 `LOCAL_VERIFIED_PENDING_REPLAY` 进 `count_passes()`,
passes 必须不增(与 `test_false_pass_not_counted_by_substring` 同族)。

---

### RT-2 Verified Adoption(最终交付模式)

在 RT-1 的产物上继续:

```text
Freeze Adaptation
  → Hermetic Clean Replay(Docker / devcontainer / CI,固定镜像)
  → Capability → Regression → Policy
  → Completion Gate
```

**只有本模式可以输出 `PASS_ADAPTED`。**

环境由用户 / harness / CI 预先构建,**不让 coding agent 在任务预算内从零
搭环境** —— 环境构建与能力适配是两个问题,混在一起就无法归因(失败到底
是环境、模型、harness 还是目标能力?)。

---

### RT-3 Offline Evidence Recheck(不调用模型)

```text
verify-bundle      证据包哈希/引用完整性
verify-trace       轨迹链完整性
gate_report --check 重算完成闸门
clean replay(可选) 对既有 adaptation 重放
```

**用途与意义**:用户、面试官或 CI 可以在**没有任何外部 AI**的情况下
重新核验既有结论。这是"不依赖外部 AI 裁定"落地的那一块 —— 已基本具备,
缺的是把三个命令合成一个入口。

---

## §2 最终系统里的 AI 边界

### §2.1 模型只做四件事

```text
观察 · 选择工具 · 生成修改 · 按公开反馈修复
```

**不负责**:定义成功、修改 requirement、读取 hidden oracle、判自己 PASS、
决定 apply、决定 rollback、裁定证据。

> **口径澄清(重要)**:"不借助外部 AI" **不等于**"不使用模型"。RepoProof
> 的核心工作本身需要一个 LLM coding agent。它的意思是:**不再需要 Claude /
> GPT / 人工分析者在 RepoProof 外部替系统解释日志、判断 PASS、挑选修复
> 结果、决定能否写入项目**。模型是**不受信任、可替换的编码 Worker**。

### §2.2 Guarded Local Execution 必须包含的组件

`已有` 见 §0;以下为**待建**清单(RT-1 上线前逐项落地,每项走 F0 自检):

```text
HostExecutionProfile      宿主环境指纹(解释器/依赖/入口)
Overlay Venv              叠加式虚拟环境,宿主 venv 不可写
Import Provenance         导入来源可溯(防"看着像装了其实没有")
Secret Allowlist          密钥白名单,只经进程环境
Network Approval          网络默认禁,逐次批准
Process Group             进程组管理,防 orphan
Data Namespace            数据命名空间隔离,防污染用户数据
Project Drift Gate        运行期间用户改了原项目 → 拒绝 apply
```

已有的 `OriginalTreeNoTouchGuard` 语义由 `main_dir_integrity` 承担
(批 11–13 四发全部 `ok`),但它目前是**运行后校验**,RT-1 需要它成为
**运行前 + 运行中 + apply 前**三道。

---

## §3 Profile 生命周期(新建 Profile Registry 的依据)

每个执行 profile(provider × tool × context × budget 四类 hash 的组合,
定义见 EXECUTOR-UPGRADE-PLAN S1)必须有明确状态:

```text
experimental → candidate → qualified → default/optional → deprecated
```

| 状态 | 准入条件 | 允许用途 |
|---|---|---|
| **experimental** | 机制刚实现 | **只跑 F0**,不给真实用户 |
| **candidate** | canary 通过 + 四类 hash 完整 | 允许内部 benchmark(E1/DQ) |
| **qualified** | provider canary 100% · **未见任务**有有效 PASS · False Pass = 0 · hidden 泄漏 = 0 · no-touch host 通过 · clean replay 通过 | 允许进 WH/HB,允许 RT-1 |
| **default** | 再加:soak 稳定 · provider 故障可恢复 · apply/rollback 稳定 · 成本延迟可接受 | 产品默认 |
| **deprecated** | 被更优 profile 取代 | 只读,历史发次仍可复核 |

**红线**:profile 任何字段改动 → 新 profile ID + 新批次。历史发次绑定的
profile 不可被静默改写(与"预注册冻结后不改"同族)。

---

## §4 模型路由:benchmark 禁止,产品可选

### §4.1 Benchmark 模式禁止路由

同一 run 必须固定 `model / provider / profile / budget`。否则无法归因。

### §4.2 产品可加**确定性**路由(数据足够之后)

由确定性 `task_shape`(文件数 / 接入点 / 状态持久化 / 生命周期 /
协议边界 / 安全语义 / 回归面 —— 本仓已有八维评分)映射到 tier,
tier 映射到 qualified profile。**不能让另一个 AI 临时决定选哪个模型。**

### §4.3 Cheap-first Escalation(后期可选,首版不默认开)

```text
先用便宜模型 → 公开进展停滞(确定性触发器)→ 从 best state 升级强模型
```

必须满足:用户显式开启 · 预算独立 · 触发器确定性 · **hidden oracle 不参与
反馈** · trace 标记模型切换 · **不用于模型 benchmark**。

---

## §5 到 RT 之前必须先过的门(顺序不可颠倒)

```text
E1 执行器消融(阶段 A,当前)
  → DQ Provider 资格
  → WH 弱模型增益(未见任务)
  → HB 能力阶梯(冻结 harness)
  → OS soak / 故障恢复 / apply-rollback 崩溃注入
  → RT 上线
```

**OS 阶段的故障注入清单**(RT 上线前必须跑通,均为确定性注入):

| 面 | 注入项 |
|---|---|
| Provider | 503 · 超时 · usage 缺失 · SSE 中断 · tool result 重放 · 重试边界 |
| 本机执行 | 用户中途关 UI · worker 崩溃 · orphan 进程 · worktree 漂移 · overlay venv 损坏 · 磁盘满 · 端口冲突 |
| 上下文 | 超长输出 · artifact 丢失 · projector 恢复 · checkpoint resume · context profile hash 不一致 |
| Apply/Rollback | apply 中途崩 · rollback 中途崩 · 用户改了文件 · 依赖变化 · 数据命名空间污染 · 重复 rollback |

关注指标:`Run Recovery Rate` · `No-touch Original Host` · `Orphan Process
Count` · `Replay Success` · `Rollback Success` · `Profile Drift` ·
`Provider Fault Attribution`。

**OS 阶段不再调模型 prompt** —— 那是 E1/DQ 的事,混进来就无法归因。

---

## §6 明确不做的运行方式

1. 产品运行绕过 clean replay 或 completion gate;
2. 让外部 AI 解释结果后人工写 PASS;
3. RT-1 直接输出 `PASS_ADAPTED`;
4. 让 coding agent 在任务预算内从零搭环境;
5. 让执行后端(含未来的 DSH bridge)直接拿到 oracle 路径 / Docker socket /
   宿主密钥 —— 它只能**提出**工具动作,真实执行必须走本仓 policy 环境;
6. 首版就开 cheap-first escalation 或 AI 决定的模型路由。


---

## §7 Profile 晋级判据(2026-08-14 落地)

判据冻结在 `src/repoproof/execution/profile_promotion.py`(G1–G8),
判定与留痕走 `scripts/promote_profile.py`。

**每一级问的是不同的问题**,这是整份设计的骨架:

| 目标级 | 问的是 | 判据 | 谁能判 |
|---|---|---|---|
| → candidate | **机制自己站不站得住?** | G1 拓扑成立 · G2 假阳侧不误杀 · G3 负控各红各位 · G4 每族谓词红过也绿过 · G5 变异全捕且守护条目在场 | **零模型可判** |
| → qualified | **真模型跑得动吗?** | G6 ≥2 个模型 profile 且 ≥1 发诚实通过 · G7 无未决假通过 | **必须有真实发次** |
| → default | **该不该成为默认?** | G8 —— 这是取舍(成本、语义、对既有发次的影响),不是测量 | **机器判不了** |

三条纪律:

1. **证据缺失一律拒绝,不假设。** 一个查不到证据就默认放行的闸门,与没有
   闸门的区别只在于它会让人误以为有闸门。
2. **判不了 = 不通过**,不是"暂且通过"。凑几个数就自动设默认,等于把一个
   取舍伪装成一个测量。
3. **晋级必须留痕**(`docs/evidence/profile_lifecycle/promotions.jsonl`):
   凭什么、依据哪份证据、哪几条判据过了。直接改 lifecycle 字段自封,等于
   把"凭什么"整个抹掉 —— 由 `tests/test_profile_promotion.py::P6` 钉死。

### 变异证据的有效期(踩了三次才定下来)

G5 要一份"对当前代码仍然成立"的变异证据。前两种写法都错:

- **按 mtime 取最新** —— 变异闸门在临时 git worktree 里跑,checkout 出来的
  文件 mtime 全一样,"最新"其实是随机取;
- **只认 HEAD 那一份** —— 严格是对的,但会死锁:证据按 HEAD 命名,而**提交
  证据本身又产生新的 HEAD**,于是 HEAD 上永远没有证据,G5 永远过不了。
  一道永远过不了的判据不是严格,是墙。

现在的语义:**证据在它守护的文件没变期间仍然有效**。守护集直接从证据自己
里读(每条变异都记了 `file` 与 `catchers`),所以证据是自足的,不必去 import
登记簿。这与语义指纹那套是同一个想法 —— 不相干的改动不该让证据作废,相干
的改动必须让它作废。

### 现状

| profile | 拓扑 | 生命周期 | 依据 |
|---|---|---|---|
| `rt-inprocess-v1` | in_process | **default** | 既有全部发次的行为,先于本机制存在 |
| `rt-sidecar-browser-v1` | sidecar | **candidate** | G1–G5 全过(2026-08-15);真 browser-use 0.13.7 + 封存 Chromium |
| `rt-sidecar-canary-v1` | sidecar | **candidate** | G1–G5 全过(2026-08-14),留痕在案 |
| `rt-sidecar-markdown-it-v1` | sidecar | experimental | 控制矩阵专用,未申请晋级 |

### `rt-sidecar-browser-v1` 的封存件(2026-08-15)

一次性 harness-only 联网 provisioning 的产物,`~/RepoProofRuntimes/`(受
`host_guard` 保护,**不在** bench 根白名单里 —— 那是 LESSONS #29 判过的错法):

```
.venv/                    330M   browser-use 0.13.7 @ 32601887cfbc(本地钉版快照)
browsers/chromium-1234/   554M   Google Chrome for Testing 151.0.7922.34(完整构建)
requirements.lock         106 条依赖闭包
runtime_manifest.json     3 个钉版来源 + 内容摘要
```

**联网边界靠结构不靠承诺**:`allow_network` 只存在于 `provision()` 的签名里,
execute 侧的 `verify_sealed()` 根本没有这个参数 —— 想在发次期联网,得先改 API
形状。agent 的会话环境一个字不改(仍 `PIP_NO_INDEX` + 冻结 wheelhouse)。

**上游本体不走网络**:从本地钉版快照装(commit 与 T3 契约逐字相同),网络只
解析依赖闭包,随后冻进 lock 并计入封存摘要。

**浏览器封存后不再重下**(用户 2026-08-15 指令)。完整 Chromium 而非
`--only-shell`:headless shell 是独立精简构建,拿它当浏览器等于自带一个"能力
缺失"的混杂变量。

矩阵实测(36s,零模型,死代理下只放行 127.0.0.1):

| adapter | 结果 | 红在哪 |
|---|---|---|
| a0 真正使用结果 | **PASS** | — |
| a1 不调用 sidecar / a2 自己重实现 / a3 假包 | FAIL | U3, U4 |
| **a4 调了但不用结果** | FAIL | **仅 U4** |
| a5 调错 symbol | FAIL | U2, U3, U4 |
| a6 replay 旧 receipt | FAIL | U1.run_nonce, U1.count, U3, U4 |
| **a7 改 receipt(删行)** | FAIL | **U1.chain, U1.count**(签名全绿) |
| a8 伪造 receipt(增行) | FAIL | U1.signature, U1.count, U3, U4 |

**a2 不是稻草人**:它真抓页面、真按 flex 规范算,数学上完全正确,仍然对不上
排版引擎的定点 LayoutUnit 与余量分配(五个数全差)。这条一旦变绿,说明能力
可重实现了,采纳判据在这套 fixture 上当场失去判别力。

canary 到 candidate 的含义要划清:**机制站得住**(拓扑成立、诚实实现不被
误杀、八条攻击各红各位、变异全捕);**不含**"真模型跑得动" —— 我们的
adapter 是照着判据写的,那叫出题人自己会做,不叫题目可解。要往 qualified
走,得等 T3-SIDECAR v1 上的真实发次。
