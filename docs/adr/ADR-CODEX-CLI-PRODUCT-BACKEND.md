# ADR: Product Mode 复用官方 Codex CLI Agent Harness

> 状态:Accepted（2026-08-27）  
> 范围:RepoProof Studio / `repoproof tool build` 的 `AGENT_ADAPT` 路线  
> 不改变:Benchmark Lab、冻结合同、历史 run、旧 ledger、历史指标

## 决策

Product Mode 的默认真实 Agent backend 改为 `codex-cli`。它通过官方
`codex exec --ephemeral --json` 使用本机已有的 ChatGPT 订阅登录，不读取、
复制或记录 Codex 的认证材料，也不要求 `OPENAI_API_KEY`。`mini-swe` 保留为
显式 API/provider 兼容后端；DSH 继续留在冻结的 Benchmark Lab 研究线。

这不是把 RepoProof 替换为 Codex。职责边界如下:

```text
Codex CLI:理解代码、调用工具、修改实现（内层 agent loop）
RepoProof:冻结目标 → 失败分类 → 有界 repair → 选最佳快照
          → held-out/回执/回归/策略验证 → clean replay
          → 历史 verdict + append-only 运营状态
```

## 为什么现在采用

原 Product Mode 的 mini-swe 路径把“模型 API 通道”和“agent loop”分开:
RepoProof 需要一个可用的 OpenAI-compatible API 网关和独立 API 额度。当前
私有网关的认证入口仍可达，但上游请求失败；ChatGPT Pro/Plus 订阅额度也
不能直接当作 OpenAI API 余额使用。

官方 Codex CLI 则支持 ChatGPT 登录，并提供适合脚本化调用的 `codex exec`。
因此它能去掉私有网关这个单点，同时复用成熟的上下文管理、工具调用、故障
处理和沙箱执行能力。RepoProof 无需再为了“能让 Agent 稳定写代码”重复造
一套通用 runtime。

## 是否算“作弊”

不算，前提是对贡献边界表述诚实。Agent harness 本来就是可复用基础设施，
和项目复用 Git、pytest、FastMCP 或数据库一样。RepoProof 不再声称自己的
创新是“实现了一个比 Codex 更强的 coding-agent loop”；它的可展示贡献是:

- 把 GitHub 能力与用户意图转成可冻结、可执行的 Tool Contract；
- 将公开失败变成类型化 FailurePacket，驱动有界 repair、停滞终止和最佳
  快照恢复；
- 不接受 Agent 自述，以独立 oracle、真实上游采用证明、回归、policy 与
  clean replay 判定结果；
- 将不可改写的历史验收与 append-only 当前发布状态分开。

反过来，若只调用 Codex 后直接展示“Done”，那才会使 RepoProof 退化成一层
薄包装。本 ADR 明确禁止这种表述和实现。

## 与 mini-swe 路径的区别

| 维度 | `codex-cli`（产品默认） | `mini-swe`（兼容后端） |
|---|---|---|
| 认证/计费 | ChatGPT 订阅登录；受订阅使用限制 | API key / 私有网关；API 独立计费 |
| Agent loop | Codex 原生 harness | 仓内 `MiniSWEBackend` + DefaultAgent |
| 上下文/工具 | Codex 原生管理 | RepoProof 显式控制观察、bash 与预算 |
| 模型调用计数 | 内部次数不可见；只记逻辑 `codex exec` 次数 | 每次模型请求可计数 |
| Token | 读取 Codex JSONL 的 `turn.completed.usage` | RepoProof/LiteLLM 同步计量 |
| 命令策略 | Codex 沙箱 + RepoProof PreToolUse 钩子 | RepoProofEnvironment 逐命令执法 |
| Lab 资格 | **无**，永不进入模型能力分母 | 仅按原冻结实验协议进入 |

## Repair 与终止语义

Codex 只替换每轮的实现执行器，不替换 RepairLoop。每轮结束后 RepoProof 自己
运行公开合同测试和宿主回归，生成 FailurePacket，再决定下一轮:

1. 全部公开测试、回归与轮内 policy 信号通过时停止；
2. 新一轮硬信号严格退步时恢复历史最佳提交；
3. 连续无进展时按既有 `stagnation` 规则停止；
4. 达到轮数、命令、token、wall-time 或 patch 上限时停止；
5. Agent 请求扩大依赖/网络/成功标准时转为
   `SCOPE_CHANGE_PENDING_USER`，不得自行放宽合同；
6. repair 停止后才运行 held-out、上游采用证明和 clean replay；任一失败
   都不能被 Agent 的完成声明覆盖。

## 可信边界与补偿控制

2026-08-27 的负向探针证明:Codex `workspace-write` 会阻止工作区外写入，
但允许读取普通工作区外文件。因此 RepoProof 增加以下控制:

- Codex 只在一次性 session 的 `host/` 中运行，`../upstream` 只读；
- prompt 通过 stdin 传入，不进入进程 argv；
- 清除 `OPENAI_API_KEY`、旧网关与 DeepSeek/LiteLLM provider 环境变量，
  并剥离无关 token/secret/SSH agent 环境变量，只保留官方 CLI 通过本机
  `HOME`/`CODEX_HOME` 自己管理的 ChatGPT 登录；
- 通过受信的 `PreToolUse` hook 复用 RepoProof command policy，并拒绝显式
  session 越界路径；每个判定写入本次 run 的策略日志；
- 命令数和 wall time 由父进程 watchdog 限制；token 从 Codex JSONL 如实
  记账；内部模型调用数写 `UNKNOWN`，不伪造为精确数字；
- Codex backend 强制 `benchmark_eligible=false`，Product run 本来也通过
  `test_mode=PRODUCT` 与 Lab 分账。

该 hook 是对诚实 coding agent 的防误触和取证层，不宣称能静态分析任意
恶意 shell/Python 混淆。因此 Codex Product run 可以形成产品验收证据，
但不能作为严格盲测或模型能力比较证据。需要这种研究结论时，必须回到冻结
的 Lab 隔离协议。
