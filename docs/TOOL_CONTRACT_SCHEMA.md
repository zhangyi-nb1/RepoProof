# ToolContract Schema 设计(M0 产出 · 依据 RFC-010 [D1][G1][G2])

- 状态:M0 设计稿,M1 实施前可修订;M1 首个契约冻结后本 schema 进入
  与 TaskContract 相同的演化纪律(加字段必须带默认值,旧契约零破坏)
- 依据:[RFC-010](rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md) §三/§四;
  现行 `src/repoproof/domain/models.py` 读码(2026-08-23,基线 `30b7a3a`)

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

**代码改动只有一处**:`TaskContract` 加 `tool: ToolSpec | None = None`
(§三)。其余全部是约定与模板。

## 二、完整契约示例(M1 pdf-table,注释即规范)

```yaml
task_id: tool-pdf-table-v1          # 工具谱系命名:tool-<slug>-v<n>

source_repo:
  url: https://github.com/jsvine/pdfplumber
  revision: guided                   # 产品模式统一 guided
  resolved_commit: <pinned>
  license: MIT
  distribution: pdfplumber
  import_module: pdfplumber

target_project:
  kind: local_tool                   # ← 新枚举值(kind 是自由 str,零代码改动)
  path: fixtures/tool_skeleton_pdf-table   # harness 生成的工具骨架(结构锚)
  package: pdf_table                 # 工具 Python 包名
  entry_point: pdf-table             # CLI 命令名(= tool.name)

requirement_spec_file: tool-pdf-table-v1.requirements.yaml
task_family: LOCAL-TOOL
adoption_shape: TOOL_ONBOARDING

tool:                                # ← 唯一新增分节(§三)
  name: pdf-table
  summary: 从 PDF 提取表格,输出 GitHub-flavored Markdown
  interface:
    usage: "pdf-table <input.pdf> [--out FILE]"
    input:  {kind: file, format: PDF}
    output: {kind: stdout, format: markdown-table}
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

## 三、`ToolSpec`:唯一新增的模型分节

```python
class ToolInterfaceIO(BaseModel):
    kind: str                  # file | stdin | stdout | out_file
    format: str                # 人读格式名(PDF / markdown-table / csv / json…)

class ToolInterface(BaseModel):
    usage: str                 # 一行用法;与骨架 argparse 必须一致(§五静态检查)
    input: ToolInterfaceIO
    output: ToolInterfaceIO
    exit_codes: dict[str, str] # 至少含 "0"/"1"/"2";语义冻结:
                               #   0=成功;1=用户错误(输入不存在/格式坏);2=内部错误

class ToolSpec(BaseModel):
    name: str                  # CLI 命令名;= target_project.entry_point
    summary: str               # 进 tool.json manifest 的一句话
    interface: ToolInterface
```

`tool: ToolSpec | None = None` 挂在 `TaskContract` 上;None = 旧谱系契约,
一切照旧。**`ToolSpec` 是三个消费者的单一事实源**:
1. 装配器生成骨架的 argparse 与 `tool.json`;
2. 接口契约测试(oracle/test_regression.py)的生成依据;
3. 交付期 manifest 一致性静态检查(§五)。

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

### 第二层:上游行为一致性(M2 进,M1 手工可选)

从上游自带测试套件选取与目标能力相关的子集,在**上游快照**上运行,
证明"pinned 版本在本环境行为正常"——它验的是上游与环境,不是 wrapper,
故独立成 oracle 文件(`test_upstream_conformance.py`),不与第一层混计。
M2 的 intake 自动化负责选取;M1 手工契约可留空。

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

**manifest 一致性静态检查**(交付期,新写,约 40 行):
`tool.json` 的 name/usage/exit_codes 必须与冻结契约 `ToolSpec` 完全一致,
不一致 = FAIL 理由(进 capability 侧 detail,不新增 gate 输入位——
completion_gate 决策表零改动,理由见
[TOOL_READY_GATE.md](TOOL_READY_GATE.md) §三)。

## 六、ContractAdequacyGate 扩条(M1 实施)

现有 13 条全保留,工具谱系加:

- **T1**:`task_family=LOCAL-TOOL` 时 `tool` 分节必须存在,
  `exit_codes` 至少覆盖 "0"/"1"/"2";
- **T2**:`tool.name == target_project.entry_point`(单一事实源不劈叉);
- **T3**:每个 `input_file/expected_file` 引用的 fixture 真实存在,
  其 sha256 进冻结清单(样例文件也是题面,缺文件 = INVALID_TASK_SPEC);
- **T4**:公开样例 ≥2 且 held-out ≥1(空 held-out = 防硬编码层失效,拒冻结)。

## 七、M1 改动清单预告(依赖序;实施时逐项过既有测试)

1. `models.py`:加 `ToolSpec` 三类 + `TaskContract.tool` 字段(默认 None);
2. `example_compiler.py`:`Example` 加 `input_file/expected_file`,
   `compile_pytest(mode="cli")` 模板;
3. `task_assembler.py`:新装配函数 `assemble_tool_task`(骨架模板见
   [TOOL_PACKAGE_LAYOUT.md](TOOL_PACKAGE_LAYOUT.md));旧 `assemble_task`
   原样保留服务旧谱系;
4. `contract_adequacy.py`:T1–T4 扩条(先写"喂合成缺陷"的自证测试);
5. `prompt` 渲染:`local-tool-v1` profile;
6. probe:`direct_tool_probe.py`(直连上游跑同一 golden 样例,基线归因用)。
