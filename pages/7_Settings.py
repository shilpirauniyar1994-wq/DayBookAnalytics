"""
DayBook Analytics — Settings & Configuration Page
Configure lead times, safety stocks, supplier mappings, and product groups.
"""

import streamlit as st
import pandas as pd
import db
from ui_utils import apply_global_styles

st.set_page_config(page_title="Settings — DayBook Analytics", page_icon="⚙️", layout="wide")
apply_global_styles()

st.title("⚙️ System Configuration & Preferences")
st.caption("Manage procurement lead times, safety stock buffers, supplier mappings, and product categorization")

tab_lead, tab_sup, tab_grp = st.tabs(["⏱ Lead Time Configuration", "🏭 Supplier Catalog & Preferences", "📦 Product Groups"])

# ---------------------------------------------------------------------------
# TAB 1: LEAD TIME CONFIGURATION
# ---------------------------------------------------------------------------
with tab_lead:
    st.subheader("Procurement Lead Times & Safety Stock Buffers")
    st.markdown("""
    Define the time (in days) it takes from placing an order until goods arrive in your warehouse.
    The PO suggestion engine prioritizes: **Product Group Override > Supplier Override > Global Default**.
    """)

    cfg_df = db.get_lead_time_config()

    # 1. Global Defaults
    st.markdown("#### 1. Global Default (Applied to all items unless overridden)")
    global_row = cfg_df[(cfg_df['config_type'] == 'default') & (cfg_df['config_key'] == 'global')]
    def_lead = int(global_row.iloc[0]['lead_time_days']) if not global_row.empty else 7
    def_safety = int(global_row.iloc[0]['safety_stock_days']) if not global_row.empty else 3

    g_col1, g_col2, g_col3 = st.columns([1.5, 1.5, 2])
    with g_col1:
        new_g_lead = st.number_input("Global Delivery Lead Time (days)", min_value=1, max_value=180, value=def_lead)
    with g_col2:
        new_g_safety = st.number_input("Global Safety Stock Buffer (days)", min_value=0, max_value=60, value=def_safety)
    with g_col3:
        st.write("")
        st.write("")
        if st.button("💾 Save Global Defaults", type="primary"):
            db.upsert_lead_time('default', 'global', new_g_lead, new_g_safety, "Global system default")
            st.success("Global lead time settings updated successfully!")

    st.markdown("---")

    # 2. Per-Supplier Overrides
    st.markdown("#### 2. Supplier-Specific Overrides")
    st.caption("E.g., Local factory suppliers take 3 days, Indian suppliers take 12 days, Overseas imports take 30-45 days.")

    supplier_prods = db.get_supplier_products()
    supplier_list = sorted(supplier_prods['supplier_name'].dropna().unique().tolist()) if not supplier_prods.empty else []

    if supplier_list:
        sup_col1, sup_col2, sup_col3, sup_col4 = st.columns([2, 1.2, 1.2, 1.5])
        with sup_col1:
            chosen_sup = st.selectbox("Select Supplier to Override", supplier_list)

        sup_existing = cfg_df[(cfg_df['config_type'] == 'supplier') & (cfg_df['config_key'] == chosen_sup)]
        cur_sup_lead = int(sup_existing.iloc[0]['lead_time_days']) if not sup_existing.empty else def_lead
        cur_sup_safety = int(sup_existing.iloc[0]['safety_stock_days']) if not sup_existing.empty else def_safety

        with sup_col2:
            override_sup_lead = st.number_input("Lead Days", min_value=1, max_value=180, value=cur_sup_lead, key=f"sup_l_{chosen_sup}")
        with sup_col3:
            override_sup_safety = st.number_input("Safety Days", min_value=0, max_value=60, value=cur_sup_safety, key=f"sup_s_{chosen_sup}")
        with sup_col4:
            st.write("")
            st.write("")
            if st.button(f"Save for {chosen_sup}"):
                db.upsert_lead_time('supplier', chosen_sup, override_sup_lead, override_sup_safety, f"Override for {chosen_sup}")
                st.success(f"Saved custom lead time for {chosen_sup}: {override_sup_lead} days lead + {override_sup_safety} days buffer!")
    else:
        st.info("No suppliers discovered yet. Upload a day book to populate the supplier directory.")

    st.markdown("---")

    # 3. Per-Product Group Overrides
    st.markdown("#### 3. Category / Product Group Overrides")
    prod_groups = db.get_product_groups()
    if prod_groups:
        grp_col1, grp_col2, grp_col3, grp_col4 = st.columns([2, 1.2, 1.2, 1.5])
        with grp_col1:
            chosen_grp = st.selectbox("Select Product Group to Override", prod_groups)

        grp_existing = cfg_df[(cfg_df['config_type'] == 'product_group') & (cfg_df['config_key'] == chosen_grp)]
        cur_grp_lead = int(grp_existing.iloc[0]['lead_time_days']) if not grp_existing.empty else def_lead
        cur_grp_safety = int(grp_existing.iloc[0]['safety_stock_days']) if not grp_existing.empty else def_safety

        with grp_col2:
            override_grp_lead = st.number_input("Group Lead Days", min_value=1, max_value=180, value=cur_grp_lead, key=f"grp_l_{chosen_grp}")
        with grp_col3:
            override_grp_safety = st.number_input("Group Safety Days", min_value=0, max_value=60, value=cur_grp_safety, key=f"grp_s_{chosen_grp}")
        with grp_col4:
            st.write("")
            st.write("")
            if st.button(f"Save for {chosen_grp}"):
                db.upsert_lead_time('product_group', chosen_grp, override_grp_lead, override_grp_safety, f"Override for group {chosen_grp}")
                st.success(f"Saved lead time for {chosen_grp}: {override_grp_lead} days!")

# ---------------------------------------------------------------------------
# TAB 2: SUPPLIER PREFERENCES
# ---------------------------------------------------------------------------
with tab_sup:
    st.subheader("Supplier Catalog & Multi-Source Products")
    st.caption("View which suppliers provide each product and configure preferences for ordering.")

    sp_df = db.get_supplier_products()
    if sp_df.empty:
        st.info("No supplier purchase records found.")
    else:
        # Check products supplied by multiple vendors
        sup_counts = sp_df.groupby('product_name')['supplier_name'].nunique().reset_index()
        multi_source = sup_counts[sup_counts['supplier_name'] > 1]['product_name'].tolist()

        s_col1, s_col2 = st.columns([2, 2])
        s_col1.metric("Active Suppliers", f"{sp_df['supplier_name'].nunique()} vendors")
        s_col2.metric("Multi-Source Products", f"{len(multi_source)} items", "Available from 2+ suppliers")

        st.markdown("#### Supplier Directory Table")
        st.dataframe(
            sp_df.sort_values('total_qty_purchased', ascending=False),
            column_config={
                'supplier_name': 'Supplier Name',
                'product_name': 'Product Supplied',
                'last_purchase_date': st.column_config.DateColumn('Last Purchased', format='YYYY-MM-DD'),
                'last_purchase_rate': st.column_config.NumberColumn('Last Rate', format='Rs. %,.2f'),
                'avg_purchase_rate': st.column_config.NumberColumn('Avg Rate', format='Rs. %,.2f'),
                'total_qty_purchased': st.column_config.NumberColumn('Total Qty', format='%,.0f'),
                'purchase_count': 'Order Count',
            },
            use_container_width=True,
            hide_index=True
        )

# ---------------------------------------------------------------------------
# TAB 3: PRODUCT GROUPS
# ---------------------------------------------------------------------------
with tab_grp:
    st.subheader("Product Groups & Categorization")
    st.caption("Keyword classification rules assigned to products in Demo Khelauna")

    li_df = db.get_line_items_df()
    if not li_df.empty:
        grp_summary = li_df.groupby('product_group').agg(
            unique_products=('product_name', 'nunique'),
            total_qty=('quantity', 'sum'),
            total_amount=('amount', 'sum')
        ).reset_index().sort_values('unique_products', ascending=False)

        st.dataframe(
            grp_summary,
            column_config={
                'product_group': 'Category Group Name',
                'unique_products': 'Unique Products',
                'total_qty': st.column_config.NumberColumn('Total Volume', format='%,.0f'),
                'total_amount': st.column_config.NumberColumn('Total Value', format='Rs. %,.2f'),
            },
            use_container_width=True,
            hide_index=True
        )
