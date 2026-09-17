"""Disposable public/internal origins for the forward proxy network test."""

# The log exists only inside the disposable container.
# ruff: noqa: S108
import http.server
import socket
import ssl
import threading
from pathlib import Path


class Server(http.server.ThreadingHTTPServer):
    address_family = socket.AF_INET6


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/redirected")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        with Path("/tmp/origin-hits").open("a") as handle:
            handle.write(self.path + "\n")
            if self.headers.get("Proxy-Authorization"):
                handle.write("forbidden-proxy-credential-leak\n")
        self.send_response(200)
        self.send_header("Content-Length", str(len(b"CONTROLLED_ORIGIN\n")))
        self.end_headers()
        self.wfile.write(b"CONTROLLED_ORIGIN\n")

    def log_message(self, *args):
        pass


for port in (80, 443, 8000, 8080):
    server = Server(("::", port), Handler)
    if port == 443:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(
            "/etc/tin-lite-proxy/tls/fullchain.pem", "/etc/tin-lite-proxy/tls/privkey.pem"
        )
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
threading.Event().wait()
