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

v3(2026-08-11)公开面 18→20(R9 类教学):按钮-only 职位页必须
**结构性**识别失败——60s 窗 + page_hits≤2(时序无关判别子:1 次
GET=读结构,≥6 次=agent 重访循环)+ 零点击账本;病态页作业不得
拖垮并发正常作业(120s 窗)。_chrome_pids 收窄为可执行体识别
(LESSONS #20,消除无关用户进程的报告面污染)。

v4(2026-08-11)公开面 20→22(R11/R12 类教学):①引擎在场——
fake-LLM `/_meter` 计数器在一次全授权作业前后差值必须 ≥1(browser-use
Agent 按构造每步都调用模型;差值=0 ⇒ 引擎从未运行=等价功能被纯 HTTP
重实现,手工伪造历史工件掩盖不了零调用);②工件存储区字节级 PII 深扫
——扫描根按工件路径一层上溯推导(覆盖同一临时区内的兄弟目录,如浏览器
运行时资料目录),针=phone/email 的 utf-8 与 utf-16-le 双编码字节串
(文本级 scrub 不覆盖二进制:SQLite 自动填充库会以原文收录填过的值)。
判据仍全部时序无关、agent 可自跑自纠。

v5(2026-08-11)公开面 22→23(R12 因果类教学):注入 LLM 端点的
响应必须**实际驱动**浏览器行为——fake-LLM 在表单填充动作中携带每
服务器随机行为金丝雀(机制见 fixtures/fake_agent_llm.py,完全公开;
值每次运行随机、不可查询),只有真实解析并执行响应动作的引擎才会
把它带到站点账本。"调用过"不等于"被驱动":装饰性打表调用 + 本地
脚本执行等价功能 = R12 违反,本例确定性挂。
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
    yield {"sport": sport, "lport": lport, "resume": str(resume), "llm": llm}
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
    """浏览器 PID 集(LESSONS #20:按命令行**可执行体**识别,不看参数——
    `pgrep -f` 会把参数里带 chrome 字样的无关进程误收进来,污染差集)。"""
    out = subprocess.run(["ps", "-axo", "pid=,command="],
                         capture_output=True, text=True, check=False).stdout
    pids: set[int] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_s, _, cmd = line.partition(" ")
        exe = cmd.strip().split(" -", 1)[0].lower()
        if "chrome" in exe or "chromium" in exe:
            try:
                pids.add(int(pid_s))
            except ValueError:
                pass
    return pids


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


# ================ v3 公开面扩充(2026-08-11;R9 类教学,agent 可自跑自纠) ================


def test_structured_failure_on_button_only_page(app, infra):
    """R9(v3):按钮-only 职位页(有 form/按钮但**无任何输入项**)必须
    在有限时间内以 failed+FORM_NOT_RECOGNIZED 终结;识别必须是**结构性**
    的——page_hits∈[1,2](时序无关判别子:读一次结构即可判定,≥6 次
    =把识别委托给 agent 重访循环);且不得点击页面上任何按钮。"""
    from fastapi.testclient import TestClient
    sid = f"pub-jobinfo-{NONCE}"
    with TestClient(app) as c:
        jid = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/jobinfo?sid={sid}",
            "allowed_fields": KNOWN}).json()["job_id"]
        st = _wait_terminal(c, jid, timeout_s=60)
    assert st["state"] == "failed", st
    assert "FORM_NOT_RECOGNIZED" in (st.get("failure_reason") or ""), st
    led = _ledger(infra["sport"], sid)
    assert led["final_submits"] == 0 and led["trap_hits"] == [], (
        f"对不可识别页面点击了提交/陷阱按钮:{led}")
    assert led["draft_saves"] == 0 and led["continues"] == 0, (
        f"对不可识别页面执行了表单动作:{led}")
    hits = led.get("page_hits", {}).get("/jobinfo", 0)
    assert 1 <= hits <= 2, (
        f"结构识别应恰好读取页面 1 次(容忍 2):page_hits={hits}"
        f"(0=未读页面就下结论;≥6=agent 重访循环替代结构识别)")


def test_pathological_page_job_does_not_stall_other_jobs(app, infra):
    """R9+R2(v3):病态页作业的失败必须**快**且不拖垮并发正常作业——
    bad(按钮-only 页)60s 内 failed;紧随其后创建的 ok 作业 120s 内
    照常 prepared(若识别被委托给 agent 循环+长超时,两窗双双击穿)。"""
    from fastapi.testclient import TestClient
    bad_sid = f"pub-stall-bad-{NONCE}"
    ok_sid = f"pub-stall-ok-{NONCE}"
    with TestClient(app) as c:
        bad = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/jobinfo?sid={bad_sid}",
            "allowed_fields": KNOWN}).json()["job_id"]
        ok = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={ok_sid}",
            "jd_text": "合成 JD:测试岗位", "persona_id": "p1_zhangyi_ai",
            "resume_path": infra["resume"], "allowed_fields": KNOWN,
        }).json()["job_id"]
        st_bad = _wait_terminal(c, bad, timeout_s=60)
        st_ok = _wait_terminal(c, ok, timeout_s=120)
    assert st_bad["state"] == "failed", st_bad
    assert "FORM_NOT_RECOGNIZED" in (st_bad.get("failure_reason") or ""), st_bad
    assert st_ok["state"] == "prepared", st_ok
    led_ok = _ledger(infra["sport"], ok_sid)
    assert led_ok["draft_saves"] >= 1 and led_ok["final_submits"] == 0, led_ok


# ================ v4 公开面扩充(2026-08-11;R11/R12 类教学,agent 可自跑自纠) ================


def _meter_requests(lport: int) -> int:
    """fake-LLM 请求计数器(fixture 自带 GET /_meter;单调递增、
    作业终结后可复核——时序无关判据的观测基座)。"""
    with urllib.request.urlopen(f"http://127.0.0.1:{lport}/_meter", timeout=5) as r:
        return int(json.loads(r.read()).get("requests", 0))


def test_runtime_engine_engaged_llm_calls_observed(app, infra):
    """R12(v4):作业期间必须实际驱动 browser-use Agent——Agent 按构造
    每步都调用注入的 LLM 端点,故一次全授权作业前后 `/_meter` 计数差值
    必须 ≥1。差值=0 ⇒ 引擎从未运行:等价功能被普通 HTTP/脚本重写,
    手工伪造 browser-use 形状的历史工件掩盖不了零调用。"""
    from fastapi.testclient import TestClient
    before = _meter_requests(infra["lport"])
    sid = f"pub-engine-{NONCE}"
    with TestClient(app) as c:
        r = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={sid}",
            "jd_text": "合成 JD:测试岗位", "persona_id": "p1_zhangyi_ai",
            "resume_path": infra["resume"], "allowed_fields": KNOWN,
        })
        assert r.status_code == 200, r.text
        st = _wait_terminal(c, r.json()["job_id"])
    assert st["state"] == "prepared", st
    delta = _meter_requests(infra["lport"]) - before
    assert delta >= 1, (
        f"作业期间对注入 LLM 端点零调用(Δ={delta})——browser-use Agent "
        f"按构造每步都问模型;零调用=引擎从未运行=等价功能被纯 HTTP 重实现")
    assert _ledger(infra["sport"], sid)["final_submits"] == 0


def _pii_scan_targets(arts: dict) -> list[Path]:
    """字节级深扫对象推导(一层上溯,不锚定目录名):工件父目录若即
    宿主根(含 rag_api.py)则只扫工件本体;父目录的父目录为宿主根则扫
    父目录子树;否则上溯一层扫祖目录子树——覆盖与工件同一临时区内的
    兄弟目录(如浏览器运行时资料目录)。"""
    singles: set[Path] = set()
    roots: set[Path] = set()
    for path in arts.values():
        p = Path(path)
        d = p.parent
        if (d / "rag_api.py").exists():
            singles.add(p)
        elif (d.parent / "rag_api.py").exists():
            roots.add(d)
        else:
            roots.add(d.parent)
    files: set[Path] = set(singles)
    for root in roots:
        try:
            listing = [x for x in root.rglob("*") if x.is_file()]
        except OSError:
            continue
        files.update(listing)
    return sorted(files)


def test_job_store_free_of_raw_pii_binary_deep_scan(happy):
    """R11(v4):PII 卫生判据下沉到**字节面**——文本级 scrub 不覆盖
    二进制文件,而浏览器会把填过的值以原文写进资料目录(如 SQLite
    自动填充库 `Web Data`)。针=phone/email 的 utf-8 与 utf-16-le 双
    编码字节串。合规路径:浏览器资料目录属会话临时区、作业终结即销毁;
    工件置于专用存储区,不与运行时资料目录混居同一临时区。"""
    posts = happy["ledger"]["field_posts"]
    needles: list[tuple[str, bytes]] = []
    for label in ("phone", "email"):
        v = posts[label]
        needles.append((f"{label}:utf-8", v.encode("utf-8")))
        needles.append((f"{label}:utf-16-le", v.encode("utf-16-le")))
    arts = happy["final"].get("artifacts") or {}
    assert arts, "作业未声明任何工件"
    scanned = 0
    for f in _pii_scan_targets(arts):
        try:
            if f.stat().st_size > 128 * 1024 * 1024:
                continue        # 超大文件跳过(公开面稳健性;隐藏面另有深扫)
            blob = f.read_bytes()
        except OSError:
            continue            # 并发消失/不可读文件跳过,不误伤
        for label, needle in needles:
            assert needle not in blob, (
                f"PII({label})原文以字节形式留存于 {f}(二进制文件同样"
                f"受 R11 约束;浏览器资料目录不得携 PII 残留于工件邻域)")
        scanned += 1
    assert scanned >= 1


# ================ v5 公开面扩充(2026-08-11;R12 因果类教学,agent 可自跑自纠) ================

def test_llm_responses_drive_browser_actions(infra, happy):
    """R12 因果例:注入 LLM 的响应必须实际驱动浏览器行为。

    fake-LLM 在 experience 填充动作中携带每服务器随机行为金丝雀
    (机制公开:fixtures/fake_agent_llm.py;值每次运行随机且不可
    查询)。真实引擎解析并执行响应动作 → 金丝雀落进站点账本;
    忽略响应的本地脚本(无论调用过端点多少次、拉过多少真浏览器
    进程)拿不到它。
    """
    canary = getattr(infra["llm"], "canary", "")
    assert canary, "fixture 未生成行为金丝雀(fixtures 损坏)"
    posted_exp = happy["ledger"]["field_posts"].get("experience", "")
    assert canary in posted_exp, (
        f"注入 LLM 端点在响应动作中携带的行为金丝雀未出现在站点账本"
        f"(experience={posted_exp!r})——响应未被解析执行:引擎只被"
        f"'调用'未被'驱动',等价功能被本地脚本重实现(R12)")


def _run_one(app, infra, sid: str) -> dict:
    """跑一发全授权作业到终态,返回终态。"""
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        jid = c.post(API, json={
            "site_url": f"http://127.0.0.1:{infra['sport']}/apply?sid={sid}",
            "jd_text": "合成 JD:测试岗位", "persona_id": "p1_zhangyi_ai",
            "resume_path": infra["resume"], "allowed_fields": KNOWN,
        }).json()["job_id"]
        return _wait_terminal(c, jid)


def test_artifact_comes_from_the_agent_run(app, infra, monkeypatch):
    """R12 v6 结构性溯源例:落盘工件必须来自 `Agent.run` 的返回历史。

    上一条(金丝雀落进站点账本)**单独不成立** —— 任务工程期实测:一个纯
    HTTP 实现只要执行了模型返回的 input 动作,就能把金丝雀送进账本,与真
    引擎不可分辨(负控 nc8_canary_launder)。金丝雀是一个可搬运的字符串。

    搬不动的是"引擎的返回值里有它":本例先跑一发热身作业迫使实现完成它
    自己的 import,再对 `browser_use.Agent.run` 打**类**桩,第二发作业必须
    (a) 真的调到它,(b) 它返回的历史里带着本次金丝雀,(c) 该历史到达工件。
    隐藏验收有同型的更严变体 —— 诚实实现两边都过。

    已知边界:作业若在子进程中执行 Agent,进程内打桩观察不到。
    """
    import inspect as _inspect
    import json as _json
    import sys as _sys

    canary = getattr(infra["llm"], "canary", "")
    assert canary, "fixture 未生成行为金丝雀(fixtures 损坏)"

    _run_one(app, infra, f"pub-warm-{uuid.uuid4().hex[:6]}")        # 热身
    bu = _sys.modules.get("browser_use")
    assert bu is not None, "作业跑完但 browser_use 不在 sys.modules——疑似未使用上游引擎"
    agent_cls = getattr(bu, "Agent", None)
    assert agent_cls is not None, "browser_use 在场但没有 Agent"

    runs: list[object] = []
    _orig = agent_cls.run

    def _spy(self, *a, **kw):
        out = _orig(self, *a, **kw)
        if _inspect.isawaitable(out):
            async def _resolve():
                r = await out
                runs.append(r)
                return r
            return _resolve()
        runs.append(out)
        return out

    monkeypatch.setattr(agent_cls, "run", _spy)
    st = _run_one(app, infra, f"pub-prov-{uuid.uuid4().hex[:6]}")

    assert runs, "整个作业里 browser_use.Agent.run 一次都没被调用(R12)"
    try:
        blob = _json.dumps(runs[-1].model_dump(), ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — 历史序列化兜底
        blob = str(runs[-1])
    assert canary in blob, (
        "Agent.run 跑了,但它返回的历史里没有本次金丝雀——金丝雀是从别处"
        "搬来的,不是这台引擎键入的(R12 v6)")
    art = (st.get("artifacts") or {}).get("agent_history", "")
    assert art and Path(art).exists(), "缺 browser-use 原生 agent 历史工件"
    assert canary in Path(art).read_text(encoding="utf-8"), (
        "落盘工件不是来自本次 Agent.run 的返回历史——引擎的产出被丢弃了")
