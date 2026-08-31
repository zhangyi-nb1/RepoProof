# M6.2 离线多文件工作区资格测试手册

## 当前状态

- 工程候选已实现 `workspace_bundle_v1`、ToolSpec v4、目录 manifest、原子
  runtime、结构/格式/语义/运行验证、clean replay、Fresh audit、Studio 目录
  交互和 append-only incident 类型。
- 本文件不代表八仓已经运行。真实模型与资格批次仍需单独授权。
- 预注册文件中的 wheel manifest 必须在批次发车前补齐 SHA-256 并冻结；未补齐
  时批次状态是 `BLOCKED_BEFORE_EXECUTION`。
- `cli_v2` 四仓历史结论、旧合同、旧 run 和 release ledger 均不改写。

## 发车前盘面

```bash
git status --short
git rev-parse HEAD
git branch --show-current
git diff --check
.venv/bin/ruff check src tests scripts
.venv/bin/mypy src/repoproof
PYTHONPATH=. .venv/bin/pytest -q
```

还必须执行：

1. 生成每个固定依赖闭包的离线 wheelhouse manifest；
2. 将 wheel 名称、大小和 SHA-256 写入预注册清单；
3. 计算清单 SHA-256，之后不再编辑；
4. 记录当前 Git commit 与 `src/repoproof` Python tree SHA-256；
5. 确认默认 drafter/API gateway 与 mini-swe provider 预检通过，但不提前消费
   一次正式 Agent 发次；
6. 运行仓库特例扫描，新增 Core 命中必须为零。已有 legacy/Lab 命中只允许按
   冻结基线报告，不得扩大。

## 固定顺序

1. N0 Browser Use admission 负控；
2. B1 Cookiecutter；
3. B2 csvkit；
4. C1 pdfplumber；
5. C2 Trafilatura；
6. C3 NetworkX；
7. C4 Datasette；
8. C5 Textual；
9. C6 marimo。

真实案例无需因后续通用修复从第一仓重跑。每次通用修复后，所有已完成案例必须
在新 framework tree SHA 下重新运行零模型合同回归、结构验证和 clean replay；
对应真实模型 run、合同和 ledger 保持不变。

## 单案例操作

1. 只输入预注册的模糊需求，先做 admission 与仓库分析。
2. 检查模型建议仍是工作语言；采用建议只回填需求，不创建或冻结任务。
3. 审核公开 commitments、目录结构合同、fixture builder 和 3–4 个场景蓝图。
4. 由 builder 生成真实输入，由固定上游 reference 生成期望目录；确认至少三组。
5. 运行零模型演练。合同、fixture、reference、preflight 或 upstream 失败必须
   零 Agent、零 repair。
6. 用固定 mini-swe/API gateway 运行初次实现和最多两轮有界 repair。
7. 独立执行结构、格式、语义、反事实控制、运行验证和 clean replay。
8. 在主 Journey 生成新的 Fresh-audit 场景；不得上传两个普通文件替代目录真值。
9. 检查历史 verdict、当前 operational 状态和 package health 分栏。
10. 写入 append-only case terminal record；失败也必须有唯一 stage、owner、
    reason code 和 next action。

## Incident 处理

出现问题时先冻结 incident，不以仓库名命名修复：

```text
用户现象
 -> failure stage
 -> owner
 -> public normalized fingerprint
 -> 被违反的通用不变量
 -> 匿名合成负控（修复前必须失败）
 -> 通用层修复
 -> 同一负控转绿 + 全量回归 + 已完成案例零模型 replay
```

安全/false-success 类问题可在首例修复；其他问题只有在第二个独立任务出现相同
指纹后才能修改 Core。单例非安全问题只记录，不为了让案例通过而放宽合同、
verifier、replay 或 release gate。

`HarnessChangeEvidenceV1` 的两个 incident id 不是人工声明即可：writer 会重读
append-only incident，校验同一公开指纹，并要求两个不同 task version。失败的
v4 action 与每个失败 Agent 轮分别留 incident；错误原文、私有路径、目录哈希和
held-out 值均不进入公开 fingerprint。

## 关闭口径

- N0 必须在 admission 零模型拒绝。
- 八个真实案例都必须有唯一终态；失败不能显示 `ACTIVE`。
- 每次 Harness 修改有 `HarnessChangeEvidenceV1`。
- 不存在 held-out 泄漏、false-success、路径逃逸或新增仓库特例。
- B1、B2 和至少四个复杂案例成功，其中至少一个含 SQLite/二进制工作区，
  至少一个是可运行应用，才把 profile 从 `EXPERIMENTAL` 升为 `SUPPORTED`。
- Product 记录的所有 Benchmark 计分字段保持 false。

## 对外表述

允许：RepoProof 在受支持的公开 Python、本地 CPU、离线工作区范围内，能把一项
能力构造成经过独立验证和 clean replay 的多文件本地工具；本批给出九个固定案例
的记录结果。

禁止：把案例通过率说成任意仓库成功率，把 Agent 自述称为 verified，或把历史
READY 与当前 ACTIVE 合成一个“成功”状态。
