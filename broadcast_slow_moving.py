"""
Broadcast Slow-Moving Inventory Pack (50 Products Across 5 Categories)
Picks 10 top slow-moving items with verified high-res photos from:
  1. General (#01 - #10)
  2. Big Toys (#11 - #20)
  3. Fancy Toys (#21 - #30)
  4. Indian Item (#31 - #40)
  5. Birthday Items (#41 - #50)

Enforces strict data separation:
  - Bubble A (Photo Message): Customer-Safe (Item #, Product Name, Category, Wholesale CTA) -> NO stock, NO cost!
  - Bubble B (Separate Text): Confidential Owner Reference (Cost Price, Available Stock, Selling Price, Margin)
Dispatches to WhatsApp (+977 9851155318) via local Baileys bridge on http://127.0.0.1:5006/send.
"""

import os
import sys
import json
import time
import argparse
import requests
import pandas as pd
from typing import List, Dict, Any, Optional

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import db
import po_engine
import hermes_tools
from stksum_parser import OFFICIAL_CATEGORIES

DEFAULT_RECIPIENT = os.getenv("TIKTOK_MANUAL_DISPATCH_PHONE", "+9779851155318")
BRIDGE_SEND_URL = "http://127.0.0.1:5006/send"
BRIDGE_STATUS_URL = "http://127.0.0.1:5006/status"

TARGET_CATEGORIES = [
    ("General", "General"),
    ("Big Toys", "Big Toys"),
    ("Fancy Toys", "Fancy Toys"),
    ("Indian Item", "Indian Item"),
    ("Birthday Items", "Birthday Items")
]


def resolve_local_or_remote_image(image_spec: Optional[str]) -> Optional[str]:
    """Resolves local:// or relative paths to absolute filesystem path or returns HTTP URL."""
    if not image_spec or not isinstance(image_spec, str) or str(image_spec).strip().lower() in ['nan', 'none', '']:
        return None
    image_spec = image_spec.strip()
    if image_spec.startswith("local://"):
        fname = image_spec.replace("local://", "")
        fpath = os.path.join(hermes_tools.LOCAL_IMAGE_DIR, fname)
        if os.path.exists(fpath):
            return os.path.abspath(fpath)
    elif os.path.isabs(image_spec) and os.path.exists(image_spec):
        return image_spec
    elif os.path.exists(image_spec):
        return os.path.abspath(image_spec)
    elif image_spec.startswith(("http://", "https://")):
        return image_spec
    return None


def get_slow_moving_broadcast_items(items_per_category: int = 10) -> List[Dict[str, Any]]:
    """
    Computes stock aging and extracts `items_per_category` slow-moving items with verified photos
    for each target category, enriched with cost price, current stock, and wholesale selling price.
    """
    print("[Broadcast Engine] Calculating inventory aging across DayBook catalog...", flush=True)
    li_df = db.get_line_items_df()
    if li_df.empty:
        raise RuntimeError("No line items found in database.")

    aging_df = po_engine.calculate_aging(li_df)
    if aging_df.empty:
        raise RuntimeError("Could not calculate aging metrics.")

    # Load catalog prices
    catalog_items = hermes_tools.get_cached_catalog()
    catalog_price_map = {}
    for item in catalog_items:
        p_name = item.get("product_name")
        sp = item.get("selling_price") or item.get("catalog_price")
        if p_name and sp is not None:
            catalog_price_map[p_name] = float(sp)

    all_selected = []
    item_counter = 1

    for cat_key, cat_name in TARGET_CATEGORIES:
        subset = aging_df[(aging_df['product_group'] == cat_name) & (aging_df['est_stock'] > 0)]
        # Sort by days_since_sale descending (never sold / oldest first), then by est_stock descending
        sorted_sub = subset.sort_values(by=['days_since_sale', 'est_stock'], ascending=[False, False])

        cat_items = []
        for _, row in sorted_sub.iterrows():
            p_name = str(row['product_name']).strip()
            raw_img = hermes_tools.resolve_product_image(p_name, None)
            resolved_img = resolve_local_or_remote_image(raw_img)

            if resolved_img:
                cat_items.append({
                    "item_index": item_counter,
                    "product_name": p_name,
                    "category": cat_name,
                    "est_stock": float(row['est_stock']),
                    "days_since_sale": int(row['days_since_sale']),
                    "aging_bucket": str(row.get('aging_bucket', 'Unknown')),
                    "image_path": resolved_img
                })
                item_counter += 1
                if len(cat_items) >= items_per_category:
                    break

        all_selected.extend(cat_items)
        print(f"  [+] {cat_name}: Selected {len(cat_items)} items with verified photos", flush=True)

    # Batch enrich purchase cost
    product_names = [it["product_name"] for it in all_selected]
    costs = hermes_tools.get_purchase_cost_for_products(product_names)

    for it in all_selected:
        p_name = it["product_name"]
        c_info = costs.get(p_name, {})
        cost_price = c_info.get("cost_price")
        last_supplier = c_info.get("last_supplier") or "Direct Import / Central Godown"
        selling_price = catalog_price_map.get(p_name)

        # Fallback pricing calculation if not explicitly set in catalog
        if selling_price is None or selling_price <= 0:
            if cost_price and cost_price > 0:
                selling_price = round(cost_price * 1.35, 2)
            else:
                selling_price = 0.0

        margin = round(selling_price - cost_price, 2) if (cost_price and selling_price) else 0.0
        margin_pct = round((margin / cost_price) * 100, 1) if (cost_price and cost_price > 0) else 0.0

        it["cost_price"] = cost_price
        it["selling_price"] = selling_price
        it["margin"] = margin
        it["margin_pct"] = margin_pct
        it["last_supplier"] = last_supplier

        # Format Customer-Safe Photo Caption (Bubble A) - STRICTLY NO STOCK, NO COST
        it["photo_caption"] = (
            f"📸 [{it['category']} | Item #{it['item_index']:02d}/50]\n"
            f"*{it['product_name']}*\n"
            f"💬 Wholesale Carton Inquiries & Booking:\n"
            f"👉 WhatsApp: +977 9803216856"
        )

        # Format Confidential Reference Text (Bubble B) - Private Owner Metrics
        stock_str = f"{int(round(it['est_stock']))} PCS"
        cost_str = f"Rs. {cost_price:,.2f}" if cost_price else "Inquire Invoice"
        selling_str = f"Rs. {selling_price:,.2f}" if selling_price else "Call for Quote"
        margin_str = f"Rs. {margin:,.2f} ({margin_pct}%)" if margin > 0 else "N/A"
        days_str = "Never Sold" if it['days_since_sale'] >= 9999 else f"{it['days_since_sale']} Days Unsold"

        it["private_text"] = (
            f"📊 *CONFIDENTIAL REFERENCE — Item #{it['item_index']:02d}*\n"
            f"📦 Product: *{it['product_name']}*\n"
            f"📂 Category: {it['category']}\n"
            f"💰 Purchase Cost: {cost_str}\n"
            f"🏷️ Wholesale Selling Rate: {selling_str}\n"
            f"📈 Unit Profit Margin: {margin_str}\n"
            f"📦 Current Available Stock: {stock_str}\n"
            f"⏳ Movement Status: {days_str}\n"
            f"🏢 Supplier: {last_supplier}"
        )

    return all_selected


def is_bridge_connected() -> bool:
    """Checks if Baileys bridge HTTP API is reachable and connected to WhatsApp."""
    try:
        r = requests.get(BRIDGE_STATUS_URL, timeout=3)
        if r.status_code == 200:
            data = r.json()
            return bool(data.get("is_connected") or data.get("status") == "connected")
    except Exception:
        pass
    return False


def dispatch_item_to_whatsapp(to_phone: str, item: Dict[str, Any]) -> bool:
    """Dispatches Bubble A (Photo) and Bubble B (Confidential Text) via WhatsApp Bridge."""
    payload = {
        "to": to_phone,
        "image_path": item["image_path"],
        "caption": item["photo_caption"],
        "follow_up_text": item["private_text"]
    }
    try:
        res = requests.post(BRIDGE_SEND_URL, json=payload, timeout=30)
        return res.status_code == 200 and res.json().get("success", False)
    except Exception as e:
        print(f"   [Error] Dispatch failed for Item #{item['item_index']}: {e}", flush=True)
        return False


def send_broadcast_pack(recipient: str = DEFAULT_RECIPIENT, category_filter: Optional[str] = None):
    """Executes full transmission of the 50 slow-moving items in category batches."""
    print("=" * 65)
    print(f"🚀 DEMO KHELAUNA — SLOW-MOVING INVENTORY BROADCAST DISPATCH")
    print(f"Recipient: {recipient}")
    print("=" * 65)

    items = get_slow_moving_broadcast_items(items_per_category=10)
    if category_filter:
        items = [it for it in items if it["category"].lower() == category_filter.lower()]
        print(f"Filtered for category '{category_filter}': {len(items)} items.")

    if not items:
        print("No items found to broadcast.")
        return

    # Check WhatsApp bridge
    if not is_bridge_connected():
        print(f"\n⚠️ WARNING: WhatsApp Bridge is not online or not connected at {BRIDGE_STATUS_URL}.")
        print("Please ensure the bridge is running (node whatsapp_bridge/bridge_server.js) and paired.")
        return

    print(f"\nConnected to WhatsApp Bridge! Beginning transmission of {len(items)} items...\n")

    current_cat = None
    success_count = 0

    for it in items:
        # Category announcement header
        if it["category"] != current_cat:
            current_cat = it["category"]
            cat_header = f"🚀 *CATEGORY BATCH: {current_cat.upper()}* (10 Items)\n━━━━━━━━━━━━━━━━━━━━"
            try:
                requests.post(BRIDGE_SEND_URL, json={"to": recipient, "text": cat_header}, timeout=15)
                time.sleep(1.0)
            except Exception:
                pass

        print(f"▶ Sending Item #{it['item_index']:02d}: {it['product_name']} ({it['category']})...", end="", flush=True)
        ok = dispatch_item_to_whatsapp(recipient, it)
        if ok:
            print(" ✅ Delivered (Photo + Private Reference)")
            success_count += 1
        else:
            print(" ❌ Failed")

        # Pacing to prevent WhatsApp rate throttling
        time.sleep(2.5)

    print("\n" + "=" * 65)
    print(f"🎉 BROADCAST COMPLETE: {success_count}/{len(items)} items delivered to {recipient}!")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slow-Moving Inventory Broadcast Pack")
    parser.add_argument("--preview", action="store_true", help="Preview items and messages without sending")
    parser.add_argument("--send", action="store_true", help="Send items directly to WhatsApp")
    parser.add_argument("--to", type=str, default=DEFAULT_RECIPIENT, help="Target recipient phone number")
    parser.add_argument("--category", type=str, default=None, help="Specific category filter")

    args = parser.parse_args()

    if args.send:
        send_broadcast_pack(recipient=args.to, category_filter=args.category)
    else:
        # Default to preview
        items = get_slow_moving_broadcast_items(items_per_category=10)
        if args.category:
            items = [it for it in items if it["category"].lower() == args.category.lower()]

        print("\n" + "=" * 80)
        print(f"📋 PREVIEW: 50 SLOW-MOVING BROADCAST ITEMS")
        print("=" * 80)
        for it in items:
            print(f"\n--- Item #{it['item_index']:02d} [{it['category']}] ---")
            print(f"Product: {it['product_name']}")
            print(f"Photo: {it['image_path']}")
            print(f"\n[BUBBLE A (Customer Safe Photo Caption)]:\n{it['photo_caption']}")
            print(f"\n[BUBBLE B (Confidential Private Reference Text)]:\n{it['private_text']}")
            print("-" * 50)
        print(f"\nTotal previewed: {len(items)} items across 5 categories.")
        print("Run with '--send' to dispatch these to WhatsApp.")
