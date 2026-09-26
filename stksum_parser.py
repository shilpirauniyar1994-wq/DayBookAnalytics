"""
DayBook Analytics — Stock Summary Parser & Category Mapper
Extracts opening stock balances and product categories from Tally StkSum.xlsx exports.
Normalizes products into the 6 official business categories:
  - Big Toys
  - Birthday Items
  - Factory Item
  - Fancy Toys
  - General
  - Indian Item
"""

import os
import openpyxl
import pandas as pd
import datetime
from typing import Dict, List, Tuple, Any, Optional

DATA_DIR = "data"
OPENING_STOCK_FILE = os.path.join(DATA_DIR, "opening_stock.csv")
PRODUCT_GROUPS_FILE = os.path.join(DATA_DIR, "product_groups.csv")

OFFICIAL_CATEGORIES = [
    'Big Toys',
    'Birthday Items',
    'Factory Item',
    'Fancy Toys',
    'General',
    'Indian Item'
]

# Normalization mapping for category header variations
CATEGORY_HEADER_MAP = {
    'big toys': 'Big Toys',
    'big toy': 'Big Toys',
    'birthday item': 'Birthday Items',
    'birthday items': 'Birthday Items',
    'factory item': 'Factory Item',
    'factory items': 'Factory Item',
    'fancy toys': 'Fancy Toys',
    'fancy toy': 'Fancy Toys',
    'general': 'General',
    'indian item': 'Indian Item',
    'indian items': 'Indian Item',
}

# In-memory mapping cache
_cached_product_group_map: Optional[Dict[str, str]] = None


def normalize_category_name(raw_name: str) -> Optional[str]:
    """Normalize raw string to one of the 6 official categories, or None if not a category."""
    if not raw_name:
        return None
    clean = str(raw_name).strip().lower()
    return CATEGORY_HEADER_MAP.get(clean)


def parse_stock_summary(
    filepath_or_buffer: Any,
    as_of_date: str = '2025-06-15'
) -> Tuple[pd.DataFrame, Dict[str, Any], Dict[str, Any]]:
    """
    Parse a Tally Stock Summary Excel file into a clean DataFrame.

    Returns:
      1. df: DataFrame with columns:
         ['product_name', 'product_group', 'opening_qty', 'opening_rate', 'opening_value',
          'closing_qty', 'closing_rate', 'closing_value', 'as_of_date']
      2. category_summary: Dict mapping category -> {op_value, cl_value, product_count}
      3. metadata: Dict with date_range, total_products, total_opening_val, total_closing_val
    """
    wb = openpyxl.load_workbook(filepath_or_buffer, data_only=True)
    ws = wb.active

    # Extract date range if present in top rows
    date_range_str = "15-Jun-2025 to 24-Sep-2026"
    for r in range(1, 6):
        val = ws.cell(r, 1).value or ws.cell(r, 2).value
        if val and 'to' in str(val).lower() and ('2025' in str(val) or '2026' in str(val) or '208' in str(val)):
            date_range_str = str(val).strip()
            break

    # Pass 1: Find category header rows and Grand Total
    # In Tally StkSum exports, category headers have text in Col 1, Col 2 & 3 are None, Col 4 has total value
    category_rows: Dict[int, str] = {}
    grand_total_row = None

    for r in range(1, ws.max_row + 1):
        c1 = ws.cell(r, 1).value
        if not c1:
            continue
        c1_str = str(c1).strip()
        if c1_str.lower() == 'grand total':
            grand_total_row = r
            continue

        norm_cat = normalize_category_name(c1_str)
        if norm_cat:
            # Check if it's a category header (Col 2 and Col 3 are None)
            c2 = ws.cell(r, 2).value
            c3 = ws.cell(r, 3).value
            if c2 is None and c3 is None:
                category_rows[r] = norm_cat

    # Pass 2: Extract items under each category
    records: List[Dict[str, Any]] = []
    category_summary: Dict[str, Dict[str, Any]] = {
        cat: {'opening_val': 0.0, 'closing_val': 0.0, 'product_count': 0, 'items_with_stock': 0}
        for cat in OFFICIAL_CATEGORIES
    }

    current_group = None

    for r in range(1, ws.max_row + 1):
        if grand_total_row and r >= grand_total_row:
            break

        if r in category_rows:
            current_group = category_rows[r]
            # Capture header totals if present
            hdr_op_val = float(ws.cell(r, 4).value or 0.0)
            hdr_cl_val = float(ws.cell(r, 7).value or 0.0)
            category_summary[current_group]['header_op_val'] = hdr_op_val
            category_summary[current_group]['header_cl_val'] = hdr_cl_val
            continue

        if not current_group:
            continue

        c1 = ws.cell(r, 1).value
        if not c1:
            continue
        prod_name = str(c1).strip()
        if prod_name.lower() in ('particulars', 'demo khelauna', 'grand total', 'nan', ''):
            continue

        op_qty = float(ws.cell(r, 2).value or 0.0)
        op_rate = float(ws.cell(r, 3).value or 0.0)
        op_val = float(ws.cell(r, 4).value or 0.0)
        cl_qty = float(ws.cell(r, 5).value or 0.0)
        cl_rate = float(ws.cell(r, 6).value or 0.0)
        cl_val = float(ws.cell(r, 7).value or 0.0)

        # Update stats
        category_summary[current_group]['product_count'] += 1
        category_summary[current_group]['opening_val'] += op_val
        category_summary[current_group]['closing_val'] += cl_val
        if abs(op_qty) > 0 or abs(op_val) > 0:
            category_summary[current_group]['items_with_stock'] += 1

        records.append({
            'product_name': prod_name,
            'product_group': current_group,
            'opening_qty': op_qty,
            'opening_rate': op_rate,
            'opening_value': op_val,
            'closing_qty': cl_qty,
            'closing_rate': cl_rate,
            'closing_value': cl_val,
            'as_of_date': as_of_date
        })

    df = pd.DataFrame(records)

    metadata = {
        'date_range': date_range_str,
        'as_of_date': as_of_date,
        'total_products': len(df),
        'items_with_opening': len(df[df['opening_qty'] != 0]),
        'total_opening_value': round(df['opening_value'].sum(), 2) if not df.empty else 0.0,
        'total_closing_value': round(df['closing_value'].sum(), 2) if not df.empty else 0.0,
    }

    return df, category_summary, metadata


def save_stock_summary_data(df: pd.DataFrame) -> Tuple[int, int]:
    """
    Save parsed stock summary data to local CSV and sync to Supabase if configured.
    Returns: (opening_stock_count, product_group_count)
    """
    global _cached_product_group_map
    if df.empty:
        return 0, 0

    os.makedirs(DATA_DIR, exist_ok=True)
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. Save local opening stock CSV
    op_cols = ['product_name', 'product_group', 'opening_qty', 'opening_rate', 'opening_value',
               'closing_qty', 'closing_rate', 'closing_value', 'as_of_date']
    save_df = df[op_cols].copy()
    save_df['updated_at'] = now_str
    save_df.to_csv(OPENING_STOCK_FILE, index=False, encoding='utf-8')

    # 2. Save local product groups mapping CSV
    pg_df = df[['product_name', 'product_group']].drop_duplicates(subset=['product_name']).copy()
    pg_df['updated_at'] = now_str
    pg_df.to_csv(PRODUCT_GROUPS_FILE, index=False, encoding='utf-8')

    # Invalidate in-memory cache
    _cached_product_group_map = None

    # 3. Synchronize to Supabase if client is available
    try:
        from db import get_client, is_supabase_configured
        client = get_client()
        if client is not None and is_supabase_configured():
            # A. Sync opening_stock table (columns: product_name, opening_qty, unit, as_of_date)
            # Note: PostgreSQL identity column 'id' must not be included
            op_records = []
            for _, r in df.iterrows():
                op_records.append({
                    'product_name': str(r['product_name']).strip(),
                    'opening_qty': float(r['opening_qty']),
                    'unit': 'PCS',
                    'as_of_date': str(r['as_of_date'])
                })
            for i in range(0, len(op_records), 100):
                batch = op_records[i:i+100]
                client.table('opening_stock').upsert(batch, on_conflict='product_name').execute()

            # B. Sync product_group_mappings table (columns: product_name, product_group)
            pg_records = []
            for _, r in pg_df.iterrows():
                pg_records.append({
                    'product_name': str(r['product_name']).strip(),
                    'product_group': str(r['product_group']).strip()
                })
            for i in range(0, len(pg_records), 100):
                batch = pg_records[i:i+100]
                client.table('product_group_mappings').upsert(batch, on_conflict='product_name').execute()
    except Exception as e:
        print(f"[stksum_parser] Supabase sync warning: {e}")

    return len(save_df), len(pg_df)


def get_product_group_mapping_dict() -> Dict[str, str]:
    """
    Get dictionary mapping lowercased product_name -> official product category.
    Loaded from memory cache, local CSV, or StkSum.xlsx.
    """
    global _cached_product_group_map
    if _cached_product_group_map is not None:
        return _cached_product_group_map

    mapping: Dict[str, str] = {}

    # Check local CSV first
    if os.path.exists(PRODUCT_GROUPS_FILE):
        try:
            df = pd.read_csv(PRODUCT_GROUPS_FILE, encoding='utf-8')
            for _, r in df.iterrows():
                p = str(r['product_name']).strip().lower()
                g = str(r['product_group']).strip()
                if p and g:
                    mapping[p] = g
            if mapping:
                _cached_product_group_map = mapping
                return _cached_product_group_map
        except Exception:
            pass

    # Check if StkSum.xlsx is in workspace root
    if os.path.exists('StkSum.xlsx'):
        try:
            df, _, _ = parse_stock_summary('StkSum.xlsx')
            save_stock_summary_data(df)
            for _, r in df.iterrows():
                p = str(r['product_name']).strip().lower()
                g = str(r['product_group']).strip()
                if p and g:
                    mapping[p] = g
            _cached_product_group_map = mapping
            return _cached_product_group_map
        except Exception:
            pass

    _cached_product_group_map = mapping
    return mapping


def infer_product_group(product_name: Any, custom_map: Optional[Dict[str, str]] = None) -> str:
    """
    Classify any product into one of the 6 official business categories:
      - Big Toys
      - Birthday Items
      - Factory Item
      - Fancy Toys
      - General
      - Indian Item

    Step 1: Exact match against official mappings from StkSum.xlsx
    Step 2: Intelligent keyword fallback for newly introduced products
    Step 3: Default to 'General'
    """
    if not product_name or pd.isna(product_name):
        return 'General'

    p_clean = str(product_name).strip()
    p_lower = p_clean.lower()

    # Step 1: Exact / Case-insensitive match from StkSum mapping
    mapping = custom_map if custom_map is not None else get_product_group_mapping_dict()
    if p_lower in mapping:
        return mapping[p_lower]

    # Step 2: Intelligent heuristic fallback for new items introduced in later vouchers
    # Factory Item indicators
    if any(k in p_lower for k in ['factory item', '(factory', 'factory']):
        return 'Factory Item'

    # Indian Item indicators
    if any(k in p_lower for k in ['indian item', 'indian', 'ind item', 'ind ']):
        return 'Indian Item'

    # Birthday & Party Item indicators
    if any(k in p_lower for k in ['birthday', 'ballon', 'balloon', 'sashi', 'candle', 'crown', 'party', 'topper', 'banner', 'cap']):
        return 'Birthday Items'

    # Big Toys indicators (vehicles, ride-ons, battery cars, scooters, bikes)
    if any(k in p_lower for k in ['big toy', 'jeep', 'tricycle', 'push car', 'baby bed', 'rider', 'slide car',
                                  'scooty', 'scooter', 'bike', 'car 12v', '12v', 'v-8', 'tesla', 'vespa']):
        return 'Big Toys'

    # Fancy Toys indicators (dolls, beauty sets, drones, robotics, RC)
    if any(k in p_lower for k in ['doll', 'beauty', 'makeup', 'r/c', 'rc ', 'drone', 'robot', 'fancy']):
        return 'Fancy Toys'

    # Step 3: Default category
    return 'General'
