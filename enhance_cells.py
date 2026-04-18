"""
enhance_cells.py — Injects three enhancement cells into agnes.ipynb.

Run once:
    python enhance_cells.py

Idempotent: checks for marker cell IDs before inserting.

Enhancements added:
  1. Cell 4.M   — Multimodal CoA Extraction (Gemini Vision)
  2. Cell 4.5-EMB — Ingredient Joint Embeddings & Semantic Similarity
  3. Cell 10-OR  — Bipartite Matching / ILP Optimal Disruption Rerouting
"""

import json
from pathlib import Path

NB_PATH = Path("agnes.ipynb")

# ── Helpers ──────────────────────────────────────────────────────────────────

def make_code_cell(source: str, cell_id: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cell_id,
        "metadata": {},
        "outputs": [],
        "source": source,
    }


def make_markdown_cell(source: str, cell_id: str) -> dict:
    return {
        "cell_type": "markdown",
        "id": cell_id,
        "metadata": {},
        "source": source,
    }


def find_cell_index(cells: list, cell_id: str) -> int | None:
    for i, c in enumerate(cells):
        if c.get("id") == cell_id:
            return i
    return None


def find_cell_index_by_marker(cells: list, marker: str) -> int | None:
    for i, c in enumerate(cells):
        src = "".join(c.get("source", []))
        if marker in src:
            return i
    return None


# ─────────────────────────────────────────────────────────────────────────────
# CELL 4.M — Multimodal CoA Extraction
# ─────────────────────────────────────────────────────────────────────────────

CELL_4M_MARKDOWN = """\
## 📸 Multimodal CoA Extraction *(Agnes 2.0 — new)*

Demonstrates **Vision-Language Model (VLM) document parsing**: Gemini Flash (multimodal) reads a synthetic Certificate of Analysis image and extracts structured compliance data — the production replacement for the mock `scrape_supplier_compliance()` in Cell 4.

**Three multimodal concepts demonstrated:**
- **Joint Embedding concept** — image and text mapped to the same structured output schema
- **Input handling** — PIL PNG bytes → `types.Part.from_bytes()` → Gemini multimodal API
- **VLM extraction** — visual tokens → structured JSON matching the compliance dict schema

In production Agnes would: download CoA PDFs from supplier portals, convert via `pdf2image`, and replace all mock data automatically.

**Key outputs:** `vlm_compliance` — extracted compliance dict comparable to `scrape_supplier_compliance()`
"""

CELL_4M_CODE = r'''# ─────────────────────────────────────────────────────────────
# CELL 4.M — Multimodal CoA Extraction (Gemini Vision)
# ─────────────────────────────────────────────────────────────
# Demonstrates Vision-Language Model (VLM) document parsing:
# Gemini Flash reads a Certificate of Analysis image and extracts
# the same structured compliance schema used by Cell 4's mock.
#
# Multimodal concepts applied:
#   1. Joint Embeddings  — image + extraction prompt → shared schema space
#   2. Input Handling    — PIL image bytes → base64 → Gemini Part
#   3. VLM Extraction    — visual tokens → structured JSON output
#
# Production path:
#   Supplier CoA PDF → pdf2image → PIL.Image → Gemini Flash Vision
#   → structured compliance dict → replaces mock DB entirely
# ─────────────────────────────────────────────────────────────

import io
import json as _json

print("=" * 70)
print("  CELL 4.M: MULTIMODAL CoA EXTRACTION — GEMINI VISION")
print("=" * 70)

# ── Step 1: Create a synthetic Certificate of Analysis image ─────────────
# In production this would be a real CoA PDF converted to image bytes.
# We synthesise a realistic PureBulk CoA to demonstrate the pipeline.

COA_TEXT_LINES = [
    "CERTIFICATE OF ANALYSIS",
    "",
    "Supplier          : PureBulk, Inc.",
    "Product           : Vitamin D3 (Cholecalciferol) Powder 1% SD",
    "Lot Number        : PB-VD3-2026-0418",
    "Grade             : Pharmaceutical Grade",
    "",
    "Specification Results",
    "  Appearance      : White to off-white powder",
    "  Assay (HPLC)    : 101.2%   (Spec: 95.0-105.0%)",
    "  Heavy Metals    : <10 ppm  (USP <231>)",
    "  Microbial Count : <100 cfu/g",
    "",
    "Certifications",
    "  GMP Certified   : Yes (NSF GMP Certificate #GMP-052981)",
    "  Kosher           : Yes (OK Kosher #OKK-2026)",
    "  Halal            : Not certified",
    "  USP Verified     : Not certified",
    "  Non-GMO          : Yes (statement on file)",
    "  FDA Registration : 3014836",
    "",
    "Logistics",
    "  Typical Lead Time : 7 business days",
    "  Storage           : Store below 25 degrees C, away from light",
    "",
    "Authorised by: QA Manager, PureBulk Inc.    Date: 2026-04-18",
]

img_bytes = None
coa_source = "text_fallback"

try:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (720, 560), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18
        )
        font_body = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13
        )
    except OSError:
        font_title = ImageFont.load_default()
        font_body  = ImageFont.load_default()

    y = 20
    for i, line in enumerate(COA_TEXT_LINES):
        font = font_title if i == 0 else font_body
        draw.text((30, y), line, fill=(0, 0, 0), font=font)
        y += 22 if i == 0 else 16

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()
    coa_source = "synthetic_PIL"
    print(f"  Synthetic CoA image  : {len(img_bytes):,} bytes  (PIL PNG)")

except ImportError:
    coa_source = "text_fallback"
    print("  PIL not installed — using text-encoded CoA (same extraction path)")

if img_bytes is None:
    img_bytes = "\n".join(COA_TEXT_LINES).encode("utf-8")
    print(f"  Text-encoded CoA     : {len(img_bytes):,} bytes")

# ── Step 2: Build structured extraction prompt ────────────────────────────
EXTRACTION_SCHEMA = """{
  "organic_certified" : <bool>,
  "fda_registered"    : <bool>,
  "non_gmo"           : <bool>,
  "grade"             : "<pharmaceutical | food | technical>",
  "lead_time_days"    : <int>,
  "certifications"    : ["<cert_name>", ...],
  "notes"             : "<one sentence summary of key compliance points>"
}"""

EXTRACTION_PROMPT = f"""You are a supply chain compliance extraction agent.
Read the Certificate of Analysis (CoA) document provided and extract ONLY
the following fields into valid JSON — no extra keys:

{EXTRACTION_SCHEMA}

Extraction rules:
- grade        : "pharmaceutical" if document states pharmaceutical grade, else "food" or "technical"
- certifications: list ONLY third-party certifications with explicit evidence
                  (GMP, USP, NSF, Halal, Kosher, ISO, Organic, Non-GMO Project, etc.)
- fda_registered: true if an FDA facility registration number is present
- non_gmo      : true if a Non-GMO statement or certification is mentioned
- lead_time_days: parse integer from lead time text; use 14 if not found
- notes        : one sentence summarising the most important compliance points

Respond with valid JSON only — no markdown fences, no explanation."""

# ── Step 3: Call Gemini Flash (multimodal) ────────────────────────────────
vlm_compliance = None
vision_response = None

try:
    if coa_source == "synthetic_PIL":
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
    else:
        image_part = types.Part.from_bytes(data=img_bytes, mime_type="text/plain")

    print("\n  Sending CoA to Gemini Flash (multimodal) ...")
    vision_response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=[image_part, EXTRACTION_PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )
    vlm_compliance = _json.loads(vision_response.text.strip())
    vlm_compliance["_source"] = coa_source
    print("  Extraction complete\n")

except Exception as exc:
    print(f"  Vision extraction failed ({exc}) — using mock fallback\n")
    vlm_compliance = dict(scrape_supplier_compliance("PureBulk", TARGET_INGREDIENT))
    vlm_compliance["_source"] = "mock_fallback"

# ── Step 4: Compare VLM extraction vs. mock baseline ─────────────────────
mock_compliance = scrape_supplier_compliance("PureBulk", TARGET_INGREDIENT)

print("  COMPARISON: VLM Extraction vs. Mock Baseline")
print("  " + "-" * 66)
print(f"  {'Field':<22}  {'VLM Extracted':<32}  {'Mock Baseline'}")
print("  " + "-" * 66)

for key in ["grade", "fda_registered", "non_gmo", "organic_certified",
            "lead_time_days", "certifications"]:
    vlm_val  = str(vlm_compliance.get(key, "—"))
    mock_val = str(mock_compliance.get(key, "—"))
    match = "=" if vlm_val == mock_val else "~"
    print(f"  {match}  {key:<20}  {vlm_val:<32}  {mock_val}")

print(f"\n  VLM notes      : {vlm_compliance.get('notes', '—')}")
if vision_response is not None:
    print(f"  Tokens used    : {vision_response.usage_metadata.prompt_token_count} in"
          f" / {vision_response.usage_metadata.candidates_token_count} out")

print("\n" + "=" * 70)
print("  Production path: CoA PDF -> pdf2image -> PIL -> Gemini Vision")
print("  -> structured JSON -> replaces all mock compliance data")
print("=" * 70)
'''

# ─────────────────────────────────────────────────────────────────────────────
# CELL 4.5-EMB — Ingredient Joint Embeddings
# ─────────────────────────────────────────────────────────────────────────────

CELL_45EMB_MARKDOWN = """\
## 🔗 Ingredient Joint Embeddings *(Agnes 2.0 — new)*

Uses the embedding model already loaded in Cell 4.5 to build a **cosine similarity matrix** over all 143 fragmented ingredient names — discovering semantic substitution candidates that exact-name matching misses.

**Why this matters:** Agnes currently groups ingredients by parsed SKU name. Two ingredients with different names but the same molecular function (e.g. `calcium-carbonate` ↔ `calcium-citrate`) are invisible to the current pipeline. Joint embeddings surface these candidates automatically.

**Key outputs:**
- `df_emb_pairs` — all high-similarity pairs (cosine ≥ 0.80) as cross-cluster substitution candidates
- `sim_matrix` — full 143×143 cosine similarity matrix for downstream use
"""

CELL_45EMB_CODE = r"""# ─────────────────────────────────────────────────────────────
# CELL 4.5-EMB — Ingredient Joint Embeddings & Semantic Similarity
# ─────────────────────────────────────────────────────────────
# Uses rag_index.embedding_model (all-MiniLM-L6-v2, already loaded
# in Cell 4.5) to compute pairwise cosine similarity over all 143
# ingredient names.
#
# Joint embedding concept:
#   Each ingredient name is mapped to a 384-dim vector.
#   Cosine similarity between two vectors reflects how semantically
#   similar the two names are in the model's learned space.
#   High similarity (>=0.80) = candidate cross-cluster substitute.
#
# This extends Agnes from name-based to semantic clustering:
#   "vitamin-d3" <-> "vitamin-d3-cholecalciferol"   (same molecule)
#   "calcium-carbonate" <-> "calcium-citrate"         (functional family)
#   "magnesium-stearate" <-> "stearic-acid"           (overlapping chem)
#
# No new dependencies — reuses rag_index.embedding_model from Cell 4.5.
# ─────────────────────────────────────────────────────────────

import numpy as np
import pandas as pd

print("=" * 70)
print("  CELL 4.5-EMB: INGREDIENT JOINT EMBEDDINGS")
print("=" * 70)

# ── Step 1: Collect all 143 ingredient names ──────────────────────────────
ingredient_names = sorted(df_fragmented["ingredient_name"].unique().tolist())
print(f"\n  Encoding {len(ingredient_names)} ingredient names ...")

embeddings = rag_index.embedding_model.encode(
    ingredient_names,
    normalize_embeddings=True,
    show_progress_bar=False,
)
print(f"  Embedding shape    : {embeddings.shape}  ({embeddings.shape[1]}-dim per name)")
print(f"  Embedding model    : all-MiniLM-L6-v2 (reused from Cell 4.5)")

# ── Step 2: Cosine similarity matrix (dot product of L2-norm vectors) ────
sim_matrix = np.dot(embeddings, embeddings.T)   # shape: (143, 143)

# ── Step 3: Extract high-similarity pairs (exclude self-similarity) ───────
SIMILARITY_THRESHOLD = 0.80
pairs = []
n = len(ingredient_names)
for i in range(n):
    for j in range(i + 1, n):
        score = float(sim_matrix[i, j])
        if score >= SIMILARITY_THRESHOLD:
            # Look up BOM volumes for context
            bom_a = int(
                df_fragmented[df_fragmented["ingredient_name"] == ingredient_names[i]]
                ["bom_appearances"].sum()
            )
            bom_b = int(
                df_fragmented[df_fragmented["ingredient_name"] == ingredient_names[j]]
                ["bom_appearances"].sum()
            )
            pairs.append({
                "ingredient_a":       ingredient_names[i],
                "ingredient_b":       ingredient_names[j],
                "cosine_similarity":  round(score, 4),
                "combined_bom_value": bom_a + bom_b,
            })

pairs.sort(key=lambda x: x["cosine_similarity"], reverse=True)
df_emb_pairs = pd.DataFrame(pairs)

print(f"\n  Pairs with cosine similarity >= {SIMILARITY_THRESHOLD} : {len(pairs)}")
print(f"  These are candidate cross-cluster substitution pairs")
print(f"  (eligible inputs for evaluate_substitutability_rag in Cell 5)\n")

if not df_emb_pairs.empty:
    display(
        df_emb_pairs.head(20).reset_index(drop=True).rename(columns={
            "ingredient_a":       "Ingredient A",
            "ingredient_b":       "Ingredient B",
            "cosine_similarity":  "Cosine Similarity",
            "combined_bom_value": "Combined BOM Value",
        })
    )
else:
    print("  No pairs found above threshold.")

# ── Step 4: Vitamin D family cluster (detailed) ───────────────────────────
print("\n  Vitamin D family — pairwise similarities:")
print("  " + "-" * 70)
vd_names = [n for n in ingredient_names if "vitamin-d" in n or "cholecalciferol" in n]
if vd_names:
    for i_a, name_a in enumerate(vd_names):
        for name_b in vd_names[i_a + 1:]:
            ia = ingredient_names.index(name_a)
            ib = ingredient_names.index(name_b)
            sim = float(sim_matrix[ia, ib])
            verdict = "HIGH" if sim >= 0.80 else ("MED" if sim >= 0.60 else "LOW")
            print(f"  [{verdict}]  {name_a:40s}  <->  {name_b}  sim={sim:.4f}")
else:
    print("  No vitamin-D ingredients found.")

print(f"\n  Summary:")
print(f"    {len(ingredient_names)} ingredients encoded, {len(pairs)} high-similarity pairs found")
print(f"    Top candidate: {pairs[0]['ingredient_a'] if pairs else 'N/A'}"
      f" <-> {pairs[0]['ingredient_b'] if pairs else 'N/A'}"
      f" (sim={pairs[0]['cosine_similarity'] if pairs else 0:.4f})")
print(f"\n  These pairs are stored in df_emb_pairs for use in the executive dashboard.")
print("=" * 70)
"""

# ─────────────────────────────────────────────────────────────────────────────
# CELL 10-OR — Bipartite Matching / ILP Optimal Rerouting
# ─────────────────────────────────────────────────────────────────────────────

CELL_10OR_MARKDOWN = """\
## 🔗 Bipartite Matching — Optimal Disruption Rerouting *(OR Enhancement)*

Upgrades Cell 10's greedy rerouting with the **Hungarian Algorithm** (`scipy.optimize.linear_sum_assignment`) extended with capacity-aware supplier slots. When a supplier fails, greedy lookup assigns each ingredient to the locally cheapest backup independently — ignoring the fact that multiple ingredients competing for the same high-quality supplier drives up effective cost.

**Bipartite matching approach:**
- Rows = top-20 affected ingredients; Columns = supplier slots (5 backup suppliers × 4 capacity slots each)
- Cost per cell = `lead_time_norm × (1 − compliance_weight)` (lower = better)
- Infeasible edges (no coverage) get cost = `1e6`
- `linear_sum_assignment` finds the globally optimal 20×20 assignment in O(n³)

**Key outputs:**
- `df_bipartite` — ingredient → supplier optimal assignment vs. greedy
- Total cost reduction percentage from optimal vs. independent greedy
"""

CELL_10OR_CODE = r"""# ─────────────────────────────────────────────────────────────
# CELL 10-OR — Bipartite Matching: Optimal Disruption Rerouting
# ─────────────────────────────────────────────────────────────
# Upgrades the greedy per-ingredient rerouting in Cell 10 with
# the Hungarian algorithm (scipy.optimize.linear_sum_assignment).
#
# Problem framing:
#   When Prinova USA fails, 20+ ingredients need rerouting.
#   Greedy picks the cheapest backup for each ingredient separately.
#   This ignores global supply balance — multiple critical ingredients
#   all routing to the same single best supplier is not resilient.
#
#   Hungarian algorithm: builds a capacity-aware cost matrix and finds
#   the globally optimal ingredient→supplier assignment in O(n^3).
#
# Cost matrix construction:
#   Rows    = top-20 most affected ingredients
#   Columns = 5 backup suppliers × CAPACITY slots each (20 total)
#   cost[i,j] = lead_time_norm × (1 - compliance_weight)
#               (lower = better; 1e6 = no coverage / infeasible)
#
# Capacity slots: each supplier can serve up to CAPACITY ingredients.
# This is the key extension vs. raw bipartite — it prevents one
# supplier from being over-assigned when alternatives exist.
# ─────────────────────────────────────────────────────────────

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

print("=" * 70)
print("  CELL 10-OR: BIPARTITE MATCHING — OPTIMAL DISRUPTION REROUTING")
print("=" * 70)

FAILED_SUPPLIER = "Prinova USA"
N_INGREDIENTS   = 20    # top-N ingredients by BOM at risk
N_TOP_SUPPLIERS = 5     # backup suppliers to include in matching
CAPACITY        = 4     # max ingredients per backup supplier slot

# ── Step 1: Top affected ingredients ──────────────────────────────────────
affected = (
    df_supplier_coverage[df_supplier_coverage["supplier_name"] == FAILED_SUPPLIER]
    .groupby("ingredient_name")
    .agg(
        bom_at_risk      = ("bom_appearances", "sum"),
        companies_at_risk = ("company_name",    "nunique"),
    )
    .sort_values("bom_at_risk", ascending=False)
    .head(N_INGREDIENTS)
    .reset_index()
)
ingredients = affected["ingredient_name"].tolist()

# ── Step 2: Top-5 backup suppliers (by breadth of coverage) ──────────────
backup_sups = (
    df_supplier_coverage[df_supplier_coverage["supplier_name"] != FAILED_SUPPLIER]
    .groupby("supplier_name")["ingredient_name"]
    .nunique()
    .sort_values(ascending=False)
    .head(N_TOP_SUPPLIERS)
    .index.tolist()
)

print(f"\n  Failed supplier       : {FAILED_SUPPLIER}")
print(f"  Ingredients (top-{N_INGREDIENTS})   : {len(ingredients)}")
print(f"  Backup suppliers      : {N_TOP_SUPPLIERS}  ({', '.join(backup_sups)})")
print(f"  Capacity per supplier : {CAPACITY} ingredient slots each")
print(f"  Cost matrix shape     : {len(ingredients)} x {N_TOP_SUPPLIERS * CAPACITY}")

# ── Step 3: Build 20x20 capacity-expanded cost matrix ────────────────────
INFEASIBLE = 1e6

# Coverage lookup: which ingredients each backup supplier can serve
backup_coverage: dict[str, set] = {
    s: set(
        df_supplier_coverage[df_supplier_coverage["supplier_name"] == s]["ingredient_name"]
    )
    for s in backup_sups
}

# Precompute lead time range for normalisation
all_leads = [scrape_supplier_compliance(s, ingredients[0])["lead_time_days"]
             for s in backup_sups]
max_lead = max(all_leads) or 1.0

# Base cost matrix: N_INGREDIENTS × N_TOP_SUPPLIERS
base_cost = np.full((len(ingredients), N_TOP_SUPPLIERS), INFEASIBLE)

for j, sup in enumerate(backup_sups):
    for i, ing in enumerate(ingredients):
        if ing in backup_coverage[sup]:
            prof      = scrape_supplier_compliance(sup, ing)
            lead_norm = prof["lead_time_days"] / max_lead
            comp_w    = compute_compliance_weight(prof)
            # Normalise comp_w to [0,1] range (max observed ~1.8)
            comp_norm = min(comp_w / 1.8, 1.0)
            base_cost[i, j] = round(lead_norm * (1.0 - comp_norm), 6)

# Expand to capacity-aware 20x20 matrix by duplicating supplier columns
# Each supplier gets CAPACITY independent "slots" — same cost per slot
# Small epsilon distinguishes slots so the solver distributes assignments
epsilon = np.zeros((len(ingredients), N_TOP_SUPPLIERS * CAPACITY))
for k in range(CAPACITY):
    slot_start = k * N_TOP_SUPPLIERS
    epsilon[:, slot_start:slot_start + N_TOP_SUPPLIERS] = base_cost + (k * 1e-8)

cost_matrix = epsilon
n_rows, n_cols = cost_matrix.shape

# ── Step 4: Hungarian algorithm ───────────────────────────────────────────
row_ind, col_ind = linear_sum_assignment(cost_matrix)

# Map column indices back to supplier names
def col_to_supplier(col_idx: int) -> str:
    return backup_sups[col_idx % N_TOP_SUPPLIERS]

# ── Step 5: Greedy baseline ───────────────────────────────────────────────
greedy_results = []
for i, ing in enumerate(ingredients):
    costs = [(j, base_cost[i, j]) for j in range(N_TOP_SUPPLIERS)]
    costs.sort(key=lambda x: x[1])
    if costs and costs[0][1] < INFEASIBLE:
        greedy_results.append((ing, backup_sups[costs[0][0]], costs[0][1]))
    else:
        greedy_results.append((ing, "UNASSIGNED", INFEASIBLE))

# ── Step 6: Build comparison table ────────────────────────────────────────
records = []
total_greedy_cost   = 0.0
total_optimal_cost  = 0.0

for rank_pos, i in enumerate(row_ind):
    ing         = ingredients[i]
    bom_risk    = int(affected.loc[i, "bom_at_risk"])
    opt_sup     = col_to_supplier(col_ind[rank_pos])
    opt_cost    = float(cost_matrix[i, col_ind[rank_pos]])

    _, grd_sup, grd_cost = greedy_results[i]

    if opt_cost < INFEASIBLE:
        total_optimal_cost += opt_cost
    if grd_cost < INFEASIBLE:
        total_greedy_cost  += grd_cost

    records.append({
        "ingredient":       ing,
        "bom_at_risk":      bom_risk,
        "greedy_supplier":  grd_sup,
        "optimal_supplier": opt_sup,
        "greedy_cost":      round(grd_cost, 4) if grd_cost < INFEASIBLE else "—",
        "optimal_cost":     round(opt_cost, 4) if opt_cost < INFEASIBLE else "—",
        "diff":             "CHANGED" if grd_sup != opt_sup else "same",
    })

df_bipartite = pd.DataFrame(records).sort_values("bom_at_risk", ascending=False)

print("\n  OPTIMAL vs GREEDY ASSIGNMENT:")
display(df_bipartite.reset_index(drop=True))

# ── Step 7: Summary ───────────────────────────────────────────────────────
improvement_pct = (
    (total_greedy_cost - total_optimal_cost) / total_greedy_cost * 100
    if total_greedy_cost > 0 else 0.0
)
changed = (df_bipartite["diff"] == "CHANGED").sum()

# Count how many ingredients each supplier received
opt_dist = df_bipartite["optimal_supplier"].value_counts()

print("\n  Optimal supplier load distribution:")
for sup, count in opt_dist.items():
    print(f"    {sup:<30}  {count} ingredient(s)")

print(f"\n  Total greedy cost    : {total_greedy_cost:.4f}")
print(f"  Total optimal cost   : {total_optimal_cost:.4f}")
print(f"  Cost reduction       : {improvement_pct:.2f}%")
print(f"  Assignments changed  : {changed} / {len(ingredients)}")
print(f"\n  Hungarian algorithm: O(n^3) guaranteed globally optimal assignment.")
print(f"  Capacity slots ({CAPACITY} per supplier) prevent single-supplier overload,")
print(f"  ensuring resilient distribution across backup sources.")
print("\n" + "=" * 70)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Main patching logic
# ─────────────────────────────────────────────────────────────────────────────

def patch():
    with open(NB_PATH, encoding="utf-8") as f:
        nb = json.load(f)
    cells = nb["cells"]

    # ── Idempotency guards ────────────────────────────────────────────────
    marker_ids = {"code4multimodal", "code45embeddings", "code10or"}
    existing_ids = {c.get("id") for c in cells}
    already_done = marker_ids & existing_ids

    if already_done:
        print(f"Already patched — found cell IDs: {already_done}. Aborting.")
        return

    # ── Locate anchor cells ───────────────────────────────────────────────
    idx_cell4      = find_cell_index(cells, "7fa32050")   # CELL 4
    idx_rag045     = find_cell_index(cells, "rag045cell") # CELL 4.5
    idx_cell10     = find_cell_index(cells, "ab1bb18f")   # CELL 10

    missing = []
    if idx_cell4  is None: missing.append("Cell 4  (id=7fa32050)")
    if idx_rag045 is None: missing.append("Cell 4.5 (id=rag045cell)")
    if idx_cell10 is None: missing.append("Cell 10 (id=ab1bb18f)")
    if missing:
        print(f"ERROR: Could not find anchor cells: {missing}")
        return

    print(f"  Cell 4     at index {idx_cell4}")
    print(f"  Cell 4.5   at index {idx_rag045}")
    print(f"  Cell 10    at index {idx_cell10}")

    # ── Insert in REVERSE notebook order to avoid index shifting ─────────
    # (Insert Cell 10-OR first, then 4.5-EMB, then 4.M)

    # 1. Cell 10-OR: insert after Cell 10
    cells.insert(idx_cell10 + 1, make_markdown_cell(CELL_10OR_MARKDOWN, "md10or"))
    cells.insert(idx_cell10 + 2, make_code_cell(CELL_10OR_CODE, "code10or"))
    print(f"  Inserted Cell 10-OR at indices {idx_cell10 + 1}-{idx_cell10 + 2}")

    # 2. Cell 4.5-EMB: insert after Cell 4.5
    #    (idx_rag045 is unchanged since we inserted after it)
    cells.insert(idx_rag045 + 1, make_markdown_cell(CELL_45EMB_MARKDOWN, "md45emb"))
    cells.insert(idx_rag045 + 2, make_code_cell(CELL_45EMB_CODE, "code45embeddings"))
    print(f"  Inserted Cell 4.5-EMB at indices {idx_rag045 + 1}-{idx_rag045 + 2}")

    # 3. Cell 4.M: insert after Cell 4 (before the RAG markdown at idx_rag045)
    #    idx_cell4 unchanged (all our insertions were at higher indices)
    cells.insert(idx_cell4 + 1, make_markdown_cell(CELL_4M_MARKDOWN, "md4multimodal"))
    cells.insert(idx_cell4 + 2, make_code_cell(CELL_4M_CODE, "code4multimodal"))
    print(f"  Inserted Cell 4.M at indices {idx_cell4 + 1}-{idx_cell4 + 2}")

    # ── Save ──────────────────────────────────────────────────────────────
    with open(NB_PATH, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1, ensure_ascii=False)

    print(f"\nNotebook patched and saved: {NB_PATH}")
    print(f"  Total cells now: {len(cells)}")
    print("\nNew cells added:")
    print("  [Cell 4.M]     code4multimodal  — Multimodal CoA Extraction")
    print("  [Cell 4.5-EMB] code45embeddings — Ingredient Joint Embeddings")
    print("  [Cell 10-OR]   code10or          — Bipartite Matching Rerouting")


if __name__ == "__main__":
    print("Agnes Cell Enhancer — Multimodal + Embeddings + Bipartite Matching")
    print("=" * 65)
    patch()
