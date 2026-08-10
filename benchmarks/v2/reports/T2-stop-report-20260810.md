# T2 停点报告(源 §48)· OfferClaw × Open Deep Research · 2026-08-10

## 1-4 任务标识

- Task:`t2-offerclaw-open-deep-research-v1`(task_shape **15/16**,冻结于 843d77d)
- Host:OfferClaw @ `85278e6`(副本 602 基线)· Target:open_deep_research @ `20aaa0d`
- TaskPackage:`benchmarks/v2/tasks/t2_open_deep_research/`(契约 14 条/公开 10 用例/隐藏 H1-H10/负控 5/fixtures)
- 预注册:`T2-prereg-20260810.md`(批 1)+ `T2-prereg-v2-20260810.md`(批 2,环境停修后)

## 5-7 控制组

- 正控:公开 10/10 + 隐藏 10/10 + 回归 602/602(冻结时)
- 负控 NC1-NC5:逐一挂在预期 tripwire(冻结时)
- 直连基线:公开 3/10、隐藏 1/10

## 8-9 模型运行汇总(6 发全入账,含轮线)

| # | 批 | 模型 | 公开逐轮 | 隐藏 | policy | replay | verdict | 读入/产出 | wall |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | deepseek-v4-pro | 0→3→3 | 1/10 | PASS | – | FAIL | 1.71M/19k | 15.1m |
| 2 | 1 | gpt-5.5 | 9(R1) | 10/10 | **FAIL**(2398>1800 行) | – | FAIL | 585k/4.9k | 8.4m |
| 3 | 1 | gpt-5.6 | 1→10 | 10/10 | PASS | **FAIL**(依赖不可复现) | FAIL | 1.05M/19k | 17.9m |
| 4 | 2 | deepseek-v4-pro | 0(1 轮止) | 0/10 | **FAIL**(2360>1800 行) | – | FAIL | 567k/6.9k | 6.3m |
| 5 | 2 | gpt-5.5 | **10(R1)** | **9/10**(缺 h5) | PASS | – | FAIL | 556k/8.0k | 7.5m |
| 6 | 2 | gpt-5.6 | **10(R1)** | 8/10(缺 h2,h5) | PASS | – | FAIL | 580k/16k | 10.8m |

**批 1 污染裁定**:run2/run3 的能力数字**不可引用为模型能力**(两者
均读取了遗留正控工作区 `_scratch_t2_positive/research_jobs.py`;run3
另从 `_scratch_odr_compat` venv 搬运 site-packages 并据此钉版=其
replay 死因)。run1/4/5/6 为干净测量。verdict 全部保留不改写。

## 10-11 FailurePacket / Best State

失败包驱动在 run3 可见(R1 1/10 → R2 10/10);批 2 三发均一轮收束
(5/6 号 all-public-pass 停,4 号补丁超限停)。Best State 均为末轮。

## 12-13 回滚 / Scope Change

全 6 发 rollback_count=0、scope_change=0。

## 14-18 能力 / 回归 / Policy / Replay / 判定

- **T2 零 PASS_ADAPTED(0/6)**——较 T1(2 个 PASS)难度台阶实证;
- 宿主回归 6/6 全程 603≥602,零破坏;主目录指纹 6/6 ok;
- 独立验证逐层拦截实录:policy 拦 2(补丁超限)、隐藏 oracle 拦 2
  (公开全绿仍抓出 h5/h2+h5)、replay 拦 1(不可复现依赖)、直连地板 1;
- **清洁环境共同失守点 = H5 重启语义**(2/2 走到 oracle 的干净 run
  都缺);h2 并发串扰 1 例。非同根因全败,§30.4 不触发;若后续攻坚,
  审计项预留:"正控须过完整 session+replay 路径"。

## 19 成本

6 发合计:读入 5.05M / 产出 74k tokens · agent 侧 wall 66 分钟 ·
全程在用户预批封套(计划 3 发 ×2=6 发)内,未追加。

## 20-22 新发现 Failure 与 Harness 增强

1. **环境污染类(批 1 实证,已修)**:任务工程遗留工作区被 agent 一条
   `ls` 挖到(正控=答案卷;实验 venv=包矿)。修复=遗留物全量隔离 +
   **bench 根白名单卫生门**(白名单外条目 → BLOCKED 零预算;钉死测试
   4 例;批 2 三发 `host.bench_hygiene ok` 实时验证)。触发条件:两
   run 独立中招(§38.2 重复证据达标);LESSONS #14;
2. **补丁预算与 vendor 路线的结构性冲突(跨模型重复 ×2)**:deepseek
   批 2 与 gpt-5.5 批 1 独立选择"拷贝 ODR 源码进宿主树"路线,均落在
   2360-2398 行 > 1800 上限。合规赢路线(会话内 sys.path 引 upstream,
   批 2 两个 gpt 实际走通)存在,故非任务不可能;记录为"任务形状信息",
   不改冻结预算;
3. e5 论文路由引导缺口与 OfferClaw 侧改进建议(批前基线阶段发现,
   已单列;OfferClaw 改进挂独立任务芯片);
4. 观察级(批后议,不构成缺陷):`--dry-run` 探测被禁装 token 名单
   过宽拦截;PolicyVerifier.extra.causality_problems 字段名与语义不符
   (记录的是问题总数);agent 提示词"Linux container"措辞与 L 模式
   实况不符(保守方向,全模型一致)。

## 23-24 Feature Transaction / Rollback Readiness

无 PASS → 无 Apply、无 Feature Transaction;Unapproved Real Apply=0。

## 25 证据束

`runs/t2-…-{035957,042251,044105,052324,053152,054159}/`(trace 链
6/6 校验通过)· runs.jsonl 6 行 · 批前/终验后 RAG 基线与 KB 指纹
`reports/t2-rag-baseline/` · 预注册 ×2 · 本报告。

## 附:补发 run7 与 H5 重裁定(2026-08-10,用户令"看 h5 方差"直接钉出 oracle 缺陷)

**run7**(gpt-5.5 #3,134545,预注册于 prereg-v2 补发节):公开 10/10
一轮 · 隐藏 7/10(h1/h2/h5)· policy PASS · 559k/7.3k · 主指纹 ok。

**H5 重裁定(取证三步,现场重建于 /tmp,bundle diff 逐发复跑)**:
1. 三个清洁实现(5.5×2、5.6×1)全部选 SQLite 持久化;oracle h5 第一
   断言锚定正控的 `research_jobs/{jid}.json` 文件布局 → glob 空 →
   全部在"未持久化"层假阴性;
2. 契约 R9/R10 只规定行为、未言明存储布局;公开套件无重启用例且失败
   持久化用例布局无关(三发公开全过即证);
3. **行为层复验 3/3 合规**:人工制造 stale running + 模块重装载,三个
   实现全部正确落终态(failed),无一永久 running。

**修正结论**:E4 所记"h5=共同短板"撤销;h5 三挂全部重分类为
**oracle 布局锚定缺陷(系统性假阴性)**。清洁队列行为层等价分:
gpt-5.5 批2=**10/10 等价**(唯一拦截者=oracle 缺陷;其 replay 反事实
结果如实记为未知,不声称"本应 PASS")、gpt-5.6 批2=9/10 等价(h2 真
失分)、run7=8/10 等价(h1/h2 真失分=采样方差)。真实能力缺口收敛为:
**h2 并发隔离(2/3)、h1 图保真(1/3)、deepseek 地板(2/2)**。

**处置**:冻结的 v1 任务包与全部 verdict 不改写、不入排名;task-v2
设计债记档——h5 须改为布局无关判据(如进程级中断/适配器声明存储探针);
oracle stdout 未归档致断言层取证需现场重建,一并列为 bundle 改进项。
LESSONS #15(oracle 不得锚定契约未言明的实现布局,#3 同族)。

## 红线记分(全批)

False System Pass **0** · Hidden Oracle Leakage **0**(oracle 不在
遗留物中,trace 零接触)· Unapproved Real Apply **0** · 真实数据
备份零接触(已迁出 bench)· 弱模型零加预算 · n<3 不排名(每模型
干净 n=1-2,不作排名结论)。

## 结论边界(§49 纪律)

可说:T2 在冻结预算内对当前三模型有真实区分度;RepoProof 六层验证
在 6 发中逐层拦下全部不合格产物且零误放行;h5(重启恢复语义)是
当前模型代际在本任务上的共同短板。不可说:模型排名(n 不足)、
harness 普遍提效、任务不可能(合规路线已被走通 9/10)。
