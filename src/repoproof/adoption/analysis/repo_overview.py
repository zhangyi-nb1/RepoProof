"""仓库概览(展示件)—— 让用户在写"我想要什么能力"之前先看懂这个仓库。

**定位必须先说死**:本模块的产物是**展示件**,不是判据。

- 它不进 draft 字段、不进冻结合同、不参与任何 gate;
- 它**不得自动填进用户的能力描述** —— 那等于让系统替用户写下"我要什么",
  而"我要什么"正是人闸唯一不可代劳的东西(计划确认那一关同理);
- 每一条都带**来源**(README 原文 / pyproject / 静态扫描),因为一份说不出
  出处的介绍,在这个项目里没有资格出现在用户面前。

零模型、零网络、纯提取:输入是已经分析完的 `RepositoryReport`。
可选的"模型总结/翻译"是**另一层**(drafter),产物同样只进展示层,
并且必须在 UI 上与本模块的原文摘录**分开标注**。
"""

from __future__ import annotations

from repoproof.adoption.analysis.repository_analyzer import RepositoryReport

_API_PREVIEW = 12          # 公开入口预览条数
_CANDIDATE_PREVIEW = 8


def _val(finding) -> str:
    return "" if finding is None else str(getattr(finding, "value", "") or "")


def build_repo_overview(report: RepositoryReport) -> dict:
    """→ {repository, headline, prose, quickstart, facts[], surfaces[], sources[]}

    `facts` 是"可指认的事实 + 出处"的成对列表,给 UI 逐条渲染。
    """
    facts: list[dict] = []

    def fact(label: str, finding, *, fallback: str = "") -> None:
        value = _val(finding) or fallback
        if not value:
            return
        facts.append({
            "label": label,
            "value": value,
            "evidence": str(getattr(finding, "evidence", "") or ""),
            "provenance": str(getattr(finding, "provenance", "") or ""),
        })

    fact("许可证", report.license)
    fact("Python 版本", report.python_version)
    fact("安装方式", report.install_method)
    fact("可固定版本", report.commit)
    if report.dependencies:
        facts.append({"label": "运行期依赖",
                      "value": "、".join(report.dependencies[:10])
                               + ("…" if len(report.dependencies) > 10 else ""),
                      "evidence": report.dependencies_evidence,
                      "provenance": "FACT"})
    else:
        facts.append({"label": "运行期依赖", "value": "无(零第三方依赖)",
                      "evidence": report.dependencies_evidence, "provenance": "FACT"})
    fact("是否需要 GPU", report.gpu)
    fact("是否依赖外部服务", report.external_services)
    if report.secrets_required:
        facts.append({"label": "需要的环境密钥",
                      "value": "、".join(sorted({_val(s) for s in report.secrets_required})),
                      "evidence": "静态扫描 os.environ 读取点", "provenance": "FACT"})
    fact("测试目录", report.tests)

    surfaces: list[dict] = []
    for f in report.public_api[:_API_PREVIEW]:
        surfaces.append({"kind": "公开符号", "value": _val(f),
                         "evidence": str(getattr(f, "evidence", "") or "")})
    for c in report.capability_candidates[:_CANDIDATE_PREVIEW]:
        surfaces.append({"kind": "能力候选", "value": str(getattr(c, "name", "") or c),
                         "evidence": str(getattr(c, "evidence", "") or "")})
    for f in report.cli_entry_points[:_API_PREVIEW]:
        surfaces.append({"kind": "CLI 入口", "value": _val(f),
                         "evidence": str(getattr(f, "evidence", "") or "")})

    prose = report.readme_excerpt or ""
    # headline 取**第一句有信息量的话**:README 首段常常只是项目名本身
    # (`# coolkit`),拿它当一句话介绍等于什么都没说。
    paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
    headline = next((p for p in paragraphs if len(p) >= 20), paragraphs[0] if paragraphs else "")
    headline = headline[:200]

    return {
        "repository": report.repository,
        "headline": headline,
        "prose": prose,
        "prose_source": "README 原文摘录(未经模型改写)" if prose else "",
        # quickstart 只在 provenance=FACT 时才是**真代码块**;INFERENCE/UNKNOWN
        # 时它的 value 是一句说明("README 存在但无代码块"),把那句话塞进
        # 代码框会让用户以为上手片段长这样(2026-08-27 浏览器实测发现)。
        "quickstart": (_val(report.quickstart)
                       if getattr(report.quickstart, "provenance", "") == "FACT" else ""),
        "quickstart_note": ("" if getattr(report.quickstart, "provenance", "") == "FACT"
                            else _val(report.quickstart)),
        "quickstart_evidence": str(getattr(report.quickstart, "evidence", "") or ""),
        "facts": facts,
        "surfaces": surfaces,
        "risks": list(report.risks),
        "sources": list(report.sources),
    }
