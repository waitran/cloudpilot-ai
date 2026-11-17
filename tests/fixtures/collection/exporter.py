"""Synthetic cAdvisor-shaped samples, enabled only by the explicit CI Compose override."""

import time
from http.server import BaseHTTPRequestHandler, HTTPServer

START = time.monotonic()
LABELS = 'container="api",pod="synthetic-api",namespace="demo",uid="synthetic-pod-uid-1"'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        body = (
            "# TYPE container_cpu_usage_seconds_total counter\n"
            f"container_cpu_usage_seconds_total{{{LABELS}}} {(time.monotonic() - START) * 0.125}\n"
            "# TYPE container_memory_working_set_bytes gauge\n"
            f"container_memory_working_set_bytes{{{LABELS}}} 134217728\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 9100), Handler).serve_forever()
