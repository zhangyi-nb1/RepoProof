"""Risk Checker(RFC-003)— 合并双侧分析风险 + 派生交叉风险(!)。

这里的风险 = 不阻断、但必须由用户确认的事项(RISK_REVIEW 的输入)。
"""

from __future__ import annotations

import re

from repoproof.adoption.analysis.host_analyzer import HostProjectReport
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport

_RE_MIN_VER = re.compile(r">=\s*3\.(\d+)")


def _min_minor(spec: object) -> int | None:
    m = _RE_MIN_VER.search(str(spec or ""))
    return int(m.group(1)) if m else None


def collect_risks(host: HostProjectReport, repo: RepositoryReport) -> list[str]:
    risks: list[str] = []

    if repo.external_services.value:
        risks.append(
            f"目标仓库依赖外部服务客户端 {repo.external_services.value}——运行可能需要网络/账号,需你确认"
        )
    if repo.scan_stats.truncated or host.scan_stats.truncated:
        risks.append("源码扫描不完整(仓库过大)——分析结论覆盖面有限,需你确认可接受")
    if repo.tests.provenance == "UNKNOWN":
        risks.append("目标仓库没有测试目录——其行为只能靠参考校准确认,风险较高")

    host_min, repo_min = _min_minor(host.python_version.value), _min_minor(repo.python_version.value)
    if host_min is not None and repo_min is not None and repo_min > host_min:
        risks.append(
            f"Python 版本可能冲突:目标仓库要求 >=3.{repo_min},你的项目声明 >=3.{host_min}——需你确认"
        )

    # 双侧分析器自身发现的风险照单合并;剔除已由 policy 以 blocker(×)
    # 或 question(?)表达过的类别,避免同一事项双重呈现
    _covered = ("GPU", "secret", "密钥", "无法固定版本", "许可证", "测试配置",
                "版本要求", "依赖声明", "无测试目录", "扫描不完整", "外部服务")
    for src_risks in (host.risks, repo.risks):
        for r in src_risks:
            if any(k in r for k in _covered):
                continue
            if r not in risks:
                risks.append(r)
    return risks
