# RFC-011:Tool Contract Coherence & Operational Release State

- 状态:**IMPLEMENTED / CLOSED**（用户于 2026-08-23 批准；2026-08-24 复验关闭）
- 日期:2026-08-23
- 依据:
  - [产品方向重构](../PRODUCT_REDIRECTION.md):False Success 是产品最应控制的指标之一;
  - [RFC-010](RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md):验证面无 LLM、
    检查器先以合成缺陷自证、冻结史不可改写、阶段内 RFC 先行;
  - M4 批次二真实缺陷:`tool-pyspellchecker-tool-v1` 的冻结声明要求 JSON，
    reference / examples / oracle 却共同接受排序纯文本，流水线因此出现
    1 个 false-success。

本文冻结下一阶段的产品语义与验收标准。实施仍不得修改冻结合同、历史
run 或既有审计记录；机制阶段默认不发起真实模型调用。

## 一、问题声明

RepoProof 已经能证明:

1. agent 是否满足冻结 oracle;
2. 是否真实调用 pinned upstream;
3. 是否破坏骨架或触犯 policy;
4. 是否能从锁定依赖干净重建并重放。

M4 批次二证明还缺一层:

> **冻结 oracle 本身是否与用户确认的 Tool Contract 一致。**

`pyspellchecker` v1 的三个表面互相矛盾:

- `capability.statement` 与 `tool.interface.output.format` 声明 JSON 对象;
- draft 的 `capability.output_schema` 曾写成 `SpellingSuspicionReport`;
- reference 和所有 expected files 返回换行分隔的纯文本单词。

现有样例编译器忠实地把错误 expected 编译成测试，reference 彩排与真模型
都通过了这份错误 oracle。换言之，verification plane 正确证明了
“实现满足 oracle”，却没有证明“oracle 满足用户确认的输出合同”。

第二个缺口是撤回只存在于审计账与散文结论中:

- 历史 run 仍正确保留 `VERIFIED_TOOL_READY`（不可改写）;
- 本机 `tool.json` 与注册表也仍据历史 verdict 显示可用;
- `tool list` 只有 `OK/MISSING/UNVERIFIED`，无法表达已撤回;
- `tool mcp` 只检查历史 verification，仍可暴露已撤回工具。

因此，“历史验证事实”和“当前运营发布状态”必须分离。

## 二、目标与非目标

### 目标

1. 给 Tool Contract 增加**单一、机器可执行的输出合同**;
2. 在冻结/真实模型调用前拦住“声明 JSON、真值纯文本”这一类矛盾;
3. 在运行期独立解析实际 stdout，不依赖错误 expected 自证;
4. 建立 append-only 的运营发布状态，支持审核、撤回和可追溯恢复;
5. 让 registry、RepoProof 受管 MCP/升级发布与指标同时区分
   历史 READY 和当前运营状态;
6. 保持全部旧冻结合同可加载、旧 run 可重放、历史数字不回写。

### 非目标

- 不修订或重跑 `tool-pyspellchecker-tool-v1`;
- 不把自然语言语义一致性假装成形式化证明;
- 不引入 LLM verifier;
- 不在本阶段继续扩仓、跑新模型批次或比较 provider;
- 不复活 Studio UI（CLI-first 仍是已批准产品形态）;
- 不把 ToolContract 分叉成第二套独立模型。
- 不将 operational ledger 伪装成 OS 级执行策略;不通过删除、
  `chmod` 或 ACL 禁止用户直接运行保留在盘上的 `bin/<name>`。

## 三、裁决一:输出合同成为单一事实源

### 3.1 模型演化

在现有 `ToolInterfaceIO` 上做加法演化，旧合同默认值保持可加载。推荐形态:

```yaml
tool:
  interface:
    output:
      kind: stdout
      format: JSON
      contract:
        media_type: application/json
        root_type: object
        required:
          language: string
          token_count: integer
          suspicious_count: integer
          suspicious: array
```

约束:

- `format` 继续是人读短名;
- `contract` 是机器判定源，首版只支持足以覆盖现有本地工具形态的确定性
  子集:`text`、`json`、`json_object`、`json_array`、`json_lines`;
- JSON 对象可声明必需顶层字段及基本类型;
- 未声明 `contract` 的**旧冻结合同**沿旧语义加载;
- 新 draft 若 `format` 规范化为 JSON 家族却没有可执行 contract，D/T 闸
  返回 `REVIEW_REQUIRED` 或拒冻结，不能默认为“任意文本”;
- draft 中用户确认的 `capability.output_schema` 不再被装配器静默丢弃。

### 3.2 单一事实源消费者

下列产物必须从同一个输出合同生成，不允许各写一份:

1. 冻结 Tool Contract;
2. 交付 `tool.json`;
3. public/held-out 输出格式测试;
4. reference 彩排;
5. MCP `outputSchema`/描述;
6. 运营 audit 的默认解析器;
7. 人读 evidence report。

## 四、裁决二:两道确定性一致性门

### 4.1 冻结前静态门（零模型调用）

新检查编号沿 adequacy T 系追加，不重排旧键:

- **T6 output contract present**:结构化格式必须有可执行合同;
- **T7 golden output parseable**:所有 `expected_file` 必须按输出合同解析;
- **T8 exact structured golden exists**:JSON 家族至少有一组完整精确真值;
  `contains:` 可补语义断言，但不能单独证明结构合法;
- **T9 schema fields agree**:draft 的 output schema、ToolSpec 输出合同、
  manifest 投影必须无静默丢失或分叉。

检查器先接受以下合成负控:

| 控制 | 声明 | golden | 必须结局 |
|---|---|---|---|
| NC_json_plaintext | JSON object | `helo\nwrld\n` | 冻结前拒绝，模型调用 0 |
| NC_json_wrong_root | JSON object | `["helo"]` | T7/T9 拒绝 |
| NC_json_missing_field | 必需 `language` | 无该键对象 | T7/T9 拒绝 |
| POS_json_report | JSON object + required fields | 合法完整对象 | 全绿 |

旧的 text/Markdown/TSV/HTML 工具不因 JSON 规则误伤。

### 4.2 运行期独立门

装配器为每个公开与 held-out 成功样例生成独立的输出合同验证。至少满足:

- JSON 使用标准库严格解析;明确拒绝非 JSON 标准数值 `NaN` /
  `Infinity` / `-Infinity`,并拒绝解析为非有限浮点的 `1e400` /
  `-1e400`;
- 根类型和 required 字段/基础类型逐项检查;
- JSON Lines 逐个非空行解析;
- 失败节点以稳定前缀 `[tool-output-contract]` 进入 capability evidence;
- reference fake 彩排与真 agent 产物走同一检查;
- 不能因为 actual stdout 恰好等于错误 expected 而跳过格式解析。

该门仍编译为现有 capability pytest 节点，不给 completion gate 增加第五个
输入位，维持 RFC-010 的四验证器决策表。

## 五、裁决三:历史验证与运营状态分离

### 5.1 两个互不覆盖的事实

```text
historical_verification
  = 某次冻结合同下 completion gate 的不可改写结论

operational_release
  = 当前 task version 是否可作为 ACTIVE 成果被受管 MCP 暴露/完成升级发布
```

历史 `PASS_ADAPTED → VERIFIED_TOOL_READY` 永不改写。运营状态由新的
append-only 决策账折叠计算:

```text
REVIEW_REQUIRED  初次导出或尚无新鲜运营审计
ACTIVE           运营审计通过，可作为 RepoProof 受管发布的 ACTIVE 成果
REVOKED          审计失败、合同缺陷或用户明确撤回
```

若未来允许恢复，只能 append 新决定，不能删除旧 `REVOKED` 行。合同缺陷
造成的撤回原则上通过**新 task version**修复，不能在原 v1 上重写真值。

### 5.2 运营决策账

现行文件:`<dest_root>/.repoproof-release-decisions.jsonl`。每行至少包括:

```json
{
  "schema_version": 1,
  "tool": "example-tool",
  "task_id": "tool-example-tool-v1",
  "run_id": "...",
  "decision": "ACTIVE|REVIEW_REQUIRED|REVOKED",
  "reason_code": "FRESH_INPUT_PASS|OUTPUT_CONTRACT_MISMATCH|USER_WITHDRAWAL|...",
  "reason": "human-readable explanation",
  "evidence_sha256": "...",
  "decided_at": "RFC3339 UTC",
  "actor": "human|operator|migration"
}
```

纪律:

- append-only，损坏行判死而不是忽略;账本 JSON 同样严格拒绝
  `NaN` / `Infinity` / `-Infinity` 与溢出为非有限值的 `1e400` /
  `-1e400`;
- 不记录用户输入正文或可能敏感的完整 stdout，只记必要哈希/摘要;
- 同一工具的有效状态由最后一条合法决定折叠;
- `--scan` 只能补 registry 索引，不能伪造 ACTIVE 决定;
- 决策账是运营状态事实源，registry 只是缓存/索引。

### 5.3 CLI 与消费者

现行 CLI:

```text
repoproof tool audit <name> --input FILE --expected-file FILE
repoproof tool withdraw <name> --reason "..."
repoproof tool list
repoproof tool mcp <name>
```

- `audit` 可选择先走 `build.sh`，再以 fresh non-example input 真调用;
  build 成功后须重验 canonical 包树及 manifest/provenance identity；除
  opaque `.venv` 外，若换入 symlink/特殊文件或改写身份，则 append
  `BUILD_FAILED/REVOKED` 且不得执行 launcher;
- `withdraw` 只追加 REVOKED 决定，不删包、不改 `tool.json`;
- `list` 同时展示 `historical_verdict` 与 `operational_status`;
- `mcp` 对 `REVOKED` 或 `REVIEW_REQUIRED` 拒绝新生成;M5 adapter
  在运行期的 list/call 同样拒绝;
- 已经生成的 MCP 文件不自动删除（避免破坏性动作），但 list/检查明确标红;
- pipeline 导出成功后先记 `REVIEW_REQUIRED`，完成运营审计才进入 ACTIVE。

### 5.4 运营执法边界

`operational_status` 是 RepoProof 受管发布状态,不是操作系统的禁用位:

- `withdraw` 和 audit 失败仍保留原工具包与 `bin/<name>`;
- 用户绕过 RepoProof 直接手工执行原始 bin,不在 M5 的强制边界;
- M5 强制覆盖 RepoProof 管理的 audit、MCP 生成、新 adapter 的
  `tools/list` / `tools/call` 运行期复核,以及同名工具安全升级发布;
- pre-M5 adapter 无法被原地注入 runtime 执法,因此 list 以
  `LEGACY_SERVER_MUST_BE_DETACHED` 要求操作者从客户端解绑;
- 对外 claim 必须说“阻止 RepoProof 受管暴露/发布”,不得说
  “撤回后本地 CLI 无法执行”。

### 5.5 同名新 task version 安全升级

合同缺陷修复必须新建更高 task version;同一 `tool.name` 的安装
升级遵循以下顺序:

1. pipeline 在真模型调用前做只读 preflight;同 task 覆盖、降级/
   非严格递增版本、task 谱系错配、包/registry 错配都拒绝,
   避免在注定无法安全结算时消耗真模型预算;既有包而 registry 缺失、
   registry 指向缺失包或身份漂移同样 fail closed;
2. 存在 pre-M5 legacy MCP server 时,操作者必须先从客户端解绑
   并移走该 server 文件;否则拒绝升级,不自动删除;
3. installer 在 `<dest_root>/.repoproof-install.lock` 下重做 preflight,再在
   `dest_root` 同盘隐藏 staging 目录完整物化候选包;
4. 新 task version 的 `REVIEW_REQUIRED` 必须在交换包之前 append,
   防止新包继承旧 `ACTIVE`;
5. 旧包不改字节,用同盘原子 rename 移入
   `.repoproof-versions/<name>/<old-task>--<package-id>/`,候选包再
   原子切换到标准路径;
6. 新 provenance 记录 `replaces`;registry 通过同盘临时文件 + `fsync`
   + 原子 replace 结算,并把旧 task/run/contract/归档路径追加到
   `previous_versions`;
7. registry 原子 replace 是 package + registry 的提交/线性化点:
   在该点之前发现的可捕获失败自动把候选移回 staging、把旧归档移回
   canonical 路径;若中断发生于 replace 已提交之后且复核确认 registry
   已绑定新版,保留一致的新 package + registry,不能只回滚 package;
8. 新版 `REVIEW_REQUIRED` 不回删。提交前恢复旧包后,旧 task 与最后决定
   版本错配而 fail closed;成功切换后新版也仍是 `REVIEW_REQUIRED`,
   必须通过新 fresh-input
   audit 才能进入受管 `ACTIVE` 发布面。

上述自动恢复只覆盖进程能够捕获并完成恢复的失败。`SIGKILL`、掉电或
恢复动作本身失败可能停在两次 rename 之间,需要操作者盘查 canonical
package、archive、staging 与 registry;本 RFC 不承诺任意崩溃都能自动
回滚。

### 5.6 Package identity、锁序与路径安全

所有 package consumer 共用以下强绑定,不得从 registry 或目录名猜缺失值:

```text
canonical directory basename = manifest.name = provenance.tool
provenance.task_id            = tool-<name>-vN (N 为无前导零正整数)
manifest.verification.run_id  = provenance.run_id
manifest.verification.contract_sha256
                              = provenance.tool_contract_sha256
```

`evidence/provenance.json` 必需。registry、audit、MCP、迁移和升级发现
缺字段、错名、task 谱系不符或 run/contract 不一致即 fail closed。升级
另外要求真模型前严格加载整本 registry，并令其 canonical path、task、
run、contract 与历史 verdict 匹配包,再验证 archive identity、`provenance.replaces` 与
`previous_versions`。

package install/upgrade、registry scan/write、MCP 生成与 audit/withdraw
由共享 install 锁串行化;默认只读 `tool list` 不取该锁,观察到中间态时
fail closed。复合操作若还需 release ledger,固定按
`.repoproof-install.lock` → `.repoproof-release.lock` 获取。audit 从包身份
检查、真实执行至决定 append 全程持双锁,所以并发 withdraw 只能随后
追加。生成的 MCP runtime 对 `tools/list` / `tools/call` 同样持双锁;
`tools/call` 从 ACTIVE 与 executable 检查直到子进程执行、输出校验和
结果发布完成都不释放,避免 check/use 竞态。

canonical package 根和关键包树禁止 symlink/特殊文件。仅既有的顶层
普通目录 `.venv` 作为可再生环境例外,其内部视为 opaque;
`adaptation.patch` 不得创建或修改 `.venv`。release ledger、registry、
install/release lock、`.repoproof-versions` 归档链、生成 MCP 与输出目标
统一做 containment/no-follow;控制文件和输出还要求单链接普通文件。
包树中的 symlink/路径逃逸/非普通文件一律拒绝;控制文件或输出的
hardlink 也拒绝,不得跟随或覆盖。

### 5.7 MCP `--out` 的本次调用事务

生成的 adapter 不复用最终路径已有内容。每次声明 `--out` 时,它在最终
父目录创建一个 fresh 临时名字、删除占位,再把该不存在的名字交给本次
工具调用;工具必须在本次调用中创建结果。exit 0 后 adapter 以
`O_NOFOLLOW` 重新打开并验证单链接普通文件,按 v2 输出合同验证内容,
只有全部通过才原子 replace 到最终路径。最终目标原先为 symlink、目录、
特殊文件或 hardlink 时直接拒绝;执行/合同失败只清理临时文件,不把陈旧
文件冒充新结果。

## 六、指标口径

`scripts/tool_metrics.py` 保留原历史列，并增加运营列:

```text
historical_tool_ready
operational_ready
review_required
revoked
false_success
```

M4 批次二的历史事实必须同时保留:

- submitted = 12;
- accepted = 11;
- historical tool ready = 10;
- replay success = 10;
- operational ready = 9;
- false success = 1（10 个审计对象中）。

不得用运营撤回反向修改历史 run verdict，也不得只报 9 而隐藏流水线曾给出
10 个 READY。两种口径并列正是产品诚实性。

## 七、迁移原则

1. 所有现有冻结 contract/sidecar 字节不变;
2. 所有现有 run、classification、audit JSONL 字节不变;
3. 新模型字段全部有兼容默认值;
4. 首次迁移从已有 append-only operator audit 生成 release decision，来源哈希
   必须入账，不能凭散文猜状态;
5. `pyspellchecker` v1 迁移为 REVOKED，只改变运营决策账与 registry 投影;
6. 其工具目录不删除，历史 `tool.json.verification` 不改;
7. 若修复能力，必须新建 `tool-pyspellchecker-tool-v2`，重新确认合同并走
   正常单发流程;本 RFC 不授权该真发。

## 八、实施顺序（批准后）

1. **M5-a schema + negative controls**:模型加法演化，先钉四个输出合同控制;
2. **M5-b freeze/runtime gates**:T6–T9 + 自动生成运行期格式节点;
3. **M5-c release ledger**:append-only 决策账、折叠器、registry/list 投影;
4. **M5-d consumer enforcement**:MCP 与 pipeline 按运营状态执法;
5. **M5-e metrics + migration**:双口径指标、pyspellchecker 撤回状态迁移;
6. **M5-f user smoke**:零模型合成工具走 draft→rehearsal→audit→ACTIVE;
7. 全量测试、claims 检查、泄漏扫描、文档收口。

每一步先跑窄测，最后再跑全量;整个 M5 机制阶段默认零真模型调用。

## 九、成功判据

以下全部满足才可关闭 M5:

1. NC_json_plaintext 在冻结或 fake rehearsal之前/期间被拒，真实模型调用 0;
2. 合法 JSON object 正控通过冻结、reference 彩排与运行期解析;
3. wrong-root、missing-field、删掉输出验证器三种突变均被稳定抓住;
4. 既有 text/Markdown/TSV/HTML 合成任务无误伤;
5. 旧合同全量 `TaskContract.load_frozen(..., require_sidecar=True)` 通过;
6. `tool list` 对 pyspellchecker 显示历史 READY + 当前 REVOKED;
7. `tool mcp pyspellchecker-tool` 拒绝，且不删除历史包/证据;
8. registry scan 不会把 REVOKED 静默恢复成 ACTIVE;
9. metrics 同时报历史 READY 10、运营 READY 9、false-success 1;
10. 验证面零 LLM，冻结史/台账无改写，held-out 无新增泄漏;
11. 全量测试不少于当前基线且零失败;
12. README、HANDOFF 与机器事实源一致，公开 claim 检查通过。

## 十、用户裁决（已批准）

用户已确认以下四点:

1. **批准 M5 优先做 false-success 预防与撤回闭环，不继续跑第三批仓。**
2. **批准历史 verification 与当前 operational release 双状态并存。**
3. **批准新导出工具先为 REVIEW_REQUIRED，fresh-input audit 后才 ACTIVE。**
4. **批准 Studio UI 继续延后，先把 CLI/registry/MCP 的可信状态打通。**

四项裁决直接延续产品报告的核心差异化:
RepoProof 不以“agent 做完了”或“oracle 绿了”作为最终信任终点，而要继续
证明 oracle 与合同一致、当前发布状态也诚实可追溯。

## 十一、实施落点与迁移结果

M5 机制实现集中在以下单一事实路径:

- `domain.models.ToolOutputContract`：v2 机器输出合同；未知 schema 字段
  明确拒绝，旧 v1 冻结件维持 `contract=None` 兼容语义；
- `adoption.assembly.output_contract`：freeze/runtime/audit/MCP 共用的
  确定性严格 JSON 解析与投影；非标准 `NaN` / `Infinity` /
  `-Infinity` 及浮点溢出 `1e400` / `-1e400` 明确拒绝；
- `harness.contract_adequacy`：T6–T9；正式 runner 与 `task check` 均接通；
- `runner.tool_release`：严格 append-only 决策账、fresh audit、withdraw、
  M4 audit 幂等迁移；损坏行、task 版本错配与非 READY manifest 均判死；
- `runner.tool_registry` / `tool_mcp`：双状态展示与 ACTIVE 执法；新生成
  MCP adapter 每次 list/call 在 install→release 双锁内重读决策账，
  call 持锁至 fresh `--out` 校验/发布；未改写的 pre-M5 adapter 会被
  标为 `LEGACY_SERVER_MUST_BE_DETACHED`；
- `runner.tool_export` / `tool_pipeline`：真模型前升级预检、同盘 staging、
  REVIEW_REQUIRED-first 的原子包切换、旧包字节不变归档、registry
  replace 提交点、`previous_versions` 与失败恢复/fail-closed 协议；
- `runner.tool_paths`：canonical package identity、共享 install 锁、
  package/control/archive/MCP/output 的 containment 与 no-follow 纪律；
- `scripts/tool_metrics.py`：历史与运营口径并列，并复用发布模块的严格
  ledger/audit 解析语义。

2026-08-24 已从原始 `benchmarks/v2/m4_audits.jsonl` 的 22 行按源行哈希
迁移到本机 release ledger：首次 `imported=22`（ACTIVE 21 / REVOKED 1），
二次导入 `skipped=22`，证明幂等。盘面为 21 ACTIVE、2 REVIEW_REQUIRED、
1 REVOKED；两个早期 dogfood 工具没有 M4 fresh audit，故未伪造 ACTIVE。
`pyspellchecker-tool` 同时显示历史 `VERIFIED_TOOL_READY` 与运营
`REVOKED/OUTPUT_CONTRACT_MISMATCH`，`tool mcp` 返回拒绝。迁移前后 registry、
pyspell manifest 与原 audit ledger 的 SHA-256 均保持不变。

这里的“拒绝/撤回”严格指 RepoProof 受管 audit、MCP 与升级发布面。
原始工具包及 `bin/pyspellchecker-tool` 仍保留，用户直接手工执行不受
OS 级阻断；M5 没有声称提供该层控制。

关闭复验：M5 定向测试全绿；37 份 sidecar 冻结合同全部原样加载；
`1384 collected = 1324 passed + 60 skipped + 0 failed`。其中 1323 项在全量
进程通过；唯一受并行 OfferClaw 开发写入影响的保护目录 smoke 已在同一
RepoProof 工作树独立通过。改动 Python 文件 Ruff、`git diff --check` 与
公开 claim 检查均通过。机制与迁移阶段真实模型调用为 0，冻结
contract/sidecar、历史 runs/classification/audit JSONL 均未改写。
