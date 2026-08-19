# DSH 集成线全程报告(2026-08-17 → 2026-08-20)

> 范围:官方 DeepSeek Harness(DSH)minimal SDK 集成线从 ADR 到批毕关闭的
> 全部过程与结果,含 E1 桥接批两代实录、机制发现、直白结论与后续规划。
> 事实源:git 4848c78..34c6b20、`benchmarks/v2/runs.jsonl`(207 行)、
> `benchmarks/v2/preregistrations/E1-DSH-MINIMAL-BRIDGE-1-prereg-20260818.md`
> (含附录二/三)、`docs/evidence/` 各证据件。本报告只汇总,不新设判据。

---

## 0. 一页结论(直白版)

**进展**:集成线阶段 0-8 全程完结(批关闭提交 34c6b20)。DSH 作为
**不可信 AgentBackend** 完整接入:供应链断网可重建、独立进程 worker、
事件适配可对账、隔离负控落钉、profile 晋级 qualified(DQ-SDK-1)、
E1 桥接批 12 计分发跑毕。裁决平面全程留在仓内,DSH 的任何输出
(final_response / finish_reason / 会话 JSONL)从未产生过一次 PASS。

**引入 DSH 后 DeepSeek 表现如何**:没有变好。同任务同预算下
H0(自研 mini-swe 臂)×pro 2/3 通过,H1(DSH 臂)×pro 1/3;flash 两臂
0/3。n=3/格,不构成显著差异,但至少可说:**DSH 没有带来提升**。主导失败
模式(8/12)与臂无关 —— 修好全部 5 道 delta 却砸了一道隐藏邻位回归测试
(`test_multiple_pivoted_sources`),公开面 1150 全绿于是自信提交。这是
模型能力边界,不是 harness 能修的(修 = 泄答案)。

**原本的 GPT 有没有提升**:**无数据**。整条线 17 发真跑全部是
DeepSeek(pro/flash);GPT 本地端点 8/18 起 503,今日 12:00 后才恢复,
按用户指示不补测。"有没有提升"诚实答案 = 没跑过,不知道。

**要不要直接引入 DSH 部件**:不引部件,引设计。DSH 的上下文经济性来自
**有状态服务端会话**,在我们的无状态 chat 端点上复制不了;可搬运的杠杆是
**send 侧历史折叠**,而这件东西仓里本来就有(S2′ 滑动窗口)。P0(本代)
已把它对 DeepSeek 数据的送达缺口修掉并做完隔离加固,见 §8。

---

## 1. 目标与信任模型

指导报告(20260817)的立项:把官方 DSH 当作一个**可插拔的执行平面**接进
RepoProof,回答"换掉自研 agent 循环,判决结果会怎样"。三条不动的线:

- **裁决平面冻结**:PASS/FAIL 只出自仓内 oracle + 独立终局验证 + 干净重放;
  DSH 是被测对象,不是量具的一部分。
- **不可信执行**:DSH worker 独立进程、封存 runtime、预算 watchdog、
  进程组刀;它说什么都只是证据,不是结论。
- **台账分池**:backend 轴(mini-swe / dsh)进指纹与代际标签,B 族代际
  自立,不与 E0/E1 执行器代际互比。

## 2. 阶段时间线(0-8,全部完结)

| 阶段 | 内容 | 关键提交(日期) |
|---|---|---|
| 0 | ADR:DSH minimal 作不可信 AgentBackend | 4848c78(8/17) |
| 1 | 供应链固化:九枚钉死物封存成 runtime,断网可重建 | a4cb97a |
| 2 | agent backend 轴落进指纹与台账 | 4efe2e1 |
| 3 | dsh_worker 独立进程最小闭环首次真跑通 | ace960e |
| 4 | 事件适配 + usage 终态权威 + 预算 watchdog + 进程组刀 | 2371d0f |
| 5 | 隔离与安全负控十项落钉(证明声明过的边界,不表演没有的沙箱) | 5ba74c0 |
| 6 | LLM 线协议实测 + 金丝雀 C1-C15 + profile 登记/晋级 candidate | b478aa6→84b766a |
| 7 | DQ-SDK-1 资格批:`rt-dsh-minimal-0.1.0rc6-v1` 晋级 **qualified** | 6c88ea5→0396153 |
| 8 | runner 侧 B-dsh 集成 + E1 桥接批(冻结→代 1 停批→代 2 批毕) | 007a422→34c6b20(8/19) |

全程变异闸门伴随:237 → 257 枚变异体,每个冻结点全捕零逃逸。

## 3. DQ-SDK-1(阶段 7):backend 资格

- 5/5 运行恰好打满零加发;G6=2 模型(v4-pro/v4-flash)、G6b=1 诚实通过
  (发 4 flash PASS_ADAPTED 9/9 + 干净重放 PASS + fidelity DELIVERED)、G7 清。
- 批中打出并钉死两处**仪器**缺陷:①回执块落账 NameError(发 1/发 2 废行,
  预注册附录四);②dsh 发次台账 runtime_profile_id 回落契约缺省(G6 恒读
  0)—— 修法都是结构性的(纯函数 + 准入组合指纹),各带回归钉与变异体。
- 工程发现:**请求轴是 DSH 臂的绑定约束** —— 四次真跑逐发 logical_requests
  = 91 撞 90 上限;DSH 请求重、token 轻(≈55-77K in/发,对 mini-swe 的
  0.55-1.7M)。这直接驱动了 E1 的预算映射设计。

## 4. E1-DSH-MINIMAL-BRIDGE-1(阶段 8):两代实录

**冻结**(efbf076):双模型都进(用户决策,模型作分层因子),n=3/臂/模型
共 12 计分;四轴等值预算,calls 轴 90→500 作两臂同值的逃逸后备;
API 窗口规则 14:00 硬止;开跑前置门 = 变异证据 257/257(430bcd5)。

**代 1 停批**(a6e3a52):序 2 pro(run 130403)开局 `cd /` 自毁 cwd 后
全盘寻路,把 bench **母树**误认作工作区,在里面建 venv、跑测、改
lineage.py。判决面诚实(判决工作区 patch 0 字节,FAIL = 零适配基线),
但母树被污染 → 停批。收口:母树幂等重建(host_digest 与建包时同值)、
发车摘要绊线 `scripts/check_host_digest.py` 制度化(发前不符拒发/发后
归因本发)、答案泄漏轴三发排除(封存池 d5-hunt 零读取)、机制判读作废
收回。结构性隐患入册(附录二):worker 以本机用户身份跑,母树可写 ——
登记为代际工程(P0 已落地,见 §8)。

**代 2 批毕**(34c6b20):窗口重开后照冻结原序整段重跑,01:54-07:49
十二发 12/12 首试成功、零缺陷重跑、绊线 24 道全绿。

| 格 | 结果 |
|---|---|
| H0(mini-swe)× pro | **2/3**(PASS 9/9 ×2;FAIL 4/9 = 零适配,探索到贴墙才交) |
| H1(dsh)× pro | **1/3**(PASS 9/9 + replay;FAIL 8/9 ×2) |
| H0 × flash | 0/3 |
| H1 × flash | 0/3 |

H1 fidelity 双闸绿:送达 6/6 = 100%,attribution 全 ok —— 输的发次输在
模型,不是桥没送到。主导失败 8/12 = 修好全部 5 道 delta 但砸
`test_h2_no_regression_broken`(隐藏邻位测试,公开树里没有),与臂无关。

## 5. E5 机制发现:两臂各贴不同预算轴

同一四轴等值预算下:

- **H1(dsh)六发全自然完成**:106-183 逻辑请求(越旧 90 墙、无一近
  500),输入 53-74K tokens/发;
- **H0(mini-swe)六发全贴 in-token 墙**:1.72-1.76M/1.8M(96-97.5%),
  calls 仅 52-61。

这是"换循环 = 换消耗形状"的直接证据。根因(代 2 轨迹逐条实测):H0 的
无状态 chat 端点**每次调用重发全部历史**,单发累计输入 1.8M 的真身是
~55 次调用 × 平均 ~33K 的重复历史;DSH 的经济性来自有状态服务端会话,
在这类端点上不可复制。判读边界:单任务、seen、n=3 —— 不读作 DSH 优劣。

## 6. GPT 的位置(诚实划界)

整条集成线 **零 GPT 发次**。E 轨(8/14 关闭)的三条红线措辞照旧有效:
不得写"执行侧在本仓无靶子"、不得写"DeepSeek 报告核心建议不适用"、
不得把"未获得暴露"说成"不存在"。本线恰好反向印证了第三条:S2′ 在 GPT
两臂上 TREATMENT_NOT_DELIVERED / LOCAL_ADVERSE_EFFECT,而 E1-DSH 代 2 的
DeepSeek 轨迹离线重放证明**暴露条件在 DeepSeek 路径上存在且巨大**
(全历史重发吃掉 96-97.5% in-token 预算)。GPT×DSH 若要测,需先建协议
适配层(DSH worker 说 DeepSeek 协议)—— 未建,不在本线范围。

## 7. 暴露的问题(全线汇总)

1. **越区结构性隐患**(代 1 事故):执行面无读写硬隔离 —— P0 已收口(§8)。
2. **H0 上下文经济性**:全历史重发把预算烧在重复输入上 —— P0 已修送达
   缺口,在线消融待批。
3. **回归邻位失败模式**(模型侧):修 delta 砸隐藏邻居,8/12 主导。
   harness 无法在不泄答案的前提下消除;可作后续能力评测的判别性靶点。
4. **登记欠账**:full-runner×dsh 假端点常驻钉(批后补);
   instrumentation_fingerprint 不覆盖 runner/host_guided.py(已知局限)。

## 8. P0 实施记录(2026-08-20,本代,零 API)

用户指令"完成 P0"= mini-swe-v2 观测管理改造 + 资格件;顺手把越区硬隔离
做进同一代际。全部落地:

**A. 观测管理(window-v1.1)**
- 机制沿用仓内既有 S2′ 滑动窗口(`context_projector.project_window`,
  折窗口外旧读取型结果,执行型一票否决),接线本就在
  `TokenBudgetedModel.query()` 的模型缝上(先投影后记账,轨迹保全history)。
- 离线重放(零模型,`scripts/replay_projection_dsh_h0.py`,自证 4 条 +
  偏移对齐审计零错位)发现 v1 分类器在 deepseek-v4-flash 两发**零激活**:
  flash 惯用 `cd /绝对路径 && sed …` 带路,链首段是 cd,读取白名单永不
  命中 —— 与批 14 gpt-5.6 链式零激活同构,分类器覆盖缺口。
- **v1.1 = 剥链首 cd 导航段 + pwd 入读取集**,折叠规则与安全边界一字未动;
  版号同源(`WINDOW_POLICY` 常量 → manifest 与 context 指纹),
  代际标签自动派生离开 E0。
- 证据(`docs/evidence/projection_exposure/replay-E1-DSH-H0-window-v11.json`):
  六发 H0 激活 4/6 → **6/6**,总输入(估)节省 **-19.1% → -26.7%**,
  零激活两发修到 -18.8% / -24.8%,v1.1 无一发比 v1 差。
- 旋钮 `REPOPROOF_CONTEXT_PROJECTION` 缺省 **off** = E0 逐字节不变;
  **在线真模型资格发未跑,待用户 API 授权**。

**B. 越区硬隔离**
- **母树锁写**:`scripts/lock_bench_hosts.py`(lock/unlock/status),三宿主
  host+wheelhouse 全树 749 条去写位(目录也锁 —— 代 1 的越区是建新文件,
  只锁文件锁不住);`_digest_tree` 只算路径+内容,锁前后 host_digest 同值
  (实测绊线三宿主全绿)。
- **快照落权归一**:`prepare_host_snapshot` copy2 后补 u+w(其余位原样)——
  锁写的母树照常出可写快照(端到端探针:357 文件零只读,写入成功)。
- **绊线扩面**:`check_host_digest.py` 发车双面执法 = 摘要一致(检测)+
  全树零写位(预防),任一红即拒发。
- 重建包工序:先 `unlock` → prepare → `lock` → 绊线验证(脚本内置提醒;
  prepare_hb1_hosts.py 按零触碰决定未改,锁着跑会响亮失败)。

**C. 资格件**:钉死测试 +6(cd 链可折/cd+pytest 不折/兜底 cd + 分号链/
引号不剥/版号字面量钉/快照落权),变异体 +3(M90a/b/c,共 260),
全量套件与变异门见收口提交。

## 9. 规划(P0 之后)

- **P0 收尾(待批,一发真过)**:v1.1 在线真模型资格发(window 旋钮开,
  单发验证 projection.applied 事件与台账指纹),需 API 授权。
- **P0.5(待批)**:GPT 基线批 —— 本地端点已恢复(8/20 12:00 后),
  先补 GPT×H0 基线,才谈得上"GPT 有没有提升";GPT×DSH 需协议适配层,
  另行立项。
- **P1(登记在册)**:full-runner×dsh 假端点常驻钉;E1 任务面扩 click
  两宿主(可出题池 3 里的另外两个);E1-S2(window 开)对 DeepSeek 的
  在线消融设计(预注册先行,E0/E1 分池永不互比)。

---

*本报告为汇总件;与预注册/台账冲突处以后者为准。*
