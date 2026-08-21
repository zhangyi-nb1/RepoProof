# V2GEN-GPT-EXT-1 预注册:构造法 v2 扩批(click×2)+ DSH 教导迁移一发(2026-08-21)

**测试模式:E1(单臂观察批,双子臂:H0 mini-swe 计分 4 发 + DSH-shim 观察
1 发;total 语义;F0/F0b 冒烟不计)。冻结点 = 本文件所在提交;开跑后判据
一字不改。**

授权链:用户 2026-08-21 批准建议 1-3("那先完成1-3,然后为我总结探寻到
的结果和结论")—— 1=v2 铺到 click-3581/3407 每模型跨任务 n≥3、2=失败驱动
分析、3=DSH 臂一发 v2 验教导迁移。承接 V2GEN-GPT-BASE-1(冻结 44e4c69,
2/2 PASS)。

## 1. 研究问题

**Q1(扩批坐实,H0 计分 4 发)**:构造法 v2 机制是否跨任务成立 —— 两类
历史败象(剥离旧测试被砸 / 隐藏新测试被砸)在 click 两任务上是否同样
缺席(delta 全绿 + 回归零破坏)。每模型跨 v2 代际任务数达 n=3
(sqlglot 前批 + click 两任务;跨批合述仅作描述,两批同轴同冻结纪律)。

**Q2(DSH 教导迁移,观察 1 发)**:契约承载的教导面(R5 名单/R6 保守性)
是否迁移到 DSH 循环 —— v1 时代 DSH 各发(deepseek E1 8/12、GPT DQ 3/3)
全败于同一回归破坏类;v2 下 DSH×gpt-5.6×sqlglot-8042-v2 一发是否避开。
**预写**:DSH 全史重发且 v2 树更大,若先撞 in-token 轴(R6 shim 发前拒
→ budget_refused)则读数 = "DSH 重发史×total 1.8M 轴不相容",教导面
问题**悬置不判**,不读作教导失效。

**不回答**:模型能力(seen task,n=1/组合)、v1 vs v2 数值 A/B、
DSH vs H0 优劣(E0/E1 永不互比同律)、投影(本批 off)。

## 2. 组合与同一性

- H0 臂:mini-swe × openai-compatible(REPOPROOF_API_BASE/KEY/MODEL 注入,
  不设 REPOPROOF_PROVIDER),契约 `benchmarks/v2/tasks/hb1_click_3581_v2/
  contract-e1-total.yaml` 与 `…/hb1_click_3407_v2/contract-e1-total.yaml`
  —— 预算块与 sqlglot-8042-v2 e1-total **逐字同值**(total/1/500/300/
  15/1500/60 分/1.8M/240K);差异恰为身份/宿主/基线/R5 名单。
- DSH 臂:`--backend dsh` × 同环境注入 × `rt-dsh-minimal-0.1.0rc6-v1` ×
  dsh_gpt_shim(upstream_protocol=openai-compatible+dsh_gpt_shim),契约
  `…/hb1_sqlglot_8042_v2/contract-e1-total.yaml`;R6 shim 发前预算闸在环
  (max_input_tokens=1.8M)。**资格声明**:该 runtime 的 qualified 只背书
  deepseek 直连;GPT×shim 资格批 DQ-GPT-SHIM-1 曾如实 FAIL —— 本发是
  MECHANISM_ABLATION 观察,**不授予也不使用资格**,E1G-GPT-BRIDGE-1 维持
  永不开跑;重走资格仍须另立 DQ-GPT-SHIM-2。
- 宿主:hb1-click-3581-v2(基线 1681 绿/0 红/26 skip)、hb1-click-3407-v2
  (1917/0/26)、hb1-sqlglot-8042-v2(1193/0/0)—— 全部锁写 + host_digest
  入证据;发车绊线 `check_host_digest.py <vid>` 每发前后(vid 对应本发宿主)。
- 投影:`REPOPROOF_CONTEXT_PROJECTION` 不设(off,WV11 结论沿用)。
- 对照读数(方向性,不合池):click 两任务无 v1 同轴基线(v1 e1-total
  GPT 只跑过 sqlglot;HB-PCDELTA-1 是 per_round+guided 多轮制,制度不同
  不可数值比较)—— click 读数是 v2 制度下的首采,问题只问败象类缺席。

## 3. 分类旁挂(逐计分发,DSH 发同挂)

`test_mode=E1` · `run_purpose=MECHANISM_ABLATION` · `task_seen=true` ·
counts_toward_* **全 false** · `treatment_assigned=false` ·
assistance_level=BOUNDED_PUBLIC_REPAIR · host_modification_mode=PRISTINE ·
oracle_authorship=UPSTREAM_OWN_TEST_SUITE · PRE_REGISTERED。
F0/F0b 冒烟不落分类行。

## 4. 发次序与上限

冒烟(零 API,负控双侧验新宿主判卷):
1. F0:3581-v2 × `--fake positive` → 期望 PASS_ADAPTED;
2. F0b:3581-v2 × `--fake control:nc_regression_break` → 期望 FAIL/REGRESSION_BROKEN;
3. F0:3407-v2 × `--fake positive` → 期望 PASS_ADAPTED;
4. F0b:3407-v2 × `--fake control:nc_regression_break` → 期望 FAIL/REGRESSION_BROKEN。

计分(健康探 200 且目标模型在列后):

5. 发 1:3581-v2 × gpt-5.5 × H0(run_order 1);
6. 发 2:3581-v2 × gpt-5.6 × H0(run_order 2);
7. 发 3:3407-v2 × gpt-5.5 × H0(run_order 3);
8. 发 4:3407-v2 × gpt-5.6 × H0(run_order 4);
9. 发 5:8042-v2 × gpt-5.6 × **DSH-shim**(run_order 5,Q2 观察)。

计分 5 发,**运行上限 7**(+2 缺陷重跑位)。停规:冒烟不达期望 → 停修,
该冒烟从零重跑;instrument 缺陷 → 停修重跑不回填;绊线红 → 全停;
DSH 发 budget_refused 属预写读数不属缺陷,不占重跑位。

## 5. 封套与判读边界

- 封套:计分 ≤7;墙钟累计 ≤4h;in ≤6M tok(名义;H0 预估 0.4-0.8M/发 ×4
  + DSH ≤1.8M)/ out ≤0.6M tok;超封套中止请示。
- 裁决只走隐藏 oracle + 验证器 + 干净重放 + Completion Gate;台账 cost
  如实;闸门数字只出自 gate_report。
- 判读上界:全部 seen、n=1/组合;Q1 只问败象类缺席,不作能力/成功率
  主张;Q2 若 PASS → 教导面可迁移 DSH 循环(单发方向读数);若败于
  回归类 → 教导面不足以覆盖 DSH 循环,如实记;若 budget_refused →
  悬置;不与 v1、不与 deepseek 合池。

---

## 附录:批结果转录(2026-08-21,机械转录不改判据)

冻结点 aa43ba6;工程 2bd6892(门 275/275,证据 c7be971)。发序照 §4,
绊线每发前后全绿(三宿主),健康探 200 双模型在列,零缺陷零重跑。

冒烟 4/4 达期望:3581-v2 F0 PASS_ADAPTED(3/3)/ F0b FAIL/REGRESSION_BROKEN;
3407-v2 F0 PASS_ADAPTED(1/1)/ F0b FAIL/REGRESSION_BROKEN —— 两新宿主判卷
双侧验讫。

| 发 | 组合 | 判决 | 读数 |
|---|---|---|---|
| 1 | 3581-v2 × gpt-5.5 × H0 | **PASS_ADAPTED**(3/3,回归零破坏)+ replay PASS | 16 调用 / in 176,786(cache 76%)/ 墙 3.0 分 |
| 2 | 3581-v2 × gpt-5.6 × H0 | **PASS_ADAPTED**(3/3,回归零破坏)+ replay PASS | 21 调用 / in 222,200(cache 80%)/ 墙 5.7 分 |
| 3 | 3407-v2 × gpt-5.5 × H0 | **FAIL / j3=DESIGN_MISMATCH**(delta 0/1,回归 1917/1917 零破坏) | 28 调用 / in 436,314(cache 70%) |
| 4 | 3407-v2 × gpt-5.6 × H0 | **FAIL / j3=DESIGN_MISMATCH**(同一节点 0/1,回归零破坏) | 22 调用 / in 293,792(cache 82%) |
| 5 | 8042-v2 × gpt-5.6 × **DSH** | **FAIL / j3=REGRESSION_BROKEN**(delta 5/5 绿,砸 test_multiple_pivoted_sources) | 52 调用 / in 1,753,290(贴 1.8M 轴)/ out 49K / 墙 29.5 分 |

封套核销:计分 5/≤7;in 2.88M ≤6M;out 92K ≤0.6M;墙累计(计分 49.8 分
+ 冒烟)≈65 分 ≤4h —— 全内,零重跑位动用。

**Q1 答(扩批坐实)**:v2 机制跨任务成立 —— H0 四发回归**全部零破坏**
(可见+隐藏两面),历史盲区败象类在 H0 零复发。通过侧:3581 双模型
PASS;失败侧:3407 双模型败**同一枚**隐藏节点
(param_type_input_parameter_defaults_at_runtime),回归干净,j3=
DESIGN_MISMATCH。归因(patch 与池内答案对读):3407 题面是上游**开放式
设计讨论**(三选项 + 作者偏好),合并版真实设计(ParamType 第二类型参数
+ PEP 696 默认 + Python<3.13 `__class_getitem__` 运行期补默认)**不在
题面文本里**;两模型均只按题面选项改 prompt() 签名层,谁也没有(也无从)
重构出合并版设计 —— **题面欠定类,病灶在任务构造侧不在模型侧**。
跨任务 tally(v2 代际 H0,与前批合述仅描述):gpt-5.5 与 gpt-5.6 各
2/3 PASS,失败完全同源。

**Q2 答(DSH 教导迁移)**:**不迁移**。同模型(gpt-5.6)×同任务
(8042-v2)×同契约(同 R5/R6 教导)×同端点:H0 环 PASS_ADAPTED,DSH 环
delta 5/5 全绿、可见回归干净,却砸掉 v1 历史盲区节点
multiple_pivoted_sources(R3 分类器窄化单发复核:STRIPPED_NEW,证据
V2GEN-GPT-EXT-1-dsh.json)——教导面写在契约里,H0 循环下起效,DSH 循环
下不起效。消耗同差:DSH in 4.1×(1.75M vs 428K)、52 vs 26 调用。
无 budget_refused(预写的悬置分支未触发,判读有效)。E5 机制
"换循环=换消耗形状"延伸为**"换循环=换合规形状"**。观察发不授予资格。

批性质注记:全部 seen、n=1/组合;失败侧两类均已归因(题面欠定 /
循环合规不迁移),无 harness 缺陷发现;不作能力主张,不合池。
