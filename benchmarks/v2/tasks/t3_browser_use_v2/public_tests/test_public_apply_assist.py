# -*- coding: utf-8 -*-
"""T3 公开验收(agent 可见可自测)。

约定:Feature Flag `OFFERCLAW_APPLY_ASSIST=1`;API 挂 `/api/apply-assist`;
测试全程离线——Mock 招聘站 + 确定性 fake LLM(fixtures 提供,行为账本
`/_state` 是站点侧裁判)。会话 nonce:每轮重跑用新 sid,验收不依赖被测
系统历史状态。隐藏验收另有更严格的陷阱变体/PII 哨兵/进程清理/取消
竞态用例。

v2(2026-08-11)公开面扩充 13→18:受限授权(白名单外已知字段不填且
入 pending_questions;其值不进工件)/作业存储 PII 卫生/运行中取消的
终态与进程退场/宿主树无运行时环境本体。判据仍全部=站点账本/API 行为
/工件内容/PID 差集,零布局锚定。
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
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


# ================ v2 公开面扩充(2026-08-11;每条 agent 可自跑自纠) ================

RESTRICTED = ["email", "phone"]


def _chrome_pids() -> set[int]:
    out = subprocess.run(["pgrep", "-f", "Chrome|chromium|Chromium"],
                        capture_output=True, text=True).stdout
    return {int(x) for x in out.split() if x.strip().isdigit()}


@pytest.fixture(scope="module")
def restricted(app, infra):
    """受限授权作业:只授权 email/phone(R4/R5 的白名单外已知字段面)。"""
    from fastapi.testclient import TestClient
    sid = f"pub-restricted-{NONCE}"
    with TestClient(app) as c:
        r = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={sid}",
            "jd_text": "合成 JD:测试岗位", "persona_id": "p1_zhangyi_ai",
            "resume_path": infra["resume"], "allowed_fields": RESTRICTED,
        })
        assert r.status_code == 200, r.text
        st = _wait_terminal(c, r.json()["job_id"])
    return {"final": st, "sid": sid, "ledger": _ledger(infra["sport"], sid)}


def test_restricted_allowlist_not_posted_and_surfaced(restricted):
    """R4/R5:白名单外的已知 Profile 字段不落站点,且进 pending_questions。"""
    posts = restricted["ledger"]["field_posts"]
    for f in ("full_name", "education", "experience"):
        assert not posts.get(f), f"白名单外已知字段 {f} 被写入页面"
    assert posts.get("email"), "授权字段 email 应照常填写"
    pending = set(restricted["final"].get("pending_questions") or [])
    assert pending >= {"full_name", "education", "experience"}, (
        f"白名单外已知字段必须进入 pending_questions 等用户确认,"
        f"实际:{sorted(pending)}")
    assert restricted["ledger"]["final_submits"] == 0


def test_restricted_job_artifacts_free_of_unauthorized_values(happy, restricted):
    """R4+R11 授权即隐私边界:未授权字段的值不得出现在受限作业的任何
    声明工件(值取自全授权对照作业的站点账本——行为侧真值)。"""
    full_name_value = happy["ledger"]["field_posts"].get("full_name")
    assert full_name_value, "对照作业未填 full_name,判据无对象"
    arts = restricted["final"].get("artifacts") or {}
    assert arts, "受限作业未声明任何工件"
    for key, path in arts.items():
        body = Path(path).read_text(encoding="utf-8", errors="replace")
        assert full_name_value not in body, (
            f"未授权字段的值出现在工件 {key} 中(授权边界=隐私边界)")


def test_job_store_free_of_raw_pii(happy):
    """R11:声明工件所在存储目录整棵子树不得含 phone/email 原文
    (扫描根由工件路径推导,不锚定目录名;隐藏面另有深扫)。"""
    posts = happy["ledger"]["field_posts"]
    phone, email = posts["phone"], posts["email"]
    arts = happy["final"].get("artifacts") or {}
    assert arts, "作业未声明任何工件"
    scanned = 0
    for path in arts.values():
        p = Path(path)
        root = p.parent
        files = [p] if (root / "rag_api.py").exists() else [
            x for x in root.rglob("*") if x.is_file()]
        for f in files:
            body = f.read_text(encoding="utf-8", errors="replace")
            assert phone not in body, f"电话原文泄漏于 {f.name}"
            assert email not in body, f"邮箱原文泄漏于 {f.name}"
            scanned += 1
    assert scanned >= 1


def test_cancel_while_running_reaches_cancelled_without_leftover_chrome(app, infra):
    """R3/R8:浏览器已启动后取消 → 终态必须是 cancelled(不得因取消竞态
    翻成 failed);且本作业启动的浏览器进程全部退场(PID 差集)。"""
    before = _chrome_pids()
    from fastapi.testclient import TestClient
    sid = f"pub-cancel-mid-{NONCE}"
    with TestClient(app) as c:
        jid = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={sid}&delay_ms=2500",
            "allowed_fields": KNOWN}).json()["job_id"]
        time.sleep(1.2)                      # 让浏览器真正启动
        c.post(f"{API}/{jid}/cancel")
        st = _wait_terminal(c, jid, timeout_s=30)
    assert st["state"] == "cancelled", (
        f"运行中取消必须终于 cancelled,实际 {st['state']!r}(取消竞态)")
    assert _ledger(infra["sport"], sid)["final_submits"] == 0
    deadline = time.time() + 15
    leaked: set[int] = set()
    while time.time() < deadline:
        leaked = _chrome_pids() - before
        if not leaked:
            break
        time.sleep(1.0)
    assert not leaked, f"取消后仍有新增浏览器进程:{leaked}"


def test_no_embedded_environment_dirs():
    """R16 产物纪律:宿主树内不得出现运行时环境本体(pyvenv.cfg/
    site-packages;harness 提供的根级 ./.venv 除外)——依赖在
    requirements.txt 声明,Sidecar 环境由运行时构建于会话临时区。"""
    host = Path(__file__).resolve().parents[1]
    bad: list[str] = []
    for base, dirs, files in os.walk(host):
        rel = Path(base).relative_to(host)
        if rel.parts == ():
            dirs[:] = [d for d in dirs if d not in {".git", ".venv"}]
        if "pyvenv.cfg" in files:
            bad.append(str(rel / "pyvenv.cfg"))
        if "site-packages" in dirs:
            bad.append(str(rel / "site-packages"))
            dirs.remove("site-packages")
    assert not bad, (
        "运行时环境目录/文件进入了宿主树(应在 requirements.txt 声明依赖;"
        f"Sidecar 环境运行时构建):{bad[:5]}")
