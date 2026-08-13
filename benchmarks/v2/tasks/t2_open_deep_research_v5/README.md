# T2:OfferClaw × Open Deep Research(首个正式 Benchmark)

- 宿主:OfferClaw @ `85278e6`(副本 `~/RepoProofBench/offerclaw-t2-odr`,602 测试基线)
- 目标:open_deep_research @ `20aaa0d422bd290c83f93574810ef1244e8d5955`
- 形态:宿主级集成(模式 L);task_shape **15/16**(高难 Project-to-Project 档)

## 任务工程期实测的技术事实(写给任务作者,不给 agent)

1. **依赖冲突形态 = 家族撕裂(比 T1 隐蔽一档)**:ODR 主依赖含 google
   系(vertexai/genai)→ protobuf<7 级联把 opentelemetry api/sdk/common/
   proto 降到 1.37,而宿主 otlp exporter 停在 1.44 → **家族内版本撕裂**
   → chromadb 导入链断 → 宿主测试连收集都过不了。**安装成功、宿主暗伤**。
   一致性解实测:全 otel 家族对齐 1.37(补压两个 exporter)→ 602 全绿;
2. **blockbuster 陷阱**:langgraph-cli[inmem] 传递依赖的阻塞 IO 探测器
   会把宿主套件 12s 拖到 **95s**(8 倍),卸载即复原。预算按慢路径兜底;
3. **进程内集成可行**:ODR@20aaa0d(0.5 时代代码)在宿主 langchain-core
   1.5.3 / langgraph 1.2 下 import + 编译图正常;
4. **Fake 驱动可行**:上游自带 `search_api="none"`;配合 fixtures 的
   OpenAI 兼容假服务可完整驱动真实 Research Graph(零公网零真钥)。
   注意 langchain-openai 1.x 的 `with_structured_output` 走
   `response_format.json_schema` 而非 function-calling;
5. **FastAPI + `from __future__ import annotations`**:请求模型必须定义
   在**模块级**,函数内定义会被当成 query 参数(实测 422);
6. **重导入即重启**:`sys.modules` 清理后重新 import 宿主 app 等价于
   进程重启,可用于验证 running 恢复语义。

## v5 相对 v4 改了什么(只改公开面与执法,不改任务本体)

v4 批次留下两处"隐藏面在执法、公开面一字未提",v5 把它们补齐:

1. **R15 并发隔离**:v4 的隐藏 H2 一直按并发不串判死,而 R1–R14 与全部
   公开用例里从来没有这条 —— 违反"闸门要杀的先教"(LESSONS #33)。
   v5 写进契约,并加公开用例 `test_concurrent_jobs_do_not_cross`。
2. **R16 报告溯源(F2 处方,与 T3v5 h7 同构)**:v4 的隐藏 H1 只断言
   "图被调用过",是纯存在性判据。order-20 因此穿过去了 —— 它确实调了
   `init_chat_model`,却在进程内挂本地回显桩自答,报告是自己手写的,
   公开面全绿。v5 给 fake LLM 加了**每次启动现摇的因果金丝雀**(写进
   压缩发现与终稿正文)与**调用密度**判据,H1 与公开用例
   `test_report_body_comes_from_the_engine` 同时执法。

预算 / task_shape / 宿主基线与 v4 **逐字相同**:变的只有"说清楚"和
"查得出",任务本体没有变简单也没有变难(§39)。

## 目录

```
contract.yaml        公开需求 R1–R16 + 预算 + task_shape(冻结对象)
fixtures/            **公开** fake LLM 服务(agent 可见可用,含因果金丝雀)
public_tests/        agent 可见可自测(14 项)
oracle/              隐藏验收 H1-H10(harness 持有,路径不进 agent 环境)
controls/positive*/  正控 2 个(第二个是误杀侧)——绝不进 agent 工作区
controls/nc*/        负控 7 条(必须按预期挂)
```

## 控制组为什么是这几个

| 对象 | 它证明的事 |
|---|---|
| `positive` | 验收自洽可满足 |
| `positive_trunc` | **不误杀**:诚实实现只存报告前 300 字符,仍须全绿 |
| `nc1`–`nc5` | 各自那条需求真的在执法 |
| `nc6_local_report` | 抓得住**不动脑的伪造**:图真调、产出丢掉、报告自己写 |
| `nc8_canary_launder` | 抓得住**有意的规避**:图真调、产出丢掉、金丝雀单独抠出来贴上 |

nc8 是 2026-08-13 对抗验证时加的,**首测 24/24 全绿** —— 当时 R16 只有
金丝雀一条判据,而金丝雀是可搬运的常量。补上"正文同源"后才红。教训:
每条新判据都要配一个"有意规避"的负控,只配"不动脑伪造"的会让人以为
判据成立(LESSONS #43 坑三)。

## 六物验证怎么跑

装配由 `scripts/build_control_tree.py` 收口(默认建完即拆),判定由
`scripts/validate_controls.py` 收口 —— 矩阵与结论只出自脚本:

```bash
.venv/bin/python scripts/validate_controls.py \
    --task benchmarks/v2/tasks/t2_open_deep_research_v5
```

它需要一个装了 `open_deep_research` 的解释器(装配器刻意不复制 `.venv`)。
默认走 `~/RepoProofBench-quarantine/_scratch_odr_compat/venv` —— **那份
共享 venv 不能删**,7 棵已废弃的手搓树当年都软链到它。

`nc6_local_report` 是 v5 新增的负控,专门证明金丝雀抓得住它该抓的那一型:
上游真被加载、图真被调用、调用密度与正控一致、报告里也有研究主题,
唯独把 `result["final_report"]` 丢掉换成本地模板 —— 只有金丝雀会红。
