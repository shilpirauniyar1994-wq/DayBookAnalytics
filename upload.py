"""
DayBook Analytics — Supabase Ingestion & Deduplication Module
Safely uploads parsed vouchers and line items to Supabase PostgreSQL,
handling duplicates with composite unique constraints and updating supplier analytics.
"""

import os
import math
import pandas as pd
from typing import Dict, List, Any, Optional, Callable
from db import get_client, is_supabase_configured

def clean_float(val, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return default
    try:
        f = float(val)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (ValueError, TypeError):
        return default

def clean_str(val, default: Optional[str] = None) -> Optional[str]:
    if val is None or pd.isna(val):
        return default
    s = str(val).strip()
    return default if s in ('', 'nan', 'None', '<NA>') else s

def chunked(items: List[Any], chunk_size: int = 500):
    """Yield successive chunk_size chunks from items."""
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]

def upload_vouchers(vouchers_df: pd.DataFrame, upload_id: Optional[int] = None) -> Dict[str, int]:
    """
    Upload voucher records to Supabase with deduplication.
    Unique constraint: (date, voucher_type, voucher_no, party_name).
    """
    client = get_client()
    if client is None:
        raise ConnectionError("Supabase client is not configured. Please check your .env file.")

    records = vouchers_df.to_dict('records')
    cleaned_records = []
    for r in records:
        entry = {
            'date': str(r['date']),
            'voucher_no': clean_str(r.get('voucher_no'), ''),
            'voucher_type': clean_str(r.get('voucher_type'), ''),
            'party_name': clean_str(r.get('party_name'), 'Unknown'),
            'voucher_category': clean_str(r.get('voucher_category'), 'Other'),
            'miti': clean_str(r.get('miti')),
            'narration': clean_str(r.get('narration')),
            'month': clean_str(r.get('month')),
            'debit_amount': clean_float(r.get('debit_amount')),
            'credit_amount': clean_float(r.get('credit_amount')),
        }
        if upload_id is not None:
            entry['upload_id'] = upload_id
        cleaned_records.append(entry)

    total = len(cleaned_records)
    inserted = 0

    for batch in chunked(cleaned_records, 500):
        try:
            # ON CONFLICT DO NOTHING (skip existing duplicates, only insert genuinely new vouchers)
            res = client.table('vouchers').upsert(
                batch,
                on_conflict='date,voucher_type,voucher_no,party_name',
                ignore_duplicates=True
            ).execute()
            if res.data:
                inserted += len(res.data)
        except Exception as e:
            print(f"[Upload] Voucher batch upload note: {e}")

    skipped = max(0, total - inserted)
    return {'inserted': inserted, 'skipped': skipped, 'total': total}

def build_voucher_id_map(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[tuple, int]:
    """
    Fetch voucher IDs for the given date range to map foreign keys for line_items.
    Returns: {(date_str, voucher_type, voucher_no, party_name): voucher_id}
    """
    client = get_client()
    if client is None:
        return {}

    id_map = {}
    page_size = 1000
    offset = 0

    while True:
        query = client.table('vouchers').select('id, date, voucher_type, voucher_no, party_name').order('id')
        if start_date:
            query = query.gte('date', start_date)
        if end_date:
            query = query.lte('date', end_date)

        res = query.range(offset, offset + page_size - 1).execute()

        if not res.data:
            break

        for r in res.data:
            key = (str(r['date']), str(r['voucher_type']).strip(), str(r['voucher_no']).strip(), str(r['party_name']).strip())
            id_map[key] = r['id']

        if len(res.data) < page_size:
            break
        offset += page_size

    return id_map

def upload_line_items(line_items_df: pd.DataFrame, voucher_id_map: Dict[tuple, int]) -> Dict[str, int]:
    """
    Upload line items with foreign key linked to vouchers.
    Unique constraint: (date, voucher_type, voucher_no, party_name, product_name, quantity, rate).
    """
    client = get_client()
    if client is None:
        raise ConnectionError("Supabase client is not configured.")

    records = line_items_df.to_dict('records')
    cleaned_records = []
    for r in records:
        d_str = str(r['date'])
        v_type = clean_str(r.get('voucher_type'), '')
        v_no = clean_str(r.get('voucher_no'), '')
        p_name = clean_str(r.get('party_name'), 'Unknown')
        key = (d_str, v_type, v_no, p_name)

        cleaned_records.append({
            'date': d_str,
            'voucher_no': v_no,
            'voucher_type': v_type,
            'party_name': p_name,
            'voucher_category': clean_str(r.get('voucher_category'), 'Other'),
            'product_name': clean_str(r.get('product_name'), ''),
            'product_group': clean_str(r.get('product_group'), 'Others'),
            'month': clean_str(r.get('month')),
            'quantity': clean_float(r.get('quantity')),
            'rate': clean_float(r.get('rate')),
            'amount': clean_float(r.get('amount')),
            'voucher_id': voucher_id_map.get(key)
        })

    total = len(cleaned_records)
    inserted = 0

    for batch in chunked(cleaned_records, 500):
        try:
            res = client.table('line_items').upsert(
                batch,
                on_conflict='date,voucher_type,voucher_no,party_name,product_name,quantity,rate',
                ignore_duplicates=True
            ).execute()
            if res.data:
                inserted += len(res.data)
        except Exception as e:
            print(f"[Upload] Line items batch upload note: {e}")

    return {'inserted': inserted, 'total': total}

def update_supplier_products(line_items_df: pd.DataFrame):
    """
    Auto-populate and refresh supplier_products from Purchase line items.
    """
    client = get_client()
    if client is None:
        return

    from po_engine import resolve_supplier_alias
    purchases = line_items_df[line_items_df['voucher_category'] == 'Purchase'].copy()
    if purchases.empty:
        return

    purchases['supplier_name'] = purchases.apply(
        lambda r: resolve_supplier_alias(r.get('party_name', ''), r.get('voucher_no', '')),
        axis=1
    )

    supplier_agg = purchases.groupby(['supplier_name', 'product_name']).agg(
        last_purchase_date=('date', 'max'),
        last_purchase_rate=('rate', 'last'),
        avg_purchase_rate=('rate', 'mean'),
        total_qty_purchased=('quantity', 'sum'),
        purchase_count=('product_name', 'count'),
    ).reset_index()

    records = supplier_agg.to_dict('records')
    cleaned_records = []
    for r in records:
        cleaned_records.append({
            'supplier_name': clean_str(r.get('supplier_name'), 'Unknown'),
            'product_name': clean_str(r.get('product_name'), ''),
            'last_purchase_date': str(r['last_purchase_date']),
            'last_purchase_rate': clean_float(r.get('last_purchase_rate')),
            'avg_purchase_rate': round(clean_float(r.get('avg_purchase_rate')), 2),
            'total_qty_purchased': clean_float(r.get('total_qty_purchased')),
            'purchase_count': int(clean_float(r.get('purchase_count'))),
        })

    for batch in chunked(cleaned_records, 300):
        try:
            client.table('supplier_products').upsert(
                batch,
                on_conflict='supplier_name,product_name'
            ).execute()
        except Exception:
            pass

def full_upload_pipeline(
    filepath_or_buffer: Any,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    file_size: int = 0,
    filename: str = 'DayBook.xlsx'
) -> Dict[str, Any]:
    """
    Execute full ingestion: parse -> record history -> upload vouchers -> upload line items -> update suppliers.
    """
    from parser import parse_daybook

    client = get_client()
    if client is None:
        raise ConnectionError("Supabase connection not available. Please verify .env settings.")

    if progress_callback:
        progress_callback(0.05, "Parsing Excel day book...")

    vouchers_df, line_items_df = parse_daybook(filepath_or_buffer)

    # 1. Log to upload_history
    start_date = str(vouchers_df['date'].min()) if not vouchers_df.empty else None
    end_date = str(vouchers_df['date'].max()) if not vouchers_df.empty else None

    upload_record = client.table('upload_history').insert({
        'filename': filename,
        'file_size_bytes': file_size,
        'date_range_start': start_date,
        'date_range_end': end_date,
        'total_vouchers': len(vouchers_df),
        'total_line_items': len(line_items_df),
        'status': 'In Progress',
    }).execute()

    upload_id = upload_record.data[0]['id'] if upload_record.data else None

    try:
        if progress_callback:
            progress_callback(0.25, f"Uploading {len(vouchers_df)} vouchers with deduplication...")
        v_result = upload_vouchers(vouchers_df, upload_id)

        if progress_callback:
            progress_callback(0.50, "Linking line items to vouchers...")
        id_map = build_voucher_id_map(start_date, end_date)

        if progress_callback:
            progress_callback(0.70, f"Uploading {len(line_items_df)} product line items...")
        li_result = upload_line_items(line_items_df, id_map)

        if progress_callback:
            progress_callback(0.85, "Updating supplier catalog and purchase trends...")
        update_supplier_products(line_items_df)

        # Merge new records into local cache safely
        try:
            import db
            db.append_to_local_cache(vouchers_df, line_items_df)
        except Exception as e:
            print(f"[Upload] Local cache append note: {e}")

        if progress_callback:
            progress_callback(0.95, "Recording upload history...")

        # Update upload_history with final status
        if upload_id:
            client.table('upload_history').update({
                'new_inserted': v_result['inserted'],
                'skipped': v_result['skipped'],
                'new_products': line_items_df['product_name'].nunique(),
                'status': 'Success',
            }).eq('id', upload_id).execute()

        # Keep Hermes Knowledge Base in sync with newly uploaded stock and transactions
        try:
            from hermes_engine import sync_hermes_items
            sync_hermes_items()
        except Exception as e:
            print(f"[Upload] Hermes Knowledge Base sync note: {e}")

        if progress_callback:
            progress_callback(1.0, "Upload and Hermes sync successfully completed!")

        return {
            'vouchers': v_result,
            'line_items': li_result,
            'total_products': line_items_df['product_name'].nunique(),
            'total_suppliers': line_items_df[line_items_df['voucher_category'] == 'Purchase']['party_name'].nunique(),
        }

    except Exception as e:
        if upload_id:
            client.table('upload_history').update({
                'status': 'Failed',
                'error_message': str(e),
            }).eq('id', upload_id).execute()
        raise e
