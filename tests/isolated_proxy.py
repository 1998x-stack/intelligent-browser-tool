"""HTTP-only in-container proxy fixture for isolated Chrome CI testing.

This is deliberately a test-only request recorder / deny-by-default endpoint.
It is NOT a general forwarding proxy and must never be deployed as such.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

seen = []
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def respond(self, code, content=b"", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        if content:
            self.wfile.write(content)

    def do_CONNECT(self):
        with lock:
            seen.append(("CONNECT", self.path))
        self.respond(403, b"HTTPS not enabled in this controlled HTTP fixture")

    def do_GET(self):
        path = urlsplit(self.path)
        host = (path.hostname or self.headers.get("Host") or "").lower()
        request_path = path.path or "/"
        if request_path == "/__stats__" and host.startswith(("127.0.0.1", "localhost", "local-proxy")):
            with lock:
                content = json.dumps(seen).encode("utf-8")
            return self.respond(200, content, (("Content-Type", "application/json"),))
        with lock:
            seen.append((host, request_path))
        if host == "allowed.test" and request_path == "/redirect":
            return self.respond(302, headers=(("Location", "http://allowed.test/start"),))
        if host == "allowed.test" and request_path == "/start":
            body = b"""<!doctype html><html><head><title>Isolated Allowed Fixture</title></head>
            <body><h1>Isolated Browser Verified</h1>
            <img src='http://blocked.test/image.png'>
            <iframe src='http://blocked.test/frame'></iframe>
            <script>fetch('http://blocked.test/xhr').catch(()=>{});</script>
            <p>This is a controlled test site in an internal Docker network.</p></body></html>"""
            return self.respond(200, body, (("Content-Type", "text/html"),))
        return self.respond(403, b"Blocked by isolated test proxy")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 3128), Handler).serve_forever()
