# DayBook Analytics — Aligned Execution Blueprint

## 🎯 Executive Summary & Aligned Specifications

This blueprint captures the complete system architecture and business rules established during the interactive alignment session for **Demo Khelauna**.

---

### 1. 📦 Inventory & Stock Calculation
- **Formula:** `Current Stock = Opening Stock + Total Purchases - Total Sales`
- **Opening Balance Input:** Users can input opening stock directly in the UI or upload a two-column CSV/Excel (`Product Name`, `Opening Stock`).
- **Safety Fallback:** If opening stock is not defined for a product, stock is computed from net movement and clamped at `>= 0` to prevent negative stock distortions.

---

### 2. 🏭 4 Major Parent Suppliers & Lead Time Matrix
Raw Tally imports often use shipment/container names. The system consolidates them into 4 parent supplier profiles:

| Parent Supplier | Aliases Merged | Lead Time | Typical Source | Currency |
|---|---|---|---|---|
| **Huabei** | `Huabei 15`, `Huabei 14`, `SHANTOU HUABEI...`, etc. | **3 Months (90 days)** | China Import | **RMB (¥)** |
| **Rara** | `Rara 2603`, `RARA2026JULY02`, `RARA...`, etc. | **3 Months (90 days)** | China Import | **RMB (¥)** |
| **Shivam** | `Shivam`, `Shivam Plastic`, etc. | **1 Month (30 days)** | Domestic / India | **NPR / INR** |
| **Venkateshwara / Surendar** | `Venkateshwara`, `Surendar Plastic`, etc. | **1 Month (30 days)** | Domestic / India | **NPR / INR** |
| **Local / Factory / Others** | `Factory`, `Stock Milan`, `Delhi SK`, etc. | **7–14 days** (configurable) | Local / Domestic | **NPR** |

---

### 3. 🛒 Purchase Order Calculation Engine
- **Target Forward Coverage:** **2 Months of Sales (60 Days)**
- **Reorder Trigger:** When `Current Stock <= Reorder Point`
  $$\text{Daily Velocity} = \frac{\text{Sales in Lookback Window}}{\text{Lookback Days}}$$
  $$\text{Reorder Point} = \text{Daily Velocity} \times \text{Lead Time Days}$$
  $$\text{Suggested Order Qty} = (\text{Daily Velocity} \times 60) + \max(0, \text{Reorder Point} - \text{Current Stock})$$
- **Lookback Controls:** 30d, 60d, 90d, or prior year's festive period (from `DayBook6.xlsx`).
- **Festive / Seasonal Multiplier:** Optional percentage adjustment slider (e.g. +15% boost for Dashain/Tihar season).
- **Master Carton Rounding:** When `PCS/CTN` is mapped from commercial invoices, quantities can be rounded up to whole cartons.

---

### 4. 💱 Commercial Invoice ETL Pipeline & Instant Database Architecture
- **The Performance Problem:** Supplier Excel files are massive (~28 MB each, ~95 MB total). Re-parsing spreadsheets on page loads or during matching caused 30–60 second latency.
- **The Implemented ETL Solution:**
  1. **One-Time Extraction Pipeline (`invoice_matcher.py`):**
     - Scans `commercial invoices/*.xlsx`.
     - Intelligently extracts unique items, carton pack sizes (`pcs_per_ctn`), and calculates true per-piece RMB unit rates (`rmb_price`).
     - Auto-matches against known Tally items via memory lookup, model code matching, and high-confidence fuzzy similarity.
     - Upserts unique items into the `commercial_invoice_items` database table.
     - Logs price adjustments to `commercial_price_history` whenever newer invoices modify rates.
  2. **Immediate Archival:**
     - Once extracted into the database, processed Excel files are immediately moved into `commercial invoices/archive/`.
     - Leaves the active folder clean and prevents repeated file I/O.
  3. **100% Database-Driven UI (`pages/8_Commercial_Invoices.py`):**
     - Dashboard loads in **~16 ms** directly from the persistent database table.
     - Provides a 1-click **"📥 Ingest & Archive New Commercial Invoices"** button for new incoming shipments.
     - Interactive item matching interface operates purely on database records.
     - Auto-syncs matched items with the active RMB catalog (`product_supplier_mappings`) consumed by the PO Engine.
  4. **RMB Purchase Order Integration:**
     - PO Engine uses active RMB prices and carton sizes for Huabei, Rara, and overseas suppliers.
     - Exports professional formatted Excel workbooks with RMB currency (¥) and carton totals.

---

### 5. 🏷️ Fixed Product Groups Excel
- **Rule:** A fixed Excel file defines `Product Name` ➔ `Product Group`.
- **Defaulting:** Any product not found in the fixed Excel mapping defaults to `'Others'`.
- **Management:** Settings page provides an upload/template download button to update this mapping at any time.

---

### 6. 📒 Classified Party Ledger
- **Party Categories:** Filter by:
  - **Customers (Debtors):** Sales bills and receipts.
  - **Suppliers (Creditors):** Purchase invoices and payments.
  - **Operating Expenses:** Rent, transport, staff, freight, tea/snacks.
- **Statement Features:** Date range filter, search, full narration text, cheque numbers, and running balance calculation.

---

### 7. 📤 Direct Cloud Supabase Ingestion
- Deduplication key: `(date, voucher_type, voucher_no, party_name)`
- Pre-upload comparison: In-file vouchers vs. existing records vs. new inserts.
- Direct write to Supabase with real-time progress bar.
