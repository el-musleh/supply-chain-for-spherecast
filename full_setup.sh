#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# full_setup.sh — Unified Setup Script for Agnes 2.0
#
# This script performs all first-time setup steps:
#   1. Check .env file
#   2. Build knowledge base (scrape_kb.py)
#   3. Download ML models (download_models.py)
#   4. Inject RAG cells (patch_notebook.py)
#   5. Print setup summary
#
# Usage:
#   chmod +x full_setup.sh
#   ./full_setup.sh
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
KB_FILE="$SCRIPT_DIR/KB/regulatory_docs.json"
MODELS_DIR="$SCRIPT_DIR/models"
NOTEBOOK_FILE="$SCRIPT_DIR/agnes.ipynb"
ENV_FILE="$SCRIPT_DIR/.env"

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║     Agnes 2.0 — Unified Setup Script                ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo -e "  ${BOLD}Started :${RESET} $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
sep
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Check .env file
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Step 1: Checking .env file${RESET}\n"

if [[ -f "$ENV_FILE" ]]; then
    API_KEY_VAL=$(grep -E '^GEMINI_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [[ -n "$API_KEY_VAL" ]]; then
        ok ".env exists with GEMINI_API_KEY (${#API_KEY_VAL} chars)"
    else
        warn ".env exists but GEMINI_API_KEY is empty"
        echo -e "       Add your key: echo \"GEMINI_API_KEY=your-key-here\" >> .env"
    fi
else
    err ".env file missing"
    echo -e "       Create it with: echo \"GEMINI_API_KEY=your-key-here\" > .env"
    echo -e "       Get your key from: https://aistudio.google.com/app/apikey"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Build Knowledge Base
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Step 2: Building Knowledge Base${RESET}\n"

if [[ -f "$KB_FILE" ]]; then
    DOC_COUNT=$(python3 -c "import json; d=json.load(open('$KB_FILE')); print(len(d))" 2>/dev/null || echo "?")
    ok "KB/regulatory_docs.json already exists ($DOC_COUNT documents)"
    echo -e "       Re-run manually if needed: python scrape_kb.py"
else
    info "KB/regulatory_docs.json not found — building..."
    if python3 "$SCRIPT_DIR/scrape_kb.py"; then
        DOC_COUNT=$(python3 -c "import json; d=json.load(open('$KB_FILE')); print(len(d))" 2>/dev/null || echo "?")
        ok "KB built successfully ($DOC_COUNT documents)"
    else
        err "scrape_kb.py failed"
        echo -e "       Check your network connection and retry"
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Download ML Models
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Step 3: Downloading ML Models${RESET}\n"

if [[ -d "$MODELS_DIR/all-MiniLM-L6-v2" && -d "$MODELS_DIR/cross-encoder-reranker" ]]; then
    MODEL_MB=$(du -sm "$MODELS_DIR" 2>/dev/null | cut -f1 || echo "?")
    ok "Local models already cached (${MODEL_MB} MB) — offline mode ready"
    echo -e "       Re-download manually if needed: python download_models.py"
else
    info "Local models not found — downloading (~175 MB)..."
    if python3 "$SCRIPT_DIR/download_models.py"; then
        MODEL_MB=$(du -sm "$MODELS_DIR" 2>/dev/null | cut -f1 || echo "?")
        ok "Models downloaded successfully (${MODEL_MB} MB)"
    else
        err "download_models.py failed"
        echo -e "       Check your network connection and retry"
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Inject RAG Cells
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Step 4: Injecting RAG Cells${RESET}\n"

# Check if already patched
if python3 -c "
import json
nb = json.load(open('$NOTEBOOK_FILE'))
for cell in nb['cells']:
    src = ''.join(cell.get('source', []))
    if 'CELL 4.5' in src and 'RAG Compliance Knowledge Base' in src:
        exit(0)
exit(1)
" 2>/dev/null; then
    ok "RAG cells already injected in agnes.ipynb"
    echo -e "       Re-run manually if needed: python patch_notebook.py"
else
    info "RAG cells not found — injecting..."
    if python3 "$SCRIPT_DIR/patch_notebook.py"; then
        ok "RAG cells injected successfully"
    else
        err "patch_notebook.py failed"
        echo -e "       Check the error output above"
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Generate Dashboard Signals
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Step 5: Generating Dashboard Signals${RESET}\n"

DASHBOARD_FILE="$SCRIPT_DIR/KB/dashboard_signals.json"

if [[ -f "$DASHBOARD_FILE" ]]; then
    ING_COUNT=$(python3 -c "import json; d=json.load(open('$DASHBOARD_FILE')); print(len(d))" 2>/dev/null || echo "?")
    ok "KB/dashboard_signals.json already exists ($ING_COUNT ingredients)"
    echo -e "       Re-generate manually: python generate_dashboard.py"
else
    info "KB/dashboard_signals.json not found — generating..."
    if python3 "$SCRIPT_DIR/generate_dashboard.py"; then
        ING_COUNT=$(python3 -c "import json; d=json.load(open('$DASHBOARD_FILE')); print(len(d))" 2>/dev/null || echo "?")
        ok "Dashboard signals generated successfully ($ING_COUNT ingredients)"
    else
        err "generate_dashboard.py failed"
        echo -e "       Check your DB connection and retry"
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Setup Summary
# ─────────────────────────────────────────────────────────────────────────────
echo ""
sep
echo ""
echo -e "${BOLD}  Setup Complete!${RESET}"
echo ""
echo -e "  ${GREEN}✓${RESET}  .env configured"
echo -e "  ${GREEN}✓${RESET}  Knowledge base built (KB/regulatory_docs.json)"
echo -e "  ${GREEN}✓${RESET}  ML models downloaded (models/)"
echo -e "  ${GREEN}✓${RESET}  RAG cells injected (agnes.ipynb)"
echo -e "  ${GREEN}✓${RESET}  Dashboard signals generated (KB/dashboard_signals.json)"
echo ""
sep
echo ""
echo -e "  ${BOLD}Next Steps:${RESET}"
echo ""
echo -e "  1. Launch Jupyter Notebook:"
echo -e "       jupyter-lab"
echo ""
echo -e "  2. Or launch the Gradio Web UI:"
echo -e "       python agnes_ui.py"
echo ""
echo -e "  3. Or use the production launcher:"
echo -e "       ./start.sh"
echo ""
sep
echo ""
