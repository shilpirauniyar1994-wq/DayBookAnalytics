"""
Bafa Sync & Rollback Engine — DayBook Analytics
Safely synchronizes wholesale sales prices with +10% markup into Bafa's Supabase database
(ktlzbplvxmpxzbbsxbid.supabase.co), with automated pre-sync snapshots and 1-click rollback.

Usage:
    python bafa_sync.py --preview           # Preview all matches & proposed prices (dry-run)
    python bafa_sync.py --snapshot          # Take full snapshot backup of Bafa prices
    python bafa_sync.py --sync              # Create snapshot + sync all prices with +10% markup
    python bafa_sync.py --rollback          # Revert all prices to the latest snapshot
    python bafa_sync.py --rollback <file>   # Revert to a specific snapshot file
"""

import os
import sys
import json
import time
import datetime
import threading
import concurrent.futures
from typing import Dict, List, Any, Optional, Callable, Tuple
import pandas as pd

from HermesData.catalog_reader import get_catalog_client, get_all_catalog_products
from hermes_tools import get_cached_catalog

SNAPSHOT_DIR = os.path.join("data", "bafa_snapshots")
DEFAULT_MARKUP_PERCENT = 10.0

def ensure_snapshot_dir():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)

def take_bafa_snapshot() -> str:
    """
    Downloads all current product records from Bafa's Supabase and saves
    a complete JSON backup snapshot before any modifications.
    Returns: filepath of the saved snapshot.
    """
    ensure_snapshot_dir()
    client = get_catalog_client()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_filename = f"bafa_snapshot_{timestamp}.json"
    snapshot_path = os.path.join(SNAPSHOT_DIR, snapshot_filename)
    latest_pointer = os.path.join(SNAPSHOT_DIR, "latest_snapshot.json")

    print(f"[Bafa Snapshot] Fetching full catalog from Bafa Supabase...")
    all_products = []
    offset = 0
    page_size = 1000

    while True:
        res = client.table("products").select("id, price, selling_price, image_url, tags").range(offset, offset + page_size - 1).execute()
        data = res.data or []
        if not data:
            break
        all_products.extend(data)
        if len(data) < page_size:
            break
        offset += page_size

    snapshot_payload = {
        "created_at": datetime.datetime.now().isoformat(),
        "total_products": len(all_products),
        "products": [
            {
                "id": p["id"],
                "price": p.get("price"),
                "selling_price": p.get("selling_price"),
                "image_url": p.get("image_url"),
                "tags": p.get("tags")
            }
            for p in all_products
        ]
    }

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, indent=2, ensure_ascii=False)

    # Save latest pointer
    with open(latest_pointer, "w", encoding="utf-8") as f:
        json.dump({"latest_snapshot_path": snapshot_path, "timestamp": timestamp}, f, indent=2)

    print(f"[Bafa Snapshot] Successfully saved {len(all_products)} product states to {snapshot_path}")
    return snapshot_path

def get_latest_snapshot_path() -> Optional[str]:
    """Finds the most recent snapshot file."""
    ensure_snapshot_dir()
    latest_pointer = os.path.join(SNAPSHOT_DIR, "latest_snapshot.json")
    if os.path.exists(latest_pointer):
        try:
            with open(latest_pointer, "r", encoding="utf-8") as f:
                data = json.load(f)
                p = data.get("latest_snapshot_path")
                if p and os.path.exists(p):
                    return p
        except Exception:
            pass

    # Fallback: find highest timestamp in filename
    files = sorted([
        f for f in os.listdir(SNAPSHOT_DIR) 
        if f.startswith("bafa_snapshot_") and f.endswith(".json")
    ])
    if files:
        return os.path.join(SNAPSHOT_DIR, files[-1])
    return None

def calculate_bafa_prices(markup_pct: float = DEFAULT_MARKUP_PERCENT) -> List[Dict[str, Any]]:
    """
    Matches Bafa products against DayBook's calculated wholesale rates,
    applying the markup formula: round(wholesale_price * (1 + markup_pct / 100)).
    """
    bafa_df = get_all_catalog_products()
    daybook_items = get_cached_catalog()

    daybook_map = {
        it["product_name"]: it 
        for it in daybook_items 
        if it.get("selling_price") and it["selling_price"] > 0
    }

    planned_updates = []
    multiplier = 1.0 + (markup_pct / 100.0)

    for _, row in bafa_df.iterrows():
        p_name = str(row["product_name"]).strip()
        if p_name in daybook_map:
            db_item = daybook_map[p_name]
            wholesale_rate = float(db_item["selling_price"])
            marked_up_price = int(round(wholesale_rate * multiplier))
            curr_bafa_sp = row.get("selling_price")
            curr_bafa_sp_str = str(curr_bafa_sp).strip() if curr_bafa_sp is not None else ""

            needs_update = curr_bafa_sp_str != str(marked_up_price)

            planned_updates.append({
                "id": p_name,
                "bafa_catalog_price": row.get("catalog_price"),
                "current_bafa_selling_price": curr_bafa_sp,
                "daybook_wholesale_price": round(wholesale_rate, 2),
                "proposed_selling_price": str(marked_up_price),
                "current_stock": db_item.get("current_stock"),
                "has_photo": bool(row.get("image_url")),
                "needs_update": needs_update
            })

    return planned_updates

def preview_sync(markup_pct: float = DEFAULT_MARKUP_PERCENT):
    """Prints a clear preview dry-run report without modifying any data."""
    updates = calculate_bafa_prices(markup_pct)
    total_matched = len(updates)
    need_change = [u for u in updates if u["needs_update"]]

    print(f"\n=======================================================")
    print(f" BAFA PRICE SYNC PREVIEW (Markup: +{markup_pct}%)")
    print(f"=======================================================")
    print(f"Total Products in Bafa:             {len(get_all_catalog_products()):,}")
    print(f"Exact Matches in DayBook Catalog:   {total_matched:,}")
    print(f"Items Requiring Price Update:       {len(need_change):,}")
    print(f"Items Already Matching Formula:     {total_matched - len(need_change):,}")
    print(f"-------------------------------------------------------")
    print(f"Sample 10 Proposed Price Updates:")
    print(f"{'Product ID':<30} | {'Wholesale':>10} | {'Bafa (+10%)':>12} | {'Current Bafa':>12} | {'Stock':>6}")
    print(f"-" * 78)
    for u in updates[:10]:
        print(f"{u['id'][:30]:<30} | Rs.{u['daybook_wholesale_price']:>7.2f} | Rs.{u['proposed_selling_price']:>9} | {str(u['current_bafa_selling_price'] or 'None'):>12} | {int(u['current_stock'] or 0):>6}")
    print(f"=======================================================\n")
    return updates

def execute_sync(
    markup_pct: float = DEFAULT_MARKUP_PERCENT,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, Any]:
    """
    Executes a safe batch update of Bafa's products.selling_price:
    1. Creates a complete timestamped snapshot first.
    2. Updates matching items whose prices differ.
    3. Guarantees other columns (price, image_url, tags) remain untouched.
    """
    # 1. Take snapshot
    snapshot_path = take_bafa_snapshot()

    # 2. Calculate updates
    client = get_catalog_client()
    updates = calculate_bafa_prices(markup_pct)
    to_update = [u for u in updates if u["needs_update"]]

    total = len(to_update)
    print(f"[Bafa Sync] Found {total} products needing price update in Bafa.")

    import concurrent.futures
    import threading

    updated_count = 0
    failed_count = 0
    errors = []
    lock = threading.Lock()
    processed_count = 0

    def update_single_item(item):
        nonlocal updated_count, failed_count, processed_count
        item_id = item["id"]
        new_sp = item["proposed_selling_price"]
        success = False
        err_msg = None

        for attempt in range(3):
            try:
                res = client.table("products").update({"selling_price": new_sp}).eq("id", item_id).execute()
                if res.data:
                    success = True
                    break
                else:
                    err_msg = f"{item_id}: No row updated"
            except Exception as e:
                err_msg = f"{item_id}: {str(e)}"
                time.sleep(0.5 * (attempt + 1))
            time.sleep(0.05)

        with lock:
            processed_count += 1
            curr_idx = processed_count
            if success:
                updated_count += 1
            else:
                failed_count += 1
                if err_msg:
                    errors.append(err_msg)

        if progress_callback:
            progress_callback(curr_idx, total, item_id)
        elif curr_idx % 100 == 0 or curr_idx == total:
            print(f"[Bafa Sync] Progress: {curr_idx}/{total} (Updated: {updated_count}, Failed: {failed_count})")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(update_single_item, to_update))

    summary = {
        "status": "success" if failed_count == 0 else "partial",
        "snapshot_path": snapshot_path,
        "total_matched": len(updates),
        "total_updated": updated_count,
        "failed_count": failed_count,
        "errors": errors[:10]
    }
    print(f"\n[Bafa Sync Complete] Updated: {updated_count:,} items. Snapshot saved to {snapshot_path}")
    return summary

def rollback_bafa_prices(
    snapshot_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Dict[str, Any]:
    """
    Rolls back Bafa's products.selling_price to the exact previous state
    recorded in the snapshot file.
    """
    target_snapshot = snapshot_path or get_latest_snapshot_path()
    if not target_snapshot or not os.path.exists(target_snapshot):
        raise FileNotFoundError("No valid snapshot file found to rollback from!")

    print(f"[Bafa Rollback] Reading snapshot: {target_snapshot}...")
    with open(target_snapshot, "r", encoding="utf-8") as f:
        snapshot_data = json.load(f)

    products = snapshot_data.get("products", [])
    total = len(products)
    client = get_catalog_client()

    print(f"[Bafa Rollback] Restoring {total} products to snapshot values...")
    reverted_count = 0
    failed_count = 0
    processed_count = 0
    lock = threading.Lock()

    def revert_single_item(item):
        nonlocal reverted_count, failed_count, processed_count
        item_id = item["id"]
        orig_sp = item.get("selling_price")
        success = False

        for attempt in range(3):
            try:
                client.table("products").update({"selling_price": orig_sp}).eq("id", item_id).execute()
                success = True
                break
            except Exception as e:
                time.sleep(0.5 * (attempt + 1))
            time.sleep(0.05)

        with lock:
            processed_count += 1
            curr_idx = processed_count
            if success:
                reverted_count += 1
            else:
                failed_count += 1

        if progress_callback:
            progress_callback(curr_idx, total, item_id)
        elif curr_idx % 100 == 0 or curr_idx == total:
            print(f"[Bafa Rollback] Progress: {curr_idx}/{total} (Reverted: {reverted_count})")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(revert_single_item, products))

    print(f"\n[Bafa Rollback Complete] Restored {reverted_count:,} products to previous state from {target_snapshot}")
    return {
        "status": "success",
        "reverted_count": reverted_count,
        "failed_count": failed_count,
        "snapshot_used": target_snapshot
    }

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--preview" in args or not args:
        preview_sync(DEFAULT_MARKUP_PERCENT)
    elif "--snapshot" in args:
        take_bafa_snapshot()
    elif "--sync" in args:
        execute_sync(DEFAULT_MARKUP_PERCENT)
    elif "--rollback" in args:
        custom_snap = None
        for a in args:
            if a.endswith(".json") and os.path.exists(a):
                custom_snap = a
        rollback_bafa_prices(custom_snap)
    else:
        print("Unknown arguments. Available flags: --preview, --snapshot, --sync, --rollback")
