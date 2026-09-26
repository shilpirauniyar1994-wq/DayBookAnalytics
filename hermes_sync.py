"""
Hermes Sync CLI Tool
Run manually or via scheduled tasks to synchronize product photos, tags,
live stock balances, and selling prices into the `hermes_items` table in our Primary DB.

Usage:
    python hermes_sync.py
"""

import sys
import time

# Ensure UTF-8 stdout/stderr on Windows to avoid charmap errors
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from hermes_engine import sync_hermes_items

def main():
    print("=" * 65)
    print(">> Hermes Knowledge Base -- Catalog & Ledger Synchronization")
    print("=" * 65)
    start_time = time.time()

    def progress(pct, msg):
        print(f"[{int(pct * 100):3d}%] {msg}")

    try:
        summary = sync_hermes_items(progress_callback=progress)
        elapsed = time.time() - start_time
        print("\n" + "=" * 65)
        print(">> Hermes Sync Completed Successfully in {:.1f}s!".format(elapsed))
        print("=" * 65)
        print(f"  • Total Products in Knowledge Base: {summary['total_items']:,}")
        print(f"  • Synchronized to Primary Supabase: {summary['inserted_or_updated']:,}")
        print(f"  • Products with Photos:            {summary['with_photos']:,}")
        print(f"  • Products with Tags:              {summary['with_tags']:,}")
        print(f"  • Products with Positive Stock:     {summary['with_positive_stock']:,}")
        print(f"  • Products with RMB Invoice Price: {summary['with_rmb_price']:,}")
        print(f"  • Sync Timestamp:                  {summary['synced_at']}")
        print("=" * 65)
    except Exception as e:
        print(f"\n[ERROR] Sync failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
