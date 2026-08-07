# RFC-002: Repository Analyzer(Guided Adoption · Phase 2)

- 状态:实施中(与实现同一 commit)
- 层:Task Preparation Layer(`adoption/analysis/repository_analyzer.py`)
- 依赖:复用 RFC-001 的静态扫描基元(Finding 三态 / 依赖解析 /
  py 文件遍历)——同包复用,不复制逻辑

## 与 Phase 1 的关键差异:网络边界

Host Analyzer 纯本地;Repository Analyzer 需要获取远端仓库内容。
本 RFC 把副作用钉死为**恰好一种**:

> `git clone --depth 1`(匿名)到 `upstream-cache/analysis/<slug>/`
> ——仓库自己的缓存区,绝不写用户项目、绝不写 evidence。

其余铁律不变:**目标仓库代码永不执行**(不 pip install、不 import、
不跑 setup.py)、不启动 Docker、零 LLM。分析全部是对 clone 下来的
文件做确定性静态扫描。

- "是否公开" 的操作定义:匿名浅克隆成功 ⇒ 公开(FACT,evidence=
  clone 结果);失败 ⇒ UNKNOWN(可能私有/不存在/网络故障,如实报错误)
- `resolved_commit`:clone 后 `git rev-parse HEAD`(FACT)
- 离线可测:`analyze_repository_dir(path)` 接受任意已就位的仓库目录
  (测试注入 fixture;真实入口 `analyze_repository(url)` 只是
  clone + 前者)。测试零网络,另对本地已缓存的 pinned
  python-frontmatter 快照做真实仓库自测

## 检测矩阵(§四 13 项,全确定性)

| # | 项 | 方法 | 来源标注 |
|---|---|---|---|
| 1 | 是否公开 | 匿名 clone 成败 | clone |
| 2 | License | LICENSE* 关键词 + pyproject `license` | LICENSE 文件 / pyproject |
| 3 | Commit/Tag | `git rev-parse HEAD` + 用户指定 revision | git |
| 4 | Python 版本 | requires-python | pyproject |
| 5 | 安装方式 | build-system/setup.py → pip;仅源码 → 源码复制(INFERENCE) | pyproject / 文件布局 |
| 6 | Dependencies | pyproject + requirements(复用 RFC-001 解析) | pyproject / requirements |
| 7 | Public API | 顶层包 `__all__` + 顶层 def/class 正则 | source code |
| 8 | CLI 入口 | [project.scripts] + `__main__.py` | pyproject / source |
| 9 | GPU 需求 | deps ∩ {torch,cuda…} + README CUDA 提及 | requirements / README |
| 10 | 外部服务 | deps ∩ {openai,redis,boto3…} | requirements |
| 11 | Secret 需求 | 源码/README 扫 `environ/getenv` 的 *_KEY/TOKEN/SECRET | source / README |
| 12 | Quickstart | README 首个代码块 | README |
| 13 | 测试情况 | tests/ 目录 + test_*.py 计数 | 文件布局 |

`capability_candidates`:顶层包导出符号 + 集成词根模块 →
`{name, interface, evidence}`,全部带定义位置;`runtime` 汇总
`{python, gpu, external_api}`。GPU/外部服务/Secret 检出即写入
`risks`——它们是 Phase 3 Admission 的直接输入。

## 输出

`RepositoryReport`(pydantic,`to_dict()`):§四 schema + 每项
Finding 三态 + `sources`(实际读过哪些文件)+ `scan_stats`。
UNKNOWN 永不猜。

## CLI

- `repoproof analyze-repo --url <github-url> [--revision <tag>]`(联网 clone)
- `repoproof analyze-repo --local-path <dir>`(离线,分析已有目录)

## 非目标

Admission 判定(Phase 3 消费本报告)、语义级 API 理解(LLM 参与在
Phase 4 的 Plan 层)、非 GitHub 托管、私有仓库鉴权。
