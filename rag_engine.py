"""
rag_engine.py — Agnes RAG Engine

Production-ready module for Retrieval-Augmented Generation over the
Agnes compliance knowledge base.

Importable by both agnes.ipynb (hackathon) and a future web app.

Public API
----------
build_index(kb_path)                → RagIndex
hybrid_search(index, query, top_k)  → list[dict]
rerank(query, docs, top_n)          → list[dict]
store_decision(decision)            → None
retrieve_similar_cases(query, top_k)→ list[dict]
format_context_block(docs)          → str
"""

from __future__ import annotations

import json
import os
import re
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

# ── Optional heavy dependencies (imported lazily) ────────────────────────────
# faiss, sentence_transformers, rank_bm25 are required at runtime.
# We import them lazily so that importing this module doesn't fail if they
# haven't been installed yet — a useful property for testing.


def _check_rag_dependencies() -> None:
    """
    Verify RAG dependencies are installed. Raise ImportError with install
    instructions if any are missing.
    """
    missing = []
    required = [
        ("faiss", "faiss-cpu"),
        ("sentence_transformers", "sentence-transformers"),
        ("rank_bm25", "rank-bm25"),
    ]
    for module, package in required:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        raise ImportError(
            f"RAG dependencies missing: {missing}\n"
            f"Install with: pipx inject jupyterlab {' '.join(missing)}\n"
            f"Or: pip install {' '.join(missing)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RagIndex:
    """
    Holds the FAISS HNSW vector index, BM25 index, and raw documents.
    Produced by build_index() and consumed by hybrid_search().
    """
    docs: list[dict]
    faiss_index: object          # faiss.Index
    bm25: object                 # BM25Okapi
    embedding_model: object      # SentenceTransformer
    tokenized_docs: list[list]   # pre-tokenized for BM25

    # --- Production upgrade path ---
    # Replace faiss_index with a Qdrant/Weaviate client.
    # Replace bm25 with an Elasticsearch BM25 endpoint.
    # Replace embedding_model with OpenAI text-embedding-3-small.


# ─────────────────────────────────────────────────────────────────────────────
# Index building
# ─────────────────────────────────────────────────────────────────────────────

def build_index(kb_path: str = "KB/regulatory_docs.json") -> RagIndex:
    """
    Load the knowledge base JSON and build FAISS HNSW + BM25 indexes.

    Parameters
    ----------
    kb_path : str
        Path to the regulatory_docs.json file produced by scrape_kb.py.

    Returns
    -------
    RagIndex
        Fully initialized index ready for hybrid_search().
    """
    _check_rag_dependencies()
    import faiss
    from sentence_transformers import SentenceTransformer
    from rank_bm25 import BM25Okapi

    kb_path = Path(kb_path)
    if not kb_path.exists():
        raise FileNotFoundError(
            f"Knowledge base not found at '{kb_path}'.\n"
            "Run: python scrape_kb.py"
        )

    with open(kb_path, encoding="utf-8") as f:
        docs = json.load(f)

    from transformers import logging as _hf_logging
    _hf_logging.set_verbosity_error()
    _hf_logging.disable_progress_bar()

    _emb_local = Path(__file__).parent / "models" / "all-MiniLM-L6-v2"
    _emb_path  = str(_emb_local) if _emb_local.exists() else "all-MiniLM-L6-v2"
    _emb_src   = "local" if _emb_local.exists() else "HF Hub"
    print(f"  Loading embedding model ({_emb_src}) ...", end=" ", flush=True)
    if not _emb_local.exists():
        print(f"\n  💡 Tip: Run 'python download_models.py' for offline use", end=" ", flush=True)
    model = SentenceTransformer(_emb_path)
    print("done")

    # Build combined text for each document
    doc_texts = [
        f"{doc['title']} {doc['source']} {doc['content']}"
        for doc in docs
    ]

    # FAISS HNSW index (384-dim, M=32 for small corpus)
    print(f"  Encoding {len(docs)} documents ...", end=" ", flush=True)
    embeddings = model.encode(doc_texts, show_progress_bar=False, normalize_embeddings=True)
    print("done")

    dim = embeddings.shape[1]
    faiss_index = faiss.IndexHNSWFlat(dim, 32)   # M=32, ef_construction default
    faiss_index.hnsw.efSearch = 64                # higher ef = better recall
    faiss_index.add(embeddings.astype(np.float32))

    # BM25 index
    tokenized_docs = [_tokenize(t) for t in doc_texts]
    bm25 = BM25Okapi(tokenized_docs)

    print(f"  Index built: {len(docs)} docs | FAISS HNSW (M=32) | BM25 Okapi")
    return RagIndex(
        docs=docs,
        faiss_index=faiss_index,
        bm25=bm25,
        embedding_model=model,
        tokenized_docs=tokenized_docs,
    )


def _tokenize(text: str) -> list[str]:
    """Simple lowercase tokenizer for BM25."""
    return re.findall(r"[a-z0-9]+", text.lower())


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval
# ─────────────────────────────────────────────────────────────────────────────

def hybrid_search(
    index: RagIndex,
    query: str,
    top_k: int = 5,
    alpha: float = 0.65,
) -> list[dict]:
    """
    Hybrid retrieval: alpha * vector_score + (1-alpha) * BM25_score.

    Parameters
    ----------
    index   : RagIndex   Pre-built index from build_index().
    query   : str        Natural language query.
    top_k   : int        Number of results to return.
    alpha   : float      Weight for vector score (0 = pure BM25, 1 = pure vector).

    Returns
    -------
    list[dict]   Documents sorted by combined score, each with a 'rag_score' key.
    """
    n_docs = len(index.docs)
    candidate_k = min(n_docs, top_k * 3)   # over-fetch for fusion

    # ── Vector search ────────────────────────────────────────────────────────
    query_emb = index.embedding_model.encode(
        [query], normalize_embeddings=True, show_progress_bar=False
    ).astype(np.float32)

    distances, v_indices = index.faiss_index.search(query_emb, candidate_k)
    # Inner-product with normalized vectors == cosine similarity
    vector_scores = {int(idx): float(score)
                     for idx, score in zip(v_indices[0], distances[0])
                     if idx >= 0}

    # ── BM25 search ──────────────────────────────────────────────────────────
    tokenized_query = _tokenize(query)
    bm25_raw = index.bm25.get_scores(tokenized_query)

    bm25_max = float(bm25_raw.max()) if bm25_raw.max() > 0 else 1.0
    bm25_scores = {i: float(bm25_raw[i]) / bm25_max for i in range(n_docs)}

    # ── Reciprocal Rank Fusion (RRF) variant with alpha weighting ─────────────
    # Normalize vector scores to [0, 1]
    v_max = max(vector_scores.values(), default=1.0)
    v_min = min(vector_scores.values(), default=0.0)
    v_range = (v_max - v_min) or 1.0

    combined: dict[int, float] = {}
    all_indices = set(vector_scores) | set(range(n_docs))

    for idx in all_indices:
        v_score = (vector_scores.get(idx, 0.0) - v_min) / v_range
        b_score = bm25_scores.get(idx, 0.0)
        combined[idx] = alpha * v_score + (1.0 - alpha) * b_score

    # Sort and take top_k
    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]

    result = []
    for idx, score in ranked:
        doc = dict(index.docs[idx])
        doc["rag_score"] = round(score, 4)
        result.append(doc)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Re-ranking
# ─────────────────────────────────────────────────────────────────────────────

def rerank(query: str, docs: list[dict], top_n: int = 3) -> list[dict]:
    """
    Cross-encoder re-ranking using sentence-transformers CrossEncoder.

    Filters and re-orders `docs` by relevance to `query`.
    Falls back to the original order if the cross-encoder is unavailable.

    Parameters
    ----------
    query   : str         Query used for retrieval.
    docs    : list[dict]  Candidates from hybrid_search().
    top_n   : int         Number of results to keep after re-ranking.

    Returns
    -------
    list[dict]   Top-n docs with 'rerank_score' key added.
    """
    if not docs:
        return docs

    try:
        from transformers import logging as _hf_logging
        _hf_logging.set_verbosity_error()
        _hf_logging.disable_progress_bar()
        from sentence_transformers import CrossEncoder
        _ce_local = Path(__file__).parent / "models" / "cross-encoder-reranker"
        _ce_path  = str(_ce_local) if _ce_local.exists() else "cross-encoder/ms-marco-MiniLM-L-6-v2"
        ce = CrossEncoder(_ce_path)

        pairs = [(query, f"{doc['title']} {doc['content'][:500]}") for doc in docs]
        scores = ce.predict(pairs, show_progress_bar=False)

        scored = sorted(
            zip(scores, docs), key=lambda x: x[0], reverse=True
        )[:top_n]

        result = []
        for score, doc in scored:
            doc = dict(doc)
            doc["rerank_score"] = round(float(score), 4)
            result.append(doc)
        return result

    except Exception:
        # Fallback: return top_n from existing rag_score order
        for doc in docs:
            doc.setdefault("rerank_score", doc.get("rag_score", 0.0))
        return docs[:top_n]


# ─────────────────────────────────────────────────────────────────────────────
# Historical decision memory
# ─────────────────────────────────────────────────────────────────────────────

_DECISIONS_PATH = "KB/decisions.json"


def store_decision(decision: dict) -> None:
    """
    Persist an LLM evaluation result to KB/decisions.json.

    Expected keys in decision:
        ingredient_a, ingredient_b, supplier_a, supplier_b,
        grade_a, grade_b, certifications_a, certifications_b,
        verdict (APPROVE/REJECT/etc.), confidence, reasoning, evidence_trail
    """
    path = Path(_DECISIONS_PATH)
    path.parent.mkdir(exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    record = dict(decision)
    record["stored_at"] = datetime.now().isoformat()
    existing.append(record)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def retrieve_similar_cases(
    ingredient_a: str,
    ingredient_b: str,
    grade_a: str = "",
    grade_b: str = "",
    certifications_a: list[str] | None = None,
    certifications_b: list[str] | None = None,
    top_k: int = 3,
) -> list[dict]:
    """
    Retrieve the most similar past evaluation decisions.

    Uses BM25 over stored decisions — no heavy model required.
    Returns an empty list if no history exists yet.
    """
    path = Path(_DECISIONS_PATH)
    if not path.exists():
        return []

    try:
        with open(path, encoding="utf-8") as f:
            decisions = json.load(f)
    except Exception:
        return []

    if not decisions:
        return []

    # Build a query string from the current evaluation
    certs_a = " ".join(certifications_a or [])
    certs_b = " ".join(certifications_b or [])
    query_tokens = set(_tokenize(
        f"{ingredient_a} {ingredient_b} {grade_a} {grade_b} {certs_a} {certs_b}"
    ))

    # Build doc strings for each past decision
    scored: list[tuple[float, dict]] = []
    for d in decisions:
        doc_tokens = set(_tokenize(
            f"{d.get('ingredient_a','')} {d.get('ingredient_b','')} "
            f"{d.get('grade_a','')} {d.get('grade_b','')} "
            f"{' '.join(d.get('certifications_a',[]))} "
            f"{' '.join(d.get('certifications_b',[]))}"
        ))
        # Jaccard similarity
        intersection = len(query_tokens & doc_tokens)
        union = len(query_tokens | doc_tokens)
        score = intersection / union if union else 0.0
        scored.append((score, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for score, d in scored[:top_k] if score > 0]


# ─────────────────────────────────────────────────────────────────────────────
# Prompt formatting helpers
# ─────────────────────────────────────────────────────────────────────────────

def format_context_block(docs: list[dict]) -> str:
    """
    Format retrieved regulatory documents as a prompt context block.

    Returns a string ready to be injected into the LLM prompt.
    """
    if not docs:
        return ""

    lines = ["=== REGULATORY CONTEXT (retrieved from knowledge base) ==="]
    for i, doc in enumerate(docs, 1):
        lines.append(f"\n[{i}] {doc['title']}")
        lines.append(f"    Source : {doc['source']}")
        lines.append(f"    Type   : {doc['type']}")
        content = doc["content"][:800].strip()
        lines.append(f"    Content: {content}")

    lines.append("\n(Cite sources as [Source Name] in your evidence trail when relevant.)")
    return "\n".join(lines)


def format_precedent_block(cases: list[dict]) -> str:
    """
    Format historical decision cases as a precedent block for the prompt.
    """
    if not cases:
        return ""

    lines = ["=== PRECEDENT CASES (similar past evaluations) ==="]
    for i, c in enumerate(cases, 1):
        lines.append(f"\n[Case {i}]")
        lines.append(f"  Pair     : {c.get('ingredient_a','?')} → {c.get('ingredient_b','?')}")
        lines.append(f"  Grades   : {c.get('grade_a','?')} → {c.get('grade_b','?')}")
        lines.append(f"  Verdict  : {c.get('verdict','?')} (confidence: {c.get('confidence','?')})")
        lines.append(f"  Reasoning: {c.get('reasoning','')[:300]}")

    lines.append("\n(Use precedent cases as reference, but evaluate the current case on its own merits.)")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# RAGAS-lite evaluation utilities
# ─────────────────────────────────────────────────────────────────────────────

def score_faithfulness(evidence_trail: list[str], retrieved_docs: list[dict]) -> float:
    """
    Faithfulness: fraction of evidence trail items that can be grounded in
    at least one retrieved document (token overlap > threshold).

    Returns a score in [0, 1].
    """
    if not evidence_trail or not retrieved_docs:
        return 0.0

    all_doc_tokens: set[str] = set()
    for doc in retrieved_docs:
        all_doc_tokens.update(_tokenize(doc["content"]))
        all_doc_tokens.update(_tokenize(doc["title"]))

    grounded = 0
    for item in evidence_trail:
        item_tokens = set(_tokenize(item))
        if not item_tokens:
            continue
        overlap = len(item_tokens & all_doc_tokens) / len(item_tokens)
        if overlap >= 0.20:   # ≥20% token overlap = grounded
            grounded += 1

    return round(grounded / len(evidence_trail), 3)


def score_answer_relevance(recommendation: str, retrieved_docs: list[dict]) -> float:
    """
    Answer relevance: heuristic check that the verdict is consistent with
    the retrieved regulatory context.

    Checks for keywords in retrieved docs that support the verdict.
    Returns a score in [0, 1].
    """
    if not retrieved_docs:
        return 0.5   # neutral when no context

    doc_text = " ".join(d["content"] for d in retrieved_docs).lower()

    approve_signals = ["meet", "exceed", "comply", "certified", "equivalent", "approved"]
    reject_signals  = ["missing", "lack", "fail", "gap", "not certified", "prohibited", "absent"]

    approve_count = sum(1 for w in approve_signals if w in doc_text)
    reject_count  = sum(1 for w in reject_signals  if w in doc_text)
    total = approve_count + reject_count or 1

    if recommendation in ("APPROVE",):
        return round(approve_count / total, 3)
    elif recommendation in ("REJECT",):
        return round(reject_count / total, 3)
    else:
        return round(0.5, 3)   # neutral for HUMAN_REVIEW / APPROVE_WITH_CONDITIONS


def score_context_recall(retrieved_docs: list[dict], query: str) -> float:
    """
    Context recall: fraction of retrieved docs whose type/title is
    relevant to the query (keyword overlap heuristic).

    Returns a score in [0, 1].
    """
    if not retrieved_docs:
        return 0.0

    query_tokens = set(_tokenize(query))
    relevant = 0
    for doc in retrieved_docs:
        doc_tokens = set(_tokenize(f"{doc['title']} {doc['type']}"))
        overlap = len(query_tokens & doc_tokens) / (len(query_tokens) or 1)
        if overlap >= 0.10:
            relevant += 1

    return round(relevant / len(retrieved_docs), 3)


def evaluate_rag_quality(
    eval_result: dict,
    retrieved_docs: list[dict],
    query: str,
) -> dict:
    """
    Compute RAGAS-lite quality scores for one LLM evaluation.

    Parameters
    ----------
    eval_result     : dict   LLM output (with evidence_trail, recommendation).
    retrieved_docs  : list   Documents fed to the LLM.
    query           : str    The retrieval query used.

    Returns
    -------
    dict with keys: faithfulness, answer_relevance, context_recall, overall
    """
    evidence = eval_result.get("evidence_trail", [])
    recommendation = eval_result.get("recommendation", "")

    faith  = score_faithfulness(evidence, retrieved_docs)
    relev  = score_answer_relevance(recommendation, retrieved_docs)
    recall = score_context_recall(retrieved_docs, query)
    overall = round((faith + relev + recall) / 3, 3)

    return {
        "faithfulness":      faith,
        "answer_relevance":  relev,
        "context_recall":    recall,
        "overall":           overall,
        "query":             query,
        "docs_retrieved":    len(retrieved_docs),
        "evidence_items":    len(evidence),
    }


# ─────────────────────────────────────────────────────────────────────────────
# RAG-augmented LLM evaluation
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_substitutability_rag(
    client,
    types,
    ingredient_a: str,
    supplier_a: str,
    compliance_a: dict,
    ingredient_b: str,
    supplier_b: str,
    compliance_b: dict,
    context_companies: list,
    context_bom_appearances: int,
    agnes_system_prompt: str,
    rag_idx: Optional[RagIndex] = None,
    model_name: str = "gemini-flash-latest",
    temperature: float = 0.2,
) -> tuple[dict, list, str]:
    """
    RAG-augmented substitutability evaluation.

    Retrieves relevant regulatory context from the knowledge base,
    injects it into the Gemini prompt, and returns (result, retrieved_docs, query).

    Parameters
    ----------
    client : google.genai.Client
        Initialized Gemini client.
    types : google.genai.types
        Types module for GenerateContentConfig.
    ingredient_a, supplier_a, compliance_a : Current ingredient details.
    ingredient_b, supplier_b, compliance_b : Proposed ingredient details.
    context_companies : list
        CPG companies affected by the consolidation.
    context_bom_appearances : int
        Total BOM appearances at risk.
    agnes_system_prompt : str
        Base system prompt (AGNES_SYSTEM_PROMPT from notebook).
    rag_idx : RagIndex, optional
        Pre-built RAG index. If None, evaluation proceeds without RAG context.
    model_name : str
        Gemini model to use.
    temperature : float
        Sampling temperature for generation.

    Returns
    -------
    (eval_result: dict, retrieved_docs: list, query: str)
        eval_result contains the LLM JSON response with _meta and sources_cited.
        retrieved_docs are the documents fed into the prompt.
        query is the retrieval query used.
    """
    # ── Step 1: Build retrieval query ────────────────────────────────────────
    certs_a = ", ".join(compliance_a.get("certifications", []))
    certs_b = ", ".join(compliance_b.get("certifications", []))
    grade_a = compliance_a.get("grade", "")
    grade_b = compliance_b.get("grade", "")

    query = (
        f"{ingredient_a} {ingredient_b} {grade_a} {grade_b} "
        f"compliance certification {certs_a} {certs_b} "
        f"substitution dietary supplement"
    )

    # ── Step 2: Hybrid search + re-rank ──────────────────────────────────────
    retrieved_docs: list[dict] = []
    context_block = ""
    precedent_block = ""

    if rag_idx is not None:
        raw_docs = hybrid_search(rag_idx, query, top_k=5)
        retrieved_docs = rerank(query, raw_docs, top_n=3)
        context_block = format_context_block(retrieved_docs)

        # Historical precedent cases
        similar = retrieve_similar_cases(
            ingredient_a=ingredient_a,
            ingredient_b=ingredient_b,
            grade_a=grade_a,
            grade_b=grade_b,
            certifications_a=compliance_a.get("certifications", []),
            certifications_b=compliance_b.get("certifications", []),
            top_k=2,
        )
        precedent_block = format_precedent_block(similar)

    # ── Step 3: Build RAG-augmented system prompt ────────────────────────────
    rag_system_prompt = agnes_system_prompt
    if context_block:
        rag_system_prompt = context_block + "\n\n" + rag_system_prompt
    if precedent_block:
        rag_system_prompt = rag_system_prompt + "\n\n" + precedent_block

    rag_grounding_rules = """
GROUNDING RULES (RAG context provided above):
- The REGULATORY CONTEXT section contains real documents retrieved from the Agnes knowledge base.
- PREFER grounding your evidence_trail items in these documents.
- Cite sources in square brackets, e.g.: "[USP Verification Program] USP-verified products must contain..."
- If a retrieved document is not relevant to a specific point, you may use your own knowledge but do NOT fabricate citations.
- The PRECEDENT CASES section (if present) shows similar past evaluations. Use them as reference but evaluate the current case independently.
"""
    if context_block:
        rag_system_prompt = rag_system_prompt + rag_grounding_rules

    # ── Step 4: Build user message ────────────────────────────────────────────
    cert_a = ", ".join(compliance_a.get("certifications", [])) or "None"
    cert_b = ", ".join(compliance_b.get("certifications", [])) or "None"
    company_list = ", ".join(context_companies[:8])
    if len(context_companies) > 8:
        company_list += f" ... (+{len(context_companies)-8} more)"

    user_message = f"""## Substitutability Evaluation Request

### Ingredient A — Current (consolidate FROM)
- Ingredient name   : {ingredient_a}
- Supplier          : {supplier_a}
- FDA registered    : {compliance_a.get('fda_registered')}
- Grade             : {compliance_a.get('grade')}
- Non-GMO           : {compliance_a.get('non_gmo')}
- Organic           : {compliance_a.get('organic_certified')}
- Certifications    : {cert_a}
- Lead time         : {compliance_a.get('lead_time_days')} days
- Supplier notes    : {compliance_a.get('notes','')}

### Ingredient B — Proposed (consolidate TO)
- Ingredient name   : {ingredient_b}
- Supplier          : {supplier_b}
- FDA registered    : {compliance_b.get('fda_registered')}
- Grade             : {compliance_b.get('grade')}
- Non-GMO           : {compliance_b.get('non_gmo')}
- Organic           : {compliance_b.get('organic_certified')}
- Certifications    : {cert_b}
- Lead time         : {compliance_b.get('lead_time_days')} days
- Supplier notes    : {compliance_b.get('notes','')}

### Business Context
- CPG companies affected : {company_list}
- Total BOM appearances  : {context_bom_appearances}
- Consolidation goal     : Replace all company-specific SKUs with one consolidated purchase order

### Question
Can Ingredient B (from {supplier_b}) substitute for Ingredient A (from {supplier_a})
across all affected CPG companies' BOMs while maintaining full quality and compliance?

{"[NOTE: Regulatory context has been provided above. Please cite relevant sources in your evidence trail.]" if context_block else ""}
Provide your structured JSON evaluation.
"""

    # ── Step 5: Call Gemini ───────────────────────────────────────────────────
    response = client.models.generate_content(
        model=model_name,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=rag_system_prompt,
            response_mime_type="application/json",
            temperature=temperature,
        ),
    )

    raw_text = response.text.strip()
    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        result = {
            "substitutable": False,
            "confidence": 0.0,
            "evidence_trail": [f"JSON parse error: {exc}", f"Raw: {raw_text[:300]}"],
            "compliance_met": False,
            "compliance_gaps": ["LLM response could not be parsed — requires manual review"],
            "reasoning": "Parse failure.",
            "recommendation": "HUMAN_REVIEW_REQUIRED",
        }

    # ── Step 6: Attach metadata ───────────────────────────────────────────────
    usage = response.usage_metadata
    result["_meta"] = {
        "model": model_name,
        "input_tokens": usage.prompt_token_count,
        "output_tokens": usage.candidates_token_count,
        "ingredient_a": ingredient_a,
        "supplier_a": supplier_a,
        "ingredient_b": ingredient_b,
        "supplier_b": supplier_b,
        "rag_enabled": rag_idx is not None,
        "docs_retrieved": len(retrieved_docs),
        "sources": [d.get("source", "") for d in retrieved_docs],
    }

    result["sources_cited"] = [
        {"id": d["id"], "source": d["source"], "title": d["title"],
         "score": d.get("rerank_score", d.get("rag_score", 0))}
        for d in retrieved_docs
    ]

    # ── Step 7: Store decision in historical memory ───────────────────────────
    store_decision({
        "ingredient_a": ingredient_a,
        "ingredient_b": ingredient_b,
        "supplier_a": supplier_a,
        "supplier_b": supplier_b,
        "grade_a": compliance_a.get("grade", ""),
        "grade_b": compliance_b.get("grade", ""),
        "certifications_a": compliance_a.get("certifications", []),
        "certifications_b": compliance_b.get("certifications", []),
        "verdict": result.get("recommendation", ""),
        "confidence": result.get("confidence", 0.0),
        "reasoning": result.get("reasoning", "")[:400],
        "evidence_trail": result.get("evidence_trail", []),
        "sources_cited": result.get("sources_cited", []),
    })

    return result, retrieved_docs, query
