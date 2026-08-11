# Apply Assist browser sidecar

`OFFERCLAW_APPLY_ASSIST=1` enables the API. It is off by default and the router is not
registered when off. The implementation uses browser-use `Agent` and `BrowserSession`;
it never implements browser actions with OfferClaw's existing Playwright dependency.

browser-use 0.13.7 requires pydantic 2.12.5 while OfferClaw intentionally tracks its host
stack. Installing that lock in-process caused a measured ~11x regression, so the browser
engine is an isolated process. Build its environment outside this repository:

```sh
scripts/build_apply_assist_sidecar.sh /var/tmp/offerclaw-browser-use
export APPLY_ASSIST_SIDECAR_PYTHON=/var/tmp/offerclaw-browser-use/bin/python
export APPLY_ASSIST_LLM_BASE_URL=http://127.0.0.1:PORT/v1
export APPLY_ASSIST_LLM_API_KEY=...
```

Browser profiles are per-job OS temporary directories and are deleted on every exit.
Only redacted native history and a redacted policy log are retained. Authentication or
CAPTCHA is never bypassed; production adapters must surface it as a pending Human Gate.
