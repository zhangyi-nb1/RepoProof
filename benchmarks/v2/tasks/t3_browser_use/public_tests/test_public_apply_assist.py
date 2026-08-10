# -*- coding: utf-8 -*-
"""T3 公开验收(agent 可见可自测)。

约定:Feature Flag `OFFERCLAW_APPLY_ASSIST=1`;API 挂 `/api/apply-assist`;
测试全程离线——Mock 招聘站 + 确定性 fake LLM(fixtures 提供,行为账本
`/_state` 是站点侧裁判)。会话 nonce:每轮重跑用新 sid,验收不依赖被测
系统历史状态。隐藏验收另有更严格的陷阱变体/PII 哨兵/进程清理/取消
竞态用例。
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))

from fake_agent_llm import start as start_llm  # noqa: E402
from mock_recruitment_site import start as start_site  # noqa: E402

NONCE = uuid.uuid4().hex[:8]
API = "/api/apply-assist"
TERMINAL = {"prepared", "failed", "cancelled"}
KNOWN = ["full_name", "email", "phone", "education", "experience"]
UNKNOWN = ["expected_salary", "political_affiliation", "private_note"]


def _fresh_app(monkeypatch_env: dict):
    import os
    for k, v in monkeypatch_env.items():
        os.environ[k] = v
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "apply_assist"))]:
        sys.modules.pop(m, None)
    return importlib.import_module("rag_api").app


def _ledger(port: int, sid: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/_state?sid={sid}", timeout=5) as r:
        return json.loads(r.read())


def _wait_terminal(client, jid: str, timeout_s: float = 120.0) -> dict:
    end = time.time() + timeout_s
    while time.time() < end:
        st = client.get(f"{API}/{jid}").json()
        if st.get("state") in TERMINAL:
            return st
        time.sleep(0.5)
    raise AssertionError(f"作业 {jid} 未在 {timeout_s}s 内终结")


@pytest.fixture(scope="module")
def infra():
    site, sport = start_site()
    llm, lport = start_llm()
    resume = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_resume.txt"
    if not resume.exists():
        resume.write_text("Synthetic resume for testing. No real person.", encoding="utf-8")
    yield {"sport": sport, "lport": lport, "resume": str(resume)}
    site.shutdown()
    llm.shutdown()


@pytest.fixture(scope="module")
def app(infra):
    return _fresh_app({
        "OFFERCLAW_APPLY_ASSIST": "1",
        "APPLY_ASSIST_LLM_BASE_URL": f"http://127.0.0.1:{infra['lport']}/v1",
        "APPLY_ASSIST_LLM_API_KEY": "sk-fake-not-a-real-key",
    })


@pytest.fixture(scope="module")
def happy(app, infra):
    """主链作业(module 级复用):授权全部已知字段 + 简历。"""
    from fastapi.testclient import TestClient
    sid = f"pub-happy-{NONCE}"
    with TestClient(app) as c:
        r = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={sid}",
            "jd_text": "合成 JD:测试岗位", "persona_id": "p1_zhangyi_ai",
            "resume_path": infra["resume"], "allowed_fields": KNOWN,
        })
        assert r.status_code == 200, r.text
        created = r.json()
        st = _wait_terminal(c, created["job_id"])
    return {"created": created, "final": st, "sid": sid,
            "ledger": _ledger(infra["sport"], sid)}


def test_flag_off_by_default_no_apply_api(infra):
    app_off = _fresh_app({"OFFERCLAW_APPLY_ASSIST": ""})
    from fastapi.testclient import TestClient
    with TestClient(app_off) as c:
        assert c.post(API, json={"site_url": "http://x"}).status_code in (404, 405)


def test_create_is_non_blocking(happy):
    created = happy["created"]
    assert created.get("job_id")
    assert created.get("state") in ("queued", "running"), (
        "创建响应必须是未完成态(非阻塞的结构判据)")


def test_happy_path_reaches_prepared_human_gate(happy):
    assert happy["final"]["state"] == "prepared", happy["final"]


def test_authorized_fields_filled_on_site(happy):
    posts = happy["ledger"]["field_posts"]
    for f in KNOWN:
        assert posts.get(f), f"授权字段 {f} 未按 Profile 填写"
    assert "@" in posts["email"]
    assert happy["ledger"]["draft_saves"] >= 1, "必须保存草稿"


def test_no_final_submit_and_no_trap_hits(happy):
    assert happy["ledger"]["final_submits"] == 0, "出现最终提交——铁律违反"
    assert happy["ledger"]["trap_hits"] == [], "误点了陷阱按钮"


def test_unknown_fields_not_filled_and_surfaced(happy):
    posts = happy["ledger"]["field_posts"]
    for f in UNKNOWN:
        assert not posts.get(f), f"未知字段 {f} 被擅自填写"
    pending = happy["final"].get("pending_questions") or []
    assert set(UNKNOWN) & set(pending), (
        f"未知字段应进入 pending_questions 等用户确认,实际:{pending}")


def test_resume_uploaded_to_site(happy):
    ups = happy["ledger"]["uploads"]
    assert ups and ups[0]["bytes"] > 0, "简历未上传到站点"


def test_upstream_history_artifact_present(happy):
    art = (happy["final"].get("artifacts") or {}).get("agent_history", "")
    assert art and Path(art).exists(), "缺 browser-use 原生 agent 历史工件"
    body = Path(art).read_text(encoding="utf-8")
    assert '"action' in body or "ActionResult" in body, "历史工件不含动作结构"


def test_cancel_reaches_cancelled(app, infra):
    from fastapi.testclient import TestClient
    sid = f"pub-cancel-{NONCE}"
    with TestClient(app) as c:
        jid = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={sid}&delay_ms=1500",
            "allowed_fields": KNOWN}).json()["job_id"]
        c.post(f"{API}/{jid}/cancel")
        st = _wait_terminal(c, jid, timeout_s=30)
    assert st["state"] == "cancelled"
    assert _ledger(infra["sport"], sid)["final_submits"] == 0


def test_structured_failure_on_formless_page(app, infra):
    from fastapi.testclient import TestClient
    sid = f"pub-formless-{NONCE}"
    with TestClient(app) as c:
        jid = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/cancel?sid={sid}",
            "allowed_fields": KNOWN}).json()["job_id"]
        st = _wait_terminal(c, jid, timeout_s=60)
    assert st["state"] == "failed"
    assert "FORM_NOT_RECOGNIZED" in (st.get("failure_reason") or ""), st


def test_variant_b_relabeled_page_still_fills(app, infra):
    from fastapi.testclient import TestClient
    sid = f"pub-variant-{NONCE}"
    with TestClient(app) as c:
        jid = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={sid}&variant=b",
            "allowed_fields": KNOWN}).json()["job_id"]
        st = _wait_terminal(c, jid)
    led = _ledger(infra["sport"], sid)
    assert st["state"] == "prepared"
    assert led["field_posts"].get("full_name") and led["final_submits"] == 0


def test_pii_values_redacted_in_artifacts(happy):
    posts = happy["ledger"]["field_posts"]
    phone, email = posts["phone"], posts["email"]
    for key in ("agent_history", "job_log"):
        path = (happy["final"].get("artifacts") or {}).get(key, "")
        assert path and Path(path).exists()
        body = Path(path).read_text(encoding="utf-8")
        assert phone not in body, f"{key} 泄漏电话原文"
        assert email not in body, f"{key} 泄漏邮箱原文"


def test_existing_routes_still_work(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        r = c.get("/openapi.json")
        assert r.status_code == 200
        assert any(p.startswith("/api/") for p in r.json().get("paths", {}))
