# Claims Matrix — every public statement, its evidence, its limits

Status vocabulary: **VERIFIED** (independent, committed evidence) ·
**CASE_LEVEL_EVIDENCE** (true for the recorded case(s); no generality
claim) · **EXPERIMENTAL** (mechanism exists; effect unproven) ·
**NOT_SUPPORTED** (no evidence; do not claim) · **FORBIDDEN** (false
or misleading; never claim anywhere).

## 两个事实源,永不合并

| 事实源 | 覆盖 | 重建 |
|---|---|---|
| [benchmark_summary.json](benchmark_summary.json) | **Benchmark Lab**:MVP 时代冻结的 12 发快照(31/33、9/12、18/18、首个 PASS_ADAPTED) | `scripts/build_benchmark_summary.py` |
| [product_summary.json](product_summary.json) | **Product Mode**:313 行台账里的 84 发产品运行、两批真实仓、运营发布状态、完整性存量 | `scripts/build_product_summary.py` |

一致性由 `scripts/check_public_claims.py` 确定性强制(CI 三 job 之一)。

**分账铁律**:Product 发次 `task_seen=true`,一律不进模型能力/held-out
分母 —— 产品跑通多少工具,不能拿来说"模型有多强"。checker 直接钉死
`counts_toward_model_capability=false`。

## Allowed claims

### A. 协议与判定(跨两个模式)

| ID | 对外表述 | 证据 | 状态 |
|---|---|---|---|
| C1 | RepoProof 把"GitHub 单能力 → 本地工具"固定为冻结合同、受控执行、独立验证、干净重放、证据闭环的工作流 | 冻结合同 73 份、tool_tasks 37、oracle 39、controls 33;`runs/<run_id>/` 全证据包 | VERIFIED |
| C2 | 判定权不在 agent 手里:completion gate 只读四个独立 verifier 的结构化结果,agent 自述被构造性忽略并由测试钉死 | `verification/completion_gate.py` 决策表 + `verifiers.py`;`repoproof demo verify` 可现场复算 | VERIFIED |
| C3 | 出题本身要过准入:正控必须过、空实现/绕上游重写/硬编码三类作弊必须被抓住,否则任务不许冻结 | `controls/` 33 个任务的正负控矩阵 + `harness/controls_battery.py` + `ContractAdequacyGate` | VERIFIED |
| C4 | 上游采用有密码学回执:HMAC 签名 + 运行时实际加载模块的 artifact hash + 输入 digest + 采纳谓词四重绑定,缺采纳谓词一律判不通过 | `receipts/model.py`、`receipts/verify.py`;负控在 `docs/evidence/receipt_controls/` | VERIFIED |
| C5 | 失败也交付证据:FAIL/BLOCKED 同样落完整证据包与台账行 | 313 行 `runs.jsonl`,FAIL/BLOCKED 行齐备 | VERIFIED |

### B. Product Mode(数字出自 product_summary.json)

| ID | 对外表述 | 证据 | 状态 |
|---|---|---|---|
| C6 | 两批预注册真实公开仓库走完整产品链路;批次二 submitted 12 / accepted 11 / historical READY 10 / clean replay 10 / 运营可用 9 / false-success 1 | `product_summary.json.batch_2` ← `m4_metrics.json` + append-only 审计与发布台账 | VERIFIED(**必带 C8 限定句**) |
| C7 | 系统抓到过自己的假成功:`pyspellchecker` v1 冻结题面声明 JSON,而 examples/oracle 验的是纯文本;运营资格被撤回,冻结合同与真跑一字未改;此后工程化为 ToolSpec v2 输出合同 + T6–T9 装配期检查 | `m4_metrics.json.false_success`、RFC-011、发布台账 REVOKED 行 | VERIFIED |
| C8 | **主仓完整性存量限定**:完整性对账曾在 completion gate 之后才算、只落 report 不进判定;清点存量发现 19 发 PRODUCT PASS 的 `main_dir_integrity=MISMATCH`,10 发绑定已导出工具、8 个当前 ACTIVE —— 其中 8 个工具的交付发次在现行完整性闸下应判 BLOCKED | `product_summary.json.ledger.product_runs_integrity_mismatch_but_pass`(19 条)+ 每发的 append-only 勘误行 | VERIFIED(限定句,**引用 C6 时必须同时出现**) |
| C9 | C8 不触及工具功能证据:clean replay 与 fresh non-example 抽查是独立证据线,不依赖原发主仓完整性,且均已通过 | `m4_metrics.json.per_task[].replay` + `m4_audits.jsonl` 22 条 | VERIFIED |
| C9b | **干净复样已取得**:8 道受 C8 影响的冻结题在静默窗内按现行闸重跑,8/8 `PASS_ADAPTED` + `main_dir_integrity=ok`(472,949 in)。证明"这道冻结题 + 钉版上游今天能干净通过";**不**追改原发 verdict、**不**替换工具包/registry/发布决定。19 发中 15 发所属任务已覆盖,剩 4 发属 `jsonschema-report`(REVIEW_REQUIRED)与 `pyspellchecker`(REVOKED),均非 ACTIVE | 预注册 `benchmarks/v2/preregistrations/INTEGRITY-RESAMPLE-1-20260826.md` + `product_summary.json.ledger.clean_resample_by_task` | VERIFIED |
| C9c | 复样批采用 `gpt-5.6-terra`,原发为 `gpt-5.5` —— **已知非受控变量**,本批不产出任何模型能力或模型对比结论 | 预注册 §五 D(发前冻结) | VERIFIED(措辞约束) |
| C10 | 产品线共 84 发(44 真模型 + 40 fake 彩排),真模型 39 PASS_ADAPTED / 5 FAIL,覆盖 27 个不同任务 | `product_summary.json.ledger` | CASE_LEVEL_EVIDENCE |
| C11 | 彩排是真发前的预算闸:fake 彩排不过就不烧真实模型预算 | `runner/tool_pipeline.py` 九步流水线第 8 步 | VERIFIED |
| C12 | DIRECT_WRAP 快路径在确定性可解的任务上零模型调用完成并过同一条验证链 | `adoption/planning` + Gate 3 合成 minilib 全链 PASS_DIRECT + wrong-symbol 负控 | VERIFIED |
| C13 | 运营态与历史结论双口径并列:`historical_verdict` 不可改写,`operational_status` 是 append-only 发布决定;MCP 只对历史 READY + 当前 ACTIVE 开放 | RFC-011;`tool list` 双栏;M5 adapter 每次 list/call 复核账本 | VERIFIED |

### C. Benchmark Lab(数字出自 benchmark_summary.json)

| ID | 对外表述 | 证据 | 状态 |
|---|---|---|---|
| C14 | 系统曾拒绝高度完成但不合格的产物:Chonkie 31/33、rank_bm25 9/12 均判 FAIL 并在干净环境复现失败 | `gate3c-real-run/`、`gate5-second-repo/` | VERIFIED |
| C15 | 首个 PASS_ADAPTED 来自把合同修到机器可判充分(typed RequirementSpec + 13 项确定性准入门 + 宿主输入守卫),不是调 prompt | `gate72-corrected-spec-run/`:capability 18/18 含 held-out、replay clean_adoption PASS | VERIFIED(必须带 F8 的"非单变量") |
| C16 | 9 类真实失败分类学,含 harness 自身两个 bug 的自查自证 | [FAILURE_TAXONOMY.md](FAILURE_TAXONOMY.md) | VERIFIED |
| C17 | Budget-State 观察与 Coverage Ledger 机制存在并被真实 run 检验过 | gate4a(null result)、gate4b(首次 Submit、outcome 不变) | EXPERIMENTAL(必须同说效果未证明) |

### D. 工程与自查

| ID | 对外表述 | 证据 | 状态 |
|---|---|---|---|
| C18 | CI 三 job(ruff 全仓 / mypy 可信链八包 0 错 / pytest 全量,slow 不跳过);mypy 豁免是显式登记的棘轮,边界与 PROJECT_MAP 代码分区逐包一致 | `.github/workflows/ci.yml`、`pyproject.toml [tool.mypy]` | VERIFIED |
| C19 | Linux 容器 CI 预演咬出五条真缺陷,含"保护目录表 lower 化路径被当 fs 路径访问 → ext4 上快照静默漏保护" | 2026-08-25 EXPLORATION_LOG 状态条目 + `host_guard.py` 比对键/访问路径分离 | VERIFIED |
| C20 | 外部审计两条 P0 被真修:执行闸可伪造绕过(只查 confirmed+sha)、完整性不进判定;后者连带把自己的招牌成果 append-only 降级 | `capability_plan.assert_may_execute`、`host_guided.apply_integrity_to_verdict` + 勘误行 | VERIFIED |
| C21 | 保护目录按结构发现(本仓 + 兄弟 git 仓)而非硬编码目录名 —— 硬编码在别人机器上等于保护集合为空 | `host_guard.structural_protected()` + 回归钉 `test_no_personal_paths_hardcoded_in_defaults` | VERIFIED |

## Forbidden claims

| ID | 禁止表述 | 原因 |
|---|---|---|
| F1 | 支持任意 GitHub 仓库 | 公开 Python / CPU / 单能力 / 简中依赖;每个任务仍需人工合同与 oracle 工程 |
| F2 | 能保证适配成功 | 见 C6/C10 的真实 FAIL 计数 |
| F3 | Harness 普遍提升 Agent 成功率 | 无对照证据;4A 为 null result |
| F4 | Budget Awareness 已证明有效 | gate4a 预注册结果:无差异 |
| F5 | Coverage Ledger 已证明跨任务有效 | gate5 中被完全忽略(0/9);experimental / default off |
| F6 | Docker 是恶意代码安全沙箱 | 正确措辞:isolation / disposal / replay(SECURITY.md) |
| F7 | Trace 不可伪造 | 正确措辞:tamper-EVIDENT;有仓库写权限者可重写整链 |
| F8 | Gate 7.2 是单变量实验 | 任务版本、schema、prompt 面、guard 同时改变;预注册明文禁止 |
| F9 | Host Guard 完成的异常输入处理属于 Agent 能力 | 那是 host 代码 |
| F10 | 低成本模型达到 Codex / Claude Code 通用编码能力 | 本项目不测通用能力 |
| F11 | 已达到生产级平台 | 无多租户/鉴权/队列/横向扩展 |
| F12 | 支持任意语言、GPU、私有仓库或大型应用全量融合 | 超出 v1 承诺边界 |
| **F13** | 引用批次二运营/历史数字时省略完整性限定句(C8) | checker 机器钉死;省略即把一条已知有疑的证据以全强度流通 |
| **F14** | 拿 Product 发次的 PASS 数当模型能力成绩 | Product 任务 `task_seen=true`,RFC-010 [G4] 分账铁律 |
| **F15** | 说 analyzer "自动理解用户意图" | analyzer 只做表面特征检测(导出名单/签名/文件位置);候选与意图是否相符由用户确认把关(RFC-013 §4) |
| **F16** | 说 M6 用户测试证据"在仓库内可独立审计" | 两份原始记录表尚未归档;只可说"项目方报告测试已完成"(见 `docs/evidence/m6_user_tests/`) |
| **F17** | 说 M7 sidecar / OS 级隔离已完成 | EXPERIMENTAL,功能面冻结,OS 隔离未关闭 |
