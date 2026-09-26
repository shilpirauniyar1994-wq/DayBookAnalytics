"""
DayBook Analytics — Commercial Invoices & RMB Price Matcher Page
Extract unique items once, store in database, dump files in archive, and operate
100% on derived database items for instant page loads and zero repeated Excel scans.
"""

import streamlit as st
import pandas as pd
import os
import datetime
import db
import invoice_matcher
from ui_utils import apply_global_styles

st.set_page_config(
    page_title="Commercial Invoices — DayBook Analytics",
    page_icon="💱",
    layout="wide"
)
apply_global_styles()

st.title("💱 Commercial Invoices & RMB Price Matcher")
st.caption("ETL Pipeline: Extract unique items from commercial invoices into database, archive raw spreadsheets, and manage RMB prices for Purchase Orders.")

folder = "commercial invoices"
archive_folder = os.path.join(folder, "archive")

# Check folder status
unprocessed_files = invoice_matcher.get_unprocessed_invoices(folder)
archived_files = [f for f in os.listdir(archive_folder) if f.lower().endswith(('.xlsx', '.xls'))] if os.path.exists(archive_folder) else []

# Load items directly from database (instant speed, 0 Excel file scans)
db_items = db.get_commercial_invoice_items()
total_items = len(db_items)
matched_count = len(db_items[db_items['is_matched'] == True]) if not db_items.empty else 0
pending_count = total_items - matched_count

# Top KPI Overview
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("📦 Extracted Items (DB)", f"{total_items}", "Stored in database")
k2.metric("✅ Matched with Tally", f"{matched_count}", "Active in PO engine")
k3.metric("⏳ Pending Mapping", f"{pending_count}", "Unlinked items")
k4.metric("🗃️ Archived Invoices", f"{len(archived_files)} files", "Processed & saved")
k5.metric("📥 Waiting in Folder", f"{len(unprocessed_files)} files", "New files to ingest")

st.markdown("---")

# ---------------------------------------------------------------------------
# INGESTION & ARCHIVAL ACTION BANNER
# ---------------------------------------------------------------------------
col_action, col_status = st.columns([2.5, 3.5])

with col_action:
    ingest_clicked = st.button(
        "📥 Ingest & Archive New Commercial Invoices",
        type="primary",
        help="Extract unique items and RMB prices into database and immediately move Excel files into archive",
        use_container_width=True
    )

with col_status:
    if unprocessed_files:
        st.warning(f"**{len(unprocessed_files)} new commercial invoice(s)** waiting in `{folder}/`: {', '.join(unprocessed_files[:3])}{'...' if len(unprocessed_files) > 3 else ''}")
    else:
        st.success("✅ **Folder Clean:** All commercial invoices have been extracted into the database and archived.")

if ingest_clicked:
    if not unprocessed_files:
        st.info("No new commercial invoice files found in `commercial invoices/`. Place new supplier files there anytime to ingest.")
    else:
        with st.spinner(f"Ingesting {len(unprocessed_files)} invoice(s), extracting items, and archiving files..."):
            result = invoice_matcher.extract_and_archive_all_new_invoices(folder=folder)
            st.session_state['ingest_result'] = result
            st.balloons()
            st.rerun()

if 'ingest_result' in st.session_state:
    res = st.session_state.pop('ingest_result')
    st.success(f"""
    🎉 **Ingestion Complete!**
    - **Invoices Processed & Archived:** {res['files_processed']} file(s)
    - **Total Items Extracted:** {res['items_extracted']} items
    - **New Items Added to DB:** {res['new_items']} items
    - **RMB Prices Updated:** {res['updated_prices']} items
    - **Auto-Matched to Tally:** {res['auto_matched']} items
    """)

# ---------------------------------------------------------------------------
# TABS: 100% DATABASE-DRIVEN
# ---------------------------------------------------------------------------
tab_matcher, tab_catalog, tab_history, tab_archive = st.tabs([
    "🔗 Match Items to Tally",
    "🏷️ Active RMB Price Catalog",
    "📈 Price Change History",
    "🗃️ Invoice Archive"
])

# Fetch all Tally products for dropdowns
li_df = db.get_line_items_df()
tally_prods = sorted(li_df['product_name'].dropna().unique().tolist()) if not li_df.empty else []

# ---------------------------------------------------------------------------
# TAB 1: ITEM MATCHER (OPERATES 100% ON DATABASE)
# ---------------------------------------------------------------------------
with tab_matcher:
    st.subheader("Commercial Invoice Items Database & Tally Matcher")
    st.caption("Matches supplier item codes and descriptions to your Tally catalog. All data loads instantly from the database without re-reading spreadsheets.")

    if db_items.empty:
        st.info("No commercial invoice items in database yet. Place supplier spreadsheets in `commercial invoices/` and click 'Ingest & Archive New Commercial Invoices'.")
    else:
        # Filters Row
        f1, f2, f3 = st.columns([1.5, 1.5, 3])
        with f1:
            status_filter = st.selectbox("Status Filter", ["Pending Mapping (Unmatched)", "Matched", "All Items"], index=0)
        with f2:
            suppliers_list = ["All Suppliers"] + sorted(db_items['supplier_name'].dropna().unique().tolist())
            supplier_filter = st.selectbox("Supplier", suppliers_list, index=0)
        with f3:
            search_query = st.text_input("🔍 Search Item Code, Description, or Tally Product", "")

        # Apply Filters
        filtered_df = db_items.copy()
        if status_filter == "Pending Mapping (Unmatched)":
            filtered_df = filtered_df[filtered_df['is_matched'] == False]
        elif status_filter == "Matched":
            filtered_df = filtered_df[filtered_df['is_matched'] == True]

        if supplier_filter != "All Suppliers":
            filtered_df = filtered_df[filtered_df['supplier_name'] == supplier_filter]

        if search_query:
            q = search_query.lower()
            filtered_df = filtered_df[
                filtered_df['supplier_item_no'].astype(str).str.lower().str.contains(q) |
                filtered_df['supplier_desc'].astype(str).str.lower().str.contains(q) |
                filtered_df['tally_product_name'].astype(str).str.lower().str.contains(q)
            ]

        st.markdown(f"**Showing {len(filtered_df)} items** (out of {len(db_items)} total items in DB)")

        # Quick Batch Actions
        high_conf_pending = db_items[(db_items['is_matched'] == False) & (db_items['match_confidence'] >= 0.8) & (db_items['tally_product_name'].notna())]
        if not high_conf_pending.empty:
            b_col1, b_col2 = st.columns([2.5, 3.5])
            with b_col1:
                if st.button(f"⚡ Accept All {len(high_conf_pending)} High-Confidence Auto-Matches (>80%)", type="secondary", use_container_width=True):
                    batch_matches = []
                    for _, r in high_conf_pending.iterrows():
                        batch_matches.append({
                            'item_key': r['item_key'],
                            'tally_product_name': r['tally_product_name'],
                            'match_type': 'Auto Confirmed',
                            'confidence': float(r.get('match_confidence', 0.9))
                        })
                    db.batch_update_commercial_matches(batch_matches)
                    st.success(f"Confirmed {len(batch_matches)} matches successfully!")
                    st.rerun()

        # Display matching items
        if filtered_df.empty:
            st.info("No items match the selected filter.")
        else:
            # Paginated or scrollable list
            items_to_show = filtered_df.head(100)  # show first 100 for responsive UI
            if len(filtered_df) > 100:
                st.caption(f"Showing first 100 of {len(filtered_df)} items. Use the search bar above to narrow down results.")

            # Batch confirmation form
            with st.form("manual_matching_form"):
                updates_to_save = []
                unmatches_to_save = []

                for idx, r in items_to_show.iterrows():
                    key = r['item_key']
                    it_no = str(r.get('supplier_item_no', ''))
                    it_desc = str(r.get('supplier_desc', ''))
                    price = r.get('rmb_price', 0.0)
                    pcs = r.get('pcs_per_ctn', 0)
                    is_m = bool(r.get('is_matched', False))
                    curr_tally = str(r.get('tally_product_name', '')) if pd.notna(r.get('tally_product_name')) else ''
                    m_type = str(r.get('match_type', 'Unmatched'))
                    conf = float(r.get('match_confidence', 0.0))

                    col_it, col_price, col_tally, col_unlink = st.columns([2.5, 1.2, 3, 0.8])

                    with col_it:
                        st.markdown(f"**{it_no}** — {it_desc[:40]}")
                        st.caption(f"Supplier: `{r.get('supplier_name')}` | Source: `{r.get('source_invoice')}`")

                    with col_price:
                        st.markdown(f"**¥{price:.3f}**")
                        st.caption(f"{pcs} pcs/ctn")

                    with col_tally:
                        options = ["-- Unmatched --"] + tally_prods
                        default_idx = 0
                        if curr_tally and curr_tally in tally_prods:
                            default_idx = options.index(curr_tally)

                        chosen_tally = st.selectbox(
                            f"Tally Product for {it_no}",
                            options=options,
                            index=default_idx,
                            key=f"tally_sel_{key}",
                            label_visibility="collapsed"
                        )

                        if chosen_tally != "-- Unmatched --" and chosen_tally != curr_tally:
                            updates_to_save.append({
                                'item_key': key,
                                'tally_product_name': chosen_tally,
                                'match_type': 'Manual Selection',
                                'confidence': 1.0
                            })
                        elif chosen_tally != "-- Unmatched --" and not is_m:
                            updates_to_save.append({
                                'item_key': key,
                                'tally_product_name': chosen_tally,
                                'match_type': m_type if m_type != 'Unmatched' else 'Manual Selection',
                                'confidence': conf if conf > 0 else 1.0
                            })

                    with col_unlink:
                        if is_m:
                            unlink_check = st.checkbox("Unlink", key=f"unlink_{key}", help="Remove Tally link for this item")
                            if unlink_check:
                                unmatches_to_save.append(key)
                        else:
                            if conf > 0:
                                st.caption(f"🎯 {int(conf * 100)}%")

                    st.markdown("<hr style='margin:4px 0px; border-color:#e2e8f0;'>", unsafe_allow_html=True)

                submit_btn = st.form_submit_button("💾 Save Changes & Update Active Catalog", type="primary")

                if submit_btn:
                    if unmatches_to_save:
                        for uk in unmatches_to_save:
                            db.unmatch_commercial_item(uk)
                    if updates_to_save:
                        db.batch_update_commercial_matches(updates_to_save)
                    st.success(f"Saved {len(updates_to_save)} match updates and {len(unmatches_to_save)} unlinks!")
                    st.rerun()

# ---------------------------------------------------------------------------
# TAB 2: ACTIVE RMB PRICE CATALOG
# ---------------------------------------------------------------------------
with tab_catalog:
    st.subheader("Active RMB Price Catalog & Pack Sizes")
    st.caption("These prices and master pack sizes are actively utilized by the Purchase Order suggestion engine for overseas suppliers.")

    current_mappings = db.get_product_supplier_mappings()

    if current_mappings.empty:
        st.info("No products mapped with RMB prices yet. Link items in the 'Match Items to Tally' tab to populate this catalog.")
    else:
        # Search & Filter
        s_c1, s_c2 = st.columns([3, 1.5])
        with s_c1:
            cat_search = st.text_input("🔍 Search catalog by product name, supplier code, or description...", "", key="cat_search_input")
        with s_c2:
            sup_filter = st.selectbox("Filter Supplier", ["All"] + sorted(current_mappings['supplier_name'].dropna().unique().tolist()), key="cat_sup_filter")

        display_cat = current_mappings.copy()
        if sup_filter != "All":
            display_cat = display_cat[display_cat['supplier_name'] == sup_filter]

        if cat_search:
            q = cat_search.lower()
            mask = (
                display_cat['product_name'].astype(str).str.lower().str.contains(q) |
                display_cat['supplier_item_no'].astype(str).str.lower().str.contains(q) |
                display_cat['supplier_desc'].astype(str).str.lower().str.contains(q)
            )
            display_cat = display_cat[mask]

        st.dataframe(
            display_cat,
            column_config={
                'product_name': st.column_config.TextColumn('Tally Product Name', width='medium'),
                'supplier_name': 'Supplier',
                'supplier_item_no': 'Invoice Item #',
                'supplier_desc': 'Invoice Description',
                'rmb_price': st.column_config.NumberColumn('Price (RMB ¥)', format='¥%.3f'),
                'pcs_per_ctn': st.column_config.NumberColumn('PCS / CTN', format='%d pcs'),
                'invoice_file': 'Source Invoice',
                'matched_at': 'Matched Date',
            },
            use_container_width=True,
            hide_index=True
        )

        # CSV Download button
        csv_data = display_cat.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Active RMB Catalog (CSV)",
            data=csv_data,
            file_name=f"RMB_Price_Catalog_{datetime.date.today().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

# ---------------------------------------------------------------------------
# TAB 3: PRICE CHANGE HISTORY
# ---------------------------------------------------------------------------
with tab_history:
    st.subheader("Commercial Invoice Price Change History")
    st.caption("Audit trail of RMB unit prices updated across consecutive commercial invoices.")

    hist_df = db.get_commercial_price_history()

    if hist_df.empty:
        st.info("No price changes recorded yet. When a newer commercial invoice contains an item with an updated price, the change is automatically logged here.")
    else:
        st.dataframe(
            hist_df,
            column_config={
                'supplier_name': 'Supplier',
                'supplier_item_no': 'Item # / Code',
                'supplier_desc': 'Description',
                'old_rmb_price': st.column_config.NumberColumn('Previous Price (¥)', format='¥%.3f'),
                'new_rmb_price': st.column_config.NumberColumn('New Price (¥)', format='¥%.3f'),
                'source_invoice': 'Updated In Invoice',
                'updated_at': 'Update Timestamp'
            },
            use_container_width=True,
            hide_index=True
        )

# ---------------------------------------------------------------------------
# TAB 4: INVOICE ARCHIVE
# ---------------------------------------------------------------------------
with tab_archive:
    st.subheader("Archived Commercial Invoices")
    st.caption("Spreadsheets that have been parsed, ingested into the database, and safely moved out of the active folder.")

    if not archived_files:
        st.info("No invoices in archive yet.")
    else:
        arch_data = []
        for af in archived_files:
            full_ap = os.path.join(archive_folder, af)
            sz = os.path.getsize(full_ap) / (1024 * 1024)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(full_ap)).strftime('%Y-%m-%d %H:%M')
            arch_data.append({
                'filename': af,
                'file_size_mb': round(sz, 2),
                'archived_at': mtime
            })

        st.dataframe(
            pd.DataFrame(arch_data),
            column_config={
                'filename': 'Invoice File Name',
                'file_size_mb': st.column_config.NumberColumn('File Size (MB)', format='%.2f MB'),
                'archived_at': 'Archive Date',
            },
            use_container_width=True,
            hide_index=True
        )
