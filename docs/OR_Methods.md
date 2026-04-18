# Operations Research Methods for Agnes AI Supply Chain Optimization

## Overview

This document maps every applicable Operations Research (OR) algorithm and method to each Agnes pipeline component. For each method, the table entry shows the category, fit rating (★★★ = strongest fit), the problem it solves, and the implementation status in `agnes.ipynb`.

Agnes's current pipeline uses heuristic weighted scores. The OR methods below either **replace** those heuristics with provably optimal formulations, or **extend** them with statistically rigorous models.

---

## Pipeline Map: OR Methods by Cell

```
Cell 1 (Setup) → Cell 2 (DB Ingest) → Cell 3 (Target) → Cell 4 (Enrichment)
                                                                     ↓
Cell 7 (Report) ← Cell 6 (Consolidation) ← Cell 5 (LLM) ← ─────────┘
                        ↑ ILP
Cell 8 (Trust) → Cell 9 (Risk Heat Map) → Cell 10 (Disruption)
  ↑ Bayesian           ↑ TOPSIS/HHI           ↑ Network Flow
Cell 11 (GPO) [new]
  ↑ Shapley Value
```

---

## Cell 6 — Supplier Consolidation & Ranking

**Current heuristic**: `score = bom_appearances_covered × compliance_weight × trust_multiplier`

This is a hand-crafted additive/multiplicative formula with arbitrary weights. It cannot guarantee optimality and ignores combinatorial interactions (e.g., choosing supplier A makes supplier B redundant).

### Applicable OR Methods

| # | Method | Category | Fit | Problem Solved |
|---|--------|----------|-----|----------------|
| 1 | **Integer Linear Programming (ILP) — Supplier Selection** | Combinatorial Optimization | ★★★ | Binary select/reject for each supplier; maximize compliance-weighted BOM coverage subject to budget, lead time, and compliance constraints. Provably optimal. |
| 2 | **Set Covering Problem (SCP)** | Combinatorial Optimization | ★★★ | Find the *minimum* number of suppliers that together cover all ingredient requirements. Classical OR formulation; solvable with ILP. |
| 3 | **Multi-Objective Optimization (Pareto / ε-constraint)** | Multi-Objective Opt. | ★★ | Expose the Pareto frontier between competing objectives: minimize cost, minimize lead time, maximize compliance score. No single optimal — gives decision-makers a menu of trade-offs. |
| 4 | **Analytic Hierarchy Process (AHP)** | MCDM | ★★ | Formalizes the current weight formula via pairwise comparison matrices. Derives consistency-checked weights for criteria (grade, certifications, lead time, FDA status). |
| 5 | **TOPSIS** (Technique for Order Preference by Similarity to Ideal Solution) | MCDM | ★★ | Ranks suppliers by distance from the ideal best solution and the negative-ideal worst solution. Normalized, scale-invariant. |
| 6 | **Stochastic Knapsack** | Stochastic Optimization | ★ | Assigns order volume to suppliers under uncertain demand. Each supplier has a capacity; maximize expected fill rate under demand uncertainty. |

### Implemented in Agnes
**✅ Priority 1 — ILP Supplier Selection** replaces the heuristic in Cell 6. See Cell 6-OR in `agnes.ipynb`.

**Mathematical formulation:**
```
Decision variables:
  x_s ∈ {0, 1}   for each supplier s   (1 = selected)

Objective:
  maximize  Σ_s [ bom_coverage(s) × compliance_weight(s) × trust_multiplier(s) × x_s ]

Constraints:
  1. Σ_s x_s ≥ 1                           (at least one supplier selected)
  2. lead_time(s) ≤ MAX_LEAD_TIME  ∀s      (lead time feasibility)
  3. compliance_weight(s) ≥ MIN_COMPLIANCE ∀s selected  (quality floor)
  4. x_s = 0  if LLM verdict = REJECT      (hard compliance filter)
```

---

## Cell 8 — Supplier Trust Score

**Current heuristic**: `score = 100 + (on_time × 10) − (delays × 20)` → mapped to 0.5–1.5 multiplier

This is a linear additive model with fixed rewards/penalties. It ignores statistical uncertainty (a supplier with 1 delivery and 1 on-time should not be as trusted as one with 100 deliveries and 95 on-time), treats all deliveries equally regardless of age, and cannot detect performance degradation trends.

### Applicable OR Methods

| # | Method | Category | Fit | Problem Solved |
|---|--------|----------|-----|----------------|
| 1 | **Bayesian Beta-Binomial Updating** | Bayesian Inference | ★★★ | Model supplier on-time probability as a Beta distribution. Update posterior after each delivery. Trust = posterior mean; uncertainty = posterior variance. Inherently handles small sample sizes. |
| 2 | **EWMA** (Exponentially Weighted Moving Average) | Time-Series / Control | ★★ | Weight recent deliveries more heavily than old history. Configurable decay factor λ. Detects trend shifts faster than cumulative averages. |
| 3 | **CUSUM / Shewhart Control Charts** | Statistical Process Control | ★★ | Detect when supplier performance crosses a control limit (mean shift). Triggers automatic PROBATION status before accumulated damage is severe. |
| 4 | **ELO Rating System** | Competitive Ranking | ★ | Competitive ranking borrowed from chess — suppliers "compete" against each other; beating expectations gives more points than expected wins. Natural for comparative leaderboards. |

### Implemented in Agnes
**✅ Priority 3 — Bayesian Beta Trust Score** replaces the additive model in Cell 8. See Cell 8-OR in `agnes.ipynb`.

**Mathematical formulation:**
```
Prior: Beta(α₀=2, β₀=1)   (weak prior: slightly believe suppliers are reliable)

After n deliveries with k on-time:
  Posterior: Beta(α = α₀ + k,  β = β₀ + (n − k))

Trust probability p̂ = α / (α + β)    (posterior mean)
Trust multiplier  = 0.5 + p̂           (maps [0,1] → [0.5, 1.5])

Uncertainty interval = 95% credible interval of the posterior
  → if interval is wide (few deliveries), trust stays near prior
  → if interval is narrow (many deliveries), trust reflects actual performance
```

---

## Cell 9 — Supply Chain Risk Heat Map

**Current heuristic**: `vulnerability_index = total_bom_appearances / distinct_supplier_count`

This single ratio ignores critical dimensions: how many *companies* depend on an ingredient, supplier geographic concentration, lead time spread (a 45-day lead time is far riskier than a 7-day one), and whether any suppliers have poor trust scores.

### Applicable OR Methods

| # | Method | Category | Fit | Problem Solved |
|---|--------|----------|-----|----------------|
| 1 | **TOPSIS** | MCDM | ★★★ | Rank all 143 ingredients on 4+ criteria simultaneously (supplier_count, total_bom, company_count, avg_lead_time, min_trust_score). Normalized; no arbitrary vulnerability index needed. |
| 2 | **Herfindahl-Hirschman Index (HHI)** | Concentration Metrics | ★★★ | Measures supplier concentration per ingredient: `HHI = Σ (BOM_share_s)²`. HHI=1.0 means monopoly (CRITICAL); HHI→0 means perfectly diversified. Used in antitrust/market analysis. |
| 3 | **Monte Carlo Simulation** | Stochastic Simulation | ★★ | Assigns disruption probability to each supplier, then simulates thousands of scenarios. Outputs: expected BOM-days-at-risk, Value-at-Risk (VaR) at 95th percentile per ingredient. |
| 4 | **AHP for Risk Criteria Weighting** | MCDM | ★★ | Formalizes how much weight to assign to each risk dimension (supplier count vs. BOM volume vs. lead time vs. company count) using pairwise expert comparisons. |
| 5 | **Shannon Entropy Diversification Score** | Information Theory | ★★ | `H = −Σ p_s × log(p_s)` where p_s = BOM share per supplier. Maximum entropy = perfectly diversified; H=0 = single source. Continuous analogue of supplier count. |

### Implemented in Agnes
**✅ Priority 2 — TOPSIS Risk Heat Map** replaces the vulnerability index in Cell 9. See Cell 9-OR in `agnes.ipynb`.

**Mathematical formulation (4-criterion TOPSIS):**
```
Criteria matrix X (143 ingredients × 4 criteria):
  C1: total_bom_appearances     (higher = more risk)
  C2: company_count             (higher = more interdependency)
  C3: 1/supplier_count          (fewer suppliers = more risk, inverted)
  C4: avg_lead_time_days        (longer = more risk)

Steps:
  1. Normalize: r_ij = x_ij / √(Σ x_ij²)
  2. Weight: v_ij = w_j × r_ij     (weights w = [0.35, 0.20, 0.30, 0.15])
  3. Ideal best  A⁺ = max(v_ij) for each criterion
     Ideal worst A⁻ = min(v_ij) for each criterion
  4. Distance to ideal: d⁺_i = √Σ(v_ij - A⁺_j)²
     Distance to worst: d⁻_i = √Σ(v_ij - A⁻_j)²
  5. TOPSIS score: C_i = d⁻_i / (d⁺_i + d⁻_i)   ∈ [0, 1]
     Higher score = higher risk proximity to ideal-worst
```

---

## Cell 10 — Disruption Simulator

**Current heuristic**: Greedy lookup — find alternate suppliers for each affected ingredient; classify as MANAGEABLE or CRITICAL.

This approach is suboptimal: when a supplier fails, some backup suppliers may themselves be constrained; there may be partial coverage scenarios; and the order of rerouting decisions affects total cost. Greedy lookup ignores all of this.

### Applicable OR Methods

| # | Method | Category | Fit | Problem Solved |
|---|--------|----------|-----|----------------|
| 1 | **Minimum-Cost Network Flow (MCNF)** | Network Optimization | ★★★ | Model the supply network as a flow graph: source nodes (suppliers), sink nodes (ingredients/companies), edge capacities (supplier limits), edge costs (unit price × lead time). After a node failure, solve the residual network for optimal rerouting. |
| 2 | **Bipartite Maximum Matching (Hungarian Algorithm)** | Graph Theory | ★★★ | Optimally assign each affected ingredient to one backup supplier. Hungarian algorithm guarantees maximum coverage in O(n³). Useful when each supplier can only handle a subset of ingredients. |
| 3 | **Robust Optimization (min-max formulation)** | Robust Optimization | ★★ | Design a sourcing portfolio that minimizes the *worst-case* impact across all possible disruption scenarios. More conservative than expected-value optimization. |
| 4 | **Two-Stage Stochastic Programming** | Stochastic Optimization | ★★ | Stage 1 (here-and-now): select primary suppliers. Stage 2 (wait-and-see recourse): after disruption is revealed, choose backup suppliers. Objective: minimize expected total cost across scenarios. |
| 5 | **Simulated Annealing / Genetic Algorithm** | Meta-heuristics | ★ | For large-scale portfolio rerouting where exact ILP/flow methods are too slow. Explores neighborhood of solutions via probabilistic search. |

### Production Implementation Note
The MCNF approach requires capacity data per supplier (how many tons/units per ingredient they can supply). This data is not in the current SQLite schema. **For Agnes's hackathon scope**, the bipartite matching is the most tractable implementation given available data. Full MCNF would be enabled in production with ERP capacity data.

---

## GPO / Buying Consortium (New Cell 11)

**Current state**: Referenced in pipeline description but not implemented.

The Group Purchasing Organization (GPO) feature is where Agnes's most powerful business value lies: 17 companies buying vitamin-d3-cholecalciferol independently have *zero* combined leverage; if they form a consortium, they unlock volume discounts. The question is: how should savings be allocated fairly?

### Applicable OR Methods

| # | Method | Category | Fit | Problem Solved |
|---|--------|----------|-----|----------------|
| 1 | **Cooperative Game Theory — Shapley Value** | Game Theory | ★★★ | Fairly distributes consortium savings among member companies based on each company's marginal contribution to every possible coalition. The only allocation satisfying efficiency, symmetry, dummy, and additivity axioms. |
| 2 | **Core of a Cooperative Game** | Game Theory | ★★ | Determines which coalitions are *stable* — no subgroup has incentive to break away and negotiate separately. Core membership guarantees the grand coalition won't fragment. |
| 3 | **Mechanism Design / VCG Auction** | Mechanism Design | ★ | Incentive-compatible procurement mechanism: each company truthfully reports its volume demand; the mechanism aggregates demand and allocates orders to maximize total surplus. Prevents strategic misreporting. |
| 4 | **Newsvendor Model** | Stochastic Inventory | ★ | Optimal order quantity under uncertain demand with volume-discount price tiers. For each consortium ingredient, find Q* that minimizes expected holding + stockout costs. |
| 5 | **Bin Packing / Price-Tier Knapsack** | Combinatorial Opt. | ★ | Optimally assign order quantities to price tiers (e.g., 0–100kg at $50, 100–500kg at $42, 500kg+ at $38) to maximize savings without over-ordering. |

### Implemented in Agnes
**✅ Bonus — Shapley Value GPO** is added as Cell 11 in `agnes.ipynb`.

**Mathematical formulation:**
```
Players: N = {c₁, c₂, …, c₁₇}   (17 CPG companies)

Value function v(S) for coalition S:
  v(S) = total_volume(S) × unit_cost_saving(S) − fixed_coordination_cost
  where unit_cost_saving(S) = base_price × volume_discount_rate(|S|)

Shapley value for company i:
  φᵢ = Σ_{S ⊆ N∖{i}} [ |S|!(|N|−|S|−1)! / |N|! ] × [v(S∪{i}) − v(S)]

Interpretation:
  φᵢ = company i's fair share of consortium savings
  Σφᵢ = total consortium savings  (efficiency)
```

---

## Summary Table: Implementation Status

| Cell | Current Method | OR Replacement | Status | Library |
|------|---------------|----------------|--------|---------|
| Cell 6 | Weighted score heuristic | **ILP Supplier Selection** | ✅ Implemented | `PuLP` |
| Cell 8 | Additive ±10/20 points | **Bayesian Beta-Binomial** | ✅ Implemented | `scipy.stats` |
| Cell 9 | `BOM / supplier_count` | **TOPSIS + HHI** | ✅ Implemented | `numpy/pandas` |
| Cell 10 | Greedy lookup | Bipartite Matching (documented) | 📋 Documented | `scipy.optimize` |
| Cell 11 | Not implemented | **Shapley Value GPO** | ✅ Implemented | Pure Python |

---

## References & Further Reading

1. **ILP / Set Covering**: Wolsey, L.A. (1998). *Integer Programming*. Wiley.
2. **TOPSIS**: Hwang, C.L., Yoon, K. (1981). *Multiple Attribute Decision Making*. Springer.
3. **AHP**: Saaty, T.L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill.
4. **Bayesian Supplier Evaluation**: Talluri, S., Narasimhan, R. (2003). Vendor evaluation with performance variability. *EJOR*, 146(3).
5. **HHI Concentration Index**: U.S. DOJ/FTC Merger Guidelines (2010).
6. **Shapley Value**: Shapley, L.S. (1953). A value for n-person games. *Contributions to the Theory of Games*, 2.
7. **Minimum Cost Network Flow**: Ahuja, R.K., Magnanti, T.L., Orlin, J.B. (1993). *Network Flows*. Prentice Hall.
8. **Robust Optimization**: Ben-Tal, A., Nemirovski, A. (2002). Robust optimization — methodology and applications. *Mathematical Programming*, 92(3).
9. **Two-Stage Stochastic Programming**: Birge, J.R., Louveaux, F. (2011). *Introduction to Stochastic Programming*. Springer.
10. **Newsvendor Model**: Silver, E.A., Pyke, D.F., Peterson, R. (1998). *Inventory Management and Production Planning and Scheduling*. Wiley.
