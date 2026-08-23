# RFC-012: Managed Sidecar Tools

- 状态：**EXPERIMENTAL / CANDIDATE**（未关闭、未发布）
- 阶段：M7
- 前置关闭条件：M6 Engineering 与 M6 Preview 均关闭。当前候选代码的并行
  开发不满足、也不豁免这两道门禁
- 依据：
  - [RFC-010](RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md)：Local Tool、独立验证与 clean replay；
  - [RFC-011](RFC-011-TOOL-CONTRACT-COHERENCE-AND-RELEASE-STATE.md)：
    可执行输出合同、历史验证与运营发布状态分离；
  - [ToolContract Schema](../TOOL_CONTRACT_SCHEMA.md) 与
    [Tool Package Layout](../TOOL_PACKAGE_LAYOUT.md)。

本文定义 M7 的候选交付运行时。它把受支持范围从单进程本地 CLI 扩展到
**本地 CPU、无用户密钥、仅 loopback HTTP、每次调用即启即停**的工具，
但用户入口仍是统一的 CLI 与 RepoProof 受管 MCP。

本文不声称 M7 已成为稳定能力，也不把零模型 fixture 的通过等同于真实上游
仓库的成功。首个真实仓 clean replay 必须单独获批；单例只证明支持面存在，
不产生任意仓库成功率 claim。

**产品范围说明：M7 只扩展当前“GitHub capability → verified local tool”产品。**
旧的任意仓适配定位与 Benchmark Lab 只保留隔离、历史兼容和只读研究边界，
不属于本里程碑的开发对象。下文提及 Benchmark 组件仅用于防止 runtime 概念
混用或说明可复用的验证机制，不代表继续建设旧产品路线，也不新增模型比较、
研究任务、计分指标或 Lab UI。

## 一、问题与目标

部分 GitHub 能力天然以进程内服务形态工作：初始化后通过 HTTP 接受一次请求，
而不是由 CLI 进程直接 import 并执行。允许用户填写任意 URL、启动命令或常驻
daemon 会立即扩大可信边界，也会让 CLI、MCP、验证与 clean replay 分叉。

M7 因此只增加一个低自由度 profile：

```yaml
tool:
  schema_version: 3
  runtime:
    mode: http_sidecar
    profile_id: tool-http-sidecar-v1
    lifecycle: per_invocation
    credentials: none
    network: loopback_only
    protocol: repoproof-http-sidecar-v1
    startup_timeout_seconds: 10
    request_timeout_seconds: 120
    shutdown_timeout_seconds: 3
```

目标：

1. 固定交付运行时形状，不开放任意 endpoint、任意命令或显式端口；
2. 让 CLI 与 MCP 经同一 launcher、发布状态和输出合同；
3. 每次调用都可界定启动、readiness、请求、校验和回收；
4. clean replay 只依赖导出包与锁文件，不依赖 RepoProof 外部 runtime 根、
   API Key、云账号或外网；
5. 保留 pinned upstream 真实采用证明，不把 HTTP 包装误当成采用证据。

非目标：浏览器、GPU、私有仓、云账号、多语言 CLI、常驻服务、用户管理端口、
URL 输入、对象参数和扩展 MCP schema。

## 二、三种 runtime 不得混用

RepoProof 目前存在三个名称相近但信任职责不同的概念：

| 概念 | 描述对象 | 生命周期 / 持有者 | 能证明什么 |
|---|---|---|---|
| `ToolSpec.runtime` | **交付包在用户机器上的运行方式** | `bin/<tool>` 每次调用创建和回收 | 本次本地调用遵守固定 sidecar 协议 |
| `TaskContract.runtime_profile` | 构建、执行与验证拓扑 | Harness / runner | 任务按哪个不可变执行 profile 被测量 |
| Benchmark `SidecarSession` / `upstream_sidecar` | 研究与 conformance 的受观测上游调用 | Harness 持有 | run 内调用、receipt 与采用谓词成立 |

因此：

- `ToolSpec.runtime.profile_id=tool-http-sidecar-v1` **不得**写进或复用
  `TaskContract.runtime_profile`；
- 现有 `SidecarSession` 不能复制进交付包充当产品 runtime；
- build-time 的观测代理、签名密钥、nonce 与可信审计材料不能进入交付包；
- 用户运行期的 loopback 调用不是签名 receipt，不能声称具有相同证明强度。

## 三、冻结协议

### 3.1 ToolSpec v3

v3 在 v2 可执行输出合同之上增加 `ToolRuntimeSpec`。字段严格
`extra=forbid`，且首版只接受上文八个固定语义值与有界超时。

- v1/v2 必须省略 `tool.runtime`，继续按原语义加载；
- v3 必须提供 `tool.runtime`；
- v3 首版输入只允许 `kind=file`，输出只允许 `kind=stdout`；
- 不允许 `launch_command`、host、port、URL、daemon lifecycle 或 credential
  配置；
- `tool.json.runtime.delivery` 必须是冻结 `tool.runtime` 的完整投影。

这是一条 schema 加法演化边界，不回写 v1/v2 冻结合同。任何旧工具若要采用
managed sidecar，必须创建新的 task version。

### 3.2 HTTP 协议

Supervisor 只允许启动装配器生成的固定 Python 模块，并执行：

```text
bind 127.0.0.1:0
  → 生成一次性内部 token
  → 等待原子 readiness record
  → GET /healthz
  → POST /v1/invoke
  → 校验 request_id、响应 envelope 与 ToolOutputContract
  → 无条件 terminate / kill / wait
```

协议固定要求：

- 只绑定 `127.0.0.1`，端口由 OS 动态分配；
- readiness 必须绑定 host、port、protocol 与实际 child PID；
- `GET /healthz` 与 `POST /v1/invoke` 都要求一次性内部 token；
- token 由 supervisor 每次生成，只用于本次进程间握手，不是用户 credential，
  不写入合同、manifest 或 evidence；
- invoke 请求只承载 `request_id` 与本地 `input_path`；
- 响应只承载成功 stdout 或有界错误 envelope；
- 请求、响应 envelope、错误消息和各阶段时长均有上限；
- 生成 server 只绑定 loopback；候选实现的 Python audit guard 只能作为
  进程内补充探针，**不是 OS 级网络隔离**。在子进程、UDP、DNS、Unix
  socket 等绕行面尚未由 OS sandbox 关闭前，不能据此声称外连被强制禁止。

`credentials: none` 的含义是用户不提供 API Key 或服务账号；它不取消上述
内部、一次性、不可复用的进程握手 token。

## 四、唯一调用链

交付包只有一条受支持调用链：

```text
用户 / MCP
    ↓
bin/<tool>
    ↓
Python CLI main（输入和 exit-code 语义）
    ↓
sidecar_supervisor
    ↓
一次性 sidecar_server → pinned upstream 能力
    ↓
响应绑定 + ToolOutputContract 校验
    ↓
stdout
```

MCP adapter 必须 subprocess 调用同一 `bin/<tool>`，不得直连端口或 import
sidecar 实现。这样 `ACTIVE / REVIEW_REQUIRED / REVOKED` 执法、exit code、
stderr/stdout 边界和输出合同不会因入口不同而漂移。

同一输入的 CLI 与 MCP 必须得到相同成功输出或等价稳定错误。
`REVIEW_REQUIRED` 与 `REVOKED` 均阻止 RepoProof 受管 MCP 调用；用户绕开
RepoProof 手工执行包内 bin，仍不在运营 ledger 的 OS 强制边界内。

## 五、装配与 clean replay

ToolSpec v3 包在 v2 布局上增加：

```text
src/<package>/
├── main.py                 # 唯一 CLI 入口，调用 supervisor
├── impl.py                 # agent 实现；必须采用 pinned upstream
├── sidecar_server.py       # 固定 loopback HTTP server
├── sidecar_supervisor.py   # 生命周期、timeout、绑定与回收
└── sidecar_contract.py     # 从 ToolOutputContract 生成的 stdout 校验器
```

`__init__.py`、`__main__.py`、`main.py`、`sidecar_server.py`、`sidecar_supervisor.py`、
`sidecar_contract.py`、`bin/<tool>`、`build.sh`、`tool.json` 与
`pyproject.toml` 是 harness 结构锚。装配时逐文件冻结 SHA-256，最终验证按
普通文件、无 symlink 和摘要逐项核对；仅在人读 prompt 中写“不得修改”不算
执法。Agent 只负责 `impl.py` 中的上游采用与锁定依赖，其自述不产生成功结论。

clean replay 必须从导出包的 `build.sh`、`requirements.lock.txt` 和包内源码
重建。不得读取 RepoProof checkout 之外的 DSH/runtime 根，不得读取 API Key，
不得访问公网，也不得依赖上一次调用遗留的 daemon、端口或进程。

## 六、可信采用与 receipt 边界

Managed sidecar 只解决**交付期进程拓扑**，不自动证明 agent 使用了上游。
构建与验证仍由 Harness 持有观测代理并生成签名 receipt，复用既有 U1–U4
谓词与不可变 RuntimeProfile ID 原则：

- receipt 绑定本次 run/nonce、pinned package、目标 symbol 与输入；
- receipt 绑定真实返回值及最终 stdout 的采用关系；
- verifier 独立读取签名证据，agent 无签名密钥；
- clean replay 重获行为证据，不接受旧 receipt 充当本次调用。

在“真实子进程调用 → 返回值 → 最终 stdout”尚未可靠绑定前，即使能力样例
通过，运营结果最多为 `REVIEW_REQUIRED`，不得称为 verified 或 `ACTIVE`。
当前候选实现因此对所有 ToolSpec v3 固定返回
`MANAGED_SIDECAR_TRUST_PENDING`：旧 ledger 中伪造或遗留的 `ACTIVE`、以及
fresh audit PASS 都不能越过该闸；MCP 生成和调用同样被阻止。历史 verdict
保持原样，不因这道运营闸被改写。

首次安装 v3 时，该 reason code 还会作为绑定 `tool + task_id` 的 append-only
release 记录写入。随后原地篡改 `tool.json`、provenance 或 task id，因与注册
身份冲突而 fail closed，不能把同一 task 伪装成 v2 来继承 `ACTIVE`；经受管
installer 产生的真正新 task version 则建立自己的独立运营状态。未来若关闭
强 receipt 与 OS 隔离，也只能为新 task 或显式迁移追加记录，不得删除或回写
这条历史记录。

## 七、确定性验收与攻击矩阵

### 7.1 schema / assembler

必须拒绝：v3 缺 runtime、额外 runtime 键、非 loopback network、常驻
lifecycle、任意启动命令、构建/交付 profile 混用、非 file 输入或非 stdout
输出。v1/v2 的加载和历史重放必须保持不变。

### 7.2 生命周期与协议故障

零模型 fixture 至少覆盖：

- startup、request、shutdown timeout；
- child 提前退出、崩溃、malformed response、错误 request binding；
- 超大请求或响应、无效 JSON、输出合同不匹配；
- 动态端口并发与端口竞争；
- 外连尝试被拒；
- 在 supervisor 自身仍可执行清理的成功、失败、超时和 child 提前退出路径中
  均无孤儿进程，并覆盖 TERM→KILL 升级；supervisor 被外部 `SIGKILL` 后的
  父死亡回收在具备 OS 级机制前是已知缺口，不能被测试措辞掩盖。

### 7.3 receipt 攻击矩阵

M7 不另造一套 receipt。既有 conformance/receipt 测试必须继续拦截：

| 攻击 | 必须失败的原因 |
|---|---|
| never-call / pure reimplementation | 没有本次真实上游调用 |
| fake package / vendored copy | package / provenance 与 pinned 上游不符 |
| wrong symbol | 调用目标不属于冻结能力 |
| call-ignore-result / uncorrelated call | 返回值未绑定最终 stdout |
| replay old receipt | run nonce、调用次数或本次输入不匹配 |
| truncated result | 返回值与最终采用的完整性不成立 |
| tampered / forged evidence | 签名或 receipt 内容校验失败 |

### 7.4 关闭顺序

1. 零模型 fixture 关闭 schema、assembler、协议和 conformance；
2. CLI/MCP 同输入同结果及运营状态执法通过；
3. 强 U1–U4 receipt 可靠绑定真实子进程返回值与最终 stdout；
4. OS 级网络/进程隔离关闭 audit-hook 绕行和父进程被杀后的残留面；
5. clean replay 证明包独立于 RepoProof 外部 runtime、密钥和外网；
6. 单独授权后，选择一个公开 Python、CPU、无密钥仓进行真实构建与 replay；
7. 保守记录该单例，不外推成功率，再决定是否关闭 M7。

在以上门禁前，ToolSpec v3 与 managed sidecar 都只能标记为
`experimental/candidate`。
