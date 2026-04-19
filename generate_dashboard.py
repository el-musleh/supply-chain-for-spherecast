import sqlite3
import pandas as pd
import json
import random
import re
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────
DB_PATH = Path("DB/db.sqlite")
KB_DIR = Path("KB")
OUT_PATH = KB_DIR / "dashboard_signals.json"

_COMPLIANCE_MOCK_DB = {
    ("Prinova USA", "vitamin-d3-cholecalciferol"): {
        "organic_certified": False,
        "fda_registered":    True,
        "non_gmo":           True,
        "grade":             "pharmaceutical",
        "lead_time_days":    14,
        "certifications":    ["USP", "GMP", "Halal", "Kosher"],
    },
    ("PureBulk", "vitamin-d3-cholecalciferol"): {
        "organic_certified": False,
        "fda_registered":    True,
        "non_gmo":           True,
        "grade":             "pharmaceutical",
        "lead_time_days":    7,
        "certifications":    ["GMP", "Kosher"],
    },
    ("Prinova USA", "vitamin-d3"): {
        "organic_certified": False,
        "fda_registered":    True,
        "non_gmo":           True,
        "grade":             "food",
        "lead_time_days":    14,
        "certifications":    ["GMP", "Kosher"],
    },
    ("PureBulk", "vitamin-d3"): {
        "organic_certified": False,
        "fda_registered":    True,
        "non_gmo":           False,
        "grade":             "food",
        "lead_time_days":    7,
        "certifications":    ["GMP"],
    },
}

class SupplierTrustTracker:
    BASE_SCORE   = 100
    ON_TIME_BONUS = 10
    DELAY_PENALTY = 20

    def __init__(self):
        self._scores  = {}

    def get_score(self, supplier_name: str) -> int:
        if supplier_name not in self._scores:
            # Deterministic seed for "randomness"
            # Note: Python's hash() is randomized per process by default.
            # We'll use a simple sum of ordinals for a stable seed across processes.
            seed = sum(ord(c) for c in supplier_name)
            rng = random.Random(seed)
            score = self.BASE_SCORE
            for _ in range(20):
                if rng.random() < 0.80:
                    score += self.ON_TIME_BONUS
                else:
                    score -= self.DELAY_PENALTY
            self._scores[supplier_name] = max(10, score)
        return self._scores[supplier_name]

    def get_trust_multiplier(self, supplier_name: str) -> float:
        return round(max(0.5, min(1.5, self.get_score(supplier_name) / 100)), 3)

def compute_compliance_weight(compliance: dict) -> float:
    weight = 1.0
    if compliance.get("grade") == "pharmaceutical":
        weight += 0.2
    elif compliance.get("grade") == "technical":
        weight -= 0.3
    if compliance.get("fda_registered"):
        weight += 0.1
    if compliance.get("non_gmo"):
        weight += 0.1
    cert_bonus = min(0.30, len(compliance.get("certifications", [])) * 0.05)
    weight += cert_bonus
    return round(max(0.1, weight), 3)

def scrape_supplier_compliance(supplier_name: str, ingredient_name: str) -> dict:
    # Minimal version of the scraper fallback chain
    return _COMPLIANCE_MOCK_DB.get((supplier_name, ingredient_name), {
        "organic_certified": False,
        "fda_registered":    True,
        "non_gmo":           False,
        "grade":             "food",
        "lead_time_days":    14,
        "certifications":    ["GMP"],
    })

def main():
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        return

    KB_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    # ── Data Ingestion (re-implementing notebook SQL) ────────────────────────
    SQL_CTE = """
    WITH parsed AS (
        SELECT
            p.Id        AS product_id,
            p.SKU,
            p.CompanyId,
            c.Name      AS company_name,
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
        SELECT
            ingredient_name,
            COUNT(DISTINCT CompanyId) AS company_count,
            SUM(bom_appearances)      AS total_bom_appearances
        FROM bom_usage
        GROUP BY ingredient_name
        HAVING company_count > 1
    )
    """

    df_fragmented = pd.read_sql_query(SQL_CTE + """
    SELECT
        fi.ingredient_name,
        fi.company_count,
        fi.total_bom_appearances,
        bu.company_name,
        bu.bom_appearances
    FROM fragmented_ingredients fi
    JOIN bom_usage bu ON bu.ingredient_name = fi.ingredient_name
    """, conn)

    df_supplier_coverage = pd.read_sql_query(SQL_CTE + """
    SELECT
        fi.ingredient_name,
        bu.company_name,
        s.Name              AS supplier_name
    FROM fragmented_ingredients fi
    JOIN bom_usage bu         ON bu.ingredient_name = fi.ingredient_name
    JOIN Supplier_Product sp  ON sp.ProductId        = bu.product_id
    JOIN Supplier s           ON s.Id                = sp.SupplierId
    """, conn)

    conn.close()

    # ── Process Risk and Consortium ──────────────────────────────────────────
    df_supplier_counts = (
        df_supplier_coverage
        .groupby("ingredient_name")["supplier_name"]
        .nunique()
        .reset_index()
        .rename(columns={"supplier_name": "supplier_count"})
    )

    df_bom_totals = (
        df_fragmented
        .groupby("ingredient_name")
        .agg(
            total_bom_appearances = ("bom_appearances", "sum"),
            company_count         = ("company_name",    "nunique"),
        )
        .reset_index()
    )

    df_risk = df_bom_totals.merge(df_supplier_counts, on="ingredient_name")
    
    def _risk_tier(row):
        if row["supplier_count"] == 1: return "CRITICAL"
        if row["supplier_count"] == 2 and row["total_bom_appearances"] >= 20: return "HIGH"
        if row["total_bom_appearances"] >= 15: return "MEDIUM"
        return "LOW"
    
    df_risk["risk_tier"] = df_risk.apply(_risk_tier, axis=1)
    df_risk["vulnerability_index"] = (df_risk["total_bom_appearances"] / df_risk["supplier_count"]).round(2)

    consortium_set = set(df_bom_totals[df_bom_totals["company_count"] >= 5]["ingredient_name"])

    # ── Build Dashboard ──────────────────────────────────────────────────────
    trust_tracker = SupplierTrustTracker()
    dashboard_rows = []

    for _, row in df_risk.iterrows():
        ing = row["ingredient_name"]
        
        suppliers = df_supplier_coverage[df_supplier_coverage["ingredient_name"] == ing]["supplier_name"].unique()
        
        if len(suppliers) == 0:
            trust_mult = 1.0
            comp_weight = 1.0
        else:
            trust_mult = max(trust_tracker.get_trust_multiplier(s) for s in suppliers)
            comp_weight = max(compute_compliance_weight(scrape_supplier_compliance(s, ing)) for s in suppliers)

        agnes_score = round(row["total_bom_appearances"] * comp_weight * trust_mult, 1)

        # Deterministic savings estimate
        seed = sum(ord(c) for c in ing)
        rng = random.Random(seed)
        if row["risk_tier"] in ("CRITICAL", "HIGH"):
            est_pct = round(rng.uniform(10.0, 15.0), 1)
        else:
            est_pct = round(rng.uniform(6.0, 11.0), 1)

        dashboard_rows.append({
            "ingredient_name":  ing,
            "companies":        int(row["company_count"]),
            "bom_appearances":  int(row["total_bom_appearances"]),
            "suppliers":        int(row["supplier_count"]),
            "risk_tier":        row["risk_tier"],
            "vuln_index":       row["vulnerability_index"],
            "trust_score":      int(trust_mult * 100),
            "compliance_wt":    round(comp_weight, 3),
            "agnes_score":      agnes_score,
            "est_savings":      f"{est_pct}%",
            "gpo_eligible":     "YES" if ing in consortium_set else "—",
        })

    df_dashboard = (
        pd.DataFrame(dashboard_rows)
        .sort_values("agnes_score", ascending=False)
        .reset_index(drop=True)
    )
    df_dashboard.insert(0, "priority", df_dashboard.index + 1)
    
    df_dashboard.to_json(OUT_PATH, orient="records", indent=2)
    print(f"✓ Dashboard signals generated: {OUT_PATH} ({len(df_dashboard)} ingredients)")

if __name__ == "__main__":
    main()
