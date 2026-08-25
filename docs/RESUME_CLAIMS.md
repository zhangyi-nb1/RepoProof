# Resume claims — evidence-bound wording only

数字只能出自两个机器可读事实源:[product_summary.json](product_summary.json)
(Product Mode)与 [benchmark_summary.json](benchmark_summary.json)
(Benchmark Lab)。**两者永不合并**。措辞约束见
[CLAIMS_MATRIX.md](CLAIMS_MATRIX.md);一致性由
`scripts/check_public_claims.py` 在 CI 里确定性强制。

三个贡献面永远分开写:**Agent** 写 adapter;**Harness** 提供合同充分性、
隔离、策略、预算、验证、重放、闸门;**Host Guard** 负责输入类型校验与
稳定错误边界。

---

## 版本 1 · 稳健技术版

**RepoProof — 把 GitHub 单个能力转成经独立验证的本地 AI Tool 的 Agent Harness(个人项目,Python)**

- 设计并实现完整产品链路:静态分析 → CapabilityPlanV1(证据化 surface 检测 + 确定性路由 + 用户确认闸)→ 冻结 Tool Contract → DIRECT_WRAP(零模型受信模板)或 AGENT_ADAPT(有界修复循环)→ 四路独立验证 → 干净重放 → 导出 + append-only 运营发布状态 + MCP 暴露。两批预注册真实公开仓库跑完全链路,批次二 submitted 12 / accepted 11 / historical READY 10 / clean replay 10 / 运营可用 9 / false-success 1。
  - 限定(必带):其中 8 个工具的**交付发次在现行完整性闸下应判 BLOCKED** —— 主仓完整性对账当时在 completion gate 之后才算、不参与判定;历史 verdict 一字不改,每发有 append-only 勘误行。工具功能证据不受影响(clean replay 与 fresh-input 抽查是独立证据线,均已通过)。**这 8 道冻结题已于 2026-08-26 按现行闸在静默窗内复样,8/8 PASS_ADAPTED + `integrity=ok`**(预注册 INTEGRITY-RESAMPLE-1,472,949 in);复样不追改原发 verdict、不替换工具包,只证明"这道题今天能干净过"。
  - 证据:`docs/product_summary.json`、`docs/m4_metrics.json`、`benchmarks/v2/`
- **判定独立性是这个项目的核心**:completion gate 只读四个互不读 agent 自述的 verifier 结构化结果;held-out oracle 对 agent 零泄漏并由测试钉死;上游采用由密码学回执证明(HMAC 签名 + 运行时实际加载模块的 artifact hash + 输入 digest + 采纳谓词四重绑定,缺采纳谓词一律判不通过)。出题本身也要过准入:正控必须过、三类作弊控必须被抓住,否则任务不许冻结。
  - 证据:`src/repoproof/verification/`、`receipts/`、`controls/`(33 个任务的正负控矩阵)
- **系统抓到过自己的三次假成功,每次都转成一道确定性防线**:① `pyspellchecker` 冻结题面声明 JSON 而 oracle 验纯文本 → ToolSpec v2 输出合同 + T6–T9 装配期检查;② 执行闸只查 confirmed+sha,伪造 `UNSUPPORTED+confirmed=true` 重封即可绕过 → 执行点重查全部语义前提 + plan 与上游身份绑定;③ 主仓完整性不进判定 → `apply_integrity_to_verdict` 前置到台账装配之前,并把自己当时的招牌成果 append-only 降级。
  - 证据:RFC-011、`capability_plan.assert_may_execute`、`host_guided.apply_integrity_to_verdict` + 勘误行
- 证据纪律作为第一原则:真实发次预注册且不重跑;FAIL/BLOCKED 同样落完整证据;缺失值写 `UNKNOWN` 不写 null;勘误一律追加覆盖行、不改旧行;对外数字由机器可读事实源 + 确定性 claims 检查器约束(CI 三 job:ruff 全仓 / mypy 可信链八包 0 错 / pytest 1499 项全量,slow 不跳过)。
  - 证据:`.github/workflows/ci.yml`、`scripts/check_public_claims.py`

## 版本 2 · 冲击力版

**RepoProof — 让 Coding Agent 的"我做完了"接受审判的证据 Harness**

- 真实 agent 把开源库适配到 31/33 测试通过——系统仍判 FAIL,并在全新容器里复现同一失败。高完成度不等于可采用,这正是本项目要解决的问题。
  - 证据:`docs/evidence/gate3c-real-run/`
- **最有说服力的不是通过率,是它抓自己**:一个宣称"抓假成功"的系统,自己的判定层漏掉了主仓完整性——一发报 PASS_ADAPTED,而同一份 report.json 里 `ok=false`。修法不是补文档,是把完整性做成纯函数前置进判定;后果不是掩盖,是用 append-only 勘误把当时最亮眼的成果(首条干净非平凡修复轨迹)自我降级,并回头清点出 19 发同根因的存量,逐发挂勘误。
  - 证据:`apply_integrity_to_verdict` + `benchmarks/v2/run_classifications.jsonl` 勘误行
- 判定权完全不在 agent 手里:gate 只读独立 verifier 的结构化结果,agent 的 claim 被构造性忽略并由测试钉死;负结果(预算感知 null、coverage ledger 被无视 0/9)全部留在 benchmark 里不删。
  - 证据:`docs/BENCHMARK.md`、`docs/PROJECT_EVOLUTION.md`
- 注意:此版本仍不得暗示"harness 提升成功率"或"单变量改进"(F3/F8)。

## 版本 3 · 面试友好版

**RepoProof — 给 AI Agent 的工具货架加一道独立验收和可撤回机制**

- 用户给一个 GitHub 仓库 + 一句能力描述,系统输出一个本地 CLI 工具,并同时给出:钉版上游、冻结合同、验证结果、重放结果、来源回执、证据报告。工具可以被人调用,也可以作为 MCP 被 Claude / Codex 调用。
- **可撤回是重点**:`historical_verdict`(当时通过验收,永不改写)与 `operational_status`(ACTIVE / REVIEW_REQUIRED / REVOKED,append-only)双口径并列。只有历史 READY + 当前 ACTIVE 才能生成 MCP;生成的 adapter 每次 list/call 都复查账本,撤回即时生效。这解决的是 agent 工具生态里"谁来担保这个工具还能信"的问题。
- 拒绝也是产品结果:四态准入 + 用户确认闸,在烧真实模型预算之前拒掉不适合自动 Tool 化的任务;fake 彩排不过就不发真发。
- 所有对外数字有机器可读事实源和确定性一致性检查;演示可以完全无模型(证据复算 + 干净重放)。
  - 证据:`repoproof demo verify/replay`、`docs/DEMO.md`

## 全局禁语(任何版本、任何场合)

- "支持任意 GitHub 仓库 / 保证适配成功 / 生产级平台"(F1/F2/F11)
- "harness 普遍提升 agent 成功率"(F3;无对照证据)
- "单变量实验证明规格修复带来 8/11→18/18"(F8;多变量同时改变)
- "输入校验也是 agent 完成的"(F9;那是 Host Guard)
- "budget awareness / coverage ledger 已证明有效"(F4/F5;null / 被忽略)
- 不得称 security sandbox,不得称 tamper-proof(F6/F7;正确词=isolation / tamper-evident)
- **引用批次二数字时省略完整性限定句**(F13;checker 机器钉死)
- **拿 Product 发次的 PASS 数当模型能力成绩**(F14;task_seen=true,分账铁律)
- "analyzer 自动理解意图"(F15;它只做表面特征检测,意图由用户确认)
- "M6 用户测试证据在仓库内可独立审计"(F16;记录表尚未归档)
- "M7 sidecar / OS 级隔离已完成"(F17;EXPERIMENTAL 且功能面冻结)
