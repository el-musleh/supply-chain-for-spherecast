# Agnes 2.0 — RAG Integration Plan (Best Results)

Add a production-grade RAG layer to `agnes.ipynb` that grounds every LLM compliance decision in real scraped regulatory knowledge, with a clean module boundary that can be lifted directly into a future web app.

---

## Architecture Decision

- **Two files**: `rag_engine.py` (the reusable module) + new cells in `agnes.ipynb` that import it.
- `rag_engine.py` is the "production web app ready" artifact — no notebook-specific code inside it.
- Notebook cells stay thin: build index → call retrieval → pass context to Gemini.

---

## Phase 1 — Real Compliance Knowledge Base (scraping)
**~3–4 h | Highest hackathon scoring impact**

### Step 1: Create `rag_engine.py`
Reusable module, importable by both the notebook and the future web app.

```
rag_engine.py
├── scrape_regulatory_docs()   ← fetch real pages (FDA, USP, GMP, Halal, NSF)
├── build_index()              ← FAISS HNSW + BM25
├── hybrid_search(query, k)    ← α·vector + (1−α)·BM25, returns top-k docs
├── rerank(query, docs)        ← cross-encoder re-ranker (sentence-transformers)
├── store_decision()           ← append to decisions.json (historical memory)
└── retrieve_similar_cases()   ← BM25 over past decisions
```

### Step 2: Scrape real regulatory pages
Target URLs (publicly available, no auth needed):

| Source | Content |
|--------|---------|
| FDA 21 CFR Part 111 | Dietary supplement GMP |
| FDA Dietary Supplement Health & Education Act | DSHEA requirements |
| USP General Notices | Grade definitions |
| FDA Halal / Kosher guidance | Certification criteria |
| NSF/ANSI 173 summary | Supplement certification |
| IFANCA Halal standards | Halal criteria |
| Non-GMO Project standard | Non-GMO requirements |

Store as `KB/regulatory_docs.json` — versioned, human-readable, easy to show judges.

### Step 3: Index with FAISS HNSW + BM25
```python
# In rag_engine.py
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-dim, fast
index = faiss.IndexHNSWFlat(384, M=32)  # HNSW, no IVF needed at this scale
bm25  = BM25Okapi(tokenized_docs)
```

### Step 4: New Cell 4.5 in notebook — RAG Setup
```python
from rag_engine import build_index, hybrid_search, rerank
rag_index = build_index("KB/regulatory_docs.json")
print(f"RAG KB loaded: {len(rag_index.docs)} documents indexed")
```

---

## Phase 2 — Modify Cell 5 (LLM + RAG)
**~1 h | Direct scoring lift on "evidence quality" criterion**

Replace the current bare LLM call with a RAG-augmented version:

1. Build query from ingredient pair + compliance fields
2. `hybrid_search()` → top-5 regulatory docs
3. `rerank()` → filter to top-3 most relevant
4. Inject retrieved context into Gemini prompt BEFORE the evaluation block
5. Add `sources_cited` field to LLM JSON output schema
6. Evidence trail items must now reference a source: `"[USP <2750>] Dietary supplement grade requires..."`

Updated AGNES_SYSTEM_PROMPT addition:
```
GROUNDING RULE:
- Use the REGULATORY CONTEXT section to support your evidence trail.
- Each evidence_trail item SHOULD cite its source in [brackets] when retrieved context supports it.
- Do NOT cite a source if you are not sure it says what you claim.
```

---

## Phase 3 — Historical Decision Memory
**~1 h | Enables "scales over time" narrative for judges**

- After every `evaluate_substitutability()` call, `store_decision()` appends to `KB/decisions.json`
- Before each new evaluation, `retrieve_similar_cases()` finds the 2–3 most similar past verdicts
- Injected into prompt as "PRECEDENT CASES" block
- Demonstrates continuous learning — a strong scalability story

---

## Phase 4 — RAGAS-lite Evaluation
**~1 h | Shows evaluation discipline — rare among hackathon teams**

Build a minimal RAGAS-style evaluation **without the RAGAS library** (avoids install complexity):

New Cell 12 — RAG Quality Report:
```
Faithfulness   : Are evidence_trail facts supported by retrieved docs?
               → Check: does the fact text appear in any retrieved doc?

Answer Relevance: Is the recommendation consistent with the retrieved context?
               → Gemini self-eval: "Rate 1-5: Does this verdict follow from this context?"

Context Recall : Were the most relevant docs actually retrieved?
               → Use existing decisions as ground truth
```

Output: a clean table with scores per evaluation — shows judges you measure your own quality.

---

## Phase 5 — Production Bridge
**~30 min | No extra code — just structure**

`rag_engine.py` is already the production module. Document the production upgrade path in a `docs/RAG_Architecture.md`:

| Hackathon (now) | Production (web app) |
|-----------------|----------------------|
| `faiss-cpu` local index | Qdrant Cloud / Weaviate |
| `all-MiniLM-L6-v2` | `text-embedding-3-small` (OpenAI) |
| `decisions.json` flat file | PostgreSQL vector table |
| Playwright scraping on-demand | Scheduled nightly scraper job |
| BM25 via `rank-bm25` | Elasticsearch BM25 |
| `sentence-transformers` reranker | Cohere Rerank API |

---

## Dependencies to Add to `requirements.txt`

```
sentence-transformers>=2.7.0
faiss-cpu>=1.8.0
rank-bm25>=0.2.2
```

No heavy new dependencies. All run locally on CPU without GPU.

---

## Notebook Cell Map (Final State)

| Cell | Content |
|------|---------|
| 1 | Setup (unchanged) |
| 1.5 | DB exploration (unchanged) |
| 2 | Fragmented demand ingestion (unchanged) |
| 3 | Target selection (unchanged) |
| 4 | Mock compliance enrichment (unchanged) |
| **4.5 NEW** | **RAG Engine setup — scrape + index + test queries** |
| 5 | LLM evaluation **modified** — now RAG-grounded with source citations |
| 5.5 | Self-monitoring (unchanged, picks up new `sources_cited` field) |
| 6-OR | ILP optimization (unchanged) |
| 7 | Report (minor: show sources in evidence trail) |
| 8-OR | Bayesian trust (unchanged) |
| 9-OR | TOPSIS risk heat map (unchanged) |
| 10 | Disruption simulator (unchanged) |
| 11-OR | Shapley GPO (unchanged) |
| **12 NEW** | **RAG Quality Report (faithfulness, relevance, recall)** |

---

## Judging Criteria Coverage

| Criterion | Addressed By |
|-----------|-------------|
| Evidence trails | Source-cited evidence trail in Cell 5 |
| Trustworthiness / hallucination control | Retrieved context grounds LLM; reranker filters noise |
| External data sourcing | Real scraped regulatory docs (FDA, USP, GMP, Halal, NSF) |
| Soundness of substitution logic | LLM now reasons FROM documents, not just from training data |
| Scalability | `rag_engine.py` module + production upgrade table |
| Quality of final sourcing proposal | RAGAS-lite self-evaluation shows measurable quality |

---

## Time Budget

| Phase | Time |
|-------|------|
| Phase 1 — scrape + build `rag_engine.py` + Cell 4.5 | 3–4 h |
| Phase 2 — modify Cell 5 | 1 h |
| Phase 3 — historical memory | 1 h |
| Phase 4 — RAGAS-lite Cell 12 | 1 h |
| Phase 5 — production doc | 30 min |
| Testing + polish | 1 h |
| **Total** | **~8 h** |

Leaves 16+ h for presentation prep, demo rehearsal, and other notebook polish.
