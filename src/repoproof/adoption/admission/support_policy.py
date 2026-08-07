"""Support Policy(RFC-003)— 当前版本自动适配的硬性范围,规则表。

blockers(×,UNSUPPORTED):GPU 需求 / 无法固定 commit / 需要 secret。
questions(?,NEED_INFORMATION):license、安装方式、python 版本、
宿主测试命令等关键信息 UNKNOWN——系统不猜,请用户补。
confirmed(✓):静态分析确认的事实,展示给用户。
"""

from __future__ import annotations

from pydantic import BaseModel

from repoproof.adoption.analysis.host_analyzer import (
    UNKNOWN,
    HostProjectReport,
)
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport


class PolicyResult(BaseModel):
    confirmed: list[str] = []
    questions: list[str] = []
    blockers: list[str] = []


def evaluate_policy(host: HostProjectReport, repo: RepositoryReport) -> PolicyResult:
    confirmed: list[str] = []
    questions: list[str] = []
    blockers: list[str] = []

    # ---- blockers(硬性不支持) ----
    if repo.gpu.value is True:
        blockers.append(f"目标仓库需要 GPU(依据:{repo.gpu.evidence})——当前仅支持 CPU")
    if repo.commit.provenance == UNKNOWN:
        blockers.append("无法固定目标仓库版本(commit)——结果不可复现,不能自动适配")
    if repo.secrets_required:
        names = sorted({str(s.value) for s in repo.secrets_required})
        blockers.append(f"目标仓库要求环境密钥 {names}——当前不自动提供 secret")

    # ---- confirmed(✓) ----
    if repo.is_public.value is True:
        confirmed.append("目标仓库是公开仓库(匿名克隆成功)")
    if repo.commit.provenance != UNKNOWN:
        confirmed.append(f"版本可固定:commit {str(repo.commit.value)[:12]}")
    if repo.gpu.value is False:
        confirmed.append("CPU 即可运行(未发现 GPU 依赖)")
    if repo.license.provenance != UNKNOWN and "未识别" not in str(repo.license.value):
        confirmed.append(f"许可证:{repo.license.value}({repo.license.evidence})")
    if repo.public_api or repo.capability_candidates:
        confirmed.append(f"存在公开入口({len(repo.public_api)} 个可导入符号)")
    if host.test_command.provenance != UNKNOWN:
        confirmed.append(f"你的项目测试命令:{host.test_command.value}")

    # ---- questions(?,信息缺口) ----
    if repo.license.provenance == UNKNOWN or "未识别" in str(repo.license.value):
        questions.append("目标仓库许可证无法自动识别——请人工确认许可证及兼容性")
    if repo.install_method.provenance == UNKNOWN:
        questions.append("目标仓库安装方式未知——请确认如何安装/引入")
    if repo.python_version.provenance == UNKNOWN:
        questions.append("目标仓库未声明 Python 版本——请确认与你的项目版本兼容")
    if host.test_command.provenance == UNKNOWN:
        questions.append("你的项目没有可识别的测试命令——请提供,否则无法做回归确认")
    if not repo.public_api and not repo.capability_candidates:
        questions.append("未找到公开入口(__all__/顶层符号)——请指明要采用的接口")

    return PolicyResult(confirmed=confirmed, questions=questions, blockers=blockers)
