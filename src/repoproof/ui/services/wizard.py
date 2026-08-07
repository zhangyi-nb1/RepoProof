"""任务向导的输入校验(§六 适用性检查四态)。

重要边界:这里只做「表单输入是否完整/是否落在当前版本支持范围内」
的纯 UI 校验,产出 READY / NEED_INFO / UNSUPPORTED / RISK_REVIEW 四态。
它不是 Core 的判定逻辑,不替代 ContractAdequacyGate(开始前检查)、
不替代最终判定;真正的任务草稿生成复用既有 `repoproof task init`。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_GITHUB_URL = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/?$")


@dataclass
class AdmissionResult:
    state: str  # READY / NEED_INFO / UNSUPPORTED / RISK_REVIEW
    reason: str  # 一句话原因
    confirmed_facts: list[str] = field(default_factory=list)  # 系统已确认的事实
    next_step: str = ""  # 用户下一步
    executes_third_party_code: bool = True  # 是否会执行第三方代码
    missing: list[str] = field(default_factory=list)


def check_wizard_inputs(
    *,
    goal: str,
    project_path: str,
    repo_url: str,
    revision: str,
    needs_gpu: bool,
    risk_confirmed: bool,
) -> AdmissionResult:
    """确定性输入校验 → 四态。永不联网、永不调模型、永不写文件。"""
    missing = []
    if not goal.strip() or len(goal.strip()) < 10:
        missing.append("想实现的功能(至少一句完整的话)")
    if not project_path.strip():
        missing.append("你的项目路径")
    if not repo_url.strip():
        missing.append("目标仓库地址")
    if not revision.strip():
        missing.append("目标仓库版本号(Tag 或 Commit)")

    if missing:
        return AdmissionResult(
            state="NEED_INFO",
            reason=f"还有 {len(missing)} 项必填信息未填写",
            confirmed_facts=["已填写的内容都已通过格式检查" if len(missing) < 4 else "尚未开始检查"],
            next_step="补全下方标注的必填项后,再次点击「检查是否适合使用」",
            missing=missing,
        )

    if needs_gpu:
        return AdmissionResult(
            state="UNSUPPORTED",
            reason="当前版本只支持 CPU 环境,不支持需要 GPU 的目标仓库",
            confirmed_facts=["输入信息完整", "目标仓库被标记为需要 GPU"],
            next_step="更换一个 CPU 即可运行的目标仓库,或等待后续版本",
            executes_third_party_code=False,
        )

    if not _GITHUB_URL.match(repo_url.strip().rstrip("/") if repo_url.strip().endswith("/") else repo_url.strip()):
        return AdmissionResult(
            state="UNSUPPORTED",
            reason="当前版本只支持公开的 GitHub 仓库地址(https://github.com/作者/仓库名)",
            confirmed_facts=["输入信息完整", f"地址「{repo_url.strip()[:60]}」不是公开 GitHub 仓库格式"],
            next_step="改用目标项目在 GitHub 上的公开地址",
            executes_third_party_code=False,
        )

    if not risk_confirmed:
        return AdmissionResult(
            state="RISK_REVIEW",
            reason="任务会在隔离容器中下载并执行目标仓库的代码,需要你确认",
            confirmed_facts=[
                "输入信息完整,格式正确",
                "目标仓库是公开 GitHub 地址",
                "运行发生在 Docker 隔离容器中(用于隔离、销毁与复测,不是恶意代码安全沙箱)",
            ],
            next_step="确认你信任这个公开仓库后,勾选下方的风险确认,再继续",
        )

    return AdmissionResult(
        state="READY",
        reason="信息完整,目标仓库类型在当前支持范围内",
        confirmed_facts=[
            "想实现的功能已描述",
            "你的项目路径与目标仓库地址、版本号完整",
            "目标仓库是公开 GitHub 地址,CPU 环境",
            "你已确认在隔离容器中执行该仓库代码",
        ],
        next_step="进入下一步,确认采用计划",
    )
