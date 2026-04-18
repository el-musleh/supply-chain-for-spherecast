# Repository Guidelines

## Project Structure & Module Organization

- `DB/db.sqlite` — SQLite database (61 companies, 876 raw materials, 40 suppliers, 149 BOMs, 1,528 BOM components).
- `agnes.ipynb` — Main 7-cell pipeline: DB ingestion → target selection → mock compliance enrichment → Gemini reasoning → consolidation → final report.
- `explore_data.ipynb` — Scratch notebook for ad-hoc DB queries.
- `.env` — Contains `GEMINI_API_KEY`; loaded via `python-dotenv`. Never commit this file (already in `.gitignore`).

**Non-obvious architecture detail:** Raw-material SKUs follow `RM-C{CompanyId}-{ingredient-name}-{8hexhash}`. Parsing the ingredient name out of the SKU (strip prefix via `SUBSTR`/`INSTR`, strip last 9 chars for the hash) reveals that multiple CPG companies independently buy the same ingredient under separate SKUs — this fragmentation is the core problem Agnes solves. All SQL CTEs in `agnes.ipynb` Cell 2 depend on this formula.

## Build & Development Commands

```bash
# First-time setup (uses pipx — required on exfat filesystem where venv symlinks fail)
chmod +x setup.sh && ./setup.sh

# Launch notebooks
jupyter-lab
```

**Important:** This repo lives on an `exfat` filesystem that does not support symlinks. Standard `python -m venv` will fail. All packages are managed via `pipx` into `~/.local/share/pipx`.

If `setup.sh` is unavailable, install manually:
```bash
pip install google-genai ipykernel python-dotenv pandas --break-system-packages
```

## LLM Integration

- Model: `gemini-flash-latest` via `google-genai` SDK (`import google.genai as genai`).
- API key: set `GEMINI_API_KEY` in `.env`; Cell 1 calls `load_dotenv()` then `genai.Client(api_key=...)`.
- Structured output: `response_mime_type="application/json"` + `temperature=0.2` — no markdown fence stripping needed.
- The system prompt in Cell 5 (`AGNES_SYSTEM_PROMPT`) hard-encodes compliance guardrails. Do not soften them — hallucination control is a primary judging criterion.

## Consolidation Logic

Cell 6 ranks suppliers by `bom_appearances_covered × compliance_weight`. Suppliers with LLM verdict `APPROVE`, `APPROVE_WITH_CONDITIONS`, or `HUMAN_REVIEW_REQUIRED` are included; only `REJECT` is excluded.

`compliance_weight` formula:
- Base: +1.0
- Pharmaceutical grade: +0.2 | FDA registered: +0.1 | Non-GMO: +0.1
- Per certification (USP, GMP, Halal, Kosher, etc.): +0.05, capped at +0.30
- Technical grade: −0.30 | Minimum floor: 0.10

## Commit Conventions

Four commits in history follow the pattern: `<Verb> <what> for <context>` (e.g., `Implements Agnes AI for CPG sourcing consolidation`). Keep messages imperative and descriptive.
