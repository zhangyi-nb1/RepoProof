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

## 目录

```
contract.yaml        公开需求 21 条 + 预算 + task_shape(冻结对象)
fixtures/            **公开** fake LLM 服务(agent 可见可用)
public_tests/        agent 可见可自测(10 项)
oracle/              隐藏验收 H1-H10(harness 持有,路径不进 agent 环境)
controls/positive/   参考实现(证明验收自洽可满足)——绝不进 agent 工作区
controls/nc*/        负控 5 条(必须按预期挂)
```
