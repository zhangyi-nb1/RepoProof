# ToolContract Schema 现行规范(RFC-010 [D1][G1][G2] + RFC-011 M5)

- 状态:**M5 已实施**;新 draft 使用 ToolSpec v2,旧冻结契约保持 v1 语义
- 依据:
  [RFC-010](rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md) §三/§四与
  [RFC-011](rfc/RFC-011-TOOL-CONTRACT-COHERENCE-AND-RELEASE-STATE.md) §三/§四
- 演化纪律:新字段必须有兼容默认值;冻结 contract/sidecar 不回写;
  新规则以 `tool.schema_version` 分界,不对 v1 补施 v2 语义

## 一、总设计原则:演化不分叉

**ToolContract 不是新模型,是 `TaskContract` 的一次谱系扩展。**
理由与 T3-INPROC/T3-SIDECAR 分叉时相同:能力定义变了要立谱系旁注,
但 pydantic 模型全部字段带默认值、`kind` 是自由字符串,加值零破坏
——12 份冻结历史契约与 1127 测试不动。

| 复用件 | 处置 |
|---|---|
| `sha256 sidecar 冻结` / `load_frozen` | 原样 |
| `SourceRepo`(url/revision/resolved_commit/license/distribution/import_module) | 原样——上游 pinned 语义完全一致 |
| `Environment` / `Constraints` / `Budgets` | 原样 |
| `Acceptance`(argv 列表) | 原样——验收载体沿用 pytest([D1]) |
| `RequirementSpec` + ContractAdequacyGate | 原样 + M1 扩条(§六) |
| `runtime_profile` | 原样,默认 `rt-inprocess-v1`(= [D4] 弱档);M2 加 import-hook profile |
| `task_family` | 新谱系值 **`LOCAL-TOOL`**(旁注,不改 task_id 规则) |
| `adoption_shape` | 新值 **`TOOL_ONBOARDING`** |

M0 时 `TaskContract` 只增加了 `tool: ToolSpec | None = None`;
M5 继续做加法演化:`ToolSpec.schema_version` 默认为 `1`,
`ToolInterfaceIO.contract` 默认为 `None`。因此旧 contract 加载结果不变,
而新 draft 由 D 闸强制使用 v2。

## 二、完整 v2 契约示例(示意,不改写已冻结 pdf-table v1)

```yaml
task_id: tool-pdf-table-v2          # 工具谱系命名:tool-<slug>-v<n>

source_repo:
  url: https://github.com/jsvine/pdfplumber
  revision: guided                   # 产品模式统一 guided
  resolved_commit: <pinned>
  license: MIT
  distribution: pdfplumber
  import_module: pdfplumber

target_project:
  kind: local_tool                   # ← 新枚举值(kind 是自由 str,零代码改动)
  path: fixtures/tool_skeleton_pdf-table-v2 # harness 生成的工具骨架(结构锚)
  package: pdf_table                 # 工具 Python 包名
  entry_point: pdf-table             # CLI 命令名(= tool.name)

requirement_spec_file: tool-pdf-table-v2.requirements.yaml
task_family: LOCAL-TOOL
adoption_shape: TOOL_ONBOARDING

tool:
  schema_version: 2                 # 新 draft 必须为 v2;v1 只用于冻结历史
  name: pdf-table
  summary: 从 PDF 提取表格,输出 GitHub-flavored Markdown
  interface:
    usage: "pdf-table <input.pdf> [--out FILE]"
    input:  {kind: file, format: PDF}
    output:
      kind: stdout
      format: markdown-table
      contract:
        media_type: text/markdown
        root_type: text
        required: {}
    exit_codes: {"0": success, "1": user_error, "2": internal_error}

capability:
  statement: >
    把 pdfplumber 的表格提取能力包装为本地 CLI 工具 pdf-table:
    输入一个 PDF 文件,输出其中全部表格的 Markdown 渲染;
    必须调用 pinned pdfplumber 实现;行为以公开样例为准;
    重复调用确定;完全离线 CPU-only。
  output_schema: MarkdownTables

environment: {os: linux, arch: arm64, python: "3.12", cpu_only: true,
              network_install: true, network_test: false}

constraints:
  forbidden: [gpu, privileged_container, oracle_write, model_download,
              network_at_test_time]
  editable_zones: [tool]             # agent 只能写工具骨架区
  forbidden_install_extras: []

budgets:                             # M1 起步值 = guided 默认;冻结前定值不回改
  max_agent_steps: 20
  max_wall_time_minutes: 30
  max_command_minutes: 5
  max_semantic_recoveries: 3
  max_same_action: 2
  max_patch_files: 12                # 工具包多文件交付,较 adapter 单文件放宽
  max_patch_lines: 600
  max_input_tokens_total: 400000
  max_output_tokens_total: 40000
  monetary_soft_cap_usd: 5.0

acceptance:
  capability_command: ["pytest", "-q", "/oracle/test_capability.py"]
  regression_command: ["pytest", "-q", "/oracle/test_regression.py"]
  probe_script: direct_tool_probe.py # M1 新增:直连上游探针(工具版)
```

## 三、`ToolSpec` v2 与 `ToolOutputContract`

```python
OutputFieldType = Literal[
    "any", "string", "integer", "number", "boolean",
    "object", "array", "null",
]

class ToolOutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: str
    root_type: Literal["text", "json", "object", "array", "json_lines"]
    required: dict[str, OutputFieldType] = Field(default_factory=dict)

class ToolInterfaceIO(BaseModel):
    kind: str                  # file | stdin | stdout | out_file
    format: str                # 人读格式名(PDF / markdown-table / csv / json…)
    contract: ToolOutputContract | None = None

class ToolInterface(BaseModel):
    usage: str                 # 一行用法;与骨架 argparse 必须一致(§五静态检查)
    input: ToolInterfaceIO
    output: ToolInterfaceIO
    exit_codes: dict[str, str] # 至少含 "0"/"1"/"2";语义冻结:
                               #   0=成功;1=用户错误(输入不存在/格式坏);2=内部错误

class ToolSpec(BaseModel):
    schema_version: int = 1    # 1=冻结历史;2=RFC-011 输出合同门禁
    name: str                  # CLI 命令名;= target_project.entry_point
    summary: str               # 进 tool.json manifest 的一句话
    interface: ToolInterface
```

`ToolOutputContract` 是有意限定的可执行子集,不伪装成完整 JSON
Schema:

- `json_object` / `json_array` / `jsonl` / `ndjson` 只是 draft 输入别名,
  模型分别归一为 `object` / `array` / `json_lines`;
- `media_type` 必须非空且与根类型同族;JSON 根必须声明 JSON/NDJSON
  media type,`text` 不得声明 JSON media type;
- `required` 只校验顶层字段与上述基本类型;`text` / `array`
  根不得声明 `required`;
- `extra="forbid"` 使未定义的合同键直接失败,避免拼错字段被静默
  忽略;
- `integer` / `number` 显式排除 Python `bool`,防止 JSON `true`
  被当作数字;
- JSON 路径使用严格解析:拒绝 JSON 标准之外的 `NaN` / `Infinity` /
  `-Infinity`,也拒绝解析为非有限浮点的 `1e400` / `-1e400`;它们不得
  因 Python 标准库的默认扩展或浮点溢出被当成 `number`。

`tool: ToolSpec | None = None` 挂在 `TaskContract` 上;`None` 是非工具旧谱系。
对 LOCAL-TOOL,`schema_version=1` + `contract=None` 是冻结 v1 的兼容语义;
不得因其人读 `format` 含 JSON 就倒推或补写合同。新 draft 的
D 闸要求 `schema_version == 2`,且 v2 必须有 `output.contract`。

**v2 `ToolSpec` 是单一事实源**:

1. 装配器生成骨架 argparse 与 `tool.json`;
2. public / held-out 接口与输出合同测试;
3. 交付期 manifest 一致性静态检查;
4. reference 彩排与真 agent 产物的实际 stdout 校验;
5. fresh-input 运营 audit;
6. MCP `outputSchema` 投影与调用结果校验。

装配器把 `schema_version` 投影为 manifest 的
`contract_schema_version`,保留用户确认的
`capability.output_schema`,并完整投影 `interface.output`。

## 四、样例三层细则([G2] 落地)

### 第一层:golden examples(用户确认冻结;唯一进 capability oracle 的层)

`Example` 模型扩展(example_compiler):

```yaml
examples:
  - input_file: fixtures/inputs/simple_table.pdf     # 文件输入(新增,二选一)
    expected_file: fixtures/expected/simple_table.md # 期望全文精确比对(规范化行尾)
  - input_file: fixtures/inputs/two_tables.pdf
    expected: "contains:| 姓名 | 金额 |"              # contains: 断言沿用
  - input: "--help"                                  # 字符串输入沿用(直接作 argv)
    expected: "contains:usage: pdf-table"
```

- `input | input_file` 二选一;`expected | expected_file` 二选一;
- held-out 切分沿用 `split_examples` 现行逻辑,**held-out 样例的
  input/expected 文件一并进 oracle fixtures,绝不进公开区**;
- 编译目标从"import 包调 `run(value)`"换成 **subprocess 跑 CLI**:
  `compile_pytest` 加 `mode="cli"` 模板——断言 exit code == 0 且输出匹配。
  这是 example_compiler 在 M1 的主要改动。
- **防硬编码是 held-out 层的存在理由**(产品口径独立性):agent 看得到
  公开样例,看不到 held-out;正控(硬编码全样例映射)只证明测试自洽,
  绝不交付。

#### v2 成功样例的独立 stdout 校验(M5)

对 v2,装配器把同一份 `ToolOutputContract` 验证器编译进每个
public 与 held-out 成功样例节点。执行顺序为:

1. subprocess 真调 CLI 并取得**实际 stdout**;
2. 不依赖 golden 内容,独立按输出合同解析实际 stdout;
3. 按 golden 做精确或 `contains:` 能力断言。

这意味着 actual 与错误 expected 恰好相等也不能跳过格式门。
JSON 使用严格标准库解析(包括拒绝 `NaN` / `Infinity` /
`-Infinity` 与溢出为非有限值的 `1e400` / `-1e400`);JSON Lines
逐个非空行跑同一严格解析;
`object` / `array` 根与 `required` 字段类型逐项校验。失败使用稳定
前缀 `[tool-output-contract]`进入 capability evidence,且错误不携带
stdout 原文。`--help` / `--version` 等 CLI 元数据路径不是能力输出,
不套用 JSON 输出合同。reference fake 彩排与真 agent 运行复用
同一批生成节点。

v1 不生成这一新校验;其历史 oracle 与重放语义保持不变。

### 第二层:上游行为一致性(M2-e 实施定稿)

从上游自带测试套件确定性选取与目标能力相关的子集(`intake/
upstream_conformance.select_upstream_tests`:关键词命中排序、上限、
不硬凑),证明"pinned 版本在本环境行为正常"——它验的是上游与环境,
不是 wrapper。

> **执行时机(html2md 彩排实测倒逼)**:落在 **materialize 期预检**
> (harness 侧已装上游的解释器跑,不健康=物化拒绝,记录落任务包
> `conformance.json`),**不进 run**。曾试 S0 health check:上游库属
> agent 的 lock 责任,S0 态骨架 venv 里没有它,收集必崩;若让 harness
> 预装上游,replay"从 agent 自锁 lock 重建"的执法点被打穿。run 期的
> 上游健康由 agent 装完后的 oracle 自然覆盖。

### 第三层:接口契约检查(装配器自动生成,进 regression)

不依赖能力语义、纯由 `ToolSpec` 推导的结构检查,即 **regression 在
工具谱系下的新所指**(RFC-010 §五 🟡):

| 检查 | 断言 |
|---|---|
| help 可达 | `<tool> --help` exit 0 且含 usage 行 |
| 用户错误语义 | 不存在的输入文件 → exit 1,stderr 非空,stdout 空 |
| 格式错误语义 | 坏格式输入(如伪 PDF)→ exit 1,不是 traceback 裸奔(exit 2) |
| 确定性 | 同一输入两次运行输出字节一致 |
| 离线 | network_test=false 环境下全部通过(由执行环境保证,测试断言不 mock) |
| 输出纯净 | stdout 只含声明格式,诊断信息一律走 stderr |

## 五、RequirementSpec 映射与静态检查

**owner 枚举不改代码**,工具谱系下的所指约定:

| owner | 旧所指 | 工具谱系所指 |
|---|---|---|
| `ADAPTER` | agent 交付的 adapter | agent 交付的 wrapper 实现(main 逻辑 + 依赖锁定) |
| `HOST_INPUT_GUARD` | 宿主输入护栏 | **骨架预置层**:argparse、文件存在检查(harness 责任,不计 agent 能力) |
| `HARNESS` / `UPSTREAM` | 不变 | 不变 |

责任分界实例(M1 pdf-table):输入文件不存在 → exit 1 由骨架 argparse
层完成 = HOST_INPUT_GUARD;**坏 PDF 内容** → 捕获上游异常转 exit 1
= ADAPTER(这是能力的一部分:错误包装,Chonkie 负例的直接教训)。

**manifest 一致性静态检查**(交付期):
`tool.json` 的 name/usage/exit_codes 必须与冻结契约 `ToolSpec` 完全一致。
v2 另要求:

- `contract_schema_version == tool.schema_version`;
- manifest `interface.output` 与契约的 output(包含 `contract`)整体一致;
- `capability.output_schema` 必须原样投影,不得被 `output.format`
  覆盖;
- 人读 `output.format` 与机器 `contract.root_type` 必须同族。

不一致 = FAIL 理由(进 capability 侧 detail,不新增 gate 输入位——
completion_gate 决策表零改动,理由见
[TOOL_READY_GATE.md](TOOL_READY_GATE.md) §三)。

## 六、ContractAdequacyGate 的 LOCAL-TOOL 扩条(现行)

既有 C 系与通用 adequacy 检查全保留,工具谱系加:

- **T1**:`task_family=LOCAL-TOOL` 时 `tool` 分节必须存在,
  `exit_codes` 至少覆盖 "0"/"1"/"2";
- **T2**:`tool.name == target_project.entry_point`(单一事实源不劈叉);
- **T3**:每个 `input_file/expected_file` 引用的 fixture 真实存在,
  其 sha256 进冻结清单(样例文件也是题面,缺文件 = INVALID_TASK_SPEC);
- **T4**:公开样例 ≥2 且 held-out ≥1(空 held-out = 防硬编码层失效,拒冻结)。
- **T5**:工具自身包名不得与 pinned upstream 的 import module 或
  PEP 503 归一后的 distribution 同名,避免 PYTHONPATH 遮蔽上游;
- **T6 output contract present**:ToolSpec v2 必须声明
  `tool.interface.output.contract`;
- **T7 golden output parseable**:所有能力输出路径上的精确
  `expected` / `expected_file` 必须按合同可解析;`contains:` 只做
  补充语义断言,不充当完整结构真值;
- **T8 exact structured golden exists**:JSON 家族至少有一组
  非 `contains:` 的完整精确真值;
- **T9 schema fields agree**:`output.format` / `output.contract` 同族,
  `capability.output_schema` 非空且不丢失,manifest 中的完整 output
  投影与 `contract_schema_version` 与冻结契约一致。

T6–T9 只对 `tool.schema_version >= 2` 生效。装配器在写入任何
生成字节或 sidecar **之前**先跑同等 preflight;生成后
ContractAdequacyGate 再结合 `tool.json` 与样例文件复核。新 draft
的 D 闸另会拒绝降级为 v1 的规避。

## 七、实施锚点与兼容边界

| 职责 | 实施锚点 |
|---|---|
| 模型与 v1 默认 | `src/repoproof/domain/models.py` |
| 单一输出合同解析/测试/MCP 投影 | `src/repoproof/adoption/assembly/output_contract.py` |
| 新 draft D 闸 | `src/repoproof/adoption/intake/tool_confirm.py` |
| 写入前 T6–T9 preflight 与 manifest 投影 | `src/repoproof/adoption/assembly/tool_assembler.py` |
| public / held-out 实际 stdout 节点 | `src/repoproof/adoption/assembly/example_compiler.py` |
| 冻结前 adequacy 复核 | `src/repoproof/harness/contract_adequacy.py` |

兼容边界是结构性的:旧 contract 仍以 `TaskContract.load_frozen`
的 `require_sidecar=True` 路径按 sidecar 加载,旧 v1 不因 M5 被重写或套用
T6–T9;只有新 v2 题才获得输出合同保证。若修复旧题的合同
缺陷,必须立新 `task_id` / task version,不能改写 v1 真值。
同一 `tool.name` 可通过更高且同谱系的 task version 安全升级,
但升级是安装/发布协议,不是 schema 回写;具体执法见
[TOOL_READY_GATE.md](TOOL_READY_GATE.md) §6.4。

安装后的包身份也不得从 schema 字段猜测:`<dest_root>/<name>` 的
canonical 目录名、`tool.json.name` 与必需的
`evidence/provenance.json.tool` 必须相同;`task_id` 必须精确匹配
`tool-<name>-vN`(`N` 为无前导零正整数),manifest verification 的 `run_id` /
`contract_sha256` 必须与 provenance 的对应字段一致。registry、audit、
MCP 与升级都复用这组绑定;缺 provenance 或任一错配即 fail closed。
包树、锁、归档、MCP 与事务性 `--out` 的 no-follow/线性化约束见
[TOOL_READY_GATE.md](TOOL_READY_GATE.md) §6.3–§6.5。
