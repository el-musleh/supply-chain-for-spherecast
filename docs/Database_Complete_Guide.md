# Database Architecture Complete Guide

## Overview

The Agnes AI system uses a local SQLite database (`DB/db.sqlite`) to model fragmented raw material demands across multiple CPG companies. This database contains real companies and real products with adjusted and approximated Bills of Materials (BOMs) and ingredients.

### Database Statistics

- **Companies**: 61 CPG brands
- **Products**: 876 items (both finished goods and raw materials)
- **Suppliers**: 40 raw material vendors
- **BOMs**: 149 product formulations
- **BOM Components**: 1,528 ingredient mappings
- **Fragmented Ingredients**: 143 (purchased by multiple companies independently)

## Entity-Relationship Diagram (ERD)

```
┌─────────────┐
│  Company    │
├─────────────┤
│ Id (PK)     │
│ Name        │
└─────┬───────┘
      │
      │ 1
      │
      │ N
┌─────▼─────────┐         ┌─────────────┐
│   Product     │         │   Supplier  │
├───────────────┤         ├─────────────┤
│ Id (PK)       │         │ Id (PK)     │
│ SKU           │         │ Name        │
│ CompanyId (FK)│         └──────┬──────┘
│ Type          │                │
└───────┬───────┘                │
        │                         │
        │ 1                       │ 1
        │                         │
        │ N                       │ N
        │                         │
┌───────▼────────┐      ┌────────▼─────────┐
│      BOM       │      │Supplier_Product   │
├────────────────┤      ├───────────────────┤
│ Id (PK)        │      │ SupplierId (FK)  │
│ProducedProductId│      │ ProductId (FK)   │
│ (FK to Product)│      └───────────────────┘
└───────┬────────┘
        │
        │ 1
        │
        │ N
┌───────▼────────────┐
│  BOM_Component    │
├───────────────────┤
│ BOMId (FK)        │
│ ConsumedProductId │
│ (FK to Product)   │
└───────────────────┘
```

## Core Tables Detailed Documentation

### 1. Company Table

**Purpose**: Represents the CPG (Consumer Packaged Goods) companies that produce finished goods.

**Schema**:
| Column | Type | Description |
|--------|------|-------------|
| Id | INTEGER | Primary Key |
| Name | TEXT | Company name (e.g., 'Nature Made', 'GNC', 'Kirkland Signature') |

**Sample Data**:
| Id | Name |
|----|------|
| 1 | 21st Century |
| 2 | ALL ONE |
| 3 | AN PERFORMANCE |
| 4 | AlkemyPower |
| 5 | Aloha |
| 30 | Nature Made |
| 52 | The Vitamin Shoppe |
| 57 | Vitacost |

**Key Insight**: These are the end brands whose products consumers buy in stores. They are Agnes's ultimate customers.

---

### 2. Product Table

**Purpose**: Represents any item in the supply chain. This includes both finished goods (products sold to consumers) and raw material ingredients.

**Schema**:
| Column | Type | Description |
|--------|------|-------------|
| Id | INTEGER | Primary Key |
| SKU | TEXT | Stock Keeping Unit - unique identifier |
| CompanyId | INTEGER | Foreign Key to Company table |
| Type | TEXT | Either 'finished-good' or 'raw-material' |

**SKU Format for Raw Materials**:

Raw material SKUs follow a strict pattern:
```
RM-C{CompanyId}-{ingredient-name}-{8-character-hash}
```

**Examples**:
- `RM-C30-vitamin-d3-cholecalciferol-559c9699`
- `RM-C52-vitamin-d3-cholecalciferol-1d08f804`
- `RM-C57-vitamin-d3-cholecalciferol-528f4316`

**Breaking down the example** `RM-C30-vitamin-d3-cholecalciferol-559c9699`:
- `RM` = Raw Material
- `C30` = Company ID 30 (Nature Made)
- `vitamin-d3-cholecalciferol` = Ingredient name
- `559c9699` = 8-character hash for uniqueness

**Sample Data - Finished Goods**:
| Id | SKU | CompanyId | Type |
|----|-----|-----------|------|
| 1 | FG-iherb-10421 | 28 | finished-good |
| 2 | FG-iherb-116514 | 6 | finished-good |
| 3 | FG-iherb-71022 | 56 | finished-good |
| 4 | FG-iherb-52816 | 33 | finished-good |

**Sample Data - Raw Materials**:
| Id | SKU | CompanyId | Type |
|----|-----|-----------|------|
| 506 | RM-C30-vitamin-d3-cholecalciferol-559c9699 | 30 | raw-material |
| 509 | RM-C52-vitamin-d3-cholecalciferol-1d08f804 | 52 | raw-material |
| 511 | RM-C57-vitamin-d3-cholecalciferol-528f4316 | 57 | raw-material |

**Critical Architecture Detail**: The SKU format is the key to solving the fragmentation problem. By parsing the ingredient name out of the SKU, Agnes can identify when multiple companies are independently purchasing the same ingredient under different SKUs.

---

### 3. BOM Table (Bill of Materials)

**Purpose**: Represents the formulation or recipe for a specific finished product. Every product classified as a 'finished-good' has an associated BOM.

**Schema**:
| Column | Type | Description |
|--------|------|-------------|
| Id | INTEGER | Primary Key |
| ProducedProductId | INTEGER | Foreign Key to Product table (must be a finished-good) |

**Sample Data**:
| Id | ProducedProductId |
|----|-------------------|
| 1 | 1 |
| 2 | 2 |
| 3 | 3 |
| 4 | 4 |

**Key Insight**: A BOM is like a recipe card. It tells you which ingredients (raw materials) are needed to make a specific finished product.

---

### 4. BOM_Component Table

**Purpose**: The mapping table that defines which raw materials (ingredients) are consumed by a specific BOM.

**Schema**:
| Column | Type | Description |
|--------|------|-------------|
| BOMId | INTEGER | Foreign Key to BOM table |
| ConsumedProductId | INTEGER | Foreign Key to Product table (must be a raw-material) |

**Sample Data**:
| BOMId | ConsumedProductId |
|-------|-------------------|
| 1 | 506 |
| 1 | 509 |
| 1 | 511 |
| 1 | 512 |
| 2 | 208 |

**Key Insight**: Each row represents one ingredient in a recipe. A BOM for a multivitamin might have 20+ BOM_Component rows, one for each vitamin and mineral.

**Important Constraint**: According to the database rules, every BOM has at least 2 BOM components, and all components are of type 'raw-material'.

---

### 5. Supplier Table

**Purpose**: Represents raw material suppliers who can fulfill purchase orders.

**Schema**:
| Column | Type | Description |
|--------|------|-------------|
| Id | INTEGER | Primary Key |
| Name | TEXT | Supplier name (e.g., 'Prinova USA', 'PureBulk', 'Cargill') |

**Sample Data**:
| Id | Name |
|----|------|
| 1 | Prinova USA |
| 2 | PureBulk |
| 3 | Cargill |
| 4 | ADM |
| 5 | Univar Solutions |

**Key Insight**: These are the vendors that actually manufacture and sell the raw ingredients. Agnes's goal is to help CPG companies consolidate purchases with these suppliers.

---

### 6. Supplier_Product Table

**Purpose**: Maps which raw materials can be provided by which suppliers. This is a many-to-many relationship.

**Schema**:
| Column | Type | Description |
|--------|------|-------------|
| SupplierId | INTEGER | Foreign Key to Supplier table |
| ProductId | INTEGER | Foreign Key to Product table (must be a raw-material) |

**Sample Data**:
| SupplierId | ProductId |
|------------|-----------|
| 1 | 506 |
| 1 | 509 |
| 2 | 506 |
| 2 | 511 |

**Key Insight**: This table tells you which suppliers can deliver which ingredients. If multiple suppliers can deliver the same ingredient, that's a consolidation opportunity.

**Important Constraint**: According to the database rules, Supplier_Product relationships only exist for raw-material type products, not finished goods.

---

## The Fragmentation Problem

### How Fragmentation Manifests in the Database

Consider the ingredient "vitamin-d3-cholecalciferol":

**Company A (Nature Made, Id=30)**:
- SKU: `RM-C30-vitamin-d3-cholecalciferol-559c9699`
- Product Id: 506
- Purchases from: Prinova USA

**Company B (The Vitamin Shoppe, Id=52)**:
- SKU: `RM-C52-vitamin-d3-cholecalciferol-1d08f804`
- Product Id: 509
- Purchases from: Prinova USA

**Company C (Vitacost, Id=57)**:
- SKU: `RM-C57-vitamin-d3-cholecalciferol-528f4316`
- Product Id: 511
- Purchases from: PureBulk

These are **the same ingredient** (vitamin-d3-cholecalciferol) but:
- They have different Product IDs (506, 509, 511)
- They have different SKUs (different company IDs and hashes)
- They might be purchased from different suppliers
- No single query on Product.Id would reveal they're the same ingredient

**This is the fragmentation problem Agnes solves.**

### The Solution: SKU Parsing

By using SQL string functions to extract the ingredient name from the SKU, Agnes can group these together:

```sql
-- Parsing formula
SUBSTR(
    SUBSTR(SKU, 4 + INSTR(SUBSTR(SKU, 4), '-')),
    1,
    LENGTH(SUBSTR(SKU, 4 + INSTR(SUBSTR(SKU, 4), '-'))) - 9
)
```

**Step-by-step breakdown**:
1. `SUBSTR(SKU, 4)` → Removes "RM-" prefix
2. `INSTR(..., '-')` → Finds the dash after C{id}
3. `SUBSTR(SKU, 4 + offset)` → Removes "RM-C{id}-" prefix
4. `LENGTH(...) - 9` → Removes the trailing "-{8hexhash}"
5. Result: `vitamin-d3-cholecalciferol`

Once parsed, Agnes can:
- Group all raw materials with the same ingredient name
- Count how many companies purchase that ingredient
- Trace back through BOM_Component and BOM to count finished goods affected
- Identify consolidation opportunities

---

## SQL Query Patterns

### Query 1: Find All Fragmented Ingredients

This query identifies ingredients purchased by more than one company:

```sql
WITH parsed AS (
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
        SUM(bom_appearances) AS total_bom_appearances
    FROM bom_usage
    GROUP BY ingredient_name
    HAVING company_count > 1
)
SELECT * FROM fragmented_ingredients
ORDER BY total_bom_appearances DESC;
```

**Result** (top 5):
| ingredient_name | company_count | total_bom_appearances |
|-----------------|---------------|----------------------|
| vitamin-d3-cholecalciferol | 17 | 33 |
| gelatin | 11 | 30 |
| magnesium-stearate | 11 | 30 |
| microcrystalline-cellulose | 13 | 29 |
| citric-acid | 12 | 26 |

### Query 2: Get Supplier Coverage for an Ingredient

This query shows which suppliers can deliver a specific ingredient:

```sql
WITH parsed AS (
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
)
SELECT
    pr.ingredient_name,
    pr.company_name,
    pr.SKU AS company_sku,
    s.Name AS supplier_name
FROM parsed pr
JOIN Supplier_Product sp ON sp.ProductId = pr.product_id
JOIN Supplier s ON s.Id = sp.SupplierId
WHERE pr.ingredient_name = 'vitamin-d3-cholecalciferol'
ORDER BY pr.company_name, s.Name;
```

**Result**:
| ingredient_name | company_name | company_sku | supplier_name |
|-----------------|--------------|-------------|---------------|
| vitamin-d3-cholecalciferol | 21st Century | RM-C1-vitamin-d3-cholecalciferol-67efce0f | Prinova USA |
| vitamin-d3-cholecalciferol | 21st Century | RM-C1-vitamin-d3-cholecalciferol-67efce0f | PureBulk |
| vitamin-d3-cholecalciferol | Nature Made | RM-C30-vitamin-d3-cholecalciferol-559c9699 | Prinova USA |
| vitamin-d3-cholecalciferol | Nature Made | RM-C30-vitamin-d3-cholecalciferol-559c9699 | PureBulk |

### Query 3: Trace Finished Products Using an Ingredient

This query shows which finished goods depend on a specific ingredient:

```sql
WITH parsed AS (
    SELECT
        p.Id AS rm_product_id,
        c.Name AS company_name,
        SUBSTR(
            SUBSTR(p.SKU, 4 + INSTR(SUBSTR(p.SKU, 4), '-')),
            1,
            LENGTH(SUBSTR(p.SKU, 4 + INSTR(SUBSTR(p.SKU, 4), '-'))) - 9
        ) AS ingredient_name
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
WHERE pr.ingredient_name = 'vitamin-d3-cholecalciferol'
ORDER BY pr.company_name, fg.SKU;
```

**Result** (sample):
| company_name | ingredient_name | finished_product_sku |
|--------------|-----------------|----------------------|
| 21st Century | vitamin-d3-cholecalciferol | FG-iherb-cen-27493 |
| 21st Century | vitamin-d3-cholecalciferol | FG-target-a-1006517338 |
| GNC | vitamin-d3-cholecalciferol | FG-gnc-145223 |
| Nature Made | vitamin-d3-cholecalciferol | FG-costco-100214136 |
| Nature Made | vitamin-d3-cholecalciferol | FG-cvs-486916 |

---

## Case Study: Vitamin D3 Fragmentation

### The Data

**Ingredient**: vitamin-d3-cholecalciferol
- **Companies purchasing separately**: 17
- **Total BOM appearances**: 33 (33 finished products depend on this ingredient)
- **Distinct supplier options**: 2 (Prinova USA, PureBulk)
- **Unique company SKUs**: 17

### Per-Company Breakdown

| Company | SKU | BOM Appearances |
|---------|-----|----------------|
| Nature Made | RM-C30-vitamin-d3-cholecalciferol-559c9699 | 11 |
| The Vitamin Shoppe | RM-C52-vitamin-d3-cholecalciferol-1d08f804 | 3 |
| Vitacost | RM-C57-vitamin-d3-cholecalciferol-528f4316 | 3 |
| 21st Century | RM-C1-vitamin-d3-cholecalciferol-67efce0f | 2 |
| up&up | RM-C62-vitamin-d3-cholecalciferol-c763da21 | 2 |
| NOW Foods | RM-C28-vitamin-d3-cholecalciferol-8956b79c | 1 |
| GNC | RM-C19-vitamin-d3-cholecalciferol-3f392102 | 1 |
| Kirkland Signature | RM-C25-vitamin-d3-cholecalciferol-564712ba | 1 |

### Supplier Coverage

| Supplier | Companies Served | BOM Coverage |
|----------|------------------|--------------|
| Prinova USA | 17 | 33 |
| PureBulk | 17 | 33 |

### The Opportunity

All 17 companies are purchasing the same ingredient, likely at different prices and terms. If they could see the combined demand (33 BOM appearances), they would have significant leverage to negotiate better pricing and terms with suppliers.

However, Agnes's compliance analysis reveals that PureBulk cannot substitute for Prinova USA due to missing USP and Halal certifications. This demonstrates why consolidation must be compliance-aware, not just volume-based.

---

## Database Access Tools

### Recommended Tools

1. **DB Browser for SQLite** (Recommended for beginners)
   - Free, open-source
   - Visual table browser
   - SQL query editor
   - Export to CSV

2. **DBeaver** (For advanced users)
   - Professional database tool
   - Supports SQLite and many other databases
   - Advanced autocomplete and ERD visualization

3. **VS Code SQLite Viewer Extension**
   - Integrated into VS Code
   - Quick table viewing
   - No need to leave your editor

### Python Integration

```python
import sqlite3
import pandas as pd

# Connect to database
conn = sqlite3.connect('DB/db.sqlite')

# Execute query
query = """
    SELECT * FROM Product 
    WHERE Type = 'raw-material' 
    LIMIT 5
"""
df = pd.read_sql_query(query, conn)

# View results
print(df)

# Close connection
conn.close()
```

---

## Common Queries for Exploration

### List All Tables
```sql
SELECT name FROM sqlite_master WHERE type='table';
```

### Count Records per Table
```sql
SELECT 'Company' as table_name, COUNT(*) as count FROM Company
UNION ALL
SELECT 'Product', COUNT(*) FROM Product
UNION ALL
SELECT 'BOM', COUNT(*) FROM BOM
UNION ALL
SELECT 'BOM_Component', COUNT(*) FROM BOM_Component
UNION ALL
SELECT 'Supplier', COUNT(*) FROM Supplier
UNION ALL
SELECT 'Supplier_Product', COUNT(*) FROM Supplier_Product;
```

### Find Top 10 Most Used Ingredients
```sql
WITH parsed AS (
    SELECT
        p.Id,
        SUBSTR(
            SUBSTR(p.SKU, 4 + INSTR(SUBSTR(p.SKU, 4), '-')),
            1,
            LENGTH(SUBSTR(p.SKU, 4 + INSTR(SUBSTR(p.SKU, 4), '-'))) - 9
        ) AS ingredient_name
    FROM Product p
    WHERE p.Type = 'raw-material'
)
SELECT
    ingredient_name,
    COUNT(bc.BOMId) AS bom_count
FROM parsed p
JOIN BOM_Component bc ON bc.ConsumedProductId = p.Id
GROUP BY ingredient_name
ORDER BY bom_count DESC
LIMIT 10;
```

---

## Related Documents

- `Project_Overview.md` - High-level project introduction
- `Agnes_Pipeline_Architecture.md` - How Agnes queries and processes this database
- `Technical_Implementation_Guide.md` - Setup and usage instructions
