# 预注册:批 6 · 轮内约束反馈层重测(2026-08-12,冻结后不改)

## 一句话

**任务包一个字节不动,只换 harness**,验证 LESSONS #33 修复(轮内约束
反馈)是否把"第 1 轮公开全绿即停、剩余轮次整数浪费、盖棺被政策/重放
击杀"这个形状消掉。**预测的是机制,不是成绩。**

## 变更面(唯一变量声明)

| 面 | 状态 | 取证 |
|---|---|---|
| 任务包 `t2_open_deep_research_v4` / `t3_browser_use_v5` | **逐字节不动** | `git diff 6995ee46..a099e1e -- benchmarks/v2/tasks/{t2_open_deep_research_v4,t3_browser_use_v5}` 输出为空 |
| 预算/契约/公开面/oracle | 不动(见下预算盒) | 同上(契约与 fixtures 都在任务包内) |
| harness | **6995ee46 → a099e1e** | `repair_loop.py` +53 / `host_guided.py` +248 / `failure_packet.py` +3;`scripts/` 为验证工具,不参与运行 |

**可比性声明**:harness_commit 变了,本批**不得与批 5 及此前任何批次
合并统计**;旧批次台账行不改写、不重跑、不作废(它们的 verdict 本就
正确,错的是 harness 没在轮内说话)。本批是新基线的第 1 批,n=1/模型
不排名。

**§39 边界自查**:改的是"把终局闸门已经在执法、且任务提示里已经全文
披露的约束,在轮间告诉 agent 当前读数"。没有放宽任何上限、没有减少
任何需求、没有泄漏隐藏面。任务难度不变,考题印清楚了。

## 反事实(上批台账实测,机器可查)

| run_order | run_id 尾号 | 模型 | rounds_used | public_by_round | 死因 | 浪费轮次 |
|---|---|---|---|---|---|---|
| 47 | 030156 | gpt-5.5 | 2/3 | [9, 23] | 钉版离线解析不到,重放击杀 | 1 |
| 48 | 054108 | gpt-5.6 | 1/3 | [23] | 同上(browser-use==0.13.7) | 2 |
| 49 | 060126 | gpt-5.5 | 3/3 | [3, 12, 7] | 12/12 轮因 1 条被拒命令回滚(rollback_count=2),denied 跨轮累计 | 0(但最好的一轮被扔) |
| 50 | 061522 | gpt-5.6 | 1/3 | [12] | patch 2630 行 > 1800,政策闸击杀 | 2 |
| 39 | 181550(批 5) | gpt-5.5 | 1/3 | [23] | 46 文件 > 25,政策闸击杀 | 2 |

五发的共同点:**公开面全绿之后 harness 就不说话了**,而杀死它们的三条
判据(patch 上限、钉版可解析、被拒命令)全都在任务提示里写着。

## 冻结预测(机制可判性;跑完逐条核对,事后不得改措辞)

**P1(H3 生效)**:出现"某轮公开全绿但仍有 fatal 违规"的情形时,
`rounds_used` 必须 > 该轮序号——即不再全绿即停。
判法:`runs.jsonl` 的 `rounds_used` × `public_passed_by_round` ×
`runs/<id>/repair/round-N/record.json` 的 `failure_packets`。
**若本批无任何一发触发 fatal 违规,P1 记为"未被检验"(vacuous),不算
通过也不算失败**——不许拿没发生的事当成功。

**P2(H2 生效)**:任一轮触发 {patch 文件/行数超限、requirements 新增
钉版离线解析不到、命令被拒、改动 public_tests} 中任一项时,该轮
`record.json` 的 `failure_packets` 必须非空,且包体含**具体数字或分发名**
(如 `2630`+`1800`、`browser-use`)。反例=上批 061522 的
`failure_packets: []` 配 `diff_lines: 2630`。

**P3(H1 生效)**:任一轮 denied ≥ 1 时,**下一轮**若自身零违规,则该轮
`record.json` 的 `policy_violations` 必须为 0(不继承)。反例=上批
060126 round-3 背着 round-2 的 1。

**P4(H4 生效)**:发生回滚(`rollback_count > 0`)时,下一轮
`failure_packets` 必须含一枚 `type: ROLLBACK` 的包,且被恢复快照的失败
包 `actual` 字段不得全是"该检查项断言失败"占位串。

**观察量(不预测、只记录)**:verdict 分布、公开/隐藏通过数、
`rounds_used`、token 用量、依赖探针命中次数。**PASS 数不作预测**——
成绩由能力与运气支配,拿它当预测会污染"机制是否生效"这个真正的问题。

**判定口径**:P1-P4 逐条给 通过/未通过/未被检验;**任一条"未通过"即
本批结论为"修复未验证",不得以 PASS 数好看掩盖**。

## 运行计划(v3 代跑协议,用户已一句授权)

- **模型池与顺序**:① gpt-5.5 × T2v4 ② gpt-5.6 × T2v4 ③ gpt-5.5 × T3v5
  ④ gpt-5.6 × T3v5(run_order 51-54)。deepseek 维持出池(批 4 决定;
  上批 0/12 属能力边界,反馈层不制造能力,重入需另行预注册)。
- **预算(逐字节沿用,弱模型不加料)**:
  - T2v4:`per_round` / 3 轮 / 36 调用 / 120 命令 / 20 文件 / 1800 行 /
    45min / 600k 读入 / 60k 产出
  - T3v5:`per_round` / 3 轮 / 45 调用 / 150 命令 / 25 文件 / 2500 行 /
    75min / 800k 读入 / 80k 产出
- **成本封套(最坏)**:T2v4 单发 1.8M 读入 / 180k 产出;T3v5 单发
  2.4M 读入 / 240k 产出;**计划 4 发合计最坏 8.4M 读入 / 840k 产出**,
  墙钟最坏 4 小时(不含装配与重放)。**运行上限 8 发**(计划×2)。
- **发前卫生门(T3 必做)**:七族 `$TMPDIR` 残留清扫
  (`rp_apply_assist_*`、`offerclaw-apply-*`、`offerclaw_apply_assist_jobs`、
  `offerclaw_apply_assist_artifacts`、`browser-use-user-data-dir-*`、
  `browseruse-*`、`browser-use-downloads-*`)+ pkill 浏览器残留;
  修复轮内自产残留不清。KB 指纹批前后各一次。
- **逐发人工取证(order-38 教训,继续执行)**:每发落账后、下一发发射
  前,人工磁盘取证该发适配补丁(T3:browser_use import 在场性 +
  nested_meter 密度;T2:R12 实质审查)——系统 verdict 不作放行依据。
- **停点**:四发跑完 → 合并报告(结果表 + P1-P4 逐条核对 + 逐败归因 +
  可比性声明)。**harness 缺陷 → 停 → 修 + 钉死 + 本批作废重预注册 →
  复测**;**模型弱点只记录不现场改**(§39/§38.2)。
- **红线**:False Pass / 泄漏 / 未批准写回 / 主目录被动 = 0,任一非零
  即刻停批。全发入账不挑选。

## 批次纪律

批内禁改任务包;Safety/Integrity 一次即修但本批作废重预注册;不同
harness_commit 不互比;`batch` 字段写 `T2v4-T3v5-RERUN-20260812`(非
EXPLORATORY —— 本批是正式预注册批次,计入闸门)。

harness_commit(冻结):`a099e1e`(含 H1-H4 反馈层 + 红绿守卫修复;
红绿 10/10 逐节点、变异闸门 20/20、全量 488 tests / 0 failures)。
