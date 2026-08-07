# Resume claims — evidence-bound wording only

Every number below traces to [benchmark_summary.json](benchmark_summary.json);
wording constraints come from [CLAIMS_MATRIX.md](CLAIMS_MATRIX.md).
The three contribution planes must never be merged:
**Agent** wrote the adapter (upstream calls, schema mapping, flag
conversion, error wrapping). **Harness** provided contract adequacy,
isolation, policy, budgets, verification, replay, gate. **Host
Guard** owns input type validation and stable error boundaries.

## 版本 1 · 稳健技术版

**RepoProof — 面向 Coding Agent 的开源能力采用与独立验证 Harness(个人项目,Python/Docker)**

- 设计并实现"冻结合同 → 合同充分性准入 → 单 Agent 受控执行 → 独立四重验证(Capability/Regression/Policy/Clean-room Replay)→ 证据闭环"的完整协议;完成 12 次记录在案的真实运行,产出 1 例可信 PASS_ADAPTED 与 11 例带确定性失败复现的诚实 FAIL。
  - 证据:`docs/benchmark_summary.json`、`docs/evidence/gate72-corrected-spec-run/`
- 建立 9 类真实失败分类学(含 harness 自身两个 bug 的自查自证),据此把修复方向从"调 prompt"转向"规格工程":RequirementSpec + 13 项确定性 ContractAdequacyGate + Prompt 投影 hash 绑定 + Host InputContractGuard,修复后单次预注册运行取得 capability 18/18(含 held-out)+ 干净容器重放通过。
  - 证据:`docs/FAILURE_TAXONOMY.md`、Gate 7→7.2 提交链(`b5430bb`→`f428c30`)
- 以证据纪律为第一原则:每次真实运行均预注册且不重跑;agent 自述不参与判定;31/33、9/12 等高完成度产物被独立 verifier 拒绝;对外数字由机器可读事实源 + 确定性 claims 检查器约束。
  - 证据:`scripts/check_public_claims.py`、`docs/evidence/gate3c-real-run/`、`gate5-second-repo/`
- 不能使用的表述:见下方"全局禁语"。

## 版本 2 · 冲击力版

**RepoProof — 让 Coding Agent 的"我做完了"接受审判的证据 Harness**

- 真实 agent 把开源库适配到 31/33 测试通过——系统仍判 FAIL 并在全新容器复现同一失败:高完成度不等于可采用,这是本项目要解决的问题本身。
  - 证据:`docs/evidence/gate3c-real-run/`
- 首个 PASS_ADAPTED 不是靠调 prompt,而是靠把合同修到"机器可判充分":typed RequirementSpec、公开真值表、13 项确定性准入门、宿主输入守卫——修复后真实 agent 单次预注册运行 18/18(含 held-out)+ 干净重放,16/20 调用内主动提交。
  - 证据:`docs/evidence/gate72-corrected-spec-run/PREREGISTRATION.md` + `report.json`
- 判定权完全不在 agent 手里:completion gate 只读独立 verifier 结构化结果,claim 被构造性忽略并由测试钉死;负结果(预算感知 null、ledger 被无视)全部保留在 benchmark 里。
  - 证据:`docs/BENCHMARK.md`、`docs/PROJECT_EVOLUTION.md`
- 注意:此版本仍不得暗示"harness 提升成功率"或"单变量改进"。

## 版本 3 · 面试友好版

**RepoProof — 开源库采用任务的"考试院":出题、监考、阅卷、复核全独立**

- 把"把 X 库的能力接进宿主项目"变成冻结合同 + 隐藏判卷:agent 只见公开合同/公开样例/可运行公开测试,oracle 与 held-out 输入永不进入 agent 容器。
- 一个真实的 mini-swe-agent(deepseek-v4-pro)在这套约束下写出 67 行 adapter 拿到首个 PASS_ADAPTED;此前同源任务因合同欠规范诚实 FAIL——失败被归因到任务作者而非 agent,并转化为可复用的准入门。
- 所有对外数字有机器可读事实源和确定性一致性检查;演示完全无模型(证据复算 + 干净容器重放)。
  - 证据:`repoproof demo verify/replay`、`docs/DEMO.md`

## 全局禁语(任何版本、任何场合)

- "支持任意 GitHub 仓库 / 保证适配成功 / 生产级平台"
- "harness 普遍提升 agent 成功率"(F3;无对照证据)
- "单变量实验证明规格修复带来 8/11→18/18"(F8;多变量同时改变)
- "输入校验也是 agent 完成的"(F9;那是 Host Guard)
- "budget awareness / coverage ledger 已证明有效"(F4/F5;null / 被忽略)
- 不得称 security sandbox,不得称 tamper-proof(F6/F7;正确词=isolation / tamper-evident)
