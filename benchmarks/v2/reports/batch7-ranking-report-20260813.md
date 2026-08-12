# 批 7 报告:排序对齐终局(LESSONS #35)现场验证(2026-08-13)

预注册:`benchmarks/v2/preregistrations/T3v5-ranking-prereg-20260813.md`。
判定由 `scripts/batch_criteria.py T3v5-RANKING-20260813` 机器产出,
散文只解释。

**harness_commit 记账更正(如实)**:预注册文里冻结声明写 `a573bc9`,
台账两发实际记录 `3851f60`(即预注册提交本身)。二者
`git diff -- src/ scripts/` **为空** —— 运行路径代码逐字节相同,只差那份
预注册文档。不改台账,在此标注。

## 结果表(2 发,全部入账)

| order | 模型 | 轮次 | 公开逐轮 | denied | 隐藏 | policy | replay | verdict |
|---|---|---|---|---|---|---|---|---|
| 55 | gpt-5.5 | 3/3 | [3, 6, 8] | 0 | 2/8 | PASS | UNKNOWN | FAIL |
| 56 | gpt-5.6 | 2/3 | [7, **23**] | 1(r1) | **8/8** | PASS | **PASS** | **PASS_ADAPTED** |

红线:主目录指纹对账 2/2 `ok`,False Pass 0(人工取证见下),泄漏 0,
未批准写回 0。

## 判据核对(机器判定,`batch_criteria.py` 输出)

| 判据 | 结果 | 证据 |
|---|---|---|
| **Q1** denied 不计入排序 | **通过** | order-56 r1:`denied=1` → `policy_violations=0`,score 第 2 位保持 1.0。**批 6 同型情形该值是 1 / 0.0** |
| **P3** denied 不跨轮继承 | **通过 5/5** | 5 个轮次逐一相符 |
| **P2** 违规包携带真值 | **通过 1/1** | order-56 r1 的 POLICY_VIOLATION 包点名"1 command(s) were DENIED" |
| **Q2** 无仅因 denied 的回滚冤案 | **未被检验** | 本批零回滚 |
| **Q3** denied 的最优轮必须当选 | **未被检验** | 无"denied 且严格最优"的轮(order-56 最优轮 r2 的 denied=0) |
| **Q4** tampered 仍计入排序 | **未被检验** | 无一轮改动 public_tests(预期内) |
| **P4** 回滚必被说明 | **未被检验** | 本批零回滚 |

**合议:通过**(无一条未通过)。**但必须说清强度**:live 只兑现了
Q1 —— "denied 不再毒化排序"这一半;"因此最好的轮能当选"(Q3)这一半
本批**未被检验**,因为凑巧没出现"denied 轮同时是最优轮"的组合。

## 确定性推演(预注册前已完成并入档,不是本批结果)

用批 6 真实逐轮数据分别以新旧排序重算 best_round:

| 发次 | 逐轮 公开/denied | 旧排序选 | 新排序选 | 结局改变 |
|---|---|---|---|---|
| order-53 | r1=3/0 r2=3/0 **r3=21/1** | round-1(3/23) | **round-3(21/23)** | **是** |
| order-54 | r1=13/0 r2=13/1 r3=11/1 | round-1(13/23) | round-1(13/23) | 否 |

**合起来读**:推演证明"在批 6 真实出现过的局面里,新排序会交付 21/23
而非 3/23";live 证明"新排序在真实运行中确实不再给 denied 轮扣分,且
教学包照常送达"。Q3 那一环仍缺现场实例,留待后续批次自然遇到。

## 逐发人工取证(系统 verdict 不作放行依据)

- **order-56(PASS)**:①真上游在场——`from browser_use import Agent,
  BrowserProfile, BrowserSession, ChatOpenAI`,由 BrowserSession 实际驱动
  浏览器;②**计量指纹 27 requests**(capability 与 replay 两次一致),
  与批 3 order-37「真 browser-use sidecar」的 27 同量级;伪造型 order-38
  是 10/9/9(≈ 每作业恰一次),纯 HTTP 重写型是 0 —— 本发不是那两种;
  ③oracle 8/8 含 h7 因果金丝雀;④干净重放 PASS。**判定:PASS 坐实。**
- **order-55(FAIL)**:公开 8/23、隐藏 2/8,不构成 PASS 争议。

## 闸门(唯一产出器 `scripts/gate_report.py`)

**T1 2 / T2 4 / T3 2 / T4 0**。T3 由 1 增至 2,`gate_met` 现为
T1/T2/T3 全 True、T4 False。

## 可比性

批 7(`3851f60`)与批 6(`d42e8a38`)、批 5(`cea0bf1`)**不可合并统计**。
n=1/模型,不排名。旧批次台账行不改写。

## 附:本批新增的流程件

`scripts/batch_criteria.py` —— 批次判据核对器。此前"P2 通过 5/5"这类
判定是我手打 python 片段现算的:一次性、不可复跑,批 6 就错过一次
(把 `anthropic` 判成"不含具体真值")。现在固化为脚本,三种结局
通过/未通过/**未被检验**,vacuous 是一等公民。
**自身负控已钉死**:把批 6(修复前)数据喂进去,Q1/Q2/Q3 必须报红、
P2/P3/P4 必须报绿 —— 检查器要先证明自己查得出缺陷,才有资格发绿。
