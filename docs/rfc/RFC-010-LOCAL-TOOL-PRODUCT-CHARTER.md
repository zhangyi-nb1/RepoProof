# RFC-010: Local Tool Product Charter(GitHub Capability → Verified Local Tool)

- 状态:**章程定稿待用户签字**(2026-08-23;四项关键决策已由用户拍板,见 §三)
- 依据:用户方向文档 [PRODUCT_REDIRECTION.md](../PRODUCT_REDIRECTION.md)
  + GPT 适配线收线实测([RETROSPECTIVE-GPT-ADAPTATION.md](../RETROSPECTIVE-GPT-ADAPTATION.md):
  严口径出题 30 候选仅产 2 题、窗口 2 零准入;v1 FAIL → v2 PASS 单变量实证
  "成功率首先来自出题与 harness")
  + 2026-08-23 全仓读码盘点(基线 `30b7a3a`,结论摘录于 §五)
- 本 RFC 是方向章程:定"做什么、按什么顺序、什么不变"。具体 schema/布局设计
  是 M0 的后续产出,不在本文展开。

## 一、方向声明

主产品场景从「任意 Repository Adaptation」收敛为
**「GitHub Capability Onboarding:把用户在 GitHub 看中的单一能力,
自动转化为经过独立验证的本地工具」**。

方向文档 §15 的八条判断全部采纳,其中三条在盘上有直接数据背书:
- 判断 3(Harness 不保证模型完成超出能力的任务)= 既有产品承诺
  「判定保证而非成功保证」(T2 22 发:19 次拒绝全部有理、0 误判);
- 判断 5(差异化核心 = Contract + 独立验证 + Replay + 证据)= 四平面架构中
  自研的三个平面;
- 判断 7(主动缩小任务空间)= 出题瓶颈实测卡死的直接教训。

## 二、与既有资产的关系(核心认识)

**盘上已存在新方向的雏形,转向的主体是语义收敛,不是重写:**

1. A 谱系契约(`contracts/adopt-*-guided-v1.yaml`)的「宿主」早已退化为合成的
   `user_capability.run(value)` 单函数包——这就是本地工具的形状,只是名字
   还叫 consumer fixture;
2. `adoption/` 流水线(intent → 分析(FACT/INFERENCE/UNKNOWN)→ 准入四态 →
   计划 → 装配 → 修复 → 交付)就是方向文档 §7 用户体验的现成骨架;
   `support_policy` 的 BLANK_PROJECT 分支是 Local Tool 场景的直接前身;
3. guided UI 线(RFC-008 Gate A–E + Streamlit Studio ~3000 行)2026-08-08
   已由用户亲手跑通全链路,冻结至今,可在 M3 复活对接;
4. 验证/证据/隔离/回执四面整体可搬(§五资产分级)。

## 三、已裁决决策(用户拍板,2026-08-23)

**[D1] v1 交付物核心形态 = CLI-first 工具包。**
标准布局目录:tool manifest(名称/输入输出 schema/来源/pinned 版本)
+ 单一 CLI 入口 + venv 构建声明 + 证据包。MCP / Python API 在 M3 由
manifest 机械转换生成,不进 v1 关键路径。验收载体沿用 pytest
(junit 节点级验证器零改动)。

**[D2] M1 首个 dogfood 场景 = PDF 表格 → Markdown。**
上游取 pdfplumber 类纯 Python 仓;固定 PDF fixture → 期望表格的验收样例。
选题原则:打穿闭环,不挑战难度;用户日常真用。

**[D3] 真模型阶段 Agent 后端默认 = mini-swe-agent,DSH 保留 `--backend dsh`。**
DSH 预算轴悬置问题(一发观察 1.75M in,收线结论「需重新设计而非调参」)
不阻塞主线,M3 前再裁。M1 内部照例先 fake 钉死机制再上真模型。

**[D4] 「真实使用 upstream」证明强度 = M1 弱档起步,M2 升级。**
M1 用现成的 provenance 零 import 检测 + 正负控制组(零新写);
M2 新写 import-hook 取证件:验收期在工具进程内劫持 import 写回执
(复用 U1–U4 谓词与 9 负控矩阵),交付期工具保持纯净。
「sidecar 常驻交付」不做(与轻量本地工具的产品形态冲突);
sidecar 拓扑保留给重运行时能力(浏览器类,方向文档场景二)。

## 四、四个设计缺口的解决原则(M0 落实)

**[G1] 契约起草自动化与 LLM 边界。** 产品模式允许 LLM 进入出题面,但仅限
**草稿层**:LLM 起草 → 确定性 ContractAdequacyGate(13 条,扩工具语义)→
用户确认 → 冻结。冻结后 LLM 不再触碰题面;**验证面无 LLM 铁律不变**。
Gate 7 教训(欠定契约的失败是出题人的锅)在产品模式转译为:起草质量差 =
用户确认负担重 = 体验失败,故 M2 的质量重心在起草而非执行。

**[G2] 验收判定物三层来源。**
① 用户确认契约时冻结 golden examples,**其中一部分标 held-out 不给 agent**
——防的不是泄题,是 agent 硬编码样例答案;
② 从上游自带测试选相关子集做「上游行为一致性」检查;
③ 工具接口/结构检查自动生成(exit code 语义、输出 schema、错误处理、
确定性/离线)。
独立性口径:post-cutoff / 盲攻 / 预注册整套留在 Benchmark Lab;
产品模式保留最小独立性 = held-out 样例 + 验证器不读 agent 声明。

**[G3] Product Mode 与 Benchmark Lab 分界。** 同仓不 fork,按配置分流:
Lab 资产(held-out 准入、盲攻、预注册、猎题)封存保持可运行,不进产品
关键路径;M4 时 Lab 方法论(预注册、诚实闸门、变异自证)回归服务产品指标。
产品运行照记台账,`test_mode` 标 product,不与 Lab 成绩互比
(RuntimeProfile 语义指纹守卫同律)。

**[G4] 成功指标的诚实口径。** Tool Ready Rate 必须与任务接受率**成对报**
(防把准入闸调严刷指标);False Success 审计为最高优先指标;
指标只出自单一脚本。

## 五、资产分级(2026-08-23 读码盘点结论摘录)

- 🟢 **近零改动搬移**:Completion Gate 决策表、PolicyVerifier、
  ReplayVerifier(`clean_adoption` 才撑 PASS)、ContractAdequacyGate 13 条、
  RequirementSpec、trace 哈希链、bundle/redaction、oracle 只读守卫、
  回执 U1–U4 + 9 负控、sidecar、RuntimeProfile 注册表、LocalWorktree/Docker
  双执行后端、DSH watchdog、保护目录护栏、依赖不可复现归因、
  EXPORT_ONLY 交付包、三级写回协议;
- 🟡 **改语义不改结构**:`TargetProject`(kind 加 `local_tool`)、
  HostRegressionVerifier(→ 工具自测 + 确定性/离线回归,argv 走契约)、
  setup_commands/health_checks 默认值、prompt_profile 加 `local-tool-v1`、
  admission 单仓推广、`task_assembler` 模板(**工作量主体**)、
  provenance 路径参数、Verdict 对外名 → `VERIFIED_TOOL_READY`;
- 🔴 **必须新写**:工具接口验证器(CLI argv/stdin/stdout/exit code;
  按纪律喂合成缺陷自证)、通用 delivery extractor、
  (M2)import-hook 取证件、(可选)AgentBackend 正式 Protocol。

## 六、路线 M0–M4

| 阶段 | 目标 | 关键产出 | 成功判据 | API |
|---|---|---|---|---|
| **M0** 章程与语义冻结 | 方向 → 可执行语义 | 本 RFC;[ToolContract schema](../TOOL_CONTRACT_SCHEMA.md)(A 谱系演化);[Tool Package Layout](../TOOL_PACKAGE_LAYOUT.md) 规范;[VERIFIED_TOOL_READY 判定表](../TOOL_READY_GATE.md)(样例三层细则并入 schema §四) | 文档齐 + 用户签字 + 1127 基线复验绿(见 §七前提) | 零 |
| **M1** 手工契约打穿闭环 | 第一个真工具 | task_assembler 工具骨架模板;`local-tool-v1` prompt profile;工具接口验证器(自证);通用 delivery extractor;fake 先行后真模型 | 用户日常真用的 PDF 表格工具 + 干净环境 clean replay 通过 + 证据包完整 + 新验证器负控全数落网 | 低(个位数发) |
| **M2** intake 半自动化 | 人写契约 → 人确认契约 | 契约草稿生成([G1] 边界);adequacy 扩条;样例三层落地;admission 扩 local_tool;import-hook 取证([D4]) | GitHub URL + 一句话需求 → 冻结契约,人只确认不撰写;草稿质量入台账 | 中 |
| **M3** 产品收口 | 单命令旅程 | `repoproof tool add <url> --capability "..."`;本地工具注册表(已装工具 + 证据索引);MCP 暴露(manifest 机械转换);可选 Studio UI 复活 | 端到端体验 = 方向文档 §7 流程 | 中 |
| **M4** 批量实测与指标 | 用数字说话 | 10–20 真实仓批跑;四指标([G4] 口径) | 指标出自单一脚本;正负结果都入档;跑批前预注册 | 高 |

每阶段为一道 gate:产出 + 判据绿 + 用户验收,才进下一阶段;
阶段内改动照旧 RFC 先行。

## 七、开工前提(M1 硬前提)—— ✅ 2026-08-23 达成,实测口径如下

收线清理已删 `.venv/` 等可再生件(commit `30b7a3a`)。venv 重建后实测:
首跑 `1086 passed + 53 skipped + 8 failed = 1147`,与收线记录
`1127 passed + 20 skipped = 1147` **总数一致、零测试丢失**;8 个失败
逐一取证,全部为清理删除的 Lab 外部资源所致(封存 runtime / 部署树 /
runs 历史),零代码回归。经用户裁决补资源存在性 skipif(对齐仓内既有
模式,断言零改动,资源回盘自动恢复执行)后:

> **产品线基线 = `1086 passed + 61 skipped + 0 failed`(exit 0)。**

"期望 1127 passed" 属完整复活 Lab 资源后的口径(RETROSPECTIVE §7
第 4–5 步完成后),与本基线不矛盾。变异闸门 290/290 属 Lab 资产,
按 [G3] 不阻塞产品线,M4 前复验。

## 八、不变的铁律(全程沿用)

1. 单自主循环(静态守卫测试在案);
2. 验证面无 LLM;Completion Gate 不读 agent 声明;
3. held-out(产品口径 = 隐藏样例)对 agent 零泄漏,测试钉死;
4. FAIL 也交付完整证据包;失败必须可归因;
5. 数字只出自一个脚本,散文只解释不下判断;
6. 检查器先喂合成缺陷自证,再谈查得出真缺陷;
7. 循环 vs 闸门对齐律:闸门要杀的先教,闸门不杀的不许暗中判死;
8. 台账 append-only;每批运行声明 test_mode;
9. 沉默不是通过:没量到 = 判死,不造零不造真。

## 九、v1 边界(对外承诺口径)

支持:Public GitHub 仓、单一明确 capability、Python-first、本地 CPU、
简单-中等依赖、可构造可验证样例。
不承诺:任意语言、GPU/分布式/云账号、移动端、自动重写上游
(原则五:不适合接入则如实返回 UNSUPPORTED/REVIEW_REQUIRED,
拒绝即产品价值)、完全无监督开发。
`Local Reimplementation` 明确排除出 v1(方向文档 §6 原则五)。
