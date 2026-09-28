"""
DayBook Analytics — Excel Data Parser
Normalizes hierarchical Tally Day Book exports into clean relational DataFrames.
"""

import pandas as pd
import datetime
import re
from collections import Counter
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
      1. vouchers_df: Header-level and compound voucher records with dedicated narrations
      2. line_items_df: Item-level transaction lines
    """
    df = pd.read_excel(filepath_or_buffer, sheet_name=0, header=None)

    vouchers: List[Dict[str, Any]] = []
    line_items: List[Dict[str, Any]] = []

    current_voucher: Optional[Dict[str, Any]] = None
    current_sub_entries: List[Dict[str, Any]] = []

    def finalize_voucher(v_obj: Optional[Dict[str, Any]], sub_entries: List[Dict[str, Any]]):
        if not v_obj:
            return

        v_cat = v_obj['voucher_category']

        if v_cat in ('Receipt', 'Payment') and sub_entries:
            # Handle compound financial vouchers (multi-party receipts/payments)
            party_counts = Counter()
            for entry in sub_entries:
                p_name = entry['party_name']
                count = party_counts[p_name]
                party_counts[p_name] += 1

                # If same party appears multiple times in the same voucher, append index (e.g. 28, 28-2)
                v_num_str = v_obj['voucher_no'] if count == 0 else f"{v_obj['voucher_no']}-{count + 1}"
                narr = ' | '.join(entry['narration_parts']) if entry['narration_parts'] else None

                vouchers.append({
                    'date': v_obj['date'],
                    'miti': v_obj['miti'],
                    'party_name': p_name,
                    'voucher_type': v_obj['voucher_type'],
                    'voucher_category': v_cat,
                    'voucher_no': str(v_num_str),
                    'debit_amount': entry['debit_amount'],
                    'credit_amount': entry['credit_amount'],
                    'narration': narr,
                    'month': v_obj['date'].strftime('%Y-%m'),
                })
        else:
            # Sales / Purchase / Other vouchers (standard 1 header -> many products)
            narr = ' | '.join(v_obj['narration_parts']) if v_obj['narration_parts'] else None
            vouchers.append({
                'date': v_obj['date'],
                'miti': v_obj['miti'],
                'party_name': v_obj['party_name'],
                'voucher_type': v_obj['voucher_type'],
                'voucher_category': v_cat,
                'voucher_no': str(v_obj['voucher_no']),
                'debit_amount': v_obj['debit_amount'],
                'credit_amount': v_obj['credit_amount'],
                'narration': narr,
                'month': v_obj['date'].strftime('%Y-%m'),
            })

            # Line items
            products = aggregate_duplicate_lines(v_obj['products'])
            for p in products:
                line_items.append({
                    'date': v_obj['date'],
                    'party_name': v_obj['party_name'],
                    'voucher_type': v_obj['voucher_type'],
                    'voucher_category': v_cat,
                    'voucher_no': str(v_obj['voucher_no']),
                    'product_name': p['product_name'],
                    'quantity': p['quantity'],
                    'rate': p['rate'],
                    'amount': p['amount'],
                    'month': v_obj['date'].strftime('%Y-%m'),
                    'product_group': assign_product_group(p['product_name']),
                })

    for i in range(len(df)):
        row = df.iloc[i]
        col0 = row[0]
        col7 = row[7]

        # Check if this row is a voucher header:
        # Col 0 must be date/datetime, and Col 7 must be a non-null voucher type string
        is_date = isinstance(col0, (datetime.datetime, datetime.date, pd.Timestamp))
        is_vch = pd.notna(col7) and safe_str(col7) not in ('', 'Vch Type')

        if is_date and is_vch:
            finalize_voucher(current_voucher, current_sub_entries)

            v_date = col0.date() if hasattr(col0, 'date') else col0
            v_type = safe_str(col7)
            v_cat = classify_voucher_type(v_type)
            v_no = safe_str(row[8], default='0')
            party = safe_str(row[2], default='Unknown')
            debit = safe_float(row[9])
            credit = safe_float(row[10])

            current_voucher = {
                'date': v_date,
                'miti': safe_str(row[1]),
                'party_name': party,
                'voucher_type': v_type,
                'voucher_category': v_cat,
                'voucher_no': v_no,
                'debit_amount': debit,
                'credit_amount': credit,
                'narration_parts': [],
                'products': [],
            }

            if v_cat in ('Receipt', 'Payment'):
                # Initialize first sub-entry for the header party
                current_sub_entries = [{
                    'party_name': party,
                    'debit_amount': debit,
                    'credit_amount': credit,
                    'narration_parts': []
                }]
            else:
                current_sub_entries = []

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

        v_cat = current_voucher['voucher_category']

        if v_cat in ('Receipt', 'Payment'):
            str2 = safe_str(val2)

            # Check if this row is another party line:
            # col2 has party name (not Cash, On Account, A/c) and col3 (debit) or col4 (credit) has amount
            if str2 and str2 not in SKIP_NAMES and not str2.startswith('On Account') and 'A/c' not in str2 and (pd.notna(val3) or pd.notna(val4)):
                p_deb = safe_float(val3) if v_cat == 'Payment' else 0.0
                p_crd = safe_float(val4) if v_cat == 'Receipt' else (safe_float(val3) if v_cat == 'Receipt' else 0.0)

                current_sub_entries.append({
                    'party_name': str2,
                    'debit_amount': p_deb,
                    'credit_amount': p_crd,
                    'narration_parts': []
                })
                continue

            # Narration row:
            # col1 has text, col3 and col4 are empty/NaN
            if pd.notna(val1) and pd.isna(val4) and pd.isna(val3) and pd.isna(col0):
                str1 = safe_str(val1)
                if str1 and str1 not in SKIP_NAMES and not str1.startswith('On Account'):
                    if current_sub_entries:
                        current_sub_entries[-1]['narration_parts'].append(str1)
                    else:
                        current_voucher['narration_parts'].append(str1)
            continue

        else:
            # Standard Sales / Purchase / Other voucher processing
            if pd.notna(val1) and pd.notna(val4):
                str1 = safe_str(val1)
                if str1 not in SKIP_NAMES and not str1.startswith('On Account'):
                    amt = safe_float(val4)
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

            str2 = safe_str(val2)
            if 'A/c' in str2:
                continue

            if pd.notna(val1) and pd.isna(val4) and pd.isna(col0):
                str1 = safe_str(val1)
                if str1 and str1 not in SKIP_NAMES and not str1.startswith('On Account'):
                    current_voucher['narration_parts'].append(str1)

    finalize_voucher(current_voucher, current_sub_entries)

    vouchers_df = pd.DataFrame(vouchers)
    line_items_df = pd.DataFrame(line_items)

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
