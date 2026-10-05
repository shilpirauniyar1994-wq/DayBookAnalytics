"""
DayBook Analytics — Product Analytics Page
Sortable product sales table with official product category filters,
opening balance integration, stock balance, Nepali calendar month dropdown,
custom date range filter, and drill-down metrics.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import datetime
import importlib
import db
importlib.reload(db)
from po_engine import estimate_current_stock, to_date_obj
from stksum_parser import OFFICIAL_CATEGORIES
from ui_utils import apply_global_styles, format_currency, format_qty, get_category_badge, get_stock_badge, render_html_table

st.set_page_config(page_title="Product Analytics — DayBook Analytics", page_icon="📦", layout="wide")
apply_global_styles()

st.title("📦 Product Sales & Category Analytics")
st.caption("Inspect sales volume, opening stock, current inventory levels, revenue, and official category groupings")

li_df = db.get_line_items_df()
v_df = db.get_vouchers_df()

if li_df.empty:
    st.warning("No line items found. Please upload a day book file first.")
    st.stop()

# Ensure safe date objects
li_df['date_obj'] = li_df['date'].apply(to_date_obj)
if not v_df.empty:
    v_df['date_obj'] = v_df['date'].apply(to_date_obj)

# Ensure canonical official product group for every line item
from stksum_parser import infer_product_group, get_product_group_mapping_dict
pg_map = get_product_group_mapping_dict()
li_df['product_group'] = li_df['product_name'].apply(lambda p: infer_product_group(p, custom_map=pg_map))

all_valid_dates = pd.concat([li_df['date_obj'].dropna(), v_df['date_obj'].dropna()]).dropna()
if all_valid_dates.empty:
    st.warning("No valid dates found in transactions.")
    st.stop()

global_min_date = all_valid_dates.min()
global_max_date = all_valid_dates.max()

# ---------------------------------------------------------------------------
# NEPALI CALENDAR MONTH DICTIONARY BUILDER
# ---------------------------------------------------------------------------
NEP_MONTH_NAMES = {
    '01': 'Baisakh', '02': 'Jestha', '03': 'Ashadh', '04': 'Shrawan',
    '05': 'Bhadra', '06': 'Ashwin', '07': 'Kartik', '08': 'Mangsir',
    '09': 'Poush', '10': 'Magh', '11': 'Falgun', '12': 'Chaitra'
}

# Build date to Nepali Miti map from vouchers
nepali_months_map = {}
if not v_df.empty and 'miti' in v_df.columns:
    date_miti_pairs = v_df.dropna(subset=['date_obj', 'miti'])[['date_obj', 'miti']].drop_duplicates()
    for _, r in date_miti_pairs.iterrows():
        d = r['date_obj']
        m_str = str(r['miti']).strip()
        parts = m_str.split('-')
        if len(parts) == 3:
            day_s, mo_s, yr_s = parts
            mo_s = mo_s.zfill(2)
            if mo_s in NEP_MONTH_NAMES:
                label = f"{NEP_MONTH_NAMES[mo_s]} {yr_s}"
                if label not in nepali_months_map:
                    nepali_months_map[label] = {
                        'start': d,
                        'end': d,
                        'sort': f"{yr_s}-{mo_s}"
                    }
                else:
                    nepali_months_map[label]['start'] = min(nepali_months_map[label]['start'], d)
                    nepali_months_map[label]['end'] = max(nepali_months_map[label]['end'], d)

sorted_nep_labels = sorted(
    nepali_months_map.keys(),
    key=lambda k: nepali_months_map[k]['sort'],
    reverse=True
)
nepali_month_options = ["All Nepali Months"] + sorted_nep_labels

# ---------------------------------------------------------------------------
# OFFICIAL PRODUCT CATEGORY FILTER BUTTONS (TOP)
# ---------------------------------------------------------------------------
all_groups = ['All'] + list(OFFICIAL_CATEGORIES)

st.subheader("Filter by Official Product Category")

if 'selected_group' not in st.session_state:
    st.session_state.selected_group = 'All'

btn_cols = st.columns(len(all_groups))
for idx, grp in enumerate(all_groups):
    is_active = (st.session_state.selected_group == grp)
    if btn_cols[idx].button(
        f"● {grp}" if is_active else grp,
        key=f"grp_btn_{grp}",
        use_container_width=True,
        type="primary" if is_active else "secondary"
    ):
        st.session_state.selected_group = grp
        st.rerun()

current_group = st.session_state.selected_group
st.info(f"Showing inventory & sales for category: **{current_group}**")

# Search and Channel Filter
c_search, c_channel = st.columns([3, 1.5])
with c_search:
    search_text = st.text_input("🔍 Search product name...", "", placeholder="Type name e.g. 'Golden', 'Bike', 'Gun'...")

with c_channel:
    sales_all = li_df[li_df['voucher_category'] == 'Sales']
    channels = ['All Channels'] + sorted(sales_all['voucher_type'].dropna().unique().tolist())
    selected_channel = st.selectbox("Sales Channel", channels)

# Filter Dataset by Category, Channel, Search
base_df = li_df.copy()
if current_group != 'All':
    base_df = base_df[base_df['product_group'] == current_group]

if selected_channel != 'All Channels':
    base_df = base_df[base_df['voucher_type'] == selected_channel]

if search_text:
    base_df = base_df[base_df['product_name'].str.contains(search_text, case=False, na=False)]

st.markdown("---")

# ---------------------------------------------------------------------------
# DATE FILTER & NEPALI CALENDAR MONTH DROPDOWN (JUST ABOVE TABLE)
# ---------------------------------------------------------------------------
st.subheader("📅 Date Range & Nepali Calendar Period")
st.caption("Filter product performance by Nepali calendar months (Bikram Sambat) or pick a custom English date range.")

# Manage filter session states
if 'active_nep_month' not in st.session_state:
    st.session_state.active_nep_month = "All Nepali Months"

col_nepali, col_dates, col_reset = st.columns([2.5, 2.5, 1])

with col_nepali:
    selected_nep_month = st.selectbox(
        "🇳🇵 Nepali Calendar Month (B.S.)",
        nepali_month_options,
        index=nepali_month_options.index(st.session_state.active_nep_month) if st.session_state.active_nep_month in nepali_month_options else 0,
        key="nep_month_picker"
    )

# Sync default date range based on selected Nepali month
if selected_nep_month != "All Nepali Months" and selected_nep_month in nepali_months_map:
    default_start = nepali_months_map[selected_nep_month]['start']
    default_end = nepali_months_map[selected_nep_month]['end']
else:
    default_start = global_min_date
    default_end = global_max_date

# Safe bounds clamping to prevent StreamlitValueAboveMaxError
default_start = max(global_min_date, min(default_start, global_max_date))
default_end = max(global_min_date, min(default_end, global_max_date))
if default_start > default_end:
    default_start = default_end

with col_dates:
    chosen_dates = st.date_input(
        "📆 English Date Range",
        value=(default_start, default_end),
        min_value=global_min_date,
        max_value=max(global_max_date, default_end),
        key=f"date_range_picker_{selected_nep_month}"
    )

with col_reset:
    st.write("")
    st.write("")
    if st.button("🔄 Reset Dates", use_container_width=True):
        st.session_state.active_nep_month = "All Nepali Months"
        st.rerun()

# Determine active start and end dates
if isinstance(chosen_dates, (tuple, list)) and len(chosen_dates) == 2:
    start_d, end_d = chosen_dates
elif isinstance(chosen_dates, (tuple, list)) and len(chosen_dates) == 1:
    start_d = end_d = chosen_dates[0]
else:
    start_d, end_d = default_start, default_end

# Apply Date Filter
period_mask = (base_df['date_obj'] >= start_d) & (base_df['date_obj'] <= end_d)
period_df = base_df[period_mask].copy()

# Sales and Purchases in selected period
period_sales = period_df[period_df['voucher_category'] == 'Sales'].copy()
period_purchases = period_df[period_df['voucher_category'] == 'Purchase'].copy()

# Aggregate product sales metrics for the period
if not period_sales.empty:
    sales_summary = period_sales.groupby(['product_name', 'product_group']).agg(
        total_qty=('quantity', 'sum'),
        total_revenue=('amount', 'sum'),
        avg_rate=('rate', 'mean'),
        min_rate=('rate', 'min'),
        max_rate=('rate', 'max'),
        transactions=('voucher_no', 'count')
    ).reset_index()

    sales_summary.loc[:, 'avg_rate'] = sales_summary['avg_rate'].round(2)
    sales_summary.loc[:, 'total_revenue'] = sales_summary['total_revenue'].round(2)
else:
    sales_summary = pd.DataFrame(columns=[
        'product_name', 'product_group', 'total_qty', 'total_revenue', 'avg_rate', 'min_rate', 'max_rate', 'transactions'
    ])

# Aggregate product purchases for the period
if not period_purchases.empty:
    purch_summary = period_purchases.groupby('product_name')['quantity'].sum().rename('period_purchased')
else:
    purch_summary = pd.Series(dtype=float, name='period_purchased')

# Load lifetime stock balance from StkSum.xlsx + purchases - sales
stock_df = estimate_current_stock(li_df)

# Merge sales summary, period purchases, and lifetime stock balance
if not sales_summary.empty:
    product_summary = sales_summary.merge(
        stock_df[['product_name', 'opening_qty', 'est_stock', 'opening_value']],
        on='product_name',
        how='left'
    )
    product_summary = product_summary.merge(
        purch_summary,
        on='product_name',
        how='left'
    )
    product_summary['opening_qty'] = product_summary['opening_qty'].fillna(0.0)
    product_summary['period_purchased'] = product_summary['period_purchased'].fillna(0.0)
    product_summary['est_stock'] = product_summary['est_stock'].fillna(0.0)
else:
    product_summary = pd.DataFrame()

# ---------------------------------------------------------------------------
# PERIOD SUMMARY METRIC CARDS
# ---------------------------------------------------------------------------
k1, k2, k3, k4, k5 = st.columns(5)
if not product_summary.empty:
    k1.metric("Products Sold in Period", f"{len(product_summary):,} items")
    tot_sold = product_summary['total_qty'].sum()
    k2.metric("Period Units Sold", f"{tot_sold:,.0f} units")
    tot_rev = product_summary['total_revenue'].sum()
    k3.metric("Period Sales Revenue", format_currency(tot_rev), help=f"Exact Revenue: Rs. {tot_rev:,.2f}")
    tot_period_purch = product_summary['period_purchased'].sum()
    k4.metric("Period Purchased Units", f"{tot_period_purch:,.0f} units")
    tot_est_stock = product_summary['est_stock'].sum()
    k5.metric("Est. Current Stock", f"{tot_est_stock:,.0f} units")
else:
    st.info(f"No transactions found for the period {start_d} to {end_d} under category '{current_group}'.")

st.markdown("---")

# ---------------------------------------------------------------------------
# COMPREHENSIVE PRODUCT INVENTORY & SALES TABLE
# ---------------------------------------------------------------------------
st.subheader("📋 Comprehensive Product Inventory & Sales Table")
date_desc = f"Period: {start_d} to {end_d}" + (f" ({selected_nep_month})" if selected_nep_month != "All Nepali Months" else "")
st.caption(f"Showing performance for **{date_desc}**. Includes Opening Balance from `StkSum.xlsx` + Purchases - Sales = Est. Current Stock. Click headers to sort.")

if not product_summary.empty:
    base_display_df = product_summary[[
        'product_name', 'product_group',
        'total_qty', 'total_revenue', 'est_stock', 'period_purchased',
        'avg_rate', 'transactions'
    ]].copy()

    # Search filter and Table Controls
    tbl_search = st.text_input("🔍 Search product name...", "", key="prod_tbl_search", placeholder="Type to filter products by name...")

    # Filter by search
    if tbl_search:
        filtered_display = base_display_df[base_display_df['product_name'].str.contains(tbl_search, case=False, na=False)].copy()
    else:
        filtered_display = base_display_df.copy()

    c_sort, c_order, c_size, c_view = st.columns([2, 1.5, 1.2, 2.3])
    with c_sort:
        sort_field = st.selectbox(
            "Sort Table By",
            ["Period Revenue", "Period Qty Sold", "Est. Current Stock", "Period Purchase", "Product Name"],
            index=0,
            key="tbl_sort_field"
        )
    with c_order:
        sort_order = st.radio("Order", ["Highest First (Desc)", "Lowest First (Asc)"], horizontal=True, key="tbl_sort_order")

    with c_size:
        page_size_choice = st.selectbox("Rows per page", [25, 50, 100, "All"], index=0, key="tbl_page_size")

    with c_view:
        table_view_mode = st.radio(
            "Table View Mode",
            ["🎨 High-Contrast Clean Table", "📊 Interactive Data Grid"],
            horizontal=True,
            key="tbl_view_mode"
        )

    sort_col_map = {
        "Period Revenue": "total_revenue",
        "Period Qty Sold": "total_qty",
        "Est. Current Stock": "est_stock",
        "Period Purchase": "period_purchased",
        "Product Name": "product_name"
    }
    target_sort_col = sort_col_map.get(sort_field, "total_revenue")
    is_asc = (sort_order == "Lowest First (Asc)")

    sorted_df = filtered_display.sort_values(target_sort_col, ascending=is_asc).reset_index(drop=True)
    total_table_items = len(sorted_df)

    ordered_cols = ['product_name', 'total_qty', 'total_revenue', 'est_stock', 'period_purchased', 'product_group', 'avg_rate', 'transactions']
    headers = [
        ("Product Name", "left"),
        ("Period Qty Sold", "right"),
        ("Period Revenue (Rs.)", "right"),
        ("Est. Current Stock", "right"),
        ("Period Purchase", "right"),
        ("Category", "left"),
        ("Avg Rate (Rs.)", "right"),
        ("# Sales", "center")
    ]

    # Quick download CSV
    csv_bytes = sorted_df[ordered_cols].to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Download Table as CSV",
        data=csv_bytes,
        file_name=f"Comprehensive_Product_Sales_{start_d}_to_{end_d}.csv",
        mime="text/csv",
        key="prod_csv_download"
    )

    if table_view_mode == "🎨 High-Contrast Clean Table":
        if 'prod_tbl_page' not in st.session_state:
            st.session_state.prod_tbl_page = 1

        if page_size_choice == "All":
            page_size = max(1, total_table_items)
            total_pages = 1
            current_page = 1
        else:
            page_size = int(page_size_choice)
            total_pages = max(1, (total_table_items + page_size - 1) // page_size)
            if st.session_state.prod_tbl_page > total_pages:
                st.session_state.prod_tbl_page = 1
            current_page = st.session_state.prod_tbl_page

        start_idx = (current_page - 1) * page_size
        end_idx = min(start_idx + page_size, total_table_items)
        page_df = sorted_df.iloc[start_idx:end_idx].reset_index(drop=True)

        rows_html = []
        for _, r in page_df.iterrows():
            name_cell = f"<td class='tbl-cell-bold' style='padding:11px 14px; font-size:14.5px;'>{r['product_name']}</td>"
            qty_cell = f"<td class='tbl-cell-main' style='padding:11px 14px; text-align:right; font-size:14px;'>{r['total_qty']:,.0f}</td>"
            rev_cell = f"<td class='tbl-val-sales' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {r['total_revenue']:,.2f}</td>"
            s_badge = get_stock_badge(r['est_stock'])
            stk_cell = f"<td style='padding:11px 14px; text-align:right;'>{s_badge}</td>"
            pur_cell = f"<td class='tbl-cell-muted' style='padding:11px 14px; text-align:right; font-size:14px;'>{r['period_purchased']:,.0f}</td>"
            c_badge = get_category_badge(r['product_group'])
            cat_cell = f"<td style='padding:11px 14px;'>{c_badge}</td>"
            rate_cell = f"<td class='tbl-cell-main' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {r['avg_rate']:,.2f}</td>"
            tx_cell = f"<td style='padding:11px 14px; text-align:center;'><span class='tbl-pill-count'>{r['transactions']:,.0f}</span></td>"

            row_str = f"<tr>{name_cell}{qty_cell}{rev_cell}{stk_cell}{pur_cell}{cat_cell}{rate_cell}{tx_cell}</tr>"
            rows_html.append(row_str)

        render_html_table(headers, rows_html, max_height=620)

        if total_pages > 1:
            st.write("")
            pg_col1, pg_col2, pg_col3 = st.columns([1.5, 3, 1.5])
            with pg_col1:
                if st.button("⬅️ Previous Page", disabled=(current_page <= 1), use_container_width=True, key="prev_pg_btn"):
                    st.session_state.prod_tbl_page = max(1, current_page - 1)
                    st.rerun()
            with pg_col2:
                st.markdown(
                    f"<div style='text-align:center; padding-top:8px; font-weight:600; color:#475569; font-size:14px;'>"
                    f"Page {current_page} of {total_pages} &nbsp;•&nbsp; Showing {start_idx+1:,}–{end_idx:,} of {total_table_items:,} items</div>",
                    unsafe_allow_html=True
                )
            with pg_col3:
                if st.button("Next Page ➡️", disabled=(current_page >= total_pages), use_container_width=True, key="next_pg_btn"):
                    st.session_state.prod_tbl_page = min(total_pages, current_page + 1)
                    st.rerun()

    else:
        # Render Enhanced Interactive Data Grid
        st.dataframe(
            sorted_df[ordered_cols],
            column_config={
                'product_name': st.column_config.TextColumn('Product Name', width=340),
                'total_qty': st.column_config.NumberColumn('Period Qty Sold', format='%,.0f', width=150),
                'total_revenue': st.column_config.NumberColumn('Period Revenue', format='Rs. %,.2f', width=180),
                'est_stock': st.column_config.NumberColumn('Est. Current Stock', format='%,.0f', width=160),
                'period_purchased': st.column_config.NumberColumn('Period Purchase', format='%,.0f', width=150),
                'product_group': st.column_config.TextColumn('Category', width=160),
                'avg_rate': st.column_config.NumberColumn('Avg Rate', format='Rs. %,.2f', width=140),
                'transactions': st.column_config.NumberColumn('# Sales', format='%,.0f', width=110),
            },
            height=620,
            use_container_width=True,
            hide_index=True
        )

st.markdown("---")

# ---------------------------------------------------------------------------
# TOP 20 CHART (RESPECTS ACTIVE PERIOD)
# ---------------------------------------------------------------------------
if not product_summary.empty:
    st.subheader(f"📊 Top 20 Performing Products ({date_desc})")
    chart_metric = st.radio("Rank Top 20 by:", ["Period Revenue (Rs.)", "Period Quantity Sold", "Current Stock (Units)"], horizontal=True)

    if "Revenue" in chart_metric:
        sort_col = 'total_revenue'
    elif "Quantity" in chart_metric:
        sort_col = 'total_qty'
    else:
        sort_col = 'est_stock'

    top20 = product_summary.sort_values(sort_col, ascending=False).head(20)

    fig_top = px.bar(
        top20,
        x=sort_col,
        y='product_name',
        orientation='h',
        color='product_group',
        title=f"Top 20 Products by {chart_metric}",
        labels={sort_col: chart_metric, 'product_name': 'Product'}
    )
    fig_top.update_layout(yaxis=dict(autorange="reversed"), height=500, margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig_top, use_container_width=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# DETAILED PRODUCT DRILL-DOWN
# ---------------------------------------------------------------------------
st.subheader("🔎 Product Deep Dive")
# Populate prods_list with all available products from catalog & inventory
available_prods = set()
if 'product_name' in base_df.columns:
    available_prods.update(base_df['product_name'].dropna().unique().tolist())
if not stock_df.empty and 'product_name' in stock_df.columns:
    available_prods.update(stock_df['product_name'].dropna().unique().tolist())

prods_list = sorted([str(p).strip() for p in available_prods if str(p).strip()])
if prods_list:
    options = ["All Products"] + prods_list
    selected_prod = st.selectbox("Select Product to Inspect Details", options)

    is_all = (selected_prod == "All Products")
    if is_all:
        prod_txns = period_sales.copy()
    else:
        prod_txns = period_sales[period_sales['product_name'] == selected_prod].copy()

    if prod_txns.empty:
        st.info(f"No sales transactions recorded for **{selected_prod}** within the active date period.")
        if not is_all and not stock_df.empty and 'product_name' in stock_df.columns:
            p_stock = stock_df[stock_df['product_name'] == selected_prod]
            if not p_stock.empty and 'est_stock' in p_stock.columns:
                curr_stk = p_stock['est_stock'].iloc[0]
                st.caption(f"📦 Current Estimated Stock for **{selected_prod}**: **{curr_stk:,.0f} units**")
    else:
        # Summary Metrics Row for Deep Dive
        m_rev = prod_txns['amount'].sum()
        m_qty = prod_txns['quantity'].sum()
        m_buyers = prod_txns['party_name'].nunique()
        m_txns = len(prod_txns)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Scope", "All Products" if is_all else selected_prod)
        k2.metric("Period Revenue", format_currency(m_rev))
        k3.metric("Period Qty Sold", format_qty(m_qty))
        k4.metric("Active Buyers / Sales", f"{m_buyers:,} buyers ({m_txns:,} sales)")

        d1, d2 = st.columns(2)
        with d1:
            if 'month' not in prod_txns.columns or prod_txns['month'].isna().all():
                prod_txns['month'] = prod_txns['date'].apply(lambda d: d.strftime('%Y-%m') if hasattr(d, 'strftime') else str(d)[:7])
            monthly_prod = prod_txns.groupby('month').agg(
                revenue=('amount', 'sum'),
                qty=('quantity', 'sum')
            ).reset_index()

            chart_title = "Monthly Revenue Across All Products in Period" if is_all else f"Monthly Revenue for {selected_prod} in Period"
            fig_m = px.bar(monthly_prod, x='month', y='revenue', title=chart_title, text_auto='.2s')
            st.plotly_chart(fig_m, use_container_width=True)

        with d2:
            buyer_title = "**Top Customers Across All Products in Period**" if is_all else f"**Top Customers Buying {selected_prod} in Period**"
            st.markdown(buyer_title)
            buyer_agg = prod_txns.groupby('party_name').agg(
                total_purchased=('quantity', 'sum'),
                total_spent=('amount', 'sum')
            ).reset_index().sort_values('total_spent', ascending=False).head(10)

            st.dataframe(
                buyer_agg,
                column_config={
                    'party_name': 'Customer / Buyer',
                    'total_purchased': st.column_config.NumberColumn('Qty Bought', format='%,.0f'),
                    'total_spent': st.column_config.NumberColumn('Total (Rs.)', format='Rs. %,.2f'),
                },
                use_container_width=True,
                hide_index=True
            )
