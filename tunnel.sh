#!/usr/bin/env bash
# tunnel.sh — Resilient tunnel launcher for Project Crucible
# Tries multiple tunnel providers in order until one establishes a connection.
#
# Usage:
#   ./tunnel.sh          # default: tunnel localhost:5000
#   ./tunnel.sh 8080     # tunnel a custom port

set -euo pipefail

PORT="${1:-5000}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TUNNEL_PID=""
TUNNEL_URL=""

cleanup() {
    echo ""
    echo "[tunnel] Shutting down..."
    [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null
    wait "$TUNNEL_PID" 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# ── Helper: wait for a URL to appear in a log file ──────────────────────────
wait_for_url() {
    local logfile="$1"
    local pattern="$2"
    local timeout="$3"
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if grep -qoP "$pattern" "$logfile" 2>/dev/null; then
            grep -oP "$pattern" "$logfile" | head -1
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# ── Provider 1: localhost.run (SSH over port 22) ─────────────────────────────
try_localhost_run() {
    echo "[tunnel] Trying localhost.run (SSH tunnel, port 22)..."
    local logfile
    logfile=$(mktemp "${SCRIPT_DIR}/.tunnel_log_XXXXXX")

    ssh -o StrictHostKeyChecking=no \
        -o ServerAliveInterval=30 \
        -o ConnectTimeout=8 \
        -R 80:localhost:${PORT} \
        nokey@localhost.run \
        > "$logfile" 2>&1 &
    TUNNEL_PID=$!

    if TUNNEL_URL=$(wait_for_url "$logfile" 'https://[a-z0-9]+\.lhr\.life' 15); then
        rm -f "$logfile"
        return 0
    fi

    kill "$TUNNEL_PID" 2>/dev/null; wait "$TUNNEL_PID" 2>/dev/null
    TUNNEL_PID=""
    echo "[tunnel]   ✗ localhost.run failed or timed out."
    rm -f "$logfile"
    return 1
}

# ── Provider 2: serveo.net (SSH over port 22) ────────────────────────────────
try_serveo() {
    echo "[tunnel] Trying serveo.net (SSH tunnel, port 22)..."
    local logfile
    logfile=$(mktemp "${SCRIPT_DIR}/.tunnel_log_XXXXXX")

    ssh -o StrictHostKeyChecking=no \
        -o ServerAliveInterval=30 \
        -o ConnectTimeout=8 \
        -R 80:localhost:${PORT} \
        serveo.net \
        > "$logfile" 2>&1 &
    TUNNEL_PID=$!

    if TUNNEL_URL=$(wait_for_url "$logfile" 'https://[a-z0-9]+\.serveo\.net' 15); then
        rm -f "$logfile"
        return 0
    fi

    kill "$TUNNEL_PID" 2>/dev/null; wait "$TUNNEL_PID" 2>/dev/null
    TUNNEL_PID=""
    echo "[tunnel]   ✗ serveo.net failed or timed out."
    rm -f "$logfile"
    return 1
}

# ── Provider 3: cloudflared quick tunnel (QUIC/HTTP2, port 7844) ─────────────
try_cloudflared() {
    local binary="${SCRIPT_DIR}/cloudflared"
    if [[ ! -x "$binary" ]]; then
        echo "[tunnel]   ✗ cloudflared binary not found, skipping."
        return 1
    fi

    echo "[tunnel] Trying cloudflared (QUIC tunnel, port 7844)..."
    local logfile
    logfile=$(mktemp "${SCRIPT_DIR}/.tunnel_log_XXXXXX")

    "$binary" tunnel --url "http://localhost:${PORT}" \
        > "$logfile" 2>&1 &
    TUNNEL_PID=$!

    if TUNNEL_URL=$(wait_for_url "$logfile" 'https://[a-z0-9-]+\.trycloudflare\.com' 20); then
        # Give it a few more seconds to verify the connection actually establishes
        sleep 3
        if grep -q "ERR.*Failed to dial" "$logfile" && ! grep -q "Registered tunnel connection" "$logfile"; then
            echo "[tunnel]   ✗ cloudflared got a URL but can't connect (port 7844 blocked)."
            kill "$TUNNEL_PID" 2>/dev/null; wait "$TUNNEL_PID" 2>/dev/null
            TUNNEL_PID=""
            rm -f "$logfile"
            return 1
        fi
        rm -f "$logfile"
        return 0
    fi

    kill "$TUNNEL_PID" 2>/dev/null; wait "$TUNNEL_PID" 2>/dev/null
    TUNNEL_PID=""
    echo "[tunnel]   ✗ cloudflared failed or timed out."
    rm -f "$logfile"
    return 1
}

# ── Provider 4: localtunnel via npx (HTTPS, port 443) ────────────────────────
try_localtunnel() {
    if ! command -v npx &>/dev/null; then
        echo "[tunnel]   ✗ npx not found, skipping localtunnel."
        return 1
    fi

    echo "[tunnel] Trying localtunnel (HTTPS, port 443)..."
    local logfile
    logfile=$(mktemp "${SCRIPT_DIR}/.tunnel_log_XXXXXX")

    npx -y localtunnel --port "${PORT}" \
        > "$logfile" 2>&1 &
    TUNNEL_PID=$!

    if TUNNEL_URL=$(wait_for_url "$logfile" 'https://[a-z0-9-]+\.loca\.lt' 25); then
        rm -f "$logfile"
        return 0
    fi

    kill "$TUNNEL_PID" 2>/dev/null; wait "$TUNNEL_PID" 2>/dev/null
    TUNNEL_PID=""
    echo "[tunnel]   ✗ localtunnel failed or timed out."
    rm -f "$logfile"
    return 1
}

# ── Main ─────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       PROJECT CRUCIBLE — RESILIENT TUNNEL LAUNCHER          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "[tunnel] Target: localhost:${PORT}"
echo ""

# Check local server is up
if ! curl -s -o /dev/null -w '' "http://localhost:${PORT}/" 2>/dev/null; then
    echo "[tunnel] ⚠  WARNING: localhost:${PORT} is not responding."
    echo "[tunnel]    Make sure the dashboard is running first:"
    echo "[tunnel]      python3 sre_agent.py --serve"
    echo ""
fi

# Try each provider in order of reliability
if try_localhost_run; then true
elif try_serveo; then true
elif try_cloudflared; then true
elif try_localtunnel; then true
else
    echo ""
    echo "[tunnel] ❌ All tunnel providers failed."
    echo "[tunnel]    Your network may be heavily restricted."
    echo "[tunnel]    Try connecting via a mobile hotspot and re-running."
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅ TUNNEL ACTIVE                                           ║"
echo "║                                                              ║"
printf "║  %-60s║\n" "$TUNNEL_URL"
echo "║                                                              ║"
echo "║  Press Ctrl+C to stop.                                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Keep alive
wait "$TUNNEL_PID"
