#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run_tests.sh — Agnes Test Runner
#
# Usage:
#   chmod +x run_tests.sh
#   ./run_tests.sh [options]
#
# Options:
#   --unit          Run unit tests (pytest tests/)
#   --scrapers      Run scraper tests with mock responses
#   --rag           Run RAG evaluation tests
#   --integration   Run full pipeline integration test
#   --ci            Run all tests (CI/CD mode)
#   --coverage      Generate coverage report
#   --verbose       Verbose output
#   --help          Show this help message
#
# Examples:
#   ./run_tests.sh --unit --verbose
#   ./run_tests.sh --ci --coverage
#   ./run_tests.sh --integration
# ─────────────────────────────────────────────────────────────────────────────

set -uo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✗${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
sep()  { echo -e "${CYAN}$(printf '─%.0s' {1..60})${RESET}"; }

# ── State ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$SCRIPT_DIR/tests"
LOGS_DIR="$SCRIPT_DIR/logs"
RESULTS_FILE="$LOGS_DIR/test_results.json"

# Default options
RUN_UNIT=false
RUN_SCRAPERS=false
RUN_RAG=false
RUN_INTEGRATION=false
RUN_COVERAGE=false
VERBOSE=false
CI_MODE=false

# ── Parse arguments ───────────────────────────────────────────────────────────
usage() {
    head -n 23 "$0" | tail -n 20
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --unit) RUN_UNIT=true ;;
        --scrapers) RUN_SCRAPERS=true ;;
        --rag) RUN_RAG=true ;;
        --integration) RUN_INTEGRATION=true ;;
        --ci) CI_MODE=true; RUN_UNIT=true; RUN_SCRAPERS=true; RUN_RAG=true; RUN_INTEGRATION=true ;;
        --coverage) RUN_COVERAGE=true ;;
        --verbose) VERBOSE=true ;;
        --help) usage ;;
        *) err "Unknown option: $1"; usage ;;
    esac
    shift
done

# Default to unit tests if no specific tests requested
if [[ "$RUN_UNIT" == false && "$RUN_SCRAPERS" == false && "$RUN_RAG" == false && "$RUN_INTEGRATION" == false ]]; then
    RUN_UNIT=true
fi

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo -e "${CYAN}${BOLD}"
echo "  ╔═══════════════════════════════════════════════════════════╗"
echo "  ║              Agnes 2.0 — Test Runner                      ║"
echo "  ╚═══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

mkdir -p "$LOGS_DIR"

# ── Initialize results ─────────────────────────────────────────────────────────
PASSED=0
FAILED=0
SKIPPED=0
RESULTS=()

record_result() {
    local name="$1" status="$2" duration="$3" output="$4"
    RESULTS+=("{\"test\": \"$name\", \"status\": \"$status\", \"duration_ms\": $duration}")
    if [[ "$status" == "PASS" ]]; then
        ((PASSED++))
        ok "$name (${duration}ms)"
    elif [[ "$status" == "SKIP" ]]; then
        ((SKIPPED++))
        warn "$name (skipped)"
    else
        ((FAILED++))
        err "$name (${duration}ms)"
        if [[ "$VERBOSE" == true ]]; then
            echo "$output"
        fi
    fi
}

# ── Test Functions ─────────────────────────────────────────────────────────────

run_unit_tests() {
    info "Running unit tests..."
    local start=$(date +%s%N)
    
    if ! command -v pytest &>/dev/null; then
        warn "pytest not found, installing..."
        pip install pytest --break-system-packages -q
    fi
    
    local output
    local pytest_args="-v"
    [[ "$CI_MODE" == true ]] && pytest_args="-v --tb=short"
    [[ "$RUN_COVERAGE" == true ]] && pytest_args="$pytest_args --cov=. --cov-report=term-missing --cov-report=html:$LOGS_DIR/coverage"
    
    output=$(cd "$SCRIPT_DIR" && python -m pytest "$TESTS_DIR" $pytest_args 2>&1)
    local exit_code=$?
    
    local end=$(date +%s%N)
    local duration=$(( (end - start) / 1000000 ))
    
    if [[ $exit_code -eq 0 ]]; then
        record_result "unit_tests" "PASS" "$duration" ""
    else
        record_result "unit_tests" "FAIL" "$duration" "$output"
    fi
    
    return $exit_code
}

run_scraper_tests() {
    info "Running scraper tests..."
    local start=$(date +%s%N)
    
    # Check if scrapers module is importable
    local output
    output=$(cd "$SCRIPT_DIR" && python3 -c "
from scrapers import ComplianceProfile, EthicsChecker, SupplierScraper, CoAExtractor
from scrapers.ethics_checker import EthicsChecker
print('All scraper modules importable')
" 2>&1)
    local exit_code=$?
    
    local end=$(date +%s%N)
    local duration=$(( (end - start) / 1000000 ))
    
    if [[ $exit_code -eq 0 ]]; then
        record_result "scraper_imports" "PASS" "$duration" ""
    else
        record_result "scraper_imports" "FAIL" "$duration" "$output"
        return 1
    fi
    
    # Run scraper unit tests if they exist
    if [[ -f "$TESTS_DIR/test_scrapers.py" ]]; then
        start=$(date +%s%N)
        output=$(cd "$SCRIPT_DIR" && python -m pytest "$TESTS_DIR/test_scrapers.py" -v 2>&1)
        exit_code=$?
        end=$(date +%s%N)
        duration=$(( (end - start) / 1000000 ))
        
        if [[ $exit_code -eq 0 ]]; then
            record_result "scraper_unit" "PASS" "$duration" ""
        else
            record_result "scraper_unit" "FAIL" "$duration" "$output"
        fi
    fi
    
    return 0
}

run_rag_tests() {
    info "Running RAG engine tests..."
    local start=$(date +%s%N)
    
    local output
    output=$(cd "$SCRIPT_DIR" && python3 -c "
from rag_engine import build_index, hybrid_search, rerank, format_context_block
print('RAG engine imports successful')

# Test that KB exists
import os
kb_path = 'KB/regulatory_docs.json'
if os.path.exists(kb_path):
    import json
    with open(kb_path) as f:
        docs = json.load(f)
    print(f'KB loaded: {len(docs)} documents')
else:
    print('WARNING: KB not found, some tests may fail')
" 2>&1)
    local exit_code=$?
    
    local end=$(date +%s%N)
    local duration=$(( (end - start) / 1000000 ))
    
    if [[ $exit_code -eq 0 ]]; then
        record_result "rag_imports" "PASS" "$duration" ""
    else
        record_result "rag_imports" "FAIL" "$duration" "$output"
        return 1
    fi
    
    # Run RAG unit tests if they exist
    if [[ -f "$TESTS_DIR/test_rag_engine.py" ]]; then
        start=$(date +%s%N)
        output=$(cd "$SCRIPT_DIR" && python -m pytest "$TESTS_DIR/test_rag_engine.py" -v 2>&1)
        exit_code=$?
        end=$(date +%s%N)
        duration=$(( (end - start) / 1000000 ))
        
        if [[ $exit_code -eq 0 ]]; then
            record_result "rag_unit" "PASS" "$duration" ""
        else
            record_result "rag_unit" "FAIL" "$duration" "$output"
        fi
    fi
    
    return 0
}

run_integration_test() {
    info "Running integration test..."
    local start=$(date +%s%N)
    
    # Check environment
    local output
    output=$(cd "$SCRIPT_DIR" && python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()

errors = []
warnings = []

# Check .env
if not os.path.exists('.env'):
    errors.append('.env file missing')
elif not os.getenv('GEMINI_API_KEY'):
    errors.append('GEMINI_API_KEY not set in .env')

# Check KB
if not os.path.exists('KB/regulatory_docs.json'):
    errors.append('KB/regulatory_docs.json missing')

# Check models
if not os.path.exists('models/all-MiniLM-L6-v2'):
    warnings.append('Embedding model not cached (will download on first use)')

# Check DB
if not os.path.exists('DB/db.sqlite'):
    errors.append('Database not found at DB/db.sqlite')

if errors:
    print('ERRORS:')
    for e in errors:
        print(f'  - {e}')
    exit(1)

if warnings:
    print('WARNINGS:')
    for w in warnings:
        print(f'  - {w}')

print('Environment check passed')
" 2>&1)
    local exit_code=$?
    
    local end=$(date +%s%N)
    local duration=$(( (end - start) / 1000000 ))
    
    if [[ $exit_code -eq 0 ]]; then
        record_result "integration_env" "PASS" "$duration" ""
    else
        record_result "integration_env" "FAIL" "$duration" "$output"
        return 1
    fi
    
    # Run a quick end-to-end test
    start=$(date +%s%N)
    output=$(cd "$SCRIPT_DIR" && python3 -c "
# Quick smoke test
from agnes_ui import _build_parts, _extract_compliance, _evaluate
from rag_engine import build_index
import os

print('Loading RAG index...')
try:
    idx = build_index('KB/regulatory_docs.json')
    print(f'RAG index: {len(idx.docs)} docs')
except Exception as e:
    print(f'RAG index load failed: {e}')

# Test with minimal data
print('Testing evaluation pipeline...')
comp_a = {'grade': 'pharmaceutical', 'fda_registered': True, 'certifications': ['USP']}
comp_b = {'grade': 'food', 'fda_registered': True, 'certifications': []}

try:
    result, docs = _evaluate('vitamin-d3', 'Supplier A', comp_a, 
                            'vitamin-d3', 'Supplier B', comp_b)
    print(f'Evaluation result: {result.get(\"recommendation\", \"ERROR\")}')
    print(f'Docs retrieved: {len(docs)}')
    print('Integration test PASSED')
except Exception as e:
    print(f'Integration test FAILED: {e}')
    exit(1)
" 2>&1)
    exit_code=$?
    
    end=$(date +%s%N)
    duration=$(( (end - start) / 1000000 ))
    
    if [[ $exit_code -eq 0 ]]; then
        record_result "integration_e2e" "PASS" "$duration" ""
    else
        record_result "integration_e2e" "FAIL" "$duration" "$output"
    fi
    
    return $exit_code
}

# ── Execute Tests ─────────────────────────────────────────────────────────────
sep
echo ""

[[ "$RUN_UNIT" == true ]] && run_unit_tests
[[ "$RUN_SCRAPERS" == true ]] && run_scraper_tests
[[ "$RUN_RAG" == true ]] && run_rag_tests
[[ "$RUN_INTEGRATION" == true ]] && run_integration_test

# ── Summary ───────────────────────────────────────────────────────────────────
sep
echo ""
echo -e "${BOLD}Test Summary${RESET}"
echo ""
echo -e "  ${GREEN}Passed:${RESET}  $PASSED"
echo -e "  ${RED}Failed:${RESET}  $FAILED"
echo -e "  ${YELLOW}Skipped:${RESET} $SKIPPED"
echo ""

# Save results to JSON
if command -v python3 &>/dev/null; then
    python3 -c "
import json
import datetime

results = {
    'timestamp': datetime.datetime.now().isoformat(),
    'passed': $PASSED,
    'failed': $FAILED,
    'skipped': $SKIPPED,
    'total': $((PASSED + FAILED + SKIPPED)),
    'tests': [$(IFS=,; echo "${RESULTS[*]}")]
}

with open('$RESULTS_FILE', 'w') as f:
    json.dump(results, f, indent=2)

print(f'Results saved to: $RESULTS_FILE')
"
fi

sep

# Exit with appropriate code
[[ $FAILED -eq 0 ]] && exit 0 || exit 1
