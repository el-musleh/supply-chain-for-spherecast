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

### 4. Inject RAG Cells into the Notebook (first time only)
Adds Cell 4.5 (RAG index) and Cell 12-RAG (quality evaluation) to `agnes.ipynb`. Safe to re-run — idempotent:

```bash
python patch_notebook.py
```

### 5. Run the Project
Start Jupyter Lab and open `agnes.ipynb`. Run all cells top-to-bottom:

```bash
jupyter-lab
```

Open the **`explore_data.ipynb`** file to see the initial SQLite database connection and queries in Pandas.

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

## Future Considerations for the 1.5-Day Sprint

To succeed in this hackathon, we must aggressively manage our scope:
- **Narrow the Domain**: Do not try to optimize the entire database. Focus on proving the concept with *one* specific ingredient category (e.g., "Sweeteners" or "Vitamins").
- **Mock the Web Scraper**: External web scraping is brittle and time-consuming. We should scrape 2 or 3 supplier websites perfectly and mock the retrieval for the rest during the demo to focus all effort on the AI reasoning.
- **Focus on the "Evidence Trail"**: UI polish is not a priority. The final output must clearly state *why* a recommendation was made (e.g., "We recommend Supplier B because their ingredient saves X% and we verified their Organic certification via [Link]").
