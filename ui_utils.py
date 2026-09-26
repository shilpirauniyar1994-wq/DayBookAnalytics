"""
DayBook Analytics — UI Utilities & Responsive Formatting
Provides shared styling, responsive metric typography, intelligent currency formatting,
and unified, high-legibility table rendering across all pages.
"""

import streamlit as st
import textwrap

OFFICIAL_CATEGORY_COLORS = {
    'Big Toys': {'bg': '#DBEAFE', 'fg': '#1E40AF', 'border': '#BFDBFE'},
    'Birthday Items': {'bg': '#FCE7F3', 'fg': '#9D174D', 'border': '#FBCFE8'},
    'Factory Item': {'bg': '#FEF3C7', 'fg': '#92400E', 'border': '#FDE68A'},
    'Fancy Toys': {'bg': '#F3E8FF', 'fg': '#6B21A8', 'border': '#E9D5FF'},
    'General': {'bg': '#F1F5F9', 'fg': '#334155', 'border': '#CBD5E1'},
    'Indian Item': {'bg': '#FFEDD5', 'fg': '#9A3412', 'border': '#FED7AA'},
}

def apply_global_styles():
    """
    Inject global CSS to fix metric truncation, ensure responsive card typography,
    and guarantee high contrast, crystal-clear legibility for all tables and grids across the app.
    """
    st.markdown("""
    <style>
        /* Responsive Metric Value Typography - Prevents '...' truncation */
        [data-testid="stMetricValue"] {
            font-size: 1.35rem !important;
            font-weight: 700 !important;
            line-height: 1.25 !important;
            overflow: visible !important;
            text-overflow: unset !important;
            white-space: normal !important;
            word-break: break-word !important;
        }

        /* Metric Label formatting */
        [data-testid="stMetricLabel"] {
            font-size: 0.82rem !important;
            font-weight: 600 !important;
            color: #64748B !important;
            line-height: 1.2 !important;
            overflow: visible !important;
            white-space: normal !important;
        }

        /* Metric Delta pill */
        [data-testid="stMetricDelta"] {
            font-size: 0.75rem !important;
            font-weight: 500 !important;
        }

        /* Metric card container padding */
        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border-radius: 8px;
            padding: 10px 14px;
            border: 1px solid #E2E8F0;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
            min-height: 90px;
        }

        /* High Legibility Table & Dataframe Styling */
        [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
            border: 1.5px solid #CBD5E1 !important;
            border-radius: 8px !important;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06) !important;
            background-color: #FFFFFF !important;
            overflow: hidden !important;
        }

        /* Crisp Unified HTML Table Styling */
        .unified-table-container {
            width: 100%;
            overflow-x: auto;
            max-height: 620px;
            border: 1.5px solid #CBD5E1;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
            background: #FFFFFF;
            margin-top: 10px;
            margin-bottom: 12px;
        }

        .unified-table {
            width: 100%;
            border-collapse: collapse;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            font-size: 14px;
            line-height: 1.5;
            color: #0F172A;
        }

        .unified-table thead tr {
            background: #1E3A8A;
            color: #FFFFFF;
            position: sticky;
            top: 0;
            z-index: 10;
            font-size: 13.5px;
            font-weight: 700;
            letter-spacing: 0.3px;
        }

        .unified-table th {
            padding: 13px 14px;
            white-space: nowrap;
            border-bottom: 2px solid #1E40AF;
        }

        .unified-table td {
            padding: 11px 14px;
            vertical-align: middle;
            border-bottom: 1px solid #E2E8F0;
        }

        .unified-table tbody tr {
            background-color: #FFFFFF;
        }

        .unified-table tbody tr:nth-of-type(even) {
            background-color: #F8FAFC;
        }

        .unified-table tbody tr:hover {
            background-color: #EEF2F6;
        }

        /* Unified Table Typography & Color System */
        .tbl-cell-main {
            font-weight: 600;
            color: #0F172A;
        }
        .tbl-cell-bold {
            font-weight: 700;
            color: #0F172A;
        }
        .tbl-cell-muted {
            color: #475569;
        }
        .tbl-cell-subtle {
            color: #64748B;
        }
        .tbl-val-sales, .tbl-val-dr {
            font-weight: 700;
            color: #047857;
        }
        .tbl-val-purchase, .tbl-val-cr {
            font-weight: 700;
            color: #DC2626;
        }
        .tbl-val-expense {
            font-weight: 600;
            color: #D97706;
        }
        .tbl-val-receipt {
            font-weight: 600;
            color: #2563EB;
        }
        .tbl-pill-vch {
            background: #F1F5F9;
            color: #334155;
            padding: 3px 8px;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 600;
            display: inline-block;
        }
        .tbl-pill-count {
            background: #F1F5F9;
            color: #475569;
            padding: 3px 9px;
            border-radius: 10px;
            font-size: 12.5px;
            font-weight: 600;
            display: inline-block;
        }

        /* Dark mode compatibility - High-Contrast Overrides */
        @media (prefers-color-scheme: dark) {
            div[data-testid="stMetric"] {
                background-color: #1E293B;
                border: 1px solid #334155;
            }
            [data-testid="stMetricLabel"] {
                color: #94A3B8 !important;
            }
            [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
                border: 1.5px solid #334155 !important;
                background-color: #0F172A !important;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
            }
            .unified-table-container {
                border: 1.5px solid #334155 !important;
                background: #0F172A !important;
            }
            .unified-table {
                color: #F8FAFC !important;
            }
            .unified-table thead tr {
                background: #1E3A8A !important;
                color: #FFFFFF !important;
            }
            .unified-table tbody tr {
                background-color: #0F172A !important;
            }
            .unified-table tbody tr:nth-of-type(even) {
                background-color: #1E293B !important;
            }
            .unified-table tbody tr:hover {
                background-color: #2E3E56 !important;
            }
            .unified-table td {
                border-bottom: 1px solid #243247 !important;
                color: #F8FAFC !important;
            }
            .tbl-cell-main, .tbl-cell-bold {
                color: #F8FAFC !important;
            }
            .tbl-cell-muted {
                color: #CBD5E1 !important;
            }
            .tbl-cell-subtle {
                color: #94A3B8 !important;
            }
            .tbl-val-sales, .tbl-val-dr {
                color: #34D399 !important; /* bright emerald-400 */
            }
            .tbl-val-purchase, .tbl-val-cr {
                color: #F87171 !important; /* bright red-400 */
            }
            .tbl-val-expense {
                color: #FBBF24 !important; /* bright amber-400 */
            }
            .tbl-val-receipt {
                color: #38BDF8 !important; /* bright electric sky-400 */
            }
            .tbl-pill-vch {
                background: #253347 !important;
                color: #E2E8F0 !important;
            }
            .tbl-pill-count {
                background: #253347 !important;
                color: #E2E8F0 !important;
            }
        }
    </style>
    """, unsafe_allow_html=True)

def get_category_badge(category: str) -> str:
    """Return crisp HTML pill badge for official product category."""
    cat = str(category or "").strip()
    conf = OFFICIAL_CATEGORY_COLORS.get(cat, {'bg': '#F1F5F9', 'fg': '#334155', 'border': '#CBD5E1'})
    return f"<span style='background:{conf['bg']}; color:{conf['fg']}; border:1px solid {conf['border']}; padding:3px 9px; border-radius:12px; font-size:12px; font-weight:600;'>{cat}</span>"

def get_stock_badge(stock: float) -> str:
    """Return colored pill badge for stock balance."""
    try:
        stk = float(stock)
    except (ValueError, TypeError):
        return "<span style='color:#64748B;'>0</span>"
    
    if stk > 0:
        return f"<span style='background:#DCFCE7; color:#15803D; border:1px solid #BBF7D0; padding:3px 9px; border-radius:12px; font-weight:700; font-size:13px;'>+{stk:,.0f}</span>"
    elif stk == 0:
        return "<span style='background:#F1F5F9; color:#64748B; border:1px solid #E2E8F0; padding:3px 9px; border-radius:12px; font-size:13px;'>0</span>"
    else:
        return f"<span style='background:#FEE2E2; color:#B91C1C; border:1px solid #FECACA; padding:3px 9px; border-radius:12px; font-weight:700; font-size:13px;'>{stk:,.0f}</span>"

def get_aging_badge(bucket: str) -> str:
    """Return crisp HTML pill badge for aging bucket."""
    b = str(bucket or "").strip()
    colors = {
        '0-30 days': ('#DCFCE7', '#15803D', '#BBF7D0'),
        '31-60 days': ('#DBEAFE', '#1E40AF', '#BFDBFE'),
        '61-90 days': ('#FEF3C7', '#92400E', '#FDE68A'),
        '91-180 days': ('#FFEDD5', '#C2410C', '#FED7AA'),   # Warm Orange (slow 3-6 months)
        '181-360 days': ('#FEE2E2', '#B91C1C', '#FECACA'),  # Crimson (stuck 6-12 months)
        '180-360 days': ('#FEE2E2', '#B91C1C', '#FECACA'),
        '180+ days': ('#FEE2E2', '#B91C1C', '#FECACA'),
        '360+ days': ('#FCE7F3', '#9D174D', '#FBCFE8'),     # Deep Rose (critical >1 year)
        '90+ days': ('#FFEDD5', '#C2410C', '#FED7AA'),
        'Never Sold': ('#F3E8FF', '#6B21A8', '#E9D5FF'),    # Violet
    }
    bg, fg, border = colors.get(b, ('#F1F5F9', '#475569', '#CBD5E1'))
    return f"<span style='background:{bg}; color:{fg}; border:1px solid {border}; padding:3px 9px; border-radius:12px; font-weight:600; font-size:12px;'>{b}</span>"

def render_html_table(headers: list, rows_html: list, max_height: int = 620):
    """
    Safely render a high-contrast HTML table using st.html.
    Guarantees no Markdown code-block escaping or indentation bugs.
    headers: list of tuples (title, align) e.g. [("Product Name", "left"), ("Period Qty Sold", "right")]
    rows_html: list of <tr>...</tr> HTML strings
    """
    th_items = []
    for title, align in headers:
        th_items.append(f"<th style='padding:13px 14px; text-align:{align}; font-weight:700;'>{title}</th>")
    
    th_str = "\n".join(th_items)
    tbody_str = "\n".join(rows_html)
    
    raw_html = f"""<div class='unified-table-container' style='max-height:{max_height}px;'>
<table class='unified-table'>
<thead>
<tr>
{th_str}
</tr>
</thead>
<tbody>
{tbody_str}
</tbody>
</table>
</div>"""
    
    if hasattr(st, 'html'):
        st.html(raw_html)
    else:
        st.markdown(textwrap.dedent(raw_html), unsafe_allow_html=True)

def format_currency(val: float, compact: bool = True, prefix: str = "Rs. ") -> str:
    """
    Format currency values for Nepali business context (NPR).
    When compact=True:
      >= 1 Crore (10M): 'Rs. 6.92 Cr'
      >= 1 Lakh (100k): 'Rs. 15.87 L'
      < 1 Lakh: 'Rs. 45,200'
    """
    if val is None or val != val:  # check for NaN
        return f"{prefix}0"
    
    abs_val = abs(val)
    sign = "-" if val < 0 else ""

    if compact:
        if abs_val >= 10_000_000:  # 1 Crore
            return f"{sign}{prefix}{abs_val / 10_000_000:.2f} Cr"
        elif abs_val >= 100_000:   # 1 Lakh
            return f"{sign}{prefix}{abs_val / 100_000:.2f} L"
        else:
            return f"{sign}{prefix}{abs_val:,.0f}"
    else:
        return f"{sign}{prefix}{abs_val:,.0f}"

def format_rmb(val: float, compact: bool = False) -> str:
    """Format Chinese Yuan (RMB) currency."""
    if val is None or val != val:
        return "¥0.00"
    if compact and abs(val) >= 10_000:
        return f"¥{val / 1000:.1f}k"
    return f"¥{val:,.2f}"

def format_qty(val: float) -> str:
    """Format product quantities cleanly."""
    if val is None or val != val:
        return "0"
    if val >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    elif val >= 1_000:
        return f"{val:,.0f}"
    return f"{val:,.0f}"
