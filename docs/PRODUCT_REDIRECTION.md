# RepoProof 产品方向重构说明：从“通用仓库适配验证”到“GitHub Capability → Verified Local Tool”

> 版本：产品方向讨论稿  
> 目的：在继续开发前，从产品视角重新审视 RepoProof 的目标、边界、价值与最终形态。  
> 当前阶段原则：**先确定“为什么做、为谁做、做成什么”，暂不展开具体工程实现。**

---

## 1. 为什么需要调整原来的项目目标

### 1.1 最初的目标是合理的，但问题空间过大

RepoProof 最初想解决的问题可以概括为：

> 给定一个 GitHub 上游项目和一个现有宿主项目，让 Agent 自动完成能力适配，并由 RepoProof 独立证明适配是否真正成功。

这个方向本身有价值，因为现实中确实存在大量类似需求：

- 在 GitHub 发现一个有用的新项目；
- 希望把其中某项能力接入自己现有的软件、学习工作流或个人项目；
- 通用 Coding Agent 可以帮助完成，但往往需要用户反复解释、纠正和验收；
- 最终“Agent 说已经完成”也不等于结果真的稳定、可复现、没有破坏原项目。

因此，原始问题并不是伪需求。

真正的问题在于，它同时要求系统解决太多开放变量：

- 任意 GitHub 项目；
- 任意宿主项目；
- 任意能力；
- 任意依赖环境；
- 任意集成方式；
- 长程 Agent 执行；
- 自动理解需求；
- 自动完成集成；
- 自动构造验收标准；
- 自动验证；
- 还要进一步形成严格的 held-out benchmark，对不同 Harness / 模型进行公平比较。

对于个人项目而言，这实际上已经同时覆盖了：

1. Coding Agent Runtime；
2. Harness；
3. 软件集成；
4. Task Authoring；
5. Verification；
6. Benchmark Construction；
7. Model Evaluation。

即使直接使用成熟开源 Harness，也只能复用其中一部分能力，不可能自动消除整个问题空间的复杂性。

### 1.2 当前开发结果说明：执行器不是唯一、甚至不是最大的瓶颈

前期开发中，一个重要假设是：

> 如果 Agent 失败主要是因为长程执行能力不足，那么引入更成熟的 DeepSeek Harness 组件后，应该明显提高成功率。

实际结果说明事情没有这么简单。

引入 DSH 后，项目确实获得了更成熟的 Agent Runtime 能力，例如：

- 更完整的 Agent Loop；
- 持续工具执行；
- Bash / Editor；
- 会话状态；
- Runtime Profile；
- 预算控制；
- 可插拔执行后端。

这些都明显节省了“重新造 Agent 基础设施”的开发工作。

但是模型最终是否成功，还受到很多其他因素影响：

- 用户需求是否足够明确；
- 任务是否被正确冻结；
- Agent 能否看到完成任务真正需要的信息；
- 测试是否公平；
- 隐藏验收是否偷偷要求了未公开语义；
- 上游项目是否适合当前集成方式；
- 任务本身是不是已经超出模型稳定能力范围；
- 不同 Agent Loop 与不同模型的行为是否匹配。

因此，前期一个需要修正的认识是：

> **可插拔 Harness 能显著降低执行基础设施开发成本，但“接入成熟 Harness”并不等于“模型成功率自动发生质变”。**

### 1.3 当前 RepoProof 的真正优势已经逐渐清晰

随着项目推进，RepoProof 最有价值的部分逐渐不是：

> “我也实现了一个能让 Agent 改代码的系统。”

因为 Codex、Claude Code、mini-swe-agent、DeepSeek Harness 本身已经能很好地承担这一层。

RepoProof 真正形成特色的地方是：

> **不直接相信 Agent 的完成声明，而是通过合同、隔离、独立验证、回归检查、Clean Replay 和证据链判断产物是否真正可用。**

也就是说，RepoProof 已经逐渐形成了两类能力：

#### A. Execution Plane

负责：

> 怎么让 Agent 做事。

这部分可以大量复用：

- mini-swe-agent；
- DeepSeek Harness；
- 未来其他 Coding Agent。

#### B. Verification Plane

负责：

> 怎么证明它真的做对了。

这部分才是 RepoProof 更具有自身特色的核心：

- Task Contract；
- Contract Adequacy；
- Capability Verification；
- Regression Verification；
- Policy；
- Upstream Provenance / Receipt；
- Clean Replay；
- Completion Gate；
- Evidence Report。

因此，项目方向应该围绕这个已经形成的优势重新收敛。

---

## 2. 新项目预期：GitHub Capability → Verified Local Tool

新的项目不再要求：

> 把任意 GitHub 项目完整、深度地融入任意现有宿主项目。

而是聚焦一个更明确、也更贴近日常使用的场景：

> **用户在 GitHub 发现一个有价值的开源能力，希望系统自动把该能力转换为自己电脑上可以直接使用、也可以被 AI Agent 调用的本地工具。**

例如：

- 一个 GitHub 项目能把 PDF 转 Markdown；
- 一个项目能提取网页结构化信息；
- 一个项目能解析某种文档；
- 一个项目有很好的代码分析能力；
- 一个项目有一套数据转换能力；
- 用户并不想完整学习、配置和长期维护整个项目；
- 用户只是希望获得其中一个明确能力。

新的 RepoProof 要做的是：

```text
GitHub Repository
        +
User Capability Goal
        ↓
理解目标能力
        ↓
判断是否适合自动 Tool 化
        ↓
形成明确的 Tool Contract
        ↓
Harness 驱动 Agent 长程执行
        ↓
生成 Local Tool
        ↓
RepoProof 独立验证
        ↓
Clean Replay
        ↓
Verified Local Tool + Evidence Report
```

因此，项目的中心从：

> Repository-to-Repository Adaptation

转变为：

> **Repository Capability-to-Local Tool Onboarding**

---

## 3. 新项目的产品定位

### 3.1 一句话定位

> **RepoProof 是一个将 GitHub 开源能力自动转化为经过独立验证的本地 AI Tool 的 Agent Harness。**

### 3.2 更完整的产品描述

> RepoProof 面向这样一种高频场景：用户在 GitHub 中发现一个有价值的开源项目，但真正把其中某项能力变成自己电脑上可以直接使用、或者能够被 AI Agent 调用的工具，仍然需要阅读文档、配置环境、理解 API、编写包装代码、处理依赖并人工验证结果。
>
> RepoProof 将这一过程固定成一个受控 Harness Workflow。用户只需要提供 GitHub Repository 与目标能力，系统负责分析项目、判断任务是否适合自动执行、冻结目标 Tool Contract、驱动可插拔 Coding Agent 完成长程实现，并通过独立测试、回归验证、运行策略检查和 Clean Replay 判断工具是否真正可用。
>
> 最终交付物不是一句“Done”，而是一个可运行、可重放、有来源、有验收证据的本地工具。

### 3.3 RepoProof 不是什么

为了控制项目规模，新定位下需要明确：

RepoProof **不是**：

- 一个比 Codex / Claude Code 更强的通用 Coding Agent；
- 一个能自动完成任意软件工程任务的平台；
- 一个能把任意 GitHub 仓库融入任意大型现有系统的自动开发工程师；
- 一个自动复刻任何开源项目的系统；
- 一个形式化证明系统；
- 一个承诺 100% 自动完成所有 GitHub 项目的工具。

RepoProof 更像：

> **一个专门针对“GitHub 能力接入本机”这一垂直任务设计的 Agent Harness + Verification System。**

---

## 4. 为什么“Local Tool”比“任意项目适配”更适合作为新的核心产品

### 4.1 输出形态更加标准

原来的宿主适配问题是：

```text
GitHub A
→ 项目 B
```

项目 B 可能是：

- Web 后端；
- RAG 系统；
- GUI；
- Notebook；
- CLI；
- 多服务系统；
- Python；
- JavaScript；
- C++。

每个宿主项目都是一个新的世界。

新的目标固定为：

```text
GitHub Capability
→ Standard Local Tool
```

目标输出相对统一，因此 Agent 的工作流也可以更加稳定。

### 4.2 更符合个人真实使用习惯

很多用户真正需要的并不是“我要长期维护整个 GitHub 项目”。

更常见的是：

> “我看中了它的某个能力，我想直接用。”

例如：

> “这个项目的网页抽取挺好，我以后想本地调用。”

> “这个 PDF 项目效果不错，我只想把它的表格抽取包装成一个命令。”

> “这个 GitHub 工具有一个很好的数据清洗功能，我希望 Claude/Codex 能直接调用。”

Local Tool 正好解决的是“能力使用”而不是“项目所有权”。

### 4.3 更能体现 Harness 的价值

一次普通的 Agent 对话可以完成一个 wrapper。

但真正的产品要求：

```text
理解需求
→ 分析仓库
→ 找入口
→ 判断依赖
→ 执行修改
→ 安装
→ 调试
→ 测试
→ 修复
→ 判断是否完成
```

这是一个典型的长程任务。

Harness 的价值就在这里：

> 不让用户在几十轮 Agent 操作中一直充当项目经理。

---

## 5. 新 RepoProof 的核心价值主张

新的产品价值不是：

> “AI 可以写代码。”

而是：

> **把一次原本需要用户长时间陪同 Coding Agent 完成的 GitHub 能力接入过程，变成一个可自动运行、可验证、可重放的标准工作流。**

可以进一步拆成四项价值。

### 5.1 自动化

用户不需要：

- 手工读完 README；
- 自己找 API；
- 一轮一轮告诉 Agent 下一步；
- 自己判断安装是否正确；
- 自己反复检查有没有破坏环境。

Harness 承担流程管理。

### 5.2 可验证

Agent 说：

> “已经完成。”

不产生成功结论。

RepoProof 要独立验证：

- 能力是否真正工作；
- 是否满足用户确认的 Tool Contract；
- 是否破坏已有环境；
- 是否真实采用指定 upstream；
- 是否在新环境仍然可运行。

### 5.3 可重现

一次偶然跑成功不等于工具可用。

RepoProof 最终应该回答：

> 在干净环境中，按照冻结的 runtime 和依赖，能不能重新构建并再次通过？

### 5.4 可替换 Agent

RepoProof 不绑定一个模型。

底层可以是：

```text
mini-swe-agent
DeepSeek Harness
未来的其他 Coding Agent
```

产品价值不依赖：

> “我们训练了一个最强 Coding Model。”

而依赖：

> **我们把 Agent 放进了一个针对 GitHub Capability Onboarding 设计的 Harness。**

---

## 6. 新项目必须遵循的原则

### 原则一：最大限度复用现有 RepoProof，而不是推倒重来

新的方向必须被视为 RepoProof 的产品化收敛，而不是重新做一个项目。

当前已有的：

- Contract；
- Contract Adequacy；
- AgentBackend；
- DSH Runtime；
- Budget；
- Isolation；
- Receipt；
- Verifier；
- Regression；
- Policy；
- Clean Replay；
- Completion Gate；
- Evidence Report；
- Mutation Testing；

都应该被视为现有资产。

新方向应优先改变：

> “这些能力服务于什么任务。”

而不是重新设计一套基础设施。

### 原则二：DSH 负责 Agent Runtime，不再重复造相同轮子

新的 RepoProof 不需要证明：

> “我们也会自己写一个 Agent Loop。”

DeepSeek Harness 已经提供：

- 长程 Agent Loop；
- Bash；
- Editor；
- Session；
- Runtime；
- 模型适配能力。

因此：

> **DeepSeek Harness 负责“怎么让模型持续做事”；RepoProof 负责“这个任务应该做什么，以及怎么判断最后真的完成”。**

这也是两者最清晰的职责分界。

### 原则三：缩小问题空间，而不是降低系统技术深度

项目不应因为赶进度退化成：

> “让 Agent 自动加一两个函数。”

真正应该缩小的是任务范围。

例如新的 v1 可以明确限制在：

- Public GitHub Repository；
- Python-first；
- CPU/local-first；
- 单一清晰 Capability；
- 本地可运行；
- 不需要复杂云账号；
- 不需要大型分布式系统；
- 难度属于简单到中等的软件能力包装。

但是在这条窄任务线上，仍然保留完整的：

- Agent；
- Harness；
- 长程执行；
- Tool Use；
- Runtime Isolation；
- Contract；
- Verification；
- Replay；
- Provenance；
- Evidence。

这样项目依然有技术含量。

### 原则四：v1 不追求“模型不会的事情也必须做成”

Harness 的作用不是：

> 把模型能力无限提高。

Harness 更合理的作用是：

> **在模型本来具备完成可能性的任务上，让整个长程执行过程更稳定、更少依赖用户介入，并对最终结果负责。**

因此，新系统允许明确判断：

```text
SUPPORTED
REVIEW_REQUIRED
UNSUPPORTED
```

拒绝高风险任务并不是失败，而是产品边界。

### 原则五：v1 优先真实使用 upstream，而不是随意自己重写

当前 RepoProof 已经投入大量工作解决：

> Agent 到底有没有真实采用 upstream。

因此，为了复用已有成果并减少新语义，v1 优先定义为：

> 用户看中某个 GitHub 项目的真实能力，RepoProof 帮助把它可靠包装成本地工具。

如果目标项目无法合理接入，可以：

> 返回不适合自动 Tool 化。

而不是第一版就允许 Agent 随意重新实现类似能力。

未来可以再扩展“Local Reimplementation”，但不应成为 v1 的复杂度来源。

### 原则六：Product Mode 和 Benchmark Lab 分离

当前 RepoProof 为了研究模型与 Harness，已经建立了：

- held-out；
- blind attack；
- preregistration；
- mutation；
- candidate hunting；
- task hygiene。

这些能力有研究价值，但不能阻塞产品完成。

因此未来概念上分为：

```text
RepoProof Product Mode
```

目标：

> 快速把 GitHub 能力转成本地工具。

和：

```text
RepoProof Benchmark Lab
```

目标：

> 严格比较 Agent / Model / Harness，并研究任务构造和泛化能力。

Benchmark Lab 保留，但不再成为 Product Mode 每个用户任务的必经步骤。

---

## 7. 新产品的预期用户体验

理想情况下，用户不应该像现在一样长时间管理 Agent。

用户体验应该接近：

```text
输入 GitHub Repo
        +
描述我想要的能力
        ↓
系统分析
        ↓
告诉我：
能不能做
难度多大
需要什么
准备输出成什么工具
        ↓
用户确认
        ↓
Harness 自动运行
        ↓
Agent 分析 / 修改 / 测试 / 修复
        ↓
RepoProof 独立验证
        ↓
PASS / FAIL
        ↓
Local Tool + Report
```

重点不是“完全零交互”。

而是从：

> 用户几十轮陪 Agent 工作

降到：

> 用户只在关键决策点确认。

---

## 8. 最终希望达到的效果

### 8.1 对普通用户

用户的体验应该是：

> “我在 GitHub 找到了一个能力，我不想研究整个项目，也不想跟 Coding Agent 来回聊一个小时。我告诉 RepoProof 我要什么，它最后给我一个本地能用的工具，并告诉我为什么它认为这个工具是真的可用。”

### 8.2 对 AI 工作流用户

最终工具不仅可以人手调用，也可以成为 AI Agent 的能力。

理想的统一工具核心可以进一步暴露为：

- CLI；
- Python API；
- Local HTTP；
- MCP。

这样用户可以把一个原本独立的 GitHub 项目快速转变成：

> **自己的 AI Tool Library 中的一项能力。**

### 8.3 对开发者

开发者得到的不只是 wrapper。

还应该得到：

```text
Source Repository
Pinned Version
Tool Contract
Runtime Information
Verification Result
Replay Result
Provenance
Evidence Report
```

因此结果具有：

- 来源；
- 版本；
- 验收标准；
- 可重现性。

---

## 9. 预设使用情景

### 场景一：PDF 能力本地化

用户发现一个 GitHub PDF 项目。

需求：

> “我不需要整个项目，只想把 PDF 表格提取功能变成一个本地工具，以后给一个 PDF 就返回 Markdown 表格。”

RepoProof：

1. 理解仓库；
2. 识别目标能力；
3. 判断该能力适合本地 Tool 化；
4. Harness 驱动 Agent 完成包装；
5. 使用样例和验收测试独立验证；
6. 在干净环境重放；
7. 输出 `pdf-table` Local Tool。

以后：

```text
pdf-table report.pdf
```

或者被 AI Agent 调用。

### 场景二：网页能力转 AI Tool

用户发现 Browser Use 或其他网页工具。

需求：

> “我想让本地 Agent 拥有网页结构化信息提取能力。”

项目依赖浏览器和复杂 Runtime。

RepoProof 不把整套浏览器环境直接塞进用户 Agent，而是把能力包装为隔离的 Local Tool / Sidecar。

最终用户只看到：

```text
extract_web_facts(url)
```

内部运行时和浏览器由 Harness 管理。

这个场景非常适合展示 RepoProof 已经积累的：

- Runtime Profile；
- Sidecar；
- Execution Receipt；
- Isolation。

### 场景三：数据处理工具

用户看到一个 GitHub 数据处理库，其中有很好用的数据清洗能力。

需求：

> “把它的 normalize 功能变成一个本地命令，让我的 CSV 可以直接处理。”

RepoProof 最终输出：

```text
normalize-data input.csv
```

并验证：

- 输入输出格式；
- 异常数据；
- 上游真实调用；
- 离线重放。

### 场景四：研究学习工具

用户看到一个新的论文 / 代码分析项目。

需求：

> “我只需要其中代码依赖图分析的能力，希望以后 Claude 可以直接调用。”

RepoProof 将该能力包装成：

```text
analyze_repo_dependencies(path)
```

并作为 Local AI Tool 暴露。

这符合用户“发现新 GitHub 项目 → 很快转成个人学习工具”的真实习惯。

### 场景五：不适合自动完成的任务

用户提交：

> “把这个需要 CUDA、多台服务器、账号登录和云数据库的复杂 AI 平台变成本地 Tool。”

RepoProof 分析后返回：

```text
UNSUPPORTED / REVIEW_REQUIRED
```

并说明原因。

这个结果本身也是产品价值：

> 不让 Agent 在一个极可能失败的任务上消耗大量时间和 API 成本。

---

## 10. 产品边界

### v1 希望支持

```text
Public GitHub Repository
+
单一明确 Capability
+
Python-first
+
本地 CPU 环境
+
简单或中等依赖
+
可以明确输入 / 输出
+
可以构造可验证样例
```

### v1 暂不承诺

- 任意语言；
- 任意 GitHub 项目；
- 大型分布式系统；
- GPU-heavy 系统；
- 内核 / 驱动；
- 移动端；
- 复杂云服务；
- 任意大型宿主项目深度集成；
- 自动重写整个上游；
- 完全无人监督的软件开发。

---

## 11. 产品成功的衡量方式

新的 RepoProof 不应该只看：

> Agent 最终 PASS 率是多少。

更重要的产品指标应该包括：

### 任务筛选质量

系统是否能够提前拒绝明显不合适的项目，而不是跑几个小时后失败。

### 用户介入次数

原本可能需要用户进行几十轮 Coding Agent 对话。

新的目标是显著减少到少量关键确认。

### Tool Ready Rate

被系统正式接受执行的任务中，有多少最终得到：

```text
VERIFIED_TOOL_READY
```

### Replay Success

生成工具在干净环境中能否再次安装并通过验证。

### False Success Rate

系统是否会把：

> “看起来能跑但其实不满足需求”

错误判断成成功。

这是 RepoProof 最应该控制的指标之一。

---

## 12. 项目的核心技术故事

最终从面试和产品两个角度，都可以将故事讲成：

> 现代 Coding Agent 已经具备很强的软件开发能力，但它们仍然是通用 Agent。用户如果只是想把 GitHub 上发现的一项能力变成自己的本地工具，通常仍然需要手动管理项目分析、环境配置、接口设计、执行过程和结果验收。
>
> RepoProof 针对这个具体场景构建了一个 Agent Harness。它不重新训练 Coding Model，而是复用 DeepSeek Harness 等成熟执行 Runtime，让 Agent 负责仓库理解和代码生成；RepoProof 自己负责 Capability Contract、任务边界、执行约束、独立验证、Clean Replay 和证据报告。
>
> 最终目标是将“与 Coding Agent 长时间协作完成一次 GitHub 项目接入”，转化为一个标准化、自动化、可验证的 GitHub Capability Onboarding 流程。

---

## 13. 修改前后的项目形态对比

| | 原 RepoProof 目标 | 新 RepoProof 产品方向 |
|---|---|---|
| 输入 | 上游 GitHub + 任意 Host | GitHub + 用户想要的 Capability |
| 输出 | Host 内的完整适配 | Standard Local Tool |
| 任务空间 | 极大 | 受控 |
| Agent | 自研 / mini-swe / DSH | 可插拔，优先复用 DSH |
| Harness 重点 | 执行 + 严格研究验证 | 长程自动 Tool Onboarding |
| 验证 | 核心 | 继续作为核心差异 |
| Task Freeze | 学术级、较重 | Product Mode 轻量化 |
| Held-out | 主线 | Benchmark Lab |
| Blind Attack | 主线 | Benchmark Lab |
| 用户参与 | 任务构造阶段很重 | 少量关键确认 |
| 成功标准 | 严格 Adoption PASS | Verified Local Tool Ready |
| 项目规模 | 接近通用软件工程 Agent 研究 | 垂直 Agent Harness 产品 |

---

## 14. 最终产品愿景

RepoProof 最终希望解决的是一个非常直观的问题：

> **GitHub 上有大量好项目，但“发现一个能力”和“真正把它变成自己可用的 AI Tool”之间仍然存在很长的工程距离。**

RepoProof 希望把这段距离压缩成：

```text
Find
→ Describe
→ Confirm
→ Wait
→ Use
```

用户：

> “这个 GitHub 项目的 X 功能我想要。”

系统：

> “可以，我已经把它变成一个本地工具；这里是运行方式、版本、验证结果和证据。”

---

## 15. 当前阶段最重要的产品判断

在进入下一阶段工程设计前，需要先判断是否认可以下几条：

1. **RepoProof 的主产品场景从任意 Repository Adaptation 转向 GitHub Capability Onboarding。**
2. **最终交付物优先固定为 Verified Local Tool，而不是任意 Host Integration。**
3. **Harness 的价值是自动管理长程接入过程，而不是保证模型完成超出自身能力的任务。**
4. **DeepSeek Harness 等成熟 Runtime 负责 Agent Execution，RepoProof 不继续重复造这一层。**
5. **RepoProof 的差异化核心继续是 Contract + Independent Verification + Replay + Evidence。**
6. **Product Mode 和 Benchmark Lab 分离，严格研究流程不再阻塞产品任务。**
7. **v1 主动缩小支持范围，以换取真正能完成、能演示、能解释的完整产品闭环。**
8. **项目不是降低技术难度，而是降低任务空间。**

如果这些判断成立，那么 RepoProof 的下一阶段就不再是：

> “继续提高所有 Repository Adaptation 的成功率。”

而是：

> **“把现有 RepoProof 与 DSH 的能力重新组织成一个真正可使用的 GitHub → Verified Local Tool 产品闭环。”**

---

## 16. 一句话总结这次方向转变

> **不是放弃 RepoProof 原来的积累，而是把“任意项目适配”这个过大的研究问题，收敛成一个更真实、更标准化、更适合 Harness 自动化、也更容易产品化的 GitHub Capability Onboarding 场景；DSH 负责让 Agent 长程做事，RepoProof 负责定义任务并证明最终 Local Tool 真的可用。**
