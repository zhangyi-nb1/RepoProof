# RepoProof — ChatGPT Web 项目交接快照

> 快照日期：2026-08-24（Asia/Shanghai）  
> 用途：上传到 ChatGPT 网页端项目，帮助一个无法直接读取本机仓库的 GPT
> 理解 RepoProof 的最新产品方向、真实进度和下一步决策。  
> 注意：本文同时描述两个本地工作树；不要把“已提交”“未提交”“未合并”
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

### 主工作树：M5，当前仍未提交

- 分支：`main`
- 当前提交：`c5c958d`（M4 批次二收官）
- 相对 `origin/main`：本地 `main` 领先 31 个提交；远端并非最新状态。
- 工作区：39 个变更路径，其中 33 个已跟踪文件被修改、6 个新文件尚未跟踪。
- 当前内容：RFC-011 / M5 输出合同一致性与运营发布状态实现。
- 本地权威交接文档记录的质量基线：`1222 passed + 60 skipped + 0 failed`
  （1282 collected）。
- 结论：**M5 在本地被记录为 complete/closed，但在形成提交前只能视为
  “已完成并复验的工作区状态”，不能假装已经存在于 GitHub。**

M5 主要新增：

1. ToolSpec v2 的机器可执行输出合同；
2. 冻结前 T6–T9 一致性门；
3. 对实际 stdout 的独立运行期解析；
4. append-only release ledger；
5. `REVIEW_REQUIRED / ACTIVE / REVOKED` 运营状态；
6. `tool audit`、`tool withdraw` 与 MCP 运行期执法；
7. 同名更高 task version 的安全升级、归档与失败恢复；
8. 37 份旧冻结合同保持可加载，不改写历史证据。

### 独立 UI 工作树：M6 UI，已提交但未合并

- 分支：`codex/repoproof-studio-product-mode`
- 基线：`c5c958d`
- 提交：
  - `4ead78a` — 新增 RepoProof Studio Product Mode；
  - `8357f90` — 将 Studio 与 Benchmark Lab 完全拆成两个应用。
- 工作树状态：干净。
- 与 M5 的关系：基于 M4 独立开发，通过 Core CLI 能力探测接入
  `audit/withdraw`，尚未与本地未提交的 M5 工作树合并。

UI 最终形态：

- `RepoProof Studio`：默认产品入口，面向 GitHub 能力 → 本地工具；
- `RepoProof Benchmark Lab`：保留旧实验、Host Pilot、历史报告和设置；
- 两套应用不同进程、不同端口、不同视觉、不同导航、不同会话状态；
- Studio 使用 `~/tools` 与 `~/.repoproof`；
- Lab 使用仓库内 `runs/`、benchmarks、reports 和 evidence；
- 两边没有交叉入口，也不混算指标。

UI 定向回归、Host Pilot 回归、静态边界检查、双端口浏览器验收均通过。
全量测试时曾出现一个 Host smoke 指纹失败：原因是另一会话同时写入受保护的
原工作树；紧接着用同一链路诊断执行完整通过，并非 UI 逻辑回归。

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

1. 等主工作树的 M5 测试会话完成并形成提交；
2. 将 UI 分支合入包含 M5 的分支，解决 CLI/UI 接口冲突；
3. 重新运行 UI、工具发布、MCP、升级与全量回归；
4. 同步更新权威 handoff、README 和版本号；
5. 经用户确认后再推送 GitHub；
6. 不在未经授权时启动第三批真实仓或新的真实模型发次。

## 7. 希望网页端 GPT 提供的建议

请优先评价：

1. 新定位是否足够聚焦，用户是否能理解“为什么需要 RepoProof”；
2. M5 的 historical/operational 双状态是否合理、是否存在误导风险；
3. M5 与独立 Studio UI 合并时最可能出现的接口或产品语义冲突；
4. 下一阶段应优先做用户体验、真实用户验证、分发安装还是继续扩验证能力；
5. 哪些产品表述可能夸大当前证据；
6. 如何设计一次低成本、不会污染 Benchmark Lab 的真实用户试用。

## 8. 事实源阅读顺序

1. 本文；
2. `docs/HANDOFF_STATE.md`；
3. `docs/rfc/RFC-011-TOOL-CONTRACT-COHERENCE-AND-RELEASE-STATE.md`；
4. `docs/rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md`；
5. `docs/PRODUCT_REDIRECTION.md`；
6. `docs/m4_metrics.json`；
7. `docs/REPOPROOF_STUDIO_PRODUCT_MODE.md`；
8. `README.md` 和相关测试。

如果文件之间冲突，先检查它属于哪个工作树、是否已提交，再把冲突列出来，
不要静默选择一个版本。
