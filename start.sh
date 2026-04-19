#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh — Agnes 2.0 Launcher with Watchdog
#
# Usage:
#   chmod +x start.sh   # first time only
#   ./start.sh
#
# Features:
#   • Prerequisite checks (.env, deps, KB)
#   • Tee output to logs/agnes_ui.log
#   • Auto-opens browser after server is ready
#   • Watchdog: auto-restarts on crash
#   • Graceful Ctrl+C with uptime / restart summary
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✗${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
sep()  { echo -e "${CYAN}$(printf '─%.0s' {1..54})${RESET}"; }

# ── State ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/agnes_ui.log"
PORT=7860
START_EPOCH=$(date +%s)
RESTART_COUNT=0

# ── Cleanup / signal handler ──────────────────────────────────────────────────
# Ctrl+C sends SIGINT to the entire process group (python3 + tee + bash),
# so python3 is already dead when cleanup() runs — no manual kill needed.
cleanup() {
    echo ""
    sep
    local elapsed=$(( $(date +%s) - START_EPOCH ))
    local h=$(( elapsed / 3600 ))
    local m=$(( (elapsed % 3600) / 60 ))
    local s=$(( elapsed % 60 ))
    echo -e "\n${BOLD}  Agnes stopped.${RESET}"
    echo -e "  Uptime    : $(printf '%02d:%02d:%02d' $h $m $s)"
    echo -e "  Restarts  : $RESTART_COUNT"
    echo -e "  Log saved : $LOG_FILE"
    sep
    exit 0
}
trap cleanup INT TERM

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Banner
# ─────────────────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║     Agnes 2.0 — Multimodal Compliance Evaluator      ║"
echo "  ║     RAG · Gemini Flash · Gradio 6 · Watchdog         ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo -e "  ${BOLD}Started :${RESET} $(date '+%Y-%m-%d %H:%M:%S')"
echo -e "  ${BOLD}URL     :${RESET} http://localhost:$PORT"
echo -e "  ${BOLD}Logs    :${RESET} $LOG_FILE"
echo -e "  ${BOLD}Stop    :${RESET} Ctrl+C"
echo ""
sep

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Prerequisites
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}  Checking prerequisites …${RESET}\n"

# python3
if ! command -v python3 &>/dev/null; then
    err "python3 not found. Install Python 3.10+ and re-run."
    exit 1
fi
ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"

# .env + GEMINI_API_KEY
ENV_FILE="$SCRIPT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    err ".env file missing. Create it:"
    echo -e "       echo \"GEMINI_API_KEY=your-key-here\" > .env"
    exit 1
fi

API_KEY_VAL=$(grep -E '^GEMINI_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
if [[ -z "$API_KEY_VAL" ]]; then
    err "GEMINI_API_KEY is empty in .env. Add your key and retry."
    exit 1
fi
ok "GEMINI_API_KEY set (${#API_KEY_VAL} chars)"

# Python deps — auto-install if missing
check_or_install() {
    local module="$1" package="${2:-$1}"
    if python3 -c "import $module" &>/dev/null; then
        ok "python module '$module'"
    else
        warn "'$module' not found — installing …"
        if pip install "$package" --break-system-packages -q; then
            ok "'$module' installed"
        else
            err "Failed to install '$package'. Run manually:"
            echo "       pip install $package --break-system-packages"
            exit 1
        fi
    fi
}

check_or_install "gradio"
check_or_install "bs4" "beautifulsoup4"
check_or_install "dotenv" "python-dotenv"
check_or_install "google.genai" "google-genai"
check_or_install "sentence_transformers"
check_or_install "faiss"
check_or_install "plotly"

# KB / regulatory docs
KB_FILE="$SCRIPT_DIR/KB/regulatory_docs.json"
if [[ -f "$KB_FILE" ]]; then
    DOC_COUNT=$(python3 -c "import json; d=json.load(open('$KB_FILE')); print(len(d))" 2>/dev/null || echo "?")
    ok "KB/regulatory_docs.json ($DOC_COUNT documents)"
else
    warn "KB/regulatory_docs.json missing — running scrape_kb.py …"
    python3 "$SCRIPT_DIR/scrape_kb.py" && ok "KB built" || {
        err "scrape_kb.py failed. Check your network and API key, then retry."
        exit 1
    }
fi

# Local model cache
MODELS_DIR="$SCRIPT_DIR/models"
if [[ -d "$MODELS_DIR/all-MiniLM-L6-v2" && -d "$MODELS_DIR/cross-encoder-reranker" ]]; then
    MODEL_MB=$(du -sm "$MODELS_DIR" 2>/dev/null | cut -f1 || echo "?")
    ok "Local models cached (${MODEL_MB} MB) — offline mode active"
else
    warn "Local models not found — downloading once (~175 MB) …"
    python3 "$SCRIPT_DIR/download_models.py" && ok "Models downloaded to $MODELS_DIR" || {
        err "Model download failed. Check network and retry, or run: python download_models.py"
        exit 1
    }
fi

# Log dir
mkdir -p "$LOG_DIR"
ok "Log directory: $LOG_DIR"

sep
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 + 4 — Server start with watchdog
# ─────────────────────────────────────────────────────────────────────────────

open_browser() {
    # Wait for the server to bind and respond
    local max_attempts=30
    local attempt=0
    while (( attempt < max_attempts )); do
        if >/dev/null 2>&1 < /dev/tcp/localhost/$PORT; then
            break
        fi
        sleep 1
        attempt=$((attempt + 1))
    done
    sleep 1 # Brief pause to ensure the app is fully initialized

    if command -v xdg-open &>/dev/null; then
        xdg-open "http://localhost:$PORT" &>/dev/null &
    elif command -v open &>/dev/null; then
        open "http://localhost:$PORT" &>/dev/null &
    fi
}

log_run_header() {
    local run_num=$1
    {
        echo ""
        printf '─%.0s' {1..60}; echo ""
        if (( run_num == 1 )); then
            echo "  Run #$run_num started at $(date '+%Y-%m-%d %H:%M:%S')"
        else
            echo "  Restart #$(( run_num - 1 )) at $(date '+%Y-%m-%d %H:%M:%S')"
        fi
        printf '─%.0s' {1..60}; echo ""
    } >> "$LOG_FILE"
}

# ─────────────────────────────────────────────────────────────────────────────
# Watchdog loop
# python3 runs in the FOREGROUND piped to tee (blocking).
# Ctrl+C propagates SIGINT to the whole process group → cleanup() fires.
# Any non-zero / non-130 exit is treated as a crash → auto-restart.
# ─────────────────────────────────────────────────────────────────────────────
RUN=1
while true; do
    log_run_header $RUN

    if (( RUN == 1 )); then
        echo -e "${BOLD}  Starting Agnes server …${RESET}"
    else
        echo -e "${BOLD}  Restarting Agnes server (attempt $RESTART_COUNT) …${RESET}"
    fi
    echo -e "  ${CYAN}→${RESET}  Output streams to terminal and $LOG_FILE\n"
    sep
    echo ""

    # Open browser in background after server has a moment to bind
    open_browser &

    # ── Foreground execution — PIPESTATUS[0] = python3 exit code ─────────────
    python3 "$SCRIPT_DIR/agnes_ui.py" 2>&1 | tee -a "$LOG_FILE" || true
    EXIT="${PIPESTATUS[0]}"

    # 0 = normal exit · 130 = Ctrl+C (SIGINT) · 143 = SIGTERM → stop cleanly
    if [[ "$EXIT" -eq 0 || "$EXIT" -eq 130 || "$EXIT" -eq 143 ]]; then
        cleanup
    fi

    # Unexpected exit → crash, schedule restart
    RESTART_COUNT=$(( RESTART_COUNT + 1 ))
    echo ""
    sep
    echo -e "\n  ${YELLOW}${BOLD}⚠  Server exited unexpectedly (code $EXIT).${RESET}"
    echo -e "  ${YELLOW}Restarting in 3 s … (attempt $RESTART_COUNT)${RESET}"
    echo -e "  ${CYAN}→${RESET}  Press Ctrl+C now to abort.\n"
    sleep 3

    RUN=$(( RUN + 1 ))
done
