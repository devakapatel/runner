#!/bin/bash
# Runner Entrypoint - Registers with fleet tracker and sends heartbeats

set -euo pipefail

TRACKER_URL="${TRACKER_URL:-http://localhost:8080}"
RUNNER_ID="${RUNNER_ID:-$(hostname)-$(date +%s)-$RANDOM}"
LABELS="${LABELS:-ubuntu,runner,fleet}"
OS_INFO="$(uname -s)"
ARCH_INFO="$(uname -m)"
GITHUB_REPO="${GITHUB_REPOSITORY:-unknown}"
GITHUB_RUN_ID="${GITHUB_RUN_ID:-unknown}"

echo "🏃 Runner starting..."
echo "   ID: $RUNNER_ID"
echo "   Labels: $LABELS"
echo "   Tracker: $TRACKER_URL"

# Register with tracker
register() {
    curl -s -X POST "$TRACKER_URL/api/register" \
        -H "Content-Type: application/json" \
        -d "$(jq -n \
            --arg id "$RUNNER_ID" \
            --arg labels "$LABELS" \
            --arg os "$OS_INFO" \
            --arg arch "$ARCH_INFO" \
            --arg repo "$GITHUB_REPO" \
            --arg run_id "$GITHUB_RUN_ID" \
            '{id: $id, labels: $labels, os: $os, arch: $arch, github_repo: $repo, github_run_id: $run_id}')" \
        | jq -r '.id // "unknown"'
}

# Send heartbeat
heartbeat() {
    curl -s -X POST "$TRACKER_URL/api/heartbeat" \
        -H "Content-Type: application/json" \
        -d "{\"id\": \"$RUNNER_ID\"}" > /dev/null
}

# Initial registration
echo "📝 Registering with tracker..."
REGISTERED_ID=$(register)
if [ "$REGISTERED_ID" != "unknown" ]; then
    RUNNER_ID="$REGISTERED_ID"
    echo "✅ Registered as: $RUNNER_ID"
else
    echo "⚠️  Registration failed, continuing with local ID"
fi

# Start heartbeat loop in background
(
    while true; do
        sleep 10
        heartbeat
    done
) &
HEARTBEAT_PID=$!

# Cleanup on exit
cleanup() {
    echo "🛑 Runner shutting down..."
    kill $HEARTBEAT_PID 2>/dev/null || true
    exit 0
}
trap cleanup EXIT INT TERM

# Keep running - replace this with your actual runner command
echo "🏃 Runner active. Heartbeat PID: $HEARTBEAT_PID"
echo "📊 Dashboard: $TRACKER_URL"

# Wait indefinitely (or exec your runner command here)
wait $HEARTBEAT_PID