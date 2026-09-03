# RepoProof M6.2 续作交接与修改纪律

> 更新时间：2026-09-01（Asia/Shanghai）  
> 适用分支：`codex/m6-2-workspace-bundle-qualification`  
> Core 实现锚点：`7db6e65`  
> 用途：交给下一位 AI 继续 M6.2；本文件是当前续作入口，不改写旧合同、旧 run、旧 ledger 或既有资格终态。

> **2026-09-02 续作完成快照（append-only，本文件其余段落保留为 09-01 交接原貌）**
>
> §四的 P0/P1/P2 已全部执行完毕；权威状态见 `docs/HANDOFF_STATE.md` 的
> 2026-09-02 Current status 与 `docs/EXPLORATION_LOG.md` 尾部两条。要点：
>
> - C6 marimo → `tool-marimo-tool-v3`、B1 → `tool-research-project-starter-v3`、
>   B2 → `tool-csvkit-tool-v1`、C1 → `tool-pdfplumber-tool-v1`、C2 →
>   `tool-trafilatura-tool-v1` 全部 `VERIFIED_TOOL_READY + ACTIVE + package OK`；
>   连同 NetworkX v4 / Datasette v3 / Textual v3，八个真实案例均有修复后成功证明，
>   首轮九个正式终态一字未改。
> - 两份 append-only `QualificationExecutionRecordV2`：
>   `docs/qualification_runs/m6_2_workspace_bundle_v2/…-first-pass-20260902.json`
>   （九案首轮终态，逐字来自冻结 `case-result.json`）与 `…-follow-up-20260902.json`
>   （八案 PASSED，语义证据经 Core 自身的 ledger→release-audit→nested 解析路径绑定）。
> - 冻结晋级门（B1+B2+≥4 复杂含 SQLite 与可运行应用）已满足，profile 记为
>   `SUPPORTED`（成熟度只在文档层落账；MCP 对目录工具仍固定拒绝）。
> - 本轮六项通用 Harness 修复各有 incident + 匿名前后控制 + `HarnessChangeEvidenceV1`：
>   admission 密钥 AST 全树扫描、import-hook 参数摘要透明、conformance 执行根探测、
>   oracle 收集范围、fresh-audit 逐提案物化与排除反馈、conformance 准入面对齐
>   pytest 实际收集面。三个冻结任务的 `conformance.json` 保持 `SKIPPED` 不改写。
> - 回归载具 `scripts/workspace_case_replay.py`（冻结 oracle 尺子 + 密封 wheelhouse +
>   离线重建），八工具在收口 framework 树下全 PASS，证据在
>   `runs/evidence/workspace-replays/`。
> - 起草物质量已由人工审阅改为系统自检自修（`tool self-check`；`tool add` 自动执行；
>   readiness `DRAFT_SELF_CHECK_*` 阻塞冻结），真实缺陷草稿端到端演示 v4 零人工通过。
> - 下一批出题草案见 `docs/m6_3_complex_workspace_qualification_v1.yaml`（未冻结）。
> - 未推送、未发布；`.claude/launch.json` 已恢复为提交版本。

## 一、接手时先区分四类事实

1. **已提交 Core 实现**：以本分支 Git 历史为准；`7db6e65` 是完成 Textual v3 前最后一个 Core 修复提交。
2. **当前工作树改动**：包括 Product append-only run 行、重建后的 `docs/v2_gate.json` / `docs/product_summary.json`、通用测试守卫和本交接文档；不得说成已经推送到 GitHub。
3. **本机未跟踪任务资产**：NetworkX、Datasette、Textual 各版本的 `contracts/`、`controls/`、`oracle/` 和 `fixtures/`。这些目录很大且包含离线 wheel，不得清理、覆盖或用 broad `git add .` 误提交。
4. **外部运营事实**：`/Users/zhangronglei/tools` 下的 registry、package 与 append-only release ledger 决定当前能否 `ACTIVE`；Agent 自述、Worker exit 0 或历史 READY 均不能替代它。

事实冲突时按以下顺序处理：冻结合同与 task package → run/evidence → append-only release ledger → Core registry 投影 → Journey/结构化动作结果 → UI 文案。日志只用于排障，不能反推可信结论。

## 二、当前进度

### 2.1 产品与工程边界

主定位仍是：

> GitHub 单能力 → 经独立验证的本地工具（Verified Local Tool）。

M6.2 只扩展 `workspace_bundle_v1`：一个本地文件或目录生成一个离线、多文件工作区，并经过结构、格式、领域语义、运行、clean replay 和 fresh audit。没有启动 M7 sidecar，没有恢复旧宿主适配路线；`host_guided.py` 仍属于冻结 Lab/legacy 资产。

`workspace_bundle_v1` 当前仍是 **EXPERIMENTAL**。升级为 `SUPPORTED` 的冻结门槛仍是：B1、B2 均 `ACTIVE`，且 C1–C6 至少四个 `ACTIVE`，其中至少一个是 SQLite/二进制工作区、至少一个是可运行应用工作区。

### 2.2 正式初次终态与后续修正证明必须分开

原资格文件中的失败终态不得覆盖。后续新 task version 达到 ACTIVE，只能追加为“修复后能力证明”。

| 案例 | 原正式终态（保留） | 修复后/当前事实 |
|---|---|---|
| N0 Browser Use | 预期拒绝，`UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT`，0 Agent | 安全准入负控成立 |
| B1 Cookiecutter | `FAILED / UPSTREAM_CONFORMANCE_ENVIRONMENT`，0 Agent | 尚未用新 task version 重试 |
| B2 csvkit | `FAILED / DRAFTER_INVALID_MODEL_OUTPUT`，0 Agent | 尚未用新 task version 重试 |
| C1 pdfplumber | `FAILED / FIXTURE_INPUT_DUPLICATE`，0 Agent | 通用 builder 绑定已修，但案例尚未用新 task version 重试 |
| C2 Trafilatura | `FAILED / FIXTURE_BUILDER_FAILED`，0 Agent | 同上 |
| C3 NetworkX | 原记录 `FAILED / WORKSPACE_OUTPUT_SCHEMA_PROJECTION_MISMATCH` | `tool-networkx-tool-v4` 已达 `VERIFIED_TOOL_READY + ACTIVE + package OK` |
| C4 Datasette | 原记录 `FAILED / DRAFT_CREATION_FAILED + LIFECYCLE_MISMATCH` | `tool-datasette-tool-v3` 已达 `VERIFIED_TOOL_READY + ACTIVE + package OK`；覆盖 SQLite 与可运行工作区 |
| C5 Textual | 原记录 `FAILED / DRAFT_CREATION_FAILED + EXTERNAL_SIDE_EFFECT_MISMATCH` | v2 历史 READY、当前 `REVOKED/BUILD_FAILED`；v3 已达 `VERIFIED_TOOL_READY + ACTIVE + package OK` |
| C6 marimo | 原记录 `FAILED / EXTERNAL_GATEWAY_UNAVAILABLE + DRAFTER_TIMEOUT` | 尚未启动新的可执行 task version |

因此现在已经形成三个复杂工作区的修复后完整成功证明：NetworkX、Datasette、Textual。它们是记录案例，不是任意仓库成功率；原资格首轮失败记录仍然成立。

### 2.3 Textual v3 的完整闭环

- Journey：`1ce6ef14839b4f8096cb8a36ee68dab0`
- task：`tool-textual-taskdesk-v3`
- rehearsal job：`991a3b5b708c48bb81080cad56d6cc85`
- real build job：`a035ed8d72424ecc8e10aefbcbc9535a`
- run：`tool-textual-taskdesk-v3-20260901-180812`
- fresh audit job：`b721d44590104e3aa7ec73c4ea517f1b`
- fresh input：模型提出 `unicode-mixed-status-log`，冻结 builder 生成真实目录；冻结 reference 生成期望目录
- 最终：`historical_verdict=VERIFIED_TOOL_READY`、`operational_status=ACTIVE`、`health=OK`
- fresh audit：结构通过、语义 verifier `textual-taskdesk-workspace-semantic-v1` 通过、目录树 SHA-256 `c087cf93e38b0c60f6225d24edf8642e2cb038f4d5d27c42a9619567c9798515`
- repair：真实构建为 `NO_REPAIR_NEEDED`

Textual v2 的撤回记录必须保留：它证明“历史验证与 clean replay 通过，但 fresh audit 重建仍可能失败”，正是发布治理存在的价值。v3 不是对 v2 ledger 的改写，而是新 task version。

## 三、本轮遇到的问题与已做的通用修复

### 3.1 意图准入与安全拒绝

问题：关键词式拒绝会把本地离线敏感数据处理误判为外部危险操作，也会漏掉否定语义、凭证、浏览器、常驻生命周期和不可逆外部写入的组合风险。

通用处理：将准入改成结构化交付维度和风险分类；明确区分可选凭证查找、显式否定、联网、浏览器、生命周期、运行环境与外部副作用。相关提交从 `1a2c6fa`、`2dba9b6`、`f215b76`、`0e6d325` 到 `772905f`。安全拒绝可以首例修复，但仍需匿名正/负控证明没有误拒本地离线任务。

### 3.2 模型起草与合同投影

问题：provider 结构化输出可能缺默认字段、返回非法长表单、把机器负责的目录拓扑误当成用户需求、或在 review/新 task version 时丢失已确认的 delivery topology。

通用处理：严格 schema 完整性、保留 invalid-output 真实语义、为长表单设置有界预算/超时、编译可满足的 workspace contract、把用户确认的 delivery requirements 与模型建议分离并跨审核/新版本保持。主要提交：`d475b43`、`78d89fa`、`4cf2923`、`1ec428a`、`a3a0dd0`、`358dee0`、`7393792`、`576381a`、`8a9d368`、`65cf19c`。

### 3.3 Fixture、reference 与真值绑定

问题：

- 多个自然场景可能被 builder 生成成相同输入；
- 模型给出的路径可能越出候选根目录；
- builder 未真实消费 `blueprint.parameters`；
- 用户确认后若语义或 blueprint 改变，旧候选可能仍被展示；
- reference 的 exact tree 看似通过，但领域 verifier 可能不同意；
- oracle 权限硬化、答案键残留扫描与运行依赖曾被混为一类。

通用处理：输入唯一性、参数绑定、便携路径投影、候选 token 绑定当前语义指纹、确认前运行领域语义筛查、区分 golden truth / oracle hardening / runtime closure。主要提交：`a973f93`、`38b1b10`、`55bad9e`、`303a830`、`e2f8277`、`c502966`、`356114b`、`7d324f8`、`3b6d470`、`ed574f0`、`f9a679c`、`4c56128`。

### 3.4 Preflight、conformance 与离线 runtime

问题：

- 可运行 workspace 在开发 venv 能跑，但只带导出物时缺依赖；
- conformance 的短 symbol 可能选中与能力无关或需要额外插件的上游测试；
- Core 自己声明的格式 validator（例如 YAML）依赖没有进入同一密封 runtime；
- reference/runtime 的所有权不清会让 task author 或 Agent 被迫补 Harness 依赖。

通用处理：密封 runnable 依赖闭包；Core 选择确实可运行且能力相关的上游节点；Harness-owned validator 依赖进入同一 lock/wheel closure；reference 运行时由 Core 持有。主要提交：`2b1a9cb`、`200bd03`、`769cfb9`、`2a8a9ae`、`94df208`、`e7fc1b8`、`96e381d`。

### 3.5 Textual v2 暴露的发布 false-success 边界

现象：v2 已是 `VERIFIED_TOOL_READY`，但 fresh audit 的强制 rebuild 运行 `pip install -e .`，从而引入未冻结的 PEP 517 build backend；wheelhouse 只冻结业务 runtime，不保证存在 setuptools/wheel。NetworkX/Datasette 先前偶然通过，不能证明协议正确。

违反的不变量：导出工具必须只依赖冻结 lock 与 wheelhouse 重建和运行；本地 Harness-owned source 不应在发布审计时新增未声明 build backend。

通用修复：`7db6e65` 让导出包只安装冻结 requirements，并用 `PYTHONPATH="$ROOT/src" python -m <package>` 运行本地 source；匿名负控先复现缺 setuptools，修复后通过。证据：

- `runs/product-incidents/incident-workspace-package-build-backend-v1.json`
- `runs/harness-changes/harness-change-workspace-source-runtime-launch-v1.json`
- `tests/test_workspace_tool_assembler.py::test_workspace_package_build_does_not_require_unfrozen_build_backend`

Textual v3 的 fresh audit 已用真实导出包证明该修复生效。

### 3.6 最新全量测试暴露的非产品链问题

首次全量 pytest 有 8 个失败，均已按通用测试不变量处理：

- 新 Product run 进入 append-only `benchmarks/v2/runs.jsonl` 后，`docs/v2_gate.json` 与 `docs/product_summary.json` 过期：运行官方生成器重建，不手改数字。
- Lab 冻结测试把 multiline 调用和源码绝对行号当成行为：改为检查方法内阶段顺序与 AST 函数所有权，仍能抓住真实顺序/重复累加问题。
- UI 密钥守卫用裸 `"sk-"` 子串，误伤 `taskdesk-v3`：改为检测 API-key 形状和明确环境变量名，不降低真实泄漏检查。
- host coverage 棘轮追加 Datasette 与 Textual；它们仍是 Product 记录，不计 Benchmark Lab 模型能力。

## 四、下一位 AI 必须完成的任务

### P0：先接续 C6 marimo

1. 不改原 `c6` 失败记录；创建新的 Journey/task version。
2. 使用冻结仓库、commit、wheelhouse 与原模糊需求；默认 LiteLLM/API 网关起草、mini-swe 实现，不切换 Codex backend。
3. 先完成仓库建议、合同、至少三组 builder 输入/期望 workspace、零模型 rehearsal。
4. 只有 `failure_owner=AGENT_ADAPTER` 的公开失败可进入最多两轮 repair。
5. 达到历史 READY 后必须继续 clean replay 与 fresh audit，最后由 registry/ledger 确认 `ACTIVE + package OK`。

### P1：用新 task version 回补 B1、B2

这是 profile 升级的硬门槛，不能只靠 C3–C6 成功绕过。

- B1：验证新的 conformance 节点选择与 Harness test-toolchain closure 是否已经解决 `pytest-mock` 类环境问题。
- B2：验证严格 drafter schema、长表单预算与机器-owned delivery projection 是否能稳定形成合法 contract。
- 原失败终态不改写；新增 append-only follow-up qualification record，显式映射“原案例 → 新 task/run → 当前运营状态”。

### P1：回补 C1、C2，提高本轮合理完成率

两例复杂度没有超出支持面，且相同 builder 参数绑定根因已经通用修复。用新 task version 重新执行，目标是验证修复是否真正泛化，而不是为了改漂亮通过率。

### P1：每次 Core 修复后的回归

对 NetworkX v4、Datasette v3、Textual v3 运行零模型合同回归、结构/语义验证和 clean replay；不得重跑或替换它们的真实 Agent 历史 run。若 replay 在新 framework SHA 下失败，追加新 incident，不能静默忽略。

### P2：M6.2 关闭与 profile 判定

1. 生成 append-only `QualificationExecutionRecordV2`，同时列出初次终态与后续新版本，不覆盖旧 `case-result.json`。
2. 达到 B1+B2+至少四个复杂 ACTIVE 的冻结门槛后，才把 profile 改成 `SUPPORTED`；否则工程可继续收口，但状态保持 `EXPERIMENTAL`。
3. 跑全量 pytest、Ruff、mypy、`git diff --check`、Streamlit 双入口 smoke、Core 特例扫描和所有已完成案例 replay。
4. 更新 `docs/HANDOFF_STATE.md` 的 Current status；旧段落下移保留，不能删除历史。

## 五、每次修改必须遵守的原则

1. **先事故，后改代码**：冻结 framework SHA、stage、owner、公开 reason code 与 normalized fingerprint。
2. **先写通用不变量**：说明系统本应保证什么；不能写“让某仓通过”。
3. **先匿名复现**：合成 fixture 不含仓库名、commit、task id、领域字段或私有路径；保存修复前失败证据。
4. **安全/false-success 首例可修**：但仍需匿名负控、修复后正控、特例扫描和回归证据。
5. **普通非安全问题需第二独立任务**：同一仓 v2/v3 不算两个独立仓；只有单例时记录 incident，不改 Core。
6. **冻结件不可变**：合同、oracle、fixture、旧 run、旧 ledger 与历史指标不改写；语义改变必须新 task version。
7. **repair 只修 Agent**：仅 `AGENT_ADAPTER`、公开可见、实际有 adapter diff 的失败可 repair；Harness、Contract、Upstream、Gateway、held-out、replay、release 故障均零 repair。
8. **不泄露 held-out**：prompt 只给公开 commitments、节点、错误类型和结构差异类别；不能给隐藏输入、期望内容、私有路径或目录哈希。
9. **状态三分**：Worker 成功不等于 Pipeline READY，Pipeline READY 不等于 Operational ACTIVE。UI 每次从 Core registry + append-only ledger 重算。
10. **网关故障暂停**：归为 `EXTERNAL_GATEWAY_UNAVAILABLE`，不切换 Codex、不消耗 repair、不伪造模型结果。
11. **Product/Lab 分账**：本批 `counts_toward_*` 全为 false；不能把 Product 案例写成模型能力成绩。
12. **不做仓库特例**：`src/repoproof` 不得出现资格仓库名、commit、task id、专属字段或路径。
13. **保护工作树**：不得删除未跟踪任务证据，不得 `git reset --hard`、`git clean` 或 broad `git add .`。
14. **不推送、不发布**：除非项目方再次明确授权。

## 六、每次修改必须保证的效果

每个 Core/Harness 修改只有同时满足下列清单才算完成：

- [ ] 原始 incident 已 append-only 保存，且不含 secrets/held-out/private path。
- [ ] 通用不变量写清，failure owner 与 stage 没有为了 repair 而错归 Agent。
- [ ] 匿名负控在修复前失败，SHA-256 已记录。
- [ ] 修改位于正确层：admission、drafting、fixture/reference、preflight、Agent adapter、verifier、replay、release/UI 之一。
- [ ] 同一匿名控制修复后通过，SHA-256 已记录。
- [ ] `HarnessChangeEvidenceV1` 完整，普通问题的两个 incident 来自不同 task version/独立任务。
- [ ] Core 特例扫描新增命中为零。
- [ ] 定向单测、Ruff、mypy 与 `git diff --check` 通过。
- [ ] 全量 pytest 与 Streamlit smoke 通过；派生 fact 文件由官方脚本重建。
- [ ] 所有已完成 workspace 案例在新 framework SHA 下完成零模型 replay。
- [ ] 历史 READY、当前 release 状态和 package health 仍分开展示。
- [ ] 失败时只有一个主要责任、稳定 reason code 和唯一下一步；不能显示 ACTIVE。
- [ ] 成功时必须同时有独立语义证据、clean replay、fresh audit、ACTIVE 和 package OK。

## 七、接手盘面与常用命令

先执行：

```bash
cd /Users/zhangronglei/Desktop/XIANGMU/RepoProof
git status --short
git branch --show-current
git rev-parse HEAD
git log --oneline -12
```

质量线：

```bash
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src/repoproof
git diff --check
.venv/bin/pytest -q
```

台账变动后只用生成器刷新事实：

```bash
.venv/bin/python scripts/gate_report.py --write
.venv/bin/python scripts/build_product_summary.py
.venv/bin/python scripts/check_public_claims.py
```

读取当前工具状态时调用 `repoproof.ui.services.product_mode.list_tools(Path('/Users/zhangronglei/tools'))`；不要解析 UI 文案或日志猜状态。在线起草前可以 `source .env`，但不得打印、记录或提交任何密钥值。

## 八、接手后不要做的事

- 不重构 3,000+ 行的 legacy `host_guided.py`；只修明确的判定/安全缺陷或其测试守卫。
- 不启动 M7 sidecar、浏览器/GPU/云账号/私有仓/常驻服务扩展。
- 不降低 workspace 结构、语义、反事实、replay 或 release gate 来追求案例通过率。
- 不把 first-pass formal failures 改写成 PASS；只追加 follow-up task/version 证据。
- 不因 Textual v3 成功删除 v2 的 `REVOKED`。
- 不把 online candidate 的一次 rejection 当成 Core bug；先看是否跨独立任务复现同一指纹。
- 不把 `exit 0`、Agent “done” 或目录能打开称为 verified。

## 九、当前交接结论

M6.2 已从“目录 profile 能装配”推进到三个中等复杂真实工作区完整 ACTIVE，其中含 SQLite/浏览器查询工作区与可交互终端应用。Textual v2 还成功暴露并修复了发布 rebuild 对未冻结 build backend 的依赖，v3 的 fresh audit 证明修复有效。

本交接落笔前的实测质量线：2144 tests collected，全量 pytest 退出 0；Ruff 全仓 0 错；mypy 187 个源码文件 0 错；`git diff --check` 与 `scripts/check_public_claims.py` 均通过。这里是本机当前工作树事实，不代表远端 CI 已运行。

项目尚不能收官为 `workspace_bundle_v1=SUPPORTED`：C6、B1、B2 是下一优先级，C1/C2 应作为通用 fixture 修复的回归案例补完。下一位 AI 的目标不是制造全绿数字，而是在不降低证据门的前提下，让这些仍在支持面内的任务通过新 task version 合理完成，并让每个剩余失败都有可审计的唯一终态。
