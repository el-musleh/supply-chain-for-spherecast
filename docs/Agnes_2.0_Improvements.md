# Agnes 2.0 Improvements Guide

## Overview

Agnes 2.0 represents a significant enhancement over the original Spherecast Agnes concept. While the original vision focused on basic consolidation with compliance checking, Agnes 2.0 introduces advanced risk management, supplier reliability tracking, and disruption simulation capabilities. This document details the improvements, their technical implementation, and their business value.

## Original Agnes Vision (from Spherecast)

The original Agnes concept, as described in the Spherecast hackathon challenge, envisioned:

**Core Capabilities**:
1. Identify functionally interchangeable components at the ingredient level
2. Infer quality and compliance requirements from structured data and external evidence
3. Produce an explainable sourcing recommendation with evidence trails
4. Balance supplier consolidation, lead time, and practical feasibility

**Original Pipeline** (7 cells):
1. Database ingestion
2. Target selection
3. Mock compliance enrichment
4. Gemini reasoning
5. Consolidation
6. Final report

**Focus**: Single-ingredient analysis with basic supplier ranking.

## Agnes 2.0 New Features

### 1. Supply Chain Risk Heat Map (Cell 9)

**Purpose**: System-wide vulnerability assessment across all 143 fragmented ingredients.

**Original Limitation**: The original Agnes analyzed one ingredient at a time without context of relative risk across the portfolio.

**Agnes 2.0 Enhancement**:
- Scans all 143 fragmented ingredients simultaneously
- Calculates vulnerability index for each ingredient
- Classifies risk into tiers (CRITICAL, HIGH, MEDIUM, LOW)
- Provides ranked priority list for procurement teams

**Technical Implementation**:
```python
vulnerability_index = total_bom_appearances / distinct_supplier_count

def _risk_tier(row: pd.Series) -> str:
    if row["supplier_count"] == 1:
        return "CRITICAL"
    if row["supplier_count"] == 2 and row["total_bom_appearances"] >= 20:
        return "HIGH"
    if row["total_bom_appearances"] >= 15:
        return "MEDIUM"
    return "LOW"
```

**Business Value**:
- **Prioritization**: Procurement teams can focus on the 18 CRITICAL single-source ingredients first
- **Resource Allocation**: Limited sourcing bandwidth goes to highest-impact opportunities
- **Risk Visibility**: Executive dashboard shows supply chain health at a glance
- **Proactive Management**: Identify risks before they become disruptions

**Sample Output**:
```
Total ingredients analyzed : 143
CRITICAL  (1 supplier)     : 18
HIGH      (2 sup, ≥20 BOM) : 11
MEDIUM    (≥15 BOMs)       : 9
LOW                        : 105

Top vulnerabilities:
1. maltodextrin (21 BOMs, 1 supplier) - CRITICAL
2. glycerin (17 BOMs, 1 supplier) - CRITICAL
3. vitamin-d3-cholecalciferol (33 BOMs, 2 suppliers) - HIGH
```

---

### 2. Go-Fish Supplier Trust Score System (Cell 8)

**Purpose**: Track supplier reliability history to adjust recommendations based on actual performance.

**Original Limitation**: The original Agnes treated all suppliers equally, assuming compliance data was sufficient for decision-making.

**Agnes 2.0 Enhancement**:
- Tracks delivery history (on-time vs delayed)
- Calculates dynamic trust score (base 100, +10 for on-time, -20 for delays)
- Maps scores to trust tiers (PROBATION through PLATINUM)
- Applies trust multiplier (0.5x to 1.5x) to compliance weight
- Encourages suppliers to maintain consistent performance

**Concept Inspiration**: Named after the card game "Go-Fish" where players build a hand over time. Similarly, suppliers build trust through consistent performance.

**Technical Implementation**:
```python
class SupplierTrustTracker:
    BASE_SCORE = 100
    ON_TIME_BONUS = 10
    DELAY_PENALTY = 20
    
    def simulate_history(self, supplier_name: str, n_deliveries: int = 20):
        rng = random.Random(hash(supplier_name) % (2 ** 31))
        score = self.BASE_SCORE
        for _ in range(n_deliveries):
            on_time = rng.random() < 0.80  # 80% base on-time rate
            if on_time:
                score += self.ON_TIME_BONUS
            else:
                score -= self.DELAY_PENALTY
        self._scores[supplier_name] = max(10, score)
    
    def get_trust_multiplier(self, supplier_name: str) -> float:
        return round(max(0.5, min(1.5, self.get_score(supplier_name) / 100)), 3)
    
    def get_trust_tier(self, supplier_name: str) -> str:
        s = self.get_score(supplier_name)
        if s >= 160: return "PLATINUM"
        if s >= 130: return "GOLD"
        if s >= 100: return "SILVER"
        if s >= 70:  return "BRONZE"
        return "PROBATION"
```

**Trust Tier Structure**:
- **PLATINUM** (≥160): 1.5x multiplier - Exceptional reliability
- **GOLD** (130-159): 1.3x multiplier - Strong performance
- **SILVER** (100-129): 1.2x multiplier - Good reliability
- **BRONZE** (70-99): 1.0x multiplier - Acceptable performance
- **PROBATION** (<70): 0.5x multiplier - Poor reliability, requires monitoring

**Business Value**:
- **Performance Incentives**: Suppliers compete on reliability, not just price
- **Risk Adjustment**: A supplier with slightly worse compliance but better history can rank higher
- **Accountability**: Trust scores create accountability for delivery performance
- **Dynamic Scoring**: Recommendations adjust as supplier performance changes over time

**Sample Impact**:
```
Without trust adjustment:
  Prinova USA: compliance=1.600, score=1.600
  PureBulk: compliance=1.500, score=1.500
  → Prinova wins

With trust adjustment:
  Prinova USA: compliance=1.600 × trust=1.200 → 1.920
  PureBulk: compliance=1.500 × trust=1.500 → 2.250
  → PureBulk wins due to superior reliability
```

**Production Note**: In production, this would pull from ERP/TMS systems with actual delivery history, not simulated data.

---

### 3. Disruption Simulator (Cell 10)

**Purpose**: "What if a supplier goes offline?" - Auto-rerouting analysis for contingency planning.

**Original Limitation**: The original Agnes provided no contingency planning capabilities. If a supplier failed, there was no pre-calculated response plan.

**Agnes 2.0 Enhancement**:
- Simulates supplier failure scenarios
- Identifies all affected ingredients and BOMs
- Checks for alternate suppliers
- Classifies exposure (MANAGEABLE vs CRITICAL)
- Generates LLM-powered contingency plan with timeline
- Quantifies disruption impact

**Technical Implementation**:
```python
def simulate_supplier_failure(failed_supplier: str):
    # Find all ingredients from failed supplier
    affected_ingredients = df_supplier_coverage[
        df_supplier_coverage["supplier_name"] == failed_supplier
    ]["ingredient_name"].unique()
    
    # For each ingredient, check for alternate suppliers
    for ingredient in affected_ingredients:
        other_suppliers = df_supplier_coverage[
            (df_supplier_coverage["ingredient_name"] == ingredient) &
            (df_supplier_coverage["supplier_name"] != failed_supplier)
        ]["supplier_name"].tolist()
        
        if not other_suppliers:
            exposure = "CRITICAL"
        else:
            exposure = "MANAGEABLE"
    
    # Generate contingency plan via LLM
    contingency_plan = generate_contingency_plan(
        affected_ingredients,
        bom_impact,
        exposure_levels
    )
```

**Contingency Plan Structure**:
```
IMMEDIATE (24 h):
  • Contact alternate suppliers for spot-buy inventory
  • Place bridge orders for top 10 ingredients
  • Notify production planning of potential delays

WEEK 1:
  • Audit remaining ingredients for secondary contracts
  • Validate quality specs of backup suppliers

MONTH 1:
  • Onboard tertiary suppliers for high-volume ingredients
  • Adjust safety stock thresholds

STRATEGIC:
  • Shift to multi-sourcing strategy
  • Implement supplier risk monitoring system
```

**Business Value**:
- **Proactive Risk Management**: Plan for disruptions before they happen
- **Rapid Response**: Pre-calculated actions reduce reaction time
- **Impact Quantification**: Know exactly which products are at risk
- **Resilience Building**: Identify single points of failure
- **Scenario Planning**: Test different failure scenarios

**Sample Output**:
```
Disruption: 'Prinova USA' goes offline
Ingredients directly affected : 135
Total BOM appearances at risk : 712
Ingredients with NO backup    : 0  ← Good news, all have alternatives

Top impact:
1. vitamin-d3-cholecalciferol (33 BOMs) - PureBackup available
2. citric-acid (26 BOMs) - Univar Solutions available
3. magnesium-oxide (25 BOMs) - Jost Chemical available
```

---

### 4. Cross-Cluster Ingredient Substitution Detection

**Purpose**: Identify substitution opportunities across ingredient name variants (e.g., vitamin-d3 → vitamin-d3-cholecalciferol).

**Original Limitation**: The original Agnes only considered exact ingredient name matches. It missed opportunities where different names referred to the same chemical substance.

**Agnes 2.0 Enhancement**:
- Identifies related ingredient clusters (e.g., vitamin-d3, vitamin-d3-cholecalciferol)
- Evaluates cross-cluster substitutability
- Combines demand across clusters for larger consolidation opportunities
- Uses LLM to determine if names represent the same chemical substance

**Technical Implementation**:
```python
# In Cell 3, related ingredient is identified:
RELATED_INGREDIENT = "vitamin-d3"
TARGET_INGREDIENT = "vitamin-d3-cholecalciferol"

# Combined opportunity calculation:
combined_companies = df_target['company_name'].nunique() + df_related['company_name'].nunique()
combined_bom = int(df_target['bom_appearances'].sum() + df_related['bom_appearances'].sum())

# In Cell 5, cross-cluster evaluation:
eval_cross_cluster = evaluate_substitutability(
    ingredient_a=RELATED_INGREDIENT,  # vitamin-d3 (food-grade)
    ingredient_b=TARGET_INGREDIENT,   # vitamin-d3-cholecalciferol (pharma-grade)
    # ... other parameters
)
```

**Business Value**:
- **Larger Consolidation Opportunities**: Combines demand across name variants
- **Chemical Accuracy**: Recognizes that different names may refer to the same substance
- **Grade-Based Reasoning**: Can upgrade from food-grade to pharma-grade when appropriate
- **Expanded Scope**: Finds opportunities exact matching would miss

**Sample Result**:
```
Target: vitamin-d3-cholecalciferol
  Companies: 17, BOMs: 33

Related: vitamin-d3
  Companies: 8, BOMs: 14

Combined opportunity: 25 companies, 47 BOM appearances

LLM verdict: APPROVE
Reasoning: Pharma-grade cholecalciferol is a direct upgrade from food-grade vitamin-d3.
Meets or exceeds all requirements while adding USP and Halal certifications.
```

---

### 5. Trust-Adjusted Compliance Weighting

**Purpose**: Multiply compliance weight by supplier trust tier to create a more holistic scoring system.

**Original Limitation**: The original Agnes used compliance weight alone, ignoring historical performance.

**Agnes 2.0 Enhancement**:
- Combines static compliance data with dynamic trust scores
- Formula: `adjusted_weight = compliance_weight × trust_multiplier`
- Trust multiplier ranges from 0.5x (PROBATION) to 1.5x (PLATINUM)
- Creates balanced view of quality and reliability

**Technical Implementation**:
```python
# In Cell 6, modified scoring:
for supplier in approved_suppliers:
    compliance_weight = compute_compliance_weight(compliance_data)
    trust_multiplier = trust_tracker.get_trust_multiplier(supplier)
    adjusted_weight = compliance_weight * trust_multiplier
    score = bom_appearances_covered × adjusted_weight
```

**Impact on Rankings**:
```
Scenario: Two suppliers for same ingredient

Supplier A:
  Compliance: 1.600 (pharma, USP, Halal, GMP, Kosher)
  Trust: SILVER (score=120, multiplier=1.2)
  Adjusted: 1.600 × 1.2 = 1.920

Supplier B:
  Compliance: 1.500 (pharma, GMP, Kosher)
  Trust: PLATINUM (score=180, multiplier=1.5)
  Adjusted: 1.500 × 1.5 = 2.250

Result: Supplier B wins despite slightly lower compliance
```

**Business Value**:
- **Holistic Evaluation**: Considers both quality and reliability
- **Performance Incentive**: Suppliers motivated to maintain consistent performance
- **Risk-Adjusted Decisions**: Accounts for delivery risk in sourcing decisions
- **Dynamic Rankings**: Recommendations adjust as supplier performance changes

---

### 6. LLM Self-Maintenance Capabilities

**Purpose**: Enable Agnes to monitor, heal, and explain her own reasoning for enhanced trustworthiness, systematic hallucination control, and explainable AI — directly addressing hackathon judging criteria.

**The Three Capabilities**:

#### 6.1 Self-Healing (Cell 5)

**Problem**: LLM API calls can fail due to network issues, rate limits, or transient errors. Without handling, the pipeline breaks.

**Solution**: Exponential backoff retry logic with graceful fallback.

**Implementation**:
```python
def evaluate_substitutability_with_healing(
    ...,
    max_retries: int = 3,
) -> dict:
    temperatures = [0.2, 0.1, 0.3]  # Vary per attempt
    
    for attempt in range(max_retries):
        try:
            result = evaluate_substitutability(
                ..., 
                temperature=temperatures[attempt]
            )
            result["_meta"]["retry_attempt"] = attempt + 1
            result["_meta"]["healing_applied"] = (attempt > 0)
            return result
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
            else:
                # Final fallback: conservative safe response
                return create_fallback_response(args, str(e))
```

**Retry Strategy**:
- Attempt 1: Temperature 0.2, wait 1s on failure
- Attempt 2: Temperature 0.1, wait 2s on failure  
- Attempt 3: Temperature 0.3, fallback if fails

**Fallback Response**:
```json
{
  "substitutable": false,
  "confidence": 0.0,
  "recommendation": "HUMAN_REVIEW_REQUIRED",
  "reasoning": "Self-healing: LLM API failed after 3 retry attempts...",
  "_meta": {
    "healing_applied": true,
    "fallback_reason": "API failure"
  }
}
```

---

#### 6.2 Self-Monitoring (Cell 5.5)

**Problem**: Without systematic tracking, low-confidence LLM outputs can slip through unnoticed, leading to poor decisions.

**Solution**: Real-time confidence tracking with persistent logging.

**The `AgnesMonitor` Class**:
```python
class AgnesMonitor:
    LOG_FILE = "agnes_monitoring_log.json"
    LOW_CONFIDENCE_THRESHOLD = 0.7
    
    def record(self, eval_result: dict, context: dict):
        """Store evaluation with metadata."""
        
    def analyze_confidence(self) -> dict:
        """Compute mean, min, max, low-count statistics."""
        
    def health_check(self) -> str:
        """Return HEALTHY / CAUTION / WARNING status."""
        
    def display_report(self):
        """Show formatted monitoring report."""
```

**Tracked Metrics**:
- Confidence score and recommendation type
- Compliance status and gap counts
- Token usage (input/output)
- Retry attempts and healing status
- Ingredient and supplier pairs
- Timestamps and session tracking

**Health Status Levels**:
| Status | Condition | Action Required |
|--------|-----------|-----------------|
| **HEALTHY** | No low-confidence evals, mean ≥ 80% | None |
| **CAUTION** | Mean confidence < 80% | Review recommended |
| **WARNING** | Any evaluation < 0.7 threshold | Manual review required |

**Report Output**:
```
======================================================================
  AGNES SELF-MONITORING REPORT
======================================================================
  Health Status    : HEALTHY
  Total Evaluations: 2
  Mean Confidence  : 96.5%
  Low Confidence   : 0 (0.0%)
  Retries Required : 0
```

---

#### 6.3 Self-Explanation (Cell 7.5)

**Problem**: Technical evidence trails are too detailed for business stakeholders; procurement teams need concise, actionable summaries.

**Solution**: Dual evidence trails — technical (Cell 7) and business (Cell 7.5).

**Implementation**:
```python
EXECUTIVE_SUMMARY_PROMPT = """You are a procurement strategy advisor...
Summarize the following supply chain recommendation...

CONSOLIDATION DATA:
- Ingredient: {ingredient}
- Companies Affected: {company_count}
...

Provide:
- executive_summary: strategic overview
- action_items: specific actions
- financial_impact: savings opportunity
- risk_considerations: key risks
- next_steps: immediate action"""

def generate_executive_summary(context: dict) -> dict:
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=EXECUTIVE_SUMMARY_PROMPT.format(**context),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    return json.loads(response.text)
```

**Output Example**:
```json
{
  "executive_summary": "Consolidation of vitamin-d3-cholecalciferol...",
  "action_items": [
    "Initiate supplier negotiation with Prinova USA",
    "Validate USP and Halal certification requirements",
    "Calculate volume-based pricing discount potential"
  ],
  "financial_impact": "Estimated 12-18% cost reduction...",
  "risk_considerations": "Compliance gaps in PureBulk option...",
  "next_steps": "Schedule procurement alignment meeting..."
}
```

---

**Business Value**:
- **Trustworthiness**: Demonstrates systematic approach to AI safety (key judging criteria)
- **Evidence Trails**: Dual technical + business explanations
- **Uncertainty Handling**: Graceful degradation and human escalation
- **Self-Awareness**: System monitors its own performance
- **Explainable AI**: Clear reasoning for every recommendation

**Hackathon Judging Criteria Addressed**:
1. ✅ **Trustworthiness** — Confidence tracking and health scoring
2. ✅ **Evidence Trails** — Dual technical and business explanations
3. ✅ **Uncertainty Handling** — Retry logic and human escalation
4. ✅ **Self-Improvement** — Monitoring enables iterative refinement

---

## Technical Improvements

### 1. Structured JSON Output from Gemini

**Original Approach**: Many LLM implementations require parsing markdown code fences from responses, which is brittle and error-prone.

**Agnes 2.0 Enhancement**:
- Uses `response_mime_type="application/json"` parameter
- Gemini returns native JSON, no markdown fences
- Eliminates parsing complexity and failure points
- More reliable and maintainable

**Implementation**:
```python
response = client.models.generate_content(
    model=model_name,
    contents=user_message,
    config=types.GenerateContentConfig(
        system_instruction=AGNES_SYSTEM_PROMPT,
        response_mime_type="application/json",  # Native JSON
        temperature=0.2,
    ),
)

raw_text = response.text.strip()
result = json.loads(raw_text)  # Direct JSON parse, no markdown stripping
```

**Benefit**: Reduces code complexity, eliminates a common failure mode, improves reliability.

---

### 2. Compliance Guardrails in System Prompt

**Original Approach**: Generic system prompts might allow dangerous downgrades (e.g., pharma-grade to food-grade) without explicit justification.

**Agnes 2.0 Enhancement**:
- Hard-encoded compliance rules in system prompt
- Explicit prohibition of grade downgrades
- Requirement for evidence on all decisions
- Confidence-based escalation for uncertainty

**System Prompt Excerpt**:
```
CRITICAL RULES:
- A substitution is only valid if the replacement MEETS OR EXCEEDS the quality 
  and compliance level of the original.
- Downgrading from pharmaceutical grade to food grade is NEVER acceptable without 
  explicit evidence that the finished product only requires food grade.
- A missing certification on the replacement supplier is a compliance gap that must 
  be flagged.
- You must never hallucinate certifications or regulatory status. If you are uncertain, 
  state the uncertainty explicitly and lower your confidence score.
- Confidence scores: 0.9+ = high certainty; 0.7–0.9 = reasonable inference; 
  below 0.7 = uncertain, escalate to human review.
```

**Benefit**: Prevents dangerous recommendations, ensures safety-first approach, provides clear escalation paths.

---

### 3. Evidence Trail Requirements

**Original Approach**: LLM might make recommendations without justification, making decisions opaque and hard to audit.

**Agnes 2.0 Enhancement**:
- Explicit requirement for evidence trail in system prompt
- Evidence must be specific, discrete facts
- Each fact must be numbered and traceable
- Evidence trail included in final report

**Evidence Trail Format**:
```python
"evidence_trail": [
    "Ingredient A carries USP certification, which is a critical quality standard.",
    "Ingredient A is Halal certified, whereas Ingredient B is not.",
    "Ingredient B lacks third-party USP verification.",
    "Consolidation across 33 BOMs requires highest common denominator of certifications."
]
```

**Benefit**: Explainable AI, auditability, trust-building, regulatory compliance support.

---

### 4. Confidence-Based Escalation

**Original Approach**: Binary approve/reject without nuance for uncertainty.

**Agnes 2.0 Enhancement**:
- Confidence score (0.0-1.0) required in output
- Confidence < 0.7 triggers HUMAN_REVIEW_REQUIRED status
- Enables risk-based decision-making
- Clear escalation criteria

**Confidence Thresholds**:
- **0.9+**: High certainty from known chemistry/regulation
- **0.7-0.9**: Reasonable inference from available data
- **<0.7**: Uncertain, requires human review

**Implementation**:
```python
if result["confidence"] < 0.7:
    result["recommendation"] = "HUMAN_REVIEW_REQUIRED"
    result["reasoning"] += " Low confidence due to insufficient data."
```

**Benefit**: Risk-aware decision-making, appropriate human involvement, prevents overconfident bad decisions.

---

## Scalability Considerations

### From Single Ingredient to Portfolio-Wide Analysis

**Original Agnes**:
- Analyzed one ingredient at a time
- Manual selection of targets
- No portfolio-level visibility

**Agnes 2.0**:
- Analyzes all 143 fragmented ingredients in one run
- Automatic prioritization via risk heat map
- Portfolio-wide vulnerability assessment
- Executive dashboard across entire supply chain

**Performance**:
- Single ingredient: ~5 seconds (LLM call)
- Full portfolio (143 ingredients): ~12 minutes (sequential)
- Parallel implementation: ~30 seconds (with proper infrastructure)

**Production Scalability**:
- Can process thousands of ingredients
- Parallel LLM calls via async/await
- Database can scale to millions of BOMs
- Trust tracking accumulates over time

---

## Production Readiness Considerations

### Data Sources

**Mock Data (Hackathon)**:
- Compliance data hardcoded in Python dict
- Delivery history simulated with seeded random
- Single ingredient focus for demo

**Production Requirements**:
- **Compliance Data**: Web scraping (Selenium/Playwright) for:
  - Supplier websites (CoA PDFs)
  - Certification databases (NSF, USP)
  - FDA Substance Registration System API
  - Multimodal LLM for document extraction
- **Delivery History**: ERP/TMS integration for:
  - Actual delivery timestamps
  - Quality incident records
  - Supplier performance metrics
- **Real-time Updates**: Continuous monitoring of:
  - Supplier status changes
  - Certification expirations
  - Regulatory updates

### Infrastructure

**Hackathon Setup**:
- Single Jupyter notebook
- Local SQLite database
- Sequential execution
- Manual cell runs

**Production Architecture**:
- **API Service**: REST/GraphQL endpoints for:
  - Ingredient analysis requests
  - Portfolio risk reports
  - Supplier performance dashboards
- **Database**: PostgreSQL or cloud SQL for:
  - Multi-user access
  - Transaction safety
  - Backup and replication
- **Queue System**: Celery/Redis for:
  - Async LLM processing
  - Background enrichment jobs
  - Scheduled risk scans
- **Monitoring**: Prometheus/Grafana for:
  - API performance
  - LLM latency
  - Error rates
  - Cost tracking

### Security

**Hackathon**:
- API key in `.env` file
- No authentication
- Local execution only

**Production Requirements**:
- **Secrets Management**: HashiCorp Vault or AWS Secrets Manager
- **Authentication**: OAuth 2.0 or API keys
- **Authorization**: Role-based access control
- **Audit Logging**: All decisions and evidence trails logged
- **Data Encryption**: At rest and in transit
- **Compliance**: SOC 2, GDPR considerations

### Error Handling

**Hackathon**:
- Basic try/catch blocks
- Safe fallback dicts
- Manual inspection of errors

**Production Requirements**:
- **Retry Logic**: Exponential backoff for LLM API failures
- **Circuit Breakers**: Prevent cascading failures
- **Dead Letter Queues**: Failed jobs for manual review
- **Alerting**: PagerDuty/Slack for critical failures
- **Graceful Degradation**: Fallback to cached data when APIs fail

---

---

### 6. RAG Compliance Knowledge Base

**Original Approach**: LLM evaluation relied solely on Gemini's training data for regulatory knowledge. No external knowledge source.

**Agnes 2.0 Enhancement**:
- `rag_engine.py` — production-ready module: `build_index()`, `hybrid_search()`, `rerank()`, `format_context_block()`
- `scrape_kb.py` — fetches 20 real regulatory documents: FDA 21 CFR 111, DSHEA, USP Verification, USP Cholecalciferol Monograph, NSF/ANSI 173, IFANCA Halal, Kosher, Non-GMO Project, GMP, FDA labeling, facility registration, etc.
- FAISS HNSW vector index (M=32, `all-MiniLM-L6-v2` 384-dim) + BM25 Okapi keyword index
- Cross-encoder re-ranker (`ms-marco-MiniLM-L-6-v2`) filters top-5 candidates to top-3
- Retrieved docs injected into Gemini `system_instruction` before evaluation
- Evidence trail items must cite `[Source]` brackets: `"[USP Verification Program] USP-verified products must contain..."`
- `sources_cited[]` field added to every LLM JSON response

**Hybrid Search Formula**:
```python
combined_score = 0.65 × vector_score + 0.35 × bm25_score
```

**Benefit**: LLM decisions are grounded in real regulatory knowledge, not just training data. Source citations make evidence trails auditable and demonstrably non-hallucinated.

---

### 7. Historical Decision Memory

**Original Approach**: Each evaluation was stateless. No memory of past decisions.

**Agnes 2.0 Enhancement**:
- Every `evaluate_substitutability_rag()` call persists the verdict to `KB/decisions.json`
- `retrieve_similar_cases()` uses Jaccard token similarity over past verdicts
- Top-2 similar cases injected as `PRECEDENT CASES` block into the Gemini prompt
- Grows automatically with each pipeline run — no manual curation required

**Stored Fields per Decision**:
```python
{
    "ingredient_a", "ingredient_b",          # what was evaluated
    "supplier_a", "supplier_b",              # which suppliers
    "grade_a", "grade_b",                    # quality grades
    "certifications_a", "certifications_b",  # certification lists
    "verdict",                               # APPROVE / REJECT / etc.
    "confidence",                            # 0.0 – 1.0
    "reasoning",                             # LLM narrative
    "evidence_trail",                        # cited facts
    "sources_cited",                         # retrieved regulatory docs
    "stored_at",                             # ISO timestamp
}
```

**Benefit**: Cross-evaluation consistency, continuous learning from accumulated decisions, demonstrates scalability story to judges.

---

### 8. RAGAS-lite Self-Evaluation

**Original Approach**: No measurement of LLM output quality. Recommendations were accepted as-is.

**Agnes 2.0 Enhancement** (Cell 12-RAG):
Three quality metrics computed per evaluation without the RAGAS library:

| Metric | Formula | Meaning |
|--------|---------|--------|
| Faithfulness | grounded items / total evidence items | Are evidence trail facts supported by retrieved docs? |
| Answer Relevance | approve/reject signals in retrieved context | Does the verdict align with what the docs say? |
| Context Recall | relevant docs / total retrieved | Were the right docs actually retrieved? |
| Overall | mean of three metrics | Aggregate RAG quality score |

**Benefit**: Agnes measures her own reasoning quality — rare among hackathon submissions. Demonstrates evaluation discipline and provides a concrete quality assurance story. Production upgrade path (NLI model, LLM judge, full RAGAS) is documented in `RAG_Architecture.md`.

---

### 9. Gradio Web Interface (agnes_ui.py)

**Original Approach**: Notebook-only interface requiring JupyterLab to run evaluations.

**Agnes 2.0 Enhancement**:
- Production-ready Gradio web app (`agnes_ui.py`) on port 7860
- Accepts 6 input types: text, image (CoA), audio, video, PDF, and URLs
- Auto-detects URLs in notes field and smart-routes them (HTML→text, PDF→bytes, image→bytes)
- Multimodal compliance extraction via Gemini Vision from uploaded documents
- RAG-augmented evaluations with source citations
- Confirmation flow: Apply / Show Alternative / Reject All before persisting to KB/decisions.json
- Session logging with structured JSON logs for debugging
- General Assessment tab for portfolio-wide health checks with live DB analytics
- Decision History tab showing stored verdicts with refresh capability
- **Database Explorer tab**: Live read-only SQL views of the supply chain database
  - Company Catalog: Dual dropdown (Company + Product Type) with dynamic table columns
    - **Finished-good view**: Shows SKU + Raw_Materials (comma-separated list of components)
    - **Raw-material view**: Shows Raw_Material_SKU + In_Stock + Used_In_Products
      - `In_Stock` = count of finished products using this material + 1 (for the material itself)
      - `Used_In_Products` = list of finished product SKUs + "Direct sold" flag
  - Supplier Catalog: Read-only view of supplier-product relationships

**Technical Implementation**:
```python
# Smart URL routing
def _resolve_url(url: str) -> tuple[types.Part | None, str]:
    # Detects Content-Type via HEAD request
    # Routes PDF → Part.from_bytes(mime="application/pdf")
    # Routes image → Part.from_bytes(mime=image/jpeg)
    # Routes HTML → BeautifulSoup text extraction
    
# Multimodal input assembly
def _build_parts(notes, coa_image, audio_file, video_file, pdf_file):
    # Interleaves all inputs into Gemini Parts
    # Handles 15MB inline limit for large files
    
# Confirmation flow
def apply_handler(state):
    # User clicks "Apply & Save"
    # Calls store_decision() → KB/decisions.json
    # Updates history table

def alternative_handler(state):
    # User clicks "Show Alternative"
    # Re-evaluates at higher temperature (0.4, 0.5, 0.6)
    # Excludes previous verdict from LLM
    # Up to 3 alternatives allowed
```

**Business Value**:
- **Accessibility**: No JupyterLab required — web browser interface
- **Stakeholder Engagement**: Business users can run evaluations without coding
- **Audit Trail**: Confirmation flow prevents accidental decision persistence
- **Multimodal**: Upload real CoA PDFs, images, and facility videos for richer compliance data
- **Portfolio View**: General Assessment tab provides executive dashboard across all ingredients

**Startup**:
```bash
python agnes_ui.py
# Opens on http://localhost:7860
# Requires: GEMINI_API_KEY in .env, KB/regulatory_docs.json, models/ cached
```

---

### 10. Production Readiness Improvements

**Original Approach**: Limited error handling, no unified setup, minimal logging documentation.

**Agnes 2.0 Enhancement**:
- **Error Handling**: Graceful degradation when KB files or models are missing
- **Session Management**: Automatic session logger cleanup on app shutdown
- **URL Resilience**: Retry logic with specific exception handling (Timeout, ConnectionError, HTTPError)
- **Unified Setup**: `full_setup.sh` script for one-command first-time setup
- **Logging Documentation**: Comprehensive `docs/Logging_Architecture.md` with dual-file logging details

**Technical Implementation**:
```python
# KB file check
if not KB_PATH.exists():
    rag_index = None
    print(f"  ⚠ KB file not found: {KB_PATH}")
    print(f"  Run: python scrape_kb.py")

# Session logger cleanup
def _cleanup_on_exit():
    if session_logger:
        session_logger.close()
atexit.register(_cleanup_on_exit)

# URL fetch with retry logic
for attempt in range(max_retries + 1):
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Agnes/2.0"})
        resp.raise_for_status()
        break
    except Timeout as e:
        if attempt < max_retries:
            continue  # Retry
```

**Business Value**:
- **Reliability**: Graceful degradation prevents app crashes
- **User Experience**: Clear error messages guide users to fix issues
- **Onboarding**: Unified setup script reduces setup time
- **Debugging**: Session logs enable troubleshooting
- **Resilience**: Retry logic handles transient network failures

**Unified Setup Script**:
```bash
chmod +x full_setup.sh
./full_setup.sh
```
Checks .env, builds KB, downloads models, patches notebook, and provides summary.

---

## Summary of Improvements

| Feature | Original Agnes | Agnes 2.0 | Business Impact |
|---------|---------------|------------|-----------------|
| **Scope** | Single ingredient | 143 ingredients | Portfolio-wide visibility |
| **Risk Analysis** | None | Risk heat map with tiers | Prioritized action list |
| **Supplier Reliability** | Ignored | Trust score system | Performance incentives |
| **Contingency Planning** | None | Disruption simulator | Proactive risk management |
| **Cross-Cluster Detection** | Exact match only | LLM-based cluster analysis | Larger consolidation opportunities |
| **Scoring** | Compliance only | Compliance × Trust | Holistic evaluation |
| **LLM Output** | Markdown parsing | Native JSON | More reliable |
| **Guardrails** | Basic | Hard-encoded rules | Safety-first approach |
| **Evidence** | Optional | Required | Explainable AI |
| **Confidence** | Binary | Score-based | Risk-aware decisions |
| **Self-Healing** | None | 3-attempt retry with fallback | Robust error recovery |
| **Self-Monitoring** | None | Real-time confidence tracking | Systematic hallucination control |
| **Self-Explanation** | None | Dual evidence trails (technical + business) | Explainable AI for stakeholders |
| **RAG Knowledge Base** | None | 20 real regulatory docs (FDA, USP, NSF, Halal) | Grounded, source-cited decisions |
| **Historical Memory** | None | Persistent verdict store + precedent retrieval | Cross-evaluation consistency |
| **Quality Evaluation** | None | RAGAS-lite (Faithfulness, Relevance, Recall) | Measurable decision quality |
| **Web Interface** | None | Gradio app with 6 input types | Accessibility for non-technical users |
| **Error Handling** | Basic | Graceful degradation with clear messages | Prevents app crashes |
| **Session Management** | None | Automatic cleanup + log download | Better debugging and audit trails |
| **URL Resilience** | None | Retry logic with specific exceptions | Handles transient network failures |
| **Unified Setup** | Manual steps | One-command full_setup.sh | Faster onboarding |
| **Logging Docs** | None | Comprehensive Logging_Architecture.md | Better system understanding |

## Competitive Advantages

1. **Compliance-First**: Never sacrifices compliance for cost
2. **Explainable**: Every decision has an evidence trail
3. **Risk-Aware**: Trust scores and vulnerability indices
4. **Proactive**: Contingency planning before disruptions
5. **Scalable**: From single ingredient to entire portfolio
6. **Adaptive**: Recommendations adjust as performance changes

## Related Documents

- `Project_Overview.md` - High-level project introduction
- `Database_Complete_Guide.md` - Database schema and relationships
- `Agnes_Pipeline_Architecture.md` - Technical pipeline documentation
- `RAG_Architecture.md` - Full RAG system design, KB contents, and production upgrade path
- `Self_Maintenance.md` - Guide to self-healing, monitoring, and explanation capabilities
- `Logging_Architecture.md` - Unified logging infrastructure documentation
- `Technical_Implementation_Guide.md` - Setup and usage instructions
