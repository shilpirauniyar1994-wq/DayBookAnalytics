"""
DayBook Analytics — Purchase Order Preparation System
Sales velocity tracking, lead time buffer calculation, and automated purchase order generation.
"""

import streamlit as st
import pandas as pd
import datetime
import db
import po_engine
import importlib
importlib.reload(po_engine)
importlib.reload(db)
from ui_utils import apply_global_styles, format_currency

st.set_page_config(page_title="Purchase Orders — DayBook Analytics", page_icon="🛒", layout="wide")
apply_global_styles()

st.title("🛒 Purchase Order Preparation")
st.caption("Sales velocity trend tracking, lead time buffer calculation, and smart PO generation")

li_df = db.get_line_items_df()
lead_config = db.get_lead_time_config()
supplier_prods = db.get_supplier_products()
rmb_mappings = db.get_product_supplier_mappings()

if li_df.empty:
    st.warning("No line items found. Please upload a day book file first.")
    st.stop()

tab_dash, tab_gen, tab_hist = st.tabs(["📊 Reorder Dashboard", "📋 Generate Purchase Orders", "📜 Saved Orders History"])

# ---------------------------------------------------------------------------
# TAB 1: REORDER DASHBOARD
# ---------------------------------------------------------------------------
with tab_dash:
    with st.spinner("Analyzing sales velocity and stock coverage..."):
        all_sug = po_engine.generate_po_suggestions(
            li_df,
            supplier_products_df=supplier_prods,
            lead_time_config_df=lead_config,
            rmb_mappings_df=rmb_mappings,
            lookback_days=30,
            cover_days=60
        )

    if all_sug.empty:
        st.success("✅ All products have adequate stock! No immediate reorders needed based on recent sales trends.")
    else:
        critical_items = all_sug[all_sug['urgency'].str.contains('Critical', case=False, na=False)]
        warning_items = all_sug[all_sug['urgency'].str.contains('Warning', case=False, na=False)]
        normal_items = all_sug[~all_sug['urgency'].str.contains('Critical|Warning', case=False, na=False)]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🔴 Critical Stockout Risk", f"{len(critical_items)} items", "Order immediately")
        col2.metric("🟡 Approaching Reorder", f"{len(warning_items)} items", "Order within week")
        tot_invest = all_sug['estimated_amount'].sum()
        col4.metric("Est. Total Investment", format_currency(tot_invest), f"{len(all_sug)} products", help=f"Total: Rs. {tot_invest:,.2f}")

        st.markdown("---")

        st.subheader("High Urgency Products Requiring Immediate Order")
        st.dataframe(
            all_sug.head(25),
            column_config={
                'product_name': st.column_config.TextColumn('Product Name', width=300),
                'product_group': st.column_config.TextColumn('Category', width=150),
                'supplier_name': st.column_config.TextColumn('Preferred Supplier', width=200),
                'daily_velocity': st.column_config.NumberColumn('Daily Sales', format='%.1f units/day', width=130),
                'est_stock': st.column_config.NumberColumn('Est. Stock', format='%,.0f', width=130),
                'days_of_stock': st.column_config.NumberColumn('Days Left', format='%.1f days', width=130),
                'suggested_qty': st.column_config.NumberColumn('Suggested Order', format='%,.0f', width=140),
                'estimated_rate': st.column_config.NumberColumn('Est. Rate', format='Rs. %,.2f', width=140),
                'estimated_amount': st.column_config.NumberColumn('Total', format='Rs. %,.2f', width=160),
                'urgency': st.column_config.TextColumn('Status', width=130),
            },
            height=450,
            use_container_width=True,
            hide_index=True
        )

# ---------------------------------------------------------------------------
# TAB 2: GENERATE PURCHASE ORDERS
# ---------------------------------------------------------------------------
with tab_gen:
    st.subheader("Order Generation Parameters")

    p1, p2, p3, p4 = st.columns([1.5, 1.5, 1.5, 2])
    with p1:
        lookback = st.selectbox(
            "Sales Lookback",
            [15, 30, 60, 90],
            index=1,
            help="Days of historical sales to compute average daily velocity"
        )
    with p2:
        cover = st.selectbox(
            "Forward Cover Period",
            [30, 45, 60, 90],
            index=2, # Default 60 days (2 months)
            help="Target stock buffer to order ahead (Default: 60 days / 2 months)"
        )
    with p3:
        season_pct = st.slider("Festive Boost (%)", min_value=0, max_value=50, value=0, step=5, help="Seasonal multiplier for upcoming festivals")
        seasonal_mult = 1.0 + (season_pct / 100.0)

    with p4:
        all_suppliers_list = ['All Suppliers'] + sorted(supplier_prods['supplier_name'].dropna().unique().tolist()) if not supplier_prods.empty else ['All Suppliers']
        selected_sup_filter = st.selectbox("Filter by Supplier", all_suppliers_list)

    # Compute recommendations
    suggestions = po_engine.generate_po_suggestions(
        li_df,
        supplier_products_df=supplier_prods,
        lead_time_config_df=lead_config,
        rmb_mappings_df=rmb_mappings,
        lookback_days=lookback,
        cover_days=cover,
        seasonal_factor=seasonal_mult
    )

    if selected_sup_filter != 'All Suppliers':
        suggestions = suggestions[suggestions['supplier_name'] == selected_sup_filter]

    if suggestions.empty:
        st.info("No items requiring orders under the selected criteria.")
    else:
        # Group suggestions by supplier
        suppliers_in_sug = sorted(suggestions['supplier_name'].unique().tolist())
        st.write(f"Found **{len(suggestions)} products** to order across **{len(suppliers_in_sug)} suppliers**.")

        for sup in suppliers_in_sug:
            sup_items = suggestions[suggestions['supplier_name'] == sup].copy()
            sup_currency = sup_items['currency'].iloc[0] if 'currency' in sup_items.columns else 'Rs.'
            sup_total = sup_items['estimated_amount'].sum()

            with st.expander(f"📦 **{sup}** — {len(sup_items)} items | Estimated Total: {sup_currency} {sup_total:,.2f}", expanded=True):
                st.caption("You can edit the **Order Qty** column directly in the table below:")

                cols_needed = ['supplier_item_no', 'product_name', 'suggested_qty', 'cartons', 'currency', 'estimated_rate', 'estimated_amount', 'daily_velocity', 'est_stock', 'days_of_stock']
                avail = [c for c in cols_needed if c in sup_items.columns]
                editable_df = sup_items[avail].copy()

                edited_table = st.data_editor(
                    editable_df,
                    column_config={
                        'supplier_item_no': st.column_config.TextColumn('Invoice Code', disabled=True),
                        'product_name': st.column_config.TextColumn('Product Name', disabled=True),
                        'suggested_qty': st.column_config.NumberColumn('Order Qty (Editable)', min_value=0, step=1),
                        'cartons': st.column_config.NumberColumn('Cartons (CTN)', disabled=True),
                        'currency': st.column_config.TextColumn('Curr', disabled=True),
                        'estimated_rate': st.column_config.NumberColumn('Rate', format='%.2f', disabled=True),
                        'estimated_amount': st.column_config.NumberColumn('Total Amount', format='%,.2f', disabled=True),
                        'daily_velocity': st.column_config.NumberColumn('Sales/day', format='%.1f', disabled=True),
                        'est_stock': st.column_config.NumberColumn('Stock', format='%,.0f', disabled=True),
                        'days_of_stock': st.column_config.NumberColumn('Days Left', format='%.1f', disabled=True),
                    },
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_{sup}"
                )
                # Recompute amount based on edited quantities
                edited_table['estimated_amount'] = edited_table['suggested_qty'] * edited_table['estimated_rate']
                new_total = edited_table['estimated_amount'].sum()

                action_c1, action_c2, action_c3 = st.columns([2, 2, 2])

                with action_c1:
                    excel_bytes = po_engine.export_po_to_excel(sup, edited_table)
                    st.download_button(
                        label=f"📥 Download Excel PO ({sup})",
                        data=excel_bytes,
                        file_name=f"PO_{sup.replace(' ', '_')}_{datetime.date.today().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_btn_{sup}",
                        use_container_width=True
                    )

                with action_c2:
                    if st.button(f"💾 Save as Draft PO", key=f"save_btn_{sup}", use_container_width=True):
                        po_no = db.save_draft_po(sup, edited_table)
                        st.success(f"Saved Draft Order **{po_no}** for {sup} (Total: Rs. {new_total:,.2f})!")

                with action_c3:
                    st.markdown(f"**Updated Total: Rs. {new_total:,.2f}**")

# ---------------------------------------------------------------------------
# TAB 3: PO HISTORY
# ---------------------------------------------------------------------------
with tab_hist:
    st.subheader("Purchase Order History")
    orders_df = db.get_purchase_orders()

    if orders_df.empty:
        st.info("No purchase orders have been saved yet. Use the 'Generate Purchase Orders' tab above to create your first order!")
    else:
        st.dataframe(
            orders_df,
            column_config={
                'po_number': st.column_config.TextColumn('PO Number', width=150),
                'supplier_name': st.column_config.TextColumn('Supplier', width=240),
                'status': st.column_config.TextColumn('Status', width=130),
                'total_amount': st.column_config.NumberColumn('Total', format='Rs. %,.2f', width=160),
                'total_items': st.column_config.NumberColumn('# Products', format='%,.0f', width=120),
                'notes': st.column_config.TextColumn('Notes', width=280),
                'created_at': st.column_config.TextColumn('Created', width=150),
            },
            height=450,
            use_container_width=True,
            hide_index=True
        )
