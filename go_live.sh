#!/usr/bin/env bash
# go_live.sh — Keep Project Crucible live for hackathon judging.
# Starts dashboard + auto-reconnecting tunnel. Run with: ./go_live.sh
# The public URL is saved to LIVE_URL.txt and printed to screen.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=5000
URL_FILE="${SCRIPT_DIR}/LIVE_URL.txt"
DASHBOARD_PID=""
TUNNEL_PID=""

cleanup() {
    echo ""
    echo "[LIVE] Shutting down..."
    [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null
    [[ -n "$DASHBOARD_PID" ]] && kill "$DASHBOARD_PID" 2>/dev/null
    wait 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# ── 1. Start dashboard if not already running ────────────────────────────────
start_dashboard() {
    if curl -s -o /dev/null -w '' "http://localhost:${PORT}/" 2>/dev/null; then
        echo "[LIVE] ✓ Dashboard already running on port ${PORT}."
    else
        echo "[LIVE] Starting dashboard server..."
        "${SCRIPT_DIR}/venv/bin/python3" "${SCRIPT_DIR}/sre_agent.py" --serve \
            > "${SCRIPT_DIR}/dashboard.log" 2>&1 &
        DASHBOARD_PID=$!

        # Wait for it to come up
        for i in $(seq 1 30); do
            if curl -s -o /dev/null "http://localhost:${PORT}/" 2>/dev/null; then
                echo "[LIVE] ✓ Dashboard is up on port ${PORT}."
                break
            fi
            sleep 1
        done

        if ! curl -s -o /dev/null "http://localhost:${PORT}/" 2>/dev/null; then
            echo "[LIVE] ✗ Dashboard failed to start. Check dashboard.log"
            exit 1
        fi
    fi
}

# ── 2. Establish tunnel with auto-reconnect ──────────────────────────────────
run_tunnel_loop() {
    local attempt=0
    while true; do
        attempt=$((attempt + 1))
        echo "[LIVE] Tunnel attempt #${attempt}..."

        local logfile
        logfile=$(mktemp "${SCRIPT_DIR}/.tunnel_XXXXXX")

        # Start SSH tunnel to localhost.run
        ssh -o StrictHostKeyChecking=no \
            -o ServerAliveInterval=15 \
            -o ServerAliveCountMax=3 \
            -o ConnectTimeout=10 \
            -o ExitOnForwardFailure=yes \
            -R 80:localhost:${PORT} \
            nokey@localhost.run \
            > "$logfile" 2>&1 &
        TUNNEL_PID=$!

        # Wait for URL to appear
        local url=""
        for i in $(seq 1 20); do
            url=$(grep -oP 'https://[a-z0-9]+\.lhr\.life' "$logfile" 2>/dev/null | head -1)
            if [[ -n "$url" ]]; then
                break
            fi
            sleep 1
        done

        if [[ -n "$url" ]]; then
            echo "$url" > "$URL_FILE"
            echo ""
            echo "╔══════════════════════════════════════════════════════════════╗"
            echo "║  🔴 PROJECT CRUCIBLE IS LIVE                                ║"
            echo "║                                                              ║"
            printf "║  %-60s║\n" "$url"
            echo "║                                                              ║"
            echo "║  Share this URL with judges. Auto-reconnects if dropped.     ║"
            echo "║  URL also saved to LIVE_URL.txt                              ║"
            echo "║  Press Ctrl+C to take offline.                               ║"
            echo "╚══════════════════════════════════════════════════════════════╝"
            echo ""

            # Wait for tunnel process to die (disconnect)
            wait "$TUNNEL_PID" 2>/dev/null
            echo "[LIVE] ⚠  Tunnel dropped. Reconnecting in 3s..."
        else
            echo "[LIVE] ⚠  Could not get URL. Retrying in 5s..."
            kill "$TUNNEL_PID" 2>/dev/null
            wait "$TUNNEL_PID" 2>/dev/null
            sleep 5
        fi

        rm -f "$logfile"
        TUNNEL_PID=""
        sleep 3

        # Verify dashboard is still alive before reconnecting
        if ! curl -s -o /dev/null "http://localhost:${PORT}/" 2>/dev/null; then
            echo "[LIVE] Dashboard went down. Restarting..."
            start_dashboard
        fi
    done
}

# ── Main ─────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       PROJECT CRUCIBLE — HACKATHON LIVE MODE                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

start_dashboard
run_tunnel_loop
