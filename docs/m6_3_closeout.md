# M6.3 复杂工作区资格批 · 收口(2026-09-03,EXPLORATORY_UNPREREGISTERED)

协议:`m6.3-complex-workspace-qualification-v1`,状态 `DRAFT_NOT_FROZEN`(本批在草稿协议下探索性执行,**不是预注册批次**;收口时协议文件 SHA-256 `5dfb74eabc94908fdff213de9671245247e3d58ab2a341cffc1ea3e6dc81a67b`,仅作记录,不构成事前冻结)。
执行政策继承 M6.2:Claude 通道(opus-4.8)起草 + mini-swe 实现,冻结 `max_model_calls: 20`;Product 记录 `counts_toward_*` 全 false。

## 每案唯一终态

| 案例 | phase1 轮 | phase2 轮 | 冻结版本 | 注册表 | 终态 | 说明 |
|---|---|---|---|---|---|---|
| n0-live-balance-monitor | 1 | 0 | — | — | **EXPECTED_REJECTION_CONFIRMED** | 预期拒绝负控:准入拒绝,零模型预算(支持面边界钉死) |
| c1-xlsx-reconciliation-workbook | 11 | 5 | tool-xlsxwriter-tool-v1 | — | **FAILED_PHASE1_AFTER_REPAIRS** | v1 到彩排后 phase 2 倒在 zip 容器元数据(尺子已改);重冻结 v2 十轮未成:xlsx 容器内成员漂移、schema 拒绝、归属筛查(均已修 Harness),最终一轮倒在路径三角振荡(合同 root / reference+verifier output/,单例待第二起) |
| c2-pptx-quarterly-briefing | 4 | 8 | tool-python-pptx-tool-v2 | REVIEW_REQUIRED | **READY_NOT_ACTIVE_FROZEN_CONTROLS_DISAGREE** | tool-python-pptx-tool-v2 真发 PASS → VERIFIED_TOOL_READY;新输入抽查冻结控制件分歧(类已修:冻结前双新输入探针;v2 冻结件不受益,需重冻结 v3) |
| c3-offline-usage-dashboard | 9 | 3 | tool-pygal-tool-v1, tool-pygal-tool-v2, tool-pygal-tool-v3, tool-pygal-tool-v4 | REVIEW_REQUIRED | **READY_NOT_ACTIVE_FROZEN_CONTROLS_DISAGREE** | v2/v3/v4 三次到彩排、v2/v4 真发 PASS(v4 20 步)→ READY 导出;新输入抽查分歧 SUMMARY_BALANCE_MISMATCH/MODEL_SVG_BAR_VALUE(诊断随行生效);v3 带冻结日期炸弹(已修扫描) |
| c4-photo-contact-sheet | 4 | 9 | tool-pillow-tool-v2, tool-pillow-tool-v3 | ACTIVE | **ACTIVE** | tool-pillow-tool-v3 真发 PASS → 新输入抽查 FRESH_INPUT_PASS → ACTIVE(驱动曾误报 FRESH_AUDIT_FAILED,已修) |
| c5-offline-docs-site | 19 | 0 | — | — | **FAILED_PHASE1_AFTER_REPAIRS** | 19 轮 phase 1 未冻结:每轮换一种 Harness 病灶(十余项已修);最终两轮在停滞预算下各 7 轮 6 修,倒在 mkdocs 主题 CDN 外链与 site/index.html 判别力缺口(模型侧/任务难度) |
| c6-calendar-schedule-pack | 12 | 2 | tool-icalendar-tool-v1 | ACTIVE | **ACTIVE** | tool-icalendar-tool-v1 一轮 20 步 PASS → FRESH_INPUT_PASS → ACTIVE(M6.3 首个全程零人工到 ACTIVE) |
| c7-analysis-notebook-pack | 13 | 4 | tool-nbformat-tool-v1, tool-nbformat-tool-v2, tool-nbformat-tool-v3, tool-nbformat-tool-v4 | ACTIVE | **ACTIVE** | tool-nbformat-tool-v4 真发 PASS → 新输入抽查通过 → ACTIVE(题面摘要 v2 + scratch 机制后一轮即过) |
| c8-translation-catalog-pack | 4 | 0 | — | — | **FAILED_PHASE1_ENVIRONMENT** | 四轮均倒在钉版源码 checkout 遮蔽已构建分发(babel CLDR 数据缺失,HARNESS 环境类单例待第二起);参考实现修复对环境错误无效 |

## 晋级门评估

定义:八个复杂案例中 ≥6 个经修复后 ACTIVE，且二进制办公类（c1/c2）、图像类（c4）、可重生成站点类（c3）各至少一个

结果:**未达成** —— 3/8 ACTIVE(c4/c6/c7);c1/c2 二进制办公类无 ACTIVE,c3 站点类 READY 未 ACTIVE。profile 状态不变(SUPPORTED,本批不改)。

## 本批 Harness 机制变更(全部:事故 → 匿名负控前红后绿 → HarnessChangeEvidenceV1 → Core 案例标识扫描)

- `harness-change-agent-scratch-location-v1`(2 起):Every agent session exposes REPOPROOF_SCRATCH_DIR, a directory inside the session root (under the fake HOME) and outside the package: it is created before the f…
- `harness-change-agent-task-statement-truthful-environment-v1`(3 起):The agent's task statement must describe the environment the run actually provides: it may not claim an execution context the harness does not create, it must n…
- `harness-change-autopilot-fresh-audit-real-payload-v1`(2 起):The autopilot judges the fresh-input audit by the audit CLI's real payload: ok=true with the singular reason_code in {FRESH_INPUT_PASS, FRESH_INPUT_SEMANTIC_PAS…
- `harness-change-conformance-node-runnability-v2`(3 起):v1 invariant unchanged (only nodes compatible with the declared runner profile may be selected). v2: before a selection is frozen it is executed once, candidate…
- `harness-change-contract-repair-cannot-weaken-validator-v1`(1 起,安全/伪认证例外):A structural contract repair may change patterns, cardinalities, limits and smoke arguments, but never the ruler: per role the validation_profile and executable…
- `harness-change-delivery-shape-self-contradiction-v1`(2 起):A drafted document whose typed delivery shape contradicts its own members (workspace_contract / fixture_builder / fixture_blueprints / an output with format_id=…
- `harness-change-delivery-shape-self-contradiction-v2`(2 起):Completion of v1: the projection repair context must survive the contradictory document it is asked to repair. On the first real DELIVERY_SHAPE_SELF_CONTRADICTI…
- `harness-change-divergence-locus-named-v1`(2 起):A divergence row does not stop at the file path: for a zip container it names the first member whose bytes differ (or the member present on one side only), for …
- `harness-change-external-interruption-is-not-a-task-failure-v1`(2 起):A run the PROVIDER ended mid-flight has no task conclusion and must not be graded as one: an EXTERNAL agent exit (service unavailable / rate limited / API timeo…
- `harness-change-golden-identity-zip-canonical-v1`(2 起):Acceptance equality of a delivered workspace is the golden identity: per file, bytes that parse as a zip archive are identified by their sorted (member name, me…
- `harness-change-import-hook-function-metadata-v2`(1 起,安全/伪认证例外):Runtime observation must preserve the observable behaviour and metadata of every wrapped upstream callable (v1). v2 extends this to the attributes the wrapped o…
- `harness-change-projection-diagnostics-everywhere-v1`(2 起):Every Core projection rejection of a drafted document carries field-level public diagnostics (loc/type/msg) — fixture blueprint count/shape/input_kind/duplicate…
- `harness-change-projection-diagnostics-everywhere-v2`(3 起):v1 invariant unchanged (every projection rejection carries loc/msg field diagnostics and enters the bounded evidence-based projection repair). v2 extends it to …
- `harness-change-reference-ownership-policy-single-ruler-v1`(2 起):The static runtime-ownership screen is one ruler applied at the two places a producer source is accepted (draft projection and reference repair), and it names w…
- `harness-change-reference-wall-clock-date-scan-v1`(1 起,安全/伪认证例外):A reference workspace is not reproducible if any generated UTF-8 text file carries today's date (local or UTC, in the spellings generators stamp) that the input…
- `harness-change-repair-rejection-reasons-travel-v1`(2 起):When Core refuses a model repair, the refusal's public code and field rows (loc/msg, never model output) travel three ways: into the retry prompt of the same re…
- `harness-change-runtime-closure-disagreement-routing-v1`(2 起):A contract-vs-producer disagreement surfaced by the Core runtime-closure step (WORKSPACE_RUNTIME_APPLICATION_MISSING / ENTRYPOINT_MISSING / OWNED_PATH_COLLISION…
- `harness-change-selfcheck-bound-counts-stalls-v1`(2 起):The self-check repair bound is a stall budget, not a repair count: a repair spends it only when the failure it faces (first reason code + first diagnostic line)…
- `harness-change-selfcheck-continues-after-unapplied-repair-v1`(2 起):A rolled-back or no-progress repair leaves the draft unchanged, so the self-check hands the same failure (same reason codes and diagnostics, same-code counter a…
- `harness-change-selfcheck-fresh-agreement-probe-v1`(2 起):Before a draft can pass its self-check, the producer and the independent judge must agree on one input neither was drafted against: each round first proposes on…
- `harness-change-selfcheck-fresh-agreement-probe-v2`(3 起):v1 invariant unchanged. v2: the pre-freeze agreement probe proposes and materialises TWO never-seen scenarios per self-check round; a single agreed scenario let…
- `harness-change-selfcheck-runs-smoke-v1`(2 起):For a runnable contract, candidate generation runs the contract's smoke command on the first sealed reference workspace with the same run_workspace_smoke ruler …
- `harness-change-semantic-mechanism-code-explanations-v1`(2 起):Every mechanism reason code the semantic screen itself produces (INPUT/ARTIFACT/UPSTREAM_RESULT binding control failures, UPSTREAM_CALL_NOT_OBSERVED, COMMITMENT…
- `harness-change-smoke-command-semantics-taught-v1`(2 起):The three prompts that can author or repair a smoke command state that the Harness runs it inside the delivered workspace alone (no candidate input, no external…
- `harness-change-structural-contract-failure-alternates-owner-v1`(2 起):WORKSPACE_REFERENCE_CONTRACT_FAILED carrying structural diagnostics is symmetric evidence between the contract and the producer that writes the paths: the contr…
- `harness-change-structural-validation-path-details-v1`(3 起):Every structural reason code returned by validate_workspace carries one public detail row naming the path it concerns and the rules or resource involved (RULE_O…
- `harness-change-verifier-verdict-consistency-named-v1`(2 起):A verifier verdict of ok=true that still carries reason codes is refused by the semantic screen as before, but the refusal is now named VERIFIER_INFORMATIONAL_R…
- `harness-change-workspace-statement-teaches-public-fixtures-v1`(3 起):The workspace-tool-v1 statement says up front what the golden gate compares (output_dir vs expected tree byte-for-byte, application file and README included) an…
- `harness-change-workspace-statement-teaches-public-fixtures-v2`(4 起):v1 invariant unchanged. v2: when the sealed launcher run.sh in a public expected tree executes a file that is identical across every public example, the digest …

## 待第二起的单例(未改)

> 判定依据:incident 记录 `RECORD_PENDING_SECOND_INCIDENT` 且其指纹未出现在任何 HarnessChangeEvidenceV1 中。其中若干条(如 zip 元数据 f0206673、自检不跑 smoke b13f6176、拒绝理由不透明 8e62ae51)已由**同一现象的重分类记录**在另一指纹下关闭,原记录按 append-only 保留;真正仍开放的是下文各类中没有对应 evidence 的那些。

- `incident-agent-self-test-output-trips-residue-gate-pptx-v1` — CORRECT_AGENT_SELF_TEST_OUTPUT_TRIPS_RESIDUE_GATE(`040f8deb534efe03`)
- `incident-agent-self-test-output-trips-residue-gate-pptx-v2` — CORRECT_AGENT_SELF_TEST_OUTPUT_TRIPS_RESIDUE_GATE(`040f8deb534efe03`)
- `incident-agent-session-path-differs-from-acceptance-nbformat-v4` — AGENT_SESSION_PATH_DIFFERS_FROM_ACCEPTANCE(`380128a7a28a40a7`)
- `incident-artifact-path-triangle-oscillation-xlsx-v1` — ARTIFACT_PATH_TRIANGLE_NOT_PINNED_AT_PROJECTION(`994a504420c8cc4b`)
- `incident-commitment-coverage-ids-not-projected-icalendar-v2` — COMMITMENT_COVERAGE_IDS_NOT_PROJECTED(`976f358f12e1a23a`)
- `incident-container-member-divergence-not-named-xlsx-v1` — CONTAINER_MEMBER_DIVERGENCE_NOT_NAMED(`67293694f103615e`)
- `incident-fixture-rejected-never-alternates-mkdocs-v1` — SYMMETRIC_FAILURE_NEVER_ALTERNATES_OWNER(`650b3fcc83cb47ba`)
- `incident-fresh-audit-diagnosis-not-carried-to-next-version-pygal-v4` — PRIOR_VERSION_FINDINGS_NOT_FED_TO_NEXT_DRAFT(`5569dd7683833a90`)
- `incident-fresh-reference-transient-55bad9e` — WORKSPACE_REFERENCE_EXECUTION_FAILED(`c75f6db3b2cb7a3d`)
- `incident-golden-identity-zip-metadata-v1` — ARTIFACT_IDENTITY_ZIP_METADATA_SENSITIVE(`f0206673517ed357`)
- `incident-literal-rule-shadowed-by-glob-mkdocs-v1` — LITERAL_RULE_SHADOWED_BY_GLOB_NOT_CAUGHT_AT_PROJECTION(`ff8cd4f3bcb70195`)
- `incident-mixed-structural-and-shape-codes-single-route-mkdocs-v1` — MIXED_STRUCTURAL_AND_SHAPE_CODES_ROUTED_TO_ONE_TARGET(`681dec2091fe1349`)
- `incident-pinned-checkout-shadows-built-distribution-babel-v1` — PINNED_SOURCE_CHECKOUT_SHADOWS_BUILT_DISTRIBUTION(`88e5af16f887742a`)
- `incident-provider-rate-limit-unmapped-nbformat-v1` — PROVIDER_EXCEPTION_UNMAPPED_RATE_LIMIT(`e084db3448187dc3`)
- `incident-reference-repair-relabels-error-as-user-input-mkdocs-v1` — REFERENCE_REPAIR_RELABELLED_INTERNAL_ERROR(`b5c2a756f5040a7c`)
- `incident-repair-rejection-feedback-opaque-pygal-v1` — REPAIR_REJECTION_FEEDBACK_OPAQUE(`8e62ae51c8a136f9`)
- `incident-selfcheck-bound-exhausted-monotone-progress-mkdocs-v1` — SELF_CHECK_BOUND_EXHAUSTED_WITH_MONOTONE_PROGRESS(`784e487ff6775a8d`)
- `incident-structured-schema-dangling-defs-mkdocs-v1` — EMBEDDED_SCHEMA_DEFS_NOT_HOISTED(`a0d07da828d8e290`)
- `incident-verifier-repair-observation-container-thin-pptx-v1` — VERIFIER_REPAIR_OBSERVATION_CONTAINER_TEXT_MISSING(`f34f0454ba73a719`)
- `incident-workspace-application-is-a-placeholder-xlsx-v1` — WORKSPACE_APPLICATION_IS_A_PLACEHOLDER(`e42d42452c2586ee`)

## 冻结清单状态

- 逐案解析 resolved_commit / 匿名克隆:已完成(准入阶段)。
- 逐案冻结 wheelhouse:已冻结的任务版本均有 manifest;未冻结案例(c5/c8)无。
- 七个 validation profile:全部实现并与导出 runtime 单尺。`static_site_v1`(目录级:index.html 存在、内链闭合)于收口后补齐(合同可选 `directory_profiles` 字段;控制件 `tests/test_static_site_directory_profile.py`);已冻结合同不受影响,c5 的未来版本方可受益。
- 协议 SHA 写入 HANDOFF:见 HANDOFF_STATE(记录性质,非预注册冻结)。

## 收口后的更正(2026-09-04)

- **c3 `tool-pygal-tool-v4` 的 READY 结论作废**:零模型复跑证明该交付件对每个输入都
  `WORKSPACE_EXTRA_FILE: __pycache__/<app>.cpython-312.pyc` —— 生产者 import 了自己写进交付
  目录的应用文件。它此前能过闸是因为**验收环境设了用户没有的 `PYTHONDONTWRITEBYTECODE`**
  (假成功;已修 `producer-runs-like-a-user-v1`,需新任务版本重走)。
- 其余 11 个冻结工作区工具在同一复跑下全部通过
  (`runs/evidence/workspace-replays/workspace-replay-20260903T165021Z.json`)。
- 冻结清单第七项 `static_site_v1` 已在收口后补齐(见上)。

## 诚实边界

- 所有 Product 发次不计模型能力/Held-out;三档模型对照(sonnet-5 / opus-4.8 / opus-5)见 EXPLORATION_LOG,不可声称 opus-4.8 等价 gpt-5.6-terra。
- 本批大量 Harness 修复发生在批次进行中(非冻结协议),因此任何“通过率”都只是探索性数字;确认性结论需要冻结 v2 协议后重跑。

## 建议的下一步(需人决定)

1. c2/c3 在冻结前双新输入探针下重冻结(v3/v5)并复打 phase 2;
2. 实现 `static_site_v1` 目录级 profile 后再评估 c5;
3. c8 需一条通用机制(参考子进程用已构建分发而非源码 checkout)——单例待第二起;
4. 冻结 M6.3 v2 协议(预注册)后做确认性批次。
