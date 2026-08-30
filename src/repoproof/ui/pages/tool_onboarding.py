"""Create, review and build a Local Tool without requiring terminal usage."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import uuid
from pathlib import Path
from typing import Literal

import streamlit as st

from repoproof.ui.product_theme import (
    apply_product_theme,
    hero,
    journey_stepper,
    section_intro,
)
from repoproof.ui.services import product_jobs, product_journeys
from repoproof.ui.services.product_mode import (
    default_output_contract,
    next_task_version_preview,
    parse_output_contract,
    tool_root,
    ui_state_root,
    validate_draft_output_examples,
)

st.set_page_config(page_title="新建工具 · RepoProof Studio", page_icon="🧰", layout="wide")
apply_product_theme()

hero(
    "从一句需求开始",
    "先生成可审阅的成功标准草稿，再放入你确认过的样例。只有人闸和确定性检查通过后，系统才会消耗真实模型预算。",
    kicker="New verified local tool",
)

job = product_jobs.product_job_state()
if job and job.get("alive"):
    st.info(f"正在执行：{job.get('label')}。可以离开本页，后台任务不会中断。")


def _service_gap(name: str, *params: str) -> str:
    """运行中的进程里,这个接口**在不在、能不能收这些参数**(LESSONS #50)。

    Streamlit 只重新 exec 页面文件,不重载它 import 的 services 模块。
    第一次咬人是"函数磁盘上有、进程里没有"(AttributeError);第二次是
    **签名变了** —— 函数还在,`hasattr` 照样通过,于是甩出
    `TypeError: got an unexpected keyword argument 'distribution'`
    (2026-08-28 用户实测,同一坑第三次)。所以只查存在性不够,得连参数
    一起查:页面要传什么,就验什么。
    """
    fn = getattr(product_jobs, name, None)
    if fn is None:
        return f"缺少接口 {name}"
    try:
        sig = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # 拿不到签名就不拦(宁可放行也不误伤)
        return ""
    missing = [p for p in params if p not in sig]
    return f"{name} 不认识参数 {missing}" if missing else ""


_STALE_WARNING = (
    "当前 Studio 进程加载的是**旧版服务模块**(Streamlit 只热重载页面,"
    "不重载后台服务)。**请重启 Studio 后再用本页功能**;"
    "已有的草稿和工具不受影响。"
)

# 本页会用到的服务接口及其参数 —— 在页面顶部一次性体检,而不是等你点了
# 按钮才炸。新增接口/参数时把它登记进来,这张表就是"页面对服务的期望"。
_SERVICE_EXPECTATIONS = (
    ("product_runtime_source_freshness", ()),
    ("read_repo_overview", ()),
    ("summarize_repo_overview", ("capability_goal",)),
    ("propose_example_candidates", ()),
    ("propose_audit_candidates", ("dest_root", "expected_task_id", "n", "offline")),
    (
        "materialize_audit_candidate",
        ("candidate", "dest_root", "expected_task_id"),
    ),
    ("start_tool_audit", ("expected_task_id",)),
    (
        "save_draft_review",
        (
            "distribution",
            "import_module",
            "license_id",
            "reference_lock",
            "semantic_commitments",
            "input_representation",
        ),
    ),
    ("confirm_draft_intent", ()),
)
_STALE_GAPS = [g for g in (_service_gap(n, *ps) for n, ps in _SERVICE_EXPECTATIONS) if g]
if not _STALE_GAPS:
    source_freshness = product_jobs.product_runtime_source_freshness()
    if not source_freshness.get("fresh"):
        _STALE_GAPS.append(
            str(source_freshness.get("reason_code") or "PRODUCT_RUNTIME_SOURCE_STALE")
        )
if _STALE_GAPS:
    st.error(f"{_STALE_WARNING}\n\n检测到:{'；'.join(_STALE_GAPS)}")
    # Do not merely warn: every action below this point may execute against the
    # stale module graph we just detected.  Stopping the render is the only
    # reliable way to keep semantic-only Core changes fail closed.
    st.stop()


def _require_service(name: str, *params: str) -> bool:
    gap = _service_gap(name, *params)
    if not gap:
        return True
    st.warning(f"{_STALE_WARNING}\n\n检测到:{gap}")
    return False


def _journey_stage(snapshot: dict) -> int:
    phase = str(snapshot.get("phase") or "NEW")
    if phase in {"RUNNING", "FAILED", "SEMANTIC_UNKNOWN"}:
        state = (
            snapshot.get("worker") or {}
            if phase == "RUNNING"
            else snapshot.get("action_result") or snapshot.get("worker") or {}
        )
        explicit_stage = state.get("journey_stage")
        if isinstance(explicit_stage, int) and 1 <= explicit_stage <= 5:
            return explicit_stage
        action = str(state.get("action") or "")
        return {
            "add": 1,
            "tool-add": 1,
            "build": 3,
            "tool-build": 3,
            "tool-build-rehearsal": 3,
            "build-real": 4,
            "tool-build-real": 4,
            "audit": 5,
            "tool-audit": 5,
        }.get(action, 1)
    return {
        "NEW": 1,
        "DRAFT": 2,
        "DRAFT_INCOMPATIBLE": 2,
        "FROZEN": 3,
        "REHEARSED": 4,
        "EXPORTED": 5,
        "ACTIVE": 5,
    }.get(phase, 1)


def _reviewed_requirement_briefs(summary_result: dict) -> list[dict]:
    """Recompute Core admission for every model proposal or fail closed.

    Model prose is useful for helping a non-expert articulate an intent, but it
    must not smuggle implementation details into the one-click adoption path.
    A malformed or technical set is therefore still visible through the normal
    summary, while *none* of its briefs becomes adoptable.
    """

    from repoproof.adoption.intake.tool_drafter import (
        DraftError,
        validate_repo_summary_document,
    )

    document = {
        "summary": summary_result.get("summary"),
        "requirement_briefs": summary_result.get("requirement_briefs"),
        "recommended_brief_id": summary_result.get("recommended_brief_id"),
    }
    try:
        validated = validate_repo_summary_document(document, allow_projected=True)
    except DraftError:
        return []
    return list(validated["requirement_briefs"])


def _adoptable_requirement_briefs(summary_result: dict) -> list[dict]:
    """Return proposals that are both deliverable and plain-language safe."""

    return [
        brief
        for brief in _reviewed_requirement_briefs(summary_result)
        if brief.get("support_status") == "SUPPORTED"
        and brief.get("adoption_status") == "ADOPTABLE"
    ]


def _start_new_journey() -> None:
    section_intro(
        "创建一项受管任务",
        "先让在线模型结合仓库证据分析你的能力目标，再由你确认并创建任务。",
    )
    drafter_state = product_jobs.online_drafter_status()
    if drafter_state.get("ready"):
        st.success(f"在线 LLM 辅助已就绪：{drafter_state.get('label')}。仓库分析、草稿和样例候选默认使用这条通道。")
    else:
        st.warning(
            f"在线 LLM 辅助不可用：{drafter_state.get('label')}。请用 API 网关启动 Studio 后再进行本轮资格测试。"
        )

    repo = st.text_input(
        "公开 GitHub 仓库",
        placeholder="https://github.com/owner/project",
        key="rp_journey_repo",
    )
    revision = st.text_input(
        "固定版本或 Commit（建议填写）",
        placeholder="v1.2.3 或完整 commit",
        key="rp_journey_revision",
    )
    analysis_signature = hashlib.sha256(f"{repo.strip()}\n{revision.strip()}".encode()).hexdigest()
    pending_adoption = st.session_state.pop("rp_pending_capability_adoption", None)
    if isinstance(pending_adoption, dict):
        pending_text = str(pending_adoption.get("text") or "").strip()
        if pending_adoption.get("signature") == analysis_signature and pending_text:
            # The capability widget has not been instantiated in this run yet,
            # so this is the one safe place to update its keyed value.
            st.session_state["rp_journey_capability"] = pending_text
            # A model suggestion is only an editable starting point.  Any
            # previously confirmed launch payload must be invalidated so the
            # user explicitly confirms the text that will reach Core.
            st.session_state.pop("rp_confirmed_capability", None)
            st.session_state["rp_capability_adoption_flash"] = {
                "ok": True,
                "message": "已把模型建议放入需求框；你仍可继续用自己的话修改，再决定是否创建任务。",
            }
        else:
            st.session_state["rp_capability_adoption_flash"] = {
                "ok": False,
                "message": "仓库或版本已经变化，旧建议没有被采用。请重新分析当前仓库。",
            }
    capability = st.text_area(
        "希望落地的单一能力",
        placeholder="先写你的目标；模型会结合仓库入口帮你发现缺失的输入、输出和边界。",
        height=120,
        key="rp_journey_capability",
    )
    adoption_flash = st.session_state.pop("rp_capability_adoption_flash", None)
    if isinstance(adoption_flash, dict):
        (st.success if adoption_flash.get("ok") else st.warning)(
            str(adoption_flash.get("message") or "需求描述已更新。")
        )

    analyze_col, static_col = st.columns(2)
    analyze_clicked = analyze_col.button(
        "让 LLM 分析仓库和这项能力",
        type="primary",
        width="stretch",
        disabled=not bool(drafter_state.get("ready")),
        help="先做匿名静态分析，再把 README 摘录、公开入口和你的能力目标交给在线模型。",
    )
    static_clicked = static_col.button(
        "仅查看静态仓库证据",
        width="stretch",
        help="零模型调用；不会执行上游代码。",
    )
    if analyze_clicked or static_clicked:
        if not repo.strip().startswith("https://github.com/"):
            st.error("请先填写公开 GitHub 仓库地址。")
        elif not _require_service("read_repo_overview"):
            pass
        else:
            with st.spinner("正在读取钉版仓库并分析公开入口……"):
                overview_result = product_jobs.read_repo_overview(repo.strip(), revision.strip() or None)
                summary_result: dict = {}
                if analyze_clicked and overview_result.get("ok"):
                    if _require_service("summarize_repo_overview", "capability_goal"):
                        summary_result = product_jobs.summarize_repo_overview(
                            overview_result["overview"],
                            offline=False,
                            capability_goal=capability,
                        )
                st.session_state["rp_journey_repo_analysis"] = {
                    "signature": analysis_signature,
                    "overview": overview_result,
                    "summary": summary_result,
                    "capability_goal": capability.strip(),
                }

    analysis = st.session_state.get("rp_journey_repo_analysis") or {}
    if analysis.get("signature") == analysis_signature:
        overview_result = analysis.get("overview") or {}
        if not overview_result.get("ok"):
            st.error(overview_result.get("error") or "仓库分析失败。")
        else:
            overview = overview_result.get("overview") or {}
            with st.container(border=True):
                st.markdown("#### 仓库与能力分析")
                if overview.get("headline"):
                    st.write(f"**仓库自述：** {overview['headline']}")
                summary_result = analysis.get("summary") or {}
                if summary_result.get("ok"):
                    st.info(f"**LLM 分析（{summary_result.get('drafter')}）**\n\n{summary_result.get('summary')}")
                    briefs = _reviewed_requirement_briefs(summary_result)
                    if briefs:
                        recommended = str(summary_result.get("recommended_brief_id") or "")
                        st.markdown("**适合这个仓库的需求表达**")
                        st.caption(
                            "以下是模型建议，尚未验证。采用只会回填上方需求框，不会创建任务、生成草稿或冻结合同。"
                        )
                        for index, brief in enumerate(briefs):
                            with st.container(border=True):
                                is_recommended = brief["brief_id"] == recommended
                                supported = brief.get("support_status") == "SUPPORTED"
                                adoptable = (
                                    supported
                                    and brief.get("adoption_status") == "ADOPTABLE"
                                )
                                if is_recommended and adoptable:
                                    suffix = " · 模型推荐 · 当前可交付"
                                elif is_recommended and supported:
                                    suffix = " · 模型推荐 · 需改成用户语言"
                                elif is_recommended:
                                    suffix = " · 模型推荐 · 当前不可交付"
                                elif adoptable:
                                    suffix = " · 当前可交付"
                                elif supported:
                                    suffix = " · 当前可交付 · 需改成用户语言"
                                else:
                                    suffix = " · 当前不可交付"
                                title = brief["title"] + suffix
                                st.write(title)
                                if brief.get("scenario"):
                                    st.caption(brief["scenario"])
                                if supported:
                                    st.write(brief["text"])
                                    if not adoptable:
                                        st.warning(
                                            "交付形状受支持，但模型措辞包含实现层表达；"
                                            "为保持需求口语化，本条不提供一键采用。"
                                        )
                                else:
                                    st.warning(
                                        "该建议被保留为真实需求，但超出当前交付 profile；"
                                        "系统不会要求模型删改需求，也不会提供一键采用。"
                                    )
                                    reasons = brief.get("support_reason_codes") or []
                                    if reasons:
                                        st.caption("Core 原因：" + "、".join(map(str, reasons)))
                                shape = brief.get("delivery_shape") or {}
                                if shape:
                                    st.caption(
                                        f"支持面 {shape.get('profile_id')} · "
                                        f"{shape.get('input_cardinality')} 个本地文件 → "
                                        f"{shape.get('output_cardinality')} 个 "
                                        f"{shape.get('output_extension')} 文本产物 · "
                                        f"{shape.get('network')}"
                                    )
                                st.caption(brief["reason"])
                                brief_key = hashlib.sha256(
                                    f"{brief['brief_id']}:{index}".encode()
                                ).hexdigest()[:12]
                                label = "采用推荐描述" if is_recommended else "采用这个描述"
                                if adoptable and st.button(label, key=f"rp_adopt_brief_{brief_key}"):
                                    st.session_state["rp_pending_capability_adoption"] = {
                                        "signature": analysis_signature,
                                        "brief_id": brief["brief_id"],
                                        "text": brief["text"],
                                    }
                                    st.rerun()
                        if st.button("保留原想法", key="rp_keep_original_capability"):
                            st.info("已保留你原来的需求描述；你仍可参考模型建议自行修改。")
                    elif summary_result.get("requirement_briefs"):
                        st.caption("模型建议包含不完整或过于技术化的内容，因此只展示摘要，不提供一键采用。")
                    else:
                        st.caption("模型只能依据下方仓库证据提出分析与措辞建议；它不会自动改写能力目标，也不参与最终判定。")
                elif summary_result:
                    st.error(summary_result.get("error") or "模型分析失败。")
                    if summary_result.get("recommended_action"):
                        st.caption(summary_result["recommended_action"])
                surfaces = list(overview.get("surfaces") or [])[:12]
                if surfaces:
                    st.markdown("**静态扫描到的公开入口**")
                    st.dataframe(
                        [
                            {
                                "类型": item.get("kind"),
                                "名称": item.get("value"),
                                "依据": item.get("evidence") or "—",
                            }
                            for item in surfaces
                        ],
                        hide_index=True,
                        width="stretch",
                    )
                risks = list(overview.get("risks") or [])[:3]
                if risks:
                    st.warning("需要确认：" + "；".join(str(risk) for risk in risks))
                analyzed_goal = str(analysis.get("capability_goal") or "")
                if analyzed_goal and analyzed_goal != capability.strip():
                    st.caption("能力描述已在分析后修改；需要时请重新点击 LLM 分析。")

    preferred_backend = os.environ.get(
        "REPOPROOF_DEFAULT_AGENT_BACKEND", "mini-swe"
    ).strip().lower()
    codex_is_default = preferred_backend in {"codex", "codex-cli", "subscription"}
    backend_options = [
        "mini-swe（API 网关）",
        "Codex CLI（ChatGPT 订阅）",
    ]
    backend_label = st.radio(
        "真实构建 Agent",
        backend_options,
        index=1 if codex_is_default else 0,
        horizontal=True,
        key="rp_journey_agent_backend",
        help=(
            "这只影响真实构建。当前启动配置默认使用 "
            f"{'Codex CLI' if codex_is_default else 'mini-swe'}；"
            "RepoProof 的合同、repair、独立验证和发布门保持不变。"
        ),
    )
    confirmed_payload = st.session_state.get("rp_confirmed_capability")
    confirmed_current = bool(
        isinstance(confirmed_payload, dict)
        and confirmed_payload.get("signature") == analysis_signature
        and confirmed_payload.get("text") == capability.strip()
    )
    if st.button(
        "确认当前需求描述",
        help=(
            "把当前输入框中的完整文本固定为下一次起草的参数。"
            "确认后再修改仓库、版本或需求会自动失效，避免后台收到陈旧建议。"
        ),
        key="rp_confirm_capability_for_launch",
    ):
        final_text = capability.strip()
        if len(final_text) < 8:
            st.error("请先用完整句子描述能力。")
        else:
            st.session_state["rp_confirmed_capability"] = {
                "signature": analysis_signature,
                "text": final_text,
            }
            st.rerun()
    if confirmed_current:
        st.success("已确认当前需求文本；后台起草只会接收这段已显示并确认的内容。")
    else:
        st.caption("采用建议或修改需求后，请先确认当前文本，再创建任务。")
    submitted = st.button(
        "创建任务并生成草稿",
        type="primary",
        disabled=not confirmed_current,
    )
    if not submitted:
        return
    clean_repo = repo.strip()
    # Use the explicit confirmation snapshot rather than a live widget value.
    # This turns the UI→Core seam into a two-step commit and prevents a rapid
    # edit/click sequence from launching with the previously adopted advice.
    clean_capability = str((confirmed_payload or {}).get("text") or "").strip()
    if not clean_repo.startswith("https://github.com/") or len(clean_capability) < 8:
        st.error("请填写公开 GitHub 仓库地址，并用完整句子描述能力。")
        return
    journey_id = uuid.uuid4().hex
    draft_dir = ui_state_root() / "drafts" / f"journey-{journey_id[:12]}"
    backend: Literal["codex-cli", "mini-swe"] = "mini-swe" if backend_label.startswith("mini-swe") else "codex-cli"
    try:
        journey = product_journeys.create_journey(
            journey_id=journey_id,
            source_repo_url=clean_repo,
            draft_dir=draft_dir,
            dest_root=tool_root(),
            agent_backend=backend,
        )
    except (OSError, ValueError) as exc:
        st.error(f"无法创建任务导航记录：{exc}")
        return
    result = product_jobs.start_tool_add(
        repo=clean_repo,
        capability=clean_capability,
        revision=revision.strip() or None,
        draft_dir=draft_dir,
        fake_drafter=False,
        journey_id=journey.journey_id,
    )
    if result.get("ok"):
        st.session_state["rp_active_journey_id"] = journey.journey_id
        st.session_state["rp_new_journey"] = False
        st.success(result.get("note") or "任务已创建，正在生成草稿。")
        st.rerun()
    else:
        st.error(result.get("error") or "草稿任务未能启动。")


def _primary_golden_errors(expected_bytes: bytes, contract_doc: dict, output_format: str) -> list[str]:
    """Validate a user-confirmed expected output before it is admitted as truth."""
    contract, contract_errors = parse_output_contract(
        json.dumps(contract_doc, ensure_ascii=False),
        output_format=output_format,
    )
    if contract_errors:
        return [f"OUTPUT_CONTRACT_INVALID: {detail}" for detail in contract_errors]
    if contract is None:  # pragma: no cover - defensive parser invariant
        return ["OUTPUT_CONTRACT_INVALID: 合同解析器未返回可执行合同"]
    try:
        expected_text = expected_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ["GOLDEN_OUTPUT_INVALID: 期望输出必须是 UTF-8"]

    from repoproof.adoption.assembly.output_contract import validate_output_text

    return [f"GOLDEN_OUTPUT_INVALID: {detail}" for detail in validate_output_text(expected_text, contract)]


def _render_draft_readiness_summary(readiness: dict) -> None:
    """Show public Core facts without exposing verifier/reference source."""

    summary = readiness.get("public_summary") or {}
    verifier_ready = bool(summary.get("semantic_verifier_ready"))
    commitment_count = int(summary.get("semantic_commitment_count") or 0)
    covered_count = int(summary.get("verifier_declared_commitment_count") or 0)
    coverage = str(summary.get("commitment_coverage") or "UNAVAILABLE")
    lock_ready = bool(summary.get("dependency_lock_ready"))
    columns = st.columns(3)
    columns[0].metric("独立语义验证器", "已就绪" if verifier_ready else "待补全")
    coverage_value = f"{covered_count}/{commitment_count}"
    coverage_delta = coverage
    if coverage == "RUNTIME_PENDING":
        coverage_value = f"{commitment_count} 项待运行复核"
        coverage_delta = "冻结/演练时动态检查"
    columns[1].metric(
        "公开承诺覆盖",
        coverage_value,
        coverage_delta,
    )
    columns[2].metric("固定依赖锁", "已就绪" if lock_ready else "待补全")
    if readiness.get("status") == "READY_TO_CONFIRM":
        st.success("Core 检查已通过；显式确认当前语义后即可进入冻结与演练。")
    elif readiness.get("ready"):
        st.success("Core 冻结 readiness 已通过。")
    else:
        reasons = [str(code) for code in readiness.get("reason_codes") or []]
        if reasons:
            st.caption("Core readiness：" + "、".join(reasons))


def _render_primary_contract_and_examples(journey: dict, fallback_review: dict) -> dict:
    """Render the complete stage-2 workbench in the primary Product Journey.

    Contract and examples are product inputs, not diagnostics.  They therefore
    live here by default; the advanced area remains a compatibility/debugging
    surface for raw paths, JSON and older tasks.
    """
    journey_id = str(journey["journey_id"])
    prefix = f"rp_main_{journey_id}"
    draft_dir = Path(journey["draft_dir"])
    review = product_jobs.read_managed_draft_review(draft_dir)
    if not review.get("ok"):
        review = fallback_review
    if not review.get("ok"):
        st.info("草稿仍在生成；完成后这里会直接出现合同、LLM 样例候选和样例输入入口。")
        return review

    draft_dir = Path(review["draft_dir"])
    draft = review["draft"]
    tool = draft.get("tool") or {}
    interface = tool.get("interface") or {}
    capability = draft.get("capability") or {}
    intent_contract = draft.get("_intent_contract") or {}
    semantic_commitment_rows = list(intent_contract.get("commitments") or [])
    delivery_inputs = list(
        ((intent_contract.get("delivery") or {}).get("requirements") or {}).get("inputs") or []
    )
    saved_input_representation = str(
        (delivery_inputs[0] if delivery_inputs else {}).get("representation")
        or "utf8_text"
    )
    source_repo = draft.get("source_repo") or {}
    dependency_lock = review.get("dependency_lock") or {}
    draft_readiness = review.get("draft_readiness") or {}
    saved_output_format = str((interface.get("output") or {}).get("format") or "")
    existing_contract = (interface.get("output") or {}).get("contract") or default_output_contract(
        saved_output_format
    )
    raw_signature = hashlib.sha256(str(review.get("raw_draft") or "").encode("utf-8")).hexdigest()[:12]
    flash = st.session_state.pop(f"{prefix}_flash", None)
    if flash:
        (st.success if flash.get("ok") else st.error)(flash.get("message") or "草稿状态已更新。")

    st.markdown("#### 1. 审核成功合同")
    st.caption("模型可以起草，但你确认的合同才是后续 Agent、独立验证和 clean replay 共同遵守的成功标准。")
    _render_draft_readiness_summary(draft_readiness)
    with st.form(f"{prefix}_contract_{raw_signature}"):
        tool_name = st.text_input(
            "工具名",
            value=str(tool.get("name") or ""),
            key=f"{prefix}_name_{raw_signature}",
        )
        summary = st.text_input(
            "一句话摘要",
            value=str(tool.get("summary") or ""),
            key=f"{prefix}_summary_{raw_signature}",
        )
        statement = st.text_area(
            "Core 编译的公开能力题面",
            value=str(capability.get("statement") or ""),
            height=140,
            key=f"{prefix}_statement_{raw_signature}",
            disabled=True,
            help="它由用户目标和下方公开行为承诺编译，不能绕过追踪链直接改写。",
        )
        semantic_commitments_text = st.text_area(
            "公开行为承诺（每行一条）",
            value="\n".join(
                str(item.get("public_text") or "")
                for item in semantic_commitment_rows
            ),
            height=150,
            key=f"{prefix}_semantic_commitments_{raw_signature}",
            help=(
                "模型提出的算法、规范化、错误和边界规则必须全部在这里公开。"
                "held-out 只能隐藏输入，不能隐藏规则。"
            ),
        )
        format_input, format_output = st.columns(2)
        input_format = format_input.text_input(
            "输入格式",
            value=str((interface.get("input") or {}).get("format") or ""),
            key=f"{prefix}_input_format_{raw_signature}",
        )
        output_format = format_output.text_input(
            "输出格式",
            value=saved_output_format,
            key=f"{prefix}_output_format_{raw_signature}",
        )
        input_representation = st.selectbox(
            "样例输入表示",
            options=["utf8_text", "binary"],
            index=1 if saved_input_representation == "binary" else 0,
            format_func=lambda value: (
                "UTF-8 文本（可由 LLM 起草候选）"
                if value == "utf8_text"
                else "二进制文件（需要上传真实文件）"
            ),
            key=f"{prefix}_input_representation_{raw_signature}",
            help=(
                "这是交付合同的一部分，不由 .pdf/.docx 等名称猜测。"
                "选择变化后需要重新确认合同。"
            ),
        )
        output_schema = st.text_input(
            "输出结构名称",
            value=str(capability.get("output_schema") or ""),
            key=f"{prefix}_output_schema_{raw_signature}",
        )
        st.caption("固定上游身份：自动分析不到时必须由你补全；这些值会进入冻结合同与依赖锁。")
        identity_distribution, identity_module, identity_license = st.columns(3)
        distribution = identity_distribution.text_input(
            "PyPI 包名",
            value=str(source_repo.get("distribution") or ""),
            key=f"{prefix}_distribution_{raw_signature}",
        )
        import_module = identity_module.text_input(
            "import 名",
            value=str(source_repo.get("import_module") or ""),
            key=f"{prefix}_module_{raw_signature}",
        )
        license_id = identity_license.text_input(
            "许可证",
            value=str(source_repo.get("license") or ""),
            key=f"{prefix}_license_{raw_signature}",
        )
        reference_lock = st.text_area(
            "固定依赖锁（每行一个 包名==精确版本）",
            value="\n".join(str(pin) for pin in dependency_lock.get("pins") or []),
            key=f"{prefix}_reference_lock_{raw_signature}",
            help=(
                "动态版本无法自动派生时请填写，例如 "
                "example-package==1.2.3；允许写完整的精确版本闭包。"
            ),
        )
        output_contract_text = st.text_area(
            "可执行输出合同",
            value=json.dumps(existing_contract, ensure_ascii=False, indent=2),
            height=150,
            key=f"{prefix}_output_contract_{raw_signature}",
            help="所有输出（包括上游参考输出与最终工具 stdout）都会由同一 ToolOutputContract 校验。",
        )
        with st.expander("高级：reference 与独立 verifier 源码", expanded=False):
            reference = st.text_area(
                "上游参考实现（必须真实 import 固定版本）",
                value=str(review.get("reference_impl") or ""),
                height=220,
                key=f"{prefix}_reference_{raw_signature}",
            )
            semantic_verifier = st.text_area(
                "独立语义验证器（冻结 oracle；不得复用参考实现）",
                value=str(review.get("semantic_verifier") or ""),
                height=220,
                key=f"{prefix}_semantic_verifier_{raw_signature}",
                help=(
                    "按公开行为承诺重算实际产物；Harness 只执行统一协议、"
                    "核验固定上游调用并绑定回执，不在 Core 中写领域特判。"
                ),
            )
        save_contract = st.form_submit_button("保存合同修改", type="primary")

    if save_contract:
        parsed_contract, contract_errors = parse_output_contract(
            output_contract_text,
            output_format=output_format,
        )
        if contract_errors:
            save_result = {"ok": False, "error": "；".join(contract_errors)}
        elif not _require_service(
            "save_draft_review",
            "distribution",
            "import_module",
            "license_id",
            "reference_lock",
            "input_representation",
        ):
            save_result = {"ok": False, "error": "请重启 Studio 后再保存合同。"}
        elif parsed_contract is not None:
            save_result = product_jobs.save_draft_review(
                draft_dir,
                tool_name=tool_name,
                summary=summary,
                statement=statement,
                semantic_commitments=[
                    line.strip()
                    for line in semantic_commitments_text.splitlines()
                    if line.strip()
                ],
                input_format=input_format,
                input_representation=input_representation,
                output_format=output_format,
                output_schema=output_schema,
                reference_impl=reference,
                semantic_verifier=semantic_verifier,
                output_contract=parsed_contract.model_dump(mode="json"),
                distribution=distribution,
                import_module=import_module,
                license_id=license_id,
                reference_lock=reference_lock,
            )
        else:  # pragma: no cover - parser always returns one side
            save_result = {"ok": False, "error": "OUTPUT_CONTRACT_INVALID"}
        if save_result.get("ok"):
            st.session_state[f"{prefix}_flash"] = {
                "ok": True,
                "message": save_result.get("note") or "合同修改已保存。",
            }
            st.rerun()
        st.error(save_result.get("error") or "合同保存失败。")

    if tool_name:
        try:
            preview = next_task_version_preview(tool_name)
        except (OSError, ValueError) as exc:
            st.error(f"任务版本谱系无法安全计算：{exc}")
        else:
            st.caption(f"冻结版本只读预览：`{preview['task_id']}`。{preview['note']}")

    if dependency_lock:
        lock_source = {
            "user": "用户提供",
            "derived": "系统按钉版上游派生",
            "missing": "缺失",
        }.get(str(dependency_lock.get("source")), "未知")
        lock_pins = "`、`".join(str(pin) for pin in dependency_lock.get("pins") or [])
        lock_text = f"依赖锁（{lock_source}）"
        if lock_pins:
            lock_text += f"：`{lock_pins}`"
        lock_text += f"\n\n{dependency_lock.get('note') or ''}"
        (st.error if dependency_lock.get("source") == "missing" else st.info)(lock_text)

    st.markdown("#### 2. 生成并确认代表性样例")
    input_mode = product_jobs.example_input_mode(draft_dir)
    binary_upload = bool(input_mode.get("ok") and input_mode.get("requires_upload"))
    if not input_mode.get("ok"):
        reason_codes = "、".join(str(code) for code in input_mode.get("reason_codes") or [])
        st.error(
            f"样例输入方式无法由合同确定：{input_mode.get('error') or '未知错误'}"
            + (f"（{reason_codes}）" if reason_codes else "")
        )
        st.caption(str(input_mode.get("recommended_action") or "请先修复合同。"))
    elif binary_upload:
        st.caption(
            f"当前输入是 {input_mode.get('format')} 二进制文件。LLM 只帮助列出应覆盖的场景，"
            "不会把一段文本伪装成文件；请在下方上传真实输入，固定版本上游再给出实际输出。"
        )
    else:
        st.caption(
            "默认流程由 LLM 只生成候选输入，固定版本的上游参考实现给出实际输出；"
            "每一条只有经你确认后才会写入验收样例。重新生成不会清空已确认样例。"
        )
    drafter_state = product_jobs.online_drafter_status()
    if drafter_state.get("ready"):
        st.success(f"LLM 样例助手已就绪：{drafter_state.get('label')}。")
    else:
        st.warning(f"LLM 样例助手不可用：{drafter_state.get('label')}。可暂用离线模板检查流程。")

    candidate_controls = st.columns([1, 1, 2])
    candidate_count = candidate_controls[0].number_input(
        "候选数量",
        min_value=1,
        max_value=8,
        value=4,
        key=f"{prefix}_candidate_count",
    )
    offline_candidates = candidate_controls[1].checkbox(
        "使用离线模板",
        value=not bool(drafter_state.get("ready")),
        key=f"{prefix}_candidate_offline",
        help="默认关闭并使用 LLM；只有网关不可用或只想做零模型检查时才开启。",
    )
    generate_candidates = candidate_controls[2].button(
        "查看 LLM 文件样例建议" if binary_upload else "让 LLM 生成样例候选",
        type="primary",
        key=f"{prefix}_candidate_generate",
        disabled=(
            not bool(input_mode.get("ok"))
            or not (binary_upload or offline_candidates or bool(drafter_state.get("ready")))
        ),
        help=(
            "二进制文件只展示 LLM 起草时给出的场景建议；实际输入仍由文件上传提供。"
            if binary_upload
            else "候选会包含常规、边界和畸形输入；期望输出仍来自固定上游的实际运行。"
        ),
    )
    candidate_state_key = f"{prefix}_candidates"
    generation_key = f"{prefix}_candidate_generation"
    if generate_candidates and _require_service("propose_example_candidates"):
        spinner = (
            "读取 LLM 起草时保存的文件场景建议……"
            if binary_upload
            else "LLM 生成候选输入 → 固定版本上游逐条运行并校验输出……"
        )
        with st.spinner(spinner):
            candidate_result = product_jobs.propose_example_candidates(
                draft_dir,
                n=int(candidate_count),
                offline=offline_candidates,
            )
        if candidate_result.get("ok"):
            st.session_state[generation_key] = int(st.session_state.get(generation_key) or 0) + 1
        candidate_result["generation"] = int(st.session_state.get(generation_key) or 0)
        candidate_result["draft_dir"] = str(draft_dir.resolve(strict=False))
        st.session_state[candidate_state_key] = candidate_result

    candidate_result = st.session_state.get(candidate_state_key) or {}
    if candidate_result.get("draft_dir") != str(draft_dir.resolve(strict=False)):
        candidate_result = {}
    if candidate_result and not candidate_result.get("ok"):
        st.error(candidate_result.get("error") or "样例候选生成失败。")
    elif candidate_result.get("manual_upload_required"):
        st.info(candidate_result.get("note") or "请上传真实二进制输入文件。")
        suggestions = list(candidate_result.get("suggestions") or [])
        if suggestions:
            st.markdown("**LLM 起草时建议覆盖这些场景：**")
            for suggestion in suggestions:
                st.markdown(f"- {suggestion}")
        else:
            st.caption("当前草稿没有保存具体场景建议，请按典型、边界和损坏输入分别准备文件。")
    elif candidate_result.get("ok"):
        usable_candidates = [
            candidate
            for candidate in candidate_result.get("candidates") or []
            if (
                candidate.get("upstream_output") is not None
                and not candidate.get("upstream_error")
                and candidate.get("admission_status") != "REJECTED"
            )
        ]
        failed_candidates = [
            candidate
            for candidate in candidate_result.get("candidates") or []
            if (
                candidate.get("upstream_error")
                or candidate.get("admission_status") == "REJECTED"
            )
        ]
        st.caption(f"候选来源：{candidate_result.get('drafter')} · {candidate_result.get('note')}")
        if candidate_result.get("shortfall"):
            st.warning(
                f"请求 {candidate_result.get('requested')} 条，目前只有 "
                f"{candidate_result.get('usable_count')} 条有可确认的上游实际输出。"
            )
        else:
            st.success(
                f"已得到 {candidate_result.get('usable_count')} / "
                f"{candidate_result.get('requested')} 条可确认输出。"
            )
        generation = int(candidate_result.get("generation") or 0)
        for index, candidate in enumerate(usable_candidates):
            with st.container(border=True):
                st.markdown(
                    f"**候选 {index + 1} · `{candidate['input_name']}`**"
                    + (f" — {candidate['why']}" if candidate.get("why") else "")
                )
                candidate_input, candidate_output = st.columns(2)
                input_text = candidate_input.text_area(
                    "模型候选输入（只读）",
                    value=str(candidate.get("input_text") or ""),
                    height=120,
                    key=f"{prefix}_candidate_input_{generation}_{index}",
                    disabled=True,
                )
                output_text = candidate_output.text_area(
                    "钉版上游实际输出（只读）",
                    value=str(candidate.get("upstream_output") or ""),
                    height=120,
                    key=f"{prefix}_candidate_output_{generation}_{index}",
                    disabled=True,
                )
                st.caption(
                    "输入与输出保持成对绑定；你只判断它是否表达了所需能力。"
                    "需要自定义内容时，请使用下方手工样例入口。"
                )
                if st.button(
                    "确认这一条并加入样例",
                    key=f"{prefix}_candidate_confirm_{generation}_{index}",
                ):
                    confirmed = product_jobs.confirm_candidate_as_example(
                        draft_dir,
                        candidate,
                        expected_text=output_text,
                        input_text=input_text,
                    )
                    if confirmed.get("ok"):
                        st.session_state[f"{prefix}_flash"] = {
                            "ok": True,
                            "message": confirmed.get("note") or "样例已确认。",
                        }
                        st.rerun()
                    st.error(confirmed.get("error") or "样例确认失败。")
        if failed_candidates:
            st.warning("部分候选未通过上游执行、输出合同或独立语义预筛，不能成为成功样例。")
            st.dataframe(
                [
                    {
                        "输入": str(candidate.get("input_text") or "")[:60] or "（空）",
                        "未准入原因": (
                            ", ".join(candidate.get("admission_reason_codes") or [])
                            or candidate.get("upstream_error")
                        ),
                    }
                    for candidate in failed_candidates
                ],
                hide_index=True,
                width="stretch",
            )

    st.markdown("#### 3. 手工补充你已经核实的样例")
    st.caption("至少需要三组。文本可直接填写；DOCX、PDF、图片等二进制输入可直接上传。")
    text_sample_tab, file_sample_tab = st.tabs(["在线填写文本样例", "上传文件样例"])
    with text_sample_tab:
        text_input_column, text_output_column = st.columns(2)
        sample_name = text_input_column.text_input(
            "样例文件名",
            value="case_1.txt",
            key=f"{prefix}_manual_name",
        )
        sample_input = text_input_column.text_area(
            "样例输入内容",
            height=150,
            key=f"{prefix}_manual_input",
        )
        sample_output = text_output_column.text_area(
            "你核实过的期望输出",
            height=190,
            key=f"{prefix}_manual_output",
        )
        if st.button(
            "确认并加入这组文本样例",
            disabled=not sample_name.strip(),
            key=f"{prefix}_manual_add",
        ):
            expected_bytes = sample_output.encode("utf-8")
            output_errors = _primary_golden_errors(expected_bytes, existing_contract, saved_output_format)
            if output_errors:
                manual_result = {"ok": False, "error": "；".join(output_errors)}
            else:
                clean_name = Path(sample_name).name
                manual_result = product_jobs.add_golden_example(
                    draft_dir,
                    input_name=clean_name,
                    input_bytes=sample_input.encode("utf-8"),
                    expected_name=f"{Path(clean_name).stem}.expected.txt",
                    expected_bytes=expected_bytes,
                )
            if manual_result.get("ok"):
                st.session_state[f"{prefix}_flash"] = {
                    "ok": True,
                    "message": manual_result.get("note") or "文本样例已加入。",
                }
                st.rerun()
            st.error(manual_result.get("error") or "文本样例保存失败。")

    with file_sample_tab:
        upload_input_column, upload_output_column = st.columns(2)
        uploaded_input = upload_input_column.file_uploader(
            "输入文件",
            key=f"{prefix}_uploaded_input",
        )
        uploaded_output = upload_output_column.file_uploader(
            "期望输出文件（UTF-8）",
            key=f"{prefix}_uploaded_output",
        )
        if (
            st.button(
                "确认并加入这组文件样例",
                disabled=not (uploaded_input and uploaded_output),
                key=f"{prefix}_uploaded_add",
            )
            and uploaded_input is not None
            and uploaded_output is not None
        ):
            output_errors = _primary_golden_errors(
                uploaded_output.getvalue(),
                existing_contract,
                saved_output_format,
            )
            if output_errors:
                upload_result = {"ok": False, "error": "；".join(output_errors)}
            else:
                upload_result = product_jobs.add_golden_example(
                    draft_dir,
                    input_name=uploaded_input.name,
                    input_bytes=uploaded_input.getvalue(),
                    expected_name=uploaded_output.name,
                    expected_bytes=uploaded_output.getvalue(),
                )
            if upload_result.get("ok"):
                st.session_state[f"{prefix}_flash"] = {
                    "ok": True,
                    "message": upload_result.get("note") or "文件样例已加入。",
                }
                st.rerun()
            st.error(upload_result.get("error") or "文件样例保存失败。")

    fresh_review = product_jobs.read_managed_draft_review(draft_dir)
    if fresh_review.get("ok"):
        review = fresh_review
    examples = list(review.get("examples") or [])
    st.metric("当前已确认样例", len(examples), help="冻结前至少需要三组")
    if examples:
        st.dataframe(examples, hide_index=True, width="stretch")
    return review


def _render_journey_card(snapshot: dict) -> None:
    journey = snapshot["journey"]
    phase = str(snapshot.get("phase") or "NEW")
    tool_name = str(snapshot.get("tool_name") or "待命名工具")
    task_id = str(snapshot.get("task_id") or "尚未冻结")
    st.markdown(f"### {tool_name}")
    st.caption(str(journey.get("source_repo_url") or "仓库待确认"))
    journey_stepper(_journey_stage(snapshot))

    worker = snapshot.get("worker") or {}
    result = snapshot.get("action_result") or {}
    worker_status = str(worker.get("status") or "IDLE")
    worker_label = {
        "RUNNING": "执行中",
        "SUCCEEDED": "进程完成",
        "FAILED": "进程失败",
        "INTERRUPTED": "已中断",
        "IDLE": "空闲",
    }.get(worker_status, "状态未知")
    # Audit/withdraw are later operational actions and intentionally do not
    # emit a new pipeline verdict.  Keep showing the immutable historical
    # verification from Core instead of making READY disappear after audit.
    pipeline = str(
        result.get("pipeline_verdict")
        or snapshot.get("historical_verdict")
        or "尚未形成"
    )
    operational = str(snapshot.get("operational_status") or "UNVERIFIED")
    health = str(snapshot.get("package_health") or "NOT_EXPORTED")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Worker", worker_label)
    c2.metric("Pipeline", pipeline)
    c3.metric("Operational", operational)
    c4.metric("Package", health)
    st.caption(f"冻结任务：{task_id}。三类状态独立展示；Worker 成功不等于 Pipeline READY 或当前 ACTIVE。")

    if phase == "RUNNING":
        st.info("任务正在后台执行。离开本页不会中断；活动页会显示结构化结论。")
        if st.button("查看运行活动", type="primary", key="rp_journey_activity"):
            st.switch_page("pages/product_activity.py")
        return

    if result and not result.get("ok"):
        owner = str(result.get("failure_owner") or "UNKNOWN")
        stop = str(result.get("product_stop_code") or "UNCLASSIFIED_FAILURE")
        reasons = [str(x) for x in result.get("reason_codes") or []]
        st.error(f"任务停止：{stop}（责任方：{owner}）")
        if reasons:
            st.write("理由：" + "、".join(f"`{code}`" for code in reasons))
        st.info(str(result.get("recommended_action") or "请打开高级信息检查后再决定是否重试。"))

    if phase == "SEMANTIC_UNKNOWN":
        st.error("结构化结果或 Core 状态不可读取。为避免误报，当前任务按不可操作处理。")
        st.code(str(snapshot.get("semantic_error") or "CORE_STATUS_UNAVAILABLE"))
        return

    if phase == "DRAFT_INCOMPATIBLE":
        readiness = ((snapshot.get("draft_review") or {}).get("draft_readiness") or {})
        reasons = [str(code) for code in readiness.get("reason_codes") or []]
        st.error(
            "这份尚未冻结的草稿不具备当前可编辑结构所要求的"
            "用户目标—交付意图—公开承诺绑定，因此只能只读查看，"
            "不能继续补样例或进入构建。"
        )
        if reasons:
            st.write("Core 原因：" + "、".join(f"`{code}`" for code in reasons))
        st.info(str(readiness.get("recommended_action") or "请创建一项新任务。"))
        if st.button(
            "按当前流程创建新任务",
            type="primary",
            key=f"rp_restart_incompatible_{journey['journey_id']}",
        ):
            st.session_state["rp_new_journey"] = True
            st.rerun()
        return

    if phase == "FAILED":
        owner = str(result.get("failure_owner") or "UNKNOWN")
        action = str(result.get("action") or "")
        task_id_value = str(snapshot.get("task_id") or "")
        if owner in {"HARNESS", "UPSTREAM", "EXTERNAL"} and task_id_value:
            retry_rehearsal = action != "tool-build-real"
            retry_reason_codes = {str(code) for code in result.get("reason_codes") or []}
            if "LEGACY_MCP_MUST_BE_DETACHED" in retry_reason_codes:
                label = "旧 MCP 已解绑并备份后重试真实构建"
            else:
                label = (
                    "环境修复后重新运行零模型演练"
                    if retry_rehearsal
                    else "环境恢复后重试真实构建"
                )
            if st.button(label, type="primary", key=f"rp_retry_{journey['journey_id']}"):
                started = product_jobs.start_tool_build_real(
                    task_id_value,
                    Path(journey["dest_root"]),
                    agent_backend=str(journey.get("agent_backend") or "mini-swe"),
                    journey_id=str(journey["journey_id"]),
                    rehearsal_only=retry_rehearsal,
                    draft_dir=Path(journey["draft_dir"]),
                )
                (st.success if started.get("ok") else st.error)(started.get("note") or started.get("error"))
                if started.get("ok"):
                    st.rerun()
        elif owner in {"CONTRACT", "USER_INPUT"}:
            frozen = bool(task_id_value and not Path(journey["draft_dir"]).is_dir())
            label = "创建新任务版本" if frozen else "修正输入或合同"
            if st.button(label, type="primary", key=f"rp_fix_{journey['journey_id']}"):
                if frozen:
                    st.session_state["rp_new_journey"] = True
                else:
                    st.session_state["rp_advanced_editor"] = True
                st.rerun()
        else:
            st.warning("本次有界 repair 已终止，不会通过重新点击来无限消耗模型预算。")
            if st.button("创建新任务版本", type="primary", key=f"rp_new_version_{journey['journey_id']}"):
                st.session_state["rp_new_journey"] = True
                st.rerun()
        return

    if phase in {"NEW", "DRAFT"}:
        review = snapshot.get("draft_review") or {}
        readiness = (review.get("draft_readiness") or {}) if review.get("ok") else {}
        readiness_summary = readiness.get("public_summary") or {}
        r1, r2 = st.columns(2)
        r1.metric(
            "已确认代表性样例",
            int(readiness_summary.get("example_count") or 0),
            "至少 3 组",
        )
        r2.metric("Core readiness", str(readiness.get("status") or "等待草稿"))
        if not review.get("ok"):
            st.info("草稿尚未生成完成。若后台任务已停止，请到活动页查看唯一失败原因。")
        else:
            st.info("请在下方主流程核对合同，并用 LLM 候选或手工入口确认至少三组代表性样例。")
            review = _render_primary_contract_and_examples(journey, review)
        readiness = (review.get("draft_readiness") or {}) if review.get("ok") else {}
        confirmed = st.checkbox(
            "我已核对用户目标、每条公开行为承诺、上游版本、许可证和代表性样例",
            key=f"rp_confirm_{journey['journey_id']}",
        )
        ready = bool(readiness.get("ready_to_confirm"))
        if review.get("ok") and not ready:
            st.info(str(readiness.get("recommended_action") or "请先补全 Core readiness。"))
        if st.button(
            "确认合同并运行零模型演练",
            type="primary",
            disabled=not (ready and confirmed),
            key=f"rp_rehearse_{journey['journey_id']}",
        ):
            intent_confirmation = product_jobs.confirm_draft_intent(
                Path(journey["draft_dir"])
            )
            if intent_confirmation.get("ok"):
                started = product_jobs.start_tool_build(
                    draft_dir=Path(journey["draft_dir"]),
                    dest_root=Path(journey["dest_root"]),
                    rehearsal_only=True,
                    agent_backend=str(journey.get("agent_backend") or "mini-swe"),
                    journey_id=str(journey["journey_id"]),
                )
            else:
                started = intent_confirmation
            (st.success if started.get("ok") else st.error)(started.get("note") or started.get("error"))
            if started.get("ok"):
                st.rerun()
        return

    if phase in {"FROZEN", "REHEARSED"} and snapshot.get("task_id"):
        if phase == "FROZEN":
            st.warning("合同已冻结，但没有可确认的演练通过结果；为避免跳步，真实构建被禁用。")
            return
        st.info("零模型演练已通过。真实构建会调用所选 Agent，但最终结论仍由独立验证和 clean replay 给出。")
        if st.button("开始真实构建与独立验证", type="primary", key=f"rp_real_{journey['journey_id']}"):
            started = product_jobs.start_tool_build_real(
                str(snapshot["task_id"]),
                Path(journey["dest_root"]),
                agent_backend=str(journey.get("agent_backend") or "mini-swe"),
                journey_id=str(journey["journey_id"]),
            )
            (st.success if started.get("ok") else st.error)(started.get("note") or started.get("error"))
            if started.get("ok"):
                st.rerun()
        return

    if phase == "EXPORTED":
        st.info("历史验证产物已导出。还需一组未参与构建的新鲜输入完成 Fresh audit，才能进入 ACTIVE。")
        audit_prefix = f"rp_main_audit_{journey['journey_id']}"
        drafter_state = product_jobs.online_drafter_status()
        st.markdown("#### 让系统给一组新鲜输入")
        st.caption(
            "模型只提议一批构建阶段没有见过的输入；期望输出由冻结的参考实现真实调用钉版上游产生。"
            "它不是被测工具的自述，也不是模型猜出的答案。"
        )
        audit_controls = st.columns([1, 1, 2])
        audit_count = audit_controls[0].number_input(
            "候选数量",
            min_value=1,
            max_value=8,
            value=4,
            key=f"{audit_prefix}_count",
        )
        audit_offline = audit_controls[1].checkbox(
            "使用离线模板",
            value=not bool(drafter_state.get("ready")),
            key=f"{audit_prefix}_offline",
            help="默认关闭并使用 LLM；只在网关不可用时用零模型模板检查流程。",
        )
        propose_audit = audit_controls[2].button(
            "让 LLM 生成 Fresh audit 候选",
            type="primary",
            disabled=not (audit_offline or bool(drafter_state.get("ready"))),
            key=f"{audit_prefix}_propose",
        )
        candidate_state_key = f"{audit_prefix}_candidates"
        generation_key = f"{audit_prefix}_generation"
        if propose_audit and _require_service(
            "propose_audit_candidates", "dest_root", "expected_task_id", "n", "offline"
        ):
            with st.spinner("LLM 提议新鲜输入 → 冻结参考实现真实运行并生成独立期望输出……"):
                audit_candidates = product_jobs.propose_audit_candidates(
                    tool_name,
                    dest_root=Path(journey["dest_root"]),
                    expected_task_id=task_id,
                    n=int(audit_count),
                    offline=audit_offline,
                )
            if audit_candidates.get("ok"):
                st.session_state[generation_key] = int(st.session_state.get(generation_key) or 0) + 1
            audit_candidates["generation"] = int(st.session_state.get(generation_key) or 0)
            audit_candidates.setdefault("tool_name", tool_name)
            audit_candidates.setdefault("task_id", task_id)
            audit_candidates.setdefault("dest_root", str(journey["dest_root"]))
            st.session_state[candidate_state_key] = audit_candidates

        audit_candidates = st.session_state.get(candidate_state_key) or {}
        if audit_candidates and (
            audit_candidates.get("tool_name") != tool_name
            or audit_candidates.get("task_id") != task_id
            or audit_candidates.get("dest_root") != str(journey["dest_root"])
        ):
            audit_candidates = {}
        if audit_candidates and not audit_candidates.get("ok"):
            st.error(audit_candidates.get("error") or "Fresh audit 候选生成失败。")
            if audit_candidates.get("recommended_action"):
                st.info(str(audit_candidates["recommended_action"]))
        elif audit_candidates.get("ok"):
            candidates = list(audit_candidates.get("candidates") or [])
            st.caption(f"候选来源：{audit_candidates.get('drafter')} · {audit_candidates.get('note')}")
            if not candidates:
                st.warning("这一批输入没有一条能被冻结参考实现接住，请重新生成或改用下方文件回退。")
            generation = int(audit_candidates.get("generation") or 0)
            for index, candidate in enumerate(candidates):
                input_text = str(candidate.get("input_text") or "")
                expected_text = str(candidate.get("upstream_output") or "")
                if (
                    candidate.get("input_text") is None
                    or candidate.get("upstream_output") is None
                ):
                    continue
                with st.container(border=True):
                    st.markdown(
                        f"**新鲜候选 {index + 1} · `{Path(str(candidate.get('input_name') or 'fresh.txt')).name}`**"
                    )
                    if candidate.get("why"):
                        st.caption(str(candidate["why"]))
                    audit_input_col, audit_expected_col = st.columns(2)
                    audit_input_col.text_area(
                        "模型提议的输入",
                        value=input_text,
                        height=140,
                        disabled=True,
                        key=f"{audit_prefix}_input_{generation}_{index}",
                    )
                    audit_expected_col.text_area(
                        "冻结参考实现的实际输出",
                        value=expected_text,
                        height=140,
                        disabled=True,
                        key=f"{audit_prefix}_expected_{generation}_{index}",
                    )
                    if st.button(
                        "确认这组输入与参考真值并运行 Fresh audit",
                        key=f"{audit_prefix}_run_{generation}_{index}",
                    ):
                        if not _require_service(
                            "materialize_audit_candidate",
                            "candidate",
                            "dest_root",
                            "expected_task_id",
                        ):
                            continue
                        files = product_jobs.materialize_audit_candidate(
                            tool_name,
                            candidate=candidate,
                            dest_root=Path(journey["dest_root"]),
                            expected_task_id=task_id,
                        )
                        if not files.get("ok"):
                            st.error(files.get("error") or "无法保存 Fresh audit 材料。")
                        elif _require_service("start_tool_audit", "expected_task_id"):
                            started = product_jobs.start_tool_audit(
                                tool_name,
                                Path(files["input"]),
                                Path(files["expected"]),
                                Path(journey["dest_root"]),
                                expected_task_id=task_id,
                                journey_id=str(journey["journey_id"]),
                            )
                            (st.success if started.get("ok") else st.error)(
                                started.get("note") or started.get("error")
                            )
                            if started.get("ok"):
                                st.rerun()

        with st.expander("改用你已经核实的输入与期望文件", expanded=False):
            st.caption("这是网关不可用或你已有独立真值时的回退；上传不会绕过同一 Fresh audit。")
            a, b = st.columns(2)
            fresh_input = a.file_uploader("新鲜输入", key=f"rp_audit_in_{journey['journey_id']}")
            fresh_expected = b.file_uploader(
                "独立确认的期望输出",
                key=f"rp_audit_out_{journey['journey_id']}",
            )
            if (
                st.button(
                    "用上传文件运行 Fresh audit",
                    disabled=not (fresh_input and fresh_expected),
                    key=f"rp_audit_upload_{journey['journey_id']}",
                )
                and fresh_input is not None
                and fresh_expected is not None
            ):
                files = product_jobs.materialize_audit_files(
                    tool_name,
                    input_name=fresh_input.name,
                    input_bytes=fresh_input.getvalue(),
                    expected_name=fresh_expected.name,
                    expected_bytes=fresh_expected.getvalue(),
                )
                if not files.get("ok"):
                    st.error(files.get("error") or "无法保存 Fresh audit 材料。")
                elif _require_service("start_tool_audit", "expected_task_id"):
                    started = product_jobs.start_tool_audit(
                        tool_name,
                        Path(files["input"]),
                        Path(files["expected"]),
                        Path(journey["dest_root"]),
                        expected_task_id=task_id,
                        journey_id=str(journey["journey_id"]),
                    )
                    (st.success if started.get("ok") else st.error)(
                        started.get("note") or started.get("error")
                    )
                    if started.get("ok"):
                        st.rerun()
        return

    if phase == "ACTIVE":
        st.success("当前运营状态为 ACTIVE：历史验证、包身份和 Fresh audit 均由 Core 判定可用。")
        if st.button("打开工具库并使用", type="primary", key=f"rp_use_{journey['journey_id']}"):
            st.switch_page("pages/tool_library.py")


@st.fragment(run_every="2s")
def _render_running_journey(journey_id: str) -> None:
    """Poll only while a durable worker is actually RUNNING.

    The ordinary page remains event-driven.  Once the authoritative worker
    reaches a terminal state, one full rerun removes this timed fragment and
    renders the CLI/Core result.  This avoids both a permanently stale spinner
    and an always-on page refresh after completion.
    """

    try:
        journey = product_journeys.read_journey(journey_id)
        snapshot = product_journeys.journey_snapshot(journey)
    except (OSError, ValueError) as exc:
        st.error(f"Journey 状态不可读取：{exc}")
        return
    if snapshot.get("phase") != "RUNNING":
        st.rerun(scope="app")
    _render_journey_card(snapshot)


def _render_primary_journey() -> None:
    try:
        journeys = product_journeys.list_journeys()
    except (OSError, ValueError) as exc:
        st.error(f"Journey 导航目录不可读取：{exc}")
        journeys = []

    top_left, top_right = st.columns([4, 1])
    active = None
    if journeys and not st.session_state.get("rp_new_journey"):
        labels = {
            f"{row.tool_name or row.source_repo_url.rsplit('/', 1)[-1]} · {row.updated_at[:16]}": row
            for row in journeys
        }
        selected = top_left.selectbox("最近任务", list(labels), key="rp_journey_picker")
        active = labels[selected]
        st.session_state["rp_active_journey_id"] = active.journey_id
        if top_right.button("新任务", width="stretch"):
            st.session_state["rp_new_journey"] = True
            st.rerun()
    else:
        top_left.markdown("### 新的 Product Journey")
        if journeys and top_right.button("返回最近任务", width="stretch"):
            st.session_state["rp_new_journey"] = False
            st.rerun()

    if active is None:
        _start_new_journey()
    else:
        snapshot = product_journeys.journey_snapshot(active)
        if snapshot.get("phase") == "RUNNING":
            _render_running_journey(active.journey_id)
        else:
            _render_journey_card(snapshot)

    with st.expander("高级信息与旧任务"):
        st.caption("原始路径、ID、JSON、完整日志以及已有 frozen/rehearsed 任务只在这里展示。")
        cards = product_journeys.synthesized_read_only_cards()
        if cards:
            st.dataframe(cards, hide_index=True, width="stretch")
        else:
            st.write("没有需要合成展示的旧任务。")


_render_primary_journey()
st.toggle(
    "显示高级合同与样例编辑器",
    key="rp_advanced_editor",
    help="普通流程不需要复制草稿路径；仅在核对/修改合同与样例时打开。",
)
if not st.session_state.get("rp_advanced_editor"):
    st.stop()


tab_discover, tab_review, tab_build = st.tabs(["1 · 描述能力", "2 · 审核成功标准", "3 · 构建与验证"])

with tab_discover:
    section_intro("告诉系统你想保留哪项能力", "只选择一个输入输出明确、能用样例验证的能力。")
    _drafter_state = (
        product_jobs.online_drafter_status()
        if hasattr(product_jobs, "online_drafter_status")
        else {"ready": False, "backend": "UNKNOWN", "label": "请重启 Studio 加载新起草通道"}
    )
    if _drafter_state.get("ready"):
        st.success(
            f"在线智能辅助已就绪：{_drafter_state.get('label')}。"
            "摘要、在线起草和候选输入都使用这条通道；它们仍只是草稿，不参与判定。"
        )
    else:
        st.warning(f"在线智能辅助不可用：{_drafter_state.get('label')}。离线模板和静态分析仍可使用。")
    # 仓库与版本放在表单**之外**:这样填完仓库就能先读一份简介,再回来
    # 写"你想要的能力" —— 不了解这个仓库的人,写不出准确的能力描述。
    repo = st.text_input(
        "公开 GitHub 仓库",
        placeholder="https://github.com/owner/project",
        key="rp_repo_url",
    )
    revision = st.text_input("版本或 Commit（可选）", placeholder="v1.2.3 或完整 commit", key="rp_repo_rev")

    if st.button("读取仓库简介（零模型，只做静态分析）", disabled=not repo.strip()) and _require_service(
        "read_repo_overview"
    ):
        with st.spinner("匿名浅克隆并静态分析中……（不会执行仓库代码）"):
            st.session_state["rp_overview"] = product_jobs.read_repo_overview(repo, revision or None)
        st.session_state.pop("rp_overview_summary", None)

    _ov_result = st.session_state.get("rp_overview") or {}
    if _ov_result and not _ov_result.get("ok"):
        st.error(_ov_result.get("error") or "读取失败")
    elif _ov_result.get("ok"):
        _ov = _ov_result["overview"]
        with st.container(border=True):
            st.markdown("#### 这个仓库是做什么的")
            if _ov.get("headline"):
                st.markdown(f"**{_ov['headline']}**")
            if _ov.get("prose"):
                with st.expander("README 原文摘录（未经模型改写）", expanded=True):
                    st.write(_ov["prose"])
                    st.caption(f"来源：{_ov.get('prose_source') or 'README'}")
            if _ov.get("quickstart"):
                st.caption(f"上手片段（{_ov.get('quickstart_evidence') or 'README'}）")
                st.code(_ov["quickstart"], language="python")
            elif _ov.get("quickstart_note"):
                st.caption(f"上手片段：{_ov['quickstart_note']}（{_ov.get('quickstart_evidence') or 'README'}）")

            if _ov.get("facts"):
                st.markdown("**静态分析确认的事实**（每条都可追到出处）")
                st.dataframe(
                    [
                        {
                            "事实": f["label"],
                            "值": f["value"],
                            "依据": f.get("evidence") or "—",
                            "来源档位": f.get("provenance") or "—",
                        }
                        for f in _ov["facts"]
                    ],
                    hide_index=True,
                    width="stretch",
                )
            if _ov.get("surfaces"):
                st.markdown("**它对外提供的入口**（你要的能力大概率在这里面）")
                st.dataframe(
                    [
                        {"类型": s["kind"], "名称": s["value"], "依据": s.get("evidence") or "—"}
                        for s in _ov["surfaces"]
                    ],
                    hide_index=True,
                    width="stretch",
                )
            if _ov.get("risks"):
                st.warning("需要注意：" + "；".join(_ov["risks"][:3]))

            # 摘要**只走模型**:离线模板对"这个仓库是干什么的"帮不上忙
            # (它出的是格式骨架,不是对这一份 README 的复述)——用户实测
            # 反馈 2026-08-28。没有可用通道时不给一个没用的兜底,而是
            # 直接说清楚怎么才能用。
            _ready = bool(_drafter_state.get("ready"))
            if st.button(
                "让模型总结/翻译一下",
                disabled=not _ready,
                help=None if _ready else str(_drafter_state.get("label") or ""),
            ):
                with st.spinner("生成摘要中……"):
                    st.session_state["rp_overview_summary"] = product_jobs.summarize_repo_overview(_ov, offline=False)
            if not _ready:
                st.caption(
                    f"模型摘要暂不可用：{_drafter_state.get('label')}。"
                    "上面的 README 原文摘录与静态分析事实是零模型的，照常可读。"
                )
            _sum = st.session_state.get("rp_overview_summary") or {}
            if _sum and not _sum.get("ok"):
                st.error(_sum.get("error"))
            elif _sum.get("ok"):
                st.info(f"**模型摘要（{_sum.get('drafter')}）**\n\n{_sum['summary']}")
                st.caption(
                    "这是模型对上面原文的复述，**不是事实来源**；判定只认原文与静态分析。"
                    "它也不会替你决定要哪个能力——那一句必须你自己写。"
                )

    with st.form("tool_add_form"):
        capability = st.text_area(
            "你想要的能力",
            placeholder="例如：给一个 PDF 文件，提取其中所有表格并输出 Markdown。",
            height=110,
        )
        draft_default = str(ui_state_root() / "drafts" / "my-tool-draft")
        draft_dir = st.text_input("草稿保存位置", value=draft_default)
        offline = st.checkbox(
            "先用离线模板起草（零模型调用）",
            value=not bool(_drafter_state.get("ready")),
        )
        submitted = st.form_submit_button("分析仓库并生成草稿", type="primary")
    if submitted:
        result = product_jobs.start_tool_add(
            repo=repo,
            capability=capability,
            revision=revision or None,
            draft_dir=Path(draft_dir).expanduser(),
            fake_drafter=offline,
        )
        (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

    st.markdown("#### 系统会先回答")
    c1, c2, c3 = st.columns(3)
    c1.info("**是否支持**\n\nCPU、许可证、密钥和依赖风险是否在 v1 边界内。")
    c2.info("**还缺什么**\n\n哪些字段可自动起草，哪些真值必须由你确认。")
    c3.info("**是否值得运行**\n\n不合适的任务会直接拒绝，避免浪费模型预算。")

with tab_review:
    section_intro("把“什么叫完成”说清楚", "这里编辑的是题面，不是 Agent 的实现。冻结后任何模型都不能再改。")
    inspect_dir = Path(
        st.text_input(
            "草稿目录",
            value=st.session_state.get("rp_draft_dir", str(ui_state_root() / "drafts" / "my-tool-draft")),
            key="review_draft_dir",
        )
    ).expanduser()
    st.session_state["rp_draft_dir"] = str(inspect_dir)
    review_bundle = product_jobs.read_managed_draft_review(inspect_dir)
    if not review_bundle.get("ok"):
        st.info(f"生成受管草稿后回到这里审核；当前路径不可读取。 {review_bundle.get('error') or ''}")
    else:
        inspect_dir = Path(review_bundle["draft_dir"])
        _render_draft_readiness_summary(
            review_bundle.get("draft_readiness") or {}
        )
        draft = review_bundle["draft"]
        tool = draft.get("tool") or {}
        iface = tool.get("interface") or {}
        cap = draft.get("capability") or {}
        intent_contract = draft.get("_intent_contract") or {}
        semantic_commitment_rows = list(intent_contract.get("commitments") or [])
        delivery_inputs = list(
            ((intent_contract.get("delivery") or {}).get("requirements") or {}).get("inputs") or []
        )
        saved_input_representation = str(
            (delivery_inputs[0] if delivery_inputs else {}).get("representation")
            or "utf8_text"
        )
        saved_output_format = str((iface.get("output") or {}).get("format") or "")
        existing_contract = (iface.get("output") or {}).get("contract")
        if not existing_contract:
            existing_contract = default_output_contract(saved_output_format)
        # Streamlit 的控件值是**首次渲染时**定的:后来 `value=` 变了也不刷新
        # (会话状态优先)。实录 2026-08-28:用户先在草稿还空着时打开本页,
        # 控件把空值记住;起草器随后把草稿填满,页面却仍显示空白 —— 更危险
        # 的是,此时点「保存」会用这些空值**覆盖掉起草器的成果**。
        # 解法:让控件 key 跟着草稿内容走 —— 草稿一变就是新控件,按新值初始化。
        _sig = hashlib.sha256((review_bundle.get("raw_draft") or "").encode("utf-8")).hexdigest()[:12]
        with st.form("draft_review_form"):
            tool_name = st.text_input("工具名", value=str(tool.get("name") or ""), key=f"rv_name_{_sig}")
            summary = st.text_input("一句话摘要", value=str(tool.get("summary") or ""), key=f"rv_summary_{_sig}")
            statement = st.text_area(
                "Core 编译的公开能力题面",
                value=str(cap.get("statement") or ""),
                height=130,
                key=f"rv_stmt_{_sig}",
                disabled=True,
            )
            semantic_commitments_text = st.text_area(
                "公开行为承诺（每行一条）",
                value="\n".join(
                    str(item.get("public_text") or "")
                    for item in semantic_commitment_rows
                ),
                height=140,
                key=f"rv_semantics_{_sig}",
            )
            a, b = st.columns(2)
            input_format = a.text_input(
                "输入格式", value=str((iface.get("input") or {}).get("format") or ""), key=f"rv_in_{_sig}"
            )
            output_format = b.text_input("输出格式", value=saved_output_format, key=f"rv_out_{_sig}")
            input_representation = st.selectbox(
                "样例输入表示",
                options=["utf8_text", "binary"],
                index=1 if saved_input_representation == "binary" else 0,
                format_func=lambda value: (
                    "UTF-8 文本（可由 LLM 起草候选）"
                    if value == "utf8_text"
                    else "二进制文件（需要上传真实文件）"
                ),
                key=f"rv_input_representation_{_sig}",
                help="类型化合同字段；不根据文件名或格式标签推断。",
            )
            output_schema = st.text_input(
                "输出结构名称", value=str(cap.get("output_schema") or ""), key=f"rv_schema_{_sig}"
            )
            # 上游身份三件:分析器提取不到时归 owner=USER,却一直没有入口
            # (2026-08-28 核账)。提取得到时这里就是只读复核,不必改。
            _sr = draft.get("source_repo") or {}
            st.caption("上游身份（分析器已提取则无需改动；提取不到时必须由你定）")
            sd1, sd2, sd3 = st.columns(3)
            distribution = sd1.text_input(
                "PyPI 包名",
                value=str(_sr.get("distribution") or ""),
                key=f"rv_dist_{_sig}",
                help="装进会话的 Python 分发名（应与固定上游身份一致）",
            )
            import_module = sd2.text_input(
                "import 名",
                value=str(_sr.get("import_module") or ""),
                key=f"rv_mod_{_sig}",
                help="代码里 import 的模块名，通常与包名一致",
            )
            license_id = sd3.text_input("许可证", value=str(_sr.get("license") or ""), key=f"rv_lic_{_sig}")
            output_contract_text = st.text_area(
                "可执行输出合同（所有当前 Product 工具必填）",
                value=json.dumps(existing_contract, ensure_ascii=False, indent=2),
                help=("由 Core ToolOutputContract 验证；普通文本也必须明确声明 text/plain + text。"),
                height=130,
            )
            with st.expander(
                "高级：reference 与独立 verifier 源码",
                expanded=False,
            ):
                reference = st.text_area(
                    "参考实现（必须真实 import 固定上游）",
                    value=review_bundle["reference_impl"],
                    height=260,
                )
                semantic_verifier = st.text_area(
                    "独立语义验证器（冻结 oracle；不得复用参考实现）",
                    value=str(review_bundle.get("semantic_verifier") or ""),
                    height=260,
                    help=(
                        "这段代码属于任务 oracle，不交给 Agent。它必须通过固定上游"
                        "独立复核输入与最终产物。"
                    ),
                )
            save = st.form_submit_button("保存审核修改", type="primary")
        if save:
            parsed_contract, contract_errors = parse_output_contract(
                output_contract_text,
                output_format=output_format,
            )
            if contract_errors:
                result = {"ok": False, "error": "；".join(contract_errors)}
            elif not _require_service(
                "save_draft_review",
                "distribution",
                "import_module",
                "license_id",
                "input_representation",
            ):
                result = {"ok": False, "error": "请先重启 Studio 再保存（服务模块过期）"}
            elif parsed_contract is not None:
                result = product_jobs.save_draft_review(
                    inspect_dir,
                    tool_name=tool_name,
                    summary=summary,
                    statement=statement,
                    semantic_commitments=[
                        line.strip()
                        for line in semantic_commitments_text.splitlines()
                        if line.strip()
                    ],
                    input_format=input_format,
                    input_representation=input_representation,
                    output_format=output_format,
                    output_schema=output_schema,
                    reference_impl=reference,
                    semantic_verifier=semantic_verifier,
                    output_contract=parsed_contract.model_dump(mode="json"),
                    distribution=distribution,
                    import_module=import_module,
                    license_id=license_id,
                )
            else:  # pragma: no cover - defensive, parser returns one side
                result = {"ok": False, "error": "OUTPUT_CONTRACT_INVALID"}
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

        if tool_name:
            try:
                preview = next_task_version_preview(tool_name)
            except (OSError, ValueError) as exc:
                st.error(f"任务版本谱系无法安全计算：{exc}")
            else:
                st.caption(f"冻结版本只读预览：`{preview['task_id']}`。{preview['note']}")

        # ---------------- 样例助手:模型出输入、上游出输出、你逐条确认 ----------------
        _example_flash = st.session_state.pop("rp_example_flash", None)
        if _example_flash:
            (st.success if _example_flash.get("ok") else st.error)(_example_flash.get("message") or "样例状态已更新")
        with st.expander("🧪 不知道样例怎么写？让系统给你候选（真值仍由你确认）", expanded=False):
            st.caption(
                "分工是固定的：**候选输入**由模型出（输入不是判据）；**期望输出**由"
                "钉住的那一版上游**真跑**给出（不是模型猜的）；最后**每一条都要你点确认**"
                "才会成为验收真值。没有「全部确认」——一次点击只为一条负责。"
            )
            gp1, gp2, gp3 = st.columns([1, 1, 2])
            _n = gp1.number_input("要几条候选", min_value=1, max_value=8, value=4, key="rp_cand_n")
            _cand_offline = gp2.checkbox(
                "离线模板",
                value=not bool(_drafter_state.get("ready")),
                key="rp_cand_offline",
                help="零模型调用，先把流程走通",
            )
            if gp3.button("生成候选（含边界/畸形输入）", key="rp_cand_go") and _require_service(
                "propose_example_candidates"
            ):
                with st.spinner("模型出候选输入 → 钉版上游真跑……"):
                    _candidate_result = product_jobs.propose_example_candidates(
                        inspect_dir, n=int(_n), offline=_cand_offline
                    )
                    if _candidate_result.get("ok"):
                        st.session_state["rp_cands_generation"] = (
                            int(st.session_state.get("rp_cands_generation") or 0) + 1
                        )
                    _candidate_result["generation"] = int(st.session_state.get("rp_cands_generation") or 0)
                    _candidate_result["draft_dir"] = str(inspect_dir.resolve(strict=False))
                    st.session_state["rp_cands"] = _candidate_result

            _cr = st.session_state.get("rp_cands") or {}
            if _cr.get("draft_dir") != str(inspect_dir.resolve(strict=False)):
                _cr = {}
            if _cr and not _cr.get("ok"):
                st.error(_cr.get("error"))
            elif _cr.get("ok"):
                st.caption(f"候选来源：{_cr.get('drafter')} · {_cr.get('note')}")
                if _cr.get("shortfall"):
                    st.warning(
                        f"你请求 {_cr.get('requested')} 条可确认输出，目前只有 "
                        f"{_cr.get('usable_count')} 条。系统已完成最多两轮自动补候选；"
                        "其余失败输入保留在下方，便于你收紧能力描述或手工修改。"
                    )
                else:
                    st.success(f"已得到 {_cr.get('usable_count')} / {_cr.get('requested')} 条可确认的上游实际输出。")
                st.caption(
                    f"生成候选前后，磁盘中仍有 {_cr.get('confirmed_count', '—')} 条"
                    "已确认样例；重新生成候选不会清空它们。"
                )
                _usable = [
                    c for c in _cr["candidates"]
                    if (
                        c.get("upstream_output") is not None
                        and not c.get("upstream_error")
                        and c.get("admission_status") != "REJECTED"
                    )
                ]
                _errs = [
                    c for c in _cr["candidates"]
                    if (
                        c.get("upstream_error")
                        or c.get("admission_status") == "REJECTED"
                    )
                ]
                _generation = int(_cr.get("generation") or 0)

                for i, c in enumerate(_usable):
                    with st.container(border=True):
                        st.markdown(
                            f"**候选 {i + 1} · `{c['input_name']}`**" + (f" — {c['why']}" if c.get("why") else "")
                        )
                        e1, e2 = st.columns(2)
                        _in_text = e1.text_area(
                            "模型候选输入（只读）", value=c["input_text"], height=120,
                            key=f"rp_cand_in_{_generation}_{i}", disabled=True,
                        )
                        _out_text = e2.text_area(
                            "钉版上游实际输出（只读）",
                            value=c["upstream_output"],
                            height=120,
                            key=f"rp_cand_out_{_generation}_{i}",
                            disabled=True,
                        )
                        st.caption(
                            "输入与上游输出保持成对绑定；它是不是你要的能力，仍由你判断。"
                            "自定义内容请走手工样例入口。"
                        )
                        if st.button(
                            "✅ 我确认这一条，加入样例",
                            key=f"rp_cand_ok_{_generation}_{i}",
                        ):
                            r = product_jobs.confirm_candidate_as_example(
                                inspect_dir, c, expected_text=_out_text, input_text=_in_text
                            )
                            message = (r.get("note") or r.get("error") or "") + (
                                f"（真值来源：{r.get('truth_provenance')}）" if r.get("ok") else ""
                            )
                            if r.get("ok"):
                                st.session_state["rp_example_flash"] = {
                                    "ok": True,
                                    "message": message,
                                }
                                st.rerun()
                            else:
                                st.error(message)

                if _errs:
                    st.markdown("**这些候选没有进入合同成功域——它们做不成样例，但很有用**")
                    st.caption(
                        "Golden 样例只表达成功路径。这些是「这类输入会炸」的行为证据："
                        "把它们写进上面的**能力和边界**，别等真发时被隐藏验收撞出来。"
                    )
                    st.dataframe(
                        [{
                            "输入": (c["input_text"][:40] or "（空）"),
                            "未准入原因": (
                                ", ".join(c.get("admission_reason_codes") or [])
                                or c.get("upstream_error")
                            ),
                        } for c in _errs],
                        hide_index=True,
                        width="stretch",
                    )

        # 依赖锁**可见化**:此前 GAPS.md 承诺 owner=AUTO 由系统生成,却没有
        # 任何组件真的生成,而审核页也从不显示 —— 用户走完全部步骤仍拿到
        # 一个必崩的构建(2026-08-28 实测四发)。现在既然真会派生,就摆出来。
        _lock = review_bundle.get("dependency_lock") or {}
        if _lock:
            _src_label = {"user": "你写的依赖锁", "derived": "系统按钉版树派生", "missing": "缺依赖锁"}.get(
                str(_lock.get("source")), "—"
            )
            if _lock.get("source") == "missing":
                st.error(f"**依赖锁:{_src_label}** —— {_lock.get('note')}")
            else:
                st.info(
                    f"**依赖锁({_src_label})**：`"
                    + "`、`".join(_lock.get("pins") or [])
                    + "`\n\n"
                    + str(_lock.get("note") or "")
                )
            st.caption("这决定会话里装的是哪一版上游；装不上就没有任何测试能过。")

        st.markdown("#### 加入确认过的 Golden 样例")
        st.caption("至少三组，其中每四组的最后一组会自动成为不交给 Agent 的 held-out 样例。")
        st.caption("文本样例可以直接在下方「在线填写」；二进制输入（PDF、图片等）请用上传。")

        with st.expander("✍️ 在线填写一组样例（文本）", expanded=False):
            w1, w2 = st.columns(2)
            _wname = w1.text_input("样例文件名", value="case_1.txt", key="rp_write_name")
            _wint = w1.text_area("输入内容", height=140, key="rp_write_in")
            _woutt = w2.text_area("期望输出（你核实过的真值）", height=185, key="rp_write_out")
            if st.button("加入这一组（在线填写）", disabled=not _wname.strip()):
                r = product_jobs.add_golden_example(
                    inspect_dir,
                    input_name=Path(_wname).name,
                    input_bytes=_wint.encode("utf-8"),
                    expected_name=f"{Path(_wname).stem}.expected.txt",
                    expected_bytes=_woutt.encode("utf-8"),
                )
                (st.success if r.get("ok") else st.error)(r.get("note") or r.get("error"))

        c_in, c_out = st.columns(2)
        uploaded_in = c_in.file_uploader("输入文件", key="golden_input")
        uploaded_out = c_out.file_uploader("期望输出文件", key="golden_expected")
        # disabled 只挡点击,挡不住类型(也挡不住 Streamlit 版本差异下的
        # 意外触发)—— 两个文件都在场才进这一段,缺一个如实不做事。
        if (
            st.button("加入这一组样例", disabled=not (uploaded_in and uploaded_out))
            and uploaded_in is not None
            and uploaded_out is not None
        ):
            current_contract, contract_errors = parse_output_contract(
                output_contract_text,
                output_format=output_format,
            )
            golden_errors: list[str] = []
            if current_contract is not None:
                try:
                    expected_text = uploaded_out.getvalue().decode("utf-8")
                except UnicodeDecodeError:
                    golden_errors = ["GOLDEN_OUTPUT_INVALID: 期望输出必须是 UTF-8"]
                else:
                    from repoproof.adoption.assembly.output_contract import (
                        validate_output_text,
                    )

                    golden_errors = [
                        f"GOLDEN_OUTPUT_INVALID: {detail}"
                        for detail in validate_output_text(expected_text, current_contract)
                    ]
            if contract_errors or golden_errors:
                result = {
                    "ok": False,
                    "error": "；".join([*contract_errors, *golden_errors]),
                }
            else:
                result = product_jobs.add_golden_example(
                    inspect_dir,
                    input_name=uploaded_in.name,
                    input_bytes=uploaded_in.getvalue(),
                    expected_name=uploaded_out.name,
                    expected_bytes=uploaded_out.getvalue(),
                )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))
        # Gate 4:能力计划人读卡(RFC-013)—— 束内 plan.yaml 存在即渲染;
        # 证据、支持状态与执行路线都可审查,不是一句模糊的"可以做"。
        plan_file = Path(review_bundle["draft_dir"]) / "plan.yaml"
        if plan_file.is_file():
            import yaml as _yaml

            from repoproof.ui.services.product_mode import ROUTE_LABELS

            plan_doc = _yaml.safe_load(plan_file.read_text(encoding="utf-8")) or {}
            status = str(plan_doc.get("support_status") or "—")
            route = str(plan_doc.get("implementation_route") or "NONE")
            st.markdown("#### 能力计划(证据化)")
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("支持状态", status)
            pc2.metric("执行路线", route)
            pc3.metric("用户已确认", "是" if plan_doc.get("confirmed") else "否")
            st.write(f"**路线含义：** {ROUTE_LABELS.get(route, route)}")
            codes = plan_doc.get("reason_codes") or []
            if codes:
                st.write("**理由码：** " + ", ".join(f"`{x}`" for x in codes))
            surfaces = plan_doc.get("detected_surfaces") or []
            if surfaces:
                st.dataframe(
                    [
                        {
                            "类型": s.get("kind"),
                            "定位": s.get("locator"),
                            "签名": s.get("signature") or "—",
                            "置信度": s.get("confidence"),
                            "证据": "; ".join(s.get("evidence") or []) or "—",
                            "未选用原因": s.get("exclusion_reason") or "(已选用)",
                        }
                        for s in surfaces
                    ],
                    hide_index=True,
                    width="stretch",
                )
            st.caption("路由由确定性规则给出;LLM 建议不能改变支持状态或路线,未确认的计划不会触发任何真实模型。")
            # P1(外部审计 2026-08-25,easter 实例):analyzer 是**表面
            # 检测器**,不是意图匹配器 —— 这条边界必须向用户明说,
            # 不许用"自动理解你的需求"式话术把把关责任揽到系统身上。
            st.warning(
                "**请核对上面的「定位」再确认。** 系统只根据代码的表面特征"
                "(导出名单、函数签名、文件位置)找出候选入口,它**不理解**"
                "这个函数是否真是你想要的能力 —— 候选与你的意图是否相符,"
                "由你在确认这一步把关(术语:用户确认 callable locator)。"
            )

        # Any add-example button above mutates disk after the page's initial
        # snapshot. Re-read here so the metric never shows a stale zero.
        _fresh_review = product_jobs.read_managed_draft_review(inspect_dir)
        if _fresh_review.get("ok"):
            review_bundle = _fresh_review
        examples = review_bundle["examples"]
        st.metric("已确认样例", len(examples), help="冻结至少需要三组")
        if examples:
            st.dataframe(examples, hide_index=True, width="stretch")

        with st.expander("查看原始草稿与缺口清单"):
            st.code(review_bundle["raw_draft"], language="yaml")
            if review_bundle["gaps"]:
                st.markdown(review_bundle["gaps"])

with tab_build:
    section_intro("先彩排，再决定是否启动真实 Agent", "彩排门失败不会消耗真实模型预算；成功后仍需独立验证和干净重放。")
    _preferred_backend = os.environ.get(
        "REPOPROOF_DEFAULT_AGENT_BACKEND", "mini-swe"
    ).strip().lower()
    _codex_is_default = _preferred_backend in {"codex", "codex-cli", "subscription"}
    st.caption(
        "当前启动配置默认 Agent backend："
        f"{'Codex CLI（ChatGPT 订阅）' if _codex_is_default else 'mini-swe（API 网关）'}。"
        "DSH 属于冻结的 Benchmark Lab 研究线，"
        "不进入 Studio 产品构建。"
    )
    build_dir = Path(
        st.text_input(
            "已经审核完成的草稿目录",
            value=st.session_state.get("rp_draft_dir", str(ui_state_root() / "drafts" / "my-tool-draft")),
            key="build_draft_dir",
        )
    ).expanduser()
    dest_root = Path(st.text_input("工具库位置", value=str(tool_root()))).expanduser()
    rehearsal_only = st.toggle("只运行离线彩排", value=True)
    backend_label = st.selectbox(
        "真实构建 Agent",
        options=["mini-swe（API 网关）", "Codex CLI（ChatGPT 订阅）"],
        index=1 if _codex_is_default else 0,
        disabled=rehearsal_only,
        help=(
            "离线彩排不调用模型。mini-swe 使用项目配置的 API 网关；"
            "Codex CLI 复用官方 agent loop；"
            "RepoProof 仍负责合同、repair、独立验证与发布状态。"
        ),
    )
    agent_backend = "codex-cli" if backend_label.startswith("Codex CLI") else "mini-swe"
    confirmed = st.checkbox(
        "我已确认用户目标、公开行为承诺、输入输出、样例真值、上游版本和许可证"
    )
    lineage_ready = True
    core_ready = False
    build_bundle = product_jobs.read_managed_draft_review(build_dir)
    if build_bundle.get("ok"):
        build_dir = Path(build_bundle["draft_dir"])
        build_readiness = build_bundle.get("draft_readiness") or {}
        core_ready = bool(build_readiness.get("ready_to_confirm"))
        _render_draft_readiness_summary(build_readiness)
        # Gate 4:构建前的路线预告 —— 用户在点按钮前就知道会不会调模型。
        bp = build_dir / "plan.yaml"
        if bp.is_file():
            import yaml as _byaml

            _pd = _byaml.safe_load(bp.read_text(encoding="utf-8")) or {}
            _rt = str(_pd.get("implementation_route") or "NONE")
            if _rt == "DIRECT_WRAP":
                st.info("本次构建走确定性直连包装:**不会调用任何模型**;验证链(held-out/上游采用/干净重放)照常全跑。")
            elif _rt == "AGENT_ADAPT":
                st.info("本次构建需要受限 Coding Agent 适配:先离线彩排,真实模型仅在彩排通过后按预算调用。")
        output_preflight = validate_draft_output_examples(build_dir)
        preview_doc = build_bundle["draft"]
        preview_name = str((preview_doc.get("tool") or {}).get("name") or "")
        if preview_name:
            try:
                preview = next_task_version_preview(preview_name)
            except (OSError, ValueError) as exc:
                lineage_ready = False
                st.error(f"任务版本谱系无法安全计算：{exc}")
            else:
                st.caption(f"本次冻结版本只读预览：`{preview['task_id']}`。{preview['note']}")
    else:
        output_preflight = {
            "ok": False,
            "errors": [str(build_bundle.get("error") or "MANAGED_DRAFT_INVALID")],
        }
    if output_preflight["ok"]:
        st.success("OUTPUT_CONTRACT_READY：合同与 Golden 输出通过构建前只读检查。")
    else:
        st.error("构建前输出合同检查未通过：\n\n- " + "\n- ".join(output_preflight["errors"]))
    if st.button(
        "开始彩排" if rehearsal_only else "开始完整构建",
        type="primary",
        disabled=(not confirmed or not core_ready or not lineage_ready),
    ):
        intent_confirmation = product_jobs.confirm_draft_intent(build_dir)
        if intent_confirmation.get("ok"):
            result = product_jobs.start_tool_build(
                draft_dir=build_dir,
                dest_root=dest_root,
                rehearsal_only=rehearsal_only,
                agent_backend=agent_backend,
            )
        else:
            result = intent_confirmation
        (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

    # 彩排通过之后的**下半程**入口(2026-08-28 实录):tool_build 在彩排前
    # 就把草稿归档(冻结即消耗,这是对的),但此前 UI 只有"从草稿构建"一个
    # 入口 —— 于是彩排一过,回到本页只看到"草稿目录不存在",用户只能重建
    # 草稿再冻一版(v2/v3/v4…)。题面不重冻,直接对同一份合同续跑。
    if _require_service("list_rehearsed_tasks"):
        _pending = product_jobs.list_rehearsed_tasks()
        if _pending:
            st.divider()
            st.markdown("#### 已冻结、彩排过、还没导出的任务")
            st.caption("草稿在冻结时已被归档（题面不可再改）；这里直接对同一份合同跑真实构建。")
            _labels = {f"{r['task_id']}（最近彩排：{r.get('verdict') or '—'}）": r["task_id"] for r in _pending}
            _pick = st.selectbox("选择任务", list(_labels))
            _ok_to_resume = str(next((r.get("verdict") for r in _pending if r["task_id"] == _labels[_pick]), "")) in (
                "PASS_ADAPTED",
                "PASS_DIRECT",
            )
            if not _ok_to_resume:
                st.warning("这个任务最近一次彩排没过 —— 先让彩排过再谈真发（真发要烧预算）。")
            if st.button("对已冻结任务跑真实构建", type="primary", disabled=not _ok_to_resume):
                res = product_jobs.start_tool_build_real(_labels[_pick], dest_root, agent_backend=agent_backend)
                (st.success if res.get("ok") else st.error)(res.get("note") or res.get("error"))

    st.markdown("**构建全流程(每一步失败即停,不烧后续预算):**")
    st.markdown("1. 确认闸 → 2. 装配冻结 → 3. 离线彩排 → 4. Agent 构建 → 5. 独立验证 → 6. 干净重放 → 7. 导出并登记")
