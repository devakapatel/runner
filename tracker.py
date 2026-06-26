#!/usr/bin/env python3
"""
Simple API Server for Runner Slot - No fleet coordination, no registration, no heartbeat.
Each runner is completely independent with its own tunnel.
"""
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import os


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self.send_json({"status": "ok", "slot": os.environ.get("RUNNER_SLOT", "unknown"), "timestamp": time.time()})
        elif path == "/api/runners":
            self.send_json({
                "runners": [{
                    "id": f"slot-{os.environ.get('RUNNER_SLOT', 'unknown')}",
                    "domain": os.environ.get("RUNNER_DOMAIN", "unknown"),
                    "status": "running",
                    "started_at": time.time()
                }]
            })
        elif path == "/api/stats":
            self.send_json({
                "slot": os.environ.get("RUNNER_SLOT", "unknown"),
                "domain": os.environ.get("RUNNER_DOMAIN", "unknown"),
                "status": "active",
                "uptime_seconds": int(time.time() - START_TIME)
            })
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass


START_TIME = time.time()

if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    print("🏃 Runner API Server started on http://0.0.0.0:8080")
    server.serve_forever()