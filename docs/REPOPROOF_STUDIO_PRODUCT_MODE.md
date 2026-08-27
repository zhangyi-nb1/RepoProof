# RepoProof Studio · Product Mode UI

- 状态：**M6 已关门(2026-08-25)**——已并入 `main`;项目方三固定案例
  预览 + 两名目标用户理解测试完成(P0=0,P1 计 7 条全部修复并复验;
  用户测试原始记录归档位 `docs/evidence/m6_user_tests/` 待投入,详见
  该目录 README)。Gate 4 后 Studio 新增能力计划人读卡(RFC-013:
  支持状态/执行路线/理由码/表面证据,并明示「候选入口由用户确认,
  系统不做意图理解」)与 repair 逐轮时间线。

RepoProof Studio 把 RFC-010 的 `Find → Describe → Confirm → Wait → Use`
旅程映射为本地 Streamlit 工作台。UI 是控制面和展示面，不重新实现
Completion Gate，也不把 Agent 的自述转成成功结论。

## 页面

| 页面 | 作用 | 事实源 / 动作 |
|---|---|---|
| 工作台 | 产品概览、最近工具、五步旅程 | registry、release ledger、M4 metrics |
| 新建工具 | GitHub URL + 能力 → 草稿；审核合同与 golden；彩排/构建 | `repoproof tool add/build` |
| 运行活动 | 最近后台任务与日志 | 原子持久化 ProductJobStateV2；日志不产生 PASS |
| 工具库 | 双状态工具列表、调用方式、审核/撤回/MCP 入口 | Core `tool_registry.list_tools(scan=False)` |
| 可信仪表盘 | 接受率、历史 READY、运营状态、false-success | `docs/m4_metrics.json` + 本机状态账 |

旧 Guided Adoption 和 Benchmark Lab 页面完整保留在独立应用
`RepoProof Benchmark Lab` 中。两套应用可以同时打开，产品旅程和模型能力
指标不混算；凡会修改 Core 状态的任务共享同一把仓库级执行锁。

## 信任边界

1. Core 是工具状态的唯一事实源。Studio 只调用
   `tool_registry.list_tools(dest_root, scan=False)`，不自行扫描目录，也不另写
   registry、package identity 或 release-ledger 解析器。
2. 发布账损坏时 UI 不返回可操作工具；task version、package identity、
   symlink 或 provenance 异常一律 fail closed，绝不显示为 `ACTIVE`。
3. `historical_verdict`、`operational_status` 与 package health 三栏独立展示，
   互不覆盖，也不合成一个“成功”。Core reason code（包括
   `TASK_VERSION_UNAUDITED`、`INVALID_PACKAGE_IDENTITY`、
   `LEGACY_SERVER_MUST_BE_DETACHED`）必须完整可见。
4. 只有 `ACTIVE` 工具显示 MCP 生成操作。
5. Product Mode 后台任务位于 `product_jobs` 服务，用 argv 数组启动
   Core CLI，不经过 shell，密钥不进入 argv、
   页面或状态文件。
6. ProductJobStateV2 原子记录 job id/action、
   `RUNNING|SUCCEEDED|FAILED|INTERRUPTED`、worker/child PID 与进程身份、
   时间、exit code、脱敏 argv、日志和预期产物前后签名。PID 单独不构成
   存活证明；PID 复用、worker 消失或终态无法确认时按 `INTERRUPTED` 处理。
7. 后台成功必须同时满足 exit code 0 与相对启动前**新建或变化**的预期
   文件产物；旧文件、目录占位或 audit 非零退出都不算成功。Audit 即使已向
   ledger append `REVOKED`，该后台 action 仍显示 `FAILED`。
8. Studio 与 Lab 的 Core 写任务共同竞争 `<repo>/runs/.core-execution.lock`。
   活跃竞争直接拒绝；损坏或陈旧锁按 fail closed 保留现场，不自动抢占。
9. 草稿使用 Core `ToolOutputContract` 与同一格式校验器；普通文本默认合同为
   `text/plain + text + {}`，JSON/JSONL golden 在构建前即时验证。版本预览
   调用 Core 的只读版本计算，最终 task version 仍由 assembler 分配；冻结
   v1 永不改写。
10. Studio 草稿编辑只发生在 `REPOPROOF_UI_STATE_ROOT/drafts/` 受管目录；
    绝对路径越界、symlink、特殊文件和同名 golden 均拒绝。工具库目标也拒绝
    相对路径、symlink、普通文件以及 `/`、用户主目录、RepoProof 仓根等过宽
    位置。

## 与 RFC-011 / M5 Core 的整合边界

原 UI 分支基于 M4 开发；当前 M6 integration candidate 正在把视觉与信息
架构接到 M5 Core，而不是复制 M5 业务逻辑：

- `tool audit/withdraw`、release ledger、package identity 与受管 MCP 状态均由
  Core 执法；UI 只发起 Core action 并展示 Core 投影；
- 新 Product run 在创建时使用 `test_mode=PRODUCT`、
  `run_purpose=PRODUCT_ONBOARDING`，Benchmark 计分字段为 false；
- Product Mode 与 Benchmark Lab 复用同一 evidence/verification engine，
  实施的是**逻辑分账**，不是物理存储隔离；不得声称 Studio 不接触
  `runs/` 或 evidence；
- 历史 run、旧 ledger 与 M4 指标不回填、不迁移、不改写；
- 产品构建结果不能充当模型能力成绩，Lab 的研究流程也不阻塞普通产品任务。

默认执行 backend 为官方 Codex CLI（复用本机 ChatGPT 订阅登录）；mini-swe
保留为显式 API/provider 兼容选项。DSH 属冻结的 Benchmark Lab 研究线，
不作为 Studio Product Mode 选项。Codex 内部 agent loop 不参与 RepoProof
的模型能力评分，最终判定仍只来自 RepoProof 独立验证与 clean replay。
仓库摘要、在线合同起草和样例候选同样缺省走 Codex 订阅，但使用独立的
`read-only + deny-all-tools + output-schema` 文本通道；它们的输出只能进入
展示/草稿层。样例 expected output 仍由 pinned upstream 真跑并经用户逐条确认。
Agent 只有在用户确认合同与代表性样例后才尝试构建；只有独立验证、clean
replay 与 fresh audit 均成立，当前 task version 才能成为 `ACTIVE`。

## 本地启动

两套应用均只监听本机，可以同时运行：

| 应用 | 普通启动 | 带模型连接 | 地址 |
|---|---|---|---|
| RepoProof Studio | `scripts/run_ui.sh` | `scripts/run_ui_live.sh` | `127.0.0.1:8501` |
| RepoProof Benchmark Lab | `scripts/run_lab_ui.sh` | `scripts/run_lab_ui_live.sh` | `127.0.0.1:8502` |

密钥只从各自进程环境读取。旧历史记录留在原目录，不迁移、不复制、不改写。
