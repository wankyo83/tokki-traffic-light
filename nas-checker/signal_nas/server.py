import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .model import json_bytes


ADMIN_HTML = """<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>중앙 신호등 NAS 관리</title>
<style>body{background:#101a2a;color:#eef7ff;font:16px system-ui;margin:0;padding:2rem}main{max-width:760px;margin:auto}h1{font-size:1.6rem}input,select,button{box-sizing:border-box;padding:.8rem;margin:.3rem 0;border-radius:.5rem;border:1px solid #52708d;font:inherit}input{width:100%}select{width:40%}button{background:#7ce1f5;color:#071621;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#17293e;padding:1rem;border-radius:.6rem}small{color:#b5c8da}</style>
<main><h1>중앙 신호등 NAS 관리</h1><p>주소를 입력하면 Camoufox가 실제 사이트를 확인합니다. 확인 전에는 공개 주소가 바뀌지 않습니다.</p>
<label>관리 토큰<input id=token type=password autocomplete=off placeholder=\".env의 ADMIN_TOKEN\"></label>
<label>사이트<select id=site></select></label><label>새 HTTPS 주소<input id=url type=url placeholder=\"https://example.com\"></label>
<button id=submit>주소 확인 요청</button> <button id=refresh>상태 새로고침</button> <button id=run>전체 검사 지금 실행</button>
<p id=message></p><small>토큰은 이 화면에서만 사용하며 저장하지 않습니다. LAN HTTP 대신 HTTPS 역방향 프록시 또는 Tailscale을 권장합니다.</small><pre id=state>상태를 보려면 토큰을 입력하고 새로고침하세요.</pre></main>
<script>
const keys=%KEYS%;const $=x=>document.getElementById(x);keys.forEach(([key,name])=>{const o=document.createElement('option');o.value=key;o.textContent=name;$('site').append(o)});
async function call(path,method='GET',payload){const r=await fetch(path,{method,headers:{Authorization:'Bearer '+$('token').value,'Content-Type':'application/json'},body:payload?JSON.stringify(payload):undefined});const v=await r.json();if(!r.ok)throw Error(v.error||r.status);return v}
$('refresh').onclick=async()=>{try{$('state').textContent=JSON.stringify(await call('/api/state'),null,2)}catch(e){$('message').textContent=e.message}};
$('submit').onclick=async()=>{try{const v=await call('/api/manual-candidate','POST',{key:$('site').value,url:$('url').value});$('message').textContent='확인 대기: '+v.url;await $('refresh').onclick()}catch(e){$('message').textContent=e.message}};
$('run').onclick=async()=>{try{await call('/api/run','POST',{});$('message').textContent='검사 요청 완료'}catch(e){$('message').textContent=e.message}};
</script></html>"""


def make_handler(service):
    secret = os.environ.get("ADMIN_TOKEN", "")
    origin = os.environ.get("ADMIN_ALLOWED_ORIGIN", "https://wankyo83.github.io")
    if len(secret) < 24:
        raise ValueError("ADMIN_TOKEN must contain at least 24 characters")

    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            if self.headers.get("Origin") == origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Vary", "Origin")

        def _send(self, status, data, content_type="application/json; charset=utf-8"):
            payload = json_bytes(data) if not isinstance(data, bytes) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self):
            header = self.headers.get("Authorization", "")
            return hmac.compare_digest(header, "Bearer " + secret)

        def do_OPTIONS(self):
            if self.path.startswith("/api/") and self.headers.get("Origin") == origin:
                self.send_response(204)
                self._cors()
                self.end_headers()
            else:
                self._send(403, {"error": "origin not allowed"})

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"ok": True, "running": service.snapshot()["running"]})
                return
            if self.path == "/":
                from .model import SITES
                html = ADMIN_HTML.replace("%KEYS%", json.dumps([[s["key"], s["name"]] for s in SITES], ensure_ascii=False))
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return
            if not self._authorized():
                self._send(401, {"error": "관리 토큰이 필요합니다."})
                return
            if self.path == "/api/state":
                self._send(200, service.snapshot())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                self._send(401, {"error": "관리 토큰이 필요합니다."})
                return
            if self.path not in ("/api/manual-candidate", "/api/run"):
                self._send(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 2048 or length < 0:
                    raise ValueError("request too large")
                value = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/run":
                    service.wake.set()
                    self._send(202, {"queued": True})
                else:
                    url = service.submit(value.get("key"), value.get("url"))
                    self._send(202, {"queued": True, "url": url})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)[:200]})

        def log_message(self, format_string, *args):
            # Do not log bearer token or user-submitted values.
            return

    return Handler


def serve(service):
    port = int(os.environ.get("PORT", "8792"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service))
    server.serve_forever()
