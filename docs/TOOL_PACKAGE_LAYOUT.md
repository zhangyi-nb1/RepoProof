# Tool Package Layout 规范（v1/v2 stable + v3 managed-sidecar candidate）

- 状态:v1/v2 布局已实施；v3 managed-sidecar 是加文件演化，当前仅
  **experimental/candidate**
- 依据:[RFC-010](rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md) §三 [D1];
  [TOOL_CONTRACT_SCHEMA.md](TOOL_CONTRACT_SCHEMA.md)(`ToolSpec` 单一事实源)；
  [RFC-012](rfc/RFC-012-MANAGED-SIDECAR-TOOLS.md)
- 一句话:**交付物 = 一个自带构建声明与证据的目录**;"可安装"由
  clean replay 从声明重建来证明,不由"在我机器上能跑"来声称。

## 一、交付物布局(用户拿到的东西)

```
pdf-table/                          # 工具包根 = 交付物
├── tool.json                       # Tool Manifest,机读核心(§二)
├── README.md                       # 人读:用法/样例/来源/验证摘要
├── bin/
│   └── pdf-table                   # CLI 壳:exec "$ROOT/.venv/bin/python" -m pdf_table "$@"
├── src/
│   └── pdf_table/
│       ├── __init__.py
│       ├── __main__.py             # python -m pdf_table 固定入口
│       ├── main.py                  # argparse + CLI 错误边界（骨架预置）
│       └── impl.py                  # 能力实现（agent 交付）
│       # ToolSpec v3 另增加（v1/v2 不生成）：
│       ├── sidecar_server.py        # 固定 127.0.0.1:0 HTTP server（结构锚）
│       ├── sidecar_supervisor.py    # 每次调用的启动/readiness/请求/回收
│       └── sidecar_contract.py      # 从 ToolOutputContract 生成的 stdout 校验
├── requirements.lock.txt           # 全量 pinned(含上游 pinned 版本,== 钉死)
├── build.sh                        # 唯一构建声明:python3 -m venv .venv
│                                   #   && .venv/bin/pip install -r requirements.lock.txt
│                                   #   && .venv/bin/pip install -e .
├── pyproject.toml                  # 工具包自身元数据(name/entry)
└── evidence/                       # 证据包(EXPORT_ONLY 纪律,held-out 绝不进包)
    ├── report.json                 # gate 判定 + 四验证器结构化结果
    ├── run_manifest.json           # 契约 sha/prompt sha/模型/预算用量
    ├── provenance.json             # 上游 url/commit/license/distribution
    └── replay.json                 # clean replay 结论(mode=clean_adoption)
```

规则:
- **`.venv/` 永不进交付物**——venv 是 `build.sh` 的产物,可再生件
  (收线纪律的直接沿用:交付声明,不交付环境);
- `evidence/` 由 harness 写入,agent 不可写(policy 路径护栏);
- 布局键名冻结后按"加文件不改语义"演化。

## 二、`tool.json` Manifest Schema

```json
{
  "manifest_version": 1,
  "name": "pdf-table",
  "version": "1.0.0",
  "summary": "从 PDF 提取表格,输出 GitHub-flavored Markdown",
  "source": {
    "url": "https://github.com/jsvine/pdfplumber",
    "resolved_commit": "<pinned>",
    "license": "MIT",
    "distribution": "pdfplumber"
  },
  "interface": {
    "usage": "pdf-table <input.pdf> [--out FILE]",
    "input":  {"kind": "file", "format": "PDF"},
    "output": {"kind": "stdout", "format": "markdown-table"},
    "exit_codes": {"0": "success", "1": "user_error", "2": "internal_error"}
  },
  "runtime": {"python": "3.12", "cpu_only": true, "offline": true},
  "verification": {
    "verdict": "VERIFIED_TOOL_READY",
    "contract_sha256": "<冻结契约哈希>",
    "gate_report": "evidence/report.json",
    "replay_mode": "clean_adoption"
  }
}
```

v1/v2 的 `runtime.delivery` 省略（旧 manifest 无需回写）。ToolSpec v3 把
冻结 runtime 完整投影到该位置：

```json
{
  "runtime": {
    "python": "3.12",
    "cpu_only": true,
    "offline": true,
    "delivery": {
      "mode": "http_sidecar",
      "profile_id": "tool-http-sidecar-v1",
      "lifecycle": "per_invocation",
      "credentials": "none",
      "network": "loopback_only",
      "protocol": "repoproof-http-sidecar-v1",
      "startup_timeout_seconds": 10,
      "request_timeout_seconds": 120,
      "shutdown_timeout_seconds": 3
    }
  }
}
```

- `interface` 与冻结契约 `ToolSpec` **逐字段一致**(交付期静态检查,
  [TOOL_CONTRACT_SCHEMA.md](TOOL_CONTRACT_SCHEMA.md) §五);
- `verification` 由 harness 在 gate 后写入;agent 写的 manifest 里该键
  必须为 null(写了非 null = 越权声明,policy 拦截——agent 声明不产生
  成功结论的铁律在 manifest 层的落点);
- **M3 的 MCP/Python API 暴露就是本文件的机械转换**:`interface` →
  MCP tool schema;`bin/` 壳 → MCP server 进程。v1 不实现,只保证
  本文件字段充分。
- v3 的 MCP 仍只能 subprocess 调同一 `bin/<tool>`；不得读取
  `runtime.delivery` 后绕过 CLI 直连动态端口。

## 三、会话内布局(agent 工作区;对应旧 /host /upstream /adaptation)

```
会话根/
├── host/                # = 工具包根(骨架直接挂载为 host;editable_zones=["."])
│   ├── …(§一全部结构,impl.py 为空壳,evidence/ 不存在)
│   └── public_tests/    # 公开样例测试 + 接口契约骨架半(运行期由任务包注入)
└── upstream/            # pinned 上游快照(只读;策略同现行)
```

> 执行面实现注(M1 定稿):早稿设想会话内独立 `tool/` 层;实施采用
> **骨架即会话 host 根**——省一层目录、`git diff S0..best` 天然全计
> 交付(AdaptationManifest 零改动),`_delivery_dirs` 对 LOCAL-TOOL
> 短路。公开测试不进骨架交付物,由任务包在装配会话时注入。

- oracle(held-out 样例 + 接口契约测试)照旧 **harness 持有,不进会话**;
- `tool/` 即旧 `/adaptation` 的语义平移:S0 基线 git commit → 每轮 commit
  → 最优轮 diff = AdaptationManifest 冻结,机制零改动;
- 通用 delivery extractor(🔴新写):取 `tool/` 全树,排除
  `.venv/ __pycache__/ *.pyc .git/`,树哈希进 AdaptationManifest。
  工具谱系交付形状固定,故一个 extractor 服务所有工具任务
  (对照:sidecar 任务一任务一个手写 extractor)。

## 四、骨架与 agent 的责任分界(结构锚,T3v6 经验的直接沿用)

**harness 生成骨架,agent 填肉。** 接口形状是合同的一部分,不是 agent
的发挥空间——这继承"结构型锚"的实测教训:锚定结构后归因才干净。

| 件 | 谁写 | 说明 |
|---|---|---|
| `tool.json`(interface/source) | 骨架 | agent 不可改 interface(policy 检查 diff) |
| `bin/` 壳、`pyproject.toml`、`build.sh` | 骨架 | 构建协议统一,replay 才可通用 |
| `main.py` 的 argparse + 输入存在检查 | 骨架 | = HOST_INPUT_GUARD,不计 agent 能力 |
| `main.py` 的能力实现(调 pinned 上游) | **agent** | 核心交付 |
| 坏输入内容的错误包装(exit 1 vs traceback) | **agent** | 能力的一部分(Chonkie 教训) |
| `requirements.lock.txt` 的依赖锁定 | **agent** | 上游 pinned 版本必须入锁;replay 从它重建 |
| `README.md` 用法段 | agent | 事实性由样例背书,不允许成功声明措辞 |
| `evidence/` | harness | agent 不可写 |

ToolSpec v3 调整其中两项责任但不扩大可编辑面：

| v3 文件 | 谁写 | 说明 |
|---|---|---|
| `main.py` | harness | CLI 错误码与 stdout/stderr 边界；只调用 supervisor |
| `impl.py` | **agent** | 调用 pinned upstream 并返回文本结果 |
| `sidecar_server.py` | harness | 固定 loopback 协议；agent 不可改 |
| `sidecar_supervisor.py` | harness | token、动态端口、timeout、无条件回收；agent 不可改 |
| `sidecar_contract.py` | harness | 同一 ToolOutputContract 的生成投影；agent 不可改 |

以上 harness 文件连同 `__init__.py`、`__main__.py`、`bin/<tool>`、`build.sh`、`tool.json`、
`pyproject.toml` 在 HostContract 中逐文件冻结摘要，最终按摘要执法；`impl.py`
是唯一 sidecar 能力编辑面。摘要不覆盖可再生 `.venv`，也不能替代 OS sandbox。

构建期签名 receipt、观测代理和密钥仍由 Harness 持有，永不进入以上交付
文件。交付期 sidecar 调用本身不能伪称为签名采用证明。

## 五、安装与运行模型(用户视角)

```bash
# 安装(= clean replay 在用户机器上的同构动作)
cd ~/tools/pdf-table && ./build.sh

# 使用
./bin/pdf-table report.pdf            # 表格 Markdown → stdout
./bin/pdf-table report.pdf --out t.md
```

- 安装目标目录 v1 约定 `~/tools/<name>/`;M3 注册表
  (`repoproof tool list`)记录 已装工具 → manifest → 证据 的索引;
- **replay 即安装测试**:clean replay 的动作(空白环境 → build.sh →
  重跑全部验收)与用户首次安装同构——PASS 直接回答"别人机器装得起来"。

v3 对用户仍是相同命令。每次 `bin/<tool>` 调用内部创建一次性 sidecar：
固定绑定 `127.0.0.1` 动态端口、完成 health/invoke、校验输出合同，然后无条件
回收。它不要求用户管理端口、daemon 或 credential。当前候选尚无 OS 级网络
隔离，因此“loopback_only”只描述固定协议绑定，不能宣称已阻断所有外连。
clean replay 不能依赖 RepoProof checkout 外部的 runtime 根、API Key 或前次
调用残留进程。

## 六、与四平面的对接(零新概念清单)

| 平面 | 对接点 | 改动 |
|---|---|---|
| Task Authoring | `assemble_tool_task` 生成骨架+oracle+控制组 | 新模板(M1 主体工作量) |
| Agent Execution | editable_zones=[tool];预算/策略/trace | 零 |
| Verification | capability=golden 样例;regression=接口契约;policy 照旧;replay=build.sh 重建 | 语义平移([TOOL_READY_GATE.md](TOOL_READY_GATE.md)) |
| Evidence | evidence/ 目录 = bundle 导出的工具内嵌形态 | export_bundle 加落点 |
