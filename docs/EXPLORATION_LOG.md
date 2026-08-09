# 探索台账 — 任务 × 模型 × Harness 演进(复盘/面试素材)

> **常设工作流(用户 2026-08-08 确立,长期贯彻)**:用户在 UI 自选
> 仓库与能力,逐任务在多个模型上运行;协作 AI 负责分析各模型的
> 失败原因与行为差异 → 由真实失败驱动 harness 完善 → 修复并测试
> 钉死 → 记入本台账。目标:在模型不那么强的前提下,用 harness
> 机制逐步提高任务成功率与结论可信度。每条目 = 任务 / 各模型结果 /
> 异常与根因 / 由此产生的 harness 改动 / 遗留问题。

## E1 · 2026-08-08 · adopt-dateparser-guided-v1(多语言日期解析,10 样例含 ERROR 陷阱)

**设计意图**:大库(多依赖含 C 扩展 regex)、多语言样例(英/法/中/俄)
使重写不可行、`hello world => ERROR` 复刻历史 CONTRACT_REQUIREMENT_
OMISSION 陷阱、MDY/DMY 歧义对惩罚天真解析——期望触发 gpt-5.5 多轮修复。

**结果(磁盘事实)**:

| 时间 | 模型 | 类型 | 判定 | 调用 | 读入 tokens | AI 用时 |
|---|---|---|---|---|---|---|
| 18:14 | — | 装配基线·无AI | FAIL 0/11(预期) | — | — | — |
| 19:06 | gpt-5.5 | 单次 | **PASS_ADAPTED** 11/11 | 5 | 11,253 | 41.9s |
| 19:07 | gpt-5.6 | 单次 | PASS_ADAPTED 11/11 | 5 | 21,432 | 77.3s |
| 19:12:28 | deepseek-v4-pro | 单次 | PASS_ADAPTED 11/11 | 16 | 132,825 | 69.7s |
| 19:12:46 | deepseek-v4-pro | 单次 | PASS_ADAPTED 11/11 | 10 | 36,979 | 44.0s |

**用户报告的"异常"与真相**:用户感知"5.5 失败、5.6/deepseek 成功,
怀疑与执行顺序相关"。核查:**5.5 实际 PASS 且最省**;被当成"5.5
失败"的是 18:14 的**装配基线**(无 AI、预期必挂的对照运行),它混在
「你的运行」列表中与真实运行不可区分,用户按执行顺序对号入座导致
误判。运行之间共享的只有冻结任务包与只读 wheelhouse,**设计上无
顺序耦合**;唯一真实的顺序问题是并发锁竞态(下)。

**本条目揪出的三个真缺陷(全部已修,测试钉死)**:
1. 运行类型不可辨 → 列表/历史全面标注「装配基线·无AI(预期失败)/
   单次运行/多轮修复」;
2. 欢迎页快捷运行未传 guided → 四次"真实运行"全是单次,**多轮修复
   根本没武装**(这才是没看到多轮的原因)→ 欢迎页补开关,默认开;
3. 并发锁竞态:预检窗口(~30-40s)内 run 目录未创建,"最新目录=上次
   已完成运行"使产物优先判完成误放行第二次启动(两个 deepseek 重叠
   18 秒)→ 锁记录 started_at,产物须晚于启动时刻才算完成。

**行为观察**:同模型两次 deepseek 运行差异显著(16 调用/132k vs
10 调用/36k)——temp 0 下环境时序仍致轨迹分叉(与踩坑 #5 同类);
跨模型效率序:5.5(11k)< 5.6(21k)< deepseek(37k/133k)。

**遗留**:多轮修复在真实模型下仍未展开(本次因单次模式;下次同任务
勾选多轮重跑一次即可武装);任务难度对 2026 代模型仍偏低——下一级
难度 = 已有项目模式(真实宿主 + 回归约束)。

## E2 · 2026-08-08 · adopt-emoji-guided-v1(首个真实宿主 + 首次真实项目写入)

**新台阶**:宿主从空目录换成真实 Git 项目 notes_app(3 提交/2 模块/
3 测试);目标 = 走通「真实宿主分析 → 采用 → **真实项目三级写入**
→ 真实回归 → 回滚 → 复原写入」全链。目标仓库 emoji 钉 v2.9.0
(GitHub Tag 滞后 PyPI 2.15,期望值按 v2.9.0 逐一实测——inflection
教训的正向应用)。

**结果**:多模型全部一轮 PASS_ADAPTED(终验 gpt-5.4-mini:9 调用,
能力 7/7 含隐藏,clean_adoption 重放 PASS,trace 127 事件);写入/
回滚/复原在 notes_app 实测成功(apply 台账 runs/_apply/,宿主回归
3/3 绿,git 树仅多 adopted/)。**Gate E 真实项目写入停点正式解锁。**

**用户质疑"PASS 是不是真的"→ 磁盘审计**:adapter 为 4 行真实采用
(`emoji.demojize`,非样例硬编码);隐藏样例 agent 不可见仍通过;
重放在销毁重建容器中再次全过;冻结期负控(空实现)按预期挂。
结论:判定可信。真正的缺口是**体验层**——用户从头到尾没亲眼看到
能力运转(验证都在容器里)→ 遗留:结果页加「试一试」输入框(用
已 PASS 的 adapter 现场转一条);临时方案 = 宿主内 smoke 命令。

**"为什么所有模型都一轮到底"的结构性结论**:不是评判标准松(有
上述审计),是**任务形态天花板**——当前 seam 是"单函数 run(str)->str
+ 行协议样例 + 名库包装",2026 代模型(含 gpt-5.4-mini)对此形态
一轮即解。要让多轮/失败真实出现,需扩任务形态(RFC 方向):多函数/
多文件 adapter、结构化输入输出、宿主内联集成测试(agent 直面宿主
真实测试)、或行为含糊需迭代澄清的能力。**样例级小任务的探索价值
已收敛,E3 起进入形态扩展。**

**连带修复**:推荐答案 [:40] 硬截断切在句中 → 第一小句提取;第 4 步
验收样例上移紧挨其消费者(必答问题推荐引用样例,原布局迫使用户
先滑到底再滑回)。**遗留**:_apply 目录用 UTC 命名而 run 目录用本地
时间(不一致,待统一);「试一试」能力演示框。

**E1 补记(同日晚,guided 复测)**:用户开多轮开关三模型重跑——
deepseek(14 调用)、gpt-5.4(5 调用)、deepseek(7 调用)全部
`guided-repair` 模式 **第 1 轮公开 8/8 全绿 → PASS_ADAPTED**,多轮
机制已武装但无需展开;连 gpt-5.4 都一轮通过,确认该任务难度对
2026 代模型已到天花板。连带修复:修复过程页下拉名字序埋没(同坑
第三发,thefuzz 恒顶、新运行沉底,用户误以为"没有结果")→ 时间序
+「时间·模型·判定」标注;历史/回顾/修复三处列表全面增加**模型
型号列**(用户要求,取自预检记录);锁竞态案例写入
ENGINEERING_CASEBOOK 案例 1(面试复盘级)。

## 状态条目 · 2026-08-09 · 测试方案 v2 执行版定稿(阶段:Phase 0 未开始)

TESTPLAN-V2 执行版(docs/testplans/TESTPLAN-V2-OFFERCLAW.md)经独立
agent 对抗审核:**有条件通过,16 必改项全部落实**。审核最大战果 =
两个已在磁盘上成立的红线隐患:①本地 git clone 默认硬链接对象库,
T1 副本与 OfferClaw 主仓共享同一批 .git/objects 物理文件(改副本=
毁主仓)——已用 --no-hardlinks 重建并核验零共享 inode,主仓 fsck
完好;②副本 origin 指向主开发目录(git push 即写穿)——已移除。
两案入 CASEBOOK 候选。用户已批准执行版(2026-08-09)。**Phase 0 进度:① 主目录护栏+指纹
对账 ✅ 完成**(harness/host_guard.py:realpath+大小写不敏感+软链/
子路径/相对路径全拦截;apply/stage/rollback 三写入口无旁路接线;
UI 宿主路径就地拦截;指纹=工作树含 untracked+git refs 摘要,untracked
新增/内容改/refs 变动全报警,噪声目录不误报;钉死测试 5 项)。
**② LocalWorktree 执行后端 ✅ 完成**(execution/local_worktree_backend.py:
与 Docker 后端同形 start/exec/destroy/destroy_all;四条硬约束焊死——
护栏拒绝保护目录会话根、**假 HOME**(HOME/XDG/HF 全指会话内,一举切断
OfferClaw 那 4 处 `~` 访问)、净化环境+合成密钥(实测不继承用户真钥、
白名单外变量不外泄)、cwd 越界即拒;mounts 语义=**复制**非挂载非软链
(会话内改动不回写源目录,实测);超时杀进程组。钉死测试 6 项)。
**③ 宿主快照排除+合成替身+PII 出口扫描 ✅ 完成**(harness/host_snapshot.py)。
实测两项发现:(a) **L1 风险降级**——OfferClaw 的 user_profile/applications/
daily_log 均为 untracked,git 克隆天然不携带 PII,真正通道是 B 类资源
引导(复制 chroma_db=3538 条真实简历/JD 向量);(b) 真实副本试跑
(6255 文件)暴露 `logs` 排除模式误伤 `.git/logs`(reflog)→ 修为
".git 整体保留或整体排除,不允许挖洞"。真实副本 PII 扫描 0 命中。
钉死测试 5 项。④ 宿主级任务包接线 → 下一步;⑤⑥ 未开始。

## 状态条目 · 2026-08-09 · **Phase 0 完成**(下一步:Phase 1 T1 校准)

Phase 0 六件全部落地并测试钉死(全量 442 项绿):
①主目录护栏+保护目录指纹对账(`harness/host_guard.py`,77dc6a6)
②LocalWorktree 执行后端——护栏/假 HOME/净化环境含合成密钥/cwd 钉死
  四条硬约束焊死(`execution/local_worktree_backend.py`,d0846ba)
③宿主快照排除+合成替身+PII 出口扫描(`harness/host_snapshot.py`,474705b)
④宿主级会话装配+空转冒烟全链(`harness/host_task.py`,d8f846c)——
  Phase 0 完成定义的载体:冒烟已实证"替身生效/假 HOME/回归绿/未适配
  时隐藏验收挂/会话拆净/保护目录零改动/oracle 不进会话与环境"
⑤Provenance 最小版(`verification/provenance.py`,d8f846c)
⑥Benchmark V2 记录器(`persistence/bench_records.py`,d8f846c)

**Phase 1 待办(AI 做,用户只在最后跑正式 run)**:
1. Host Baseline 首测:在 t1 副本上跑 doctor/verify_pipeline/594
   pytest/verify_docs,记录耗时→定分层回归子集与容差协议;产出
   HostBaselineManifest + 副本引导手册(§4-3 七类资源实测答案);
   期间对主目录 untracked 数据(.env.local/chroma_db/gap_store)做
   一次性备份;
2. T1 任务工程:公开需求/公开测试/隐藏 oracle/task_shape 评分/
   正控全过/负控按预期挂/直连基线/冻结/预注册;
3. 交付用户:GPT-5.5 与 DeepSeek 各 1 次(随机序)的可复制指令。

## 状态条目 · 2026-08-09 · Phase 1 首测完成(Host Baseline + 副本引导)

**产出**:`docs/testplans/HOST-BOOTSTRAP-OFFERCLAW.md`(引导手册)+
副本内 `HOST_BASELINE_MANIFEST.json`。基线:**591 passed / 0 failed /
12.5s / 3 次完全确定性**;verify_pipeline 6/6;verify_docs 全绿;
doctor 8 OK·2 WARN·1 ERR(已知预期差异:chunks 口径 112 vs 3538 因
合成语料重建;WARN=合成密钥政策预期)。

**三个实测结论(推翻/确认了方案假设)**:
1. **分层回归修正被推翻**:全量仅 12.5 秒 → TESTPLAN §2-3 改为每轮跑
   全量(假设"594 测试很慢"是错的);
2. **零真实密钥可行**(§4-3 C 类政策实证):591 测试全绿,无需任何
   API key——"多轮修复不需要 OfferClaw 真钥"从推断升级为实证;
3. **chroma_db 253MB 真实向量不进副本**:改用合成语料重建索引
   (112 块,12 秒),代价仅为 chunks 口径差异(已知项)。

**替身工程迭代实录(23→12→8→4→2→0 失败)**:4 轮收敛,每轮失败都在
揭示"测试锚定了什么"。最终原则:**分类属性等价 + 行格式镜像**——
测试断言的是粗粒度属性(学历/专业/地域/方向)和解析格式,不是身份
内容;因此替身可做到"分类等价、身份全合成"。该经验对后续宿主通用。

**连带修复(真实场景暴露)**:`scan_for_pii` 未跳过依赖目录 → 真实副本
20 条命中全来自 `.venv` 第三方库作者邮箱(真实信号被淹没),已修并
钉死回归(副本自身复扫 0 命中)。

**下一步**:T1 任务工程(公开需求/公开测试/隐藏 oracle/task_shape/
正负控/直连基线/冻结/预注册)→ 交付用户可复制运行指令。

## 状态条目 · 2026-08-09 · **T1 任务工程完成,已冻结待运行**

任务 `t1-offerclaw-fastapi-mcp-v1`(task_shape **10/16**,真实工程集成档)
六步任务工程全部通过,预注册见 `benchmarks/v2/preregistrations/T1-prereg-20260809.md`。

| 验收 | 结果 |
|---|---|
| 正控(参考实现) | 公开 8/8 + 隐藏 9/9 + 宿主回归 591/591 ✅ |
| NC1 手写 MCP 不用 SDK | 挂 H5 语义替代 ✅ |
| NC2 无白名单暴露全部 | 挂 H1+H1b 越权泄漏 ✅ |
| NC3 顺手精简旧 REGISTRY | 挂 H3 宿主回归 ✅ |
| NC4 手写静态 schema | 挂 H2 协议漂移 ✅ |
| 直连基线(未适配) | 公开 4/8、隐藏 3/9 —— 起点明确 |

**三个工程发现**:
1. **真实依赖冲突是难度主来源**:pinned fastapi_mcp 声明 `mcp>=1.12.0`,
   但 mcp 2.0.0 破坏 `Server.__init__` 签名 → 必须钉 `mcp<2.0`(实测
   1.29.0 可用)。agent 需自行诊断——这是 T1 区别于样例任务的关键。
2. **负控抓出 oracle 自身漏洞(负控价值的直接证据)**:H3 原以运行时
   REGISTRY 为基准,NC3"同时精简 REGISTRY 与 /mcp"即可骗过自指断言
   → 改为**冻结值**基准后 NC3 正确挂掉。**教训:回归基准必须是冻结值,
   不能是运行时自身状态。**
3. **venv 不可 `cp -R` 迁移**(我自己踩的坑):venv 脚本 shebang 硬编码
   原路径,复制后 `pip install` 装回**源 venv**——实测污染了 t1 基线
   (已卸载清理并验证 591 恢复)。per-run 环境必须**重建**(70 秒)
   而非复制;TESTPLAN §5"复制 venv 实例"表述须修正。

**下一步**:交付用户可复制运行指令(随机序:① deepseek-v4-pro ② gpt-5.5)。

## 状态条目 · 2026-08-09 · 宿主级运行驱动接线完成,全链冒烟三发通过(待用户 pilot)

**缺口回填**:冻结时任务包就位但**运行入口不存在**(host_task.py 零调用方,
per-run venv 未接)。本条目落地 `runner/host_guided.py` + CLI `host-run`:
会话装配(快照+副本精细替身+PII 0 命中门禁)→ 会话内 git S0 锚 → per-run
venv 从**冻结 wheelhouse** 重建(146 wheels/325MB,含 mcp 1.29.0+2.0.0
双版本保留依赖冲突语义;env_baseline_hash=6bc19ab1…)→ Host Baseline
Gate → RepairLoop guided ≤3 轮(公开+回归每轮全量,git 回滚劣化轮)→
git diff 冻结适配 → 隐藏 oracle(会话外持有)/回归(≥591)/Policy(三树
不变+因果链+预算)→ clean replay → Completion Gate → 指纹对账 →
runs.jsonl 记账。钉死测试 9 项,全量套件绿。

**冒烟实录(runs.jsonl 前三行,全 fake 模型零 API)**:
| run | 预期 | 实际 | 链条验证点 |
|---|---|---|---|
| noop#1 | 走到 agent | **BLOCKED**(gate) | 门禁自身判据过严被抓:verify_docs 因合成语料 chunks 口径 exit 1,而 Manifest 早已记为已知偏差 → 判据改"0 处未围栏裸露不退化" |
| noop#2 | FAIL | **FAIL**(3 轮停滞,公开 4/8 与直连基线一致) | FAIL 路径+停滞判定+记账 |
| positive | PASS | **PASS_ADAPTED**(1 轮 8/8→oracle 9/9→回归 592→replay PASS,328s) | PASS 路径+重放语义 |

**五个工程发现(接线期,全部修复并钉死)**:
1. **pytest 9 的 `-q` 失败态不打总结行** → "N passed" 正则在失败 run 恒取 0
   (首噪:oracle 计 0/6 而真值 3/9)→ oracle/回归/公开全部改 junitxml
   结构化计数,正则仅兜底;
2. **指纹对账集语义**:RepoProof 自身在写护栏黑名单是对的,但**不能进
   指纹对账集**(run 合法写自己的 runs/)——并发跑全量套件时套件内
   smoke 测试的指纹当场报警,反向证明机制灵敏;
3. **会话根不得落在保护目录内**(护栏拒绝)→ 统一 `~/RepoProofBench/_sessions/`;
4. **replay 依赖语义落地**:venv 状态不随 git 回滚(L 模式单调性),
   clean replay 从**补丁后的 requirements.txt** 全新重建环境——"未声明
   的依赖在重放如实失败"把源 §24 Dependency Delta 变成可执行判据;
   正控声明 `fastapi-mcp` + `mcp<2.0` 后 replay 9/9 实证;提示中如实
   披露该语义(公平性,钉死测试);
5. **会话内 592 vs 副本 591**:会话环境多过 1 项(三发冒烟稳定 592,
   方向为升不触判据;具体测试项待查,挂起不阻塞)。

**下一步**:提交 harness_commit → 用户亲手 pilot(随机序:①
deepseek-v4-pro ② gpt-5.5,`repoproof host-run` 指令已备)。
