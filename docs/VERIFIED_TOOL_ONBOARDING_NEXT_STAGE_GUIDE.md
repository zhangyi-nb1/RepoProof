# RepoProof 下一阶段开发指导：Verified Tool Onboarding Harness

> 日期：2026-08-25  
> 盘面基线：`main @ 812bb7b`；当前开发分支
> `codex/m7-managed-sidecar-tools @ 7ac1a09`  
> 文档目的：吸收“DeepSeek Harness 分析报告”最近一次同类产品调研，结合
> RepoProof 当前代码和证据边界，给出一条适合单人、短周期、稳定优先的后续路线。

## 1. 先给结论

RepoProof 的新定位合理，但还应再精确一层：

> **RepoProof 是一个 Verified Tool Onboarding Harness：它把 pinned public
> GitHub 仓库中的一个明确能力，转化为受管的本地 CLI/MCP 工具；系统优先采用
> 可审计的确定性包装，只有确实需要写适配代码时才调用 Coding Agent，最终由
> 独立验证、clean replay 和运营发布账决定结果，而不是由 Agent 自述决定。**

这一定义比“GitHub → MCP 生成器”更有差异化，也比“通用 Coding Agent”更可控。
它把 RepoProof 的价值放在三件已经有代码基础的事情上：

1. 判断一个能力是否适合被工具化，以及应该走哪条实现路线；
2. 为 Agent 提供受约束的合同、环境和公开反馈，而不是盲目让 Agent 自由开发；
3. 在 Agent 之外证明工具是否满足合同、是否真实采用上游、是否可重放、现在是否
   允许被 RepoProof 受管发布。

下一阶段不应该继续扩大验证系统，也不应该继续开发旧的“任意仓库适配到任意
宿主”路线。最值得补的是当前产品中间缺失的**能力分析与执行路由层**：

```text
GitHub repo + 用户能力意图
            ↓
Capability Analyzer（证据化识别能力表面）
            ↓
Capability Plan + 用户确认
            ↓
    ┌───────┴────────┐
    ↓                ↓
DIRECT_WRAP      AGENT_ADAPT
确定性生成        受限 Agent 实现
    └───────┬────────┘
            ↓
同一 Tool Contract / Verifier / Receipt / Replay
            ↓
Verified Registry → CLI / MCP / Audit
```

## 2. 本文如何使用引用会话中的调研

引用会话是设计输入，不是仓库事实源。本文对项目进度以当前 Git、
`docs/HANDOFF_STATE.md`、RFC 和代码为准；同类项目特征则以引用会话中的调研为
起点，并对关键方向参考了项目官方仓库或文档。

需要注意：当前交接文档存在版本漂移。

- `docs/CHATGPT_WEB_HANDOFF.md` 仍写着 M6 未合并、M7 未推送，是旧快照；
- 当前 Git 表明 M6 已合入并推送到 `main @ 812bb7b`；
- M7 分支已推进到 `7ac1a09`，强 U1–U4 回执候选已落地且分支已推送；
- M7 仍是 `EXPERIMENTAL / REVIEW_REQUIRED`，因为 v3 全链 E2E、OS 级隔离、
  导出包 clean replay 和经授权真实仓仍未关闭。

因此，后续对外材料必须先统一事实锚，不应继续复制旧快照中的“未合并/未推送”
表述。

## 3. 对同类项目的正确借鉴方式

以下不是要复制一组产品功能，而是要识别 RepoProof 应该复用什么、保留什么。

| 项目类型 / 代表项目 | 它解决的主要问题 | RepoProof 值得借鉴 | 不应照搬 |
|---|---|---|---|
| 能力发现与 MCP 生成：CAMEL-AI MCPify | 用 AST、LLM 或 Agent 从 Python API、CLI、Web API 中发现可暴露能力并生成 MCP 配置 | 多策略 detection、先发现 callable surface、生成结构化配置 | 把“检测到接口并能 serve”直接称为 verified；把整个仓库所有接口都暴露出去 |
| MCP 机械转换：FastMCP | 用低代码方式生成 MCP server，并支持 OpenAPI/FastAPI 等既有接口 | 成熟 MCP 协议层和确定性 schema 投影，减少自写协议代码 | 把 MCP 当作产品核心；一次镜像大量 endpoint，导致工具语义和权限面失控 |
| 极简入口：GitMCP | 通过非常短的 URL 变换获得针对仓库文档的 MCP 入口 | “给 URL 即开始”的低认知用户旅程 | 混淆“访问仓库文档”与“构建并验证仓库能力” |
| 运行与治理：ToolHive | MCP runtime、registry、权限、隔离、可观测与供应链治理 | 可信 registry、provenance、运行状态和权限是独立产品层 | 复制企业级 Gateway、Kubernetes、身份平台和大规模运维面 |
| 本地 Agent 与扩展：Goose | provider 可换、本地 Agent、MCP 扩展生态 | Agent backend 与产品价值解耦，扩展通过标准入口使用 | 把 RepoProof 做成另一个通用桌面 Agent |
| Coding Agent Harness：OpenHands、SWE-agent、mini-swe、DSH | Agent loop、工具接口、运行环境、上下文和长程执行 | Harness 对任务表面、ACI、错误反馈和运行环境的设计会显著影响效果 | 重写成熟 Agent runtime，或把某个模型/某个 backend 作为 RepoProof 品牌本体 |
| 工具目录与分发：Composio、Smithery 一类产品 | 工具搜索、连接、生命周期和分发 | 用户按能力发现工具；registry 是长期入口而不是构建结果附属文件 | 第一版引入账户、OAuth、云端托管和海量第三方连接 |

参考入口：

- [CAMEL-AI MCPify](https://github.com/camel-ai/mcpify)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [GitMCP](https://github.com/idosal/git-mcp)
- [ToolHive](https://github.com/stacklok/toolhive)
- [Goose](https://github.com/aaif-goose/goose)
- [OpenHands](https://github.com/OpenHands/OpenHands)
- [SWE-agent ACI](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/aci.md)
- [Composio](https://github.com/ComposioHQ/composio)

最重要的组合关系是：

```text
MCPify / FastMCP 提供“发现与机械暴露”的启发
mini-swe / DSH 提供“需要写代码时怎么执行”的能力
RepoProof 自己拥有“合同、独立验证、回执、重放、发布治理”
```

RepoProof 不应 Fork 大型 Harness 改名，也不应只给 MCPify 加几组测试。面试时最
容易解释、也最能证明独立贡献的做法，是通过窄接口选择性复用成熟组件，同时让
RepoProof 掌握路由与最终判定。

## 4. 当前已经成立的产品能力

下面只列当前仓库已有代码、测试或提交支持的能力。

### 4.1 已关闭主线

- M0–M4：产品章程、首个真实工具、半自动 intake、单命令旅程和两批真实仓
  dogfood 已完成；M4 数据是记录过的案例，不是任意仓库成功率。
- M5：ToolSpec v2 输出合同、T6–T9 一致性门、实际 stdout 独立解析、
  append-only release ledger、`ACTIVE / REVIEW_REQUIRED / REVOKED` 已关闭。
- M6：Studio 已接到 Core 单一事实源并合入 `main`；项目方三个固定案例预览已
  通过，仍缺两名目标用户理解测试。

### 4.2 当前实验扩展

- M7 已有固定 ToolSpec v3 managed sidecar、每次调用启动与回收、loopback
  协议、结构锚、MCP fail-closed 和强回执候选。
- `7ac1a09` 记录的测试基线是 `1455 passed + 60 skipped + 0 failed`。
- 但 M7 尚未满足 RFC-012 全部关闭条件，因此不能 `ACTIVE`，也不能成为当前
  对外主卖点。

### 4.3 当前最关键的结构性缺口

代码已经有不少“分析器零件”，但还没有形成清晰的产品路由：

- `tool_intake.py` 已能提取 distribution、import module、公开 API、CLI、
  许可证、依赖和风险；
- `support_policy.py` 已能给出四态准入；
- `strategy_selector.py` 已有 Python adapter、CLI subprocess、HTTP sidecar 等
  策略概念；
- 但 `tool_build()` 在 fake rehearsal 后固定发起一次真实 Agent 运行，没有
  “这个仓库根本不需要 Agent”的正式路径；
- 当前 intake 更像“仓库是否大致可处理”，还没有证明“用户意图对应哪个
  callable、输入输出怎样映射、为什么选择这条实现路线”。

这正是同类项目调研对 RepoProof 最有价值的启发：**补 detection 与 routing，
而不是再补一层代码生成。**

## 5. 冻结后的产品框架

### 5.1 三个平面

建议把当前系统对外解释成三个平面，而不是一条含糊的 Agent 流水线。

| 平面 | 负责什么 | 是否允许 LLM 决定事实 |
|---|---|---|
| Onboarding Plane | 仓库分析、能力候选、支持性、合同草稿、用户确认、执行路由 | LLM 可辅助意图解释和草稿；证据、准入与最终路由必须可审查 |
| Execution Plane | 确定性包装或 Coding Agent 适配；backend 可插拔 | Agent 只产候选实现，不产成功结论 |
| Proof & Release Plane | 输出合同、独立验收、上游采用回执、policy、clean replay、ledger、MCP 执法 | 不允许 LLM 判卷；缺证据即 fail closed |

### 5.2 两条实现路径

#### DIRECT_WRAP

适用于已经存在清晰、可静态定位的 Python callable，且输入输出能映射到当前
file-in/stdout 合同的仓库。

首版只支持很窄的机械映射：

- pinned Python distribution 可安装；
- 一个经用户确认的 importable callable；
- 输入为文件路径或文件文本二选一；
- 输出为文本，或可由固定 JSON serializer 输出；
- 无 secret、GPU、外网运行时和交互式状态；
- adapter 由受信模板生成，不允许任意 shell 命令。

DIRECT_WRAP 不调用 Coding Agent，但仍必须经过同一合同、上游采用证明、独立
验证和 clean replay。通过时内部 verdict 可继续使用已有 `PASS_DIRECT`。

首版不要同时支持“任意上游 CLI 的直接包装”。CLI 参数和输出常常不是稳定 API，
且子进程采用证明需要额外绑定；先把它作为高质量检测信号，默认转入
`AGENT_ADAPT` 或 `REVIEW_REQUIRED`。

#### AGENT_ADAPT

适用于 callable 明确，但需要有限输入转换、输出规范化、异常映射或依赖处理的
任务。它继续复用现有 mini-swe 主路径和验证体系。

DSH 保持 optional/experimental。除非出现 mini-swe 无法满足、且 DSH 能以可测
方式消除的具体阻塞，不应把“资格化 DSH”设为产品 alpha 的前置里程碑。

### 5.3 四种面向用户的分析结论

实现路径与支持状态不要混成一列：

| 支持状态 | 含义 | 下一动作 |
|---|---|---|
| `SUPPORTED` | 证据足以形成可确认的能力计划 | 用户确认后进入 DIRECT_WRAP 或 AGENT_ADAPT |
| `REVIEW_REQUIRED` | 仍在支持面附近，但 callable、许可证、输入输出或真值不足 | 要求用户补一个会改变路线的事实 |
| `UNSUPPORTED` | GPU、secret、无法 pin、不可独立验收或超出当前运行边界 | 停止，不调用 Agent |
| `EXPERIMENTAL` | 例如当前 managed sidecar，机制存在但可信关闭条件未完成 | 只能 fixture/研究使用，不能 ACTIVE |

## 6. 下一阶段按什么顺序开发

不要并行开多条大线。建议依次完成下面四个 Gate。

### Gate 0：事实与范围收口

目标：让项目所有入口描述同一个当前状态。

任务：

1. 更新 `CHATGPT_WEB_HANDOFF.md`、`HANDOFF_STATE.md`、README 和 RFC-012 的
   状态行，消除 M6/M7 合并、推送和强回执状态冲突；
2. 完成 M6 剩余两名目标用户理解测试，只测三个固定案例，不新增 UI；
3. 冻结 M7 功能面。只允许补 RFC-012 已注册的全链 E2E 或可信缺口，不做性能
   优化、额外协议、端口 UI、常驻服务或新语言；
4. 对外统一使用“受支持范围内的内部 alpha”，不使用“任意 GitHub 仓库自动
   成功”表述。

关闭条件：状态文档无冲突；两名用户能正确解释 historical verification、
operational release 与 package health；M7 仍明确标为 experimental。

### Gate 1：CapabilityPlanV1 与确定性路由

目标：在调用 Agent 之前，回答“发现了什么能力、为什么支持、走哪条路线”。

新增一个独立的计划产物，不复用 ToolSpec v3 的 delivery runtime，也不改写旧
冻结合同。建议形态：

```yaml
schema_version: 1
source:
  url: https://github.com/owner/repo
  commit: <full sha>
capability_goal: <用户原始意图>
detected_surfaces:
  - kind: python_callable
    locator: package.module:function
    signature: "(input_path: str) -> str"
    evidence: ["src/package/module.py:42", "tests/test_module.py:18"]
    confidence: HIGH
support_status: SUPPORTED
implementation_route: DIRECT_WRAP
delivery_profile: cli_v2
reason_codes: [PINNED_PUBLIC_PYTHON, SINGLE_FILE_CALLABLE]
risks: []
human_confirmations:
  - callable locator
  - input mapping
  - output contract and representative examples
```

设计约束：

- confidence 用 `HIGH / MEDIUM / LOW`，不要制造 0.87 一类虚假精度；
- 每个候选必须带文件/符号证据和排除理由；
- 路由规则确定性执行，LLM 最多做候选排序和自然语言草稿；
- LLM 建议不能把 `REVIEW_REQUIRED` 变成 `SUPPORTED`；
- 计划在用户确认前不可冻结，不得触发真实模型；
- 将计划摘要或哈希写入后续 run 元数据，使执行路线可追溯。

首版路由规则：

1. GPU、secret、无法 pin、非公开或无独立真值 → `UNSUPPORTED`；
2. callable/许可证/映射不明确 → `REVIEW_REQUIRED`；
3. 单一 Python callable + 受支持映射 → `DIRECT_WRAP`；
4. callable 明确但需要有限 glue code → `AGENT_ADAPT`；
5. HTTP/service 形态 → `EXPERIMENTAL`，除非未来 M7 正式关闭；
6. 决策无法解释时一律降级，不猜。

关闭条件：至少用 API 直包、CLI 信号、歧义仓、GPU/secret、service 五类零模型
fixture 证明路由稳定、顺序无关、重复运行逐字节一致。

### Gate 2：DIRECT_WRAP 确定性快路径

目标：证明 RepoProof 不是“所有问题都交给 Agent”，而是一个会选择最低风险
执行方式的 Harness。

任务：

1. 定义最小 `DirectAdapterSpec`：callable locator、input mapper、output
   mapper、异常映射；
2. 用受信模板生成适配器，不允许用户提供任意 command 或模板代码；
3. 把 `tool_build()` 拆成共享前后段：

   ```text
   confirm / pin / materialize
             ↓
       route executor
       ├─ direct compiler
       └─ coding agent
             ↓
   verify / receipt / replay / export / registry
   ```

4. 两条路径必须使用同一 ToolOutputContract、同一 held-out 隔离、同一 release
   ledger 和同一 MCP adapter；
5. DIRECT_WRAP 必须真正调用 pinned upstream，不能以模板代码重新实现能力；
6. 记录 `agent_invoked=false`、route 和证据，不把无模型路径计入模型成绩。

关闭条件：一个本地 fixture 在零模型情况下取得 `PASS_DIRECT`，且 never-call、
wrong-symbol、call-ignore-result、输出合同错误和 replay 漂移全部被拦截。

### Gate 3：AGENT_ADAPT 的一次有界公开反馈修复

目标：在不泄露 held-out 的前提下，让 Agent 对可修复的公开失败获得一次结构化
反馈，提升稳定性而不制造无限自治循环。

优先复用现有 `adoption/repair/failure_packet.py`、repair budget 和 guided repair
资产，不复活旧宿主产品路线。

首版只允许**一次**修复：

```text
initial candidate
      ↓
public verifier
      ├─ PASS → independent hidden / policy / replay gates
      └─ FAIL(agent-owned, public) → FailurePacketV1 → one repair
                                             ↓
                                      full verification again
```

可反馈：公开测试节点、稳定错误码、公开合同字段、允许修改的文件和剩余预算。

不可反馈：held-out 输入/期望、oracle 源码、签名密钥、隐藏 receipt 细节、能够反推
真值的差分内容。

以下失败不得交给 Agent 反复试：合同不足、许可证/支持面问题、Harness 自身故障、
ledger 或 package identity 损坏、held-out 失败、receipt 可信面缺失、OS 隔离缺口。

关闭条件：公开可修复 fixture 能在一次修复内恢复；不可修复和 hidden failure
诚实失败；泄漏负控全数落网；无第二轮、无隐式重试。

### Gate 4：Studio 收口与面试演示

目标：把新机制呈现清楚，不再扩展页面数量。

只修改现有“新建工具”和“活动”页面：

- 展示 detected surface、证据、支持状态和执行路线；
- 明确显示“本次不需要 Agent”或“本次需要受限 Agent 适配”；
- 显示为何拒绝，不用一个模糊的失败按钮代替 reason code；
- 构建后继续进入现有工具库、三栏可信状态和 MCP 操作，不新增第二个 registry。

固定准备三个演示：

1. `DIRECT_WRAP`：已有 Python API，零模型完成并通过同一验证链；
2. `AGENT_ADAPT`：需要少量 glue code，一次公开反馈后通过或诚实失败；
3. `UNSUPPORTED` 或 historical READY/current REVOKED：展示 Harness 会拒绝、会撤回，
   而不是只展示成功案例。

真实模型演示和新真实仓仍需单独授权。没有授权时先用确定性 fixture 完成 UI 和
机制验收，不为了录视频污染真实案例统计。

## 7. 测试与关闭标准

### 7.1 Capability Analyzer

- 同一 commit 与同一意图重复分析得到相同 plan；
- 候选顺序不因文件遍历顺序漂移；
- symlink、超大文件、动态 `setup.py` 不被执行或盲信；
- 模糊自然语言不会自动选择危险 callable；
- `UNSUPPORTED` 和 `REVIEW_REQUIRED` 路径模型调用数为 0；
- LLM 起草失败不会破坏静态分析事实。

### 7.2 路由与执行

- DIRECT_WRAP 不能触发 Agent backend；
- AGENT_ADAPT 默认使用 mini-swe，DSH 未资格化时 fail closed；
- 两条路径共享合同与最终 gate，不能各写一套“成功”；
- route、backend、model invocation 和 Product/Lab 计分字段进入 run 元数据；
- Product run 永不进入 Benchmark Lab 模型能力指标。

### 7.3 有界修复

- 只消费公开 failure packet；
- held-out 文本和 expected hash 不进入 Agent workspace、prompt、日志；
- repair budget 到 0 后立即停止；
- 修复后完整重跑，而不是只重跑原失败节点；
- Harness-owned / external failure 不归咎 Agent。

### 7.4 稳定性门

- 定向测试、全量 pytest、Ruff、compileall、`git diff --check` 全绿；
- worker 被杀、exit 0 无产物、并发写锁、损坏 ledger 继续 fail closed；
- 不引入孤儿进程、后台 daemon 或不受控网络；
- 新文档中的提交、分支和状态能由当前 Git 复核。

## 8. 性能策略：够快、稳定，不做过度优化

当前性能重点不是吞吐量，而是减少不必要的模型调用和不可控等待。

建议只执行四条纪律：

1. 静态分析与规则路由优先，能 DIRECT_WRAP 就不调用 Agent；
2. clone、安装、构建、Agent 和 replay 均使用已有有界 timeout；
3. 保持单个 Core 写任务串行，不建设分布式队列或多任务并发调度；
4. 先记录各阶段耗时和失败点，只有固定演示出现明显卡顿或超时才优化。

不要在目前设置没有实测依据的高并发、QPS 或毫秒级 SLO。对本地 alpha，“无
死锁、无无限重试、无孤儿进程、失败可解释、重复结果一致”比极限速度更重要。

## 9. M7 在新框架中的位置

M7 仍属于当前 Local Tool 产品，但它是 delivery profile 扩展，不是产品主线
入口，也不是旧宿主适配路线的复活。

建议当前处理方式：

- 保留现有代码、测试、强回执候选和 fail-closed marker；
- 允许补一个零模型 v3 `host_guided` 全链 E2E，使已有接线可复核；
- 不为赶 alpha 承诺 OS 级隔离，也不因此把 v3 提升为 ACTIVE；
- 不新增任意 URL、任意启动命令、daemon、显式端口或账户密钥；
- 在主演示中只把它说明为“扩展设计及诚实停点”，不把它当作已完成产品能力。

只有当 Capability Analyzer、DIRECT_WRAP 和现有 v2 产品旅程收口后，且用户确实
需要服务型仓库，才继续投入 M7 的 OS 隔离和真实仓 clean replay。

## 10. 明确暂时不做的事情

- 不继续开发旧的任意 Repository → 任意 Host 适配产品；
- 不扩 Benchmark Lab、模型比较、猎题、计分或研究 UI；
- 不 Fork OpenHands、Goose、DSH 或 MCPify 作为新主仓；
- 不一次支持多语言、浏览器、GPU、私有仓、云账户和常驻服务；
- 不做全仓函数自动暴露或大规模 OpenAPI endpoint 镜像；
- 不重新设计 Studio 五页或再建一套 registry；
- 不为了提高成功率放宽 verification、回执、replay 或 release gate；
- 不把一次真实仓成功写成通用成功率；
- 不在没有明确缺口数据时优化 Agent backend 或做复杂性能工程。

## 11. 面试时应该怎样讲这个项目

推荐用下面的叙事，而不是从测试数量或模型品牌开始：

> 许多项目能把函数或 API 暴露成 MCP，也有成熟 Coding Agent 能写 wrapper。
> RepoProof 解决的是它们之间仍然缺失的一层：先判断用户要的能力能否被可靠
> 工具化，选择确定性包装还是受限 Agent 适配，再在 Agent 之外验证能力、上游
> 真实采用和 clean replay，最后用 append-only 状态治理当前是否允许受管发布。

演示顺序：

1. 输入 GitHub URL 与能力意图；
2. 展示证据化 Capability Plan 和路线选择；
3. 展示 DIRECT_WRAP 不调用模型，或 AGENT_ADAPT 只获得有限公开反馈；
4. 展示独立验证、receipt 与 replay；
5. 展示 historical READY 但 current REVOKED 仍被 MCP 拦截；
6. 最后再说明 mini-swe/DSH 是可替换执行器，不是判官。

这个故事同时体现产品判断、Harness 设计、Agent 工程、可复现性和安全边界，技术
含量明显高于“把函数包成 MCP”，范围又小于重做一个通用 Agent 平台。

## 12. 下一次实际开工清单

按顺序执行，不要跳到 UI 或新真实仓：

1. 先修正文档事实漂移，并补 M6 两名目标用户测试记录；
2. 为 CapabilityPlanV1 写 RFC/Schema，只定义字段、路由规则和可信边界；
3. 基于现有 `tool_intake`、`repository_analyzer` 和 `support_policy` 实现五类
   零模型 fixture；
4. 在 Core 增加 `analyze → plan → confirm`，先不接 Studio；
5. 实现最窄的 Python callable DIRECT_WRAP 和 `PASS_DIRECT` 全链；
6. 复用现有 failure packet，给 AGENT_ADAPT 接一次公开反馈修复；
7. Core 门禁全绿后再把 plan 和 route 投影到现有 Studio；
8. 最后准备三个固定演示，经单独授权后再决定是否跑一个新真实仓。

如果时间只够完成一个新增里程碑，应选择 **CapabilityPlanV1 + DIRECT_WRAP**。
它最直接地吸收同类项目优点，减少 Agent 不确定性，形成清晰的 Harness 决策层，
而且可以完整复用 RepoProof 已经成熟的验证与发布治理资产。
