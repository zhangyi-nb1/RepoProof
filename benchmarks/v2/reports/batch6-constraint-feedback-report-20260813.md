# 批 6 报告:轮内约束反馈层重测(2026-08-13)

预注册:`benchmarks/v2/preregistrations/T2v4-T3v5-rerun-prereg-20260812.md`
(冻结于 `d42e8a3`,开跑前提交)。harness_commit = `d42e8a38`,全批一致。
任务包 T2v4 / T3v5 逐字节未动(`git diff` 空)。

## 结果表(4 发,全部入账,无挑选)

| order | 任务 | 模型 | 轮次 | 公开逐轮 | 回滚 | policy | replay | verdict |
|---|---|---|---|---|---|---|---|---|
| 51 | T2v4 | gpt-5.5 | 2/3 | [3, 12] | 0 | PASS | **PASS** | **PASS_ADAPTED** |
| 52 | T2v4 | gpt-5.6 | 1/3 | [12] | 0 | PASS | **PASS** | **PASS_ADAPTED** |
| 53 | T3v5 | gpt-5.5 | 3/3 | [3, 3, 21] | 1 | PASS | UNKNOWN | FAIL |
| 54 | T3v5 | gpt-5.6 | 3/3 | [13, 13, 11] | 2 | PASS | UNKNOWN | FAIL |

红线:主目录指纹对账 4/4 `ok`,postflight 残留 0,False Pass 0(逐发
人工取证见下),未批准写回 0。

**上一批同格对照(harness `6995ee46`,不合并统计,仅供死因对照)**:
order 47-50 四发全 FAIL,其中三发是"公开全绿即停 → 剩余轮次浪费 →
终局击杀"。本批同样两个模型、同样两个任务包,T2v4 双双转 PASS。

## 预注册判据核对(逐条,措辞未改)

| 判据 | 结果 | 证据 |
|---|---|---|
| **P1** 全绿+fatal 时不停轮 | **未被检验(vacuous)** | 本批无一轮在公开全绿时挂着 fatal;按预注册"不许拿没发生的事当成功",不记通过 |
| **P2** 违规轮包体含具体真值 | **通过 5/5** | 与 trace 真值交叉核对:`langchain-community`、`anthropic`、denied 计数,逐条出现在 `record.failure_packets` 里 |
| **P3** denied 不跨轮继承 | **通过 9/9** | 9 个轮次的 `record.policy_violations` 全部等于该轮 `denied_this_round` |
| **P4** 回滚必有 ROLLBACK 包 | **通过 1/1(可验实例)** | order-54 round-3 提示含 `ROLLED BACK`;order-53 的回滚发生在**最后一轮**,结构上无下一轮可送,记为不可验,非失效 |

**判定**:无一条"未通过"。P1 未被检验如实入档,不以 PASS 数掩盖。

## 机制在真实 run 里的三次现场

1. **order-51**:round-1 声明 `langchain-community`(离线轮仓解析不到)→
   探针当场抓到 → 结构化包点名该分发进入 round-2 提示 → round-2 探针
   清零、公开 12/12 → 干净重放 **PASS**。**旧 harness 下这正是 030156 /
   054108 的死法**:三轮零警告,盖棺时被重放击杀。
2. **order-54**:同一形态的 `anthropic` 连续三轮反馈,模型始终未消——
   **反馈到位,不解决是模型侧**。这正是反馈层该有的分锅能力。
3. **order-54 round-3**:提示里同时携带 ROLLBACK 说明、被拒命令说明、
   未解决的钉版三类包。旧 harness 下回滚完全静默。

## 逐发人工取证(系统 verdict 不作放行依据)

- **order-51**:适配 vendored 了 `langchain/`、`mcp/`、`tavily/`、
  `langchain_mcp_adapters/` 顶层桩 + `research_jobs_fake_chat.py`——
  与 060126 同型,首看疑似伪造。**查实为真适配**:①`../upstream/src`
  入 sys.path 后导入**真** `open_deep_research.deep_researcher`,
  oracle h1 运行时打桩(热身→对 sys.modules 实际对象打桩→二发观测)
  作证图被真调用;②那个"Fake"是**连官方 fake_llm_server 的真 HTTP
  客户端**(POST `$OPENAI_BASE_URL/chat/completions`,无该变量直接抛错,
  不本地编造);③桩只补轮仓里缺席的外围包,search 配置为 `none`。
- **order-52**:vendored `open_deep_research-0.0.16-py3-none-any.whl`。
  **逐字节核对**:轮内 5 个 `.py`,4 个与钉版上游 SHA-256 相同,唯一差异
  是 `utils.py` 把三个可选依赖 import 改成 try/except 容错,核心
  `deep_researcher.py` 分毫未动。上游 pyproject 声明版本正是 0.0.16。
- **order-53 / 54**:公开面未全绿、隐藏 oracle 未过,不构成 PASS 争议。

## 新发现(取证在此,**本批不改**,留待下一轮迭代)

### F1 · 循环排序比终局闸门更严(LESSONS #33 的第二形态)

**实录**:order-53 round-3 公开 **21/23**、仅 1 条命令被拒;该轮被回滚,
最终交付的是 round-2 的 **3/23** 状态。被拒的命令是
`... | xargs -I{} sh -c 'cat job_log.txt'` —— 一条**无害的调试命令**,
撞在 `sh -c` 黑名单上,**什么也没执行**。

**要害**:`policy_result`(终局验收闸)**根本不数 denied**——它只查
oracle/upstream 树未动、manifest 冻结、patch 上限、适配复核、token 超限。
而循环排序 `full_score` 的第 2 位把"本轮有 denied"压在通过数之上。于是
**循环用一把比终局更严的尺子,把终局本会接受的最好一轮扔了**。

n=2(060126 round-2 12/12 因 1 denied 被回滚;order-53 round-3 21/23 同因)。

**处方(下一批,需重预注册)**:按"排序只对齐终局判据,其余一律教"拆分——
`tampered`/动 oracle 等**终局会杀**的保持毒化排序;`denied`(已被拦下、
零执行)退出排序,只走违规包教学(H2 已在做)。**本批冻结了排序语义,
故不动**;此处只留证据。

### F2 · T2v4 判别面潜伏洞(与 T3v4→v5 的 h7 同族)

oracle 从不断言 `fake_llm_server` **收到过调用**。本批两发均实打实走
HTTP(已人工核对),但判别面本身容得下"本地编造响应"的下一代形态。
处方:T2v5 引入与 T3v5 h7 同构的因果金丝雀。**不在批内改任务包**。

### F3 · 构造函数先建证据目录、后过护栏

`HostGuidedRunner.__init__` 在 `_verify_static_resources()` 之前就建了
`runs/<task>-<ts>/`,导致被护栏拒绝的调用也留下空壳目录;跑测试套件
(`tests/test_host_guided.py` 两处传真实项目根)会在真实证据树里留空
run 目录。已在本批期间复现(`runs/t1-...-232901`、`-234726`)。
处方:先核验后建店 + 测试传 tmp_path。

## 闸门数字(唯一产出器 `scripts/gate_report.py`)

**T1 2 / T2 4 / T3 1 / T4 0**。T2 由 2 增至 4(本批两发 PASS_ADAPTED
均为正式预注册批次、真实模型、含干净重放)。T3 阶段闸门仍 1,未变。

## 可比性声明

本批 harness_commit `d42e8a38` 与批 5(`cea0bf1`)、探索批(`6995ee46`)
**不可合并统计**。n=1/模型,不排名。旧批次台账行不改写。
