# VERIFIED_TOOL_READY 判定表(M0 产出 · 依据 RFC-010 [D4][G2][G4])

- 状态:M0 设计稿;M1 实施时判定逻辑**零代码改动**,本文定义的是
  语义映射与新增测试节点/静态检查的落点
- 依据:现行 `verification/completion_gate.py` 决策表(Gate 2.5 冻结)
  + `verification/verifiers.py` 读码(2026-08-23)

## 一、原则:决策表不动,所指平移

`completion_gate.decide()` 只消费四个结构化 `VerificationResult` +
冻结 `AdaptationManifest` + missing_external + budget_exhausted,
**不认识"宿主"也不认识"工具"**——它已经是谱系无关的。
工具谱系全部差异都在**喂给它的四个结果怎么算出来**,决策表七行原样:

| missing_external | budget | C∧R∧P | replay | verdict |
|---|---|---|---|---|
| yes | - | - | - | BLOCKED |
| no | - | true | none | READY_FOR_REPLAY(绝非终态) |
| no | - | true | passed, clean_adoption | **PASS_ADAPTED / PASS_DIRECT** |
| no | - | true | passed, baseline_repro | READY_FOR_REPLAY |
| no | - | true | failed | FAIL(replay 分歧) |
| no | yes | false | - | FAIL + BUDGET_EXHAUSTED |
| no | no | false | - | FAIL(验证器理由) |

## 二、对外判定名映射(报告/manifest/UI 用语,内部枚举不改)

| 内部 Verdict | 工具谱系对外名 | 条件 |
|---|---|---|
| `PASS_ADAPTED` | **`VERIFIED_TOOL_READY`** | 常态:agent 交付了 wrapper(adaptation.present) |
| `PASS_DIRECT` | `VERIFIED_TOOL_READY (DIRECT)` | 罕见:骨架+上游 CLI 已满足,零 wrapper |
| `READY_FOR_REPLAY` | 中间态,不对用户报成功 | |
| `FAIL` / `BLOCKED` / `PARTIAL` | 原名 | FAIL 也交付证据包(铁律 4) |

映射只发生在**报告渲染层**(report.json 加 `verdict_public` 字段),
台账与内部枚举不动——task_id 与枚举史不可改写的纪律同款。

## 三、四验证器在工具谱系的所指

### C · CapabilityVerifier(能力)

- 载体:pytest(junit 节点级验证器零改动),oracle 节点 =
  **golden 样例(公开 + held-out)+ 确定性**;样例测试内部
  `subprocess.run` 工具 CLI,断言 exit 0 + 输出匹配
  ([TOOL_CONTRACT_SCHEMA.md](TOOL_CONTRACT_SCHEMA.md) §四第一层);
- **[D4] 弱档采纳证明并入本侧**:provenance 零 import 检测
  (`UPSTREAM_CAPABILITY_REIMPLEMENTED`)与 manifest 一致性静态检查
  (§五)不通过时,作为 capability 侧 FAIL 理由记入 detail——
  沿用现行"S2 采纳不成立并进 capability 侧,不记 harness 故障"的口径;
- M2 升级后:import-hook 回执 U1–U4 结论并入同一位置,gate 仍然零改动。

### R · RegressionVerifier(接口契约·骨架半;旧"宿主回归"的新所指)

接口契约按 owner 拆两半(M1 实施定稿;baseline gate 要求 S0 回归恒绿):
- **骨架半(HOST_INPUT_GUARD)→ R 面**:help 可达 / 输入不存在 exit 1。
  S0 骨架态恒绿,"agent 搞红它 = 破坏骨架既有行为"——正是回归语义;
  落位 `public_tests/test_interface_contract.py`(会话内,agent 可自测,
  公开面哈希守卫防篡改);
- **实现半(ADAPTER)→ 并进 C 面 oracle**:坏格式不裸奔(exit 1 非 2)/
  确定性 / 输出纯净。依赖能力实现,S0 红属预期(直连基线语义)。
全部由 `ToolSpec` 推导、装配器生成——节点语义即公开合同。
`regression_command` argv 走契约,`regression_result` 只改 detail 文案。

### P · PolicyVerifier(照旧)

trace 因果 + 预算 + oracle/upstream 树哈希前后不变 + forbidden 清单
+ **新增一条 diff 检查**:agent 对骨架锚定件(`tool.json` 的 interface、
`bin/` 壳、`build.sh` 构建协议)的改动 = 违规(结构锚执法;
按对齐律先教——prompt 里逐字声明锚定件不可改,闸门才可杀)。

### REP · ReplayVerifier(干净重建;对工具谱系价值最高的一面)

```
空白环境 → 复制冻结交付树(tool/) → ./build.sh(从 requirements.lock
重建 venv) → 重跑 capability_command + regression_command
→ 4 键比对(capability_exit / capability_failed / regression_exit /
probe_normalized_sha)→ mode=clean_adoption 才有资格撑 PASS
```

replay 即安装测试:PASS 直接回答"这个工具在干净机器上装得起来、
跑得对"。依赖不可复现归因(`DependencyNotReproducible` /
added_unresolvable / conflicting)原样复用。

## 四、为什么不加第五个验证器(设计裁决)

"工具接口验证器"(RFC-010 🔴新写)的实现形态 =
**生成器 + 静态检查,不是 gate 的第五个输入位**:

1. 动态行为检查 → 编译成 R 侧 oracle 节点(pytest 载体,junit 精确
   节点比对白捡);
2. manifest 一致性 → 交付期静态检查,不过则作为 C 侧 FAIL 理由;
3. 收益:`completion_gate` 决策表与其全部钉死测试零改动;
   四验证器的对外叙事(能力/回归/策略/重放)保持稳定;
4. 代价:接口失败在报告里挂在 C/R 名下而非独立名目——用 detail 前缀
   `[tool-interface]` 标注,归因粒度不损失。

## 五、控制组矩阵(M1 最小集;检查器先自证的铁律落点)

| 控制 | 内容 | 必须的结局 | 自证对象 |
|---|---|---|---|
| 正控(battery) | 硬编码**全部**样例映射(含 held-out) | C 样例节点全绿 | 样例测试自洽可满足(题不无解);freeze 前用,**不走全链**(弱档执法下它必死于 provenance) |
| **reference** | 出题人提供的**真 import 上游**参考实现 | 全链 PASS_ADAPTED | "真调上游的解存在";fake 全链的通关正控(bridge 物化为 host 包 controls/positive) |
| NC_empty | 空实现(返回空串) | C 必死 | 样例测试有判别力 |
| NC_hardcode | **只**硬编码公开样例 | held-out 节点必死,公开绿 | **held-out 防硬编码层真的在防**([G2] 的合成缺陷验证) |
| NC_reimpl | 硬编码全样例、零 import 上游(= battery 正控的化身) | oracle **全绿**、死于 provenance(C 侧翻,detail 保留 oracle 计数) | [D4] 弱档采纳证明查得出——没有这条,假成功直通 |
| NC_badexit | 坏输入不包装,裸奔 → 骨架兜成 exit 2 | C 面 malformed 节点必死,骨架半绿 | 接口契约(实现半)有判别力 |

五个控制随任务装配生成,`freeze-task` 前跑 controls battery
(FAILED_AS_EXPECTED 语义沿用)。**M1 新写的每一件验证代码
(cli 模式样例编译 / 接口测试生成器 / manifest 静态检查 / 通用
extractor)都必须先被上表至少一个合成缺陷证明查得出,再谈上真任务。**

## 六、产品指标口径([G4],M4 生效,此处冻结定义)

- `tool_ready_rate = VERIFIED_TOOL_READY 数 / 准入接受数`,
  **必须与 `acceptance_rate = 准入接受数 / 提交任务数` 成对报**;
- `replay_success`:交付后在第二台干净环境重跑 build.sh+验收的通过率;
- `false_success`:抽样人工审计 VERIFIED_TOOL_READY 工具"实际不满足
  用户意图"的比例——最高优先指标,审计单进台账;
- 全部数字出自单一脚本(gate_report 谱系),散文只解释不下判断。
