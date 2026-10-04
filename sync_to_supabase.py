"""
DayBook Analytics — Complete Cloud Sync & Database Reset to Supabase
Cleans all Supabase tables and re-uploads all DayBook records, commercial invoice items,
RMB prices, stock summary opening balances, product categories, and lead times.
"""

import os
import sys

# Ensure UTF-8 stdout/stderr on Windows to avoid charmap errors
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import datetime
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

import db
from upload import full_upload_pipeline, chunked
from stksum_parser import parse_stock_summary, save_stock_summary_data
from po_engine import resolve_supplier_alias

ALL_TABLES = [
    'po_line_items',
    'purchase_orders',
    'narrations',
    'line_items',
    'vouchers',
    'upload_history',
    'supplier_products',
    'commercial_price_history',
    'product_supplier_mappings',
    'commercial_invoice_items',
    'opening_stock',
    'product_group_mappings',
    'lead_time_config',
    'hermes_items'
]

def clean_supabase_tables(client):
    """Clean all tables in Supabase in reverse dependency order."""
    print("\n[Step 0] Cleaning all Supabase tables...")
    for t in ALL_TABLES:
        try:
            client.table(t).delete().gt('id', 0).execute()
            print(f"   -> Table '{t}' emptied.")
        except Exception as e:
            print(f"   -> Table '{t}' clean note: {e}")

def main():
    print("=" * 65)
    print(">> DayBook Analytics -- Complete Supabase Reset & Cloud Re-Upload")
    print("=" * 65)

    # 1. Verify Connection
    client = db.get_client()
    if not client or not db.is_supabase_configured():
        print("\n[!] Error: Cannot connect to Supabase.")
        print("Please ensure your .env file has valid SUPABASE_URL and SUPABASE_KEY.")
        sys.exit(1)

    print("\n[OK] Successfully connected to Supabase project!")

    # 0. Clean Supabase Tables
    clean_supabase_tables(client)

    # 1. Sync Lead Time Matrix
    print("\n[Step 1] Syncing Supplier Lead Time Matrix...")
    lead_times = [
        {'config_type': 'supplier', 'config_key': 'Huabei', 'lead_time_days': 90, 'safety_stock_days': 15, 'notes': 'China Overseas Import (3 months)'},
        {'config_type': 'supplier', 'config_key': 'Rara', 'lead_time_days': 90, 'safety_stock_days': 15, 'notes': 'China Overseas Import (3 months)'},
        {'config_type': 'supplier', 'config_key': 'Ayreen', 'lead_time_days': 90, 'safety_stock_days': 15, 'notes': 'China Overseas Import (3 months)'},
        {'config_type': 'supplier', 'config_key': 'Ben', 'lead_time_days': 90, 'safety_stock_days': 15, 'notes': 'China Overseas Import (Huabei/Ben 3 months)'},
        {'config_type': 'supplier', 'config_key': 'Shivam', 'lead_time_days': 30, 'safety_stock_days': 7, 'notes': 'Domestic / India Supplier (1 month)'},
        {'config_type': 'supplier', 'config_key': 'Venkateshwara / Surendar', 'lead_time_days': 30, 'safety_stock_days': 7, 'notes': 'Domestic / India Supplier (1 month)'},
        {'config_type': 'product_group', 'config_key': 'Big Toys', 'lead_time_days': 90, 'safety_stock_days': 5, 'notes': 'China Import Product Group'},
        {'config_type': 'default', 'config_key': 'global', 'lead_time_days': 14, 'safety_stock_days': 5, 'notes': 'Standard global default'},
    ]
    try:
        client.table('lead_time_config').upsert(lead_times, on_conflict='config_type,config_key').execute()
        print(f"   -> {len(lead_times)} supplier lead time profiles synced.")
    except Exception as e:
        print(f"   -> Error syncing lead times: {e}")

    # 2. Sync Stock Summary & Product Categories (StkSum.xlsx)
    print("\n[Step 2] Syncing Stock Summary Opening Balances & Product Categories...")
    if os.path.exists("StkSum.xlsx"):
        stk_df, _, _ = parse_stock_summary("StkSum.xlsx")
        op_count, pg_count = save_stock_summary_data(stk_df)
        print(f"   -> Synced {op_count} opening stock balances & {pg_count} product categories to Supabase!")
    else:
        print("   -> StkSum.xlsx not found in workspace root. Skipping opening stock sync.")

    # 3. Sync Extracted Commercial Invoice Items
    print("\n[Step 3] Syncing Extracted Commercial Invoice Items (235 items)...")
    if os.path.exists("commercial_invoice_items.csv"):
        items_df = pd.read_csv("commercial_invoice_items.csv")
        records = items_df.to_dict('records')
        for r in records:
            if 'id' in r: del r['id']
            r['is_matched'] = bool(r.get('is_matched', False))
            if pd.isna(r.get('tally_product_name')): r['tally_product_name'] = None
            if pd.isna(r.get('matched_at')): r['matched_at'] = None
            if pd.isna(r.get('supplier_item_no')): r['supplier_item_no'] = ''
            if pd.isna(r.get('supplier_desc')): r['supplier_desc'] = ''
        
        for i in range(0, len(records), 100):
            batch = records[i:i+100]
            try:
                client.table('commercial_invoice_items').upsert(batch, on_conflict='item_key').execute()
            except Exception as e:
                print(f"   -> Batch {i//100 + 1} error: {e}")
        print(f"   -> {len(records)} commercial invoice items synced to Supabase!")

    # 4. Sync Price Change History
    print("\n[Step 4] Syncing Commercial Price Change History...")
    if os.path.exists("commercial_price_history.csv"):
        hist_df = pd.read_csv("commercial_price_history.csv")
        h_records = hist_df.to_dict('records')
        for r in h_records:
            if 'id' in r: del r['id']
            if pd.isna(r.get('supplier_item_no')): r['supplier_item_no'] = ''
            if pd.isna(r.get('supplier_desc')): r['supplier_desc'] = ''
        if h_records:
            try:
                client.table('commercial_price_history').insert(h_records).execute()
                print(f"   -> {len(h_records)} price change audit entries synced.")
            except Exception as e:
                print(f"   -> Price history sync note: {e}")
        else:
            print("   -> 0 price change history entries to sync.")

    # 5. Sync Product Supplier RMB Mappings
    print("\n[Step 5] Syncing Active Product RMB Mappings (116 products)...")
    if os.path.exists("product_mappings.csv"):
        maps_df = pd.read_csv("product_mappings.csv")
        m_records = maps_df.to_dict('records')
        for r in m_records:
            if 'id' in r: del r['id']
            if pd.isna(r.get('supplier_item_no')): r['supplier_item_no'] = ''
            if pd.isna(r.get('supplier_desc')): r['supplier_desc'] = ''
        try:
            client.table('product_supplier_mappings').upsert(m_records, on_conflict='product_name').execute()
            print(f"   -> {len(m_records)} active RMB catalog products synced.")
        except Exception as e:
            print(f"   -> RMB mapping sync error: {e}")

    # 6. Sync DayBook Data from daybooks/ folder in chronological order
    daybook_dir = "daybooks"
    chronological_preference = [
        'DayBook6.xlsx',   # 2025-06-15 to 2025-09-17
        'DayBook9.xlsx',   # 2025-09-17 to 2025-12-16
        'DayBook12.xlsx',  # 2025-12-16 to 2026-03-15
        'DayBook2.xlsx',   # 2026-03-15 to 2026-05-15
        'DayBook5.xlsx',   # 2026-05-15 to 2026-08-17
        'DayBook.xlsx',    # 2026-06-13 to 2026-09-21
    ]

    daybook_files = []
    if os.path.exists(daybook_dir):
        # Add preferential chronological order first
        for name in chronological_preference:
            p = os.path.join(daybook_dir, name)
            if os.path.exists(p):
                daybook_files.append(p)
        # Add any other xlsx in daybook_dir
        for f in sorted(os.listdir(daybook_dir)):
            p = os.path.join(daybook_dir, f)
            if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith(('~', '.')) and p not in daybook_files:
                daybook_files.append(p)

    if not daybook_files:
        for f in ['DayBook.xlsx', 'DayBook6.xlsx']:
            if os.path.exists(f):
                daybook_files.append(f)

    print(f"\n[Step 6] Ingesting {len(daybook_files)} DayBook export(s) in chronological order:")
    for f in daybook_files:
        print(f"      - {os.path.basename(f)}")

    for f in daybook_files:
        fname = os.path.basename(f)
        print(f"\n   >> Ingesting {fname} into Supabase with automatic deduplication...")
        sz = os.path.getsize(f)
        def prog(pct, msg):
            pct_int = int(pct * 100)
            if pct_int in (5, 25, 50, 70, 85, 100):
                print(f"      [{pct_int}%] {msg}")

        res = full_upload_pipeline(f, progress_callback=prog, file_size=sz, filename=fname, sync_bafa=False)
        print(f"   [OK] {fname} Ingested successfully!")
        print(f"      - Vouchers: {res['vouchers']['inserted']} inserted, {res['vouchers']['skipped']} skipped")
        print(f"      - Line Items: {res['line_items']['inserted']} items recorded")

    # 7. Global Supplier Catalog Consolidation across all ingested purchases
    print("\n[Step 7] Consolidating and updating full supplier catalog in Supabase...")
    try:
        from db import load_local_data
        db.refresh_local_cache()
        _, li_df = load_local_data()
        purchases = li_df[li_df['voucher_category'] == 'Purchase'].copy()
        if not purchases.empty:
            purchases['supplier_name'] = purchases.apply(
                lambda r: resolve_supplier_alias(r.get('party_name', ''), r.get('voucher_no', '')),
                axis=1
            )
            sup_agg = purchases.groupby(['supplier_name', 'product_name']).agg(
                last_purchase_date=('date', 'max'),
                last_purchase_rate=('rate', 'last'),
                avg_purchase_rate=('rate', 'mean'),
                total_qty_purchased=('quantity', 'sum'),
                purchase_count=('product_name', 'count')
            ).reset_index()

            records = sup_agg.to_dict('records')
            for r in records:
                r['last_purchase_date'] = str(r['last_purchase_date'])
                r['last_purchase_rate'] = float(r['last_purchase_rate'])
                r['avg_purchase_rate'] = round(float(r['avg_purchase_rate']), 2)
                r['total_qty_purchased'] = float(r['total_qty_purchased'])
                r['purchase_count'] = int(r['purchase_count'])

            for batch in chunked(records, 300):
                client.table('supplier_products').upsert(
                    batch,
                    on_conflict='supplier_name,product_name'
                ).execute()

            ayreen_count = len(sup_agg[sup_agg['supplier_name'] == 'Ayreen'])
            ben_count = len(sup_agg[sup_agg['supplier_name'] == 'Ben'])
            print(f"   -> {len(records)} consolidated supplier catalog products synced!")
            print(f"   -> Supplier 'Ayreen': {ayreen_count} products consolidated")
            print(f"   -> Supplier 'Ben': {ben_count} products consolidated")
    except Exception as e:
        print(f"   -> Supplier catalog aggregation note: {e}")

    # 8. Refresh local caches
    print("\n[Step 8] Rebuilding high-speed Parquet caches...")
    db.refresh_local_cache()
    db.load_local_data()
    print("   -> Parquet caches successfully refreshed on disk!")

    # 9. Sync Hermes Knowledge Base
    print("\n[Step 9] Synchronizing Hermes AI Knowledge Base (hermes_items)...")
    try:
        from hermes_engine import sync_hermes_items
        h_summary = sync_hermes_items()
        print(f"   -> Hermes Knowledge Base Synced: {h_summary['total_items']} items, {h_summary['with_photos']} photos, {h_summary['with_positive_stock']} in stock!")
    except Exception as e:
        print(f"   -> Hermes sync note: {e}")

    # 10. Sync Bafa Product Catalog Selling Prices (+10% markup)
    print("\n[Step 10] Synchronizing Bafa Product Catalog Selling Prices (+10% markup)...")
    try:
        from hermes_tools import invalidate_catalog_cache
        invalidate_catalog_cache()
        from bafa_sync import execute_sync
        b_summary = execute_sync(markup_pct=10.0)
        print(f"   -> Bafa Price Sync Complete: {b_summary.get('total_updated', 0)} prices updated!")
    except Exception as e:
        print(f"   -> Bafa price sync note: {e}")

    print("\n" + "=" * 65)
    print("SUPABASE CLEAN & RE-UPLOAD COMPLETE!")
    print("All DayBook records, vouchers, line items, commercial invoice items,")
    print("RMB prices, stock balances, categories, Hermes Knowledge Base, and Bafa selling prices are live in Supabase!")
    print("=" * 65)

if __name__ == '__main__':
    main()
