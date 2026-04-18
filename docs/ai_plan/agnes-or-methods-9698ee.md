# Agnes OR Methods: Research → Implementation Plan

Research all applicable Operations Research algorithms across every Agnes pipeline cell, produce a prioritized reference document, then implement the highest-impact methods in `agnes.ipynb`.

---

## Phase 1 — Research & Document

Produce `docs/OR_Methods.md` mapping OR algorithms to each Agnes pipeline component. Content outline below.

### Cell 6 — Supplier Consolidation (currently: heuristic weighted score)

| Method | Category | Fit |
|--------|----------|-----|
| **Integer Linear Programming (ILP) — Supplier Selection** | Combinatorial Opt. | ★★★ — binary select/reject per supplier, constraints for compliance, budget, lead time |
| **Set Covering Problem** | Combinatorial Opt. | ★★★ — find minimum # of suppliers covering all ingredient needs |
| **Multi-Objective Optimization (MOOP / Pareto)** | Multi-obj Opt. | ★★ — cost vs. compliance vs. lead time Pareto frontier |
| **Analytic Hierarchy Process (AHP)** | MCDM | ★★ — formalizes the current weight formula via pairwise comparisons |
| **Weighted Sum / TOPSIS** | MCDM | ★★ — rank suppliers on composite score with normalized criteria |
| **Stochastic Knapsack** | Stochastic Opt. | ★ — assign order volume to suppliers under uncertain demand |

### Cell 8 — Go-Fish Trust Score (currently: additive ±points)

| Method | Category | Fit |
|--------|----------|-----|
| **Bayesian Beta-Binomial Updating** | Bayesian Inference | ★★★ — update p(on-time) posterior after each delivery; better than fixed ±10/20 |
| **EWMA (Exponential Weighted Moving Average)** | Time-series | ★★ — weights recent deliveries more heavily than old history |
| **CUSUM / Control Charts (SPC)** | Statistical Process Control | ★★ — detect performance degradation early |
| **ELO Rating System** | Competitive Ranking | ★ — competitive supplier ranking borrowed from chess |

### Cell 9 — Risk Heat Map (currently: `BOM / supplier_count`)

| Method | Category | Fit |
|--------|----------|-----|
| **TOPSIS** | MCDM | ★★★ — multi-attribute risk ranking on (supplier_count, BOM volume, company_count, lead time spread) |
| **Herfindahl-Hirschman Index (HHI)** | Concentration Metrics | ★★★ — measure supplier concentration (market power equivalent) |
| **Monte Carlo Simulation** | Stochastic Simulation | ★★ — model disruption probability distributions for each ingredient |
| **AHP for Risk Weighting** | MCDM | ★★ — formalize how to weight supplier count vs. BOM volume vs. geographic risk |
| **Entropy-Based Diversification Score** | Information Theory | ★★ — Shannon entropy of supplier distribution per ingredient |

### Cell 10 — Disruption Simulator (currently: greedy lookup)

| Method | Category | Fit |
|--------|----------|-----|
| **Minimum-Cost Network Flow** | Network Optimization | ★★★ — optimal rerouting when a supplier fails; nodes = ingredients/suppliers, edges = capacity/cost |
| **Bipartite Maximum Matching** | Graph Theory | ★★★ — Hungarian algorithm to optimally match ingredients to backup suppliers |
| **Robust Optimization (min-max)** | Robust Opt. | ★★ — design sourcing that minimizes worst-case disruption impact |
| **Two-Stage Stochastic Programming** | Stochastic Opt. | ★★ — Stage 1: normal sourcing; Stage 2: recourse after disruption |
| **Simulated Annealing / Genetic Algo** | Meta-heuristics | ★ — large-scale portfolio rerouting where exact methods are too slow |

### GPO / Buying Consortium (currently: not implemented)

| Method | Category | Fit |
|--------|----------|-----|
| **Cooperative Game Theory — Shapley Value** | Game Theory | ★★★ — fair cost-saving allocation among the 17 companies in a consortium |
| **Core of a Cooperative Game** | Game Theory | ★★ — determine which coalitions are stable (no company has incentive to leave) |
| **Mechanism Design / VCG Auction** | Mechanism Design | ★ — incentive-compatible group purchasing mechanism |
| **Bin Packing / Knapsack (order tiers)** | Combinatorial Opt. | ★ — optimal order-quantity assignment at volume-discount price tiers |

---

## Phase 2 — Implementation Priority

Implement the **3 highest-impact** methods inside `agnes.ipynb` as new or replacement cells:

### 🥇 Priority 1: ILP Supplier Selection (replaces Cell 6 heuristic)
- **Library**: `scipy.optimize.linprog` or `PuLP`
- **Model**: Binary variables `x_s ∈ {0,1}` for each supplier; maximize total compliance-weighted BOM coverage; constraints: lead time ≤ threshold, at least one approved supplier per ingredient
- **Impact**: Provably optimal supplier portfolio vs. current greedy ranking

### 🥈 Priority 2: TOPSIS for Risk Heat Map (replaces Cell 9 vulnerability index)
- **Library**: pure `pandas/numpy` (TOPSIS is parameter-free beyond weight vector)
- **Criteria**: supplier_count, total_bom_appearances, company_count, avg_lead_time_spread
- **Impact**: Multi-attribute risk ranking replaces the single-ratio vulnerability index

### 🥉 Priority 3: Bayesian Trust Score (replaces Cell 8 additive model)
- **Library**: `scipy.stats.beta` (Beta distribution conjugate prior for Bernoulli trials)
- **Model**: Prior Beta(α=2, β=1); update with on-time/late deliveries; use posterior mean as trust probability; map to 0.5–1.5 multiplier
- **Impact**: Statistically principled uncertainty-aware trust scoring

### Bonus (if time): Shapley Value for GPO (new cell)
- **Library**: Pure Python (Shapley value computation is O(2^n), feasible for ≤20 companies)
- **Model**: Value function = savings from consolidated purchasing volume discount
- **Impact**: Demonstrates cooperative game theory, differentiates the GPO feature

---

## Execution Steps

1. **[done]** Read project files and pipeline architecture
2. **[todo]** Write `docs/OR_Methods.md` — comprehensive reference document
3. **[todo]** Implement Priority 1: ILP Supplier Selection in `agnes.ipynb` (new Cell 6b or replace Cell 6)
4. **[todo]** Implement Priority 2: TOPSIS Risk Heat Map (replace/extend Cell 9)
5. **[todo]** Implement Priority 3: Bayesian Trust Score (replace Cell 8)
6. **[todo]** Bonus: Shapley Value GPO cell (new cell after Cell 10)
7. **[todo]** Run notebook end-to-end, verify outputs match or improve on originals

---

## Constraints / Notes
- All OR implementations must run without external solvers beyond `scipy` and `PuLP` (no CPLEX, Gurobi)
- Do not weaken existing compliance guardrails — OR methods must respect the compliance-first architecture
- Existing cell structure preserved; new cells append or replace with clear labels
- exFAT filesystem — install any new deps with `pip install --break-system-packages`
