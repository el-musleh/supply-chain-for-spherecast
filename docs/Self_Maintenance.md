# Agnes Self-Maintenance Capabilities Guide

## Overview

Agnes 2.0 implements three LLM-based self-maintenance strategies that enable the system to monitor, heal, and explain its own reasoning. These capabilities address critical hackathon judging criteria for trustworthiness, evidence trails, and uncertainty handling.

**The Three Capabilities**:
1. **Self-Healing** (Cell 5) — Robust error recovery with exponential backoff retry
2. **Self-Monitoring** (Cell 5.5) — Real-time confidence tracking and health assessment
3. **Self-Explanation** (Cell 7.5) — Dual evidence trails (technical + business)

---

## 1. Self-Healing (Cell 5)

### Purpose

Handle transient LLM API failures without breaking the pipeline. Provides graceful degradation to safe fallback responses when retries are exhausted.

### Implementation

The `evaluate_substitutability_with_healing()` wrapper function adds retry logic around the base `evaluate_substitutability()` function:

```python
def evaluate_substitutability_with_healing(
    ingredient_a: str, supplier_a: str, compliance_a: dict,
    ingredient_b: str, supplier_b: str, compliance_b: dict,
    context_companies: list, context_bom_appearances: int,
    model_name: str = "gemini-flash-latest",
    max_retries: int = 3,
) -> dict:
```

**Retry Strategy**:
- **Attempt 1**: Temperature = 0.2, wait on failure = 1s
- **Attempt 2**: Temperature = 0.1, wait on failure = 2s
- **Attempt 3**: Temperature = 0.3, final fallback if fails

**Temperature Tuning Rationale**:
- Lower temperature (0.1) for retry 2: More deterministic, reduces variability
- Higher temperature (0.3) for retry 3: Different response generation path

**Fallback Response** (when all retries fail):
```python
{
    "substitutable": False,
    "confidence": 0.0,
    "recommendation": "HUMAN_REVIEW_REQUIRED",
    "reasoning": "Self-healing: LLM API failed after 3 retry attempts...",
    "_meta": {
        "healing_applied": True,
        "fallback_reason": "API failure",
    }
}
```

### Metadata Tracking

Self-healing adds these fields to evaluation metadata:
- `retry_attempt`: Which attempt succeeded (1, 2, or 3)
- `temperature_used`: Temperature value for the successful attempt
- `healing_applied`: Boolean (True if retry was needed)
- `healing_note`: Human-readable description of healing action

---

## 2. Self-Monitoring (Cell 5.5)

### Purpose

Systematic tracking of LLM evaluation quality to detect low-confidence outputs, monitor token usage, and maintain audit trails for trustworthiness assessment.

### The AgnesMonitor Class

```python
class AgnesMonitor:
    LOG_FILE = "agnes_monitoring_log.json"
    LOW_CONFIDENCE_THRESHOLD = 0.7
```

**Core Methods**:

| Method | Purpose |
|--------|---------|
| `record(eval_result, context)` | Store evaluation metrics |
| `analyze_confidence()` | Compute confidence statistics |
| `flag_low_confidence()` | Identify evaluations needing review |
| `health_check()` | Overall system status (HEALTHY/CAUTION/WARNING) |
| `generate_report()` | Comprehensive monitoring report |
| `save_to_disk()` | Persist to JSON |

### Tracked Metrics

**Per-Evaluation Record**:
```json
{
  "timestamp": "2026-04-18T11:15:30",
  "session": "2026-04-18T11:10:00",
  "ingredient_pair": "vitamin-d3-cholecalciferol → vitamin-d3-cholecalciferol",
  "supplier_pair": "Prinova USA → PureBulk",
  "confidence": 0.95,
  "recommendation": "APPROVE_WITH_CONDITIONS",
  "compliance_met": false,
  "compliance_gaps_count": 2,
  "evidence_count": 4,
  "input_tokens": 2847,
  "output_tokens": 412,
  "retry_attempt": 1,
  "healing_applied": false,
  "model": "gemini-flash-latest",
  "context_type": "within_cluster"
}
```

### Health Status Levels

| Status | Condition | Meaning |
|--------|-----------|---------|
| **HEALTHY** | No low-confidence evaluations, mean confidence ≥ 80% | System operating normally |
| **CAUTION** | Mean confidence < 80% | Review recommended |
| **WARNING** | Any evaluation below 0.7 threshold | Manual review required |

### Report Output

The monitoring report displays:
1. **Health Status** — Current system state
2. **Confidence Analysis** — Mean, min, max, low-count percentage
3. **Recommendation Distribution** — Count by verdict type
4. **Token Usage** — Input/output totals
5. **Self-Healing Statistics** — Retry counts, average attempts
6. **Recent Evaluations Table** — Last 10 evaluations with key metrics

### Persistent Logging

The `agnes_monitoring_log.json` file:
- Accumulates evaluations across notebook runs
- Keeps last 100 evaluations in memory
- Full history persisted to disk
- Enables trend analysis over time

---

## 3. Self-Explanation (Cell 7.5)

### Purpose

Generate business-friendly explanations of Agnes recommendations using LLM-powered summarization. Provides dual evidence trails:
- **Technical** (Cell 7) — Regulatory details, compliance gaps, chemistry
- **Business** (Cell 7.5) — Strategic overview, financial impact, action items

### Implementation

**Prompt Engineering**:
```python
EXECUTIVE_SUMMARY_PROMPT = """You are a procurement strategy advisor...
Summarize the following supply chain recommendation...

CONSOLIDATION DATA:
- Ingredient: {ingredient}
- Companies Affected: {company_count}
- BOM Impact: {bom_count}
...

Provide:
- executive_summary: one-paragraph strategic overview
- action_items: 3 specific actions
- financial_impact: savings opportunity
- risk_considerations: key risks
- next_steps: immediate action
"""
```

### Output Format

```json
{
  "executive_summary": "Consolidation of vitamin-d3-cholecalciferol across 17 companies presents a significant opportunity...",
  "action_items": [
    "Initiate supplier negotiation with Prinova USA for consolidated purchasing",
    "Validate USP and Halal certification requirements with affected brands",
    "Calculate volume-based pricing discount potential"
  ],
  "financial_impact": "Estimated 12-18% cost reduction through volume consolidation and reduced SKU complexity",
  "risk_considerations": "Compliance gaps in PureBulk option (missing USP/Halal) limit supplier flexibility",
  "next_steps": "Schedule procurement alignment meeting with Nature Made and Kirkland Signature",
  "_meta": {
    "generated_at": "2026-04-18T11:20:00",
    "model": "gemini-flash-latest"
  }
}
```

### Fallback Behavior

If LLM generation fails, returns a safe default:
```python
{
  "executive_summary": "Consolidation opportunity identified...",
  "action_items": ["Review technical evidence", "Validate compliance", "Contact supplier"],
  "financial_impact": "Potential savings from consolidation. Detailed analysis required.",
  "_meta": {"fallback": True, "error": "API failure description"}
}
```

---

## Configuration

### Tunable Parameters

| Parameter | Default | Description | Location |
|-----------|---------|-------------|----------|
| `max_retries` | 3 | Maximum retry attempts for LLM calls | Cell 5, `evaluate_substitutability_with_healing()` |
| `LOW_CONFIDENCE_THRESHOLD` | 0.7 | Confidence level triggering WARNING status | Cell 5.5, `AgnesMonitor` class |
| `temperatures` | [0.2, 0.1, 0.3] | Temperature values per retry attempt | Cell 5, hardcoded |
| `LOG_FILE` | "agnes_monitoring_log.json" | Monitoring log filename | Cell 5.5, `AgnesMonitor` class |

### Adjusting Thresholds

To change the low-confidence threshold:
```python
monitor = AgnesMonitor()
monitor.LOW_CONFIDENCE_THRESHOLD = 0.8  # Stricter threshold
```

---

## Integration in Pipeline

**Cell Execution Order**:
```
Cell 5  →  Cell 5.5  →  Cell 6  →  Cell 7  →  Cell 7.5
(LLM)     (Monitor)    (Opt)     (Report)   (Explain)
   │           │
   └───────────┘
   eval_results passed
   to monitor.record()
```

**Data Flow**:
1. Cell 5 produces evaluation results with `_meta` data
2. Cell 5.5 records these via `monitor.record()`
3. Cell 7 uses the same evaluations for report generation
4. Cell 7.5 calls Gemini to generate executive summary

---

## Troubleshooting

### Issue: All retries failing

**Symptom**: Every evaluation shows `healing_applied: True` with `retry_attempt: 3`

**Solutions**:
1. Check API key validity in `.env`
2. Verify internet connectivity
3. Check Google AI Studio status
4. Review rate limits

### Issue: Monitoring log not persisting

**Symptom**: `agnes_monitoring_log.json` not created

**Solutions**:
1. Check write permissions in project directory
2. Verify Cell 5.5 ran successfully
3. Check for disk space issues

### Issue: Low confidence scores

**Symptom**: Health status consistently WARNING

**Possible Causes**:
- Complex ingredient substitutions with limited data
- Conflicting compliance requirements
- Missing supplier certifications

**Mitigation**:
- Review flagged evaluations manually
- Verify compliance data accuracy
- Adjust `LOW_CONFIDENCE_THRESHOLD` if needed

### Issue: Executive summary generation fails

**Symptom**: Cell 7.5 shows fallback warning

**Solutions**:
1. Check if Cells 5 and 7 ran successfully first
2. Verify `df_recommendation` is not empty
3. Check API key and connectivity

---

## Business Value

**For Hackathon Judges**:
- **Trustworthiness**: Demonstrates systematic approach to AI safety
- **Evidence Trails**: Dual technical + business explanations
- **Uncertainty Handling**: Graceful degradation and human escalation
- **Self-Awareness**: System monitors its own performance

**For Production Use**:
- Audit trail for compliance reviews
- Early warning for model drift
- Cost tracking (token usage)
- Quality assurance automation
