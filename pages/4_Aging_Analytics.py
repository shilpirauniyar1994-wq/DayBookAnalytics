"""
DayBook Analytics — Product Aging Analytics Page
Tracks stock turnover, days since last sale, aging buckets, and slow-moving/dead stock alerts
across the 6 official product categories, with Opening Stock + Purchases - Sales balance.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import datetime
import db
import importlib
import po_engine
importlib.reload(po_engine)
importlib.reload(db)
from po_engine import calculate_aging
from stksum_parser import OFFICIAL_CATEGORIES
from ui_utils import (
    apply_global_styles, format_currency, format_qty,
    get_category_badge, get_stock_badge, get_aging_badge, render_html_table
)

st.set_page_config(page_title="Aging Analytics — DayBook Analytics", page_icon="⏳", layout="wide")
apply_global_styles()

st.title("⏳ Product Aging & Inventory Health")
st.caption("Identify slow-moving items, dead inventory, and days since last stock movement across official categories")

li_df = db.get_line_items_df()

if li_df.empty:
    st.warning("No line items found. Please upload a day book file first.")
    st.stop()

# Compute aging metrics incorporating opening stock
with st.spinner("Calculating inventory aging across all products..."):
    aging_df = calculate_aging(li_df)

if aging_df.empty:
    st.info("Insufficient purchase or sales data to calculate inventory aging.")
    st.stop()

# Summary Metrics
total_products = len(aging_df)
in_stock_items = aging_df[aging_df['est_stock'] > 0]
slow_moving = aging_df[(aging_df['est_stock'] > 0) & (aging_df['days_since_sale'] > 60)]
dead_stock = aging_df[(aging_df['est_stock'] > 0) & (aging_df['days_since_sale'] == 9999)]
fast_moving = aging_df[(aging_df['days_since_sale'] <= 30)]

m1, m2, m3, m4 = st.columns(4)
m1.metric("Catalog Tracked", f"{total_products} items")
m2.metric("Active Selling (<=30d)", f"{len(fast_moving)} items", "Fast moving")
m3.metric("Slow Moving (>60d)", f"{len(slow_moving)} items", f"Stock: {slow_moving['est_stock'].sum():,.0f} units", delta_color="inverse")
m4.metric("Dead Stock (Never Sold)", f"{len(dead_stock)} items", f"Stock: {dead_stock['est_stock'].sum():,.0f} units", delta_color="inverse")

st.markdown("---")

# Visual Charts
c1, c2 = st.columns([2, 3])

with c1:
    st.subheader("Inventory Distribution by Aging Bucket")
    bucket_counts = aging_df['aging_bucket'].value_counts().reset_index()
    bucket_counts.columns = ['Bucket', 'Product Count']

    color_map = {
        '0-30 days': '#10B981',
        '31-60 days': '#3B82F6',
        '61-90 days': '#F59E0B',
        '91-180 days': '#F97316',
        '181-360 days': '#EF4444',
        '360+ days': '#BE185D',
        'Never Sold': '#8B5CF6'
    }

    fig_pie = px.pie(
        bucket_counts,
        values='Product Count',
        names='Bucket',
        color='Bucket',
        color_discrete_map=color_map,
        hole=0.4
    )
    fig_pie.update_layout(height=350, margin=dict(l=20, r=20, t=30, b=20))
    st.plotly_chart(fig_pie, use_container_width=True)

with c2:
    st.subheader("Slow Moving Products by Category")
    if not slow_moving.empty:
        group_slow = slow_moving.groupby('product_group')['est_stock'].sum().reset_index().sort_values('est_stock', ascending=False)
        fig_bar = px.bar(
            group_slow,
            x='est_stock',
            y='product_group',
            orientation='h',
            title="Estimated Stuck Stock Units by Official Category",
            labels={'est_stock': 'Unsold Units', 'product_group': 'Category'},
            color='product_group',
            color_discrete_sequence=['#F59E0B', '#EF4444', '#3B82F6', '#10B981', '#8B5CF6', '#EC4899']
        )
        fig_bar.update_layout(yaxis=dict(autorange="reversed"), height=350, margin=dict(l=20, r=20, t=30, b=20), showlegend=False)
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.success("No slow moving stock detected!")

st.markdown("---")

# Filters for Aging Table
st.subheader("📋 Inventory Aging Detail Table")
st.caption("Inspect stock aging status, unsold units, and movement velocity. Click headers or controls to sort.")

f_col1, f_col2, f_col3 = st.columns([2, 2, 2])
with f_col1:
    all_bucket_order = ['0-30 days', '31-60 days', '61-90 days', '91-180 days', '181-360 days', '360+ days', 'Never Sold']
    present_buckets = [b for b in all_bucket_order if b in aging_df['aging_bucket'].values]
    # Add any extra unexpected bucket
    for b in aging_df['aging_bucket'].unique():
        if b not in present_buckets:
            present_buckets.append(b)
    bucket_options = ['All Buckets'] + present_buckets
    selected_bucket = st.selectbox("Filter Aging Bucket", bucket_options, key="aging_bucket_sel")

with f_col2:
    group_options = ['All Categories'] + list(OFFICIAL_CATEGORIES)
    selected_group = st.selectbox("Filter Category", group_options, key="aging_group_sel")

with f_col3:
    stock_only = st.checkbox("Show only items with positive stock (Est. Stock > 0)", value=True, key="aging_stock_only")

# Search and Sorting Controls
c_srch, c_sort, c_order, c_size, c_view = st.columns([2.5, 2, 1.5, 1.2, 2.3])
with c_srch:
    aging_search = st.text_input("🔍 Search product name...", "", key="aging_search_input", placeholder="Filter by product name...")
with c_sort:
    aging_sort_col = st.selectbox(
        "Sort By",
        ["Days Since Last Sale", "Est. Stock Remaining", "Purchased Qty", "Sold Qty", "Product Name"],
        index=0,
        key="aging_sort_field"
    )
with c_order:
    aging_order = st.radio("Order", ["Highest First (Desc)", "Lowest First (Asc)"], horizontal=True, key="aging_order_radio")
with c_size:
    aging_page_size_choice = st.selectbox("Rows per page", [25, 50, 100, "All"], index=0, key="aging_page_size")
with c_view:
    aging_view_mode = st.radio(
        "Table View Mode",
        ["🎨 High-Contrast Clean Table", "📊 Interactive Data Grid"],
        horizontal=True,
        key="aging_view_mode"
    )

# Apply Table Filters
display_aging = aging_df.copy()
if selected_bucket != 'All Buckets':
    display_aging = display_aging[display_aging['aging_bucket'] == selected_bucket]

if selected_group != 'All Categories':
    display_aging = display_aging[display_aging['product_group'] == selected_group]

if stock_only:
    display_aging = display_aging[display_aging['est_stock'] > 0]

if aging_search:
    display_aging = display_aging[display_aging['product_name'].str.contains(aging_search, case=False, na=False)]

# Sort
aging_sort_map = {
    "Days Since Last Sale": "days_since_sale",
    "Est. Stock Remaining": "est_stock",
    "Purchased Qty": "qty_purchased",
    "Sold Qty": "qty_sold",
    "Product Name": "product_name"
}
target_aging_sort = aging_sort_map.get(aging_sort_col, "days_since_sale")
is_aging_asc = (aging_order == "Lowest First (Asc)")
sorted_aging = display_aging.sort_values(target_aging_sort, ascending=is_aging_asc).reset_index(drop=True)
total_aging_items = len(sorted_aging)

aging_cols = [
    'product_name', 'product_group', 'est_stock', 'days_since_sale',
    'aging_bucket', 'qty_purchased', 'qty_sold', 'opening_qty', 'last_sale'
]

# CSV Download
st.download_button(
    label="📥 Download Table as CSV",
    data=sorted_aging[aging_cols].to_csv(index=False).encode('utf-8'),
    file_name=f"Inventory_Aging_{datetime.date.today().strftime('%Y%m%d')}.csv",
    mime="text/csv",
    key="aging_csv_download"
)

if aging_view_mode == "🎨 High-Contrast Clean Table":
    if 'aging_tbl_page' not in st.session_state:
        st.session_state.aging_tbl_page = 1

    if aging_page_size_choice == "All":
        a_page_size = max(1, total_aging_items)
        a_total_pages = 1
        a_current_page = 1
    else:
        a_page_size = int(aging_page_size_choice)
        a_total_pages = max(1, (total_aging_items + a_page_size - 1) // a_page_size)
        if st.session_state.aging_tbl_page > a_total_pages:
            st.session_state.aging_tbl_page = 1
        a_current_page = st.session_state.aging_tbl_page

    a_start_idx = (a_current_page - 1) * a_page_size
    a_end_idx = min(a_start_idx + a_page_size, total_aging_items)
    page_aging_df = sorted_aging.iloc[a_start_idx:a_end_idx].reset_index(drop=True)

    headers = [
        ("Product Name", "left"),
        ("Category", "left"),
        ("Est. Stock Remaining", "right"),
        ("Days Since Sale", "right"),
        ("Aging Bucket", "center"),
        ("Purchased Qty", "right"),
        ("Sold Qty", "right"),
        ("Opening Stock", "right"),
        ("Last Sale Date", "center")
    ]

    rows_html = []
    for _, r in page_aging_df.iterrows():
        c_badge = get_category_badge(r['product_group'])
        s_badge = get_stock_badge(r['est_stock'])
        a_badge = get_aging_badge(r['aging_bucket'])
        days_str = f"{r['days_since_sale']:.0f} d" if r['days_since_sale'] < 9000 else "Never"
        last_d_str = str(r['last_sale']) if pd.notna(r['last_sale']) else "—"

        rows_html.append(f"""<tr>
            <td class='tbl-cell-bold' style='padding:11px 14px; font-size:14.5px;'>{r['product_name']}</td>
            <td style='padding:11px 14px;'>{c_badge}</td>
            <td style='padding:11px 14px; text-align:right;'>{s_badge}</td>
            <td class='tbl-cell-main' style='padding:11px 14px; text-align:right; font-size:14px;'>{days_str}</td>
            <td style='padding:11px 14px; text-align:center;'>{a_badge}</td>
            <td class='tbl-cell-muted' style='padding:11px 14px; text-align:right; font-size:14px;'>{r['qty_purchased']:,.0f}</td>
            <td class='tbl-cell-muted' style='padding:11px 14px; text-align:right; font-size:14px;'>{r['qty_sold']:,.0f}</td>
            <td class='tbl-cell-subtle' style='padding:11px 14px; text-align:right; font-size:14px;'>{r['opening_qty']:,.0f}</td>
            <td class='tbl-cell-subtle' style='padding:11px 14px; text-align:center; font-size:13px;'>{last_d_str}</td>
        </tr>""")

    render_html_table(headers, rows_html, max_height=620)

    if a_total_pages > 1:
        st.write("")
        p1, p2, p3 = st.columns([1.5, 3, 1.5])
        with p1:
            if st.button("⬅️ Previous Page", disabled=(a_current_page <= 1), use_container_width=True, key="aging_prev_btn"):
                st.session_state.aging_tbl_page = max(1, a_current_page - 1)
                st.rerun()
        with p2:
            st.markdown(
                f"<div style='text-align:center; padding-top:8px; font-weight:600; color:#475569; font-size:14px;'>"
                f"Page {a_current_page} of {a_total_pages} &nbsp;•&nbsp; Showing {a_start_idx+1:,}–{a_end_idx:,} of {total_aging_items:,} items</div>",
                unsafe_allow_html=True
            )
        with p3:
            if st.button("Next Page ➡️", disabled=(a_current_page >= a_total_pages), use_container_width=True, key="aging_next_btn"):
                st.session_state.aging_tbl_page = min(a_total_pages, a_current_page + 1)
                st.rerun()

else:
    st.dataframe(
        sorted_aging[aging_cols],
        column_config={
            'product_name': st.column_config.TextColumn('Product Name', width=320),
            'product_group': st.column_config.TextColumn('Category', width=160),
            'est_stock': st.column_config.NumberColumn('Est. Stock Remaining', format='%,.0f', width=160),
            'days_since_sale': st.column_config.NumberColumn('Days Since Sale', format='%d d', width=130),
            'aging_bucket': st.column_config.TextColumn('Aging Bucket', width=130),
            'qty_purchased': st.column_config.NumberColumn('Purchased Qty', format='%,.0f', width=140),
            'qty_sold': st.column_config.NumberColumn('Sold Qty', format='%,.0f', width=130),
            'opening_qty': st.column_config.NumberColumn('Opening Stock', format='%,.0f', width=130),
            'last_sale': st.column_config.DateColumn('Last Sale Date', format='YYYY-MM-DD', width=130),
        },
        height=620,
        use_container_width=True,
        hide_index=True
    )
