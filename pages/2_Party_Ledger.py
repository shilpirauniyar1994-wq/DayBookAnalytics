"""
DayBook Analytics — Party Ledger Page
View transaction history, narrations, running balances, and outstanding party accounts.
"""

import streamlit as st
import pandas as pd
import datetime
import importlib
import db
importlib.reload(db)
from ui_utils import apply_global_styles, format_currency, render_html_table

st.set_page_config(page_title="Party Ledger — DayBook Analytics", page_icon="📒", layout="wide")
apply_global_styles()

st.title("📒 Party Ledger & Accounts")
st.caption("Inspect individual customer & supplier statements with complete narrations")

all_parties = db.get_all_parties()

if not all_parties:
    st.warning("No parties found in the dataset.")
    st.stop()

tab_single, tab_all = st.tabs(["👤 Individual Party Statement", "📑 All Parties Balance Summary"])

with tab_single:
    col_sel, col_date, col_type = st.columns([2, 2, 1.5])

    with col_sel:
        selected_party = st.selectbox(
            "Select Customer or Supplier",
            options=all_parties,
            index=0,
            help="Choose a party to inspect their transaction ledger"
        )

    # Load party ledger
    ledger_df = db.get_party_ledger(selected_party)

    if ledger_df.empty:
        st.info(f"No transactions found for {selected_party}.")
    else:
        valid_dates = [d for d in ledger_df['date'] if isinstance(d, datetime.date)]
        min_date = min(valid_dates) if valid_dates else datetime.date.today()
        max_date = max(valid_dates) if valid_dates else datetime.date.today()

        with col_date:
            date_range = st.date_input(
                "Filter Date Range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )

        with col_type:
            types_available = ['All'] + sorted(ledger_df['voucher_type'].dropna().unique().tolist())
            selected_vch_type = st.selectbox("Voucher Type", types_available)

        # Apply filters
        start_d, end_d = (date_range[0], date_range[1]) if isinstance(date_range, (tuple, list)) and len(date_range) == 2 else (min_date, max_date)
        date_mask = ledger_df['date'].apply(lambda d: start_d <= d <= end_d if isinstance(d, datetime.date) else False)
        filtered_ledger = ledger_df[date_mask].copy()

        if selected_vch_type != 'All':
            filtered_ledger = filtered_ledger[filtered_ledger['voucher_type'] == selected_vch_type]

        # Recalculate running balance
        filtered_ledger['debit_amount'] = filtered_ledger['debit_amount'].fillna(0.0)
        filtered_ledger['credit_amount'] = filtered_ledger['credit_amount'].fillna(0.0)
        filtered_ledger['running_balance'] = (filtered_ledger['debit_amount'] - filtered_ledger['credit_amount']).cumsum()

        # Summary KPIs
        tot_dr = filtered_ledger['debit_amount'].sum()
        tot_cr = filtered_ledger['credit_amount'].sum()
        closing_bal = tot_dr - tot_cr

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Debit (Billed / Paid)", format_currency(tot_dr, compact=False), help=f"Exact: Rs. {tot_dr:,.2f}")
        m2.metric("Total Credit (Received / Sold)", format_currency(tot_cr, compact=False), help=f"Exact: Rs. {tot_cr:,.2f}")
        bal_type = "Dr (Receivable)" if closing_bal >= 0 else "Cr (Payable)"
        m3.metric("Closing Balance", f"{format_currency(abs(closing_bal), compact=False)} {bal_type}", help=f"Net Balance: Rs. {closing_bal:,.2f}")
        m4.metric("Transactions Count", f"{len(filtered_ledger):,} records")

        st.markdown("---")

        st.subheader(f"📋 Ledger Statement — {selected_party}")
        display_cols = ['date', 'miti', 'voucher_type', 'voucher_no', 'debit_amount', 'credit_amount', 'running_balance', 'narration']
        display_df = filtered_ledger[display_cols].copy()

        l_c1, l_c2 = st.columns([4, 2])
        with l_c1:
            st.download_button(
                label=f"📥 Download Ledger CSV ({selected_party})",
                data=display_df.to_csv(index=False).encode('utf-8'),
                file_name=f"Ledger_{selected_party.replace(' ', '_')}.csv",
                mime="text/csv",
                key="party_ledger_csv_dl"
            )
        with l_c2:
            ledger_view_mode = st.radio(
                "Table View Mode",
                ["🎨 High-Contrast Clean Table", "📊 Interactive Data Grid"],
                horizontal=True,
                key="ledger_view_mode"
            )

        if ledger_view_mode == "🎨 High-Contrast Clean Table":
            headers = [
                ("Date", "left"),
                ("Nepali Miti", "left"),
                ("Voucher Type", "left"),
                ("Vch #", "left"),
                ("Debit (Dr)", "right"),
                ("Credit (Cr)", "right"),
                ("Running Balance (Rs.)", "right"),
                ("Narration / Cheque Details", "left")
            ]
            rows_html = []
            for _, r in display_df.iterrows():
                bal = float(r['running_balance'])
                bal_class = "tbl-val-sales" if bal >= 0 else "tbl-val-purchase"
                dr_val = f"Rs. {r['debit_amount']:,.2f}" if r['debit_amount'] > 0 else "—"
                cr_val = f"Rs. {r['credit_amount']:,.2f}" if r['credit_amount'] > 0 else "—"
                narr = str(r['narration']) if pd.notna(r['narration']) else ""
                miti_str = str(r['miti']) if pd.notna(r['miti']) else "—"

                rows_html.append(f"""<tr>
                    <td class='tbl-cell-main' style='padding:11px 14px; font-size:13.5px;'>{r['date']}</td>
                    <td class='tbl-cell-muted' style='padding:11px 14px; font-size:13px;'>{miti_str}</td>
                    <td style='padding:11px 14px;'><span class='tbl-pill-vch'>{r['voucher_type']}</span></td>
                    <td class='tbl-cell-bold' style='padding:11px 14px; font-size:13px;'>{r['voucher_no']}</td>
                    <td class='tbl-cell-main' style='padding:11px 14px; text-align:right; font-size:13.5px;'>{dr_val}</td>
                    <td class='tbl-val-sales' style='padding:11px 14px; text-align:right; font-size:13.5px;'>{cr_val}</td>
                    <td class='{bal_class}' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {bal:,.2f}</td>
                    <td class='tbl-cell-muted' style='padding:11px 14px; font-size:13px; max-width:300px;'>{narr}</td>
                </tr>""")
            render_html_table(headers, rows_html, max_height=550)
        else:
            st.dataframe(
                display_df,
                column_config={
                    'date': st.column_config.DateColumn('Date', format='YYYY-MM-DD', width=120),
                    'miti': st.column_config.TextColumn('Nepali Miti', width=120),
                    'voucher_type': st.column_config.TextColumn('Voucher Type', width=130),
                    'voucher_no': st.column_config.TextColumn('Vch #', width=110),
                    'debit_amount': st.column_config.NumberColumn('Debit (Dr)', format='Rs. %,.2f', width=150),
                    'credit_amount': st.column_config.NumberColumn('Credit (Cr)', format='Rs. %,.2f', width=150),
                    'running_balance': st.column_config.NumberColumn('Balance', format='Rs. %,.2f', width=160),
                    'narration': st.column_config.TextColumn('Narration / Cheque Details', width=300),
                },
                height=550,
                use_container_width=True,
                hide_index=True
            )

with tab_all:
    st.subheader("📋 All Parties Balance Summary")
    st.caption("Consolidated list of all parties with total billed, received/paid, and net balances.")

    all_vouchers = db.get_vouchers_df()
    if not all_vouchers.empty:
        summary_df = all_vouchers.groupby('party_name').agg(
            total_debit=('debit_amount', 'sum'),
            total_credit=('credit_amount', 'sum'),
            transaction_count=('voucher_no', 'count'),
            last_date=('date', 'max')
        ).reset_index()

        summary_df['net_balance'] = summary_df['total_debit'] - summary_df['total_credit']
        summary_df['balance_type'] = summary_df['net_balance'].apply(lambda x: 'Dr (Receivable)' if x >= 0 else 'Cr (Payable)')

        s_col1, s_col2 = st.columns([3, 2])
        with s_col1:
            search_query = st.text_input("🔍 Search party by name...", "", key="all_parties_search")
        with s_col2:
            parties_view_mode = st.radio(
                "Table View Mode",
                ["🎨 High-Contrast Clean Table", "📊 Interactive Data Grid"],
                horizontal=True,
                key="parties_view_mode"
            )

        if search_query:
            summary_df = summary_df[summary_df['party_name'].str.contains(search_query, case=False, na=False)]

        sorted_parties = summary_df.sort_values('total_debit', ascending=False).reset_index(drop=True)

        st.download_button(
            label="📥 Download All Parties Summary (CSV)",
            data=sorted_parties.to_csv(index=False).encode('utf-8'),
            file_name="All_Parties_Balance_Summary.csv",
            mime="text/csv",
            key="all_parties_csv_dl"
        )

        if parties_view_mode == "🎨 High-Contrast Clean Table":
            p_headers = [
                ("Party Name", "left"),
                ("Total Debit (Rs.)", "right"),
                ("Total Credit (Rs.)", "right"),
                ("Net Balance (Rs.)", "right"),
                ("Status", "center"),
                ("Total Txns", "center"),
                ("Last Active", "center")
            ]
            p_rows_html = []
            for _, r in sorted_parties.head(100).iterrows():
                bal = float(r['net_balance'])
                is_dr = bal >= 0
                st_badge = "<span style='background:#DCFCE7; color:#15803D; padding:3px 9px; border-radius:10px; font-weight:700; font-size:12px;'>Dr (Receivable)</span>" if is_dr else "<span style='background:#FEE2E2; color:#B91C1C; padding:3px 9px; border-radius:10px; font-weight:700; font-size:12px;'>Cr (Payable)</span>"
                bal_class = "tbl-val-sales" if is_dr else "tbl-val-purchase"

                p_rows_html.append(f"""<tr>
                    <td class='tbl-cell-main' style='padding:11px 14px; font-size:14px;'>{r['party_name']}</td>
                    <td class='tbl-cell-bold' style='padding:11px 14px; text-align:right; font-size:13.5px;'>Rs. {r['total_debit']:,.2f}</td>
                    <td class='tbl-val-sales' style='padding:11px 14px; text-align:right; font-size:13.5px;'>Rs. {r['total_credit']:,.2f}</td>
                    <td class='{bal_class}' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {abs(bal):,.2f}</td>
                    <td style='padding:11px 14px; text-align:center;'>{st_badge}</td>
                    <td style='padding:11px 14px; text-align:center;'><span class='tbl-pill-count'>{r['transaction_count']}</span></td>
                    <td class='tbl-cell-subtle' style='padding:11px 14px; text-align:center; font-size:13px;'>{r['last_date']}</td>
                </tr>""")
            render_html_table(p_headers, p_rows_html, max_height=600)
            if len(sorted_parties) > 100:
                st.caption(f"Showing top 100 of {len(sorted_parties):,} parties. Download CSV for full dataset.")
        else:
            st.dataframe(
                sorted_parties,
                column_config={
                    'party_name': st.column_config.TextColumn('Party Name', width=280),
                    'total_debit': st.column_config.NumberColumn('Total Debit', format='Rs. %,.2f', width=160),
                    'total_credit': st.column_config.NumberColumn('Total Credit', format='Rs. %,.2f', width=160),
                    'net_balance': st.column_config.NumberColumn('Net Balance', format='Rs. %,.2f', width=160),
                    'balance_type': st.column_config.TextColumn('Status', width=140),
                    'transaction_count': st.column_config.NumberColumn('Total Txns', format='%,.0f', width=110),
                    'last_date': st.column_config.DateColumn('Last Active', format='YYYY-MM-DD', width=120),
                },
                height=600,
                use_container_width=True,
                hide_index=True
            )
