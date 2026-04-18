# Agnes AI Supply Chain Decision-Support System - Complete Documentation Summary

## Executive Summary

Agnes is an AI-powered decision-support system designed to solve fragmented raw material sourcing in the Consumer Packaged Goods (CPG) industry. Built for the Spherecast Hackathon 2026, Agnes analyzes historical procurement decisions across 60 CPG companies, identifies functionally interchangeable ingredients, verifies compliance through external data enrichment, and produces consolidated sourcing recommendations with explainable evidence trails. The system combines SQL analytics, mock external data enrichment, LLM reasoning (Gemini Flash), and optimization algorithms in a 10-cell Jupyter notebook pipeline.

## The Problem: Fragmented Sourcing

### What is Fragmentation?

Massive CPG brands often purchase the exact same raw ingredient across multiple product lines from different suppliers without centralized visibility. For example, 17 different companies independently purchase "vitamin-d3-cholecalciferol" under different SKUs, each negotiating separately with suppliers. This fragmentation results in:

- No bulk discounts despite massive combined volume
- Longer lead times due to smaller, scattered orders
- Weaker negotiation position with suppliers
- Redundant quality audits and compliance checks
- Higher operational complexity

### Database Statistics

The system uses a SQLite database (`DB/db.sqlite`) containing:
- 61 CPG companies
- 876 products (finished goods and raw materials)
- 40 suppliers
- 149 BOMs (Bill of Materials)
- 1,528 BOM components
- 143 fragmented ingredients (purchased by multiple companies)
- 1,214 BOM appearances at risk

## Technical Architecture

### Database Schema

**Core Tables**:
1. **Company**: CPG brands (Nature Made, GNC, Kirkland Signature)
2. **Product**: Finished goods and raw materials with SKU format
3. **BOM**: Formulation recipes for finished products
4. **BOM_Component**: Ingredient mappings
5. **Supplier**: Raw material vendors (Prinova USA, PureBulk, Cargill)
6. **Supplier_Product**: Supplier-to-ingredient mapping

**SKU Format for Raw Materials**:
```
RM-C{CompanyId}-{ingredient-name}-{8hexhash}
```
Example: `RM-C30-vitamin-d3-cholecalciferol-559c9699`

**Key Innovation**: By parsing the ingredient name from the SKU using SQL string functions, Agnes can identify when multiple companies are independently purchasing the same ingredient under different SKUs.

**SKU Parsing Formula**:
```sql
SUBSTR(
    SUBSTR(SKU, 4 + INSTR(SUBSTR(SKU, 4), '-')),
    1,
    LENGTH(SUBSTR(SKU, 4 + INSTR(SUBSTR(SKU, 4), '-'))) - 9
)
```

### 10-Cell Pipeline Architecture

**Cell 1: Environment Setup**
- Imports: sqlite3, json, os, random, pandas, python-dotenv, google.genai
- Loads GEMINI_API_KEY from .env file
- Initializes Gemini client
- Sets database path to DB/db.sqlite

**Cell 2: Database Connection & Fragmented Demand Ingestion**
- Parses ingredient names from SKUs using SQL CTEs
- Identifies all 143 fragmented ingredients
- Calculates supplier coverage for each ingredient
- Outputs df_fragmented and df_supplier_coverage DataFrames

**Cell 3: Target Selection & Finished-Product Impact Trace**
- Selects vitamin-d3-cholecalciferol as demo target (highest fragmentation)
- Traces which 33 finished products depend on this ingredient
- Shows per-company breakdown with SKUs and BOM counts

**Cell 4: External Data Enrichment (Mock Compliance Scraper)**
- Mock database simulates external compliance data
- Returns: organic_certified, fda_registered, non_gmo, grade, lead_time_days, certifications, notes
- In production would scrape supplier websites, certification databases, FDA API

**Cell 5: LLM Reasoning Agent (Gemini)**
- Model: gemini-flash-latest via Google GenAI SDK
- Configuration: response_mime_type="application/json", temperature=0.2
- System prompt with hard-encoded compliance guardrails
- Two evaluations: supplier consolidation and cross-cluster grade comparison
- Returns structured JSON with substitutable, confidence, evidence_trail, compliance_met, compliance_gaps, reasoning, recommendation

**Cell 6: Optimization & Supplier Consolidation Algorithm**
- Compliance weight formula: base 1.0 + grade modifiers + certification bonuses
- Ranking formula: bom_appearances_covered × compliance_weight × trust_multiplier
- Approved statuses: APPROVE, APPROVE_WITH_CONDITIONS, HUMAN_REVIEW_REQUIRED (excludes REJECT)
- Produces ranked supplier recommendation table

**Cell 7: Final Sourcing Recommendation Output**
- Executive-facing report with evidence trails
- Shows supplier ranking, LLM reasoning, compliance gaps
- Fragmentation analysis summary
- Business impact quantification

**Cell 8: Go-Fish Supplier Trust Score**
- Tracks supplier reliability (on-time deliveries increase score, delays decrease)
- Base score: 100, +10 per on-time delivery, -20 per delay
- Trust tiers: PROBATION (<70) → BRONZE → SILVER → GOLD → PLATINUM (≥160)
- Trust multiplier: 0.5x to 1.5x applied to compliance weight

**Cell 9: Supply Chain Risk Heat Map**
- Scans all 143 ingredients for vulnerability
- Vulnerability index: total_bom_appearances / distinct_supplier_count
- Risk tiers: CRITICAL (1 supplier), HIGH (2 suppliers, ≥20 BOMs), MEDIUM (≥15 BOMs), LOW
- Outputs ranked priority list for procurement teams

**Cell 10: Disruption Simulator**
- "What if a supplier goes offline?" analysis
- Simulates Prinova USA failure (135 ingredients affected, 712 BOMs at risk)
- Checks for alternate suppliers
- Generates LLM-powered contingency plan with timeline

## Key Algorithms

### Compliance Weight Formula
```python
weight = 1.0
if grade == "pharmaceutical": weight += 0.2
elif grade == "technical": weight -= 0.3
if fda_registered: weight += 0.1
if non_gmo: weight += 0.1
cert_bonus = min(0.30, len(certifications) * 0.05)
weight += cert_bonus
return max(0.1, weight)
```

### Vulnerability Index
```python
vulnerability_index = total_bom_appearances / distinct_supplier_count
```

### Trust Score
```python
score = 100 + (on_time_deliveries * 10) - (delays * 20)
trust_multiplier = max(0.5, min(1.5, score / 100))
```

### Consolidation Score
```python
score = bom_appearances_covered × compliance_weight × trust_multiplier
```

## Agnes 2.0 Improvements Over Original

### New Features

1. **Risk Heat Map (Cell 9)**: System-wide vulnerability assessment across all 143 ingredients with risk tier classification
2. **Go-Fish Trust Score (Cell 8)**: Supplier reliability tracking with dynamic scoring (0.5x to 1.5x multiplier)
3. **Disruption Simulator (Cell 10)**: "What if" scenario analysis with LLM-powered contingency planning
4. **Cross-Cluster Detection**: Identifies substitution opportunities across ingredient name variants (vitamin-d3 → vitamin-d3-cholecalciferol)
5. **Trust-Adjusted Scoring**: Combines compliance weight with trust multiplier for holistic evaluation

### Technical Improvements

1. **Structured JSON Output**: Uses response_mime_type="application/json" for native JSON, eliminating markdown parsing
2. **Compliance Guardrails**: Hard-encoded rules in system prompt prevent dangerous downgrades
3. **Evidence Trail Requirements**: Mandatory numbered facts for every recommendation
4. **Confidence-Based Escalation**: Confidence < 0.7 triggers HUMAN_REVIEW_REQUIRED status

## LLM Integration Details

### Model Configuration
- **Model**: gemini-flash-latest
- **SDK**: Google GenAI (not the older google-generativeai)
- **Response Format**: Native JSON
- **Temperature**: 0.2 for consistent, factual reasoning

### System Prompt Key Rules
- Substitution only valid if replacement MEETS OR EXCEEDS quality of original
- Downgrading from pharmaceutical to food grade NEVER acceptable without explicit evidence
- Missing certification must be flagged as compliance gap
- Never hallucinate certifications or regulatory status
- Confidence scores: 0.9+ = high certainty, 0.7-0.9 = reasonable inference, <0.7 = uncertain

### Evidence Trail Format
```json
{
  "substitutable": false,
  "confidence": 0.95,
  "evidence_trail": [
    "Ingredient A carries USP certification, critical quality standard",
    "Ingredient A is Halal certified, whereas Ingredient B is not",
    "Ingredient B lacks third-party USP verification"
  ],
  "compliance_met": false,
  "compliance_gaps": ["Missing USP certification", "Missing Halal certification"],
  "reasoning": "While Ingredient B is pharmaceutical grade, it fails compliance profile due to missing USP and Halal",
  "recommendation": "REJECT"
}
```

## Case Study: Vitamin D3

### The Opportunity
- 17 companies purchasing independently
- 33 finished products depend on this ingredient
- 17 unique SKUs for the same chemical
- 2 suppliers: Prinova USA and PureBulk
- Zero combined-volume leverage today

### Compliance Analysis
**Prinova USA**: Pharmaceutical grade, USP, GMP, Halal, Kosher, 14-day lead time
**PureBulk**: Pharmaceutical grade, GMP, Kosher, 7-day lead time (missing USP, Halal)

**LLM Verdict**: REJECT (95% confidence)
- Gap: Missing USP certification (required by GNC, Kirkland Signature)
- Gap: Missing Halal certification
- Reasoning: Major retailers require USP verification, Halal status cannot be removed without invalidating product claims

### Business Value Despite Rejection
- Risk visibility: Identifies 33 products at risk
- Actionable path: Clear certification gaps to address
- Evidence-based: Prevents dangerous consolidation
- Cross-cluster opportunity: vitamin-d3 (food-grade) can upgrade to cholecalciferol (pharma-grade) - APPROVED

## Business Value and ROI

### Portfolio-Wide Impact
- 143 fragmented ingredients
- 60 CPG companies affected
- 1,214 BOM appearances at risk
- 18 CRITICAL ingredients (single-source)
- 11 HIGH-risk ingredients (2 suppliers, high volume)

### ROI Estimation
**Example for Vitamin D3**:
- Annual volume: 10,000 kg
- Current cost: $50/kg
- Consolidated cost: $42/kg (16% discount)
- Savings: $80,000/year + $50,000 safety stock + $20,000 audits = $150,000
- Implementation: $30,000 one-time
- Net first-year: $120,000
- Payback: 2.4 months

**Portfolio-Wide (50 ingredients consolidated)**:
- Total annual savings: $5,000,000
- Implementation cost: $1,500,000
- Net first-year: $3,500,000
- 3-year ROI: 233%

## Risk Analysis

### Single-Source Dependencies
18 CRITICAL ingredients have only 1 supplier:
- maltodextrin (21 BOMs)
- glycerin (17 BOMs)
- natural-flavor (13 BOMs)

Any supplier disruption immediately halts production. Agnes recommends: qualify secondary suppliers, build safety stock, implement monitoring.

### Disruption Simulation
If Prinova USA goes offline:
- 135 ingredients affected
- 712 BOMs at risk
- 0 ingredients with no backup (manageable exposure)
- Contingency plan: contact PureBulk/Univar/Jost Chemical for spot inventory, place bridge orders, audit secondary contracts

## Use Cases

1. **New Product Launch**: Identify consolidation opportunities from day one
2. **Supplier Negotiation**: Use volume data for stronger pricing position
3. **Risk Management**: Proactive vulnerability assessment and mitigation
4. **M&A Integration**: Consolidate procurement across merged companies
5. **Regulatory Response**: Rapid response to new certification requirements

## Implementation

### Environment Setup
```bash
chmod +x setup.sh && ./setup.sh
jupyter-lab
```

### Dependencies
- google-genai >= 1.73.1
- pandas >= 2.0.0
- python-dotenv >= 1.0.0
- ipykernel >= 6.0.0

### Filesystem Considerations
Repository lives on exFAT filesystem (no symlinks). All packages managed via pipx to avoid venv symlink issues.

### Common Pitfalls
- Wrong Google package: Use google-genai, not google-generativeai
- Missing API key: Add GEMINI_API_KEY to .env file
- Symlink errors: Use pipx instead of python -m venv

## Performance Characteristics

- Database queries: < 1 second
- LLM calls: ~5-10 seconds per evaluation
- Total pipeline runtime: ~30 seconds
- Memory usage: < 50MB
- Scalability: Can process all 143 ingredients in parallel in production

## Production Readiness

### Data Sources (Mock in Hackathon)
- Compliance data: Web scraping of supplier websites, certification databases, FDA API
- Delivery history: ERP/TMS integration
- Real-time updates: Continuous monitoring

### Infrastructure Requirements
- API service for programmatic access
- PostgreSQL or cloud SQL for multi-user database
- Queue system for async LLM processing
- Monitoring and alerting

### Security
- Secrets management (HashiCorp Vault, AWS Secrets Manager)
- Authentication (OAuth 2.0)
- Role-based access control
- Audit logging
- Data encryption at rest and in transit

## Glossary

- **CPG**: Consumer Packaged Goods - companies manufacturing everyday items
- **BOM**: Bill of Materials - formulation recipe for a finished product
- **SKU**: Stock Keeping Unit - unique product identifier
- **LLM**: Large Language Model - AI system for natural language processing
- **RAG**: Retrieval-Augmented Generation - AI technique combining retrieval with generation
- **USP**: United States Pharmacopeia - quality standard for pharmaceuticals
- **GMP**: Good Manufacturing Practice - quality control standard
- **CoA**: Certificate of Analysis - document certifying product specifications
- **ERP**: Enterprise Resource Planning - business management software
- **TMS**: Transportation Management System - logistics software

## Related Documents

- `Project_Overview.md` - High-level project introduction and hackathon context
- `Database_Complete_Guide.md` - Detailed database schema, ERD, and query patterns
- `Agnes_Pipeline_Architecture.md` - Technical documentation of 10-cell pipeline
- `Agnes_2.0_Improvements.md` - Enhancements over original Agnes concept
- `Technical_Implementation_Guide.md` - Developer setup, usage, and modification guide
- `Business_Value.md` - ROI analysis, case studies, and use cases

## Quick Start

```bash
# Environment setup
chmod +x setup.sh && ./setup.sh

# Configure API key
echo "GEMINI_API_KEY=your_key_here" >> .env

# Launch notebooks
jupyter-lab

# Open agnes.ipynb and run cells sequentially
```

## Conclusion

Agnes AI transforms fragmented procurement from a hidden cost center into a strategic advantage by quantifying the problem (143 ingredients, 1,214 BOMs), enabling action through evidence-based recommendations, managing risk through vulnerability assessment, ensuring compliance through guardrails, and delivering ROI (estimated $5M+ annual savings). The system combines rigorous compliance verification with practical business value, making it a powerful tool for CPG procurement teams.
