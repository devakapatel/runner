#!/usr/bin/env python3
"""
Runner Fleet Tracker - Central service for tracking active GitHub Actions runners.
"""
import json
import time
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import uuid


STATE_FILE = Path("/tmp/runner_fleet_state.json")
STATE_LOCK = threading.Lock()


class RunnerTracker:
    def __init__(self):
        self.runners = {}
        self.load_state()

    def load_state(self):
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE) as f:
                    self.runners = json.load(f)
            except Exception:
                self.runners = {}

    def save_state(self):
        with STATE_LOCK:
            with open(STATE_FILE, "w") as f:
                json.dump(self.runners, f)

    def register(self, runner_id, metadata):
        with STATE_LOCK:
            self.runners[runner_id] = {
                "id": runner_id,
                "metadata": metadata,
                "first_seen": time.time(),
                "last_heartbeat": time.time(),
                "status": "active",
            }
            self.save_state()
            return runner_id

    def heartbeat(self, runner_id):
        with STATE_LOCK:
            if runner_id in self.runners:
                self.runners[runner_id]["last_heartbeat"] = time.time()
                self.runners[runner_id]["status"] = "active"
                self.save_state()
                return True
        return False

    def get_active_runners(self, timeout=60):
        now = time.time()
        with STATE_LOCK:
            active = {}
            for rid, data in self.runners.items():
                if now - data["last_heartbeat"] < timeout:
                    data["age"] = int(now - data["first_seen"])
                    data["last_seen_ago"] = int(now - data["last_heartbeat"])
                    active[rid] = data
            return active

    def cleanup_stale(self, timeout=120):
        now = time.time()
        with STATE_LOCK:
            stale = [rid for rid, data in self.runners.items() if now - data["last_heartbeat"] > timeout]
            for rid in stale:
                self.runners[rid]["status"] = "stale"
            self.save_state()


tracker = RunnerTracker()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.serve_dashboard()
        elif path == "/api/runners":
            self.serve_api_runners()
        elif path == "/api/stats":
            self.serve_api_stats()
        elif path == "/health":
            self.send_json({"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/register":
            self.handle_register()
        elif path == "/api/heartbeat":
            self.handle_heartbeat()
        else:
            self.send_response(404)
            self.end_headers()

    def serve_dashboard(self):
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>Runner Fleet Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; background: #0d1117; color: #c9d1d9; min-height: 100vh; }
        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
        h1 { color: #f0f6fc; margin-bottom: 8px; }
        .subtitle { color: #8b949e; margin-bottom: 24px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
        .stat-value { font-size: 36px; font-weight: 600; color: #58a6ff; }
        .stat-label { color: #8b949e; font-size: 14px; margin-top: 4px; }
        .runner-table { width: 100%; border-collapse: collapse; background: #161b22; border-radius: 8px; overflow: hidden; border: 1px solid #30363d; }
        .runner-table th, .runner-table td { padding: 12px 16px; text-align: left; border-bottom: 1px solid #30363d; }
        .runner-table th { background: #21262d; color: #8b949e; font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
        .runner-table tr:last-child td { border-bottom: none; }
        .runner-table tr:hover { background: #1f2428; }
        .status-badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .status-active { background: #238636; color: #fff; }
        .status-stale { background: #d29922; color: #0d1117; }
        .runner-id { font-family: 'SF Mono', Monaco, monospace; font-size: 13px; color: #f0f6fc; }
        .runner-meta { color: #8b949e; font-size: 13px; }
        .last-seen { color: #8b949e; font-size: 12px; }
        .refresh-btn { background: #238636; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-size: 14px; }
        .refresh-btn:hover { background: #2ea043; }
        .header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
        .timestamp { color: #8b949e; font-size: 13px; }
        .empty-state { text-align: center; padding: 60px 20px; color: #8b949e; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header-row">
            <div>
                <h1>🏃 Runner Fleet Dashboard</h1>
                <div class="subtitle">GitHub Actions Self-Hosted Runner Monitor</div>
            </div>
            <button class="refresh-btn" onclick="loadRunners()">🔄 Refresh</button>
        </div>
        
        <div class="stats-grid" id="stats"></div>
        
        <table class="runner-table" id="runnerTable">
            <thead>
                <tr>
                    <th>Runner ID</th>
                    <th>Labels</th>
                    <th>OS / Arch</th>
                    <th>Started</th>
                    <th>Last Heartbeat</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="runnerBody"></tbody>
        </table>
        
        <div class="timestamp" id="lastUpdate"></div>
    </div>

    <script>
        function formatDuration(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = seconds % 60;
            if (h > 0) return `${h}h ${m}m`;
            if (m > 0) return `${m}m ${s}s`;
            return `${s}s`;
        }

        function loadRunners() {
            fetch('/api/runners')
                .then(r => r.json())
                .then(data => {
                    const runners = Object.values(data);
                    const stats = document.getElementById('stats');
                    const tbody = document.getElementById('runnerBody');
                    const updateEl = document.getElementById('lastUpdate');
                    
                    stats.innerHTML = `
                        <div class="stat-card">
                            <div class="stat-value">${runners.filter(r => r.status === 'active').length}</div>
                            <div class="stat-label">Active Runners</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value">${runners.length}</div>
                            <div class="stat-label">Total Registered</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value">${runners.filter(r => r.status === 'stale').length}</div>
                            <div class="stat-label">Stale</div>
                        </div>
                    `;
                    
                    if (runners.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No runners registered yet. Trigger a workflow to spin up runners.</td></tr>';
                    } else {
                        tbody.innerHTML = runners.map(r => `
                            <tr>
                                <td class="runner-id">${r.id.slice(0, 8)}...${r.id.slice(-4)}</td>
                                <td class="runner-meta">${(r.metadata?.labels || '').split(',').map(l => `<span style="background:#21262d;padding:2px 6px;border-radius:4px;margin-right:4px;font-size:11px;">${l.trim()}</span>`).join('') || '—'}</td>
                                <td class="runner-meta">${r.metadata?.os || '—'} / ${r.metadata?.arch || '—'}</td>
                                <td class="last-seen">${formatDuration(r.age)} ago</td>
                                <td class="last-seen">${formatDuration(r.last_seen_ago)} ago</td>
                                <td><span class="status-badge ${r.status === 'active' ? 'status-active' : 'status-stale'}">${r.status.toUpperCase()}</span></td>
                            </tr>
                        `).join('');
                    }
                    
                    updateEl.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
                })
                .catch(err => console.error('Failed to load runners:', err));
        }

        // Auto-refresh every 5 seconds
        setInterval(loadRunners, 5000);
        loadRunners();
    </script>
</body>
</html>
"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_api_runners(self):
        runners = tracker.get_active_runners()
        self.send_json(runners)

    def serve_api_stats(self):
        runners = tracker.get_active_runners()
        stats = {
            "total": len(runners),
            "active": len([r for r in runners.values() if r["status"] == "active"]),
            "stale": len([r for r in runners.values() if r["status"] == "stale"]),
        }
        self.send_json(stats)

    def handle_register(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length)) if length else {}
        
        runner_id = data.get("id") or str(uuid.uuid4())[:8]
        metadata = {
            "labels": data.get("labels", ""),
            "os": data.get("os", ""),
            "arch": data.get("arch", ""),
            "github_repo": data.get("github_repo", ""),
            "github_run_id": data.get("github_run_id", ""),
        }
        
        tracker.register(runner_id, metadata)
        self.send_json({"id": runner_id, "status": "registered"})

    def handle_heartbeat(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length)) if length else {}
        
        runner_id = data.get("id")
        if runner_id and tracker.heartbeat(runner_id):
            self.send_json({"status": "ok"})
        else:
            self.send_response(404)
            self.send_json({"error": "Runner not found"})

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # Suppress default logging


def run_server():
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    print("🏃 Runner Fleet Tracker started on http://0.0.0.0:8080")
    server.serve_forever()


if __name__ == "__main__":
    run_server()