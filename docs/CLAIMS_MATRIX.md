# Claims Matrix — every public statement, its evidence, its limits

Status vocabulary: **VERIFIED** (independent, committed evidence) ·
**CASE_LEVEL_EVIDENCE** (true for the recorded case(s); no generality
claim) · **EXPERIMENTAL** (mechanism exists; effect unproven) ·
**NOT_SUPPORTED** (no evidence; do not claim) · **FORBIDDEN** (false
or misleading; never claim anywhere).

Fact source for all numbers: [benchmark_summary.json](benchmark_summary.json)
(regenerate with `scripts/build_benchmark_summary.py`; consistency
enforced by `scripts/check_public_claims.py`).

## Allowed claims

| Claim ID | 对外表述 | 证据 | 状态 | 允许场景 |
|---|---|---|---|---|
| C1 | RepoProof 将开源仓库能力采用任务转化为冻结合同、受控执行、独立验证和干净重放的流程 | 全部 12 条 run 记录:frozen contracts + sidecars、TaskPackage、trace 链、verifier hashes、replay 结果(`docs/evidence/`) | VERIFIED | README / 简历 / 面试 |
| C2 | 已完成首个真实 PASS_ADAPTED(frontmatter-v2 corrected-spec run) | `gate72-corrected-spec-run/report.json`:capability 18/18 含 held-out、regression 3/3、policy、clean_adoption replay PASS;prompt/provider hash 与预注册一致 | VERIFIED | README / 简历 / 面试 |
| C3 | 正向结果由 Capability、Regression、Policy 与 clean_adoption Replay 四个独立检查共同支撑,agent 自述不参与 verdict | completion gate 决策表 + `verification_result_hashes`;gate 忽略 claim_complete 由测试钉死 | VERIFIED | README / 简历 / 面试 |
| C4 | Agent 生成了 Front Matter Adapter(1 文件 67 行,调 pinned 上游、旗标拆分、P1 投影、异常包装),但输入类型边界由 Host Input Guard 负责,不算 agent 能力 | `gate72-corrected-spec-run/agent_adapter.py` + consumer `guard.py`;responsibility matrix 冻结于 TaskPackage | VERIFIED | README / 简历 / 面试(必须带责任分离表述) |
| C5 | 系统曾拒绝高度完成但不合格的产物:Chonkie 31/33、rank_bm25 9/12 均判 FAIL 并在干净环境复现失败 | `gate3c-real-run/`、`gate5-second-repo/`:failure_reproduction replay PASS + FAIL verdicts | VERIFIED | README / 简历 / 面试 |
| C6 | Gate 7.2 是 corrected-spec positive case——合同修到充分后 agent 完成剩余 ADAPTER 责任;不是单变量实验 | `gate72-corrected-spec-run/PREREGISTRATION.md` 明文预注册该定性 | VERIFIED | 任何场景(表述不可省略"非单变量") |
| C7 | 项目积累了 9 类真实失败分类,含 harness 自身两个 bug(prompt 污染、合同欠规范)的自查自证 | [FAILURE_TAXONOMY.md](FAILURE_TAXONOMY.md) 每类挂 run/trace 证据 | VERIFIED | README / 简历 / 面试 |
| C8 | Docker 用于隔离、销毁与重放(非 root、cap-drop ALL、network=none、digest 锁定) | run 记录中的 `container.security` 事件 + image digest 绑定 | VERIFIED | README / 面试(不得说成安全沙箱,见 F6) |
| C9 | Budget-State 观察与 Coverage Ledger 机制存在并被真实 run 检验过 | gate4a(null result)、gate4b(首次 Submit、outcome 不变) | EXPERIMENTAL | 面试(必须同时说明效果未证明) |

## Forbidden claims

| Claim ID | 禁止表述 | 原因 |
|---|---|---|
| F1 | 支持任意 GitHub 仓库 | 仅 3 个公开 Python/CPU 域,每个都需人工任务工程 |
| F2 | 能保证仓库适配成功 | 12 runs 里 1 个 PASS_ADAPTED,其余诚实 FAIL |
| F3 | Harness 普遍提升 Agent 成功率 | 无对照证据;4A 为 null result |
| F4 | Budget Awareness 已证明有效 | gate4a 预注册结果:无差异 |
| F5 | Coverage Ledger 已证明跨任务有效 | gate5 中被完全忽略(0/9);标注 experimental/default off |
| F6 | Docker 是恶意代码安全沙箱 | 措辞纪律:isolation/disposal/replay,非 security boundary(SECURITY.md) |
| F7 | Trace 不可伪造 | 正确表述是 tamper-EVIDENT(hash 链),拥有仓库写权限者可重写整链 |
| F8 | Gate 7.2 是单变量实验 / "改一个变量后 8/11→18/18" | 任务版本、schema、prompt 面、guard 同时改变;预注册明文禁止 |
| F9 | Host Guard 完成的异常输入处理属于 Agent 能力 | text=None 类校验是 host 代码;agent 从未实现它 |
| F10 | 低成本模型达到 Codex / Claude Code 通用编码能力 | 本项目不测通用能力;仅约束域内合同任务 |
| F11 | 已达到生产级平台 | 无多租户/鉴权/队列/横向扩展;research-grade MVP |
| F12 | 支持任意语言、GPU、私有仓库或大型应用全量融合 | 范围=公开 Python / Linux / CPU-first / 单能力采用 |
