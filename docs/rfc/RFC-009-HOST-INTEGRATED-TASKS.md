# RFC-009: Host-Integrated Task Shape(L2+ 工程级集成任务)

- 状态:**草案,待用户决策后实施**
- 依据:E2 结论(单函数 seam 对 2026 代模型一轮即解,探索价值收敛)
  + 用户采纳的《渐进式复杂任务测试与 Harness 演进方案》(外部方案,
  已核实其三个 pinned commit 真实存在)
- 升级路线:SlowAPI(校准)→ PyCasbin(首个正式 Benchmark)→
  APScheduler → FastAPI-MCP → Open Deep Research(Capstone)
- 固定宿主:fastapi/full-stack-fastapi-template @ `70461bb9`(已克隆
  至 ~/RepoProofBench/t1-slowapi 并 checkout 验证)

## 一、外部方案评估结论(2026-08-08)

**方向采纳**:难度梯度、Hidden Oracle 设计、Negative Controls、预算
表、两阶段校准、Round Telemetry、Upstream Provenance、benchmarks/v2
组织、"一批跑完才改 Harness"纪律——全部与本项目既有纪律同构,采纳。

**三处必须修正的盲区**:
1. **前提工程缺失**:方案假设"UI 填需求即可跑",but 当前 guided
   流水线 = 样例编译 seam(单函数、宿主不进容器)。L2+ 需要宿主
   快照进容器、多文件可写边界、手写 oracle 接线——这是本 RFC 主体,
   方案的 Day1/Day2 时间表不现实;
2. **宿主数据库耦合未解**(已实证):config.py `PostgresDsn` 硬类型
   + db.py import 时建 engine + conftest 直连真库。单容器离线环境
   无 Postgres——见 [USER-DECISION-1];
3. **预算解冻需重冻结纪律**:方案预算(24-45 调用/800-3000 行/
   30-90min)超当前默认(20/400/30min),合同字段支持,但每任务
   冻结前定值、冻结后不改,历史任务不回溯。

## 二、任务形态定义(L2+)

```text
容器内:
/host/        宿主项目快照(固定 commit;editable_zones 按任务白名单,
              如 backend/** 可写、frontend/** 禁写;patch 预算约束)
/upstream/    目标仓库快照(只读,固定 commit)
/oracle/      隐藏验收(手写 pytest,agent 不可见不可写,hash 守护)
/adaptation/  改动台账区(对 /host 的 patch 集 + 新文件清单)
```

- 能力验收 = 在集成后的宿主上跑手写 hidden oracle(TestClient 级);
- 宿主回归 = 宿主自带测试套件必须继续通过;
- 公开测试 = 任务作者手写、随宿主可见,agent 可自测;
- **不走样例编译器**:L2+ 任务包由任务工程(手写 contract/
  RequirementSpec/oracle/controls)产出,复用 benchmark 时代冻结
  管线;UI 样例向导仍服务样例级任务,两形态并存。

## 三、需实施的改动清单(按依赖序)

1. 执行层:宿主快照挂载 + 可写边界策略(policy 按 editable_zones
   放行 /host 白名单写入,frontend 等禁区拦截);
2. 宿主环境:依赖 wheelhouse 扩展(宿主 backend 全依赖)+ DB 方案
   ([USER-DECISION-1]);
3. 验证层:capability/regression 命令在 /host 上执行的接线;
4. Provenance 检查(方案 §22):按任务验证真实 import/实例化目标库
   (进 PolicyVerifier 或独立 ProvenanceVerifier);
5. benchmarks/v2/ 数据组织 + runs.jsonl 字段(方案 §20;round
   record 现有字段已覆盖 §21 大半);
6. Failure Taxonomy 扩容(方案 §19,按"真实出现才收录"纪律,只预
   留命名空间不预制 Recovery);
7. UI Benchmark Dashboard(后置,P2)。

## 四、用户决策点

**[USER-DECISION-1] 宿主数据库方案**:
- A. 容器内装 Postgres(apt,install 阶段联网):宿主零改动;代价 =
  apt 版本漂移伤确定性、镜像语义变重、replay 依赖 apt 源;
- B. **(推荐)** 维护披露的 bench-host 基线:template@70461bb +
  一个最小"DB 可配置化"补丁 commit(PostgresDsn→AnyUrl,测试走
  SQLite),固定该 fork commit 为宿主基线。确定性/离线重放/单容器
  全保留;代价 = 宿主是"模板衍生 fixture"须如实披露,且 Alembic/
  UUID 列需 SQLite 兼容性审计(实施时做);
- C. docker-compose 双容器:最忠实生产形态;代价 = 执行后端大改,
  与单容器信任模型冲突,成本最高。

**[USER-DECISION-2] L2+ 预算**:采纳方案 §15 数值(SlowAPI:3 轮/
24 调用/800 行/30min;PyCasbin:3 轮/30 调用/1200 行/45min…)?
成本提示:PyCasbin 3 模型×3 次×45min 上限,模型费用与时长显著高于
样例级任务。

**[USER-DECISION-3] 校准顺序**:按方案先 SlowAPI 校准(强+弱各 1 次,
均一轮过则弃)再 PyCasbin 正式;或跳过 SlowAPI 直接 PyCasbin?

## 五、口径纪律

- README v0.1.0 统计口径不动;v2 结果只进 benchmarks/v2 事实源;
- 校准 run 不入模型排名;n<3 只作方向性案例;
- False System Pass = 0 为硬目标;Hidden Oracle 零泄漏(测试钉死);
- 不同 Harness 版本的运行不直接比较(harness_commit 入 runs.jsonl)。
