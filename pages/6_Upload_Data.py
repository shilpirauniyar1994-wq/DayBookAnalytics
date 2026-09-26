"""
DayBook Analytics — Upload & Sync Data Page
Clean, deduplicated ingestion of Tally Day Book exports into Supabase Cloud Database
with overlap detection, folder synchronization, and cloud upload history.
"""

import streamlit as st
import pandas as pd
import datetime
import os
import db
from parser import parse_daybook
from upload import full_upload_pipeline
from ui_utils import apply_global_styles

st.set_page_config(page_title="Upload Data — DayBook Analytics", page_icon="📤", layout="wide")
apply_global_styles()

st.title("📤 Import & Sync Tally Day Books")
st.caption("Upload and sync Day Book exports with automatic duplicate prevention, overlap comparison, and cloud persistence.")

is_connected = db.is_supabase_configured()

if is_connected:
    st.success("🟢 **Supabase Cloud Database Connected:** Your transactions will be stored and synchronized with Supabase.")
else:
    st.info("ℹ️ **Local Mode Active:** Data is cached locally. To connect to Supabase cloud, configure `.env`.")

daybook_dir = "daybooks"
os.makedirs(daybook_dir, exist_ok=True)
folder_files = sorted([f for f in os.listdir(daybook_dir) if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith(('~', '.'))])

tab_folder, tab_upload, tab_stksum, tab_history = st.tabs([
    "📁 DayBooks Folder (`daybooks/`)",
    "📤 Upload New Export File",
    "📊 Stock Summary & Opening Balances",
    "📜 Cloud Upload History"
])

# ---------------------------------------------------------------------------
# TAB 1: DAYBOOKS FOLDER
# ---------------------------------------------------------------------------
with tab_folder:
    st.subheader(f"Files Detected in `{daybook_dir}/` ({len(folder_files)} exports)")
    st.caption("All DayBook files placed in the `daybooks/` folder can be synced directly to Supabase with automatic deduplication.")

    if not folder_files:
        st.info(f"No DayBook files found in `{daybook_dir}/`. Drop your exported spreadsheets into that folder or use the 'Upload New Export File' tab.")
    else:
        # File inventory table
        inv_data = []
        for f in folder_files:
            p = os.path.join(daybook_dir, f)
            sz_mb = os.path.getsize(p) / (1024 * 1024)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')
            inv_data.append({
                'Filename': f,
                'File Size (MB)': round(sz_mb, 2),
                'Modified': mtime
            })
        st.dataframe(pd.DataFrame(inv_data), use_container_width=True, hide_index=True)

        col_sync_all, col_select_one = st.columns([2, 3])

        with col_sync_all:
            sync_all_clicked = st.button("🚀 Sync All Daybooks to Supabase", type="primary", use_container_width=True)

        if sync_all_clicked:
            if not is_connected:
                st.error("Cannot sync to cloud: Supabase is not connected. Please verify your `.env` configuration.")
            else:
                progress_bar = st.progress(0.0)
                status_text = st.empty()

                total_files = len(folder_files)
                sync_summary = []

                for idx, fname in enumerate(folder_files):
                    fpath = os.path.join(daybook_dir, fname)
                    sz = os.path.getsize(fpath)

                    def make_prog_cb(file_idx, total_f, name):
                        def cb(pct, msg):
                            overall = (file_idx + pct) / total_f
                            progress_bar.progress(overall)
                            status_text.text(f"[{file_idx+1}/{total_f}] {name}: {msg}")
                        return cb

                    try:
                        res = full_upload_pipeline(
                            fpath,
                            progress_callback=make_prog_cb(idx, total_files, fname),
                            file_size=sz,
                            filename=fname
                        )
                        sync_summary.append({
                            'File': fname,
                            'Status': 'Success',
                            'New Vouchers': res['vouchers']['inserted'],
                            'Duplicates Skipped': res['vouchers']['skipped'],
                            'Line Items': res['line_items']['inserted']
                        })
                    except Exception as e:
                        sync_summary.append({
                            'File': fname,
                            'Status': f"Failed: {e}",
                            'New Vouchers': 0,
                            'Duplicates Skipped': 0,
                            'Line Items': 0
                        })

                progress_bar.progress(1.0)
                status_text.text("All files processed!")
                st.success("🎉 **Batch Sync Complete!** Review results below:")
                st.dataframe(pd.DataFrame(sync_summary), use_container_width=True, hide_index=True)
                db.refresh_local_cache()
                st.balloons()

        st.markdown("---")
        st.markdown("##### 🔍 Inspect or Sync an Individual DayBook File")
        selected_file = st.selectbox("Select file to preview / import", folder_files)

        if selected_file:
            sel_path = os.path.join(daybook_dir, selected_file)
            col_parse, _ = st.columns([2, 3])
            with col_parse:
                parse_one_btn = st.button(f"Analyze & Preview '{selected_file}'", use_container_width=True)

            if parse_one_btn:
                with st.spinner(f"Parsing {selected_file}..."):
                    v_df, li_df = parse_daybook(sel_path)
                    st.session_state[f'preview_{selected_file}'] = (v_df, li_df)

            if f'preview_{selected_file}' in st.session_state:
                v_df, li_df = st.session_state[f'preview_{selected_file}']
                st.markdown(f"**Date Span:** `{v_df['date'].min()}` to `{v_df['date'].max()}` | **Vouchers:** `{len(v_df):,}` | **Line Items:** `{len(li_df):,}`")

                if st.button(f"Import '{selected_file}' to Supabase Now", type="primary"):
                    p_bar = st.progress(0.0)
                    s_txt = st.empty()
                    def one_prog(pct, msg):
                        p_bar.progress(pct)
                        s_txt.text(msg)
                    res = full_upload_pipeline(sel_path, progress_callback=one_prog, file_size=os.path.getsize(sel_path), filename=selected_file)
                    st.success(f"✅ Successfully imported {selected_file}! Inserted: {res['vouchers']['inserted']} vouchers, {res['vouchers']['skipped']} duplicates skipped.")
                    db.refresh_local_cache()

# ---------------------------------------------------------------------------
# TAB 2: UPLOAD NEW EXPORT FILE
# ---------------------------------------------------------------------------
with tab_upload:
    st.subheader("Upload New Day Book File")
    st.caption("Upload newly exported Day Book spreadsheets (.xlsx or .xls) from Tally.")

    uploaded_file = st.file_uploader(
        "Choose an exported Day Book (.xlsx or .xls)",
        type=['xlsx', 'xls'],
        help="Export from Tally using Alt+E -> Excel format -> Detailed view",
        key="daybook_manual_uploader"
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_size = len(file_bytes)

        # Save to daybooks/ folder so it's persisted
        target_path = os.path.join(daybook_dir, uploaded_file.name)
        with open(target_path, "wb") as f:
            f.write(file_bytes)

        with st.spinner("Analyzing voucher structures and checking for existing records..."):
            file_vouchers, file_items = parse_daybook(target_path)

        if file_vouchers.empty:
            st.error("Could not find any voucher records in the uploaded file. Please ensure it's a valid Tally Day Book export.")
        else:
            file_start = file_vouchers['date'].min()
            file_end = file_vouchers['date'].max()

            # Compare against database
            current_vouchers = db.get_vouchers_df()
            if not current_vouchers.empty:
                def make_keys(df):
                    return set(zip(
                        df['date'].astype(str),
                        df['voucher_type'].astype(str).str.strip(),
                        df['voucher_no'].astype(str).str.strip(),
                        df['party_name'].astype(str).str.strip()
                    ))
                existing_keys = make_keys(current_vouchers)
                incoming_keys = make_keys(file_vouchers)
                new_keys = incoming_keys - existing_keys
                dup_keys = incoming_keys & existing_keys
                new_count = len(new_keys)
                dup_count = len(dup_keys)
            else:
                new_count = len(file_vouchers)
                dup_count = 0

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Vouchers in File", f"{len(file_vouchers):,}")
            c2.metric("Duplicates (Will Skip)", f"{dup_count:,}", delta_color="off")
            c3.metric("🆕 New to Insert", f"{new_count:,}")
            c4.metric("Date Span", f"{file_start} to {file_end}")

            if st.button("🚀 Process & Import into Supabase", type="primary", key="import_manual_uploaded"):
                prog_bar = st.progress(0.0)
                stat_text = st.empty()
                def up_cb(pct, msg):
                    prog_bar.progress(pct)
                    stat_text.text(msg)
                res = full_upload_pipeline(target_path, progress_callback=up_cb, file_size=file_size, filename=uploaded_file.name)
                st.success(f"✅ Successfully imported {uploaded_file.name}! Vouchers inserted: {res['vouchers']['inserted']}, skipped duplicates: {res['vouchers']['skipped']}")
                db.refresh_local_cache()
                st.balloons()

# ---------------------------------------------------------------------------
# TAB 3: STOCK SUMMARY & OPENING BALANCES
# ---------------------------------------------------------------------------
with tab_stksum:
    st.subheader("📊 Tally Stock Summary & Opening Balances")
    st.caption("Manage product opening balances (as of 15-Jun-2025) and the 6 official business categories from `StkSum.xlsx`.")

    import stksum_parser
    from ui_utils import format_currency

    col_up, col_info = st.columns([2, 1])
    with col_up:
        uploaded_stk = st.file_uploader(
            "Upload new Stock Summary Excel file (`.xlsx`, `.xls`)",
            type=["xlsx", "xls"],
            key="stksum_uploader"
        )

    # Determine file to use: uploaded file or root StkSum.xlsx
    target_stk_file = None
    if uploaded_stk is not None:
        target_stk_file = uploaded_stk
    elif os.path.exists("StkSum.xlsx"):
        target_stk_file = "StkSum.xlsx"

    if target_stk_file is None:
        st.warning("No `StkSum.xlsx` file found in workspace root. Please upload your Tally Stock Summary export file above.")
    else:
        try:
            with st.spinner("Reading Stock Summary data..."):
                stk_df, cat_summary, stk_meta = stksum_parser.parse_stock_summary(target_stk_file)

            # High Level Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Catalog Products", f"{stk_meta['total_products']:,} items")
            m2.metric("Items with Opening Balance", f"{stk_meta['items_with_opening']:,} items")
            m3.metric("Total Opening Value", format_currency(stk_meta['total_opening_value']), help=f"Rs. {stk_meta['total_opening_value']:,.2f}")
            m4.metric("Total Closing Value", format_currency(stk_meta['total_closing_value']), help=f"Rs. {stk_meta['total_closing_value']:,.2f}")

            st.markdown("---")

            # 6 Official Categories Breakdown
            st.subheader("Official Product Category Breakdown")
            cat_rows = []
            for c_name in stksum_parser.OFFICIAL_CATEGORIES:
                info = cat_summary.get(c_name, {})
                cat_rows.append({
                    'Category': c_name,
                    'Products Count': info.get('product_count', 0),
                    'With Opening Stock': info.get('items_with_stock', 0),
                    'Opening Value (Rs.)': round(info.get('opening_val', 0.0), 2),
                    'Closing Value (Rs.)': round(info.get('closing_val', 0.0), 2),
                })
            st.dataframe(
                pd.DataFrame(cat_rows),
                column_config={
                    'Category': st.column_config.TextColumn('Category', width='medium'),
                    'Products Count': st.column_config.NumberColumn('Total Products', format='%,.0f'),
                    'With Opening Stock': st.column_config.NumberColumn('With Opening Stock', format='%,.0f'),
                    'Opening Value (Rs.)': st.column_config.NumberColumn('Opening Value', format='Rs. %,.2f'),
                    'Closing Value (Rs.)': st.column_config.NumberColumn('Closing Value', format='Rs. %,.2f'),
                },
                use_container_width=True,
                hide_index=True
            )

            # Action button to sync to Supabase and update caches
            c_btn, c_stat = st.columns([2, 3])
            with c_btn:
                sync_stk_clicked = st.button("🚀 Sync Opening Balances & Categories to Supabase", type="primary", use_container_width=True)

            if sync_stk_clicked:
                with st.spinner("Saving locally and syncing 1,020 products to Supabase..."):
                    op_saved, pg_saved = stksum_parser.save_stock_summary_data(stk_df)
                    db.refresh_local_cache()
                st.success(f"✅ Successfully synced {op_saved} opening stock balances and {pg_saved} category mappings to Supabase and local cache!")
                st.balloons()

            st.markdown("---")

            # Product Inspector Table
            st.subheader("Search Stock Summary Products")
            search_prod = st.text_input("Search product...", "", placeholder="Type name e.g. 'Jeep', 'Ballon', 'Gun'...")
            cat_filter = st.selectbox("Filter Category", ['All Categories'] + stksum_parser.OFFICIAL_CATEGORIES)

            preview_df = stk_df.copy()
            if cat_filter != 'All Categories':
                preview_df = preview_df[preview_df['product_group'] == cat_filter]
            if search_prod:
                preview_df = preview_df[preview_df['product_name'].str.contains(search_prod, case=False, na=False)]

            st.dataframe(
                preview_df[[
                    'product_name', 'product_group', 'opening_qty', 'opening_rate',
                    'opening_value', 'closing_qty', 'closing_rate', 'closing_value'
                ]],
                column_config={
                    'product_name': st.column_config.TextColumn('Product Name', width='medium'),
                    'product_group': 'Category',
                    'opening_qty': st.column_config.NumberColumn('Opening Qty', format='%,.0f'),
                    'opening_rate': st.column_config.NumberColumn('Opening Rate', format='Rs. %,.2f'),
                    'opening_value': st.column_config.NumberColumn('Opening Value', format='Rs. %,.2f'),
                    'closing_qty': st.column_config.NumberColumn('Closing Qty', format='%,.0f'),
                    'closing_rate': st.column_config.NumberColumn('Closing Rate', format='Rs. %,.2f'),
                    'closing_value': st.column_config.NumberColumn('Closing Value', format='Rs. %,.2f'),
                },
                use_container_width=True,
                hide_index=True
            )

        except Exception as e:
            st.error(f"Error parsing Stock Summary file: {e}")

# ---------------------------------------------------------------------------
# TAB 4: CLOUD UPLOAD HISTORY
# ---------------------------------------------------------------------------
with tab_history:
    st.subheader("Supabase Cloud Ingestion Log")
    st.caption("Audit trail of all Tally Day Book imports committed to Supabase.")

    if not is_connected:
        st.info("Upload history is tracked when connected to Supabase.")
    else:
        client = db.get_client()
        try:
            res = client.table('upload_history').select('*').order('uploaded_at', desc=True).limit(50).execute()
            if res.data:
                hist_df = pd.DataFrame(res.data)
                st.dataframe(
                    hist_df[[
                        'filename', 'date_range_start', 'date_range_end',
                        'total_vouchers', 'new_inserted', 'skipped',
                        'total_line_items', 'status', 'uploaded_at'
                    ]],
                    column_config={
                        'filename': 'File Name',
                        'date_range_start': 'Start Date',
                        'date_range_end': 'End Date',
                        'total_vouchers': st.column_config.NumberColumn('Total Vouchers', format='%d'),
                        'new_inserted': st.column_config.NumberColumn('New Inserted', format='%d'),
                        'skipped': st.column_config.NumberColumn('Duplicates Skipped', format='%d'),
                        'total_line_items': st.column_config.NumberColumn('Line Items', format='%d'),
                        'status': 'Status',
                        'uploaded_at': 'Upload Timestamp'
                    },
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No upload history recorded in Supabase yet. Run an import in the tabs above to begin tracking.")
        except Exception as e:
            st.error(f"Error loading upload history: {e}")
