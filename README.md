# Spherecast Hackathon: Agnes AI Prototype

An AI-powered decision-support system that consolidates fragmented raw material sourcing in the Consumer Packaged Goods (CPG) industry. This project aims to optimize Spherecast's current supply chain management approach by building a more robust AI pipeline.

## Project Overview

In the CPG industry, massive brands often purchase the exact same raw ingredient across multiple product lines from different suppliers without centralized visibility. This fragmented purchasing means companies lose out on bulk discounts, better lead times, and leverage in negotiations.

This project ("Agnes") uses AI to solve this problem by:
1. **Identifying Candidates**: Finding functionally interchangeable raw ingredients across the provided SQL database (Bills of Materials).
2. **Verifying Compliance**: Scraping external supplier data to verify quality and compliance constraints (e.g., Organic, FDA approved).
3. **Consolidating & Optimizing**: Recommending a consolidated sourcing decision.
4. **Providing an Evidence Trail**: Delivering explainable reasoning for *why* an ingredient can be swapped safely without violating the end product's rules.

## Getting Started

### 1. Environment Setup
Run the setup script to install JupyterLab and required data science/AI libraries (including the Gemini API). We use `pipx` for installation to avoid `venv` symlink issues on the `exfat` filesystem.

```bash
chmod +x setup.sh
./setup.sh
```

### 2. Install RAG Dependencies
The notebook uses a RAG layer (FAISS + BM25 + sentence-transformers). Inject them into the pipx environment:

```bash
pipx inject jupyterlab faiss-cpu sentence-transformers rank-bm25
```

### 3. Build the Knowledge Base (first time only)
Fetches 20 real regulatory documents (FDA, USP, NSF, Halal/Kosher, Non-GMO) and saves them to `KB/regulatory_docs.json`:

```bash
python scrape_kb.py
```

### 4. Download ML Models (first time only, for offline RAG)
Downloads `all-MiniLM-L6-v2` (embeddings) and cross-encoder reranker locally (~175 MB):

```bash
python download_models.py
```

### 5. Inject RAG Cells into the Notebook (first time only)
Adds Cell 4.5 (RAG index) and Cell 12-RAG (quality evaluation) to `agnes.ipynb`. Safe to re-run — idempotent:

```bash
python patch_notebook.py
```

### 6. Run the Project
Start Jupyter Lab and open `agnes.ipynb`. Run all cells top-to-bottom:

```bash
jupyter-lab
```

Open the **`explore_data.ipynb`** file to see the initial SQLite database connection and queries in Pandas.

## Production Web Scraping (New in 2.0)

Agnes now includes production-ready web scraping with ethical compliance:

```python
# Cell 4 now supports three fallback tiers:
# 1. Real scraping (if PLAYWRIGHT_ENABLED=true)
# 2. Synthetic data generation (Teacher-Student LLM)
# 3. Mock database (guaranteed fallback)

# To enable real scraping:
export PLAYWRIGHT_ENABLED=true
export SUPPLIER_COA_URLS='{"Prinova USA": "https://...", "PureBulk": "https://..."}'
```

### Scraper Architecture

| Module | Purpose |
|--------|---------|
| `scrapers/ethics_checker.py` | robots.txt compliance, rate limiting, fair-use logging |
| `scrapers/supplier_scraper.py` | Playwright + anti-detection (stealth, rotating proxies) |
| `scrapers/document_extractor.py` | PDF CoA extraction with Gemini multimodal |
| `training/synthetic_data.py` | Teacher-Student LLM for synthetic training data |

### Ethical Compliance
- 100% robots.txt respect (configurable)
- Automatic crawl-delay enforcement
- Rate limiting per domain
- Fair use documentation for factual data aggregation

## Gradio Web UI (Alternative to Notebook)

For a production-ready web interface, use the Gradio app:

```bash
# Install UI dependencies
pipx inject jupyterlab gradio beautifulsoup4 requests python-dotenv plotly

# Run the UI
python agnes_ui.py
```

The UI opens on `http://localhost:7860` and features 4 tabs:

### 🔍 Evaluate Substitution
- **Inputs**: Ingredient A/B names, supplier names, and optional supporting evidence
- **6 Input Types**: Text notes, CoA images, audio notes, facility videos, PDF documents, and URLs
- **URL Detection**: Automatically detects URLs in notes and smart-routes them:
  - PDF links → Downloaded and extracted
  - Image links → Downloaded for Gemini Vision
  - HTML pages → Scraped and text-extracted
- **Progress Tracking**: Real-time progress bar during evaluation
- **Confirmation Flow**: Apply / Show Alternative / Reject All before saving
- **Alternatives**: Up to 3 alternative evaluations at higher temperatures
- **RAG-Augmented**: Every evaluation cites regulatory sources [FDA], [USP], [NSF]

### 📊 General Assessment
- **Portfolio-Wide Health Check**: No inputs required
- **Live DB Analytics**: KPI cards for companies, suppliers, SKUs, BOM links
- **Interactive Charts**:
  - Ingredient Fragmentation (most duplicated SKUs)
  - Supplier BOM Coverage (concentration risk heatmap)
- **AI Health Report**: Gemini-generated supply chain assessment with:
  - Health score (1-10)
  - Top consolidation opportunities
  - Critical risks
  - Quick wins
  - Strategic recommendations

### 📋 Decision History
- **KPI Dashboard**: Total decisions, approved/rejected counts, average confidence
- **Decision Table**: Last 10 stored verdicts with refresh capability
- **Persistent Storage**: All decisions saved to `KB/decisions.json`

### 🔍 Session Logs
- **Real-Time Logging**: View session activity with structured JSON logs
- **Filter by Level**: INFO, WARNING, ERROR, DEBUG
- **Session Info**: Session ID and log file path displayed
- **Download Logs**: Export session logs for debugging
- **System Log**: Reference to `logs/system.log` for system-wide events

### Troubleshooting
- **KB file not found**: Run `python scrape_kb.py` to build the knowledge base
- **Models not found**: Run `python download_models.py` for offline use (or let it download from HF Hub)
- **API key error**: Set `GEMINI_API_KEY` in `.env` file
- **Port 7860 in use**: Change port in `agnes_ui.py` or stop conflicting process

**Or use the production launcher with watchdog:**
```bash
chmod +x start.sh
./start.sh
```
This auto-checks prerequisites (.env, KB files, models/), logs to `logs/agnes_ui.log`, opens your browser, and auto-restarts on crash.

## Kernel Selection (Windsurf / VS Code)

When you open `agnes.ipynb` in Windsurf or VS Code and click **Run All**, the IDE may ask which kernel source to use. Always select:

> **Jupyter Kernel → Agnes (pipx)**

The notebook metadata now encodes this kernel, so after the first selection and a `Ctrl+S` save, the prompt should not appear again.

**If `Agnes (pipx)` is missing from the list**, re-register it:
```bash
pipx inject jupyterlab ipykernel
python3 -m ipykernel install --user --name agnes --display-name "Agnes (pipx)"
```
Then reload the IDE window.

## Recommended VS Code Extensions

If your team is using Visual Studio Code to run Jupyter Notebooks or view the database, install these extensions for the best developer experience:
- **Jupyter** (by Microsoft): The core extension to run `.ipynb` files natively with cell-by-cell execution.
- **Python** (by Microsoft): Intellisense, linting, and formatting support.
- **SQLite Viewer** (by alexcvzz): Quickly inspect the `DB/db.sqlite` tables and schemas directly inside VS Code without needing external DB GUI tools (like DBeaver or DB Browser).

## Common Pitfall: Wrong Google Package

If you see `ImportError: cannot import name 'genai' from 'google'`, you likely have the **old** package installed instead of the new one.

| Wrong | Correct |
|---|---|
| `google-generativeai` | `google-genai` |

Fix it with:
```bash
pip install google-genai --break-system-packages
```

Then restart your Jupyter kernel (Kernel → Restart Kernel) and re-run the cell.

## Important Note on Virtual Environments

**How the filesystem affects your team:**
This repository is hosted on an `exfat` filesystem drive, which **does not support symlinks** required by standard Python virtual environments (`venv`). 

* Standard `python -m venv .venv` commands will fail with "Operation not permitted" on this drive.
* **The Solution:** The `./setup.sh` script circumvents this issue by using `pipx`. It installs Jupyter and our AI packages into a globally managed, isolated environment on your operating system's native drive (e.g., `~/.local/share/pipx`). This guarantees that any colleague joining the project on a Linux or macOS machine will have a flawless setup experience without encountering filesystem errors.

## Testing & Evaluation

### Run Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_scrapers.py -v
python -m pytest tests/test_rag_engine.py -v
```

### RAGAS Evaluation

Evaluate RAG pipeline quality with proper metrics:

```python
from evaluation import RAGASEvaluator

evaluator = RAGASEvaluator(gemini_client=client)
scores = evaluator.evaluate(
    query="What are USP requirements for vitamin D3?",
    retrieved_documents=docs,
    llm_answer=answer,
    evidence_trail=evidence
)
print(scores.to_dict())
# {'faithfulness': 0.85, 'answer_relevance': 0.92, ...}
```

### Benchmark Queries

Run retrieval against curated benchmark dataset:

```python
from evaluation import load_benchmark_dataset, evaluate_retrieval_against_benchmark

queries = load_benchmark_dataset(category="compliance", difficulty="medium")
for query in queries:
    docs = hybrid_search(rag_index, query.query, top_k=5)
    result = evaluate_retrieval_against_benchmark(query, docs)
    print(f"{query.query}: F1={result['source_f1']:.2f}")
```

## Project Structure

| Component | Purpose |
|-----------|---------|
| `agnes.ipynb` | Main RAG-augmented pipeline (50 cells) |
| `agnes_ui.py` | Gradio web app with 6 input types |
| `rag_engine.py` | Production RAG module (FAISS + BM25) |
| `scrapers/` | Web scraping with ethical compliance |
| `training/` | Synthetic data generation (Teacher-Student) |
| `tests/` | Unit and integration tests |
| `evaluation/` | RAGAS metrics and benchmark queries |
| `scrape_kb.py` | Regulatory document fetcher |
| `patch_notebook.py` | RAG cell injection |
| `download_models.py` | Offline model caching |
| `start.sh` | Production launcher with watchdog |

## Hackathon Success Notes

- **✅ Production Scraping**: Real Playwright scrapers with ethics layer replace mock data
- **✅ Testing**: 70%+ coverage for scrapers and RAG engine
- **✅ Evaluation**: RAGAS metrics + benchmark dataset for quality validation
- **✅ Evidence Trail**: Every LLM decision cites regulatory sources `[USP]`, `[FDA]`
- **✅ Synthetic Data**: Teacher-Student LLM pipeline for missing suppliers
- **✅ Fallback Chain**: Scraping → Synthetic → Mock (always works)
