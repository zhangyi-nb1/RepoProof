# M6.1 自然需求与多格式科研产物资格测试手册

## 当前事实边界

- Studio 已支持：仓库证据分析、2–3 条结构化自然语言建议、一键回填后继续编辑、主 Journey 内的 LLM Fresh audit 候选。
- Core 已支持 UTF-8 文本产物的 `--out` 交付；本批覆盖 RIS、TSV、Markdown、HTML，不覆盖 PDF 等二进制产物。
- RIS、TSV、Markdown、HTML 现在都有独立于 golden 文本的媒体格式底线检查；任务语义仍由冻结 reference、公开/held-out 样例、上游采用证明和 clean replay 判定。
- 四个 case-specific semantic verifier 必须在各自合同冻结后按预注册规则落成并产生回执；当前状态是 `PENDING_FROZEN_TASKS`，缺回执时即使普通流水线显示 READY/ACTIVE，也不能把该案例结算为本批资格通过。
- M6.1 新导出包会把“仅公开输入”复制到 `public_examples/inputs`，让候选去重与 release freshness 共用包身份。缺该目录的旧包不得回退读取仓库骨架；需要新 task version 重导出，避免出现两套 freshness 事实源。
- Studio 运行 reference 时必须启用受支持的 OS 隔离：网络全拒绝、写入仅限一次性目录、Provider 密钥不进入子进程。隔离后端不可用时在 LLM 调用前停止，不以普通子进程降级。
- 四个真实仓库资格案例尚未运行。权威预注册清单是 `docs/m6_1_multiformat_qualification.yaml`；它是冻结的计划件，`NOT_RUN` 永久保持不变。项目方从 Studio 发起批次后，结果只能写入新的 append-only 执行记录。

## 为什么不能把“文件能打开”当成通过

每个成功结果必须同时经过三层判断：

1. `ToolOutputContract` 检查声明的媒体类型，阻止把 JSON 或任意纯文本冒充 RIS、TSV、Markdown 或安全的自包含 HTML。
2. 实际 stdout 与冻结 reference 调用 pinned upstream 得到的真值比较；Agent 的完成声明不参与判定。
3. 每个案例还必须满足预注册清单里的 `semantic_verifier_requirements`。例如 Pint 结果要按输入用 Pint 复核，NetworkX 指标要重算，不能只检查表面格式。

缺少任意一层，都不能把案例标记为资格通过。

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
5. 检查合同是否表达对应案例的隐藏行为规则。缺少关键算法、错误语义或确定性规则时，不得冻结；这次案例记为合同起草失败。
6. 请求 4 条 LLM 样例输入候选。期望产物只能来自固定上游 reference；至少确认 3 条成功样例，并拒绝畸形或偏题候选。
   这 3 条在 `examples.yaml` 中必须持久标记为
   `UPSTREAM_DERIVED_USER_CONFIRMED`，且输入/输出绑定哈希有效；手工样例
   `USER_SUPPLIED` 可以补充合同，但不能代替本批的 3 条上游派生样例。
7. 确认至少一条后重新生成候选，确认已采纳样例数量和文件仍然存在。
8. 依次完成零模型演练、mini-swe 真实构建、独立验证和 clean replay。
9. 在主 Journey 的 Fresh audit 阶段让 LLM 生成新输入。服务必须绑定当前 `dest_root + task_id`，并排除公开样例；用户确认 reference 真值后再运行 audit。
10. 达到 `VERIFIED_TOOL_READY + clean replay PASS + fresh audit PASS + ACTIVE + package OK` 后，用 `--out` 保存声明扩展名的产物并执行清单中的格式语义复核。

## 批次作废规则

- 发现通用 Harness 或 UI 缺陷：立即停止，整批作废；修复并完成全量回归后从 RISpy 重新开始。
- 合同、环境、Harness 或 upstream 故障：不得消耗 Agent repair 轮次。
- 发生语义变更：创建新 task version，不改写冻结合同、旧 run 或 release ledger。
- 每次批次执行必须另存 append-only 记录，至少包含框架 commit/tree hash，以及 case 到 Journey、task、run 的映射；不得回填本预注册文件。

## 对外表述

四个案例即使全部通过，也只证明该固定支持面在这四个记录案例中成立，不代表任意 GitHub 仓库成功率。
