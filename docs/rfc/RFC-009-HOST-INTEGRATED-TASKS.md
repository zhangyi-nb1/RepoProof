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

---

## 六、v2 修订(2026-08-09):宿主改为 OfferClaw(用户方案 v2 评估采纳)

**变更**:废弃 fastapi-template 宿主线(其 Postgres 自举正是 v1 的
[USER-DECISION-1],v2 用"本地健康项目"直接消解);主宿主固定
**OfferClaw @ 8e59a18f**(已核对:本地 HEAD 即该 commit;metrics
事实源 53 路由/594 pytest/3538 chunks 与方案引用一致)。梯度改为:
T1 fastapi_mcp(校准)→ T2 Open Deep Research(首个正式 Benchmark)
→ T3 browser-use(副作用 Harness)→ T4 Feature Transaction(回滚
专项)。四个 pinned commit 全部核实真实。

### 6.1 对用户方案 v2 的修正(评估发现的不合适处)

1. **前提工程仍未解,且比 v1 更重**:OfferClaw 依赖面含
   sentence-transformers(→torch)、chromadb(含 3538 chunks 持久
   数据)、playwright——全容器化 = 多 GB wheelhouse + Chroma 数据
   快照工程,T3 还要浏览器进容器。方案默认"UI 填了就能跑"不成立,
   执行架构是新的第一决策(见 6.2);
2. **阶段 A 过重**:Feature Transaction Schema / Rollback Readiness
   Gate 全量前置违反 problem-first——Phase 0 只做最小集(执行后端 +
   宿主快照排除规则 + 主目录护栏 + runs.jsonl 事实源),事务图等
   T1/T2 出证据后按 §38.2 触发;
3. **每轮跑 594 全量测试的成本未测**:Host Baseline Gate 首跑要产出
   套件耗时,回归可能需要"每轮子集 + 终验全量"分层(冻结前定);
4. **T3 复杂度被低估**:browser-use 自带嵌套 agent(运行时也要模型)
   + mock 招聘站 fixture 工程,列为远期,不进前两批;
5. metrics 数字为字符串型("594"),对账工具须容忍类型。

### 6.2 [USER-DECISION-4] 执行架构(取代已消解的 DECISION-1)

- **模式 L(推荐,Phase 1)本地 Worktree 执行后端**:每 run 全新
  worktree + 专用 venv(按宿主 requirements 构建一次后克隆复用);
  agent 命令经既有 argv 策略过滤后在 worktree 内本地执行。环境与
  用户本地 100% 一致、Chroma/Playwright 零工程;代价 = 隔离从容器
  降为策略层(如实记录为临时信任模型弱化,硬化项排队);
- **模式 D(后续硬化)全容器**:最强隔离;代价 = 多 GB wheelhouse、
  数据快照、浏览器进容器,工程量数周级。

### 6.3 OfferClaw 保护机制栈(用户红线,五层)

1. **主目录硬护栏(新增机制,立即实现)**:向导/apply/一切写路径
   拒绝命中 `~/Desktop/XIANGMU/offerclaw`(真实开发目录)——硬编码
   黑名单 + 测试钉死;RepoProof 只接受 ~/RepoProofBench/ 下的副本;
2. **副本纪律**:每任务独立 clone(本地克隆自主仓库,只读源)、
   detach 在 8e59a18,每 run 新 worktree,用后可弃;
3. **Host Baseline Gate**:run 前 doctor/verify_pipeline/pytest/
   verify_docs 全绿,否则 HOST_BASELINE_UNHEALTHY→BLOCKED(0 修复
   预算消耗),宿主故障绝不算 Agent 失败;
4. **既有写回防线**(E2 已实测):三级确认 + 指纹漂移门 + preimage
   备份 + 回滚账本 + 崩溃中途自动回滚;
5. **数据与密钥**:宿主快照排除清单(.env*、*.lock、gap_store 等
   运行态文件);测试只用合成 Persona/JD/简历;`.env.local` 永不进
   workspace/trace/bundle。

### 6.4 阶段计划(操作序)

- **Phase 0(RepoProof 工程,本 RFC 实施)**:模式 L 执行后端 +
  主目录护栏 + 宿主快照/排除 + provenance 检查最小版 + benchmarks/
  v2 runs.jsonl;
- **Phase 1(T1 校准)**:Host Baseline 首测(定套件耗时与容差)→
  T1 任务工程(手写 oracle/正负控)→ GPT-5.5 + DeepSeek 各 1 次
  pilot(随机序)→ 双一轮过则 T1=CALIBRATION_ONLY;
- **Phase 2(T2 正式)**:三模型 pilot → 有区分度补齐 3×3;
- **Phase 3+**:T3 / T4 按方案,前批稳定后启动。
- 纪律沿用方案 §31-39/§49(批内禁改 harness、Safety Bug 修复即
  批作废重预注册、n<3 不排名、False System Pass=0)。

### 6.5 执行架构论证记录(模式 L vs D,面向技术评审与面试问答)

**设计初期原则站在哪边**:诚实回答——**模式 D**。设计基线文档把
"临时 Docker Workspace"列为 MVP 基础层,"Proof"的定义含干净重放。
模式 L 是**有记录的、保接口的、限期的降级**,其合法性同样来自设计
文档自身:§12.2 明文允许"同接口临时降级=进度降级,不改变定位"
(MySQL→SQLite 先例),P1 problem-first 禁止为无真实失败的目标先付
数周基建。且设计文档 §11.1 原文:Docker 从来不是恶意代码沙箱,
任务分布=人工准入的公开可信仓库——L 损失的是纵深防御的一层,不是
从安全到不安全的跳变。

**模式 L 弊端(如实)**:①agent 命令在宿主机执行,argv 策略成为
最后防线,无内核级兜底;②复现性降级为"同机级"(新 worktree+新
venv 可排除工作区污染,排除不了机器状态),他人无法异机复现;
③macOS/arm64 与 Linux 容器的平台差异;④venv/模型缓存跨 run 共享
的灰区;⑤资源限制靠计时器而非 cgroup;⑥需新建本地执行后端并重新
钉死证据采集等价性。

**模式 D 好处(对称)**:内核隔离兜底、封闭复现(digest 镜像+
wheelhouse)、平台一致、cgroup 硬限、销毁即净、对外声称力度最强。

**L 如何保护 OfferClaw 主目录(六层,与容器无关)**:①主目录硬
护栏黑名单(一切写路径拒绝命中真实开发目录,测试钉死);②副本
纪律(本地克隆只读源、每 run 新 worktree、副本可弃);③文件写入
路径策略限定 worktree 内;④argv 命令过滤 deny-by-default;
⑤**run 前后主目录 tree-hash 对账**——被写必当场发现并停机;
⑥主目录自身 git 历史为最终保底。诚实边界:L 给出的不是"不可能
被写"而是"多层防线把概率压到极低 + 被写必被发现 + 可恢复";
容器的保证同样依赖挂载配置正确(挂错目录一样能写坏),两种模式下
真正保护主目录的都是路径纪律+护栏+对账,容器只为"agent 任意命令"
多加一层内核兜底。

**默认模式与证据分级制度**:默认**模式 L**(探索/产品阶段);
**凡进入对外公开声称的 benchmark 结论,须在模式 D 复验,或如实
标注证据等级**。runs.jsonl 记 `execution_backend` 字段:L 级 =
machine-reproducible,D 级 = hermetic-reproducible,**不同等级不
互比不互算**。核心可信度机制(隐藏 Oracle 不给 agent、独立验证、
Completion Gate、False System Pass=0)与执行后端无关,在两种模式
下等强——RepoProof 的反假完成叙事不依赖容器,容器服务的是复现性
与安全纵深。
