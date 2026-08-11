from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('content-length','0') or '0')
        body = self.rfile.read(n)
        try:
            data = json.loads(body or b'{}')
        except Exception:
            data = {}
        msgs = data.get('messages') or []
        text = '\n'.join(str(m.get('content','')) for m in msgs if isinstance(m, dict))
        resp = {"choices":[{"message":{"role":"assistant","content":"Fake LLM response\n" + text}}], "usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}
        raw = json.dumps(resp).encode()
        self.send_response(200); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, *a):
        pass

def start():
    srv = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
