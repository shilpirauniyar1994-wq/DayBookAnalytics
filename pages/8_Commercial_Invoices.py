"""
DayBook Analytics — Commercial Invoices & RMB Price Matcher Page
Extract unique items, auto-match invoices with DayBook Purchase Vouchers,
reconcile line items with exact quantities and landed cost multipliers,
and propagate RMB prices to the Purchase Order engine and WhatsApp assistant.
"""

import streamlit as st
import pandas as pd
import os
import re
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
st.caption("Intelligent Two-Stage Matcher: Pairs imported China commercial invoices with DayBook Purchase Vouchers, reconciles line items with quantity & landed cost checks, and synchronizes RMB prices.")

folder = "commercial invoices"
archive_folder = os.path.join(folder, "archive")
os.makedirs(folder, exist_ok=True)
os.makedirs(archive_folder, exist_ok=True)

# Check folder status
unprocessed_files = invoice_matcher.get_unprocessed_invoices(folder)
archived_files = [f for f in sorted(os.listdir(archive_folder)) if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith(('~', '.'))] if os.path.exists(archive_folder) else []

# Load items directly from database
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
# INGESTION & UPLOAD BANNER
# ---------------------------------------------------------------------------
c_upload, c_ingest = st.columns([3, 2])

with c_upload:
    uploaded_file = st.file_uploader(
        "📤 Upload New Commercial Invoice (Excel .xlsx / .xls)",
        type=["xlsx", "xls"],
        help="Upload a supplier commercial invoice to automatically parse, pair with a DayBook Purchase Voucher, and extract RMB prices."
    )
    if uploaded_file is not None:
        save_path = os.path.join(folder, uploaded_file.name)
        if not os.path.exists(save_path):
            with open(save_path, "wb") as f_out:
                f_out.write(uploaded_file.getbuffer())
            st.success(f"Uploaded `{uploaded_file.name}` to `{folder}/`!")
            st.session_state['selected_invoice_file'] = uploaded_file.name
            st.rerun()

with c_ingest:
    st.markdown("**Batch Ingestion Pipeline**")
    if unprocessed_files:
        st.warning(f"**{len(unprocessed_files)} file(s) waiting in `{folder}/`:** {', '.join(unprocessed_files[:2])}{'...' if len(unprocessed_files) > 2 else ''}")
    else:
        st.success("✅ **Folder Clean:** All invoices processed and archived.")

    if st.button("📥 Ingest & Archive All New Invoices", type="primary", use_container_width=True):
        if not unprocessed_files:
            st.info("No unarchived invoice files found in `commercial invoices/`.")
        else:
            with st.spinner(f"Ingesting {len(unprocessed_files)} file(s)..."):
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
# TABS
# ---------------------------------------------------------------------------
tab_reconcile, tab_db_items, tab_catalog, tab_history, tab_archive = st.tabs([
    "🎯 Voucher-Aware Reconciliation",
    "🔗 Database Items Matcher",
    "🏷️ Active RMB Price Catalog",
    "📈 Price Change History",
    "🗃️ Invoice Archive"
])

# Fetch all Tally products and DayBook Purchase Vouchers
v_df, li_df = db.load_local_data()
tally_prods = sorted(li_df['product_name'].dropna().unique().tolist()) if not li_df.empty else []
pv_df = v_df[v_df['voucher_category'] == 'Purchase'] if not v_df.empty else pd.DataFrame()

# Saved mappings memory
saved_mappings_df = db.get_product_supplier_mappings()
saved_lookup = {}
if not saved_mappings_df.empty:
    for _, r in saved_mappings_df.iterrows():
        saved_lookup[str(r['product_name']).strip()] = {
            'supplier_item_no': str(r.get('supplier_item_no', '')),
            'supplier_desc': str(r.get('supplier_desc', '')),
            'rmb_price': float(r.get('rmb_price', 0.0)),
            'pcs_per_ctn': int(r.get('pcs_per_ctn', 0)),
        }

# ---------------------------------------------------------------------------
# TAB 1: VOUCHER-AWARE RECONCILIATION
# ---------------------------------------------------------------------------
with tab_reconcile:
    st.subheader("🎯 Stage 1 & 2: Macro Voucher Pairing & Micro Item Reconciliation")
    st.caption("Select any uploaded or archived commercial invoice to automatically match with its corresponding DayBook Purchase Voucher and reconcile item RMB prices.")

    # All available invoice files
    all_available_files = []
    file_path_map = {}

    for uf in unprocessed_files:
        label = f"📥 [New] {uf}"
        all_available_files.append(label)
        file_path_map[label] = os.path.join(folder, uf)

    for af in archived_files:
        label = f"🗃️ [Archived] {af}"
        all_available_files.append(label)
        file_path_map[label] = os.path.join(archive_folder, af)

    if not all_available_files:
        st.info("No commercial invoice spreadsheets available. Upload an Excel file above to begin matching.")
    else:
        # Default file selection
        default_file_idx = 0
        if 'selected_invoice_file' in st.session_state:
            target_f = st.session_state.pop('selected_invoice_file')
            for i, lab in enumerate(all_available_files):
                if target_f in lab:
                    default_file_idx = i
                    break

        selected_label = st.selectbox(
            "Select Commercial Invoice to Reconcile:",
            options=all_available_files,
            index=default_file_idx,
            help="Choose an invoice spreadsheet to inspect and reconcile against DayBook Purchase Vouchers"
        )
        selected_file_path = file_path_map[selected_label]

        # Parse invoice items and extract metadata
        invoice_items = invoice_matcher.parse_commercial_invoice(selected_file_path)
        meta = invoice_matcher.extract_invoice_metadata(selected_file_path)

        if not invoice_items:
            st.error(f"Could not extract items from `{os.path.basename(selected_file_path)}`. Please ensure the file contains valid headers.")
        else:
            # Stage 1: Macro Matching (Find Candidate Vouchers)
            candidates = invoice_matcher.find_candidate_purchase_vouchers(invoice_items, metadata=meta, limit=6)

            # Build candidate voucher options for selector
            voucher_options = []
            voucher_details_map = {}

            if candidates:
                for c in candidates:
                    v_key = c['voucher_no']
                    v_label = f"🎯 {c['voucher_no']} / {c['party_name']} — Date: {c['date']} | Line Items: {c['item_count']} | Overlap: {c['overlap_count']}/{len(invoice_items)} ({c['confidence_pct']}% Score)"
                    voucher_options.append(v_label)
                    voucher_details_map[v_label] = c

            voucher_options.append("-- Select from All DayBook Purchase Vouchers --")
            voucher_options.append("-- None (Search Full Catalog) --")

            # Voucher Pairing Banner
            st.markdown("#### 🚢 Stage 1: Purchase Voucher Pairing")
            v_col1, v_col2 = st.columns([4, 1.5])

            with v_col1:
                selected_v_label = st.selectbox(
                    "Linked DayBook Purchase Voucher:",
                    options=voucher_options,
                    index=0,
                    help="The DayBook Purchase Voucher representing this physical shipment in Tally."
                )

            active_voucher_no = None
            active_voucher_party = None
            active_candidate_info = None

            if selected_v_label in voucher_details_map:
                active_candidate_info = voucher_details_map[selected_v_label]
                active_voucher_no = active_candidate_info['voucher_no']
                active_voucher_party = active_candidate_info['party_name']
            elif selected_v_label == "-- Select from All DayBook Purchase Vouchers --":
                # Show all purchase vouchers from DayBook
                all_pv_labels = sorted(pv_df['voucher_no'].dropna().astype(str).unique().tolist())
                chosen_manual_v = st.selectbox("Select Purchase Voucher No from DayBook:", all_pv_labels)
                active_voucher_no = chosen_manual_v

            with v_col2:
                if active_candidate_info:
                    conf = active_candidate_info['confidence_pct']
                    if conf >= 75:
                        st.markdown(f"<div style='margin-top:25px;'><span style='background-color:#dcfce7; color:#166534; font-weight:700; padding:6px 14px; border-radius:9999px; border:1px solid #86efac;'>🟢 Auto-Linked ({conf}%)</span></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='margin-top:25px;'><span style='background-color:#fef9c3; color:#854d0e; font-weight:700; padding:6px 14px; border-radius:9999px; border:1px solid #fde047;'>🟡 Candidate ({conf}%)</span></div>", unsafe_allow_html=True)
                elif active_voucher_no:
                    st.markdown(f"<div style='margin-top:25px;'><span style='background-color:#e0f2fe; color:#075985; font-weight:700; padding:6px 14px; border-radius:9999px;'>🔵 Manual Link</span></div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='margin-top:25px;'><span style='background-color:#f1f5f9; color:#475569; font-weight:700; padding:6px 14px; border-radius:9999px;'>⚪ Full Catalog</span></div>", unsafe_allow_html=True)

            # Stage 2: Micro Matching
            if active_voucher_no:
                reconciled_items = invoice_matcher.match_invoice_items_against_voucher(
                    invoice_items=invoice_items,
                    voucher_no=active_voucher_no,
                    party_name=active_voucher_party,
                    saved_mappings=saved_lookup,
                    tally_products=tally_prods
                )
                # Fetch line items of this voucher to populate top of dropdowns
                v_line_items = li_df[li_df['voucher_no'].astype(str).str.lower() == str(active_voucher_no).strip().lower()]
                voucher_product_names = sorted(v_line_items['product_name'].dropna().unique().tolist())
            else:
                reconciled_items = invoice_matcher.match_invoice_items_to_tally(
                    invoice_items=invoice_items,
                    tally_products=tally_prods,
                    saved_mappings=saved_lookup
                )
                voucher_product_names = []

            # Reconciliation Metrics Row
            matched_items_count = sum(1 for it in reconciled_items if it.get('matched_product_name'))
            match_pct = round((matched_items_count / len(reconciled_items)) * 100, 1) if reconciled_items else 0
            multipliers = [it['landed_multiplier'] for it in reconciled_items if it.get('landed_multiplier', 0) > 0]
            avg_mult = round(sum(multipliers) / len(multipliers), 1) if multipliers else 0.0
            total_invoiced_pcs = sum(it.get('invoiced_qty', 0) for it in reconciled_items)
            total_invoiced_rmb = sum(it.get('rmb_price', 0.0) * it.get('invoiced_qty', 0) for it in reconciled_items)

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("📦 Invoice Items", f"{len(reconciled_items)} items", f"{total_invoiced_pcs:,} pcs total")
            m2.metric("✅ Matched with Voucher", f"{matched_items_count} / {len(reconciled_items)}", f"{match_pct}% Match Rate")
            m3.metric("💱 Avg Landed Multiplier", f"{avg_mult}x" if avg_mult > 0 else "—", "NPR / RMB Rate")
            m4.metric("💴 Invoiced Total (RMB)", f"¥ {total_invoiced_rmb:,.2f}" if total_invoiced_rmb > 0 else "—", meta.get('supplier', 'Supplier'))
            if active_candidate_info and active_candidate_info.get('credit_amount'):
                m5.metric("🇳🇵 Voucher Total (NPR)", f"Rs. {active_candidate_info['credit_amount']:,.0f}", f"Voucher: {active_voucher_no}")
            else:
                m5.metric("🇳🇵 Voucher Total (NPR)", "—", f"Voucher: {active_voucher_no or 'None'}")

            st.markdown("---")
            st.markdown("#### 📋 Stage 2: Side-by-Side Item Reconciliation")
            st.caption("Review auto-detected matches. The dropdown prioritizes line items from the linked voucher first, followed by the rest of your catalog.")

            # Batch Confirmation Form
            with st.form(f"reconcile_form_{active_voucher_no}_{len(reconciled_items)}"):
                # Header row
                h1, h2, h3, h4, h5, h6 = st.columns([2.5, 1.4, 2.8, 1.4, 1.2, 1.2])
                h1.markdown("**Invoice Item # & Description**")
                h2.markdown("**Invoiced (RMB & Qty)**")
                h3.markdown("**Matched Tally Product**")
                h4.markdown("**Voucher (Qty & Rate)**")
                h5.markdown("**Landed Multiplier**")
                h6.markdown("**Status**")
                st.markdown("<hr style='margin:2px 0px 8px 0px; border-color:#cbd5e1;'>", unsafe_allow_html=True)

                form_updates = []
                form_catalog_mappings = []

                # Build full dropdown options list:
                # 1. "-- Unmatched --"
                # 2. Line items from the voucher (prefixed with 🎯)
                # 3. All other catalog items
                other_catalog_prods = [p for p in tally_prods if p not in voucher_product_names]
                dropdown_options = ["-- Unmatched --"]
                if voucher_product_names:
                    dropdown_options.extend([f"🎯 {p}" for p in voucher_product_names])
                dropdown_options.extend(other_catalog_prods)

                for idx, it in enumerate(reconciled_items):
                    c1, c2, c3, c4, c5, c6 = st.columns([2.5, 1.4, 2.8, 1.4, 1.2, 1.2])

                    it_no = it.get('supplier_item_no', '')
                    it_desc = it.get('supplier_desc', '')
                    rmb_p = it.get('rmb_price', 0.0)
                    pcs_ctn = it.get('pcs_per_ctn', 0)
                    inv_ctns = it.get('invoiced_ctns', 0)
                    inv_qty = it.get('invoiced_qty', 0)
                    curr_matched = it.get('matched_product_name')
                    v_rate = it.get('voucher_rate', 0.0)
                    v_qty = it.get('voucher_qty', 0)
                    multiplier = it.get('landed_multiplier', 0.0)
                    match_type = it.get('match_type', 'Unmatched')
                    conf = it.get('confidence', 0.0)

                    with c1:
                        st.markdown(f"**{it_no}**")
                        st.caption(f"{it_desc[:42]}{'...' if len(it_desc) > 42 else ''}")

                    with c2:
                        st.markdown(f"**¥ {rmb_p:.3f}**")
                        qty_desc = f"{inv_qty:,} pcs" if inv_qty > 0 else ""
                        ctn_desc = f" ({inv_ctns} ctns × {pcs_ctn})" if inv_ctns > 0 and pcs_ctn > 0 else (f"{pcs_ctn}/ctn" if pcs_ctn > 0 else "")
                        st.caption(f"{qty_desc}{ctn_desc}")

                    with c3:
                        # Find matching option in dropdown
                        default_idx = 0
                        if curr_matched:
                            target_val = f"🎯 {curr_matched}" if curr_matched in voucher_product_names else curr_matched
                            if target_val in dropdown_options:
                                default_idx = dropdown_options.index(target_val)
                            elif curr_matched in dropdown_options:
                                default_idx = dropdown_options.index(curr_matched)

                        chosen_val = st.selectbox(
                            f"Product for {it_no}_{idx}",
                            options=dropdown_options,
                            index=default_idx,
                            key=f"rec_sel_{idx}_{it_no}",
                            label_visibility="collapsed"
                        )

                        # Clean chosen value
                        chosen_prod = chosen_val.replace("🎯 ", "").strip() if chosen_val != "-- Unmatched --" else None

                    with c4:
                        if curr_matched and (v_rate > 0 or v_qty > 0):
                            st.markdown(f"**Rs. {v_rate:,.2f}**")
                            st.caption(f"{v_qty:,.0f} pcs in voucher")
                        else:
                            st.caption("—")

                    with c5:
                        if multiplier > 0:
                            if 18.0 <= multiplier <= 45.0:
                                st.markdown(f"<span style='background-color:#dcfce7; color:#166534; font-weight:700; padding:2px 8px; border-radius:6px;'>{multiplier}x</span>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<span style='background-color:#fee2e2; color:#991b1b; font-weight:700; padding:2px 8px; border-radius:6px;'>{multiplier}x</span>", unsafe_allow_html=True)
                        else:
                            st.caption("—")

                    with c6:
                        if chosen_prod:
                            st.markdown(f"<span style='font-size:12px; color:#166534; font-weight:600;'>🟢 {match_type[:15]}</span>", unsafe_allow_html=True)
                            st.caption(f"{int(conf * 100)}% match" if conf > 0 else "Linked")
                        else:
                            st.markdown("<span style='font-size:12px; color:#94a3b8;'>⚪ Unlinked</span>", unsafe_allow_html=True)

                    st.markdown("<hr style='margin:3px 0px; border-color:#f1f5f9;'>", unsafe_allow_html=True)

                    if chosen_prod:
                        item_key = db.make_item_key(meta.get('supplier', 'Huabei'), it_no, it_desc)
                        form_updates.append({
                            'item_key': item_key,
                            'supplier_name': meta.get('supplier', 'Huabei'),
                            'supplier_item_no': it_no,
                            'supplier_desc': it_desc,
                            'rmb_price': rmb_p,
                            'pcs_per_ctn': pcs_ctn,
                            'invoiced_qty': inv_qty,
                            'voucher_no': active_voucher_no or '',
                            'landed_multiplier': multiplier,
                            'source_invoice': os.path.basename(selected_file_path),
                            'matched_product_name': chosen_prod,
                            'match_type': match_type if match_type != 'Unmatched' else 'Manual Link',
                            'confidence': conf if conf > 0 else 1.0,
                            'is_matched': True
                        })
                        form_catalog_mappings.append({
                            'product_name': chosen_prod,
                            'supplier_name': meta.get('supplier', 'Huabei'),
                            'supplier_item_no': it_no,
                            'supplier_desc': it_desc,
                            'rmb_price': rmb_p,
                            'pcs_per_ctn': pcs_ctn,
                            'invoice_file': os.path.basename(selected_file_path),
                            'matched_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
                        })

                submit_reconcile = st.form_submit_button(
                    f"💾 Save All {len(form_catalog_mappings)} Confirmed Mappings & Update Catalog RMB Prices",
                    type="primary",
                    use_container_width=True
                )

                if submit_reconcile:
                    if not form_catalog_mappings:
                        st.warning("No matched products selected to save.")
                    else:
                        with st.spinner("Saving mappings and updating Hermes AI knowledge base..."):
                            # 1. Upsert items to commercial_invoice_items
                            db.upsert_commercial_invoice_items(form_updates)
                            # 2. Save to product_supplier_mappings and propagate to hermes_items
                            db.save_product_supplier_mappings(form_catalog_mappings)

                        st.success(f"🎉 Successfully saved {len(form_catalog_mappings)} product mappings and synchronized RMB prices!")
                        st.balloons()
                        st.rerun()

# ---------------------------------------------------------------------------
# TAB 2: DATABASE ITEMS MATCHER (MANAGEMENT OF EXTRACTED DB ITEMS)
# ---------------------------------------------------------------------------
with tab_db_items:
    st.subheader("Commercial Invoice Items Database & Tally Matcher")
    st.caption("Manage all extracted supplier item codes across your historical database. All data loads instantly from the database without re-reading spreadsheets.")

    if db_items.empty:
        st.info("No commercial invoice items in database yet. Ingest an invoice above to populate the database.")
    else:
        # Filters Row
        f1, f2, f3 = st.columns([1.5, 1.5, 3])
        with f1:
            status_filter = st.selectbox("Status Filter", ["Pending Mapping (Unmatched)", "Matched", "All Items"], index=0, key="db_status_filter")
        with f2:
            suppliers_list = ["All Suppliers"] + sorted(db_items['supplier_name'].dropna().unique().tolist())
            supplier_filter = st.selectbox("Supplier", suppliers_list, index=0, key="db_sup_filter")
        with f3:
            search_query = st.text_input("🔍 Search Item Code, Description, or Tally Product", "", key="db_search_input")

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
                filtered_df['supplier_item_no'].astype(str).str.lower().str.contains(q, regex=False) |
                filtered_df['supplier_desc'].astype(str).str.lower().str.contains(q, regex=False) |
                filtered_df['tally_product_name'].astype(str).str.lower().str.contains(q, regex=False)
            ]

        st.markdown(f"**Showing {len(filtered_df)} items** (out of {len(db_items)} total items in DB)")

        # Quick Batch Actions
        high_conf_pending = db_items[(db_items['is_matched'] == False) & (db_items['match_confidence'] >= 0.8) & (db_items['tally_product_name'].notna())]
        if not high_conf_pending.empty:
            b_col1, b_col2 = st.columns([2.5, 3.5])
            with b_col1:
                if st.button(f"⚡ Accept All {len(high_conf_pending)} High-Confidence Auto-Matches (>80%)", type="secondary", use_container_width=True, key="accept_high_conf_btn"):
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
            items_to_show = filtered_df.head(100)
            if len(filtered_df) > 100:
                st.caption(f"Showing first 100 of {len(filtered_df)} items. Use the search bar above to narrow down results.")

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
                            f"Tally Product for {it_no}_{key}",
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
# TAB 3: ACTIVE RMB PRICE CATALOG
# ---------------------------------------------------------------------------
with tab_catalog:
    st.subheader("Active RMB Price Catalog & Pack Sizes")
    st.caption("These prices and master pack sizes are actively utilized by the Purchase Order suggestion engine and the WhatsApp AI assistant.")

    current_mappings = db.get_product_supplier_mappings()

    if current_mappings.empty:
        st.info("No products mapped with RMB prices yet. Reconcile invoices in the first tab to populate this catalog.")
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
                display_cat['product_name'].astype(str).str.lower().str.contains(q, regex=False) |
                display_cat['supplier_item_no'].astype(str).str.lower().str.contains(q, regex=False) |
                display_cat['supplier_desc'].astype(str).str.lower().str.contains(q, regex=False)
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

        csv_data = display_cat.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Active RMB Catalog (CSV)",
            data=csv_data,
            file_name=f"RMB_Price_Catalog_{datetime.date.today().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )

# ---------------------------------------------------------------------------
# TAB 4: PRICE CHANGE HISTORY
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
# TAB 5: INVOICE ARCHIVE
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
