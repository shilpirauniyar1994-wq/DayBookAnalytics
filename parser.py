"""
DayBook Analytics — Excel Data Parser
Normalizes hierarchical Tally Day Book exports into clean relational DataFrames.
"""

import pandas as pd
import datetime
import re
from typing import Tuple, List, Dict, Any, Optional

VOUCHER_CATEGORY_MAP = {
    'Head Office Sales': 'Sales',
    'Bafal Sales': 'Sales',
    'Pasal': 'Sales',
    'Sales': 'Sales',
    'Purchase': 'Purchase',
    'Payment': 'Payment',
    'Receipt': 'Receipt',
    'Credit Note': 'Credit Note',
    'Stock Journal': 'Stock Transfer',
}

SKIP_NAMES = {
    'On Account', 'NaN', 'nan', 'Cheque/DD', 'Claim', '',
    'Head Office Sales A/c', 'Purchase A/c', 'Bafal Sales A/c'
}

# Official 6 business categories from Tally Stock Summary (StkSum.xlsx)
OFFICIAL_PRODUCT_GROUPS = [
    'Big Toys',
    'Birthday Items',
    'Factory Item',
    'Fancy Toys',
    'General',
    'Indian Item'
]

def classify_voucher_type(vtype: Any) -> str:
    """Classify raw voucher type string into standard accounting category."""
    if pd.isna(vtype):
        return 'Other'
    v_clean = str(vtype).strip()
    return VOUCHER_CATEGORY_MAP.get(v_clean, 'Other')

def assign_product_group(product_name: str) -> str:
    """Classify product into one of the 6 official business categories."""
    try:
        from stksum_parser import infer_product_group
        return infer_product_group(product_name)
    except Exception:
        return 'General'

def safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert any numeric/string value to float."""
    if pd.isna(val):
        return default
    try:
        # Strip currency symbols, commas or whitespace
        s = re.sub(r'[^\d.-]', '', str(val).strip())
        return float(s) if s else default
    except (ValueError, TypeError):
        return default

def safe_str(val: Any, default: str = '') -> str:
    """Safely convert value to stripped string."""
    if pd.isna(val):
        return default
    s = str(val).strip()
    return '' if s.lower() == 'nan' else s

def extract_qty(val: Any) -> float:
    """Extract numeric quantity even if string contains units like '108.00 pcs'."""
    if pd.isna(val):
        return 0.0
    s = str(val).strip()
    # Match initial numeric part
    match = re.search(r'[-+]?\d*\.?\d+', s)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return 0.0
    return 0.0

def aggregate_duplicate_lines(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge multiple occurrences of the same product within a single voucher.
    Sums quantity and amount; recalculates weighted average rate.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for p in products:
        key = p['product_name']
        if key in merged:
            merged[key]['quantity'] += p['quantity']
            merged[key]['amount'] += p['amount']
            # Recalculate rate if quantity > 0
            if merged[key]['quantity'] > 0:
                merged[key]['rate'] = merged[key]['amount'] / merged[key]['quantity']
        else:
            merged[key] = p.copy()
    return list(merged.values())

def parse_daybook(filepath_or_buffer: Any) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Parse a Tally Day Book Excel file into two DataFrames:
      1. vouchers_df: Header-level voucher records
      2. line_items_df: Item-level transaction lines
    """
    df = pd.read_excel(filepath_or_buffer, sheet_name=0, header=None)

    vouchers: List[Dict[str, Any]] = []
    current_voucher: Optional[Dict[str, Any]] = None

    for i in range(len(df)):
        row = df.iloc[i]
        col0 = row[0]
        col7 = row[7]

        # Check if this row is a voucher header:
        # Col 0 must be date/datetime, and Col 7 must be a non-null voucher type string
        is_date = isinstance(col0, (datetime.datetime, datetime.date, pd.Timestamp))
        is_vch = pd.notna(col7) and safe_str(col7) not in ('', 'Vch Type')

        if is_date and is_vch:
            if current_voucher:
                vouchers.append(current_voucher)

            v_date = col0.date() if hasattr(col0, 'date') else col0
            v_type = safe_str(col7)
            v_no = safe_str(row[8], default='0')
            party = safe_str(row[2], default='Unknown')

            current_voucher = {
                'date': v_date,
                'miti': safe_str(row[1]),
                'party_name': party,
                'voucher_type': v_type,
                'voucher_category': classify_voucher_type(v_type),
                'voucher_no': v_no,
                'debit_amount': safe_float(row[9]),
                'credit_amount': safe_float(row[10]),
                'narration_parts': [],
                'products': [],
            }
            continue

        if current_voucher is None:
            continue

        # Check if the row contains "Day Book Total :" to end voucher parsing
        if pd.notna(col0) and 'Day Book Total' in str(col0):
            break

        val1 = row[1]
        val2 = row[2]
        val3 = row[3]
        val4 = row[4]

        # 1. Product line detection:
        # Col 1 is product name, Col 4 has a numeric amount, Col 2 has quantity
        if pd.notna(val1) and pd.notna(val4):
            str1 = safe_str(val1)
            # Make sure it's not a known non-product row like "On Account" or "Cheque/DD"
            if str1 not in SKIP_NAMES and not str1.startswith('On Account'):
                amt = safe_float(val4)
                # If amount > 0 or qty > 0, it's a product line
                qty = extract_qty(val2)
                rate = safe_float(val3)
                if amt != 0.0 or qty != 0.0:
                    current_voucher['products'].append({
                        'product_name': str1,
                        'quantity': qty,
                        'rate': rate,
                        'amount': amt,
                    })
                    continue

        # 2. Account lines (e.g. 'Purchase A/c' with amount in col 2 or 3)
        str2 = safe_str(val2)
        if 'A/c' in str2:
            continue

        # 3. Narration detection:
        # Col 1 has text, Col 4 is empty/NaN, not a product line
        if pd.notna(val1) and pd.isna(val4) and pd.isna(col0):
            str1 = safe_str(val1)
            if str1 and str1 not in SKIP_NAMES and not str1.startswith('On Account'):
                current_voucher['narration_parts'].append(str1)

    # Append final voucher
    if current_voucher:
        vouchers.append(current_voucher)

    # Build vouchers DataFrame
    v_records = []
    for v in vouchers:
        v_records.append({
            'date': v['date'],
            'miti': v['miti'],
            'party_name': v['party_name'],
            'voucher_type': v['voucher_type'],
            'voucher_category': v['voucher_category'],
            'voucher_no': str(v['voucher_no']),
            'debit_amount': v['debit_amount'],
            'credit_amount': v['credit_amount'],
            'narration': ' | '.join(v['narration_parts']) if v['narration_parts'] else None,
            'month': v['date'].strftime('%Y-%m'),
        })
    vouchers_df = pd.DataFrame(v_records)

    # Build line items DataFrame
    li_records = []
    for v in vouchers:
        products = aggregate_duplicate_lines(v['products'])
        for p in products:
            li_records.append({
                'date': v['date'],
                'party_name': v['party_name'],
                'voucher_type': v['voucher_type'],
                'voucher_category': v['voucher_category'],
                'voucher_no': str(v['voucher_no']),
                'product_name': p['product_name'],
                'quantity': p['quantity'],
                'rate': p['rate'],
                'amount': p['amount'],
                'month': v['date'].strftime('%Y-%m'),
                'product_group': assign_product_group(p['product_name']),
            })
    line_items_df = pd.DataFrame(li_records)

    return vouchers_df, line_items_df

if __name__ == '__main__':
    import sys
    test_file = sys.argv[1] if len(sys.argv) > 1 else 'DayBook.xlsx'
    print(f"Testing parser on {test_file}...")
    v_df, li_df = parse_daybook(test_file)
    print(f"Vouchers parsed: {len(v_df)}")
    print(f"Line items parsed: {len(li_df)}")
    print(f"Unique products: {li_df['product_name'].nunique()}")
    print("Voucher categories count:")
    print(v_df['voucher_category'].value_counts().to_string())
    print("\nProduct groups count:")
    print(li_df['product_group'].value_counts().to_string())
