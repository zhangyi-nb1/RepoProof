# RepoProof Studio · Product Mode UI

RepoProof Studio 把 RFC-010 的 `Find → Describe → Confirm → Wait → Use`
旅程映射为本地 Streamlit 工作台。UI 是控制面和展示面，不重新实现
Completion Gate，也不把 Agent 的自述转成成功结论。

## 页面

| 页面 | 作用 | 事实源 / 动作 |
|---|---|---|
| 工作台 | 产品概览、最近工具、五步旅程 | registry、release ledger、M4 metrics |
| 新建工具 | GitHub URL + 能力 → 草稿；审核合同与 golden；彩排/构建 | `repoproof tool add/build` |
| 运行活动 | 最近后台任务与日志 | `~/.repoproof/product-job.json`；日志不产生 PASS |
| 工具库 | 双状态工具列表、调用方式、审核/撤回/MCP 入口 | tool.json、registry、release ledger |
| 可信仪表盘 | 接受率、历史 READY、运营状态、false-success | `docs/m4_metrics.json` + 本机状态账 |

旧 Guided Adoption 和 Benchmark Lab 页面完整保留在独立导航分组，不与
Product Mode 指标混算。

## 信任边界

1. UI 只读取现有事实；发布账缺失或损坏时一律投影为 `REVIEW_REQUIRED`。
2. 历史验证与当前运营状态并列展示，互不覆盖。
3. 只有 `ACTIVE` 工具显示 MCP 生成操作。
4. UI 后台任务用 argv 数组启动 Core CLI，不经过 shell，密钥不进入 argv、
   页面或状态文件。
5. 后台成功必须形成相对启动前**新建或变化**的预期产物；旧文件不算成功。
6. 草稿编辑只发生在用户选择的 draft 目录；同名 golden 文件拒绝覆盖。
7. UI 不修改冻结合同、历史 run、Benchmark ledger 或已导出的工具包。

## 与 RFC-011 / M5 合并

本 UI 基于 M4 已提交点独立开发。它不复制 M5 业务逻辑，而是按能力探测
`tool audit/withdraw`：

- M5 尚未合并时，审核与撤回入口显示“核心命令待接入”；
- M5 合并后，入口自动调用 Core CLI；
- release ledger 仍由 Core 写入，UI 只折叠并展示；
- M5 的可执行输出合同可以在“审核成功标准”中查看和编辑 JSON 投影。

## 本地启动

继续使用现有 `scripts/run_ui.sh`。应用只监听 `127.0.0.1`，默认首页已经是
Product Mode。需要真实模型连接时使用 `scripts/run_ui_live.sh`；密钥只从
进程环境读取。
