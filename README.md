---
title: Daybook WhatsApp Assistant
emoji: 📱
colorFrom: green
colorTo: emerald
sdk: docker
app_port: 7860
pinned: false
---

# 📊 DayBook Analytics — Demo Khelauna

A high-performance analytics system and procurement assistant built for **Demo Khelauna** (wholesale toys and party supplies), parsing Tally Day Book exports and connecting to **Supabase PostgreSQL** with automated deduplication and smart Purchase Order preparation.

---

## 🌟 Key Features

1. **📈 Monthly Sales, Purchases & Expenses**
   - High-level KPIs: Total Sales, Purchases, Receipts, Expenses, and Net Margin.
   - Interactive Plotly multi-category monthly bar chart and daily sales velocity line chart.
   - Financial breakdown table by period.

2. **📒 Party Ledger & Accounts**
   - Comprehensive customer and supplier statements with **full narration text and cheque info**.
   - Chronological running balances (`Dr` receivable vs `Cr` payable).
   - "All Parties Balance Summary" table showing outstanding balances and last active dates.

3. **📦 Product Analytics**
   - Table of all products with Sales Volume, Revenue, Average Rate, and Frequency.
   - **One-click Product Group Buttons** at the top (`Balls`, `Candles`, `Cars`, `Clay`, `Cycles`, `Factory Items`, `Guns`, etc.).
   - Interactive top-20 chart and product drill-down (monthly sales & top buyers).

4. **⏳ Aging Analytics**
   - Stock movement tracking based on purchases vs sales.
   - Classification into aging buckets: `0-30 days`, `31-60 days`, `61-90 days`, `90+ days`, and `Never Sold`.
   - **Slow-moving inventory alerts** (>60 days with stock) and dead stock list.

5. **🛒 Purchase Order Preparation**
   - Auto-calculates daily and weekly sales velocity over configurable lookback windows (15/30/60/90 days).
   - Evaluates stock against **Reorder Points** based on delivery lead times and safety stock buffers.
   - Groups draft POs by preferred supplier with **interactive editable order quantities**.
   - **Export to formatted Excel PO** with one click.

6. **📤 Upload DayBook Data (Clean Deduplication)**
   - Upload new Tally Day Book exports (`.xlsx`).
   - **Preview & Comparison step** showing:
     - Total vouchers in file
     - Overlapping records already in the database (skipped)
     - New vouchers (inserted)
     - New products discovered
   - Tracks past imports in the `upload_history` table.

7. **⚙️ Settings & Lead Times**
   - Customize global default lead time (days) and safety stock buffer (days).
   - Define custom per-supplier overrides (e.g. Factory = 3 days, Indian suppliers = 14 days, Overseas imports = 35 days).
   - Category group overrides and supplier catalog management.

---

## 🚀 Quick Start

### 1. Launch App (Local Offline Mode)
You can run the app immediately using the local `DayBook.xlsx` exports already in the folder:

```powershell
python -m streamlit run app.py
```

### 2. Connect to Supabase Cloud Database (Optional)
To sync data across devices and maintain persistent cloud storage:

1. Copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Open `.env` and fill in your Supabase project credentials:
   ```env
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_KEY=your-anon-or-service-role-key
   ```
3. Run `schema.sql` in your **Supabase Dashboard -> SQL Editor**.
4. Open the **Upload Data** page in the dashboard and click **Process & Import Data** to populate your cloud database.
