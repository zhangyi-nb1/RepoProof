# VERIFIED_TOOL_READY 与运营发布状态现行规范

- 状态:**M5 已实施**;历史 completion 决策表不改,新增独立的
  append-only operational release 轴
- 依据:
  [RFC-010](rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md) [D4][G2][G4] 与
  [RFC-011](rfc/RFC-011-TOOL-CONTRACT-COHERENCE-AND-RELEASE-STATE.md) §四–§六
- 实现边界:`verification/completion_gate.py` 的 Gate 2.5 冻结决策表
  仍只产生历史验证事实;RepoProof 受管 audit、MCP 与升级发布
  当前是否放行由
  `runner/tool_release.py` 的决策账独立回答

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
这一结论在 registry / list / pipeline 的现行字段名为
`historical_verdict`;legacy `verdict` 仅作同值兼容别名,绝不表示当前
可用。即使后续运营撤回,这一历史字段也不回写。

## 三、四验证器在工具谱系的所指

### C · CapabilityVerifier(能力)

- 载体:pytest(junit 节点级验证器零改动),oracle 节点 =
  **golden 样例(公开 + held-out)+ 确定性**;样例测试内部
  `subprocess.run` 工具 CLI,断言 exit 0 + 输出匹配
  ([TOOL_CONTRACT_SCHEMA.md](TOOL_CONTRACT_SCHEMA.md) §四第一层);
- **M5 v2 输出合同并入本侧**:每个 public / held-out 成功样例
  都先对 CLI 的实际 stdout 跑独立的 `ToolOutputContract` 解析,
  再做 golden 断言;这一节点不依赖 expected 是否也写错,失败以
  `[tool-output-contract]` 稳定前缀进 evidence。冻结前 T6–T9 先拦
  合同/golden/manifest 分叉;JSON 严格拒绝 `NaN` / `Infinity` /
  `-Infinity` 与溢出为非有限值的 `1e400` / `-1e400`;v1 保持原
  oracle 语义;
- **[D4] 采纳证明并入本侧(三层证据,M2-c 实施定稿)**:
  ① 静态 provenance 零 import 检测;② **运行时回执**(harness 在工具
  子进程注入 import-hook:sitecustomize 经 env 进程链、HMAC secret
  现摇、ledger 在 run_dir 会话外;判据 = import 事件 ≥1 且调用数 ≥
  文件样例数——抓"装样子 import";账缺失 = 判死);③ 探测自曝扫描
  (交付文本含 REPOPROOF_HOOK 字样 = INSTRUMENT_TAMPERED——协议不在
  任何 agent 可见面,正常实现不可能碰巧写出)。任何一层不过均作为
  capability 侧 FAIL 理由记入 detail(oracle 计数保留),沿"S2 并进
  capability 侧"口径;completion_gate 零改动。威胁边界如实:同进程
  运行时反射窃取 secret 属 v1 边界外(sidecar 拓扑仍是强档);
  量具透明性钉死:wrapper 不包异常类/类型(真实上游 FormatError 实测
  ——包类会炸 except 语义)。

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

1. 动态行为检查 → 编译成 R/C 侧 pytest 节点(junit 精确
   节点比对白捡);实现半与 v2 输出合同归 C,骨架半归 R;
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
| NC_json_plaintext | v2 声明 JSON object,golden 是纯文本 | T7 在写入/冻结前拒绝 | expected 不能与错合同共谋通关 |
| NC_json_wrong_root | v2 声明 object,golden 是 array | T7 拒绝 | 根类型校验有判别力 |
| NC_json_missing_field | object 缺合同 `required` 字段 | T7 拒绝 | 顶层字段校验有判别力 |
| POS_json_report | 完整合法 JSON object | 装配、reference 彩排、运行期解析全绿 | 合同不把正常结构化输出判死 |

任务级 RFC-010 controls 随任务装配生成,`freeze-task` 前跑
controls battery(FAILED_AS_EXPECTED 语义沿用);M5 的 JSON 正负控则
直接喂给装配前门与运行期解析器。**M1 与 M5 新写的每一件验证代码
(样例编译 / 接口测试生成器 / manifest 静态检查 / 通用
extractor / 输出合同解析)都必须先被上表至少一个合成缺陷证明
查得出,再谈上真任务。**

## 六、历史 verification 与 operational release 双状态(M5)

### 6.1 两类事实不互相覆盖

```text
historical_verification
  = 某次冻结契约下 completion gate 的不可改写结论

operational_release
  = 当前 task version 是否可作为 ACTIVE 成果被受管 MCP 暴露/完成升级发布
```

运营决策账是 `<dest_root>/.repoproof-release-decisions.jsonl`,
有三种折叠状态:

| 状态 | 语义 |
|---|---|
| `REVIEW_REQUIRED` | 初次导出、无决策或当前 task version 尚未 fresh-input audit |
| `ACTIVE` | 当前 task version 的 fresh-input audit 通过,可作为受管 MCP/升级发布的 ACTIVE 成果 |
| `REVOKED` | 审计失败、输出合同缺陷或用户明确撤回 |

每行必须通过完整 schema 校验,`最后一条合法决定`按工具折叠;
空行、损坏 JSON(包括 `NaN` / `Infinity` / `-Infinity`,以及解析为
非有限浮点的 `1e400` / `-1e400`)、缺字段、
非 RFC3339 UTC 时间或非法枚举都使
消费者 fail closed,不得跳过坏行。决策只能 append,不删除或替换
旧行;registry 是索引,决策账才是运营状态事实源。

导出注册只接受历史 `VERIFIED_TOOL_READY`工具,并为新 task version
追加初始 `REVIEW_REQUIRED`;重复注册不覆盖已有 `ACTIVE` 或
`REVOKED`。`tool list --scan` 只补 registry 索引,不伪造
`ACTIVE`;缺决策或决策 `task_id` 与当前包不匹配时必定投影为
`REVIEW_REQUIRED`。`tool list` 同时显示 `historical_verdict` 与
`operational_status`;legacy `status=OK` 只表示包/历史验证健康,
不表示当前受管发布可用。

**执法边界**:运营决策账不是 OS 级访问控制。原始
`<dest_root>/<name>/bin/<name>` 文件保留,用户直接手工执行它时
RepoProof 无法拦截。`REVIEW_REQUIRED` / `REVOKED` 的强制面是
RepoProof 管理的 audit、MCP 生成与 M5 adapter 运行期,以及安全升级
发布;不应对外声称“撤回后 CLI 不可执行”。

### 6.2 fresh-input audit 与 withdraw

```bash
repoproof tool audit <name> \
  --input <fresh-file> --expected-file <fresh-expected> \
  [--build] [--dest-root ~/tools]

repoproof tool withdraw <name> \
  --reason "<reason>" [--dest-root ~/tools]
```

`audit` 只对历史 READY 工具开始,并在执行前校验整本运营账。
输入和 expected 必须位于工具包外,其哈希也不得复用公开
fixture。审计调用 `bin/<name>`,要求 exit 0、stdout 与操作者给定
expected 字节精确相等,然后再用同一 `ToolOutputContract` 独立
解析 actual stdout;JSON/JSON Lines 中的 `NaN` / `Infinity` /
`-Infinity`,以及溢出为非有限浮点的 `1e400` / `-1e400`,一律拒绝。
只有全部通过才 append `ACTIVE`;
构建、执行、
精确比对或输出合同任一失败都 append `REVOKED` 与稳定
`reason_code`。

使用 `--build` 时，重建成功后仍须在执行 launcher 前重新校验 canonical
包树以及 `tool.json` / provenance identity；除 opaque `.venv` 外，若 build
换入 symlink/特殊文件或改写身份，audit 直接 append `BUILD_FAILED/REVOKED`，
不得执行重建后的 launcher。

决策账不保存 input / expected / stdout / stderr 正文,只保存必要的
哈希聚合与结构化结果。因 `OUTPUT_CONTRACT_MISMATCH` 撤回的
同一 task version 不得靠再次 audit 恢复;必须发布新 task version。
用户 `withdraw` 只 append `USER_WITHDRAWAL` 的 `REVOKED`,不删包、
不改 `tool.json`;普通 audit 也无权恢复用户撤回。

`repoproof tool import-audits` 用于将已有 append-only 操作者审计
按原始行哈希幂等迁移成运营决定;它不从散文猜测状态,
也不覆盖更新的用户撤回。

### 6.3 MCP 生成与运行期双重执法

`repoproof tool mcp <name>` 必须同时看到:

1. `tool.json.verification.verdict` 是历史 `VERIFIED_TOOL_READY` 或
   `VERIFIED_TOOL_READY (DIRECT)`;
2. 决策账中当前 task version 的最后状态为 `ACTIVE`。

`REVIEW_REQUIRED` / `REVOKED` 都拒绝生成。M5 生成的
`mcp_server.py` 在每次 `tools/list` 与 `tools/call` 前重新读取、严格
校验并折叠决策账,确认 task version 仍为 `ACTIVE`;因此生成后撤回
也会在 runtime fail closed。系统不自动改写或删除 pre-M5 MCP 文件,
以避免破坏性操作;若工具已非 ACTIVE 且发现旧 adapter,`tool list`
明确标记 `LEGACY_SERVER_MUST_BE_DETACHED`,由操作者从客户端解绑。

v2 工具还会把合同投影为 MCP `outputSchema`,并在调用返回前
对 actual stdout 再做合同校验;v1 无合同时保持原文本兼容路径。
严格 JSON 解析同样拒绝 `NaN` / `Infinity` / `-Infinity` 与
`1e400` / `-1e400` 这类非有限结果,
MCP JSON-RPC 回包也以 `allow_nan=False` 防止重新序列化非标准数值。

M5 adapter 对 `tools/list` 与 `tools/call` 按固定顺序同时获取
`.repoproof-install.lock` → `.repoproof-release.lock`。`tools/call` 从
ACTIVE 检查、受管 executable 检查、真实执行、输出合同校验直到结果/
`--out` 发布完成始终持有双锁;不能在状态检查后、执行前插入 withdraw
或 package upgrade。

若调用声明 `--out`,adapter 不把最终路径直接交给工具。它在最终父目录
创建本次调用专属的 fresh 临时名字,先删除占位再要求工具创建;工具退出
成功后以 no-follow 方式验证其确为单链接普通文件,再做输出合同校验,
最后才用原子 replace 发布到最终路径。旧文件不作为本次结果复用;
最终目标若为 symlink、目录、特殊文件或 hardlink 均拒绝,校验失败则
清理临时产物而不发布。

### 6.4 同名新 task version 的安全升级

同一 CLI 命令的合同缺陷不得在旧 task 上改真值;必须生成
更高且同谱系的 `tool-<name>-vN`。升级协议如下:

1. pipeline 在**真模型调用前**对现存包、整本 registry schema、release ledger、
   task id 与 MCP 文件做只读 preflight;既有包存在但 registry 缺失、
   registry 指向缺失包或任一索引身份漂移时 fail closed,不得猜测升级;
2. 同一 task id 覆盖、降级/非严格递增版本、谱系错配、包与
   registry 错配都拒绝;若发现 pre-M5 legacy MCP server,必须由
   操作者先从客户端解绑并移走该文件,否则以
   `LEGACY_MCP_MUST_BE_DETACHED` 拒绝;
3. installer 获取 `<dest_root>/.repoproof-install.lock` 后重跑 preflight,
   并在 `dest_root` 同一文件系统上的隐藏 staging 目录完整物化
   候选包;
4. 切换前先 append 新 task version 的 `REVIEW_REQUIRED`,使升级不会
   继承旧版 `ACTIVE`;
5. 旧包不改任何字节,通过同盘 `os.replace` 移入
   `.repoproof-versions/<name>/<old-task>--<package-id>/`;候选包再
   原子切换到标准 `<dest_root>/<name>/`;
6. 新 provenance 以 `replaces` 绑定前一 task/归档路径;registry 先写
   同盘临时文件、`fsync`,再原子 replace,并在 `previous_versions`
   保留旧 task/run/contract/归档引用;
7. registry 的原子 replace 是 package + registry 的提交/线性化点:
   在它提交前发现的可捕获失败自动把候选移回 staging、把归档移回
   canonical 路径,恢复旧包/旧 registry;若异常发生在 replace 已提交
   之后且复核确认 registry 已绑定新包,则保留一致的新包 + 新 registry,
   绝不只回滚一侧;
8. 已 append 的新版 `REVIEW_REQUIRED` 无论恢复与否都不回删,因此旧包
   恢复后 task version 与最后决定错配,受管消费者仍 fail closed。

升级成功后标准路径指向新包,但其运营状态仍是
`REVIEW_REQUIRED`,必须用新 fresh non-example 完成 audit 才能进入
`ACTIVE`。自动恢复只承诺进程能够捕获并完成恢复的失败;`SIGKILL`、
掉电或恢复本身失败可能停在 rename 中间态,必须由操作者盘查 canonical
包、archive、staging 与 registry,不得宣称任意崩溃都可自动回滚。
这一协议管理 RepoProof 发布路径,仍不是 OS 层对归档或当前 `bin`
文件的执行禁止。

### 6.5 包身份、共享锁与路径安全

所有受管 package consumer 必须校验同一身份:

```text
canonical directory basename = tool.json.name = provenance.tool
provenance.task_id            = tool-<name>-vN (N 为无前导零正整数)
tool.json.verification.run_id = provenance.run_id
tool.json.verification.contract_sha256
                              = provenance.tool_contract_sha256
```

`evidence/provenance.json` 是必需件,不是可选提示;任一字段缺失或错配都
拒绝 registry、audit、MCP 与升级。升级还要求 registry 的 path/task/
run/contract/historical verdict 与当前包一致,并验证归档身份和
`provenance.replaces`;同 task、降级、错谱系及缺失/漂移 registry 都
fail closed。

package install/upgrade、registry scan/write、MCP 生成与 audit/withdraw
共用 install 锁来稳定包身份;默认只读 `tool list` 不取该锁,若观察到中间态
则 fail closed。涉及运营决定的复合操作只允许按
`.repoproof-install.lock` → `.repoproof-release.lock` 获取,不得反序。
audit 在身份检查、工具执行与决定 append 的全程持双锁;withdraw 因此
只能排在 audit 之后追加,不会被一个较早开始、较晚结束的 audit 覆盖。
生成后的 MCP runtime 同样按该顺序持双锁直到调用完成。

canonical 包根及关键包树拒绝 symlink 与特殊文件。为兼容已验证环境,
只有**既有顶层普通目录 `.venv`** 作为可再生环境被视为 opaque 例外;
`adaptation.patch` 不得创建或修改 `.venv`。release ledger、registry、
install/release lock、`.repoproof-versions` 归档链、`mcp_server.py` 与
MCP `--out` 目标都要求 containment/no-follow;控制文件与输出还必须是
单链接普通文件。包树中的 symlink/路径逃逸/非普通文件一律拒绝;
控制文件或输出的 hardlink 也拒绝,不沿链读取、append 或覆盖。

## 七、产品指标双口径([G4] + RFC-011)

`scripts/tool_metrics.py` 是数字出口,同时保留历史与当前运营事实:

- `tool_ready` / `historical_tool_ready`:历史流水线 READY 数,
  撤回后不减;
- `operational_ready`:历史 READY 任务中,当前 task version 最后决定
  为 `ACTIVE` 的数量;
- `review_required`:历史 READY 任务中,最后决定为
  `REVIEW_REQUIRED`,或缺决策/task version 不匹配的数量;
- `revoked`:历史 READY 任务中,当前 task version 最后决定
  为 `REVOKED` 的数量;
- `false_success`:操作者审计单中已审计/标记数与标记任务,
  不因运营投影而隐藏历史假成功;
- `tool_ready_rate = historical_tool_ready / accepted` 必须与
  `acceptance_rate = accepted / submitted` **成对报**;
- `replay_success` 仍是历史交付的干净重建/验收事实,不因运营
  撤回而改写。

指标脚本、registry 与 MCP 生成门复用同一严格
release-ledger loader;独立 MCP server 携带等价的严格校验器。
损坏账本使指标生成失败,不得忽略坏行或默认成 ACTIVE。
散文只解释脚本输出,不手工改写数字。
