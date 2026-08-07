# RFC-001: Host Project Analyzer(Guided Adoption · Phase 1)

- 状态:实施中(本 RFC 与实现同一 commit)
- 层:**Task Preparation Layer**(`src/repoproof/adoption/`)——不触碰
  Agent loop / Verifier / Completion Gate / TaskPackage
- 运行约束(Plan 阶段铁律):**纯静态分析**——不执行项目代码、不写
  任何文件、不启动 Docker、不调用 LLM、不联网

## 动机

Guided Self-Service Adoption 的第一步是回答"这个项目是什么、哪里适合
接入新能力"。当前该判断完全依赖任务作者人工完成(Gate 6/7 的
consumer fixture 是手写的)。Host Analyzer 把可静态确认的部分自动化,
并诚实标注哪些是事实、哪些是推断、哪些不知道。

## 输入 / 输出

- 输入:`project_path`(本地目录)
- 输出:`HostProjectReport`(pydantic 模型,`to_dict()` 可序列化)

每个结论是一个 `Finding`:

```python
Finding(value, provenance: FACT|INFERENCE|UNKNOWN, evidence: str)
```

- **FACT**:直接来自代码/配置文件,evidence = 文件路径(+片段说明)
- **INFERENCE**:确定性启发式推断(规则写死,非模型),evidence = 推断依据
- **UNKNOWN**:无法确定——如实返回,禁止编造

报告字段(§三 schema):`project_type, python_version, package_manager,
entry_points, test_command, dependencies, frameworks, schemas,
integration_candidates, protected_paths, risks` + `scan_stats`(扫描
覆盖情况,防"看了一半当全看了")。

## 检测矩阵(全部确定性规则)

| # | 检测 | 方法 | provenance |
|---|---|---|---|
| 1 | pyproject.toml | tomllib 解析:name/requires-python/dependencies/scripts | FACT |
| 2 | requirements.txt | 逐行解析依赖名 | FACT |
| 3 | setup.py | 存在性 + 正则提取 install_requires(**绝不执行**) | FACT(存在)/INFERENCE(内容) |
| 4 | pytest 配置 | pytest.ini / [tool.pytest.ini_options] / tests/ 目录 | FACT / INFERENCE |
| 5 | FastAPI | 依赖声明 或 源码 `from fastapi import` | FACT |
| 6 | Flask | 同上 | FACT |
| 7 | CLI 入口 | [project.scripts] FACT;`__main__.py`/argparse/click/typer INFERENCE | 混合 |
| 8 | src 布局 | `src/<pkg>/__init__.py` 存在 | FACT |
| 9 | Pydantic Model | 正则 `class X(...BaseModel...)` 扫描 .py | FACT(定义位置) |
| 10 | 数据结构 | `@dataclass` / `TypedDict` / `NamedTuple` 扫描 | FACT(定义位置) |

集成点候选(integration_candidates)= INFERENCE:模块名命中
parser/ingest/loader/pipeline/process/index 等词根、或该文件定义了
schema 类,给出 file + reason。protected_paths = 规则默认
(`.git/ tests/ 配置文件 lockfiles`)。risks = 缺测试命令/缺版本声明/
缺 lockfile 等确定性检查。

## 扫描边界(防大仓爆炸,防"部分扫描冒充全量")

最多扫 400 个 `.py`、单文件 ≤ 200KB、跳过
`.git/.venv/node_modules/__pycache__/build/dist`。超限时
`scan_stats.truncated=true` 且相关字段的 provenance 降为
UNKNOWN/INFERENCE——报告永不假装看完了没看完的东西。

## 非目标(本 Phase 不做)

Repository Analyzer(Phase 2)、Admission(Phase 3)、Plan/LLM 参与
(Phase 4)、UI 接线(§十三,随后续 Phase)、非 Python 项目。

## 测试(§十五)

FastAPI 项目 / CLI(click)项目 / 普通 Python 包三类 fixture;
空目录 → 全 UNKNOWN 不编造;setup.py 永不执行(危险 fixture 佐证);
只读性(分析不创建/修改文件);对 RepoProof 自身自测(pyproject FACT)。
