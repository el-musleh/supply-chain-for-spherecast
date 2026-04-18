# Project Overview: Agnes AI Supply Chain Decision-Support System

## Executive Summary

Agnes is an AI-powered decision-support system designed to solve the fragmented raw material sourcing problem in the Consumer Packaged Goods (CPG) industry. Built for the Spherecast Hackathon 2026, Agnes analyzes historical procurement decisions across 60 CPG companies, identifies functionally interchangeable ingredients, verifies compliance through external data enrichment, and produces consolidated sourcing recommendations with explainable evidence trails.

## The Problem: Fragmented Sourcing in CPG

### What is the CPG Industry?

CPG (Consumer Packaged Goods) refers to companies that manufacture everyday items consumers use frequently and replace regularly. This includes:
- Food & Beverages (snacks, cereal, bottled water, dairy products)
- Personal Care & Hygiene (toothpaste, shampoo, deodorant, skincare)
- Household Products (laundry detergent, paper towels, cleaning sprays)
- Pet Care (dog food, cat litter)
- Over-the-Counter Medications (pain relievers, cold medicine, vitamins)

CPG companies produce at massive scale across dozens of product lines and factories, making their purchasing of raw ingredients highly fragmented.

### The Fragmentation Problem

Massive CPG brands often purchase the exact same raw ingredient across multiple product lines from different suppliers without centralized visibility. For example:
- 17 different companies independently purchase "vitamin-d3-cholecalciferol"
- Each company has its own SKU for the same ingredient
- No single team sees the combined demand across all companies
- Suppliers don't see the true buying volume
- Companies lose leverage on price, lead time, and service levels

This fragmentation means:
- No bulk discounts despite massive combined volume
- Longer lead times due to smaller, scattered orders
- Weaker negotiation position with suppliers
- Redundant quality audits and compliance checks
- Higher operational complexity

### Why Consolidation is Complex

You cannot simply combine orders. A cheaper or consolidated ingredient is only valuable if it is:
1. **Functionally substitutable** - The chemistry must be equivalent
2. **Compliance-compliant** - Must meet all quality and regulatory requirements
3. **Operationally feasible** - Lead times, certifications, and logistics must work

For dietary supplements, a pharmaceutical-grade ingredient with USP certification cannot be replaced by a food-grade ingredient without USP certification, even if they're chemically similar. The finished product's labeling claims depend on the ingredient's certifications.

## The Solution: Agnes AI

### Agnes Vision (from Spherecast)

At Spherecast, the concept of "Agnes" represents an AI Supply Chain Manager that helps teams make better sourcing decisions by reasoning across fragmented supply chain data. The hackathon invited participants to challenge and improve Spherecast's current approach.

### How Agnes Works

Agnes follows a 7-stage pipeline:

1. **Database Ingestion** - Loads fragmented BOM data from 60 CPG companies (143 shared ingredients, 1,214 BOM appearances)
2. **Target Selection** - Identifies high-value consolidation opportunities using demand volume and supplier diversity metrics
3. **Compliance Enrichment** - Scrapes external supplier data (certifications, grade, lead time, FDA registration)
4. **LLM Reasoning** - Uses Gemini Flash to evaluate substitutability with strict compliance guardrails
5. **Consolidation Algorithm** - Ranks suppliers by `bom_appearances_covered × compliance_weight`
6. **Evidence Trail** - Produces explainable reasoning justifying each recommendation
7. **Executive Dashboard** - Delivers ranked action list across all ingredients

### Agnes 2.0 Enhancements

The implementation extends the original Agnes concept with:
- **Risk Heat Map** - Vulnerability index scoring all 143 ingredients by supply concentration
- **Go-Fish Trust Score** - Supplier reliability tracking (on-time deliveries increase score, delays decrease it)
- **Disruption Simulator** - "What if a supplier goes offline?" auto-rerouting analysis
- **Cross-Cluster Detection** - Identifies substitution opportunities across ingredient name variants (e.g., vitamin-d3 → vitamin-d3-cholecalciferol)
- **Trust-Adjusted Scoring** - Multiplies compliance weight by supplier trust tier (0.5x to 1.5x)

## Hackathon Context

### Challenge Details

- **Duration**: 1.5 days (36 hours)
- **Team**: el-musleh
- **Technology Stack**: Python, Jupyter Notebooks, SQLite, Google GenAI SDK (Gemini Flash)
- **Data Provided**: SQLite database with real companies and approximated BOMs

### Judging Criteria

The challenge emphasizes:
1. **Practical usefulness and business relevance** - Is this actually useful for a real company?
2. **Trustworthiness and hallucination control** - How well does the system prevent AI from making things up?
3. **Evidence trails** - Can the system prove its recommendations with sources?
4. **External data sourcing** - Ability to operationalize messy, missing external information
5. **Soundness of substitution logic** - Quality of the compliance inference
6. **Creativity in scalability** - How could this system grow and improve over time?

**UI polish is not a priority** - The focus is on reasoning quality and business value.

### Deliverables

- Working prototype (agnes.ipynb)
- Presentation covering:
  - Problem framing and business relevance
  - Data acquisition and enrichment strategy
  - Approach to substitution detection and compliance inference
  - Optimization / recommendation logic
  - Architectural decisions and model choices
  - Demonstration of the system
  - Handling of uncertainty, evidence quality, and tradeoffs

## Key Stakeholders

### Spherecast
The company hosting the challenge. Spherecast is a B2B tech company that centrally manages procurement intelligence and uses it to support customers in the CPG space. Agnes is their internal AI concept for supply chain decision support.

### CPG Companies (Customers)
The database contains real companies including:
- **Retailers**: Target, CVS, Walgreens, Costco, Sam's Club, Thrive Market
- **Brands**: Nature Made, GNC, Kirkland Signature, NOW Foods, Vitacost, The Vitamin Shoppe
- **Specialty**: Nordic Naturals, Jarrow Formulas, Thorne, Ritual, Solgar

### Suppliers
Raw material vendors in the database include:
- Prinova USA, PureBulk, Cargill, ADM, Univar Solutions
- BulkSupplements, Sensient, Balchem, Cambrex
- Jost Chemical, Stauber, Virginia Dare, Source-Omega LLC

## Technical Architecture

### Database
- SQLite database (`DB/db.sqlite`) with 6 tables
- 61 companies, 876 raw materials, 40 suppliers, 149 BOMs, 1,528 BOM components
- Raw material SKUs follow pattern: `RM-C{CompanyId}-{ingredient-name}-{8hexhash}`
- Example: `RM-C30-vitamin-d3-cholecalciferol-559c9699`

### AI Model
- **Model**: Gemini Flash Latest via Google GenAI SDK
- **API**: Google GenAI (not the older google-generativeai package)
- **Configuration**: `response_mime_type="application/json"`, `temperature=0.2`
- **System Prompt**: Hard-encoded compliance guardrails to prevent hallucinations

### Key Algorithms

**Compliance Weight Formula**:
- Base: +1.0
- Pharmaceutical grade: +0.2
- FDA registered: +0.1
- Non-GMO: +0.1
- Per certification (USP, GMP, Halal, Kosher, etc.): +0.05 (capped at +0.30)
- Technical grade: −0.30
- Minimum floor: 0.10

**Vulnerability Index**:
```
vulnerability_index = total_bom_appearances / distinct_supplier_count
```
Higher index = more dangerous (high demand concentrated in few suppliers)

**Consolidation Score**:
```
consolidated_score = bom_appearances_covered × compliance_weight × trust_multiplier
```

## Filesystem Considerations

This repository lives on an `exfat` filesystem that does not support symlinks. Standard `python -m venv` will fail. All packages are managed via `pipx` into `~/.local/share/pipx`. The `setup.sh` script handles this automatically.

## Related Documents

- `Database_Architecture.md` - Detailed database schema and relationships
- `Agnes_Pipeline_Architecture.md` - Technical documentation of the 10-cell pipeline
- `Agnes_2.0_Improvements.md` - Enhancements over the original concept
- `Technical_Implementation_Guide.md` - Developer setup and usage guide
- `Business_Value.md` - ROI analysis and case studies
- `NotebookLM_Summary.md` - Consolidated reference for AI analysis

## Quick Start

```bash
# Environment setup
chmod +x setup.sh && ./setup.sh

# Launch notebooks
jupyter-lab

# Open agnes.ipynb and run cells sequentially
```

## Demo Case: Vitamin D3 Consolidation

The system uses vitamin-d3-cholecalciferol as the primary demo target because:
- Highest fragmentation: 17 companies buying independently
- 33 total BOM appearances → significant combined demand
- Only 2 available suppliers (Prinova USA, PureBulk)
- Zero price leverage today despite the combined volume
- Chemistry is unambiguous (cholecalciferol IS vitamin D3)
- LLM reasoning will be clean and defensible

The analysis shows that PureBulk cannot substitute for Prinova USA due to missing USP and Halal certifications, demonstrating Agnes's compliance-first approach even when consolidation would save money.
