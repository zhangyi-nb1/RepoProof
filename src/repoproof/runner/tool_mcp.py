"""MCP 暴露(M3-c · RFC-010 [D1]:manifest 的机械转换)。

`tool.json` → `mcp_server.py`(stdio JSON-RPC 2.0,newline-delimited;
零第三方依赖):一个 MCP tool,inputSchema 由 manifest.interface 机械
推导,tools/call = subprocess 跑 `bin/<name>`。生成物是工具包的一部分
(纯模板,不含任何运行期判断);挂接命令示例写进生成物头注释。
"""

from __future__ import annotations

import json
from pathlib import Path

_SERVER_TMPL = '''#!/usr/bin/env python3
"""MCP stdio server for `{name}`(由 repoproof tool mcp 机械生成)。

挂进 Claude Code:
    claude mcp add {name} -- python3 {server_path}
协议:JSON-RPC 2.0 over stdio(newline-delimited);单 tool = {name}。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOL = ROOT / "bin" / {name!r}

TOOL_DEF = {{
    "name": {mcp_name!r},
    "description": {description!r},
    "inputSchema": {{
        "type": "object",
        "properties": {{
            "input_path": {{"type": "string",
                            "description": "输入文件路径({in_format})"}},
            "out": {{"type": "string",
                     "description": "可选:输出文件路径(缺省返回 stdout)"}},
        }},
        "required": ["input_path"],
    }},
}}


def _reply(rid, result=None, error=None):
    msg = {{"jsonrpc": "2.0", "id": rid}}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\\n")
    sys.stdout.flush()


def _call(args):
    argv = [str(TOOL), str(args["input_path"])]
    if args.get("out"):
        argv += ["--out", str(args["out"])]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    text = r.stdout if r.returncode == 0 else (r.stderr or f"exit {{r.returncode}}")
    return {{"content": [{{"type": "text", "text": text}}],
             "isError": r.returncode != 0}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        method, rid = req.get("method", ""), req.get("id")
        if method == "initialize":
            _reply(rid, {{"protocolVersion": "2024-11-05",
                          "capabilities": {{"tools": {{}}}},
                          "serverInfo": {{"name": {name!r},
                                          "version": {version!r}}}}})
        elif method == "tools/list":
            _reply(rid, {{"tools": [TOOL_DEF]}})
        elif method == "tools/call":
            try:
                _reply(rid, _call(req["params"]["arguments"]))
            except (KeyError, subprocess.SubprocessError, OSError) as e:
                _reply(rid, error={{"code": -32000, "message": str(e)}})
        elif rid is not None:            # 未知带 id 请求:如实报不支持
            _reply(rid, error={{"code": -32601,
                                "message": f"method not found: {{method}}"}})
        # 通知(无 id)不回


if __name__ == "__main__":
    main()
'''


def write_mcp_server(tool_dir: Path) -> Path:
    """→ 生成的 mcp_server.py 路径。manifest 缺 verification 则拒
    (MCP 暴露只给已验证工具 —— 未验证的先走 build)。"""
    tool_dir = Path(tool_dir)
    manifest = json.loads((tool_dir / "tool.json").read_text(encoding="utf-8"))
    if not (manifest.get("verification") or {}).get("verdict"):
        raise RuntimeError(
            f"{manifest.get('name')}: tool.json 无 verification —— "
            "MCP 暴露只服务已验证工具")
    name = manifest["name"]
    out = tool_dir / "mcp_server.py"
    out.write_text(_SERVER_TMPL.format(
        name=name,
        mcp_name=name.replace("-", "_"),
        description=(manifest.get("summary", "") + " "
                     + f"(verified local tool; usage: "
                     + manifest.get("interface", {}).get("usage", "")).strip(),
        in_format=manifest.get("interface", {}).get("input", {}).get("format", ""),
        version=manifest.get("version", "1.0.0"),
        server_path=str(out),
    ), encoding="utf-8")
    out.chmod(0o755)
    return out
