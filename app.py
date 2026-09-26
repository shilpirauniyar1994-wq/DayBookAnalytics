"""
DayBook Analytics — Main Application Entry Point
Demo Khelauna — Wholesale Toys & Party Supplies Analytics Dashboard
"""

import streamlit as st
import pandas as pd
import datetime
import importlib
import db
importlib.reload(db)
from ui_utils import apply_global_styles, format_currency, render_html_table

st.set_page_config(
    page_title="DayBook Analytics — Demo Khelauna",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Apply responsive metric typography & styling
apply_global_styles()

st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #475569;
        margin-bottom: 1.2rem;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">📊 DayBook Analytics</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Demo Khelauna — Wholesale Toys & Party Supplies Analytics System</div>', unsafe_allow_html=True)

# Supabase vs Local Mode Badge
is_connected = db.is_supabase_configured()
if is_connected:
    st.success("🟢 Connected to Supabase Cloud Database (Live Mode)")
else:
    st.info("ℹ️ Running in Local Mode with DayBook exports. Add Supabase credentials to `.env` to enable cloud synchronization.")

# Load core datasets
with st.spinner("Loading analytics data..."):
    v_df = db.get_vouchers_df()
    li_df = db.get_line_items_df()

if v_df.empty:
    st.warning("⚠️ No data loaded yet. Please place DayBook exports in `daybooks/` or use the **Import Tally Day Book** page.")
    st.stop()

# Overall KPI Metrics
total_vouchers = len(v_df)
sales_vouchers = v_df[v_df['voucher_category'] == 'Sales']
purchases = v_df[v_df['voucher_category'] == 'Purchase']
payments = v_df[v_df['voucher_category'] == 'Payment']
receipts = v_df[v_df['voucher_category'] == 'Receipt']

total_sales_val = sales_vouchers['debit_amount'].sum()
total_purchase_val = purchases['credit_amount'].sum()
total_payment_val = payments['debit_amount'].sum()
total_receipt_val = receipts['credit_amount'].sum()
unique_prods = li_df['product_name'].nunique()
unique_parties = v_df['party_name'].nunique()

col_kpi_head, col_fmt_toggle = st.columns([4, 1.2])
with col_kpi_head:
    st.subheader("Key Business Metrics")
with col_fmt_toggle:
    compact_view = st.checkbox("Compact (Cr / Lakh)", value=True, help="Toggle between compact (e.g. Rs. 6.92 Cr) and exact full amounts")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(
    "Total Sales",
    format_currency(total_sales_val, compact=compact_view),
    f"{len(sales_vouchers):,} orders",
    help=f"Full Sales Amount: Rs. {total_sales_val:,.2f}"
)
c2.metric(
    "Total Purchases",
    format_currency(total_purchase_val, compact=compact_view),
    f"{len(purchases):,} bills",
    help=f"Full Purchases Amount: Rs. {total_purchase_val:,.2f}"
)
c3.metric(
    "Receipts In",
    format_currency(total_receipt_val, compact=compact_view),
    f"{len(receipts):,} txns",
    help=f"Full Receipts Amount: Rs. {total_receipt_val:,.2f}"
)
c4.metric(
    "Expenses / Payments",
    format_currency(total_payment_val, compact=compact_view),
    f"{len(payments):,} txns",
    help=f"Full Payments Amount: Rs. {total_payment_val:,.2f}"
)
c5.metric(
    "Catalog Size",
    f"{unique_prods:,} products",
    f"{unique_parties:,} parties"
)

st.markdown("---")

# Feature Highlights & Quick Links
st.subheader("Explore Analytics Modules")

row1_col1, row1_col2 = st.columns(2)

with row1_col1:
    st.markdown("""
    ### 📈 [1. Monthly Summary](Monthly_Summary)
    - Consolidated monthly breakdown of **Sales, Purchases, Expenses & Receipts**
    - Multi-month trend charts & daily cashflow analysis
    - Net monthly profit and volume metrics
    """)

    st.markdown("""
    ### 📒 [2. Party Ledger](Party_Ledger)
    - Complete customer & supplier transaction history
    - **Full narration text** and cheque details for every transaction
    - Real-time running balance calculation & outstanding ledger totals
    """)

    st.markdown("""
    ### 📦 [3. Product Analytics](Product_Analytics)
    - Sales revenue, quantity, average selling rates, and frequencies
    - **6 Official Product Categories:** Big Toys, Birthday Items, Factory Item, Fancy Toys, General, Indian Item
    - Sortable table with **Opening Stock + Purchases - Sales = Est. Current Stock**
    """)

with row1_col2:
    st.markdown("""
    ### ⏳ [4. Aging Analytics](Aging_Analytics)
    - Full inventory health with starting balances from `StkSum.xlsx`
    - Aging buckets: `0-30 days`, `31-60 days`, `61-90 days`, `91-180 days`, `181-360 days`, `360+ days`, `Never Sold`
    - **Slow-moving stuck units breakdown** by the 6 official business categories
    """)

    st.markdown("""
    ### 🛒 [5. Purchase Orders](Purchase_Orders)
    - Automated sales velocity tracking (daily & weekly run-rates)
    - **Lead time & safety stock aware** reorder point calculation
    - Grouped draft purchase orders with editable quantities & **Excel download**
    """)

    st.markdown("""
    ### 📤 [6. Upload Data](Upload_Data) & ⚙️ [7. Settings](Settings)
    - Safe day book imports with **3-step preview & overlap deduplication**
    - Configure supplier and group lead times, safety stocks, and order parameters
    """)

    st.markdown("""
    ### 💱 [8. Commercial Invoices](Commercial_Invoices)
    - Scan overseas supplier invoices, extract **RMB prices & carton pack sizes**
    - Auto-match with Tally products & **auto-archive completed invoices**
    """)

st.markdown("---")

# Quick Recent Activity Preview
st.subheader("📋 Recent Voucher Transactions")
st.caption("Latest 10 transactions recorded across sales, purchases, and payments")

recent_df = v_df.sort_values('date', ascending=False).head(10)[
    ['date', 'voucher_type', 'voucher_no', 'party_name', 'debit_amount', 'credit_amount', 'narration']
].copy()

headers = [
    ("Date", "left"),
    ("Voucher Type", "left"),
    ("Vch #", "left"),
    ("Party / Particulars", "left"),
    ("Debit (Rs.)", "right"),
    ("Credit (Rs.)", "right"),
    ("Narration", "left")
]

rows_html = []
for _, r in recent_df.iterrows():
    dr_str = f"Rs. {r['debit_amount']:,.2f}" if r['debit_amount'] > 0 else "—"
    cr_str = f"Rs. {r['credit_amount']:,.2f}" if r['credit_amount'] > 0 else "—"
    narr = str(r['narration']) if pd.notna(r['narration']) else ""

    rows_html.append(f"""<tr>
        <td class='tbl-cell-main' style='padding:11px 14px; font-size:13.5px;'>{r['date']}</td>
        <td style='padding:11px 14px;'><span class='tbl-pill-vch'>{r['voucher_type']}</span></td>
        <td class='tbl-cell-bold' style='padding:11px 14px; font-size:13px;'>{r['voucher_no']}</td>
        <td class='tbl-cell-main' style='padding:11px 14px; font-size:14px;'>{r['party_name']}</td>
        <td class='tbl-cell-bold' style='padding:11px 14px; text-align:right; font-size:13.5px;'>{dr_str}</td>
        <td class='tbl-val-sales' style='padding:11px 14px; text-align:right; font-size:13.5px;'>{cr_str}</td>
        <td class='tbl-cell-muted' style='padding:11px 14px; font-size:13px; max-width:280px;'>{narr}</td>
    </tr>""")

render_html_table(headers, rows_html, max_height=450)
