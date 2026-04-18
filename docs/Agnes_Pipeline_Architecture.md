# Agnes 2.0 Pipeline Architecture

## Overview

Agnes 2.0 implements a 10-cell pipeline that transforms fragmented supply chain data into actionable sourcing recommendations. The pipeline combines SQL analytics, mock external data enrichment, LLM reasoning, and optimization algorithms to produce compliance-aware consolidation proposals with explainable evidence trails.

## Pipeline Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         AGNES 2.0 PIPELINE                           │
└─────────────────────────────────────────────────────────────────────┘

┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Cell 1  │───▶│  Cell 2  │───▶│  Cell 3  │───▶│  Cell 4  │
│  Setup   │    │  DB Ingest│    │  Target  │    │  Enrich  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                                          │
                                                          ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Cell 10  │◀───│  Cell 9  │◀───│  Cell 8  │◀───│  Cell 5  │
│ Disrupt  │    │  Risk    │    │  Trust   │    │   LLM    │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                              │
                                              ▼
                                    ┌──────────┐
                                    │ Cell 5.5 │
                                    │ Monitor  │
                                    └──────────┘
                                              │
                                              ▼
                                    ┌──────────┐
                                    │  Cell 6  │
                                    │  Optimize│
                                    └──────────┘
                                              │
                                              ▼
                                    ┌──────────┐
                                    │  Cell 7  │
                                    │  Report  │
                                    └──────────┘
                                              │
                                              ▼
                                    ┌──────────┐
                                    │ Cell 7.5 │
                                    │ Explain  │
                                    └──────────┘
```

## Cell-by-Cell Documentation

### Cell 1: Environment Setup

**Purpose**: Initialize the Python environment, load dependencies, and configure the Gemini AI client.

**Key Operations**:
- Import required libraries: `sqlite3`, `json`, `os`, `random`, `pandas`
- Load environment variables using `python-dotenv`
- Initialize Google GenAI SDK client with API key from `.env`
- Configure pandas display options for readability
- Set database path to `DB/db.sqlite`

**Code Structure**:
```python
import sqlite3
import json
import os
import random
import pandas as pd
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()  # Loads GEMINI_API_KEY from .env
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
DB_PATH = "DB/db.sqlite"
```

**Output**:
- Confirmation of Agnes version
- Google GenAI SDK version
- Database path
- API key loading status

**Dependencies**:
- `google-genai` (version 1.73.1)
- `pandas`
- `python-dotenv`
- `sqlite3` (built-in)

---

### Cell 2: Database Connection & Fragmented Demand Ingestion

**Purpose**: Query the database to identify all fragmented ingredients (purchased by multiple companies) and calculate consolidation opportunities.

**Key Innovation**: The SKU parsing formula that extracts ingredient names from the structured SKU format.

**SQL CTE Structure**:

```sql
WITH parsed AS (
    -- Parse ingredient name from SKU: RM-C{CompanyId}-{ingredient-name}-{8hexhash}
    SELECT
        p.Id AS product_id,
        p.SKU,
        p.CompanyId,
        c.Name AS company_name,
        SUBSTR(
            SUBSTR(p.SKU, 4 + INSTR(SUBSTR(p.SKU, 4), '-')),
            1,
            LENGTH(SUBSTR(p.SKU, 4 + INSTR(SUBSTR(p.SKU, 4), '-'))) - 9
        ) AS ingredient_name
    FROM Product p
    JOIN Company c ON c.Id = p.CompanyId
    WHERE p.Type = 'raw-material'
),
bom_usage AS (
    -- Count BOM appearances per ingredient variant
    SELECT
        pr.ingredient_name,
        pr.company_name,
        pr.CompanyId,
        pr.product_id,
        pr.SKU,
        COUNT(bc.BOMId) AS bom_appearances
    FROM parsed pr
    JOIN BOM_Component bc ON bc.ConsumedProductId = pr.product_id
    GROUP BY pr.product_id
),
fragmented_ingredients AS (
    -- Identify ingredients purchased by >1 company
    SELECT
        ingredient_name,
        COUNT(DISTINCT CompanyId) AS company_count,
        SUM(bom_appearances) AS total_bom_appearances
    FROM bom_usage
    GROUP BY ingredient_name
    HAVING company_count > 1
)
```

**Two Main Queries**:

1. **Fragmented Demand Query** (`SQL_FRAGMENTED`):
   - Returns one row per (ingredient, company) pair
   - Shows how much each company purchases
   - Ordered by total BOM volume

2. **Supplier Coverage Query** (`SQL_SUPPLIER_COVERAGE`):
   - JOINs with Supplier_Product and Supplier tables
   - Shows which suppliers can deliver each ingredient variant
   - Essential for consolidation analysis

**Output**:
- `df_fragmented`: DataFrame with all fragmented ingredient purchases
- `df_supplier_coverage`: DataFrame with supplier mapping
- Summary statistics: 143 fragmented ingredients, 60 companies, 1,214 BOM appearances
- Top 15 consolidation opportunities ranked by BOM volume

**Sample Output**:
```
Fragmented ingredients found : 143
CPG companies involved        : 60
Total BOM appearances at risk : 1214

Top 15 consolidation opportunities:
                            CPG companies  BOM appearances  distinct suppliers
ingredient_name                                                              
vitamin-d3-cholecalciferol             17               33                   2
gelatin                                11               30                   2
magnesium-stearate                     11               30                   2
```

---

### Cell 3: Target Selection & Finished-Product Impact Trace

**Purpose**: Select a specific ingredient for detailed analysis and trace which finished products depend on it.

**Target Selection Criteria**:
The system selects `vitamin-d3-cholecalciferol` as the demo target because:
- Highest fragmentation: 17 companies buying independently
- 33 total BOM appearances → significant combined demand
- Only 2 available suppliers (Prinova USA, PureBulk)
- Zero price leverage today despite combined volume
- Chemistry is unambiguous (cholecalciferol IS vitamin D3)
- LLM reasoning will be clean and defensible

**Key Operations**:

1. **Filter data for target ingredient**:
   ```python
   TARGET_INGREDIENT = "vitamin-d3-cholecalciferol"
   RELATED_INGREDIENT = "vitamin-d3"
   df_target = df_fragmented[df_fragmented["ingredient_name"] == TARGET_INGREDIENT].copy()
   ```

2. **Display fragmentation profile**:
   - Company count
   - Total BOM appearances
   - Distinct supplier options
   - Per-company breakdown with SKUs and BOM counts

3. **Finished-product impact trace**:
   - Follow the chain: raw-material → BOM_Component → BOM → finished-good
   - Shows judges exactly WHICH products would benefit from consolidation
   - Query: `SQL_FINISHED_PRODUCTS`

**SQL for Finished Products**:
```sql
WITH parsed AS (
    SELECT
        p.Id AS rm_product_id,
        c.Name AS company_name,
        SUBSTR(...) AS ingredient_name
    FROM Product p
    JOIN Company c ON c.Id = p.CompanyId
    WHERE p.Type = 'raw-material'
)
SELECT
    pr.company_name,
    pr.ingredient_name,
    fg.SKU AS finished_product_sku
FROM parsed pr
JOIN BOM_Component bc ON bc.ConsumedProductId = pr.rm_product_id
JOIN BOM b ON b.Id = bc.BOMId
JOIN Product fg ON fg.Id = b.ProducedProductId
WHERE pr.ingredient_name = :ingredient
```

**Output**:
- Fragmentation profile for target ingredient
- Per-company SKU breakdown
- Supplier coverage table
- List of finished products (33 SKUs across 17 companies)
- Related cluster analysis (vitamin-d3 as potential cross-cluster substitute)

**Business Impact**:
- Turns abstract "BOM appearances" into concrete product names
- Shows: "If we consolidate vitamin-d3-cholecalciferol, these 33 products benefit"
- Enables ROI calculation based on product sales volume

---

### Cell 4: External Data Enrichment (Mock Compliance Scraper)

**Purpose**: Enrich supplier data with compliance information (certifications, grade, lead time, FDA registration).

**Production vs. Mock**:
In production, Agnes would:
- Crawl supplier websites (Selenium/Playwright) for Certificate of Analysis (CoA) PDFs
- Query NSF/USP certification databases
- Call FDA Substance Registration System API
- Use multimodal LLM to extract specs from product data sheets

For the hackathon, this is mocked with realistic, supplier-specific data.

**Mock Database Structure**:
```python
_COMPLIANCE_MOCK_DB = {
    ("Prinova USA", "vitamin-d3-cholecalciferol"): {
        "organic_certified": False,
        "fda_registered": True,
        "non_gmo": True,
        "grade": "pharmaceutical",
        "lead_time_days": 14,
        "certifications": ["USP", "GMP", "Halal", "Kosher"],
        "notes": "Lanolin-derived cholecalciferol. USP-grade specification sheet available."
    },
    ("PureBulk", "vitamin-d3-cholecalciferol"): {
        "organic_certified": False,
        "fda_registered": True,
        "non_gmo": True,
        "grade": "pharmaceutical",
        "lead_time_days": 7,
        "certifications": ["GMP", "Kosher"],
        "notes": "Bulk powder, pharmaceutical grade. Shorter lead time."
    }
}
```

**Function: `scrape_supplier_compliance()`**:
- Takes `(supplier_name, ingredient_name)` as input
- Returns compliance profile dictionary
- Falls back to seeded random generation for unknown pairs
- Ensures reproducibility via hash-based seeding

**Compliance Profile Schema**:
```python
{
    "organic_certified": bool,      # USDA/EU organic certification
    "fda_registered": bool,          # FDA facility registration
    "non_gmo": bool,                 # Non-GMO statement on file
    "grade": str,                    # "pharmaceutical" | "food" | "technical"
    "lead_time_days": int,          # Typical order-to-delivery lead time
    "certifications": list,          # Third-party certs (USP, NSF, GMP, Halal, Kosher, ISO)
    "notes": str                     # Free-text summary (from scraped CoA in prod)
}
```

**Output**:
- Compliance profiles for all suppliers of target ingredient
- Formatted display showing all attributes per supplier

**Key Insight**:
The mock data reflects real-world differences:
- Prinova: USP certified, Halal, longer lead time (14 days)
- PureBulk: No USP, no Halal, shorter lead time (7 days)
- This difference drives the LLM's REJECT verdict in Cell 5

---

### Cell 5: LLM Reasoning Agent (Gemini)

**Purpose**: Use Gemini Flash to evaluate ingredient substitutability with strict compliance guardrails and evidence trail requirements.

**Model Configuration**:
- **Model**: `gemini-flash-latest`
- **SDK**: Google GenAI (not the older `google-generativeai`)
- **Response Format**: Native JSON (`response_mime_type="application/json"`)
- **Temperature**: 0.2 (low for consistent, factual reasoning)
- **System Prompt**: Hard-encoded compliance guardrails

**System Prompt (`AGNES_SYSTEM_PROMPT`)**:
```
You are Agnes, an AI supply chain reasoning agent for the CPG industry.
Your role is to evaluate whether two raw-material ingredient variants are 
functionally substitutable for sourcing consolidation purposes.

CRITICAL RULES:
- A substitution is only valid if the replacement MEETS OR EXCEEDS the quality 
  and compliance level of the original.
- Downgrading from pharmaceutical grade to food grade is NEVER acceptable without 
  explicit evidence that the finished product only requires food grade.
- A missing certification on the replacement supplier is a compliance gap that must 
  be flagged.
- You must produce an evidence trail: a list of specific, discrete facts that 
  support your conclusion.
- You must never hallucinate certifications or regulatory status. If you are 
  uncertain, state the uncertainty explicitly and lower your confidence score.
- Confidence scores: 0.9+ = high certainty; 0.7–0.9 = reasonable inference; 
  below 0.7 = uncertain, escalate to human review.

OUTPUT FORMAT: Respond with valid JSON only matching this exact schema:
{
  "substitutable": <bool>,
  "confidence": <float 0.0-1.0>,
  "evidence_trail": ["<fact 1>", "<fact 2>", ...],
  "compliance_met": <bool>,
  "compliance_gaps": ["<gap description if any>"],
  "reasoning": "<2-4 sentence narrative>",
  "recommendation": "<APPROVE | APPROVE_WITH_CONDITIONS | REJECT | HUMAN_REVIEW_REQUIRED>"
}
```

**Two Evaluations Run**:

1. **Eval 1 - Supplier Consolidation**:
   - Question: "Can PureBulk replace Prinova USA for vitamin-d3-cholecalciferol?"
   - Tests: Same ingredient, different suppliers
   - Purpose: Demonstrates supplier consolidation with compliance check

2. **Eval 2 - Cross-Cluster Grade Comparison**:
   - Question: "Can pharma-grade cholecalciferol replace food-grade vitamin-d3?"
   - Tests: Different ingredient names, same supplier
   - Purpose: Demonstrates nuanced grade-level reasoning

**Function: `evaluate_substitutability()`**:
- Builds user prompt with ingredient A and B details
- Includes business context (companies affected, BOM appearances)
- Calls Gemini API with system instruction
- Parses JSON response
- Falls back to safe error dict if parsing fails
- Attaches metadata (model, tokens used, ingredient names)

**Prompt Structure**:
```python
"""
## Substitutability Evaluation Request

### Ingredient A — Current (consolidate FROM)
- Ingredient name   : {ingredient_a}
- Supplier          : {supplier_a}
- FDA registered    : {compliance_a['fda_registered']}
- Grade             : {compliance_a['grade']}
- Non-GMO           : {compliance_a['non_gmo']}
- Organic           : {compliance_a['organic_certified']}
- Certifications    : {', '.join(compliance_a['certifications'])}
- Lead time         : {compliance_a['lead_time_days']} days
- Supplier notes    : {compliance_a['notes']}

### Ingredient B — Proposed (consolidate TO)
[same structure for ingredient B]

### Business Context
- CPG companies affected : {company_list}
- Total BOM appearances  : {context_bom_appearances}
- Consolidation goal     : Replace all company-specific SKUs with one consolidated purchase order

### Question
Can Ingredient B (from {supplier_b}) substitute for Ingredient A (from {supplier_a}) 
across all affected CPG companies' BOMs while maintaining full quality and compliance?
Provide your structured JSON evaluation.
"""
```

**Output - Eval 1 Results**:
```
Recommendation : REJECT
Substitutable  : False
Confidence     : 95%
Compliance met : False
⚠ Gap         : Missing USP (United States Pharmacopeia) certification
⚠ Gap         : Missing Halal certification

Evidence trail:
• Ingredient A carries USP certification, which is a critical quality standard 
  for pharmaceutical-grade dietary supplements in the US market.
• Ingredient A is Halal certified, whereas Ingredient B is not.
• Ingredient B lacks third-party USP verification, which is often a non-negotiable 
  requirement for major retailers like Kirkland Signature and GNC.
• Consolidation across 33 BOMs requires the replacement to meet the 'highest common 
  denominator' of certifications to avoid product-specific compliance failures.

Reasoning: While Ingredient B is listed as pharmaceutical grade, it fails to meet 
the compliance profile of Ingredient A due to the absence of USP and Halal certifications. 
For major CPG brands like GNC and Kirkland, USP verification is a primary quality 
benchmark, and removing Halal status would invalidate the certification of any finished 
products currently making that claim.

Tokens used: 783 in / 267 out
```

**Output - Eval 2 Results**:
```
Recommendation : APPROVE
Substitutable  : True
Confidence     : 98%
Compliance met : True

Reasoning: Ingredient B is a direct quality upgrade from Ingredient A, moving from 
a food-grade blend to a pharmaceutical-grade USP cholecalciferol. Since Ingredient B 
meets or exceeds all regulatory, certification, and potency requirements of Ingredient A 
while originating from the same supplier, it is a low-risk candidate for consolidation.
```

**Key Innovation**:
- Evidence trail requirement forces LLM to justify decisions
- Confidence scoring enables risk-based escalation
- Compliance guardrails prevent dangerous downgrades
- JSON output eliminates markdown parsing complexity
- **Self-healing retry logic** with exponential backoff (3 attempts, temperature tuning)

---

### Cell 5.5: Self-Monitoring & Confidence Tracking

**Purpose**: Real-time monitoring of LLM evaluation quality, tracking confidence scores, token usage, and healing statistics to ensure trustworthiness and enable systematic hallucination control.

**Key Operations**:
- Initialize `AgnesMonitor` class with persistent JSON logging
- Record evaluation metadata (confidence, recommendation, compliance, tokens)
- Analyze confidence distribution and flag low-confidence evaluations (< 0.7 threshold)
- Generate health report (HEALTHY/CAUTION/WARNING status)
- Display recent evaluations table with key metrics
- Persist monitoring log to `agnes_monitoring_log.json`

**Code Structure**:
```python
class AgnesMonitor:
    LOG_FILE = "agnes_monitoring_log.json"
    LOW_CONFIDENCE_THRESHOLD = 0.7
    
    def __init__(self): ...
    def record(self, eval_result, context): ...
    def analyze_confidence(self) -> dict: ...
    def health_check(self) -> str: ...
    def display_report(self): ...
    def save_to_disk(self): ...

# Usage
monitor = AgnesMonitor()
monitor.record(eval_within_cluster, {"type": "within_cluster"})
monitor.record(eval_cross_cluster, {"type": "cross_cluster"})
monitor.display_report()
monitor.save_to_disk()
```

**Tracked Metrics**:
- Confidence score, recommendation type, compliance status
- Input/output token counts
- Retry attempts and healing status
- Ingredient and supplier pairs
- Timestamp and session tracking

**Output - Health Report**:
```
======================================================================
  AGNES SELF-MONITORING REPORT
======================================================================
  Health Status    : HEALTHY
  Session Start    : 2026-04-18T11:10:00
  Total Evaluations: 2

──────────────────────────────────────────────────────────────────────
CONFIDENCE ANALYSIS
──────────────────────────────────────────────────────────────────────
  Mean Confidence  : 96.5%
  Min / Max        : 95.0% / 98.0%
  Low Confidence   : 0 (0.0%)

──────────────────────────────────────────────────────────────────────
SELF-HEALING STATISTICS
──────────────────────────────────────────────────────────────────────
  Retries Required : 0
  Avg Retry Count  : 1.0

──────────────────────────────────────────────────────────────────────
RECENT EVALUATIONS
──────────────────────────────────────────────────────────────────────
  context_type      confidence  recommendation           compliance_met  healing_applied
  within_cluster    0.95        REJECT                   False           False
  cross_cluster     0.98        APPROVE                  True            False
```

**Health Status Levels**:
- **HEALTHY**: No low-confidence evaluations, mean ≥ 80%
- **CAUTION**: Mean confidence < 80%
- **WARNING**: Any evaluation below 0.7 threshold

---

### Cell 6: Optimization & Supplier Consolidation Algorithm

**Purpose**: Rank suppliers by a weighted score and produce the final sourcing recommendation.

**Ranking Formula**:
```
consolidated_score = bom_appearances_covered × compliance_weight × trust_multiplier
```

**Approved Statuses**:
- `APPROVE` → included, no conditions
- `APPROVE_WITH_CONDITIONS` → included, flagged
- `HUMAN_REVIEW_REQUIRED` → included as conditional, flagged
- `REJECT` → excluded entirely

**Function: `compute_compliance_weight()`**:
```python
def compute_compliance_weight(compliance: dict) -> float:
    """Score a supplier's compliance profile. Range ~0.1–1.8."""
    weight = 1.0
    
    # Grade modifiers
    if compliance.get("grade") == "pharmaceutical":
        weight += 0.2
    elif compliance.get("grade") == "technical":
        weight -= 0.3
    
    # Binary attributes
    if compliance.get("fda_registered"):
        weight += 0.1
    if compliance.get("non_gmo"):
        weight += 0.1
    
    # Certifications (capped at +0.30)
    cert_bonus = min(0.30, len(compliance.get("certifications", [])) * 0.05)
    weight += cert_bonus
    
    return round(max(0.1, weight), 3)
```

**Compliance Weight Components**:
- Base: +1.0
- Pharmaceutical grade: +0.2
- FDA registered: +0.1
- Non-GMO: +0.1
- Per certification: +0.05 (capped at +0.30)
- Technical grade: −0.30
- Minimum floor: 0.10

**Function: `consolidate_sourcing()`**:
```python
def consolidate_sourcing(
    ingredient_name: str,
    df_supplier_coverage: pd.DataFrame,
    approved_evaluations: list,
    scrape_fn,
) -> pd.DataFrame:
    """Produce ranked sourcing recommendation for a given ingredient."""
    
    # Filter to approved suppliers only
    approved_suppliers = {
        ev["_meta"]["supplier_b"]
        for ev in approved_evaluations
        if ev.get("recommendation") in _APPROVED_STATUSES
    }
    
    # Aggregate coverage data
    df_agg = (
        df_ing.groupby("supplier_name")
        .agg(
            bom_appearances_covered = ("bom_appearances", "sum"),
            companies_covered = ("company_name", "nunique"),
        )
        .reset_index()
    )
    
    # Calculate scores
    for each supplier:
        comp = scrape_fn(supplier, ingredient)
        weight = compute_compliance_weight(comp)
        score = bom_appearances_covered × weight × trust_multiplier
    
    # Sort by score descending
    return df_result.sort_values("consolidated_score", ascending=False)
```

**Output**:
- Ranked supplier table with columns:
  - rank
  - supplier_name
  - bom_appearances_covered
  - companies_covered
  - grade
  - certifications
  - lead_time_days
  - fda_registered
  - non_gmo
  - compliance_weight
  - consolidated_score
  - llm_verdict
  - agnes_recommendation (PRIMARY SUPPLIER / SECONDARY / MONITOR)

**Current State**:
Since PureBulk received a REJECT verdict in Cell 5, no suppliers pass the filter. The output shows an empty table, demonstrating Agnes's compliance-first approach.

---

### Cell 7: Final Sourcing Recommendation Output

**Purpose**: Generate the executive-facing report with evidence trails and business impact summary.

**Report Structure**:

```
======================================================================
  AGNES — CONSOLIDATED SOURCING RECOMMENDATION
======================================================================
  Ingredient   : vitamin-d3-cholecalciferol
  Scope        : 17 CPG companies, 33 BOM appearances
  LLM model    : gemini-flash-latest
======================================================================

[SUPPLIER RANKING TABLE]

[EVIDENCE TRAIL - EVALUATION 1: Supplier Consolidation]

[EVIDENCE TRAIL - EVALUATION 2: Cross-Cluster Grade Check]

[FRAGMENTATION ANALYSIS]
```

**Evidence Trail Format**:
- Numbered list of facts from LLM
- Confidence percentage
- Compliance status (PASSED / GAPS IDENTIFIED)
- Specific gaps flagged
- Reasoning summary

**Fragmentation Analysis**:
- Number of companies buying separately
- Unique SKU count
- Supplier count
- Business impact statement

**Output**:
Since no suppliers passed the consolidation filter, the report shows:
- No supplier ranking table
- Full evidence trail from both evaluations
- Clear statement of why consolidation was rejected (compliance gaps)
- Fragmentation waste summary

**Business Value**:
Even when consolidation is rejected, the report provides value by:
- Explaining WHY (compliance gaps, not just "no")
- Identifying specific missing certifications
- Quantifying the opportunity cost (33 BOMs, 17 companies)
- Providing actionable next steps (certification acquisition)

---

### Cell 7.5: Executive Summary Generator (Self-Explanation)

**Purpose**: Generate LLM-powered business-friendly explanations of recommendations, creating a dual evidence trail (technical + business) for procurement teams and leadership.

**Key Operations**:
- Build context from evaluation results and recommendation data
- Call Gemini with specialized executive-summary prompt
- Generate strategic overview with financial impact
- Provide actionable next steps for procurement teams
- Display both technical evidence (Cell 7) and business summary (this cell)

**Prompt Engineering**:
```python
EXECUTIVE_SUMMARY_PROMPT = """You are a procurement strategy advisor...
Summarize the following supply chain recommendation...

CONSOLIDATION DATA:
- Ingredient: {ingredient}
- Companies Affected: {company_count}
- BOM Impact: {bom_count}
- Recommended Supplier: {winner_supplier}
...

Provide:
- executive_summary: one-paragraph strategic overview
- action_items: 3 specific actions
- financial_impact: savings opportunity
- risk_considerations: key risks
- next_steps: immediate action
"""
```

**Function: `generate_executive_summary()`**:
```python
def generate_executive_summary(context: dict) -> dict:
    """Generate business-friendly executive summary using Gemini."""
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

**Output Format**:
```json
{
  "executive_summary": "Consolidation of vitamin-d3-cholecalciferol across 17 companies presents...",
  "action_items": [
    "Initiate supplier negotiation with Prinova USA for consolidated purchasing",
    "Validate USP and Halal certification requirements with affected brands",
    "Calculate volume-based pricing discount potential"
  ],
  "financial_impact": "Estimated 12-18% cost reduction through volume consolidation...",
  "risk_considerations": "Compliance gaps in PureBulk option (missing USP/Halal)...",
  "next_steps": "Schedule procurement alignment meeting with Nature Made and Kirkland...",
  "_meta": {
    "generated_at": "2026-04-18T11:20:00",
    "model": "gemini-flash-latest"
  }
}
```

**Display Format**:
```
======================================================================
  AGNES EXECUTIVE SUMMARY (Self-Explanation)
======================================================================

📋 STRATEGIC OVERVIEW
──────────────────────────────────────────────────────────────────────
Consolidation of vitamin-d3-cholecalciferol across 17 CPG companies...

🎯 ACTION ITEMS
──────────────────────────────────────────────────────────────────────
  1. Initiate supplier negotiation with Prinova USA
  2. Validate USP and Halal certification requirements
  3. Calculate volume-based pricing discount potential

💰 FINANCIAL IMPACT
──────────────────────────────────────────────────────────────────────
  Estimated 12-18% cost reduction through volume consolidation...

⚠️  RISK CONSIDERATIONS
──────────────────────────────────────────────────────────────────────
  Compliance gaps in PureBulk option (missing USP/Halal)...

🚀 IMMEDIATE NEXT STEPS
──────────────────────────────────────────────────────────────────────
  → Schedule procurement alignment meeting...

✓ Generated by gemini-flash-latest

Dual Evidence Trail Complete:
  • Technical: See Cell 7 Evidence Trail (regulatory & compliance)
  • Business:  See above Executive Summary (strategic & financial)
```

**Fallback Behavior**:
If LLM generation fails, returns safe default with fallback flag:
```python
{
  "executive_summary": "Consolidation opportunity identified...",
  "action_items": ["Review technical evidence", "Validate compliance", "Contact supplier"],
  "financial_impact": "Potential savings. Detailed analysis required.",
  "_meta": {"fallback": True, "error": "API failure description"}
}
```

**Dual Evidence Trail Value**:
- **Technical** (Cell 7): Detailed regulatory analysis, compliance gaps, chemistry facts
- **Business** (Cell 7.5): Strategic overview, financial impact, actionable recommendations
- **Audience**: Technical for auditors/compliance teams, Business for procurement leadership

---

### Cell 8: Go-Fish Supplier Trust Score

**Purpose**: Track supplier reliability history to adjust recommendations based on performance.

**Concept**: Similar to the card game "Go-Fish" where you build a hand over time, suppliers build trust through consistent performance.

**Scoring System**:
- Base score: 100
- On-time delivery: +10 per delivery
- Delay / quality incident: −20 per event
- Tiers: PROBATION (<70) → BRONZE → SILVER → GOLD → PLATINUM (≥160)

**Class: `SupplierTrustTracker`**:
```python
class SupplierTrustTracker:
    BASE_SCORE = 100
    ON_TIME_BONUS = 10
    DELAY_PENALTY = 20
    
    def simulate_history(self, supplier_name: str, n_deliveries: int = 20):
        # Seeded random for reproducibility
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
        # Maps score to 0.5x - 1.5x multiplier
        return round(max(0.5, min(1.5, self.get_score(supplier_name) / 100)), 3)
```

**Trust Tier Logic**:
```python
def get_trust_tier(self, supplier_name: str) -> str:
    s = self.get_score(supplier_name)
    if s >= 160: return "PLATINUM"
    if s >= 130: return "GOLD"
    if s >= 100: return "SILVER"
    if s >= 70:  return "BRONZE"
    return "PROBATION"
```

**Output**:
- Full leaderboard of all 40 suppliers
- Columns: rank, supplier_name, trust_score, trust_tier, trust_multiplier, on_time_deliveries, delays, on_time_rate
- Trust-adjusted compliance weights for target ingredient suppliers

**Sample Output**:
```
Trust-adjusted compliance weights for 'vitamin-d3-cholecalciferol' suppliers:
  Prinova USA     | score= 120 | tier=SILVER    | compliance=1.600 × trust=1.200 → adjusted=1.920
  PureBulk        | score= 180 | tier=PLATINUM  | compliance=1.500 × trust=1.500 → adjusted=2.250
```

**Business Impact**:
- A supplier with better compliance but poor history might rank lower than a slightly less compliant but highly reliable supplier
- Trust multiplier (0.5x to 1.5x) significantly impacts final scores
- Encourages suppliers to maintain consistent performance

**Production Note**:
In production, this would pull from ERP/TMS systems with actual delivery history, not simulated data.

---

### Cell 9: Supply Chain Risk Heat Map

**Purpose**: Scan all 143 fragmented ingredients and score each by supply chain vulnerability.

**Vulnerability Index Formula**:
```
vulnerability_index = total_bom_appearances / distinct_supplier_count
```

**Higher index = more dangerous**: High demand concentrated in few suppliers.

**Risk Tier Logic**:
```python
def _risk_tier(row: pd.Series) -> str:
    if row["supplier_count"] == 1:
        return "CRITICAL"
    if row["supplier_count"] == 2 and row["total_bom_appearances"] >= 20:
        return "HIGH"
    if row["total_bom_appearances"] >= 15:
        return "MEDIUM"
    return "LOW"
```

**Query Pipeline**:
1. Count suppliers per ingredient (from coverage data)
2. Sum BOM totals per ingredient
3. Merge and calculate vulnerability index
4. Apply risk tier classification
5. Sort by vulnerability index descending

**Output**:
- Summary statistics: total ingredients, counts per risk tier
- Top 15 most vulnerable ingredients table
- Columns: rank, ingredient_name, total_bom_appearances, company_count, supplier_count, vulnerability_index, risk_tier

**Sample Output**:
```
Total ingredients analyzed : 143
CRITICAL  (1 supplier)     : 18
HIGH      (2 sup, ≥20 BOM) : 11
MEDIUM    (≥15 BOMs)       : 9
LOW                        : 105

Top 15 most vulnerable ingredients:
rank  ingredient_name               total_bom_appearances  company_count  supplier_count  vulnerability_index  risk_tier
1     maltodextrin                  21                     8              1               21.0                  CRITICAL
2     glycerin                      17                     8              1               17.0                  CRITICAL
3     vitamin-d3-cholecalciferol    33                     17             2               16.5                  HIGH
```

**Business Value**:
- Prioritizes which ingredients need immediate attention
- Identifies single-source dependencies (CRITICAL)
- Highlights high-volume, low-supplier-count ingredients (HIGH)
- Enables proactive risk management

---

### Cell 10: Disruption Simulator

**Purpose**: "What if a supplier goes offline?" - Auto-rerouting analysis for contingency planning.

**Scenario**: Simulate Prinova USA going offline (largest supplier in the database).

**Analysis Steps**:
1. Identify all ingredients supplied by Prinova USA
2. Count BOM appearances at risk
3. Check for alternate suppliers
4. Classify exposure (MANAGEABLE vs CRITICAL)
5. Generate contingency plan using LLM

**Output**:
- Summary: ingredients affected, BOMs at risk, ingredients with no backup
- Top 20 affected ingredients table
- Columns: ingredient_name, bom_appearances_at_risk, companies_at_risk, alternate_suppliers, exposure
- LLM-generated contingency plan with immediate, week-1, month-1 actions

**Sample Output**:
```
======================================================================
  AGNES — DISRUPTION SIMULATOR: 'Prinova USA' goes offline
======================================================================
  Ingredients directly affected : 135
  Total BOM appearances at risk : 712
  Ingredients with NO backup    : 0  ← CRITICAL EXPOSURE
======================================================================

[Top 20 affected ingredients table]

──────────────────────────────────────────────────────────────────────
AGNES CONTINGENCY PLAN
──────────────────────────────────────────────────────────────────────
  Risk level         : HIGH
  Highest priority   : vitamin-d3-cholecalciferol

  IMMEDIATE (24 h):
    • Contact PureBulk, Univar Solutions, and Jost Chemical to secure existing spot-buy inventory.
    • Place immediate bridge orders for the top 10 ingredients by BOM volume.
    • Issue formal notice to production planning regarding potential lead-time extensions.

  WEEK 1:
    • Conduct comprehensive audit of remaining 132 ingredients to verify secondary supplier contracts.
    • Validate quality specifications of backup suppliers against existing CoAs.

  MONTH 1:
    • Onboard tertiary suppliers for high-volume ingredients like Citric Acid and Vitamin D3.
    • Perform post-mortem on safety stock levels and adjust minimum inventory thresholds.

  Strategic recommendation:
  Shift from single-distributor reliance to diversified multi-sourcing strategy.
```

**Business Value**:
- Proactive risk management
- Enables scenario planning
- Identifies single points of failure
- Provides actionable contingency steps
- Quantifies disruption impact

---

## Data Flow Between Cells

```
Cell 1 (Setup)
    ↓
    → DB_PATH, client, pandas config
    ↓
Cell 2 (DB Ingest)
    ↓
    → df_fragmented, df_supplier_coverage
    ↓
Cell 3 (Target Selection)
    ↓
    → df_target, df_target_suppliers, df_finished
    ↓
Cell 4 (Enrichment)
    ↓
    → scrape_supplier_compliance() function
    ↓
Cell 5 (LLM)
    ↓
    → eval_within_cluster, eval_cross_cluster
    ↓
Cell 6 (Optimization)
    ↓
    → df_recommendation
    ↓
Cell 7 (Report)
    ↓
    → Final formatted output
    ↓
Cell 8 (Trust)
    ↓
    → df_trust, trust_tracker object
    ↓
Cell 9 (Risk Heat Map)
    ↓
    → df_risk
    ↓
Cell 10 (Disruption)
    ↓
    → Contingency plan
```

## Key Algorithms Summary

### 1. SKU Parsing (Cell 2)
```sql
SUBSTR(
    SUBSTR(SKU, 4 + INSTR(SUBSTR(SKU, 4), '-')),
    1,
    LENGTH(SUBSTR(SKU, 4 + INSTR(SUBSTR(SKU, 4), '-'))) - 9
)
```

### 2. Compliance Weight (Cell 6)
```python
weight = 1.0
if grade == "pharmaceutical": weight += 0.2
if fda_registered: weight += 0.1
if non_gmo: weight += 0.1
cert_bonus = min(0.30, len(certifications) * 0.05)
weight += cert_bonus
return max(0.1, weight)
```

### 3. Vulnerability Index (Cell 9)
```python
vulnerability_index = total_bom_appearances / distinct_supplier_count
```

### 4. Trust Score (Cell 8)
```python
score = 100 + (on_time_deliveries * 10) - (delays * 20)
trust_multiplier = max(0.5, min(1.5, score / 100))
```

### 5. Consolidation Score (Cell 6)
```python
score = bom_appearances_covered × compliance_weight × trust_multiplier
```

## LLM Integration Details

### Prompt Engineering Principles
1. **Explicit constraints**: Hard-coded rules prevent dangerous decisions
2. **Evidence requirement**: Forces justification of every recommendation
3. **Confidence scoring**: Enables risk-based escalation
4. **Business context**: Includes scope and impact in every evaluation
5. **Structured output**: JSON schema eliminates parsing complexity

### Hallucination Controls
- System prompt explicitly forbids certification fabrication
- Confidence < 0.7 triggers HUMAN_REVIEW_REQUIRED
- Evidence trail must cite specific facts
- Uncertainty must be stated explicitly

### Token Usage (from actual run)
- Evaluation 1: 783 input tokens, 267 output tokens
- Evaluation 2: Similar range
- Total: ~2,000 tokens for both evaluations

## Performance Characteristics

### Scalability
- Database queries: < 1 second on SQLite
- LLM calls: ~5-10 seconds per evaluation (Gemini Flash)
- Total pipeline runtime: ~30 seconds for full 10-cell execution
- Can process all 143 ingredients in parallel in production

### Memory Usage
- Pandas DataFrames: < 50MB total
- SQLite connection: Minimal
- No large intermediate objects

### Reproducibility
- Random number generators seeded with supplier name hash
- Deterministic mock data generation
- Same inputs produce identical outputs

## Related Documents

- `Project_Overview.md` - High-level project introduction
- `Database_Complete_Guide.md` - Database schema and relationships
- `Agnes_2.0_Improvements.md` - Enhancements over original concept
- `Technical_Implementation_Guide.md` - Setup and usage instructions
