"""browser-use 0.13.7 sidecar worker.  JSON stdin -> JSON stdout."""
from __future__ import annotations
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


async def main() -> int:
    spec = json.load(sys.stdin)
    try:
        from browser_use import Agent, BrowserProfile, BrowserSession, ChatOpenAI
        import browser_use
    except Exception as exc:
        print(json.dumps({"ok": False, "reason": f"BROWSER_USE_IMPORT:{exc}"}))
        return 2
    if getattr(browser_use, "__version__", "0.13.7") not in ("0.13.7",):
        print(json.dumps({"ok": False, "reason": "UNPINNED_BROWSER_USE"})); return 2
    base = os.environ.get("APPLY_ASSIST_LLM_BASE_URL", "")
    key = os.environ.get("APPLY_ASSIST_LLM_API_KEY", "")
    if not base or not key:
        print(json.dumps({"ok": False, "reason": "LLM_CONFIGURATION_MISSING"})); return 2
    runtime = Path(tempfile.mkdtemp(prefix="offerclaw-browser-session-"))
    session = None
    fields = spec["fields"]
    lines = "\n".join(f"{k}: {v}" for k, v in fields.items())
    if spec.get("resume_path"):
        lines += f"\nresume_path: {spec['resume_path']}"
    task = f"""Open this local application form: {spec['site_url']}
Prepare it for the user, but NEVER submit, apply, confirm, quick-apply, or click any button
which can cause final submission. Fill only the values explicitly listed below. Do not fill
any other input. Upload only resume_path if present. Click exactly Save Draft after filling,
then stop successfully at the human gate. Do not click Continue.
{lines}"""
    try:
        profile = BrowserProfile(headless=True, user_data_dir=runtime,
            keep_alive=False, allowed_domains=["127.0.0.1", "localhost"],
            minimum_wait_page_load_time=0.2, wait_for_network_idle_page_load_time=0.3)
        session = BrowserSession(browser_profile=profile)
        llm = ChatOpenAI(model="fake-agent", api_key=key, base_url=base,
                         temperature=0, max_retries=0)
        agent = Agent(task=task, llm=llm, browser_session=session, use_vision=False,
            use_judge=False, generate_gif=False, available_file_paths=[spec["resume_path"]]
            if spec.get("resume_path") else None, max_actions_per_step=3,
            max_failures=2, step_timeout=25, llm_timeout=15, enable_signal_handler=False)
        history = await agent.run(max_steps=12)
        agent.save_history(spec["history_path"])
        # A draft save is the only success path encoded in the task/fake model. The native
        # history remains the audit source; API state is the policy-level Human Gate.
        print(json.dumps({"ok": True, "history_items": len(history.history)}))
        return 0
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(json.dumps({"ok": False, "reason": f"AGENT_ERROR:{type(exc).__name__}:{exc}"}))
        return 1
    finally:
        if session is not None:
            try: await session.kill()
            except Exception: pass
        shutil.rmtree(runtime, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
