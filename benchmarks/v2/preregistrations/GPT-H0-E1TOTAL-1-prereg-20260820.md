# GPT-H0-E1TOTAL-1 预注册:GPT 基线批(total 语义,2026-08-20)

**测试模式:E1(E 轨机制/工程侧读数;单臂观察批)。冻结点 = 本文件所在
提交;开跑后判据一字不改。**

授权链:用户 2026-08-20"为我适配和测试GPT性能";"GPT 基线批"自
DSH-INTEGRATION-REPORT §9 起在待批清单。

## 1. 研究问题(只此一问)

同一 total 语义四轴预算(`contract-e1-total.yaml`)下,**mini-swe 环
(基线 AgentBackend)× GPT** 在这道 seen 修复任务上的基线读数与消耗
形状是什么?——为 DQ-GPT-SHIM-1 的 GPT×DSH 读数提供 H0 侧**定性对照**
(该批三发全 8/9、唯欠回归检查;本批回答"同预算下 mini-swe 环的 GPT
是否同样砸回归")。

**不回答**:模型多能干(seen task,能力口径 false)、held-out、两臂
机制效应统计(**单臂批,无同批治疗臂**;与 DQ-GPT-SHIM-1 跨批只作
定性对照,不做合池检验)、GPT 与 DeepSeek 谁强。

## 2. 组合与同一性

- 臂:H0 = mini-swe 环 × openai-compatible 通道(REPOPROOF_API_BASE/
  KEY/MODEL 注入,不设 REPOPROOF_PROVIDER),`backend_id=mini-swe`。
- 与 DQ-GPT-SHIM-1 同:契约(contract-e1-total,四轴逐字同值)、任务包、
  宿主 base commit、host prompt、wheelhouse、验证器/隐藏 oracle/干净
  重放/Completion Gate。观测投影旋钮 **off**(E0 缺省)。
- preflight 判定(2026-08-20 双探活):action_protocol=native、
  temperature=0(gpt-5.5 与 gpt-5.6 同);REPOPROOF_CALL_TIMEOUT_S
  缺省 300s;obs_cap 缺省 8000。

## 3. 任务与分类旁挂(逐发次)

- 任务:`sqlglot-8042`(**seen task**,多批已见)
- `test_mode=E1` · `run_purpose=MECHANISM_ABLATION` · `task_seen=true`
- counts_toward_{model_capability, heldout_benchmark, mechanism_effect,
  treatment_effect} **全 false**(单臂观察,无治疗臂;机制口径也不计,
  防止被读成 E1-DSH 批的回填——**不回填**)
- `treatment_assigned=false` · assistance_level=BOUNDED_PUBLIC_REPAIR ·
  host_modification_mode=PRISTINE · oracle_authorship=UPSTREAM_OWN_TEST_SUITE

## 4. 发次序与上限

计划 2 发,**运行上限 3**(1 缺陷重跑位):

1. 8042 × `gpt-5.5` × H0(run_order 1);
2. 8042 × `gpt-5.6` × H0(run_order 2)。

n=1/模型 = pilot 规模(如实声明:扩展加 n 须另立批)。停规/发车绊线
(digest+锁态,每发前后)/端点健康探(发前 GET /models)同
DQ-GPT-SHIM-1 §5;instrument 缺陷 → 停修 → 该发从零重跑,不回填。

## 5. 封套与判读边界

- 封套:运行 ≤3;墙钟累计 ≤2h;in ≤4M tok / out ≤0.6M tok;超封套
  中止请示。
- 判读上界:单任务、seen、n=1/模型的观察读数——不得读作能力结论;
  不与 HB-PCDELTA-1 的 GPT 发次并池(per_round 语义不同);不与
  E1-DSH-MINIMAL-BRIDGE-1(deepseek)合池;与 DQ-GPT-SHIM-1 只作
  定性对照叙述。
- 裁决只走隐藏 oracle + 验证器 + 干净重放 + Completion Gate;
  台账 cost 列如实(litellm 读数缺失时 UNKNOWN)。
