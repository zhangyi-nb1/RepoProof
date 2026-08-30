# M6.1 自然需求与多格式科研产物资格测试手册

> 2026-08-30 语义追踪修订：旧预注册
> `m6_1_multiformat_qualification.yaml` 保留且不回写，但其
> `hidden_acceptance_rules` 用词与当前可信边界冲突。今后的首次正式执行以
> `m6_1_multiformat_qualification_v2.yaml` 为准：held-out 只隐藏输入和真值，
> 不隐藏规则；全部领域规则在冻结前形成公开行为承诺并由用户确认。
> 默认 LLM 起草通道为 LiteLLM/API 网关，真实构建为 `mini-swe`；Codex
> 仅作显式回退，不能在同一批中混用。

## 当前事实边界

- Studio 已支持：仓库证据分析、2–3 条结构化自然语言建议、一键回填后继续编辑、主 Journey 内的 LLM Fresh audit 候选。
- Core 已支持 UTF-8 文本产物的 `--out` 交付；本批覆盖 RIS、TSV、Markdown、HTML，不覆盖 PDF 等二进制产物。
- RIS、TSV、Markdown、HTML 现在都有独立于 golden 文本的媒体格式底线检查；任务语义仍由冻结 reference、公开/held-out 样例、上游采用证明和 clean replay 判定。
- 四个 task-authored semantic verifier 必须在各自合同冻结后按预注册规则落成，并通过统一的 `repoproof-semantic-verifier-v1` 执行协议产生回执；缺回执时即使普通流水线显示 READY/ACTIVE，也不能把案例结算为通过。Harness 不包含四个仓库的领域规则，只负责隔离执行、上游调用取证和身份绑定。
- M6.1 新导出包会把“仅公开输入”复制到 `public_examples/inputs`，让候选去重与 release freshness 共用包身份。缺该目录的旧包不得回退读取仓库骨架；需要新 task version 重导出，避免出现两套 freshness 事实源。
- Studio 运行 reference 时必须启用受支持的 OS 隔离：网络全拒绝、写入仅限一次性目录、Provider 密钥不进入子进程。隔离后端不可用时在 LLM 调用前停止，不以普通子进程降级。
- 2026-08-30 的四条真人 Journey 已各自完成一遍；它们是在发现并修复通用 Harness 接缝的过程中依次完成的记录案例，不冒充“框架全程冻结”的模型能力成绩。旧 v1 清单保持冻结且 `NOT_RUN` 永久不变；执行事实只来自新合同、run、语义回执和 append-only release ledger。

## 本轮执行口径（2026-08-30）

本轮目标是完成四条真人 Product Journey 并发现通用 Harness 接缝，不结算为
“框架全程冻结”的资格统计。RISpy 与 Pint 已完成的 Journey 保留为有效的记录案例；
后续若为 NetworkX 或 Biopython 修复领域无关的 Harness/UI 缺陷，只对受影响且
尚未完成的案例重试，不要求从 RISpy 重新开始。

本轮已完成记录如下；`ACTIVE` 是当前 ledger 状态，历史 verdict 与当前状态仍
分别展示：

| 案例 | task | run | historical | operational | package |
|---|---|---|---|---|---|
| RISpy | `tool-rispy-tool-v7` | `tool-rispy-tool-v7-20260830-212214` | `VERIFIED_TOOL_READY` | `ACTIVE` | `OK` |
| Pint | `tool-pint-tool-v3` | `tool-pint-tool-v3-20260830-213712` | `VERIFIED_TOOL_READY` | `ACTIVE` | `OK` |
| NetworkX | `tool-networkx-tool-v1` | `tool-networkx-tool-v1-20260830-222601` | `VERIFIED_TOOL_READY` | `ACTIVE` | `OK` |
| Biopython | `tool-biopython-tool-v1` | `tool-biopython-tool-v1-20260830-230345` | `VERIFIED_TOOL_READY` | `ACTIVE` | `OK` |

这项口径只改变本轮测试编排，不改写任何冻结合同、历史 run、旧 ledger 或旧
预注册清单。若未来需要对外声称一次严格的固定框架资格批次，再另建 append-only
执行记录，并按下文“批次作废规则”从第一仓开始。

## 公共产物协议

自然语言“公开行为承诺”只说明工具必须做到什么；对于 Markdown、HTML、RIS、
TSV 等可读文本产物，reference 与独立 verifier 还需要共享一份由用户在冻结前
可审阅的、**不含真值**的呈现语法。新 draft 因此必须包含
`_intent_contract.artifact_protocol`：

- `protocol_id` 标识协议版本；
- 每个 `observation` 将一个或多个公开承诺绑定到稳定 `locator`；
- `value_encoding` 描述对应值如何编码，例如标量、表格行或文本段落；
- 所有公开承诺必须至少被一个 observation 覆盖，且不得引用未知承诺。

协议可以说明“哪个标题/表格/DOM 节点承载哪个公开指标”，但不得写入具体样例
的答案、held-out 输入、golden 文本或私有路径。reference 负责按协议产生实际值；
verifier 只凭冻结承诺、协议、输入和候选产物独立复算。二者若各自猜测布局，
即使数值都正确也必须在起草阶段 fail closed，不能交给 Agent repair。

## 本轮固化的通用 Harness 接缝

- **源码身份与可执行运行时分账**：钉版 Git checkout 证明 commit/tree 与
  provenance；reference、semantic verifier 和 fresh audit 在声明了 lock 时
  使用内容寻址 wheelhouse 中的精确 wheel。不能把含未编译扩展的源码树放到
  `PYTHONPATH` 前面遮蔽已安装 wheel。
- **上游一致性选择使用限定调用路径**：从 reference 提取 `SeqIO.parse` 这类
  相对限定符，不退化成终端名 `parse`；选择器要求限定路径各段都有结构证据，
  并保留仓库真实的 `Tests`/`tests` 大小写。测试从实际 test root 运行，让测试
  fixture 可见，同时继续导入隔离环境里的精确 wheel。
- **analysis checkout 升格保持 Git 文件类型**：复制钉版树必须保留 tracked
  symlink；解引用 symlink 会让刚创建的 checkout 立刻产生 tracked drift，后续
  fresh audit 必须 fail closed。
- **冻结后、物化前允许同版本恢复**：只有冻结 Tool Contract、sidecar 与草稿的
  工具名、上游身份和用户确认语义哈希完全一致时，才可沿用同一 task version
  继续 materialize；恢复绝不重写冻结合同。续跑的 Worker 以新的、job-bound
  `ProductActionResultV1` 为进程产物，Pipeline verdict 仍单独投影，不能因冻结
  合同按设计没有变化而误报 Worker 失败。

### 问题定位矩阵

本轮禁止按“RIS 出错”“FASTQ 出错”命名修复。每个失败先定位到一条跨仓库
接缝，再用匿名/合成 fixture 钉住：

| 用户侧现象 | 责任环节 | 抽象缺陷 | 通用修复与验证 |
|---|---|---|---|
| 模型建议看起来可交付，却把函数名或源码路径直接写进需求框 | 仓库建议 → UI 采用 | 交付支持状态兼任了措辞质量状态 | `support_status` 只看 typed delivery topology；独立 `adoption_status` 只控制一键采用。技术化推荐不消失、不改语义，但必须人工改成工作语言；同组其他口语建议仍可采用。 |
| 用户真实需要多个产物、二进制、联网或服务时，模型被反复要求“修成可支持” | 建议 admission | 把不支持的真实需求误当成 schema/model 错误 | Core profile 返回 `UNSUPPORTED` 并保留原需求；只有表示投影错误允许一次有界修复，绝不要求模型删需求。 |
| 上游默认 writer 的文本能解析，但不是用户确认的互操作产物 | 合同起草 → reference 预检 | MIME/纯文本通过被误当成任务语义正确 | profile 编译版本化 representation validator；任务语义留在公开承诺、产物协议和独立 verifier，不能为某个 writer 放宽 Core。 |
| reference 与 verifier 都“同意”同一个错误布局 | 冻结前语义起草 | 答案和判卷器同源，且没有共同的公开呈现语法 | reference/verifier 分两次隔离起草；用户确认 value-free `artifact_protocol`；运行时增加 input/artifact/upstream-result 三项反事实控制。 |
| 源码 commit 正确，但 reference import 到未编译或错误版本代码 | 固定上游 → reference runtime | provenance identity 与 executable runtime identity 混成一件事 | Git tree 负责来源证明，内容寻址 wheelhouse 负责执行；有精确 wheel 时禁止源码 `PYTHONPATH` 抢占。 |
| conformance 选到另一个模块里同名 `parse` 测试 | 上游一致性选择 | 只按终端符号名匹配，丢失调用限定路径 | 提取并匹配 `SeqIO.parse` 等相对限定路径，保留测试目录真实大小写，并从真实 test root 执行。 |
| 新生成的 pinned checkout 一创建就报告 tracked drift | analysis checkout → 固定缓存 | 复制时解引用 tracked symlink，改变 Git 文件类型 | checkout 升格使用保留 symlink 的复制语义；回归用匿名 tracked symlink fixture。 |
| 合同冻结后进程中断，只能创建新版本；恢复后 UI 又报 Worker 失败 | 冻结 → 物化 → 状态投影 | 缺少合法断点恢复；Worker 用“合同文件变化”猜进程成功 | 身份和确认哈希完全一致时恢复同一版本且不重写合同；Worker 读取 job-bound `ProductActionResultV1`，Pipeline 与 Operational 继续独立。 |

以上 Core/Harness 路径的源码不得出现本批四个仓库 URL、tool id 或固定 commit；
自动化测试会扫描 `src/repoproof` 并在出现案例身份特判时失败。格式注册表只定义
表示层 parser/profile；用户原话或格式词本身不能生成承诺、协议或任务规则。

## 需求建议失败不能怎样“修”

模型提出需求、Core 判定当前能否交付，是两个不同责任。模型必须如实列出
所需输入、输出、网络、凭据、生命周期和运行环境；Core 再依据版本化
delivery profile 投影为 `SUPPORTED` 或 `UNSUPPORTED`。

- `UNSUPPORTED` 建议保留原始结构并展示原因，但没有可采纳文本和一键采用按钮。
- 交付拓扑不匹配不是模型输出损坏，不允许再问同一模型“改成支持的形状”。
- 只有 JSON/schema 等表示错误可以重试；重试提示不得让模型删、并或隐藏需求。
- 被采用的交付拓扑写入 intent contract，和用户原话、公开行为承诺、最终接口
  一起进入确认哈希。后续接口漂移会在冻结前失败。

因此，“一个建议同时需要两个用户产物”只是这个机制的一种输入，不是新增的
案例规则。相同判定同样适用于多输入、远程 URL、二进制产物、服务、凭据、
联网、GPU 或常驻进程；是否支持只由 profile 数据决定，不读取仓库名或任务关键词。

### “当前可交付”和“可以一键采用”必须分开

2026-08-30 的反向审计发现，若 UI 只检查 `support_status=SUPPORTED`，模型即使
把函数调用、源码路径、CLI 参数或字段 schema 写进建议，也会得到一键采用按钮。
这不会改变交付拓扑，却会破坏“从模糊、口语化需求开始”的真人体验。

当前机制因此保存两个互不替代的判断：

- `support_status` 只由结构化 `DeliveryRequirements` 与版本化 profile 决定；
  它不读取 scenario/boundary 的仓库词、格式词或技术词。
- `adoption_status` 只判断准备写回用户输入框的 scenario/boundary 是否包含
  代码化表达。它只能禁用一键采用并要求用户改成工作语言，不能把任务判为
  不支持、不能选择产物格式，也不能生成或修改任何语义承诺。

模型建议中的 title/reason 可以引用 README 的公开 API 证据，因为它们不进入
用户需求；真正进入需求框的只有通过口语化检查、再由 delivery profile 编译的
文本。某一条建议过于技术化时，其余合格建议仍可采用，不能让整次仓库分析消失。

### 格式检查不能迎合上游默认输出

格式媒体合同描述的是用户实际拿到的产物，不是某个上游 writer 的方便默认值。
如果上游默认序列化与已确认的互操作格式不一致，责任在 reference/adapter 配置与输出规范化，
不得为了让当前仓库通过而放宽 Core 格式检查。基础媒体结构检查、任务语义 oracle 和上游真实调用回执必须分层记账。

## 为什么不能把“文件能打开”当成通过

每个成功结果必须同时经过三层判断：

1. `ToolOutputContract` 按用户已确认、由 delivery profile 编译的版本化
   `validation_profile` 执行格式底线；MIME 只标识表示类型，不能暗中附加规则。
   该层阻止把 JSON 或任意纯文本冒充 RIS、TSV、Markdown 或安全的自包含 HTML。
2. 实际 stdout 与冻结 reference 调用 pinned upstream 得到的真值比较；Agent 的完成声明不参与判定。
3. 每个案例还必须满足预注册清单里的 `semantic_verifier_requirements`。例如 Pint 结果要按输入用 Pint 复核，NetworkX 指标要重算，不能只检查表面格式。

缺少任意一层，都不能把案例标记为资格通过。

### 独立语义 verifier 的责任边界

- 领域判断写在冻结任务自己的 oracle verifier 中；不得把仓库名、函数名或
  本批期望值写进 Core/Harness 分支。
- Harness 统一调用 `verify(input_path, artifact_path)`，只接受布尔结果和稳定
  reason code，不记录原始输入、产物或异常正文。
- PASS 必须同时有声明上游的签名运行时调用证据，并绑定 verifier 源码、输入、
  产物、固定 commit、输出合同及用户确认语义的 SHA-256。
- PASS 还必须通过三项领域无关的反事实控制：替换本次输入后不得继续接受原产物、
  替换候选产物后必须拒绝、替换上游调用返回值后必须拒绝。三项分别证明判决
  至少依赖本次输入、实际产物和真实上游结果；缺任一项只能进入
  `REVIEW_REQUIRED`，不能把 verifier 的自述当成证据。
- `QualificationCaseResultV1` 内嵌完整 verifier evidence，并校验其摘要、verifier
  身份和 artifact 摘要一致；只有手填名称或哈希不能再构成通过证据。

## 固定批次

顺序与上游身份固定如下。`package_version` 是依赖包版本；`UI revision`
才是 Studio“固定版本或 Commit”输入框里必须填写的 Git tag。若 tag 无法解析，
只允许改填同一行的固定 commit，不能把包版本猜成 tag。

| 顺序 | 仓库 | package_version | UI revision（Git tag） | 固定 commit |
|---|---|---|---|---|
| 1 | RISpy | `0.10.0` | `v0.10.0` | `b7aae3b2069ced3fb75287711300f2edf0bcac21` |
| 2 | Pint | `0.25.3` | `0.25.3` | `5e79411e1be2dc39c52a536168338773b49fd512` |
| 3 | NetworkX | `3.6.1` | `networkx-3.6.1` | `7530809bfa1ea7ed6fdf918a4d1431488953cb1f` |
| 4 | Biopython | `1.88` | `biopython-188` | `d7e4b8b19399668b09442a5b35765d9186b5f665` |

特别注意：Biopython 的发布包版本是 `1.88`，但仓库中的 tag 是
`biopython-188`；Studio 不得填写不存在的 `1.88` tag。

真实构建 backend 固定为 `mini-swe`。网关故障属于外部失败；批次中不得切换 Codex CLI 继续算同一批结果。

## 每仓操作步骤

1. 在“新建工具”中只填预注册清单的仓库、`ui_revision` 和
   `initial_user_request`。不要把 `package_version` 当成 UI revision；仅当 tag
   解析失败时，才改填同一案例的 `resolved_commit`。
2. 点击“让 LLM 分析仓库和这项能力”，确认出现 2–3 条用户语言建议；建议仍是“尚未验证”。
3. 按清单的 `adoption_mode` 直接采用或只做一次口语化修改。采用动作不得创建 Journey、生成草稿或冻结合同。
4. 点击“创建任务并生成草稿”。检查模型没有把 RIS、TSV、Markdown、HTML 擅自改回 JSON。
5. 检查模型提出的“公开行为承诺”是否覆盖 v2 预注册的全部规则。
   缺少关键算法、错误语义或确定性规则时，不得冻结；这是合同起草失败，
   不得交给 Agent repair，也不得用案例关键词代码补齐。
6. 请求 4 条 LLM 样例输入候选。期望产物只能来自固定上游 reference；至少确认 3 条成功样例，并拒绝畸形或偏题候选。
   这 3 条在 `examples.yaml` 中必须持久标记为
   `UPSTREAM_DERIVED_USER_CONFIRMED`，且输入/输出绑定哈希有效；手工样例
   `USER_SUPPLIED` 可以补充合同，但不能代替本批的 3 条上游派生样例。
7. 确认至少一条后重新生成候选，确认已采纳样例数量和文件仍然存在。
8. 依次完成零模型演练、mini-swe 真实构建、独立验证和 clean replay。
9. 在主 Journey 的 Fresh audit 阶段让 LLM 生成新输入。服务必须绑定当前 `dest_root + task_id`，并排除公开样例；用户确认 reference 真值后再运行 audit。
10. 达到 `VERIFIED_TOOL_READY + clean replay PASS + fresh audit PASS + ACTIVE + package OK` 后，用 `--out` 保存声明扩展名的产物并执行清单中的格式语义复核。

## 当前执行恢复规则

- 发现通用 Harness 或 UI 缺陷：立即停止受影响案例；修复并完成自动化回归后从
  该案例的合法断点继续。已经 `ACTIVE + package OK` 的早先案例不重跑。
- 合同、环境、Harness 或 upstream 故障：不得消耗 Agent repair 轮次。
- 发生语义变更：创建新 task version，不改写冻结合同、旧 run 或 release ledger。
- 每次批次执行必须另存 append-only 记录，至少包含框架 commit/tree hash，以及 case 到 Journey、task、run 的映射；不得回填本预注册文件。

若未来另行授权一轮“框架从第一仓到第四仓全程冻结”的研究型资格统计，应新建
独立执行记录，并在该新记录中预先规定是否整批重启；这不追溯改变本轮四条
Product Journey 的事实。

## 对外表述

四个案例即使全部通过，也只证明该固定支持面在这四个记录案例中成立，不代表任意 GitHub 仓库成功率。
