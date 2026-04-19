# Agnes AI Decision-Making Brain: Comprehensive Technical Presentation

**Executive Summary**: This document provides a complete technical breakdown of Agnes's AI decision-making architecture, covering RAG knowledge bases, LLM reasoning engines, compliance guardrails, evidence trails, self-maintenance capabilities, and real decision examples.

---

## Table of Contents

1. [Executive Overview](#executive-overview)
2. [The Decision-Making Pipeline](#the-decision-making-pipeline)
3. [RAG Knowledge Base](#rag-knowledge-base)
4. [LLM Reasoning Engine](#llm-reasoning-engine)
5. [Compliance Guardrails](#compliance-guardrails)
6. [Evidence Trail Generation](#evidence-trail-generation)
7. [Self-Maintenance Capabilities](#self-maintenance-capabilities)
8. [Historical Decision Memory](#historical-decision-memory)
9. [RAGAS-lite Self-Evaluation](#ragas-lite-self-evaluation)
10. [Real Decision Examples](#real-decision-examples)
11. [Technical Implementation Details](#technical-implementation-details)
12. [Comparison Tables](#comparison-tables)
13. [Production Readiness & Scalability](#production-readiness--scalability)
14. [Summary & Key Takeaways](#summary--key-takeaways)

---

## Executive Overview

### The Problem

In the CPG industry, massive brands often purchase the exact same raw ingredient across multiple product lines from different suppliers without centralized visibility. This creates:

- **Fragmented purchasing**: 143 ingredients purchased independently by 60 companies
- **Lost leverage**: No volume discounts despite combined demand
- **Compliance complexity**: Different certifications (USP, GMP, Halal, Kosher, Non-GMO)
- **Risk exposure**: 18 CRITICAL ingredients with only 1 supplier

### Why AI Reasoning is Needed

Traditional procurement systems cannot handle:
1. **Chemical substitutability**: Is "vitamin-d3" the same as "vitamin-d3-cholecalciferol"?
2. **Grade hierarchies**: Can pharma-grade replace food-grade?
3. **Certification compatibility**: Does missing USP certification break consolidation?
4. **Regulatory grounding**: Decisions must cite real FDA/USP/NSF standards

### Agnes's AI Brain Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     AGNES AI BRAIN                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │ RAG Knowledge│───▶│  LLM Reasoning│───▶│ Compliance   │    │
│  │    Base      │    │   Engine      │    │  Guardrails  │    │
│  └──────────────┘    └──────────────┘    └──────────────┘    │
│         │                   │                   │             │
│         ▼                   ▼                   ▼             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    │
│  │ Evidence     │    │ Self-Maint.  │    │ Historical   │    │
│  │   Trails     │    │  Capabilities│    │   Memory     │    │
│  └──────────────┘    └──────────────┘    └──────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key Innovations

1. **RAG Grounding**: Every decision cites real regulatory documents (FDA 21 CFR 111, USP, NSF)
2. **Compliance Guardrails**: Hard-encoded rules prevent dangerous downgrades
3. **Evidence Trails**: Every fact is numbered and source-cited
4. **Self-Maintenance**: Self-healing, self-monitoring, self-explanation
5. **Historical Memory**: Past decisions inform future evaluations

---

## The Decision-Making Pipeline

### Complete Data Flow

```
DATABASE (SQLite)
    │
    ▼
┌──────────────────┐
│ Cell 2: DB Ingest│ → Parse SKUs → Identify fragmented ingredients
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Cell 3: Target   │ → Select ingredient → Trace finished products
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Cell 4: Enrich   │ → Scrape supplier compliance data
└──────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ Cell 4.5: RAG Index Build (FAISS HNSW + BM25)                   │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────────┐
│ Cell 5: LLM Reasoning (Gemini Flash + RAG + Guardrails)          │
└──────────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────┐
│ Cell 5.5: Monitor │ → Confidence tracking, health scoring
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Cell 6: Optimize  │ → Supplier ranking with compliance weight
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Cell 7: Report    │ → Technical evidence trail output
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Cell 7.5: Explain│ → Business-friendly executive summary
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ Cell 12-RAG: Eval │ → RAGAS-lite quality metrics
└──────────────────┘
```

---

## RAG Knowledge Base

### Knowledge Base Composition

Agnes's RAG system ingests **20 real regulatory documents**:

| Category | Documents | Purpose |
|----------|-----------|---------|
| FDA Regulations | 7 docs | 21 CFR 111, DSHEA, labeling, facility registration |
| USP Standards | 3 docs | Verification Program, grade definitions, Vitamin D3 monograph |
| NSF Standards | 2 docs | Certification overview, NSF/ANSI 173 |
| Halal Standards | 2 docs | IFANCA, HFSAA standards |
| Kosher Standards | 1 doc | OK Kosher requirements |
| Non-GMO Standards | 1 doc | Non-GMO Project verification |
| GMP Standards | 1 doc | ISO 22716 cGMP principles |
| Organic Standards | 1 doc | USDA National Organic Program |
| Ingredient Guidance | 2 docs | Vitamin D3 FDA notice, third-party testing |

### FAISS HNSW Vector Index

**Configuration**:
- Model: `all-MiniLM-L6-v2` (384-dim)
- Index: `faiss.IndexHNSWFlat` with `M=32`
- efSearch: 64
- Normalization: L2-normalized (inner product = cosine similarity)

### BM25 Keyword Index

**Configuration**:
- Library: `rank_bm25.BM25Okapi`
- Tokenizer: Regex `[a-z0-9]+` (lowercase)
- Use: Exact term matching for certifications, regulatory codes

### Hybrid Search Formula

```
combined_score(doc) = 0.65 × vector_score(doc) + 0.35 × bm25_score(doc)
```

### Retrieval Pipeline

```
Query: "vitamin-d3 pharmaceutical USP GMP Halal Kosher compliance"
    ↓
hybrid_search(index, query, top_k=5)
    ↓
[vector search FAISS] + [keyword search BM25]
    ↓
Top-5 candidates with rag_score
    ↓
rerank(query, candidates, top_n=3)
    ↓
[cross-encoder: ms-marco-MiniLM-L-6-v2]
    ↓
Top-3 documents with rerank_score
    ↓
format_context_block(docs)
    ↓
Inject into Gemini prompt
```

### Code Implementation

```python
def hybrid_search(index: RagIndex, query: str, top_k: int = 5, alpha: float = 0.65):
    """Hybrid retrieval: alpha * vector_score + (1-alpha) * BM25_score."""
    
    # Vector search
    query_emb = index.embedding_model.encode([query], normalize_embeddings=True)
    distances, v_indices = index.faiss_index.search(query_emb, top_k * 3)
    vector_scores = {int(idx): float(score) for idx, score in zip(v_indices[0], distances[0])}
    
    # BM25 search
    tokenized_query = _tokenize(query)
    bm25_raw = index.bm25.get_scores(tokenized_query)
    bm25_scores = {i: float(bm25_raw[i]) / bm25_raw.max() for i in range(len(bm25_raw))}
    
    # Normalize and combine
    v_max = max(vector_scores.values(), default=1.0)
    v_min = min(vector_scores.values(), default=0.0)
    v_range = (v_max - v_min) or 1.0
    
    combined = {}
    for idx in range(len(index.docs)):
        v_score = (vector_scores.get(idx, 0.0) - v_min) / v_range
        b_score = bm25_scores.get(idx, 0.0)
        combined[idx] = alpha * v_score + (1.0 - alpha) * b_score
    
    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [dict(index.docs[idx], rag_score=round(score, 4)) for idx, score in ranked]
```

---

## LLM Reasoning Engine

### Model Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Model | `gemini-flash-latest` | Fast, cost-effective, high quality |
| SDK | `google-genai` | New official SDK |
| Response Format | Native JSON | No markdown parsing |
| Temperature | 0.2 (default) | Low for consistency |
| System Prompt | AGNES_SYSTEM_PROMPT + RAG context | Compliance-first |

### System Prompt Layers

```
Layer 1: RAG Context Block (retrieved regulatory documents)
    ↓
Layer 2: Precedent Cases Block (similar past decisions)
    ↓
Layer 3: AGNES_SYSTEM_PROMPT (base compliance rules)
    ↓
Layer 4: RAG Grounding Rules (citation requirements)
```

### The 5 Critical Rules

1. **Quality Upgrade Only**: Substitution valid only if replacement MEETS OR EXCEEDS original
2. **No Grade Downgrades**: Pharma → food grade NEVER acceptable without explicit evidence
3. **Certification Gap Detection**: Missing certification must be flagged
4. **Evidence Trail Mandatory**: Must produce specific, discrete facts
5. **No Hallucinations**: Never fabricate certifications; state uncertainty explicitly

### Confidence Thresholds

| Confidence Range | Meaning | Action |
|------------------|---------|--------|
| 0.9 - 1.0 | High certainty | Accept |
| 0.7 - 0.9 | Reasonable inference | Accept |
| < 0.7 | Uncertain | HUMAN_REVIEW_REQUIRED |

### JSON Output Schema

```json
{
  "substitutable": boolean,
  "confidence": float (0.0-1.0),
  "evidence_trail": ["fact 1", "fact 2", ...],
  "compliance_met": boolean,
  "compliance_gaps": ["gap 1", "gap 2"],
  "reasoning": "2-4 sentence narrative",
  "recommendation": "APPROVE | APPROVE_WITH_CONDITIONS | REJECT | HUMAN_REVIEW_REQUIRED",
  "sources_cited": [{"source": "...", "title": "...", "score": 0.89}]
}
```

### Self-Healing Retry Logic

```python
temperatures = [0.2, 0.1, 0.3]  # Vary per attempt

for attempt in range(3):
    try:
        result = evaluate_substitutability(..., temperature=temperatures[attempt])
        result["_meta"]["retry_attempt"] = attempt + 1
        return result
    except Exception as e:
        if attempt < 2:
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
        else:
            return create_fallback_response(e)
```

---

## Compliance Guardrails

### Comparison: With vs Without Guardrails

| Scenario | Without Guardrails | With Guardrails |
|----------|-------------------|----------------|
| Pharma → Food grade | Might approve if cheaper | REJECT (unless explicit evidence) |
| Missing USP cert | Might ignore | Flag as compliance gap |
| No evidence trail | Might approve without explanation | REJECT (evidence required) |
| Uncertain chemistry | Might guess | HUMAN_REVIEW_REQUIRED |

### Real Example: Vitamin D3 Case

**Without Guardrails**:
```
Recommendation: APPROVE
Reasoning: Both are pharmaceutical grade, similar quality profile.
```

**With Guardrails**:
```
Recommendation: REJECT
Confidence: 95%
Compliance gaps:
  - Missing USP certification
  - Missing Halal certification

Evidence trail:
  • Ingredient A carries USP certification, critical for US market
  • Ingredient A is Halal certified, whereas Ingredient B is not
  • Ingredient B lacks third-party USP verification
  • Consolidation across 33 BOMs requires highest common denominator

Reasoning: While Ingredient B is pharmaceutical grade, it fails to meet
the compliance profile due to absence of USP and Halal certifications.
```

---

## Evidence Trail Generation

### Evidence Trail Structure

```json
{
  "evidence_trail": [
    "Specific fact 1 with source citation",
    "Specific fact 2 with source citation"
  ],
  "sources_cited": [
    {"source": "U.S. Pharmacopeia (USP)", "title": "USP Grade Definitions", "score": 0.89}
  ]
}
```

### Source Citation Format

**With RAG**: `[USP Verification Program] USP-verified products must contain...`
**Without RAG**: `USP certification is a critical quality standard...`

### Faithfulness Scoring

```python
def score_faithfulness(evidence_trail, retrieved_docs):
    """Fraction of evidence items grounded in retrieved docs (≥20% token overlap)."""
    all_doc_tokens = set()
    for doc in retrieved_docs:
        all_doc_tokens.update(_tokenize(doc["content"]))
    
    grounded = 0
    for item in evidence_trail:
        item_tokens = set(_tokenize(item))
        overlap = len(item_tokens & all_doc_tokens) / len(item_tokens)
        if overlap >= 0.20:
            grounded += 1
    
    return grounded / len(evidence_trail)
```

---

## Self-Maintenance Capabilities

### 1. Self-Healing

Exponential backoff with temperature tuning:
- Attempt 1: Temperature 0.2, wait 1s on failure
- Attempt 2: Temperature 0.1, wait 2s on failure
- Attempt 3: Temperature 0.3, fallback if fails

### 2. Self-Monitoring

The AgnesMonitor class tracks:
- Confidence scores per evaluation
- Recommendation distribution
- Token usage
- Retry statistics
- Health status (HEALTHY/CAUTION/WARNING)

**Health Status Levels**:
| Status | Condition | Action |
|--------|-----------|--------|
| HEALTHY | No low-confidence, mean ≥ 80% | None |
| CAUTION | Mean < 80% | Review recommended |
| WARNING | Any < 0.7 threshold | Manual review required |

### 3. Self-Explanation

Dual evidence trails:
- **Technical** (Cell 7): Regulatory details, compliance gaps
- **Business** (Cell 7.5): Strategic overview, financial impact, action items

```json
{
  "executive_summary": "Consolidation presents significant opportunity...",
  "action_items": ["Initiate supplier negotiation", "Validate certifications"],
  "financial_impact": "Estimated 12-18% cost reduction...",
  "risk_considerations": "Compliance gaps limit supplier flexibility",
  "next_steps": "Schedule procurement alignment meeting"
}
```

---

## Historical Decision Memory

### Storage Schema

**File**: `KB/decisions.json`

```json
{
  "ingredient_a": "vitamin-d3",
  "ingredient_b": "vitamin-d3-cholecalciferol",
  "supplier_a": "Prinova USA",
  "supplier_b": "Prinova USA",
  "grade_a": "food",
  "grade_b": "pharmaceutical",
  "certifications_a": ["GMP", "Kosher"],
  "certifications_b": ["USP", "GMP", "Halal", "Kosher"],
  "verdict": "APPROVE",
  "confidence": 0.98,
  "reasoning": "Pharma-grade upgrade from food-grade...",
  "stored_at": "2026-04-18T11:15:30"
}
```

### Precedent Retrieval

Uses Jaccard token similarity:
```
similarity(A, B) = |A ∩ B| / |A ∪ B|
```

### Precedent Block Format

```
=== PRECEDENT CASES (similar past evaluations) ===

[Case 1]
  Pair     : vitamin-d3 → vitamin-d3-cholecalciferol
  Grades   : food → pharmaceutical
  Verdict  : APPROVE (confidence: 0.98)
  Reasoning: Pharma-grade upgrade from food-grade...

(Use precedent cases as reference, but evaluate current case independently.)
```

---

## RAGAS-lite Self-Evaluation

### Three Metrics

| Metric | Formula | Target |
|--------|---------|--------|
| Faithfulness | Grounded items / total items | > 0.80 |
| Answer Relevance | Signal keywords / total signals | > 0.70 |
| Context Recall | Relevant docs / total retrieved | > 0.60 |
| Overall | Mean of three metrics | > 0.70 |

### Implementation

```python
def evaluate_rag_quality(eval_result, retrieved_docs, query):
    evidence = eval_result.get("evidence_trail", [])
    recommendation = eval_result.get("recommendation", "")
    
    faith = score_faithfulness(evidence, retrieved_docs)
    relev = score_answer_relevance(recommendation, retrieved_docs)
    recall = score_context_recall(retrieved_docs, query)
    overall = round((faith + relev + recall) / 3, 3)
    
    return {
        "faithfulness": faith,
        "answer_relevance": relev,
        "context_recall": recall,
        "overall": overall
    }
```

---

## Real Decision Examples

### Example 1: Vitamin D3 Supplier Consolidation (REJECT)

**Input**:
- Ingredient A: Prinova USA (USP, GMP, Halal, Kosher, Pharma)
- Ingredient B: PureBulk (GMP, Kosher, Pharma, missing USP/Halal)

**LLM Decision**:
```json
{
  "substitutable": false,
  "confidence": 0.95,
  "evidence_trail": [
    "Ingredient A carries USP certification, critical for US market [USP]",
    "Ingredient A is Halal certified, whereas Ingredient B is not [IFANCA]",
    "Ingredient B lacks third-party USP verification [USP]",
    "Consolidation requires highest common denominator of certifications [FDA]"
  ],
  "compliance_met": false,
  "compliance_gaps": ["Missing USP certification", "Missing Halal certification"],
  "reasoning": "While Ingredient B is pharmaceutical grade, it fails to meet the compliance profile due to absence of USP and Halal certifications.",
  "recommendation": "REJECT"
}
```

**RAGAS Scores**: Faithfulness 1.0, Answer Relevance 0.75, Context Recall 0.67, Overall 0.81

### Example 2: Cross-Cluster Grade Upgrade (APPROVE)

**Input**:
- Ingredient A: Food-grade vitamin-d3 (GMP, Kosher)
- Ingredient B: Pharma-grade cholecalciferol (USP, GMP, Halal, Kosher)

**LLM Decision**:
```json
{
  "substitutable": true,
  "confidence": 0.98,
  "evidence_trail": [
    "Ingredient B is a direct quality upgrade from food to pharmaceutical grade [USP]",
    "Pharmaceutical-grade meets or exceeds all food-grade requirements [USP Monograph]",
    "Upgrade adds USP and Halal certifications for market access [USP]",
    "Same supplier eliminates qualification complexity [Internal]"
  ],
  "compliance_met": true,
  "reasoning": "Ingredient B is a direct quality upgrade, meeting or exceeding all requirements while adding beneficial certifications.",
  "recommendation": "APPROVE"
}
```

---

## Technical Implementation Details

### Code Architecture

```
rag_engine.py (production module)
├── build_index()           → RagIndex
├── hybrid_search()         → list[dict]
├── rerank()                → list[dict]
├── store_decision()        → None
├── retrieve_similar_cases()→ list[dict]
├── format_context_block()  → str
├── format_precedent_block()→ str
└── evaluate_rag_quality()  → dict
```

### Key Data Structures

**RagIndex**:
```python
@dataclass
class RagIndex:
    docs: list[dict]
    faiss_index: object
    bm25: object
    embedding_model: object
    tokenized_docs: list[list]
```

---

## Comparison Tables

### With vs Without RAG

| Aspect | Without RAG | With RAG |
|--------|-------------|---------|
| Knowledge source | LLM training data only | Real regulatory documents |
| Source citations | None | [FDA], [USP], [NSF] brackets |
| Hallucination risk | Higher | Lower (grounded in context) |
| Auditability | Limited | Full source traceability |

### With vs Without Guardrails

| Aspect | Without Guardrails | With Guardrails |
|--------|-------------------|-----------------|
| Grade downgrades | Possible | Blocked (unless explicit evidence) |
| Certification gaps | Might ignore | Always flagged |
| Evidence trails | Optional | Mandatory |
| Hallination control | Basic | Strict (confidence thresholds) |

### With vs Without Self-Maintenance

| Aspect | Without Self-Maintenance | With Self-Maintenance |
|--------|--------------------------|----------------------|
| API failures | Pipeline breaks | Self-healing with retries |
| Quality tracking | None | Confidence monitoring |
| Business explanations | Technical only | Dual trails (tech + business) |

---

## Production Readiness & Scalability

### Infrastructure Requirements

| Component | Hackathon | Production |
|-----------|-----------|------------|
| Vector DB | FAISS local | Qdrant Cloud / Weaviate |
| Embeddings | all-MiniLM-L6-v2 (384-dim) | OpenAI text-embedding-3-small |
| BM25 | rank_bm25 local | Elasticsearch BM25 |
| Decision storage | JSON file | PostgreSQL pgvector |
| Reranker | ms-marco local | Cohere Rerank API |
| Scraper | Mock | Playwright + LLM PDF extraction |

### Performance Characteristics

| Metric | Hackathon | Production |
|--------|-----------|------------|
| Single evaluation | ~5 seconds | ~2 seconds (parallel) |
| Portfolio (143 ingredients) | ~12 minutes (sequential) | ~30 seconds (parallel) |
| RAG retrieval | < 100ms | < 50ms (cached) |
| Max scale | 1,000 ingredients | 100,000+ ingredients |

### Security Considerations

- **Secrets Management**: HashiCorp Vault or AWS Secrets Manager
- **Authentication**: OAuth 2.0 or API keys
- **Audit Logging**: All decisions with evidence trails
- **Data Encryption**: At rest and in transit

---

## Summary & Key Takeaways

### The Complete AI Decision-Making Brain

Agnes implements a sophisticated AI reasoning system with:

1. **RAG Knowledge Base**: 20 real regulatory documents, FAISS HNSW + BM25 hybrid search
2. **LLM Reasoning Engine**: Gemini Flash with compliance guardrails and evidence requirements
3. **Compliance Guardrails**: 5 critical rules preventing dangerous decisions
4. **Evidence Trails**: Source-cited, numbered facts for auditability
5. **Self-Maintenance**: Self-healing, self-monitoring, self-explanation
6. **Historical Memory**: Precedent-based consistency across evaluations
7. **Quality Evaluation**: RAGAS-lite metrics measuring reasoning quality

### Key Innovations

- **Grounded Decisions**: Every LLM evaluation cites real regulatory sources
- **Compliance-First**: Guardrails prevent grade downgrades and certification gaps
- **Explainable AI**: Dual evidence trails (technical + business)
- **Self-Aware**: System monitors its own confidence and health
- **Scalable**: Clean module architecture with documented production upgrade path

### Business Impact

- **Risk Reduction**: Prevents non-compliant consolidations
- **Cost Savings**: Identifies consolidation opportunities ($5M+ estimated)
- **Audit Readiness**: Full evidence trails for regulatory reviews
- **Stakeholder Trust**: Explainable, source-cited decisions

### Next Steps for Production

1. **Infrastructure**: Deploy to cloud with proper secret management
2. **Data Integration**: Real-time supplier data via web scraping
3. **Monitoring**: Prometheus/Grafana for API performance
4. **Testing**: Expand test coverage to 90%+
5. **Documentation**: API docs and operator guides

---

**End of Presentation**
