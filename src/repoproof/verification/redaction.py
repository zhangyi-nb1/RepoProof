"""Evidence Redaction Scanner (Gate 4B non-behavioral infrastructure).

Blocks evidence publication when host paths, usernames, credentials,
private-key headers or LAN IPs appear in files destined for the public
repo. Motivated by a REAL leak: mswea's serialized output_path carried
the host absolute path into committed evidence, and an earlier BSD-grep
scan was false-negative.
"""

from __future__ import annotations

import getpass
import re
from pathlib import Path

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("host_path_macos", re.compile(r"/Users/[A-Za-z0-9_.-]+")),
    ("host_path_linux", re.compile(r"/home/[A-Za-z0-9_.-]+")),
    ("host_path_windows", re.compile(r"C:\\\\?Users\\\\?[A-Za-z0-9_.-]+", re.IGNORECASE)),
    ("api_key_openai_style", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("api_key_github", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("api_key_aws", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_header", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("lan_ip", re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")),
]


def _username_patterns() -> list[tuple[str, re.Pattern]]:
    names = set()
    try:
        names.add(getpass.getuser())
    except Exception:  # noqa: BLE001
        pass
    home = Path.home().name
    names.add(home)
    return [("username", re.compile(re.escape(n))) for n in names if len(n) >= 4]


def scan_file(path: Path) -> list[dict]:
    findings: list[dict] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [{"file": str(path), "kind": "unreadable", "match": str(exc)[:80]}]
    for kind, pat in _PATTERNS + _username_patterns():
        for m in pat.finditer(text):
            findings.append({"file": str(path), "kind": kind, "match": m.group(0)[:60]})
            break  # one hit per kind per file is enough to block
    return findings


def scan_evidence(root: Path) -> dict:
    """Scan every file under an evidence dir. ok=False blocks publication."""
    findings: list[dict] = []
    files = [p for p in sorted(Path(root).rglob("*")) if p.is_file()]
    for p in files:
        findings.extend(scan_file(p))
    return {"ok": not findings, "files_scanned": len(files), "findings": findings}
