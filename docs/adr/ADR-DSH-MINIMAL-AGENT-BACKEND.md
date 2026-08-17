# ADR:DeepSeek Harness minimal 作为**不可信 AgentBackend**(2026-08-17)

> 状态:**已采纳**。授权:用户 2026-08-17 指令 ——"我计划进一步结合
> DeepSeek harness 项目对项目进行开发(使用其现有的模块功能,来引入本项目,
> 加快开发进度,并且保证项目功能)…前面的修改测试工作可以暂停,下面结合
> 这个文档的指导进行开发"。指导文档:
> `~/Downloads/RepoProof_DSH_Minimal_SDK_集成开发指导报告_20260817.md`(v1.0)。
> 本 ADR 记**决策与边界**;分阶段执行细节以指导文档 §16 为准,与盘上实况
> 冲突时以盘上实况与本 ADR 为准(该文档的内部事实源截至 2026-08-17 早于
> WH-PILOT-1 停批,个别陈述已过时,例:"6 发正式计分尚未开始")。

## 1. 决策

一句话:**执行平面可插件化,裁决平面冻结。**

```
AgentBackend(不可信候选生成器)
├─ mini-swe(现状,唯一自治循环,src/repoproof/agents/backend.py)
└─ dsh-minimal(新增:官方 deepseek-harness-sdk 0.1.0rc6 + bundled runtime,
               独立 worker 进程,strict minimal 组合)
```

RepoProof 保留全部任务生命周期:冻结契约、workspace 构建与隔离、oracle 与
hidden fixture、上游采用回执、capability/regression/policy 验证、干净重放、
Completion Gate、分池分类、台账与最终 Verdict。DSH 只是被调用、被隔离、被
审计的候选生成器 —— 它的任何输出(`final_response` / `finish_reason` /
session JSONL / "Done" 声明)**永远不产生 PASS**,只作诊断输入。

## 2. 为什么是现在(依据,均已在盘上)

- S2′ 两批消融(批 14/15)对 GPT 代际归档关闭;S3/S4/S6 无暴露靶点;S5 会被
  假包骗出错误正信号 —— **"再猜一个自研小机制"这条路的边际证据已经打完**;
- WH-PILOT-1 停批作废(`ea075e8`):停轮规则在公开面基线全绿的 HB 族上必然
  误停 —— 引导臂只拿到合约 33% 调用量。**指导文档阶段 0("先封闭当前
  pilot")的前提由该收口满足**;DSH 提交自本 ADR 起全部落在停批之后,不入
  该批任何 generation;
- 同一收口里的送达量实证(30 调用 → delta 0/5;55 调用 → 5/5,高于盲攻上界
  4/5)说明 DeepSeek 在 8042 上的失败**至少部分是送达/终止协议问题而非纯能力
  问题** —— 这正是"换 Agent Loop / 终止边界"能回答的问题域(指导文档 §19
  假设族 H1/H2),自研臂间消融回答不了(两臂共享同一循环)。

## 3. 命名消歧(先立此存照,防台账歧义)

**"H0/H1/H2"三个编号在仓内已被占用两次,语义不同:**

| 轴 | 取值 | 出处 |
|---|---|---|
| harness_mode(同一 mini-swe 循环的引导面开关) | `guided`(WH 记 H2)/ `minimal`(WH 记 H0) | WH-PILOT-1 预注册 |
| backend(候选生成器整体替换) | 指导文档记 H0=mini-swe / H1=dsh-minimal | 指导文档 §0.1 |

**决**:代码与台账**不再新增 H 编号**。backend 轴一律用显式字段:
`backend_id ∈ {mini-swe, dsh-minimal}` + `runtime_profile_id`
(如 `rt-dsh-minimal-0.1.0rc6-v1`),入台账、入三面指纹。代际字符串的具体
拼法随阶段 2 seam 落地时定,原则只有一条:**非默认 backend 的发次必须在
指纹与代际上可分,不与任何既有批并池**。文档引用 H0/H1 时须注明是 backend
轴。

## 4. 信任边界(冻结,后续阶段不得放松)

只能由 RepoProof 控制:Task Contract、base commit、上游工件身份、oracle、
hidden fixtures、verifier 代码、Completion Gate、分池分类器、可信 usage
台账、干净重放环境、最终 Verdict。

一律视为不可信(只作诊断):模型 reasoning、DSH `final_response` /
`finish_reason` / session JSONL、agent 写入的一切日志与"证据"、公开测试的
agent 自报结果。

**结构约束**(不是口头约定):oracle / verifier 源码 / 台账对 DSH worker
**拓扑不可见**(不挂载、不共享目录);worker 环境变量走 allowlist,不继承
父进程全量 env;`cwd` 不当沙箱用(官方 minimal 是 `danger-full-access` +
裸本地 fs)—— 隔离靠 disposable checkout + 进程组 + host_guard 保护目录
既有机制,容器化列为 OS 阶段增强,不作第一轮前提。

## 5. 供应链钉死(外部事实已实核)

2026-08-17 对 PyPI 实测核验(`pypi.org/pypi/*/json`),与指导文档所载
**逐字一致**:

```
deepseek-harness-sdk == 0.1.0rc6(latest,MIT,pre-release)
  py3-none-any        sha256 8a05421be4298196cf94383e0a3164b020f5f5977a8d30019cc5add64cb208eb
deepseek-harness-runtime-bin == 0.1.0rc6(SDK 强制同版)
  macosx_14_0_arm64   sha256 2bbd65edd52dfc340d74f88a890e8031a272a820e58406c2de1f5f5dee51bd9f  ← 本机平台
  manylinux x86_64    sha256 d7261d3bdadfa8d10ab03fd06c6bbc66a182ae27d39892a0eb7c2ce9d63a5448
  manylinux aarch64   sha256 99d0ef334a4e3cb178d7b0302bbdd01c8dde6068ee5fe8b01e074541db5c7747
```

- 封存走既有 `execution/provisioning.py`(联网只在 provision 侧,
  `verify_sealed` 签名无 `allow_network`),落
  `~/RepoProofRuntimes/rt-dsh-minimal-0.1.0rc6-v1/`;
- hash 不匹配 **fail closed**;不追 `master`、不装浮动 `latest`、正式运行
  路径禁止联网重装;
- 官方 `minimal.cordis.yml` 原样固化(记 source_commit + sha256),派生
  配置必须换 composition id —— **第一轮不派生**;
- MIT 义务:`third_party/deepseek-harness/{LICENSE,NOTICE.md}`;
- **第一轮 strict minimal only**:不启用 standard / Code Mode / subagent /
  todo / web / context compaction / skills / 额外 planner —— E 轨已付过
  "多变量不可归因"的学费,不再拼十件套。

## 6. 预算与密钥

- SDK 的 `max_tokens` 只是**每次请求输出上限**,不是总预算。总预算
  (请求数 / 总 input / 总 output / 墙钟)由 RepoProof 在 worker 外部强制:
  超限 → 标记 → 终止进程组 → 宽限 → 强杀 → 冻结诊断 worktree。**只让
  Python 调用超时返回而放任子进程后台烧钱,视为缺陷**;
- usage 以 host 侧去重后的 normalized trace 为唯一事实源(流式双终态双计数
  是仓内已付学费的病,H7 系钉在前,DSH event adapter 必须带同型去重与对账
  selfcheck);
- **密钥铁律不变**:AI 不经手密钥,env 由用户注入;worker 只拿 allowlist
  过滤后的最小环境。host-side proxy(短期 run token)列为阶段 4+ 增强,
  第一轮至少做到:专用变量名、不落 argv/日志/工件。

## 7. 资格路线(沿仓内既有机器,不新造词表)

- profile 生命周期用仓内词表:`experimental → candidate → qualified →
  default`(指导文档的 draft ≈ experimental);晋级走 `promote_profile` 一路;
- `rt-sidecar-*` 的资格**不迁移**;`rt-dsh-minimal-0.1.0rc6-v1` 独立走全程:
  F0 四形态电池、C1–C15 canary、M-DSH 变异条目、假阳侧不误杀 + 负控各红各位;
- 真实模型 qualification(DQ-SDK)与 backend 对照(E1 桥)各自**新预注册**;
  `sqlglot-8042` 是已见任务,对照批分池
  `counts_toward_model_capability=false`,其结果不得写成模型能力或
  "DSH 普遍更强/无效";
- **预算等额原则**(WH 停批的教训直接搬来):HB 契约是 per_round 语义,
  DSH 单 session 发次必须拿**等总额**(`effective_budgets` 同一换算),
  且对照批判读前先核**送达量**(送达率 <80% 合约总额即停批 ——
  WH 停批报告 §五 的硬前提在 backend 对照上同样适用)。

## 8. 第一阶段不做清单

不跟 `master` / 不复制 DSH TypeScript 源码进仓 / 不 fork Cordis /
不改 mini-swe 行为(seam 包装必须字节等价)/ 不在同一提交里重构 mini-swe
又实现 dsh backend / DSH 发次不与既有任何批并池 / treatment 未激活不估计
效应 / 一发通过不升 default / 不把 8042 或任何已见任务重新计入 held-out。

## 9. 与被暂停线的关系

WH 停批暴露的修复待办(停轮条件补 `exit_status` ∧ 交付物、
`host_guided.py:2802` 硬编 `guided:True`、HB-DSENTRY 两发的 held-out 重跑
标记)属于**被暂停的既有线**,不混入 DSH 提交;它们在盘上有记录
(`WH-PILOT-1-stop-report-20260817.md` §六),不会丢。DSH 线推进到阶段 8
(对照批)前,若需用到 guided 路,先按该待办修复并重新冻结 —— 但第一轮
对照的 mini-swe 臂是单轮最小模式,不经过停轮规则,不被该缺陷阻塞。
