# RFC-008: Guided Adoption Delivery(Gate A–F)

- 状态:Gate A 提交(审计 + 设计);B–F 按序实施,各自独立 commit
- 基线:main `ac669e9`(工作树干净);LocalFlow `14603d5` 只读(1 个
  未跟踪文件 `GPT_REPO_BRIEF.md`,不动)
- 目标:把 RepoProof 从「任务准备好之后才能运行的可信 Agent Harness」
  升级为「普通 Python 开发者通过中文 UI 提交本地项目/空目录 + 公开
  GitHub 仓库 + 自然语言需求,经分析→计划确认→有界多轮适配→独立
  验证,获得可导出或可安全写回的 Integration Bundle」。
- 产品承诺(不变):任意公开仓库可提交分析;只有过准入的任务进入
  自动适配;冻结目标与预算内尽力;成功=可验证可重放,失败=准确
  原因+当前产物+下一步建议;不强行把不兼容仓库适配成功。

## 0. 当前实现审计矩阵(2026-08-08,HEAD ac669e9)

| # | 检查点 | 状态 | 证据/差距 |
|---|---|---|---|
| 1 | HostProjectReport 服务 UI | **已有** | `ui/pages/analysis.py` 进程内调用;Finding 三级溯源齐 |
| 2 | RepositoryReport 稳定 JSON | **需接线** | `to_dict()` 已有;CLI `analyze-repo` 输出人类文本,无 `--json` |
| 3 | AdmissionResult 接入 UI | **已有** | `plan_view.py`/`new_task.py` step3 四态卡真实调用 `decide()` |
| 4 | IntentDraft 可由 UI 编辑 | **需接线** | goal 可输入、plan 问题可回答;Confirmed/Assumption/Question 本体不可编辑 |
| 5 | AdoptionPlan 多接入策略 | **需重构** | 仅「直接调用/wrapper」两案;需 8 种策略 + §7.2 全字段;禁默认 adapter.py |
| 6 | FrozenAdoptionIntent 绑定确认 | **需接线** | 已绑 plan/admission sha+answers+ack;缺 intent_sha、显式 strategy、success criteria 独立绑定 |
| 7 | Repair Loop 接真实 mini-swe-agent | **缺失** | `repair_loop.py` 仅注入式 run_round(fake 驱动测试) |
| 8 | Staging / Worktree / ApplyManifest | **缺失** | 无对应模块 |
| 9 | Export / Apply / Rollback | **缺失** | 无对应模块;成功产物停在 runs/ |
| 10 | UI 只展示不执行完整链 | **部分** | 装配/冻结/运行(9B)已可;analyze-repo 仍要终端;plan_view 演示模式「代为接受风险」违反风险确认原则,需重构 |
| 11 | CLI 稳定 --json | **缺失** | analyze-host/analyze-repo 无 --json;admission 无 CLI |
| 12 | UI 与 Core 重复逻辑 | **基本无** | UI 进程内复用 Core;`new_task.py` 的 URL→repo 名解析与 CLI 轻微重复,Gate B 收敛 |

结论:分析/准入/意图/计划/人工门/修复循环的**机制层已在**,缺的是
(a) 稳定 JSON 接口与 UI 全闭环接线;(b) 8 策略计划;(c) 空目录模式;
(d) 期望草稿;(e) Staging→Export→Apply→Rollback 交付层;
(f) 修复循环接真实 Agent。以下各节为 B–F 的设计基线。

## 1. 完整用户流程

```text
1 描述想法 → 2 选择已有项目或空目录 → 3 输入目标仓库(URL)
→ 4 系统分析(host+source,静态) → 5 准入四态
→ 6 选择接入方式(8 选 1;空目录三计划) → 7 确认计划与成功标准
  (Human Gate → FrozenAdoptionIntent)
→ 8 期望草稿(可选:上游校准输出作证据,用户编辑确认)
→ 9 装配+冻结(既有 RFC-007 管线) → 10 有界多轮适配(≤3 轮)
→ 11 最终隐藏验证 + clean replay + Completion Gate
→ 12 结果页(成功/诚实失败均有产物) → 13 Diff 预览
→ 14 EXPORT_ONLY / APPLY_TO_STAGING / APPLY_CONFIRMED → 15 必要时回滚
```

失败在任何一步都返回:准确原因(FailurePacket/AdmissionReport)、
当前产物、下一步建议——FAIL/BLOCKED 也交付 Bundle 与报告。

## 2. 支持范围(准入条件,产品口径)

宿主:Python 3.10–3.12;Linux 容器可运行;有 pyproject/requirements/
setup.py 或明确安装方式;有 pytest 或用户样例;可复制到 Staging/
Worktree;不要求改生产环境。
目标仓库:公开 GitHub;可解析固定 Commit;License 可识别;Python 包/
CLI/可本地小服务;CPU-first;不要求未提供的私有数据/GPU/特权/秘密;
安装与入口可从代码/配置/文档确定;修改量在 Patch Budget 内。
口径:「任何公开仓库均可提交分析;只有通过准入的 Python 能力采用
任务才会进入自动适配。」

## 3. 状态机(产品运行主线)

```text
DRAFT_INTENT → ANALYZED → {READY|NEED_INFORMATION|RISK_REVIEW|UNSUPPORTED}
READY/RISK_REVIEW(全部风险被接受) → PLAN_PROPOSED → INTENT_FROZEN
→ (期望草稿确认) → TASK_FROZEN → REPAIR_ROUND_{1..3}
   ├─ all_public_green_pending_verification → FINAL_VERIFICATION
   ├─ STAGNATION_DETECTED / BUDGET_EXHAUSTED / MAX_ROUNDS → FINAL_VERIFICATION(带最佳状态)
   └─ SCOPE_CHANGE_PENDING_USER → (同意=新 Plan Version 重冻结 | 拒绝=停止)
FINAL_VERIFICATION → {PASS_DIRECT|PASS_ADAPTED|PARTIAL|BLOCKED|FAIL}
PASS_* → EXPORT_READY → INTEGRATION_STAGED → APPLIED | ROLLED_BACK
非 PASS → EXPORT_READY(bundle 含失败报告与当前产物)
任何时刻宿主指纹变化 → PROJECT_DRIFT_DETECTED(停止,重新分析)
```

## 4. 数据模型(新增/扩展)

- `HostProjectReport` +:`host_mode`(GIT_PROJECT/PLAIN_PROJECT/
  BLANK_PROJECT/INVALID)、`git_commit`、`tree_fingerprint`、
  `workspace_dirty`(Finding 语义不变)。
- `IntegrationStrategy`:`kind ∈ {PYTHON_ADAPTER, WRAPPER_FACADE,
  CLI_SUBPROCESS, HTTP_SIDECAR, PLUGIN, CLONE_AS_BASE, BOUNDED_PATCH,
  UNSUPPORTED}` + 推荐原因/预计修改文件/新增依赖/是否联网/是否需要
  Secret/是否修改宿主/风险/替代方案/预计验证方法。
- `FrozenAdoptionIntent` +:`intent_sha256`、`strategy`、
  `success_criteria_sha256`(既有字段不动,向后兼容)。
- `ExpectationDraft`:`cases[{input, upstream_output(证据),
  candidate_expected, field_origin ∈ {upstream_native, host_schema,
  suggested_new, uncertain}, case_kind ∈ {normal, boundary, error},
  user_confirmed}]`——上游输出只作能力证据,未确认不可 Freeze。
- `RepairRoundRecord`(§11.2 全字段,落盘 `runs/<id>/repair/round-N/`)。
- `ApplyManifest`(§9.4 全字段)+ `IntegrationBundleManifest`。
- FailurePacket 类型 +:`PROJECT_DRIFT`、`POLICY_VIOLATION`。

## 5. 信任区(继承并扩展)

既有:upstream(固定只读)/adaptation(可写)/oracle(只读+hash,
held-out 运行期对 Agent 不可见)。新增两区:
- **staging/**(RepoProof 工作区内):宿主项目临时副本或 Git
  Worktree;Agent 产物只应用到这里,原项目未确认前只读。
- **user_project(外部)**:三级写入协议(§6)之外零写入;路径必须
  resolve + symlink 检查 + path traversal 检查 + allowlist。
API Key 只在宿主进程;不进容器/Trace/Artifact/仓库。

## 6. 写入协议(三级,不可跳级)

1. **EXPORT_ONLY(默认)**:生成 `integration_bundle/`(adapter/
   patches/dependencies/tests/runtime/integration_guide.md/
   apply_manifest.json/rollback_plan.md/report.md),状态
   EXPORT_READY,不碰用户项目。
2. **APPLY_TO_STAGING**:Git 项目→固定 commit+tree hash,建临时
   worktree;非 Git→完整副本+原始文件 hash。只在副本应用、装依赖、
   跑 Public Tests + Host Regression、生成 Diff 与 ApplyManifest;
   状态 INTEGRATION_STAGED。
3. **APPLY_CONFIRMED**:仅当 Verdict∈{PASS_DIRECT,PASS_ADAPTED} ∧
   无 Drift ∧ 用户已看文件清单与 Diff ∧ 二次确认 ∧ ApplyManifest
   已生成 ∧ Rollback Plan 已验证 ∧ 路径检查通过。原子写回
   (staging 完成后整体移动/逐文件原子替换);Drift → 停止。
   禁止递归删除用户目录;回滚只恢复 Manifest 记录的文件,幂等。
宿主回归默认在 Staging + 独立 venv/容器执行;「在本机当前环境再跑
一次」须用户显式选择,结果单独标 HOST_LOCAL_REGRESSION,不替代
clean replay。

## 7. 修复循环(接真实 Agent)

产品模式 GUIDED_ADOPTION(与 Benchmark 分离)。全系统仍只有
mini-swe-agent DefaultAgent 一个自主循环;RepairLoop 是编排不是
第二个 Agent。≤3 轮;每轮:Agent 适配→Public Capability Tests→
Host Regression→FailurePacket(只引用 Public Test/Host Regression/
安装编译运行错误/公开 Requirement;严禁 held-out 名、hidden
fixture、oracle 参考输出、gate 答案、expected verdict)。Best State
按:测试可收集→Policy→回归→Hard Req→Public 通过数→预算→Diff
大小排序,禁止只按通过数;劣化轮真实恢复最佳快照;连续两轮无进展
STAGNATION;Scope Change(新增大依赖/改核心架构/联网/API Key/换
Python/改数据库/Adapter→Sidecar/超 Patch Budget/改成功标准/改
Protected Path)→暂停待用户,同意产生新 Plan Version + Hash。
循环永不宣布成功;之后必经 Freeze Adaptation → Final Hidden
Verification → clean replay → Completion Gate。

## 8. UI 页面(保持新手模式默认)

五步向导真实化:想法→项目/空目录(BLANK_PROJECT_MODE 显式)→仓库
(UI 内完成 analyze-source,零终端)→分析+准入四态(中文文案不变)
→接入方式选择+计划确认(风险逐条接受,演示「代为接受」删除)。
运行页:普通模式=准备/适配(第 N/3 轮、AI 改了什么、公开测试、原
项目是否正常、是否回滚、是否需要你决定)/最终(独立验收、全新环境
复测、结论);技术模式=Model Calls/Commands/Tokens/Trace/Snapshot
Hash/Diff/FailurePacket/Policy/Round Score。Apply 页:新增/修改文件、
依赖变化、将执行命令、测试结果、Drift、回滚方式;按钮=仅下载/应用
到副本/写入我的项目(二次确认)/取消/回滚。UI 只调 Core;subprocess
一律 shell=False + argv + timeout + capture + exit code + JSON
Schema 校验;禁止解析人类可读终端文本。

## 9. 验收标准(引 prompt §十七,20 条全量)

普通用户中文 UI 完成任务/无需手写 YAML/本地项目或空目录/任意公开
URL 可分析/不符合条件提前明确原因/过准入生成可解释 Plan/确认后才
执行/≤3 轮有界修复/Public Test 驱动/Hidden Oracle 不泄漏/成功
clean replay/失败准确 FailurePacket/可下载 Bundle/可 Staging 验证/
确认后才 Apply/Apply 可回滚/无 False Pass/UI 结论与 Core 一致/不
宣称任意仓库必然成功/不宣称 Docker 恶意代码沙箱。

## 10. 非目标

多 Agent;Planner/Reviewer/Critic/Recovery Agent;任意语言/GPU/私有
仓库;论文复现;自动 PR 合并;恶意代码强沙箱;生产部署;修改历史
Run/Trace/Evidence/Benchmark;LocalFlow 任何写操作。

## 11. 风险与回滚方案

| 风险 | 缓解/回滚 |
|---|---|
| 写回用户项目出错 | 三级协议+原子写+ApplyManifest+preimage 备份;回滚只恢复清单文件、幂等;Gate E 只在 fixture 验证,首次真实写回前停点授权 |
| Drift 竞态(确认到写回之间项目变化) | 写回前重算指纹,失配即 PROJECT_DRIFT_DETECTED 停止 |
| 期望草稿把上游输出当真值 | field_origin 标注+user_confirmed 强制;未确认不可 Freeze(测试钉死) |
| 修复循环泄漏 hidden oracle | FailurePacket 只准公开来源(静态断言+测试);held-out 文件名不进任何 Agent 可见文本 |
| 策略选择器过拟合首任务 | 8 策略由 host/repo 报告字段驱动,fixture 矩阵测试覆盖每种 kind |
| UI 抢跑(未确认即执行) | require_confirmed 结构门不变;新增步骤同样 sha 绑定 |
| 三步冻结/装配回归 | Gate B/C 每步跑全测试;既有 183+ 测试为回归网 |
| 每 Gate 回滚 | 单独普通 commit,不 squash;出错 revert 该 commit 即可,不改历史 |

## 12. 实施顺序

Gate B(分析/Plan 接线,无真实 Agent Run)→ Gate C(期望草稿+
Staging/Export,不写用户原项目)→ Gate D(真实 Guided Repair:先
fixture+fake model,真实模型前预注册)→ Gate E(Apply/Rollback,仅
fixture;首次真实写回前停点)→ Gate F(三个 dogfooding 候选,等用户
选择)。每 Gate:RFC/预注册→独立 commit→全测试→ruff→secret/
redaction scan→容器零泄漏→LocalFlow 不变→停点报告;并由**与实现
不同的独立 agent** 复核验证。
