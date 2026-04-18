# Agnes Self-Maintenance Implementation Plan

Implement three LLM-based self-maintenance strategies in `agnes.ipynb`: self-monitoring (confidence tracking), self-healing (retry logic), and self-explanation (audit trails) to enhance trustworthiness and demonstrate systematic reliability for the hackathon.

---

## Item 1: Self-Monitoring with Confidence Tracking (Cell 5.5)

**Location**: New cell inserted after Cell 5 (LLM Reasoning Agent)

**Purpose**: Analyze LLM evaluation outputs in real-time, track confidence distributions, flag low-confidence results, and maintain a persistent monitoring log.

**Implementation Details**:
- Create `AgnesMonitor` class with methods:
  - `record_evaluation(eval_result)` - stores evaluation metadata
  - `analyze_confidence()` - computes statistics on confidence scores
  - `flag_low_confidence(threshold=0.7)` - identifies evaluations needing review
  - `generate_health_report()` - produces human-readable summary
  - `save_to_disk()` - persists to `agnes_monitoring_log.json`
- Collect metrics: confidence score, recommendation type, token usage, compliance gaps, timestamp
- Output: Display DataFrame of recent evaluations + health report + alerts for scores < 0.7
- Persistence: Append to JSON file (accumulates across notebook runs)

**Code Structure**:
```python
class AgnesMonitor:
    LOG_FILE = "agnes_monitoring_log.json"
    
    def __init__(self): load existing log or create new
    def record(self, eval_result, context): append evaluation
    def health_check(self): return status (HEALTHY/WARNING/CRITICAL)
    def display_report(self): show pandas DataFrame + summary stats

# Usage in cell:
monitor = AgnesMonitor()
monitor.record(eval_within_cluster, {"type": "within_cluster"})
monitor.record(eval_cross_cluster, {"type": "cross_cluster"})
monitor.display_report()
monitor.save_to_disk()
```

**Judging Value**: Demonstrates systematic approach to hallucination control and trustworthiness monitoring.

---

## Item 2: Self-Healing Retry Logic (Enhanced Cell 5)

**Location**: Add wrapper function in Cell 5, modify existing calls

**Purpose**: Handle transient LLM API failures with intelligent retry logic and graceful degradation.

**Implementation Details**:
- Create `evaluate_substitutability_with_healing()` wrapper function:
  - Accepts same parameters as original function
  - Implements exponential backoff retry (3 attempts)
  - Adjusts temperature on retry (0.2 → 0.1 → 0.3) for varied responses
  - Falls back to rule-based conservative evaluation if all retries fail
- Modify Cell 5 to use wrapper instead of direct calls
- Track retry attempts in monitoring log

**Code Structure**:
```python
def evaluate_substitutability_with_healing(*args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            # Adjust temperature per attempt for variety
            temp = [0.2, 0.1, 0.3][attempt]
            result = evaluate_substitutability(*args, temperature=temp, **kwargs)
            result["_meta"]["retry_attempt"] = attempt + 1
            return result
        except Exception as e:
            if attempt == max_retries - 1:
                # Final fallback: return conservative safe response
                return create_fallback_response(args, str(e))
            time.sleep(2 ** attempt)  # exponential backoff

# Replace existing calls in Cell 5:
eval_within_cluster = evaluate_substitutability_with_healing(...)
eval_cross_cluster = evaluate_substitutability_with_healing(...)
```

**Fallback Response**: Returns `HUMAN_REVIEW_REQUIRED` with `confidence: 0.0` and explanation of failure.

**Judging Value**: Shows robust error handling and uncertainty management (key judging criteria).

---

## Item 3: Self-Explanation Audit Trails (Cell 7.5)

**Location**: New cell inserted after Cell 7 (Final Recommendation Output)

**Purpose**: Generate LLM-powered executive summary explaining the recommendation in business terms.

**Implementation Details**:
- Create `generate_executive_summary()` function:
  - Takes the full recommendation context (evaluations, supplier data, consolidation scores)
  - Calls Gemini with a specialized business-summary prompt
  - Produces 3-5 bullet points in plain language
- Display both technical evidence trail (existing) and executive summary (new)
- Include: what action to take, why it matters, key risks, expected benefits

**Code Structure**:
```python
EXECUTIVE_SUMMARY_PROMPT = """You are a procurement strategy advisor. Summarize the following supply chain recommendation for a CPG executive in 3-5 clear bullet points. Focus on:
1. What action to take
2. Why this matters financially
3. Key risks to monitor
4. Expected business impact

Data: {recommendation_data}

Format as concise business recommendations."""

def generate_executive_summary(eval_results, recommendation_df):
    context = build_summary_context(eval_results, recommendation_df)
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=EXECUTIVE_SUMMARY_PROMPT.format(recommendation_data=context),
        config=types.GenerateContentConfig(temperature=0.3)
    )
    return json.loads(response.text)

# Usage in cell:
summary = generate_executive_summary([eval_within_cluster, eval_cross_cluster], df_recommendation)
print("=== EXECUTIVE SUMMARY ===")
for point in summary["bullet_points"]:
    print(f"• {point}")
```

**Judging Value**: Directly addresses "explainable sourcing recommendation" requirement with dual evidence trails (technical + business).

---

## Implementation Order

1. **First**: Self-Healing (Item 2) - modify Cell 5 functions
2. **Second**: Self-Monitoring (Item 1) - add Cell 5.5 after Cell 5
3. **Third**: Self-Explanation (Item 3) - add Cell 7.5 after Cell 7

**Estimated Time**: 30-45 minutes per item

**Testing**: After each item, run Cells 1-5 to verify functionality, then proceed to next.

---

## Files Modified

- `/mnt/nvme0n1p6/Notebooks/Projects/Hackathon 2026/agnes.ipynb` - Add 2 new cells, modify Cell 5
- `/mnt/nvme0n1p6/Notebooks/Projects/Hackathon 2026/agnes_monitoring_log.json` - Created automatically

## Dependencies

No new dependencies required. Uses existing: `google-genai`, `pandas`, `json`, `time`, `os`
