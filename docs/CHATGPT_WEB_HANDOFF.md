# RepoProof — ChatGPT Web 项目交接快照

> 快照日期：2026-08-24（Asia/Shanghai）
> 用途：上传到 ChatGPT 网页端项目，帮助一个无法直接读取本机仓库的 GPT
> 理解 RepoProof 的最新产品方向、真实进度和下一步决策。
> 注意：本文同时描述多个本地 Git 状态；不要把“已提交”“未提交”“未合并”
> 三种状态混为一谈。

## 1. 一句话定位

RepoProof 已从“让 Agent 任意适配仓库”收敛为：

> **把公开 GitHub 仓库中的一个明确能力，可靠地包装成经过独立验证、
> 干净重放并具有当前发布状态的本地工具。**

面向普通用户的目标旅程是：

```text
Find → Describe → Confirm → Build → Prove → Use
```

Agent 自称完成不构成成功。最终结论来自冻结合同、独立验收、上游真实使用
证明、策略检查和干净重放。

## 2. 当前代码状态（必须先读）

### 本地 `main`：M5 已提交并关闭

- 分支：`main`
- 当前提交：`034bdf1`（M5 输出合同一致性与运营发布状态关闭）。
- 相对 `origin/main`：本地 `main` 领先 32 个提交；远端并非最新状态。
- M5 质量基线：`1324 passed + 60 skipped + 0 failed`。
- 结论：**M5 已存在于本地提交历史，但尚未推送；不得说成已经存在于
  GitHub。**

M5 主要新增：

1. ToolSpec v2 的机器可执行输出合同；
2. 冻结前 T6–T9 一致性门；
3. 对实际 stdout 的独立运行期解析；
4. append-only release ledger；
5. `REVIEW_REQUIRED / ACTIVE / REVOKED` 运营状态；
6. `tool audit`、`tool withdraw` 与 MCP 运行期执法；
7. 同名更高 task version 的安全升级、归档与失败恢复；
8. 37 份旧冻结合同保持可加载，不改写历史证据。

### M6 整合分支：Engineering Complete，尚未合回 `main`

- 分支：`codex/m6-studio-integration`
- UI 来源：`codex/repoproof-studio-product-mode @ df9cc32`（基于 M4）。
- 整合提交：`3818ccb` 以 `--no-ff` 保留 UI 历史；`d7c1278` 完成
  Core×Studio 可信整合。
- 与 M5 的关系：从 `main @ 034bdf1` 建分支并完成集成，不再存在 M5/UI
  双重事实源。
- 实测门禁：纯 M6 隔离工作树全量 pytest 退出 0（1455 collected）；
  M6 改动面 Ruff、`git diff --check` 通过。
- 阶段结论：**M6 Engineering Complete；M6 Preview Validated 尚未关闭。**
  后者仍需项目方和至少两名目标用户完成固定案例理解测试，不能由自动化替代。
- 当前未合回本地 `main`，也未推送或发布。

UI 最终形态：

- `RepoProof Studio`：默认产品入口，面向 GitHub 能力 → 本地工具；
- `RepoProof Benchmark Lab`：保留旧实验、Host Pilot、历史报告和设置；
- 两套应用不同进程、不同端口、不同视觉、不同导航、不同会话状态；
- Studio 工具库只消费 Core `tool_registry.list_tools(..., scan=False)`；
- historical verdict、operational status、package health 三栏独立展示；
- Studio 与 Lab 可同时打开，但所有 Core 写任务共用一把跨进程锁；
- Product 发次原生标记并从 Lab 模型能力指标中排除；
- 两套应用不同入口、导航和会话状态，共享证据引擎但不混算指标。

UI 定向回归、Host Pilot 回归、静态边界检查和自动化双入口浏览器旅程均通过。
全量测试首次出现的 Host smoke 指纹失败，已定位为测试期间开发服务器热重载
触碰受保护工作树；停掉该服务器后，同链路及第二次全量测试均通过。

### M7 候选分支：已提交，但未关闭、未合并

- 分支：`codex/m7-managed-sidecar-tools`（基于 M6 整合分支）。
- 实现提交：`8f6b43e`；干净工作树收口修复：`0d19e7d`。
- 状态：**EXPERIMENTAL / CANDIDATE / REVIEW_REQUIRED**，不是 M7 关闭。
- 干净提交隔离工作树全量测试：`1434 passed + 63 skipped + 0 failed`；
  改动面 Ruff、compileall、`git diff --check` 通过。
- 已实现：固定 ToolSpec v3 delivery runtime、一次性 loopback sidecar、动态端口、
  readiness/request/output-contract/回收链、10 个入口文件机器锚、append-only
  trust marker、registry/task/package identity 绑定，以及 v3 MCP 激活硬阻断。
- 已验证攻击面：manifest 降级伪装、损坏 manifest、伪造 task/provenance、
  stale/forged ACTIVE、源码 symlink、`__init__.py` 漂移均 fail closed。
- 未关闭：强 U1–U4 receipt、OS 级网络/进程隔离、真实导出包 clean replay、
  经单独授权的一个真实公开仓。因此不得称 verified 或 ACTIVE。
- 未调用模型、未运行第三批真实仓、未推送、未发布。

产品范围只包含“GitHub Capability → Verified Local Tool”。旧的任意仓适配定位
与 Benchmark Lab 仅保留隔离、历史兼容和只读研究边界，不继续开发；M7 也只
是本地工具的交付 runtime，不是旧产品路线的延伸。

## 3. 已提交的 M0–M4 事实

- RFC-010 M0–M3 已关闭：产品章程、首个工具闭环、半自动 intake 和
  `tool add/build/list/mcp` 单命令旅程已落地。
- M4 完成两批真实仓 dogfood 和指标记录。
- 最新批次二记录：

| 指标 | 事实值 |
|---|---:|
| Submitted repositories | 12 |
| Accepted for execution | 11 |
| Historical pipeline READY | 10 |
| Clean replay successful | 10 |
| Operationally ACTIVE | 9 |
| False-success findings | 1 |

False-success 是 `pyspellchecker` v1：冻结声明说输出 JSON，reference、golden
和 oracle 却共同接受纯文本。RepoProof 保留了当时的历史 READY 和全部证据，
但通过运营账将当前状态撤回，没有改写合同或重跑模型。这一缺陷直接催生 M5。

## 4. 两类状态必须分开

```text
historical_verification
  = 在当时冻结合同下，流水线不可改写的历史结论

operational_release
  = 现在是否允许 RepoProof 受管 MCP 暴露或升级发布
```

因此：

- 历史 `VERIFIED_TOOL_READY` 不能被运营撤回覆盖；
- 当前 `REVOKED` 也不能因为历史 READY 被忽略；
- ledger 缺失或损坏必须 fail closed；
- 撤回阻止的是 RepoProof 受管 MCP/发布，不是假装提供 OS 级执行禁令；
- 产品运行与 Benchmark Lab 成绩分账，不能用产品发次抬高模型成绩。

## 5. 产品当前诚实边界

v1 面向：

- 公开 GitHub Python 仓库；
- 一个输入输出明确、可用样例验证的能力；
- 本地 CPU；
- 简单到中等依赖；
- 明确的文件型输入输出。

以下仍在承诺之外：GPU 重任务、分布式系统、账户绑定能力、私有仓库、
整站/整应用迁移、高交互浏览器运行时和无法形成独立真值的任务。

## 6. 当前最重要的下一步

1. 用 ACTIVE、构建失败、historical READY/current REVOKED 三个固定案例完成
   项目方 + 两名目标用户的 M6 预览验证；
2. P0/P1 误解清零后，才把 M6 合回本地 `main`；
3. 保持 M7 候选分支冻结，不再做非必要性能优化或范围扩展；
4. 强 receipt 绑定和 OS 级隔离成立前，ToolSpec v3 最多为
   `REVIEW_REQUIRED`，不得进入 `ACTIVE`；
5. 推送、发布、第三批真实仓、真实模型调用和 M7 单仓 clean replay 均需另行授权。

## 7. 希望网页端 GPT 提供的建议

请优先评价：

1. 新定位是否足够聚焦，用户是否能理解“为什么需要 RepoProof”；
2. M6 的三栏状态与完整 reason code 是否仍可能被误读；
3. M6 固定案例预览验证能否有效发现状态认知偏差；
4. M7 sidecar 首版保持 `REVIEW_REQUIRED` 的可信边界是否足够保守；
5. 哪些产品表述可能夸大当前证据；
6. 如何设计一次低成本、不会污染 Benchmark Lab 的真实用户试用。

## 8. 事实源阅读顺序

1. 本文；
2. `docs/HANDOFF_STATE.md`；
3. `docs/rfc/RFC-011-TOOL-CONTRACT-COHERENCE-AND-RELEASE-STATE.md`；
4. `docs/rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md`；
5. `docs/PRODUCT_REDIRECTION.md`；
6. `docs/m4_metrics.json`；
7. `docs/rfc/RFC-012-MANAGED-SIDECAR-TOOLS.md`；
8. `docs/REPOPROOF_STUDIO_PRODUCT_MODE.md`；
9. `README.md` 和相关测试。

如果文件之间冲突，先检查它属于哪个工作树、是否已提交，再把冲突列出来，
不要静默选择一个版本。
