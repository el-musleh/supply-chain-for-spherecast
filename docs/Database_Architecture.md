# Database Architecture

The Agnes AI Supply Chain Decision-Support System uses a local SQLite database (`DB/db.sqlite`) to map fragmented raw material demands across multiple CPG companies. This document outlines the core tables and relationships.

## Core Tables Overview

There are 6 core tables in the database:

1. **`Company`**
   - **Purpose:** Represents the CPG (Consumer Packaged Goods) companies producing finished goods.
   - **Columns:** `Id` (Primary Key), `Name` (e.g., 'Nature Made', 'GNC').

2. **`Product`**
   - **Purpose:** Represents any item in the supply chain. This includes both finished goods and raw material ingredients.
   - **Columns:** `Id` (Primary Key), `SKU` (String identifier), `CompanyId` (Foreign Key to `Company`), `Type` (`finished-good` or `raw-material`).
   - **Key Concept:** A raw material SKU follows a strict formatting pattern: 
     `RM-C{CompanyId}-{ingredient-name}-{8-character-hash}`. 
     *Example:* `RM-C30-vitamin-d3-cholecalciferol-559c9699`

3. **`BOM` (Bill of Materials)**
   - **Purpose:** Represents the formulation or recipe for a specific finished product.
   - **Columns:** `Id` (Primary Key), `ProducedProductId` (Foreign Key to the `finished-good` Product).

4. **`BOM_Component`**
   - **Purpose:** The mapping table that defines which raw materials (ingredients) are consumed by a specific BOM.
   - **Columns:** `BOMId` (Foreign Key to `BOM`), `ConsumedProductId` (Foreign Key to the `raw-material` Product).

5. **`Supplier`**
   - **Purpose:** Represents raw material suppliers who can fulfill purchase orders.
   - **Columns:** `Id` (Primary Key), `Name` (e.g., 'Prinova USA', 'PureBulk').

6. **`Supplier_Product`**
   - **Purpose:** Maps which raw materials can be provided by which suppliers.
   - **Columns:** `SupplierId` (Foreign Key to `Supplier`), `ProductId` (Foreign Key to `Product`).

## Data Flow & Identification

### The Fragmentation Problem
Multiple companies independently purchase the exact same ingredient from different suppliers, lacking combined-volume leverage. In the database, they do not share the same `Product.Id` because each company's ingredient has its own unique SKU.

### The Solution
By using SQL's `SUBSTR` and `INSTR` functions, Agnes parses the `{ingredient-name}` out of the `Product.SKU`. 

For example, `RM-C30-vitamin-d3-cholecalciferol-559c9699` is parsed to isolate **`vitamin-d3-cholecalciferol`**. 

Once parsed, Agnes groups all raw materials sharing the exact same ingredient name. It then traces these back through the `BOM_Component` and `BOM` tables to count how many finished goods ("BOM appearances") rely on that specific ingredient, identifying the total demand waste across all companies.
