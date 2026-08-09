# T1:OfferClaw × fastapi-mcp(校准任务)

- 宿主:OfferClaw @ `8e59a18f`(副本 `~/RepoProofBench/offerclaw-t1-fastapi-mcp`)
- 目标:fastapi_mcp @ `e5cad13cabfc725bbcb047e526816d887d96da62`
- 形态:宿主级集成(模式 L 执行);**不经样例向导**,手写任务工程

## 任务工程期实测的技术事实(写给任务作者,不给 agent)

1. **依赖冲突真实存在(难度主来源)**:pinned commit 的 fastapi_mcp
   声明 `mcp>=1.12.0`,但 mcp **2.0.0 破坏了 `Server.__init__` 签名**
   → 直接 `pip install` 会在构造 `FastApiMCP` 时 TypeError。必须钉
   `mcp<2.0`(实测 1.29.0 可用)。agent 需自行诊断并解决。
2. **Streamable HTTP 需要 lifespan**:`TestClient(app)` 直用会
   `RuntimeError: Task group is not initialized`;必须
   `with TestClient(app) as c:` 触发 lifespan。
3. **握手序列**:initialize(取 `mcp-session-id` 响应头)→
   `notifications/initialized` → `tools/list`(带 session 头)。
4. **白名单机制**:`FastApiMCP(app, include_operations=[...])` 实测
   有效(未列入的 operation 不出现在 tools/list)。
5. **Schema 自动生成**:`inputSchema` 由 FastAPI/Pydantic 派生,
   因此"手写第二份 schema"可被 schema 漂移用例抓住。
6. 依赖版本零冲突面:fastapi/pydantic/starlette/httpx 与 OfferClaw
   完全一致,仅新增 mcp 系。

## 目录

```
contract.yaml        公开需求 + 预算 + task_shape(冻结对象)
public_tests/        agent 可见可自测
oracle/              隐藏验收(harness 持有,路径不进 agent 环境)
controls/positive/   参考实现(证明验收自洽可满足)——绝不进 agent 工作区
controls/nc*/        负控(必须按预期挂)
```
