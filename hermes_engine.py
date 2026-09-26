"""
Hermes Engine — AI Knowledge Base & Catalog Synchronization Engine
Builds and maintains the unified `hermes_items` table in our Primary Supabase DB.
Merges:
  1. Product photos, tags, and catalog prices from Bafa (STRICTLY READ-ONLY)
  2. Live stock balance (Opening Stock + Purchases - Sales) from DayBook ledger
  3. Last active month's weighted average selling rate from DayBook ledger
  4. Factory RMB import prices from Commercial Invoices
"""

import os
import sys
import datetime
from typing import Dict, List, Any, Optional, Callable
import pandas as pd
import numpy as np

import db
from po_engine import estimate_current_stock
from stksum_parser import infer_product_group
from HermesData.catalog_reader import get_all_catalog_products

HERMES_CACHE_CSV = os.path.join("data", "hermes_items.csv")
HERMES_CACHE_PARQUET = os.path.join("data", "hermes_items.parquet")

def build_hermes_items_df() -> pd.DataFrame:
    """
    Build the unified hermes_items DataFrame by merging:
      - Bafa product catalog (photos, tags, catalog prices) [READ-ONLY]
      - DayBook line items & opening stock (live stock & last-month selling rate)
      - Commercial invoice supplier mappings (RMB prices)
    """
    # 1. Fetch Bafa catalog (read-only)
    try:
        bafa_df = get_all_catalog_products()
    except Exception as e:
        print(f"[Hermes Engine] Warning: Failed to fetch Bafa catalog: {e}")
        bafa_df = pd.DataFrame(columns=['product_name', 'tags', 'image_url', 'catalog_price', 'selling_price'])

    # Clean product names in Bafa
    if not bafa_df.empty:
        bafa_df['product_name'] = bafa_df['product_name'].astype(str).str.strip()
        bafa_df = bafa_df.drop_duplicates(subset=['product_name'], keep='first')

    # 2. Fetch DayBook records and Opening Stock
    if db.is_supabase_configured():
        v_df = db.get_vouchers_df()
        li_df = db.get_line_items_df()
        op_df = db.get_opening_stock_df()
    else:
        v_df, li_df = db.load_local_data()
        op_df = db.get_opening_stock_df()

    # 3. Compute live stock (Opening + Purchases - Sales)
    if not li_df.empty:
        stock_df = estimate_current_stock(li_df, op_df)
    else:
        stock_df = pd.DataFrame(columns=['product_name', 'est_stock', 'product_group'])

    if not stock_df.empty:
        stock_df['product_name'] = stock_df['product_name'].astype(str).str.strip()
        stock_df = stock_df.drop_duplicates(subset=['product_name'], keep='first')

    # 4. Compute Selling Price (weighted average in the product's last active selling month)
    latest_sales = pd.DataFrame(columns=['product_name', 'selling_price', 'last_sold_month'])
    if not li_df.empty and 'voucher_category' in li_df.columns:
        sales = li_df[li_df['voucher_category'] == 'Sales'].copy()
        if not sales.empty:
            sales['product_name'] = sales['product_name'].astype(str).str.strip()
            # Group by product and month
            sales_month = sales.groupby(['product_name', 'month']).agg(
                total_qty=('quantity', 'sum'),
                total_amt=('amount', 'sum')
            ).reset_index()
            # Sort by month descending to find latest active selling month
            sales_month = sales_month.sort_values(['product_name', 'month'], ascending=[True, False])
            latest_sales = sales_month.drop_duplicates(subset=['product_name'], keep='first').copy()
            # Avoid division by zero
            valid_qty = latest_sales['total_qty'].replace(0, np.nan)
            latest_sales['selling_price'] = (latest_sales['total_amt'] / valid_qty).round(2)
            latest_sales = latest_sales.rename(columns={'month': 'last_sold_month'})[['product_name', 'selling_price', 'last_sold_month']]

    # 5. Fetch RMB import prices from Primary DB
    rmb_df = pd.DataFrame(columns=['product_name', 'rmb_price'])
    client = db.get_client()
    if client:
        try:
            rmb_res = client.table('product_supplier_mappings').select('product_name, rmb_price').execute()
            if rmb_res.data:
                rmb_df = pd.DataFrame(rmb_res.data)
                rmb_df['product_name'] = rmb_df['product_name'].astype(str).str.strip()
                rmb_df = rmb_df.drop_duplicates(subset=['product_name'], keep='first')
        except Exception as e:
            print(f"[Hermes Engine] Warning: Failed to fetch RMB prices: {e}")

    # 6. Merge All Sources
    # Primary merge on product_name (outer join to preserve all catalog and DayBook items)
    bafa_cols = ['product_name', 'tags', 'image_url', 'catalog_price']
    bafa_sub = bafa_df[bafa_cols] if not bafa_df.empty else pd.DataFrame(columns=bafa_cols)

    stock_cols = ['product_name', 'est_stock', 'product_group']
    stock_sub = stock_df[stock_cols] if not stock_df.empty else pd.DataFrame(columns=stock_cols)

    merged = pd.merge(bafa_sub, stock_sub, on='product_name', how='outer')
    merged = pd.merge(merged, latest_sales, on='product_name', how='left')
    merged = pd.merge(merged, rmb_df, on='product_name', how='left')
    merged = merged.copy()

    # 7. Clean and Standardize Fields
    merged['product_name'] = merged['product_name'].astype(str).str.strip()
    merged = merged[merged['product_name'].str.len() > 0].copy()
    merged = merged.drop_duplicates(subset=['product_name'], keep='first').copy()

    # Current Stock
    current_stock_col = pd.to_numeric(merged['est_stock'], errors='coerce').fillna(0.0).round(2)

    # Selling Price: use DayBook last month avg; fallback to Bafa catalog_price; fallback to 0.0
    daybook_sp = pd.to_numeric(merged['selling_price'], errors='coerce')
    cat_p = pd.to_numeric(merged['catalog_price'], errors='coerce')
    selling_price_col = daybook_sp.fillna(cat_p).fillna(0.0).round(2)

    # Catalog & RMB Prices
    catalog_price_col = pd.to_numeric(merged['catalog_price'], errors='coerce').round(2)
    rmb_price_col = pd.to_numeric(merged['rmb_price'], errors='coerce').round(3)

    # Product Group
    if 'product_group' in merged.columns:
        group_series = merged['product_group'].fillna('Others').copy()
        mask_unknown = group_series.isin(['Others', '', None]) | group_series.isna()
        if mask_unknown.any():
            group_series.loc[mask_unknown] = merged.loc[mask_unknown, 'product_name'].apply(infer_product_group)
    else:
        group_series = merged['product_name'].apply(infer_product_group)

    # Tags & Image URL
    tags_col = merged['tags'].apply(lambda x: str(x).strip() if pd.notna(x) and str(x).strip() not in ['', 'nan', 'None'] else None)
    image_url_col = merged['image_url'].apply(lambda x: str(x).strip() if pd.notna(x) and str(x).strip() not in ['', 'nan', 'None'] else None)
    last_sold_col = merged['last_sold_month'].apply(lambda x: str(x).strip() if pd.notna(x) and str(x).strip() not in ['', 'nan', 'None'] else None)

    merged = merged.assign(
        current_stock=current_stock_col,
        selling_price=selling_price_col,
        catalog_price=catalog_price_col,
        rmb_price=rmb_price_col,
        product_group=group_series,
        tags=tags_col,
        image_url=image_url_col,
        last_sold_month=last_sold_col
    )

    final_cols = [
        'product_name',
        'current_stock',
        'selling_price',
        'catalog_price',
        'rmb_price',
        'image_url',
        'tags',
        'last_sold_month',
        'product_group'
    ]
    return merged[final_cols].sort_values('product_name').reset_index(drop=True)

def sync_hermes_items(progress_callback: Optional[Callable[[float, str], None]] = None) -> Dict[str, Any]:
    """
    Main Synchronization Function:
      1. Pulls Bafa catalog (read-only)
      2. Computes live stock and last-month average selling rate from DayBook
      3. Attaches commercial RMB prices
      4. Upserts all records into table `hermes_items` in Primary Supabase DB
      5. Updates local parquet and CSV caches
    """
    client = db.get_client()
    if client is None:
        raise ConnectionError("Primary Supabase client is not configured in .env.")

    if progress_callback:
        progress_callback(0.10, "Fetching Bafa catalog, DayBook records, and RMB mappings...")

    df = build_hermes_items_df()
    total_records = len(df)

    if progress_callback:
        progress_callback(0.40, f"Built knowledge base ({total_records} items). Preparing database sync...")

    # Prepare records for Supabase upsert (replace NaN with None for valid JSON)
    records = df.to_dict('records')
    cleaned_records = []
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for r in records:
        clean_r = {
            'product_name': str(r['product_name']),
            'current_stock': float(r['current_stock']) if pd.notna(r['current_stock']) else 0.0,
            'selling_price': float(r['selling_price']) if pd.notna(r['selling_price']) else 0.0,
            'catalog_price': float(r['catalog_price']) if pd.notna(r['catalog_price']) else None,
            'rmb_price': float(r['rmb_price']) if pd.notna(r['rmb_price']) else None,
            'image_url': str(r['image_url']) if pd.notna(r['image_url']) and r['image_url'] else None,
            'tags': str(r['tags']) if pd.notna(r['tags']) and r['tags'] else None,
            'last_sold_month': str(r['last_sold_month']) if pd.notna(r['last_sold_month']) and r['last_sold_month'] else None,
            'product_group': str(r['product_group']) if pd.notna(r['product_group']) and r['product_group'] else 'Others',
            'updated_at': now_iso
        }
        cleaned_records.append(clean_r)

    # Batch upsert into Primary Supabase DB
    chunk_size = 200
    inserted_count = 0
    total_batches = (total_records + chunk_size - 1) // chunk_size

    for i in range(0, total_records, chunk_size):
        batch = cleaned_records[i:i + chunk_size]
        batch_idx = (i // chunk_size) + 1
        pct = 0.40 + (0.50 * (batch_idx / total_batches))
        if progress_callback:
            progress_callback(pct, f"Syncing items {i+1} to {min(i+chunk_size, total_records)} to Supabase...")

        try:
            res = client.table('hermes_items').upsert(
                batch,
                on_conflict='product_name',
                ignore_duplicates=False
            ).execute()
            if res.data:
                inserted_count += len(res.data)
            else:
                inserted_count += len(batch)
        except Exception as e:
            print(f"[Hermes Engine] Error upserting batch {batch_idx}: {e}")
            # Try individual row upsert as fallback for batch
            for row in batch:
                try:
                    client.table('hermes_items').upsert(row, on_conflict='product_name').execute()
                    inserted_count += 1
                except Exception:
                    pass

    # Save local disk cache
    os.makedirs("data", exist_ok=True)
    df.to_csv(HERMES_CACHE_CSV, index=False)
    try:
        df.to_parquet(HERMES_CACHE_PARQUET, index=False)
    except Exception:
        pass

    if progress_callback:
        progress_callback(1.0, f"Sync complete! {inserted_count} items synchronized.")

    summary = {
        'total_items': total_records,
        'inserted_or_updated': inserted_count,
        'with_photos': int(df['image_url'].notna().sum()),
        'with_tags': int(df['tags'].notna().sum()),
        'with_positive_stock': int((df['current_stock'] > 0).sum()),
        'with_rmb_price': int(df['rmb_price'].notna().sum()),
        'synced_at': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return summary

def get_hermes_items_df(force_cloud: bool = False) -> pd.DataFrame:
    """
    Retrieve hermes_items DataFrame from Primary Supabase or local cache.
    """
    if not force_cloud and os.path.exists(HERMES_CACHE_PARQUET):
        try:
            return pd.read_parquet(HERMES_CACHE_PARQUET)
        except Exception:
            pass

    client = db.get_client()
    if client:
        try:
            # Fetch all rows from hermes_items
            all_rows = []
            offset = 0
            page_size = 1000
            while True:
                res = client.table('hermes_items').select('*').range(offset, offset + page_size - 1).execute()
                if not res.data:
                    break
                all_rows.extend(res.data)
                if len(res.data) < page_size:
                    break
                offset += page_size
            if all_rows:
                df = pd.DataFrame(all_rows)
                return df
        except Exception as e:
            print(f"[Hermes Engine] Error reading hermes_items from Supabase: {e}")

    if os.path.exists(HERMES_CACHE_CSV):
        return pd.read_csv(HERMES_CACHE_CSV)

    return pd.DataFrame()

def hermes_query_items(
    tag: Optional[str] = None,
    search: Optional[str] = None,
    in_stock_only: bool = False,
    has_photo_only: bool = False,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Direct query function for Hermes Agent (or Dashboard):
    Executes against our Primary Supabase Database.
    """
    client = db.get_client()
    if client is None:
        # Fallback to local cache if client unavailable
        df = get_hermes_items_df()
        if df.empty:
            return []
        if tag:
            df = df[df['tags'].str.contains(tag.strip(), na=False, case=False)]
        if search:
            df = df[df['product_name'].str.contains(search.strip(), na=False, case=False)]
        if in_stock_only:
            df = df[df['current_stock'] > 0]
        if has_photo_only:
            df = df[df['image_url'].notna() & (df['image_url'] != '')]
        return df.head(limit).to_dict('records')

    query = client.table('hermes_items').select('product_name, current_stock, selling_price, catalog_price, rmb_price, image_url, tags, product_group, last_sold_month')
    if tag:
        query = query.ilike('tags', f"%{tag.strip().upper()}%")
    if search:
        query = query.ilike('product_name', f"%{search.strip()}%")
    if in_stock_only:
        query = query.gt('current_stock', 0)
    if has_photo_only:
        query = query.not_.is_('image_url', 'null')

    res = query.order('current_stock', desc=True).limit(limit).execute()
    return res.data or []

def get_available_tags(misspelled_tag: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """
    Returns available product tags.
    If misspelled_tag is provided, returns close matches using fuzzy search.
    If no close match or no tag provided, returns top popular tags.
    """
    import difflib

    df = get_hermes_items_df()
    if df.empty or 'tags' not in df.columns:
        return {'suggestions': [], 'popular_tags': []}

    tag_counts = {}
    for tags_str in df['tags'].dropna():
        for t in str(tags_str).split(';'):
            clean_t = t.strip().upper()
            if clean_t:
                tag_counts[clean_t] = tag_counts.get(clean_t, 0) + 1

    sorted_popular = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    all_tag_keys = list(tag_counts.keys())

    suggestions = []
    if misspelled_tag:
        raw_tag = misspelled_tag.strip().upper()
        # 1. Close fuzzy matches
        close = difflib.get_close_matches(raw_tag, all_tag_keys, n=limit, cutoff=0.45)
        # 2. Substring matches
        substring = [t for t in all_tag_keys if raw_tag in t or t in raw_tag]
        
        # Combine unique matches preserving order
        seen = set()
        for t in close + substring:
            if t not in seen:
                seen.add(t)
                suggestions.append({'tag': t, 'product_count': tag_counts[t]})

    popular_tags = [{'tag': t, 'product_count': c} for t, c in sorted_popular[:limit]]

    return {
        'input_tag': misspelled_tag,
        'has_matches': len(suggestions) > 0,
        'suggestions': suggestions[:limit],
        'popular_tags': popular_tags
    }

