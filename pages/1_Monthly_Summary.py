"""
DayBook Analytics — Monthly Summary Page
Tracks monthly sales, purchases, payments, receipts, and trend charts.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import importlib
import db
importlib.reload(db)
from ui_utils import apply_global_styles, format_currency, render_html_table

st.set_page_config(page_title="Monthly Summary — DayBook Analytics", page_icon="📈", layout="wide")
apply_global_styles()

st.title("📈 Monthly Sales, Purchases & Expenses")
st.caption("Consolidated accounting performance across periods")

v_df = db.get_vouchers_df()

if v_df.empty:
    st.warning("No voucher data found. Please upload a day book file first.")
    st.stop()

# Filters in top bar
def get_month_str(row):
    if pd.notna(row.get('month')) and str(row.get('month')).strip():
        return str(row['month']).strip()
    d = row.get('date')
    if hasattr(d, 'strftime'):
        return d.strftime('%Y-%m')
    s = str(d)
    return s[:7] if len(s) >= 7 else 'Unknown'

v_df['month'] = v_df.apply(get_month_str, axis=1)
available_months = sorted(v_df['month'].dropna().unique().tolist())
available_categories = sorted(v_df['voucher_category'].dropna().unique().tolist())

f_col1, f_col2 = st.columns([2, 2])
with f_col1:
    selected_months = st.multiselect(
        "Select Months",
        options=available_months,
        default=available_months,
        help="Filter dashboard metrics by month"
    )

with f_col2:
    selected_categories = st.multiselect(
        "Filter Voucher Types",
        options=available_categories,
        default=available_categories,
        help="Include/exclude accounting categories"
    )

if not selected_months or not selected_categories:
    st.info("Please select at least one month and one category.")
    st.stop()

# Filter data
filtered_df = v_df[
    (v_df['month'].isin(selected_months)) &
    (v_df['voucher_category'].isin(selected_categories))
]

# Calculate High Level Totals
sales_amt = filtered_df[filtered_df['voucher_category'] == 'Sales']['debit_amount'].sum()
purch_amt = filtered_df[filtered_df['voucher_category'] == 'Purchase']['credit_amount'].sum()
pay_amt = filtered_df[filtered_df['voucher_category'] == 'Payment']['debit_amount'].sum()
rec_amt = filtered_df[filtered_df['voucher_category'] == 'Receipt']['credit_amount'].sum()
net_position = sales_amt - purch_amt - pay_amt

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Sales", format_currency(sales_amt), help=f"Full Sales: Rs. {sales_amt:,.2f}")
c2.metric("Total Purchases", format_currency(purch_amt), help=f"Full Purchases: Rs. {purch_amt:,.2f}")
c3.metric("Receipts In", format_currency(rec_amt), help=f"Full Receipts: Rs. {rec_amt:,.2f}")
c4.metric("Expenses / Payments", format_currency(pay_amt), help=f"Full Expenses: Rs. {pay_amt:,.2f}")
c5.metric("Net Margin", format_currency(net_position), delta=f"{'Positive' if net_position >= 0 else 'Deficit'}", help=f"Net: Rs. {net_position:,.2f}")

st.markdown("---")

# Monthly Breakdown Bar Chart
monthly_agg = []
for m in selected_months:
    m_data = v_df[v_df['month'] == m]
    s = m_data[m_data['voucher_category'] == 'Sales']['debit_amount'].sum()
    p = m_data[m_data['voucher_category'] == 'Purchase']['credit_amount'].sum()
    e = m_data[m_data['voucher_category'] == 'Payment']['debit_amount'].sum()
    r = m_data[m_data['voucher_category'] == 'Receipt']['credit_amount'].sum()
    monthly_agg.append({
        'Month': m,
        'Sales': s,
        'Purchase': p,
        'Payment/Expense': e,
        'Receipt': r
    })

monthly_chart_df = pd.DataFrame(monthly_agg)

# Monthly Breakdown Bar Chart (Full Left to Right)
st.subheader("Monthly Financial Comparison (Sales vs Purchase vs Payments vs Receipts)")
fig_bar = go.Figure()
fig_bar.add_trace(go.Bar(x=monthly_chart_df['Month'], y=monthly_chart_df['Sales'], name='Sales', marker_color='#2563EB'))
fig_bar.add_trace(go.Bar(x=monthly_chart_df['Month'], y=monthly_chart_df['Purchase'], name='Purchase', marker_color='#DC2626'))
fig_bar.add_trace(go.Bar(x=monthly_chart_df['Month'], y=monthly_chart_df['Payment/Expense'], name='Payment/Expense', marker_color='#F59E0B'))
fig_bar.add_trace(go.Bar(x=monthly_chart_df['Month'], y=monthly_chart_df['Receipt'], name='Receipt', marker_color='#10B981'))
fig_bar.update_layout(
    barmode='group',
    height=420,
    margin=dict(l=20, r=20, t=30, b=20),
    xaxis_title="Month",
    yaxis_title="Amount (Rs.)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig_bar, use_container_width=True)

st.markdown("---")

# Daily Sales Trend Line (0 to 6M Range, outliers > 6M excluded)
st.subheader("Daily Sales Velocity Trend (0 to 6M)")
st.caption("Tracking daily sales run-rate between 0 and 6M (Rs. 60 Lakhs). High-value bulk spikes above 6M are filtered out.")
sales_only = filtered_df[filtered_df['voucher_category'] == 'Sales'].copy()
if not sales_only.empty:
    daily_sales = sales_only.groupby('date')['debit_amount'].sum().reset_index()
    daily_sales.columns = ['Date', 'Sales Amount']
    # Filter between 0 and 6M (6,000,000)
    daily_sales = daily_sales[(daily_sales['Sales Amount'] >= 0) & (daily_sales['Sales Amount'] <= 6_000_000)]
    daily_sales['Date'] = daily_sales['Date'].astype(str)
else:
    daily_sales = pd.DataFrame(columns=['Date', 'Sales Amount'])

if not daily_sales.empty:
    fig_line = px.line(
        daily_sales,
        x='Date',
        y='Sales Amount',
        title="Daily Sales Trend (0 - 6M)",
        color_discrete_sequence=['#2563EB']
    )
    fig_line.update_traces(mode='lines+markers', hovertemplate="Date: %{x}<br>Sales: Rs. %{y:,.2f}")
    fig_line.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=30, b=20),
        yaxis=dict(range=[0, 6_000_000], title="Daily Sales (Rs.)")
    )
    st.plotly_chart(fig_line, use_container_width=True)
else:
    st.info("No daily sales recorded within 0 to 6M range.")

# Monthly Summary Table
st.subheader("📋 Monthly Financial Summary Table")
st.caption("Consolidated period-by-period financial performance with exact totals")

m_c1, m_c2 = st.columns([4, 2])
with m_c1:
    st.download_button(
        label="📥 Download Summary as CSV",
        data=monthly_chart_df.to_csv(index=False).encode('utf-8'),
        file_name="Monthly_Financial_Summary.csv",
        mime="text/csv",
        key="monthly_csv_dl"
    )
with m_c2:
    monthly_view_mode = st.radio(
        "Table View Mode",
        ["🎨 High-Contrast Clean Table", "📊 Interactive Data Grid"],
        horizontal=True,
        key="monthly_view_mode"
    )

if monthly_view_mode == "🎨 High-Contrast Clean Table":
    headers = [
        ("Period", "left"),
        ("Sales (Rs.)", "right"),
        ("Purchases (Rs.)", "right"),
        ("Expenses / Payments (Rs.)", "right"),
        ("Receipts (Rs.)", "right")
    ]
    rows_html = []
    for _, r in monthly_chart_df.iterrows():
        rows_html.append(f"""<tr>
            <td class='tbl-cell-bold' style='padding:11px 14px; font-size:14.5px;'>{r['Month']}</td>
            <td class='tbl-val-sales' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {r['Sales']:,.2f}</td>
            <td class='tbl-val-purchase' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {r['Purchase']:,.2f}</td>
            <td class='tbl-val-expense' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {r['Payment/Expense']:,.2f}</td>
            <td class='tbl-val-receipt' style='padding:11px 14px; text-align:right; font-size:14px;'>Rs. {r['Receipt']:,.2f}</td>
        </tr>""")
    render_html_table(headers, rows_html, max_height=420)
else:
    st.dataframe(
        monthly_chart_df,
        column_config={
            'Month': st.column_config.TextColumn('Period', width=180),
            'Sales': st.column_config.NumberColumn('Sales', format='Rs. %,.2f', width=180),
            'Purchase': st.column_config.NumberColumn('Purchases', format='Rs. %,.2f', width=180),
            'Payment/Expense': st.column_config.NumberColumn('Expenses / Payments', format='Rs. %,.2f', width=200),
            'Receipt': st.column_config.NumberColumn('Receipts', format='Rs. %,.2f', width=180),
        },
        height=420,
        use_container_width=True,
        hide_index=True
    )
