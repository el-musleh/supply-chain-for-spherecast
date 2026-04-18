# Repository Guidelines

## Project Structure & Module Organization

- `DB/db.sqlite` — SQLite database (61 companies, 876 raw materials, 40 suppliers, 149 BOMs, 1,528 BOM components).
- `agnes.ipynb` — Main RAG-augmented pipeline: DB ingestion → target selection → compliance enrichment → **Cell 4.M** (Multimodal CoA extraction) → RAG index (Cell 4.5) → **Cell 4.5-EMB** (joint embeddings) → Gemini reasoning (Cell 5) → consolidation → **Cell 10-OR** (bipartite matching rerouting) → RAGAS-lite evaluation (Cell 12-RAG) → executive dashboard. Total: 50 cells.
- `explore_data.ipynb` — Scratch notebook for ad-hoc DB queries.
- `.env` — Contains `GEMINI_API_KEY`; loaded via `python-dotenv`. Never commit this file (already in `.gitignore`).
- `rag_engine.py` — Production-ready RAG module. Public API: `build_index()`, `hybrid_search()`, `rerank()`, `store_decision()`, `retrieve_similar_cases()`, `format_context_block()`, `evaluate_rag_quality()`. Uses FAISS HNSW (M=32) + BM25 Okapi with `all-MiniLM-L6-v2` embeddings (384-dim).
- `scrape_kb.py` — Fetches 20 real regulatory documents (FDA 21 CFR 111, DSHEA, USP Vitamin D3 Monograph, NSF/ANSI 173, Halal/Kosher standards, Non-GMO Project, etc.) and writes them to `KB/regulatory_docs.json`. Run once before launching the notebook.
- `patch_notebook.py` — One-shot idempotent script that injects Cell 4.5 (RAG setup) and Cell 12-RAG (RAGAS-lite evaluation) into `agnes.ipynb`, and upgrades Cell 5 to use `evaluate_substitutability_rag()`. Run once after cloning.
- `enhance_cells.py` — One-shot idempotent script that injects three enhancement cells: Cell 4.M (Gemini Vision multimodal CoA extraction), Cell 4.5-EMB (ingredient joint embeddings via all-MiniLM-L6-v2), and Cell 10-OR (Hungarian-algorithm bipartite matching for optimal disruption rerouting). Run once after `patch_notebook.py`.
- `agnes_ui.py` — Gradio web app (run: `python agnes_ui.py`, opens on port 7860). Accepts 6 input types (text, image, audio, video, PDF, URL); auto-detects URLs in the notes field and smart-routes them (HTML→text, PDF→bytes, image→bytes); extracts structured compliance data via Gemini Vision; runs RAG evaluation; presents recommendation with Apply / Show Alternative / Reject All confirmation flow before writing to `KB/decisions.json`.
- `KB/regulatory_docs.json` — Generated knowledge base produced by `scrape_kb.py`. Not committed; re-generate if missing.

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

## Kernel Setup (Windsurf / VS Code)

`setup.sh` registers a Jupyter kernel named **`agnes`** (display name: `Agnes (pipx)`) that points to the pipx-managed Python at `~/.local/share/pipx/venvs/jupyter/bin/python`. The `agnes.ipynb` metadata encodes this kernel, so Windsurf and VS Code should connect automatically without prompting.

**If the kernel prompt still appears:** select `Jupyter Kernel` → `Agnes (pipx)`. After running one cell, save the file (`Ctrl+S`) to persist the selection.

**If `Agnes (pipx)` is missing from the list**, re-register it:
```bash
pipx inject jupyterlab ipykernel
python3 -m ipykernel install --user --name agnes --display-name "Agnes (pipx)"
```

## RAG Pipeline

The RAG layer grounds every Gemini compliance decision in real regulatory documents. Run in this order on first setup:

```bash
# 1. Build the knowledge base (fetches 20 regulatory pages, saves KB/regulatory_docs.json)
python scrape_kb.py

# 2. Inject RAG cells into agnes.ipynb (idempotent — safe to re-run)
python patch_notebook.py

# 3. Launch the notebook and run cells top-to-bottom
jupyter-lab
```

RAG-specific dependencies (inject into the pipx environment if missing):
```bash
pipx inject jupyterlab faiss-cpu sentence-transformers rank-bm25
```

**RAG data flow:** `scrape_kb.py` → `KB/regulatory_docs.json` → Cell 4.5 (`build_index`) → Cell 5 (`hybrid_search` + `rerank` + Gemini prompt injection) → `KB/decisions.json` (historical memory) → Cell 12-RAG (RAGAS-lite quality scores).

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
