"""
DayBook Analytics — Database & Query Abstraction Layer
Seamlessly supports both Supabase PostgreSQL and local cached Excel mode.
"""

import os
import pandas as pd
import datetime
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv

load_dotenv()

_supabase_client = None
_local_cache: Dict[str, Any] = {}

def get_client():
    """Initialize and return Supabase client if configured in .env."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    url = os.getenv('SUPABASE_URL', '').strip()
    key = os.getenv('SUPABASE_KEY', '').strip()

    if url and key and 'your-project' not in url:
        import re
        url = re.sub(r'/rest/v1/?$', '', url).rstrip('/')
        try:
            from supabase import create_client
            _supabase_client = create_client(url, key)
            return _supabase_client
        except Exception:
            return None
    return None

_supabase_verified = None

def is_supabase_configured() -> bool:
    """Check if valid Supabase connection is active (cached after first check)."""
    global _supabase_verified
    if _supabase_verified is not None:
        return _supabase_verified
    client = get_client()
    if client is None:
        _supabase_verified = False
        return False
    try:
        # Quick ping query
        res = client.table('lead_time_config').select('id').limit(1).execute()
        _supabase_verified = True
        return True
    except Exception:
        _supabase_verified = False
        return False

# ---------------------------------------------------------------------------
# LOCAL DATA FALLBACK (When Supabase is not yet configured or for fast dev)
# ---------------------------------------------------------------------------

DATA_DIR = "data"
VOUCHERS_CACHE_FILE = os.path.join(DATA_DIR, "vouchers_cache.parquet")
LINE_ITEMS_CACHE_FILE = os.path.join(DATA_DIR, "line_items_cache.parquet")

def load_local_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Parse local DayBook files with fast Parquet disk caching."""
    global _local_cache
    if 'vouchers' in _local_cache and 'line_items' in _local_cache:
        return _local_cache['vouchers'], _local_cache['line_items']

    # 1. Discover all daybook files and calculate latest mtime
    files = []
    daybook_dir = "daybooks"
    if os.path.exists(daybook_dir):
        for f in sorted(os.listdir(daybook_dir)):
            if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith(('~', '.')):
                files.append(os.path.join(daybook_dir, f))

    for f in ['DayBook.xlsx', 'DayBook6.xlsx']:
        if os.path.exists(f) and f not in files:
            files.append(f)

    latest_file_mtime = 0.0
    for f in files:
        if os.path.exists(f):
            latest_file_mtime = max(latest_file_mtime, os.path.getmtime(f))

    # 2. Check if valid Parquet cache exists on disk
    if (os.path.exists(VOUCHERS_CACHE_FILE) and os.path.exists(LINE_ITEMS_CACHE_FILE) and
        os.path.getmtime(VOUCHERS_CACHE_FILE) >= latest_file_mtime and
        os.path.getmtime(LINE_ITEMS_CACHE_FILE) >= latest_file_mtime):
        try:
            v_df = pd.read_parquet(VOUCHERS_CACHE_FILE)
            li_df = pd.read_parquet(LINE_ITEMS_CACHE_FILE)
            _local_cache['vouchers'] = v_df
            _local_cache['line_items'] = li_df
            return v_df, li_df
        except Exception:
            pass

    # 3. Cache miss or stale: parse all daybook files
    from parser import parse_daybook
    from stksum_parser import infer_product_group

    v_dfs = []
    li_dfs = []

    for f in files:
        if os.path.exists(f):
            v, li = parse_daybook(f)
            v_dfs.append(v)
            li_dfs.append(li)

    if not v_dfs:
        v_df = pd.DataFrame()
        li_df = pd.DataFrame()
    else:
        v_df = pd.concat(v_dfs, ignore_index=True).drop_duplicates(
            subset=['date', 'voucher_type', 'voucher_no', 'party_name', 'debit_amount', 'credit_amount']
        )
        li_df = pd.concat(li_dfs, ignore_index=True).drop_duplicates(
            subset=['date', 'voucher_type', 'voucher_no', 'party_name', 'product_name', 'quantity', 'rate']
        )

        # Ensure product_group is classified using official 6 categories
        if not li_df.empty and 'product_name' in li_df.columns:
            li_df['product_group'] = li_df['product_name'].apply(infer_product_group)

    # 4. Save to fast Parquet cache on disk
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if not v_df.empty:
            v_df.to_parquet(VOUCHERS_CACHE_FILE, index=False)
        if not li_df.empty:
            li_df.to_parquet(LINE_ITEMS_CACHE_FILE, index=False)
    except Exception as e:
        print(f"[db] Warning writing parquet cache: {e}")

    _local_cache['vouchers'] = v_df
    _local_cache['line_items'] = li_df
    return v_df, li_df

def refresh_local_cache():
    """Clear memory cache and disk parquet cache so daybooks are re-parsed."""
    global _local_cache
    _local_cache.clear()
    for f in [VOUCHERS_CACHE_FILE, LINE_ITEMS_CACHE_FILE]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

# ---------------------------------------------------------------------------
# QUERY FUNCTIONS (Unified across Supabase and Local)
# ---------------------------------------------------------------------------

def fetch_all_from_supabase(table_name: str, order_col: str = 'id', page_size: int = 1000) -> pd.DataFrame:
    """Fetch all rows from a Supabase table with automatic pagination beyond PostgREST's 1,000-row limit."""
    client = get_client()
    if client is None or not is_supabase_configured():
        return pd.DataFrame()
    all_data = []
    offset = 0
    while True:
        try:
            res = client.table(table_name).select('*').order(order_col).range(offset, offset + page_size - 1).execute()
            if not res.data:
                break
            all_data.extend(res.data)
            if len(res.data) < page_size:
                break
            offset += page_size
        except Exception as e:
            print(f"[db] Error paginating {table_name} at offset {offset}: {e}")
            break
    return pd.DataFrame(all_data) if all_data else pd.DataFrame()

def get_vouchers_df() -> pd.DataFrame:
    """Retrieve all vouchers across full date history (13,500+ records)."""
    v_df, _ = load_local_data()
    if not v_df.empty and len(v_df) > 1000:
        return v_df.copy()
    
    # Cloud fallback if local cache is absent or incomplete
    cloud_df = fetch_all_from_supabase('vouchers', order_col='date')
    if not cloud_df.empty:
        return cloud_df
    return v_df.copy()

def get_line_items_df() -> pd.DataFrame:
    """Retrieve all product line items across full history (64,000+ items)."""
    _, li_df = load_local_data()
    if not li_df.empty and len(li_df) > 1000:
        return li_df.copy()

    # Cloud fallback if local cache is absent or incomplete
    cloud_df = fetch_all_from_supabase('line_items', order_col='date')
    if not cloud_df.empty:
        return cloud_df
    return li_df.copy()

def get_monthly_summary() -> pd.DataFrame:
    """
    Get aggregated monthly summary of vouchers by category.
    """
    v_df = get_vouchers_df()
    if v_df.empty:
        return pd.DataFrame()

    summary = v_df.groupby(['month', 'voucher_category']).agg(
        total_debit=('debit_amount', 'sum'),
        total_credit=('credit_amount', 'sum'),
        count=('voucher_no', 'count')
    ).reset_index()

    return summary.sort_values('month')

def get_party_ledger(party_name: Optional[str] = None) -> pd.DataFrame:
    """
    Get transaction ledger for a party (or all parties) with running balance.
    """
    df = None
    if is_supabase_configured() and party_name and party_name != 'All':
        client = get_client()
        if client:
            try:
                res = client.table('vouchers').select('*').eq('party_name', party_name).order('date').execute()
                if res.data:
                    df = pd.DataFrame(res.data)
            except Exception as e:
                print(f"[db] Supabase direct ledger query fallback: {e}")

    if df is None:
        v_df = get_vouchers_df()
        if v_df.empty:
            return pd.DataFrame()

        if party_name and party_name != 'All':
            df = v_df[v_df['party_name'] == party_name].copy()
        else:
            df = v_df.copy()

    if df.empty:
        return df

    df = df.copy()

    def to_date_safe(val):
        if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
            return val
        if hasattr(val, 'date'):
            return val.date()
        if isinstance(val, str) and len(val) >= 10:
            try:
                return datetime.date.fromisoformat(val[:10])
            except Exception:
                pass
        return val

    df['date'] = df['date'].apply(to_date_safe)
    df = df.sort_values(['date', 'voucher_no']).reset_index(drop=True)

    df['debit_amount'] = pd.to_numeric(df['debit_amount'], errors='coerce').fillna(0.0)
    df['credit_amount'] = pd.to_numeric(df['credit_amount'], errors='coerce').fillna(0.0)

    # Calculate running balance
    df['running_balance'] = (df['debit_amount'] - df['credit_amount']).cumsum()
    return df

def get_all_parties() -> List[str]:
    """Get sorted list of distinct party names."""
    v_df = get_vouchers_df()
    if v_df.empty:
        return []
    parties = v_df['party_name'].dropna().unique().tolist()
    return sorted([p for p in parties if p and p != 'Unknown'])

def get_product_analytics(group: Optional[str] = None) -> pd.DataFrame:
    """
    Aggregate sales metrics per product.
    """
    li_df = get_line_items_df()
    if li_df.empty:
        return pd.DataFrame()

    sales = li_df[li_df['voucher_category'] == 'Sales'].copy()

    if group and group != 'All':
        sales = sales[sales['product_group'] == group]

    if sales.empty:
        return pd.DataFrame()

    agg = sales.groupby(['product_name', 'product_group']).agg(
        total_qty=('quantity', 'sum'),
        total_revenue=('amount', 'sum'),
        avg_rate=('rate', 'mean'),
        transactions=('product_name', 'count')
    ).reset_index()

    agg.loc[:, 'avg_rate'] = agg['avg_rate'].round(2)
    agg.loc[:, 'total_revenue'] = agg['total_revenue'].round(2)
    return agg.sort_values('total_revenue', ascending=False)

def get_product_groups() -> List[str]:
    """Get list of 6 official product groups."""
    from stksum_parser import OFFICIAL_CATEGORIES
    return list(OFFICIAL_CATEGORIES)

def get_opening_stock_df() -> pd.DataFrame:
    """Fetch opening stock records from Supabase or local CSV."""
    from stksum_parser import OPENING_STOCK_FILE, parse_stock_summary, save_stock_summary_data
    if os.path.exists(OPENING_STOCK_FILE):
        try:
            return pd.read_csv(OPENING_STOCK_FILE, encoding='utf-8')
        except Exception:
            pass

    client = get_client()
    if client is not None and is_supabase_configured():
        df = fetch_all_from_supabase('opening_stock', order_col='id')
        if not df.empty:
            return df

    if os.path.exists('StkSum.xlsx'):
        try:
            df, _, _ = parse_stock_summary('StkSum.xlsx')
            save_stock_summary_data(df)
            return df
        except Exception:
            pass

    cols = ['product_name', 'product_group', 'opening_qty', 'opening_rate', 'opening_value',
            'closing_qty', 'closing_rate', 'closing_value', 'as_of_date']
    return pd.DataFrame(columns=cols)

def get_product_group_mappings() -> pd.DataFrame:
    """Fetch product category mappings from Supabase or local CSV."""
    from stksum_parser import PRODUCT_GROUPS_FILE, get_product_group_mapping_dict
    if os.path.exists(PRODUCT_GROUPS_FILE):
        try:
            return pd.read_csv(PRODUCT_GROUPS_FILE, encoding='utf-8')
        except Exception:
            pass

    client = get_client()
    if client is not None and is_supabase_configured():
        df = fetch_all_from_supabase('product_group_mappings', order_col='id')
        if not df.empty:
            return df

    mapping = get_product_group_mapping_dict()
    records = [{'product_name': p, 'product_group': g} for p, g in mapping.items()]
    return pd.DataFrame(records)

def get_lead_time_config() -> pd.DataFrame:
    """Fetch lead time configuration."""
    client = get_client()
    if client is not None and is_supabase_configured():
        res = client.table('lead_time_config').select('*').execute()
        if res.data:
            return pd.DataFrame(res.data)

    # Return local default
    if 'lead_time_config' not in _local_cache:
        _local_cache['lead_time_config'] = pd.DataFrame([{
            'config_type': 'default',
            'config_key': 'global',
            'lead_time_days': 7,
            'safety_stock_days': 3,
            'min_order_qty': 1,
            'notes': 'Default global lead time'
        }])
    return _local_cache['lead_time_config']

def upsert_lead_time(config_type: str, config_key: str, lead_days: int, safety_days: int, notes: str = ''):
    """Save or update lead time configuration."""
    client = get_client()
    if client is not None and is_supabase_configured():
        client.table('lead_time_config').upsert({
            'config_type': config_type,
            'config_key': config_key,
            'lead_time_days': lead_days,
            'safety_stock_days': safety_days,
            'notes': notes,
            'updated_at': datetime.datetime.now().isoformat()
        }, on_conflict='config_type,config_key').execute()
        return

    # Local fallback
    cfg = get_lead_time_config().copy()
    mask = (cfg['config_type'] == config_type) & (cfg['config_key'] == config_key)
    if mask.any():
        cfg.loc[mask, 'lead_time_days'] = lead_days
        cfg.loc[mask, 'safety_stock_days'] = safety_days
        cfg.loc[mask, 'notes'] = notes
    else:
        new_row = pd.DataFrame([{
            'config_type': config_type,
            'config_key': config_key,
            'lead_time_days': lead_days,
            'safety_stock_days': safety_days,
            'notes': notes
        }])
        cfg = pd.concat([cfg, new_row], ignore_index=True)
    _local_cache['lead_time_config'] = cfg

def get_supplier_products() -> pd.DataFrame:
    """Fetch supplier products mapping."""
    from po_engine import resolve_supplier_alias

    client = get_client()
    if client is not None and is_supabase_configured():
        df = fetch_all_from_supabase('supplier_products', order_col='id')
        if not df.empty:
            df['supplier_name'] = df['supplier_name'].apply(lambda s: resolve_supplier_alias(s))
            # Aggregate to merge duplicate product records across consolidated aliases
            agg = df.groupby(['supplier_name', 'product_name']).agg(
                last_purchase_date=('last_purchase_date', 'max'),
                last_purchase_rate=('last_purchase_rate', 'last'),
                avg_purchase_rate=('avg_purchase_rate', 'mean'),
                total_qty_purchased=('total_qty_purchased', 'sum'),
                purchase_count=('purchase_count', 'sum'),
                is_preferred=('is_preferred', 'any') if 'is_preferred' in df.columns else ('supplier_name', lambda x: False)
            ).reset_index()
            return agg

    # Derive from local purchases
    _, li_df = load_local_data()
    purchases = li_df[li_df['voucher_category'] == 'Purchase'].copy()
    if purchases.empty:
        return pd.DataFrame()

    from po_engine import resolve_supplier_alias
    purchases['supplier_name'] = purchases.apply(
        lambda r: resolve_supplier_alias(r.get('party_name', ''), r.get('voucher_no', '')),
        axis=1
    )

    agg = purchases.groupby(['supplier_name', 'product_name']).agg(
        last_purchase_date=('date', 'max'),
        last_purchase_rate=('rate', 'last'),
        avg_purchase_rate=('rate', 'mean'),
        total_qty_purchased=('quantity', 'sum'),
        purchase_count=('product_name', 'count')
    ).reset_index()

    agg['is_preferred'] = False
    return agg

def get_purchase_orders() -> pd.DataFrame:
    """Retrieve list of past purchase orders."""
    client = get_client()
    if client is not None and is_supabase_configured():
        res = client.table('purchase_orders').select('*').order('created_at', desc=True).execute()
        if res.data:
            return pd.DataFrame(res.data)

    if 'purchase_orders' not in _local_cache:
        _local_cache['purchase_orders'] = pd.DataFrame(columns=[
            'id', 'po_number', 'supplier_name', 'status', 'total_amount', 'total_items', 'notes', 'created_at'
        ])
    return _local_cache['purchase_orders']

def save_draft_po(supplier_name: str, items_df: pd.DataFrame, notes: str = '') -> str:
    """Save newly generated purchase order."""
    now = datetime.datetime.now()
    po_number = f"PO-{now.strftime('%Y%m%d')}-{len(get_purchase_orders()) + 1:04d}"
    total_amount = float(items_df['estimated_amount'].sum()) if 'estimated_amount' in items_df.columns else 0.0
    total_items = len(items_df)

    client = get_client()
    if client is not None and is_supabase_configured():
        po_res = client.table('purchase_orders').insert({
            'po_number': po_number,
            'supplier_name': supplier_name,
            'status': 'Draft',
            'total_amount': total_amount,
            'total_items': total_items,
            'notes': notes,
        }).execute()

        if po_res.data:
            po_id = po_res.data[0]['id']
            lines = []
            for _, r in items_df.iterrows():
                lines.append({
                    'po_id': po_id,
                    'product_name': r['product_name'],
                    'suggested_qty': float(r['suggested_qty']),
                    'ordered_qty': float(r['suggested_qty']),
                    'estimated_rate': float(r.get('estimated_rate', 0.0)),
                    'estimated_amount': float(r.get('estimated_amount', 0.0)),
                    'sales_velocity': float(r.get('daily_velocity', 0.0)),
                    'current_stock': float(r.get('est_stock', 0.0)),
                    'days_of_stock': float(r.get('days_of_stock', 0.0)),
                    'product_group': r.get('product_group', 'Others'),
                })
            client.table('po_line_items').insert(lines).execute()
        return po_number

    # Local fallback
    pos = get_purchase_orders().copy()
    new_po = pd.DataFrame([{
        'id': len(pos) + 1,
        'po_number': po_number,
        'supplier_name': supplier_name,
        'status': 'Draft',
        'total_amount': total_amount,
        'total_items': total_items,
        'notes': notes,
        'created_at': now.strftime('%Y-%m-%d %H:%M')
    }])
    _local_cache['purchase_orders'] = pd.concat([pos, new_po], ignore_index=True)
    return po_number

# ---------------------------------------------------------------------------
# COMMERCIAL INVOICE ITEMS, PRICE HISTORY & RMB MAPPINGS
# ---------------------------------------------------------------------------

INVOICE_ITEMS_FILE = "commercial_invoice_items.csv"
PRICE_HISTORY_FILE = "commercial_price_history.csv"
MAPPINGS_FILE = "product_mappings.csv"

def make_item_key(supplier_name: str, item_no: str, desc: str) -> str:
    """Generate deterministic unique key for a commercial invoice item."""
    s_clean = str(supplier_name or '').strip().lower()
    no_clean = str(item_no or '').strip().lower()
    d_clean = str(desc or '').strip().lower()
    return f"{s_clean}::{no_clean}::{d_clean[:35]}"

def get_commercial_invoice_items() -> pd.DataFrame:
    """
    Fetch all extracted items from commercial invoices stored in database / CSV.
    """
    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            res = client.table('commercial_invoice_items').select('*').order('extracted_at', desc=True).execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception:
            pass

    if os.path.exists(INVOICE_ITEMS_FILE):
        try:
            df = pd.read_csv(INVOICE_ITEMS_FILE, encoding='utf-8')
            # Ensure boolean types
            if 'is_matched' in df.columns:
                df = df.assign(is_matched=df['is_matched'].fillna(False).astype(bool))
            return df
        except Exception:
            pass

    cols = [
        'id', 'item_key', 'supplier_name', 'supplier_item_no', 'supplier_desc',
        'rmb_price', 'pcs_per_ctn', 'invoiced_qty', 'voucher_no', 'landed_multiplier',
        'source_invoice', 'extracted_at',
        'tally_product_name', 'is_matched', 'match_confidence', 'match_type', 'matched_at'
    ]
    return pd.DataFrame(columns=cols)

def get_commercial_price_history() -> pd.DataFrame:
    """Fetch history of RMB price updates across invoices."""
    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            res = client.table('commercial_price_history').select('*').order('updated_at', desc=True).execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception:
            pass

    if os.path.exists(PRICE_HISTORY_FILE):
        try:
            return pd.read_csv(PRICE_HISTORY_FILE, encoding='utf-8')
        except Exception:
            pass

    cols = ['id', 'supplier_name', 'supplier_item_no', 'supplier_desc', 'old_rmb_price', 'new_rmb_price', 'source_invoice', 'updated_at']
    return pd.DataFrame(columns=cols)

def upsert_commercial_invoice_items(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Upsert extracted invoice items into database / local store.
    - If item already exists: updates price and pcs_per_ctn, preserves match if already matched,
      and logs price changes to price history.
    - If new: inserts item.
    - Syncs matched items to active RMB catalog (product_supplier_mappings).
    """
    if not items:
        return {'new_items': 0, 'updated_prices': 0, 'total': 0}

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    existing_df = get_commercial_invoice_items()
    history_df = get_commercial_price_history()

    existing_dict = {}
    if not existing_df.empty:
        for idx, r in existing_df.iterrows():
            k = r.get('item_key') or make_item_key(r.get('supplier_name'), r.get('supplier_item_no'), r.get('supplier_desc'))
            existing_dict[k] = r.to_dict()

    new_count = 0
    price_update_count = 0
    new_history_entries = []

    for it in items:
        s_name = it.get('supplier_name', 'Import Supplier')
        it_no = str(it.get('supplier_item_no', '')).strip()
        it_desc = str(it.get('supplier_desc', '')).strip()
        key = make_item_key(s_name, it_no, it_desc)
        new_p = round(float(it.get('rmb_price', 0.0)), 3)
        new_pcs = int(it.get('pcs_per_ctn', 0))
        new_qty = int(it.get('invoiced_qty', 0))
        v_no = str(it.get('voucher_no', ''))
        multiplier = float(it.get('landed_multiplier', 0.0))
        src = it.get('source_invoice') or it.get('invoice_file', '')
        ctn_range = str(it.get('ctn_range', '')).strip()

        if key in existing_dict:
            # Item exists: check if price changed
            old_p = round(float(existing_dict[key].get('rmb_price', 0.0)), 3)
            if abs(old_p - new_p) > 0.001 and old_p > 0:
                price_update_count += 1
                new_history_entries.append({
                    'id': len(history_df) + len(new_history_entries) + 1,
                    'supplier_name': s_name,
                    'supplier_item_no': it_no,
                    'supplier_desc': it_desc,
                    'old_rmb_price': old_p,
                    'new_rmb_price': new_p,
                    'source_invoice': src,
                    'updated_at': now_str
                })

            # Update latest price and carton size
            existing_dict[key]['rmb_price'] = new_p
            existing_dict[key]['pcs_per_ctn'] = new_pcs if new_pcs > 0 else existing_dict[key].get('pcs_per_ctn', 0)
            if new_qty > 0:
                existing_dict[key]['invoiced_qty'] = new_qty
            if v_no:
                existing_dict[key]['voucher_no'] = v_no
            if multiplier > 0:
                existing_dict[key]['landed_multiplier'] = multiplier
            if ctn_range:
                existing_dict[key]['ctn_range'] = ctn_range
            existing_dict[key]['source_invoice'] = src
            existing_dict[key]['extracted_at'] = now_str

            # If not matched yet but incoming item has match suggestion, record it
            if not existing_dict[key].get('is_matched') and it.get('matched_product_name'):
                existing_dict[key]['tally_product_name'] = it['matched_product_name']
                existing_dict[key]['is_matched'] = True
                existing_dict[key]['match_type'] = it.get('match_type', 'Auto Match')
                existing_dict[key]['match_confidence'] = it.get('confidence', 0.8)
                existing_dict[key]['matched_at'] = now_str
        else:
            # Brand new item
            new_count += 1
            is_m = bool(it.get('matched_product_name'))
            existing_dict[key] = {
                'id': len(existing_dict) + 1,
                'item_key': key,
                'supplier_name': s_name,
                'supplier_item_no': it_no,
                'supplier_desc': it_desc,
                'rmb_price': new_p,
                'pcs_per_ctn': new_pcs,
                'invoiced_qty': new_qty,
                'voucher_no': v_no,
                'landed_multiplier': multiplier,
                'ctn_range': ctn_range,
                'source_invoice': src,
                'extracted_at': now_str,
                'tally_product_name': it.get('matched_product_name'),
                'is_matched': is_m,
                'match_confidence': it.get('confidence', 0.0) if is_m else 0.0,
                'match_type': it.get('match_type', 'Unmatched') if is_m else 'Unmatched',
                'matched_at': now_str if is_m else None
            }

    # Persist updated items
    final_df = pd.DataFrame(list(existing_dict.values()))
    final_df.to_csv(INVOICE_ITEMS_FILE, index=False, encoding='utf-8')

    # Persist price history if any changes
    if new_history_entries:
        if not history_df.empty:
            comb_hist = pd.concat([history_df, pd.DataFrame(new_history_entries)], ignore_index=True)
        else:
            comb_hist = pd.DataFrame(new_history_entries)
        comb_hist.to_csv(PRICE_HISTORY_FILE, index=False, encoding='utf-8')

    # Sync Supabase if configured
    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            records = []
            for rec in existing_dict.values():
                c = rec.copy()
                if 'id' in c:
                    del c['id']
                records.append(c)
            for i in range(0, len(records), 100):
                client.table('commercial_invoice_items').upsert(records[i:i+100], on_conflict='item_key').execute()
            if new_history_entries:
                h_copy = []
                for h in new_history_entries:
                    hc = h.copy()
                    if 'id' in hc:
                        del hc['id']
                    h_copy.append(hc)
                client.table('commercial_price_history').insert(h_copy).execute()
        except Exception:
            pass

    # Synchronize active product_supplier_mappings for PO Engine
    sync_matched_items_to_catalog()

    return {
        'new_items': new_count,
        'updated_prices': price_update_count,
        'total': len(final_df)
    }

def sync_matched_items_to_catalog():
    """
    Sync all matched items from commercial_invoice_items into product_supplier_mappings.
    Ensures PO Engine always has 100% synchronized RMB prices and carton sizes.
    """
    items_df = get_commercial_invoice_items()
    if items_df.empty:
        return

    matched = items_df[items_df['is_matched'] == True].copy()
    if matched.empty:
        return

    # For each Tally product, take the latest matched record
    matched = matched.sort_values('extracted_at', ascending=True)
    catalog_records = []
    for _, r in matched.iterrows():
        p_name = r.get('tally_product_name')
        if not p_name or pd.isna(p_name):
            continue
        catalog_records.append({
            'product_name': str(p_name).strip(),
            'supplier_name': r.get('supplier_name', 'Huabei'),
            'supplier_item_no': r.get('supplier_item_no', ''),
            'supplier_desc': r.get('supplier_desc', ''),
            'rmb_price': float(r.get('rmb_price', 0.0)),
            'pcs_per_ctn': int(r.get('pcs_per_ctn', 0)),
            'invoice_file': r.get('source_invoice', ''),
            'matched_at': r.get('matched_at', '')
        })

    if catalog_records:
        save_product_supplier_mappings(catalog_records)

def update_commercial_item_match(item_key: str, tally_product_name: str, match_type: str = 'Manual', confidence: float = 1.0):
    """Assign or update a Tally product match for an extracted invoice item."""
    df = get_commercial_invoice_items()
    if df.empty:
        return

    mask = df['item_key'] == item_key
    if not mask.any():
        return

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    df.loc[mask, 'tally_product_name'] = tally_product_name
    df.loc[mask, 'is_matched'] = True
    df.loc[mask, 'match_type'] = match_type
    df.loc[mask, 'match_confidence'] = confidence
    df.loc[mask, 'matched_at'] = now_str

    df.to_csv(INVOICE_ITEMS_FILE, index=False, encoding='utf-8')

    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            client.table('commercial_invoice_items').update({
                'tally_product_name': tally_product_name,
                'is_matched': True,
                'match_type': match_type,
                'match_confidence': confidence,
                'matched_at': now_str
            }).eq('item_key', item_key).execute()
        except Exception:
            pass

    sync_matched_items_to_catalog()

def batch_update_commercial_matches(matches: List[Dict[str, Any]]):
    """
    Batch update multiple item matches at once.
    Each item: {'item_key': str, 'tally_product_name': str, 'match_type': str, 'confidence': float}
    """
    if not matches:
        return

    df = get_commercial_invoice_items()
    if df.empty:
        return

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for m in matches:
        k = m['item_key']
        p_name = m['tally_product_name']
        mask = df['item_key'] == k
        if mask.any():
            df.loc[mask, 'tally_product_name'] = p_name
            df.loc[mask, 'is_matched'] = True
            df.loc[mask, 'match_type'] = m.get('match_type', 'Auto Match')
            df.loc[mask, 'match_confidence'] = m.get('confidence', 1.0)
            df.loc[mask, 'matched_at'] = now_str

    df.to_csv(INVOICE_ITEMS_FILE, index=False, encoding='utf-8')

    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            for m in matches:
                client.table('commercial_invoice_items').update({
                    'tally_product_name': m['tally_product_name'],
                    'is_matched': True,
                    'match_type': m.get('match_type', 'Auto Match'),
                    'match_confidence': m.get('confidence', 1.0),
                    'matched_at': now_str
                }).eq('item_key', m['item_key']).execute()
        except Exception:
            pass

    sync_matched_items_to_catalog()

def unmatch_commercial_item(item_key: str):
    """Remove matching between an invoice item and Tally product."""
    df = get_commercial_invoice_items()
    if df.empty:
        return

    mask = df['item_key'] == item_key
    if not mask.any():
        return

    old_tally = df.loc[mask, 'tally_product_name'].values[0]
    df.loc[mask, 'tally_product_name'] = None
    df.loc[mask, 'is_matched'] = False
    df.loc[mask, 'match_type'] = 'Unmatched'
    df.loc[mask, 'match_confidence'] = 0.0
    df.loc[mask, 'matched_at'] = None

    df.to_csv(INVOICE_ITEMS_FILE, index=False, encoding='utf-8')

    # Remove from product_supplier_mappings if present
    if old_tally:
        maps = get_product_supplier_mappings()
        if not maps.empty and (maps['product_name'] == old_tally).any():
            maps = maps[maps['product_name'] != old_tally]
            maps.to_csv(MAPPINGS_FILE, index=False, encoding='utf-8')

    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            client.table('commercial_invoice_items').update({
                'tally_product_name': None,
                'is_matched': False,
                'match_type': 'Unmatched',
                'match_confidence': 0.0,
                'matched_at': None
            }).eq('item_key', item_key).execute()
            if old_tally:
                client.table('product_supplier_mappings').delete().eq('product_name', old_tally).execute()
        except Exception:
            pass

def get_product_supplier_mappings() -> pd.DataFrame:
    """Fetch all saved commercial invoice product-to-RMB mappings."""
    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            res = client.table('product_supplier_mappings').select('*').execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception:
            pass

    if os.path.exists(MAPPINGS_FILE):
        try:
            return pd.read_csv(MAPPINGS_FILE, encoding='utf-8')
        except Exception:
            pass

    cols = ['product_name', 'supplier_name', 'supplier_item_no', 'supplier_desc', 'rmb_price', 'pcs_per_ctn', 'invoice_file', 'matched_at']
    return pd.DataFrame(columns=cols)

def sync_product_rmb_to_hermes(product_name: str, rmb_price: float) -> bool:
    """
    Directly propagate confirmed RMB price to hermes_items in Primary Supabase
    and local cache so the WhatsApp assistant and Purchase Order engine immediately
    quote the updated RMB price.
    """
    if not product_name or float(rmb_price or 0.0) <= 0:
        return False

    p_clean = str(product_name).strip()
    price_val = round(float(rmb_price), 3)

    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            client.table('hermes_items').update({
                'rmb_price': price_val
            }).eq('product_name', p_clean).execute()
        except Exception as e:
            print(f"[db] Warning syncing rmb_price to Supabase hermes_items: {e}")

    # Also update local parquet/csv cache if present
    for cache_p in [os.path.join("data", "hermes_items.parquet"), os.path.join("data", "hermes_items.csv")]:
        if os.path.exists(cache_p):
            try:
                if cache_p.endswith('.parquet'):
                    h_df = pd.read_parquet(cache_p)
                else:
                    h_df = pd.read_csv(cache_p)
                if not h_df.empty and 'product_name' in h_df.columns:
                    mask = h_df['product_name'].astype(str).str.strip() == p_clean
                    if mask.any():
                        h_df.loc[mask, 'rmb_price'] = price_val
                        if cache_p.endswith('.parquet'):
                            h_df.to_parquet(cache_p, index=False)
                        else:
                            h_df.to_csv(cache_p, index=False)
            except Exception:
                pass
    return True

def save_product_supplier_mappings(records: List[Dict[str, Any]]):
    """Save or update product-to-RMB price mappings and sync to hermes_items."""
    if not records:
        return

    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    for r in records:
        if 'matched_at' not in r or not r['matched_at']:
            r['matched_at'] = now_str

    client = get_client()
    if client is not None and is_supabase_configured():
        try:
            client.table('product_supplier_mappings').upsert(
                records,
                on_conflict='product_name'
            ).execute()
        except Exception:
            pass

    # Save to local CSV for offline persistence
    current_df = get_product_supplier_mappings()
    new_df = pd.DataFrame(records)

    if not current_df.empty:
        combined = pd.concat([current_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=['product_name'], keep='last')
    else:
        combined = new_df

    combined.to_csv(MAPPINGS_FILE, index=False, encoding='utf-8')

    # Propagate RMB prices directly to Hermes AI table
    for r in records:
        p_name = r.get('product_name')
        p_rmb = r.get('rmb_price')
        if p_name and p_rmb and float(p_rmb) > 0:
            sync_product_rmb_to_hermes(str(p_name), float(p_rmb))



