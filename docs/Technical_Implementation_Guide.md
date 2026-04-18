# Technical Implementation Guide

## Overview

This guide provides developers with detailed instructions for setting up, running, and extending the Agnes AI Supply Chain Decision-Support System. It covers environment configuration, dependency management, common pitfalls, and modification guidelines.

## Prerequisites

### System Requirements

- **Operating System**: Linux, macOS, or Windows
- **Python**: 3.10 or higher
- **Memory**: 4GB RAM minimum (8GB recommended)
- **Disk Space**: 500MB for repository and dependencies
- **Additional RAM for RAG**: ~700 MB - 1.1 GB (local embedding + reranker models)

### Filesystem Considerations

**Critical**: This repository lives on an `exfat` filesystem that does not support symlinks. Standard `python -m venv` will fail with "Operation not permitted" errors.

**Solution**: All packages are managed via `pipx` into `~/.local/share/pipx` to avoid symlink issues.

## Environment Setup

### Method 1: Automated Setup (Recommended)

Run the provided setup script:

```bash
chmod +x setup.sh
./setup.sh
```

This script:
- Installs JupyterLab via pipx
- Installs required Python packages (google-genai, pandas, python-dotenv, ipykernel)
- Configures the environment for exfat filesystem compatibility

### Method 2: Manual Setup

If `setup.sh` is unavailable, install packages manually:

```bash
pip install google-genai ipykernel python-dotenv pandas --break-system-packages
```

**Note**: The `--break-system-packages` flag is required when not using a virtual environment. This is safe for this use case as packages are installed into the system Python but managed via pipx.

### Verify Installation

```bash
# Check JupyterLab
jupyter-lab --version

# Check Python packages
python -c "import google.genai; print('google-genai:', google.genai.__version__)"
python -c "import pandas; print('pandas:', pandas.__version__)"
python -c "import dotenv; print('python-dotenv: OK')"
```

### Cache Local RAG Models

After installing dependencies, cache the local ML models for offline operation:

```bash
python download_models.py
```

This downloads ~175 MB total into `models/`:
- `all-MiniLM-L6-v2` (~90 MB) — sentence embeddings for RAG vector search
- `cross-encoder-ms-marco-MiniLM-L-6-v2` (~90 MB) — cross-encoder reranker

**RAM usage**: ~700 MB - 1.1 GB when both models are loaded.

This step is optional but recommended — models will download automatically on first use if skipped.

## Configuration

### API Key Setup

1. Create a `.env` file in the project root:
```bash
touch .env
```

2. Add your Gemini API key:
```
GEMINI_API_KEY=your_api_key_here
```

3. Ensure `.env` is in `.gitignore` (it should already be there)

### Get a Gemini API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key and add to `.env`

## Running the Project

### Start JupyterLab

```bash
jupyter-lab
```

This will:
- Start the JupyterLab server
- Open a browser window (or provide a URL to open manually)
- Load the project directory

### Open the Notebook

1. In JupyterLab, navigate to `agnes.ipynb`
2. Run cells sequentially (Cell 1 → Cell 2 → ... → Cell 10)
3. Each cell should complete within 5-10 seconds
4. Total runtime: ~30 seconds for full pipeline

### Cell Execution Order

The notebook must be run in order as each cell depends on previous cells:

1. **Cell 1**: Environment setup (run first)
2. **Cell 2**: Database ingestion (depends on Cell 1)
3. **Cell 3**: Target selection (depends on Cell 2)
4. **Cell 4**: Compliance enrichment (depends on Cell 3)
5. **Cell 5**: LLM reasoning (depends on Cell 4)
6. **Cell 6**: Optimization (depends on Cell 5)
7. **Cell 7**: Final report (depends on Cell 6)
8. **Cell 8**: Trust scoring (independent, can run anytime)
9. **Cell 9**: Risk heat map (depends on Cell 2)
10. **Cell 10**: Disruption simulator (depends on Cell 2)

## Dependencies

### Core Dependencies

```
google-genai>=1.73.1
pandas>=2.0.0
python-dotenv>=1.0.0
ipykernel>=6.0.0
```

### Python Standard Library

```
sqlite3 (built-in)
json (built-in)
os (built-in)
random (built-in)
```

### Package Versions

The project uses:
- **google-genai**: 1.73.1 (NOT the older `google-generativeai`)
- **pandas**: Latest stable
- **python-dotenv**: Latest stable

### requirements.txt

```
google-genai>=1.73.1
pandas>=2.0.0
python-dotenv>=1.0.0
ipykernel>=6.0.0
jupyterlab>=4.0.0
```

## Common Pitfalls

### 1. Wrong Google Package

**Error**: `ImportError: cannot import name 'genai' from 'google'`

**Cause**: Installed the old `google-generativeai` package instead of the new `google-genai`.

**Solution**:
```bash
pip uninstall google-generativeai
pip install google-genai --break-system-packages
```

**Verification**:
```python
# Correct
from google import genai  # Works

# Incorrect
import google.generativeai as genai  # Wrong package
```

### 2. Missing API Key

**Error**: `API key loaded: NO — check .env`

**Cause**: `.env` file missing or `GEMINI_API_KEY` not set.

**Solution**:
```bash
# Check if .env exists
ls -la .env

# Check contents
cat .env

# Add API key if missing
echo "GEMINI_API_KEY=your_key_here" >> .env
```

### 3. Symlink Errors on exFAT

**Error**: `Operation not permitted` when running `python -m venv .venv`

**Cause**: exFAT filesystem does not support symlinks required by virtual environments.

**Solution**: Use pipx instead (already handled by setup.sh):
```bash
pipx install jupyterlab
pipx install google-genai
```

### 4. Database Not Found

**Error**: `sqlite3.OperationalError: unable to open database file`

**Cause**: Database path incorrect or file missing.

**Solution**:
```bash
# Check database exists
ls -la DB/db.sqlite

# Verify path in notebook
# In Cell 1, DB_PATH should be "DB/db.sqlite"
```

### 5. JSON Parse Errors

**Error**: `JSONDecodeError` in Cell 5

**Cause**: LLM returned malformed JSON (rare with structured output).

**Solution**: The code has fallback handling:
```python
try:
    result = json.loads(raw_text)
except json.JSONDecodeError as exc:
    result = {
        "substitutable": False,
        "confidence": 0.0,
        "recommendation": "HUMAN_REVIEW_REQUIRED",
        # ... safe fallback values
    }
```

## Recommended VS Code Extensions

### Essential Extensions

1. **Jupyter** (by Microsoft)
   - Run `.ipynb` files natively
   - Cell-by-cell execution
   - Variable inspection

2. **Python** (by Microsoft)
   - Intellisense
   - Linting (pylint)
   - Formatting (black)

3. **SQLite Viewer** (by alexcvzz)
   - View `DB/db.sqlite` tables directly
   - Execute SQL queries
   - Export data to CSV

### Installation

1. Open VS Code
2. Go to Extensions panel (Ctrl+Shift+X)
3. Search for extension name
4. Click "Install"

## Database Exploration

### Using explore_data.ipynb

The `explore_data.ipynb` notebook provides a starting point for database exploration:

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect('DB/db.sqlite')

# List all tables
tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", conn)
print(tables)

# Explore Company table
company_df = pd.read_sql_query("SELECT * FROM Company LIMIT 5;", conn)
print(company_df)

conn.close()
```

### Using SQLite Viewer Extension

1. Open `DB/db.sqlite` in VS Code
2. Click "Open with SQLite Viewer"
3. Browse tables visually
4. Write custom SQL queries in the query panel

### Using DB Browser for SQLite

1. Download from [sqlitebrowser.org](https://sqlitebrowser.org/)
2. Open `DB/db.sqlite`
3. Browse tables, execute queries, export data

## Modifying the Pipeline

### Changing the Target Ingredient

In **Cell 3**, modify the target variables:

```python
# Current target
TARGET_INGREDIENT = "vitamin-d3-cholecalciferol"
RELATED_INGREDIENT = "vitamin-d3"

# Change to different ingredient
TARGET_INGREDIENT = "maltodextrin"
RELATED_INGREDIENT = None  # If no related cluster
```

Then re-run Cells 3-7 to see results for the new ingredient.

### Adding New Compliance Data

In **Cell 4**, add to the `_COMPLIANCE_MOCK_DB` dictionary:

```python
_COMPLIANCE_MOCK_DB = {
    # Existing entries...
    
    # Add new entry
    ("New Supplier", "new-ingredient"): {
        "organic_certified": True,
        "fda_registered": True,
        "non_gmo": True,
        "grade": "pharmaceutical",
        "lead_time_days": 10,
        "certifications": ["USP", "GMP", "Kosher"],
        "notes": "Your notes here",
    },
}
```

### Adjusting Compliance Weights

In **Cell 6**, modify the `compute_compliance_weight` function:

```python
def compute_compliance_weight(compliance: dict) -> float:
    weight = 1.0
    
    # Adjust grade bonuses
    if compliance.get("grade") == "pharmaceutical":
        weight += 0.2  # Increase to 0.3 for more emphasis
    elif compliance.get("grade") == "technical":
        weight -= 0.3
    
    # Add new attributes
    if compliance.get("iso_certified"):
        weight += 0.05
    
    # Adjust certification bonus cap
    cert_bonus = min(0.40, len(compliance.get("certifications", [])) * 0.05)
    weight += cert_bonus
    
    return round(max(0.1, weight), 3)
```

### Modifying the LLM System Prompt

In **Cell 5**, edit the `AGNES_SYSTEM_PROMPT` variable:

```python
AGNES_SYSTEM_PROMPT = """You are Agnes, an AI supply chain reasoning agent...

# Add new rules
- Consider geographic location of suppliers
- Factor in sustainability certifications
- Evaluate total cost of ownership, not just unit price

# Modify existing rules
- Confidence scores: 0.95+ = high certainty (increased from 0.9+)
"""
```

### Adding a New Cell

1. In JupyterLab, click "+" to add a new cell
2. Choose "Code" or "Markdown"
3. Write your code
4. Run with Shift+Enter

**Example**: Add a cell to calculate cost savings:

```python
# New cell after Cell 6
def estimate_savings(df_recommendation):
    """Estimate potential cost savings from consolidation."""
    total_bom = df_recommendation["bom_appearances_covered"].sum()
    # Assume 5% savings per consolidated BOM
    estimated_savings = total_bom * 0.05 * 1000  # $1000 per BOM
    return estimated_savings

savings = estimate_savings(df_recommendation)
print(f"Estimated annual savings: ${savings:,.0f}")
```

### Extending to Multiple Ingredients

To analyze all 143 ingredients instead of just one:

```python
# New cell after Cell 9
results = []

for ingredient in df_risk["ingredient_name"].head(20):  # Start with top 20
    # Run Cells 3-7 logic for each ingredient
    # Store results in list
    results.append({
        "ingredient": ingredient,
        "recommendation": "...",
        "savings": "...",
    })

# Convert to DataFrame
df_all_results = pd.DataFrame(results)
display(df_all_results)
```

## Debugging

### Enable Verbose Output

Add print statements throughout the pipeline:

```python
# In Cell 2
print(f"Loaded {len(df_fragmented)} fragmented ingredients")
print(f"Columns: {df_fragmented.columns.tolist()}")

# In Cell 5
print(f"Sending prompt to Gemini: {len(user_message)} characters")
print(f"Response: {response.text[:200]}...")  # First 200 chars
```

### Check Intermediate Data

After each cell, inspect the DataFrames:

```python
# After Cell 2
print(df_fragmented.head())
print(df_supplier_coverage.head())

# After Cell 5
print(eval_within_cluster)
print(eval_cross_cluster)
```

### Test LLM Connection

Isolated test of Gemini API:

```python
from google import genai
from dotenv import load_dotenv
import os

load_dotenv()
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-flash-latest",
    contents="Say hello in JSON format",
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
    ),
)
print(response.text)
```

## Performance Optimization

### Caching LLM Results

For repeated runs, cache LLM responses:

```python
import hashlib
import json

def get_cache_key(ingredient_a, supplier_a, ingredient_b, supplier_b):
    key = f"{ingredient_a}_{supplier_a}_{ingredient_b}_{supplier_b}"
    return hashlib.md5(key.encode()).hexdigest()

# Check cache before calling LLM
cache_key = get_cache_key(ingredient_a, supplier_a, ingredient_b, supplier_b)
if cache_key in llm_cache:
    result = llm_cache[cache_key]
else:
    result = evaluate_substitutability(...)
    llm_cache[cache_key] = result
```

### Parallel Processing

For analyzing multiple ingredients:

```python
from concurrent.futures import ThreadPoolExecutor

def analyze_ingredient(ingredient):
    # Run analysis for one ingredient
    return result

ingredients = df_risk["ingredient_name"].head(10).tolist()

with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(analyze_ingredient, ingredients))
```

### Database Query Optimization

Add indexes to improve query performance:

```sql
-- In SQLite
CREATE INDEX idx_product_type ON Product(Type);
CREATE INDEX idx_bom_component_bomid ON BOM_Component(BOMId);
CREATE INDEX idx_supplier_product_productid ON Supplier_Product(ProductId);
```

## Testing

### Unit Tests

Create test functions for key components:

```python
# test_agnes.py
import unittest

class TestComplianceWeight(unittest.TestCase):
    def test_pharmaceutical_grade(self):
        compliance = {"grade": "pharmaceutical", "fda_registered": True}
        weight = compute_compliance_weight(compliance)
        self.assertEqual(weight, 1.3)  # 1.0 + 0.2 + 0.1
    
    def test_technical_grade(self):
        compliance = {"grade": "technical", "fda_registered": True}
        weight = compute_compliance_weight(compliance)
        self.assertEqual(weight, 0.8)  # 1.0 - 0.3 + 0.1

if __name__ == "__main__":
    unittest.main()
```

### Integration Tests

Test the full pipeline with known inputs:

```python
def test_full_pipeline():
    # Run all cells
    # Check outputs match expectations
    assert len(df_fragmented) == 143
    assert eval_within_cluster["recommendation"] in ["APPROVE", "REJECT", "HUMAN_REVIEW_REQUIRED"]
```

## Deployment

### Export to Python Script

Convert notebook to executable script:

```bash
jupyter nbconvert --to script agnes.ipynb
```

This creates `agnes.py` that can be run directly:

```bash
python agnes.py
```

### Docker Container

Create `Dockerfile`:

```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
```

Build and run:

```bash
docker build -t agnes .
docker run -p 8888:8888 -v $(pwd):/app agnes
```

### Cloud Deployment

For production deployment to cloud platforms (AWS, GCP, Azure):

1. Containerize the application
2. Use managed Jupyter services (SageMaker, Vertex AI)
3. Set up API endpoints for programmatic access
4. Configure monitoring and logging

## Troubleshooting

### Issue: Notebook Won't Open

**Symptoms**: JupyterLab starts but notebook shows error

**Solution**:
```bash
# Check kernel
jupyter kernelspec list

# Reinstall kernel
python -m ipykernel install --user --name=agnes
```

### Issue: Out of Memory

**Symptoms**: Kernel dies during execution

**Solution**:
- Reduce data loaded in queries (add LIMIT clauses)
- Process ingredients in batches
- Increase system RAM or use cloud instance

### Issue: Slow LLM Response

**Symptoms**: Cell 5 takes > 30 seconds

**Solution**:
- Check internet connection
- Try different Gemini model (gemini-1.5-flash vs gemini-1.5-pro)
- Reduce prompt length
- Enable caching for repeated runs

### Issue: All LLM Calls Retrying

**Symptoms**: Every evaluation shows `healing_applied: True` with 3 retry attempts

**Solution**:
- Check API key validity: `cat .env | grep GEMINI`
- Verify internet connectivity: `ping google.com`
- Check Google AI Studio status and rate limits
- Review error messages in Cell 5 output

### Issue: Monitoring Log Not Created

**Symptoms**: `agnes_monitoring_log.json` missing after running Cell 5.5

**Solution**:
- Check write permissions: `ls -la .` (should show write permission)
- Verify Cell 5.5 ran successfully
- Check disk space: `df -h`
- Try manual save: Run `monitor.save_to_disk()` in a new cell

### Issue: Executive Summary Falls Back

**Symptoms**: Cell 7.5 shows "⚠ Note: Generated using fallback"

**Solution**:
- Verify Cells 5 and 7 ran successfully first
- Check that `df_recommendation` is not empty
- Review API key and connectivity
- Check if evaluation results exist: `print(eval_within_cluster.keys())`

---

## Self-Maintenance Implementation Details

### Self-Healing Configuration

**Parameters** (in Cell 5):
```python
max_retries = 3              # Number of retry attempts
temperatures = [0.2, 0.1, 0.3]  # Temperature per attempt
sleep_base = 1               # Base for exponential backoff (2^attempt seconds)
```

**Adjusting Retry Behavior**:
```python
# More aggressive retry (5 attempts)
eval_result = evaluate_substitutability_with_healing(
    ..., max_retries=5
)

# Disable healing (direct call)
eval_result = evaluate_substitutability(...)  # No retry logic
```

### Self-Monitoring Configuration

**Parameters** (in Cell 5.5, `AgnesMonitor` class):
```python
LOG_FILE = "agnes_monitoring_log.json"  # Log filename
LOW_CONFIDENCE_THRESHOLD = 0.7        # Warning threshold
```

**Adjusting Threshold**:
```python
monitor = AgnesMonitor()
monitor.LOW_CONFIDENCE_THRESHOLD = 0.8  # Stricter
monitor.LOW_CONFIDENCE_THRESHOLD = 0.6  # More lenient
```

**Log File Schema**:
```json
{
  "last_updated": "2026-04-18T11:30:00",
  "current_session": "2026-04-18T11:10:00",
  "evaluations": [
    {
      "timestamp": "2026-04-18T11:15:30",
      "session": "2026-04-18T11:10:00",
      "confidence": 0.95,
      "recommendation": "REJECT",
      "retry_attempt": 1,
      "healing_applied": false,
      ...
    }
  ]
}
```

### Self-Explanation Configuration

**Parameters** (in Cell 7.5):
```python
temperature = 0.3  # Higher = more creative, Lower = more deterministic
model = "gemini-flash-latest"  # Can use gemini-1.5-pro for longer outputs
```

### Integration Points

**Data Flow Between Cells**:
```
Cell 5 (LLM) 
  → produces eval_within_cluster, eval_cross_cluster
  → used by Cell 5.5 (monitor.record())
  → used by Cell 6 (consolidation)
  → used by Cell 7 (report)
  → used by Cell 7.5 (generate_executive_summary())
```

**Monitoring Log Lifecycle**:
1. Cell 5.5: Initialize monitor → Load existing log
2. Cell 5.5: Record evaluations → Append to evaluations list
3. Cell 5.5: Save to disk → Write JSON file
4. Next run: Load accumulated history

---

## Related Documents

- `Project_Overview.md` - High-level project introduction
- `Database_Complete_Guide.md` - Database schema and relationships
- `Agnes_Pipeline_Architecture.md` - Technical pipeline documentation
- `Agnes_2.0_Improvements.md` - Enhancements over original concept
- `Self_Maintenance.md` - Detailed guide on self-healing, monitoring, explanation
- `Business_Value.md` - ROI analysis and case studies
