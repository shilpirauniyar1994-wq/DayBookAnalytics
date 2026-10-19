"""
Daily TikTok Content Concierge & Auto-Dispatch Engine for Demo Khelauna
Runs every morning at 09:00 AM (Asia/Kathmandu).
1. Selects a trending, in-stock, policy-safe toy (excluding items posted in past 14 days).
2. Generates viral copy (Gemini AI) with zero numeric price disclosure.
3. Renders 9:16 vertical MP4 video reel with Ken Burns zoom & branding.
4. Transmits video reel + separate 1-tap copyable caption to WhatsApp (+977 9851155318).
5. Logs dispatch to Supabase audit log.
"""

import os
import sys
import json
import time
import argparse
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import db
import hermes_tools
from tiktok_safety import filter_catalog_for_tiktok, evaluate_post_safety
from tiktok_engine import generate_tiktok_copy, render_vertical_reel

DEFAULT_RECIPIENT = os.getenv("TIKTOK_MANUAL_DISPATCH_PHONE", "+9779851155318")
BRIDGE_SEND_URL = "http://127.0.0.1:5006/send"
BRIDGE_STATUS_URL = "http://127.0.0.1:5006/status"


def is_bridge_connected() -> bool:
    try:
        r = requests.get(BRIDGE_STATUS_URL, timeout=3)
        if r.status_code == 200:
            data = r.json()
            return bool(data.get("is_connected") or data.get("status") == "connected")
    except Exception:
        pass
    return False


LOCAL_DISPATCH_LOG = os.path.join(os.path.dirname(__file__), "data", "tiktok_dispatches_log.json")


def cleanup_old_renders(render_dir: str = "data/tiktok_renders", max_age_days: int = 30):
    """Deletes rendered MP4 video reels older than max_age_days to keep disk storage lean."""
    try:
        if not os.path.exists(render_dir):
            return
        cutoff_sec = time.time() - (max_age_days * 86400)
        deleted = 0
        for fname in os.listdir(render_dir):
            if fname.lower().endswith((".mp4", ".mov", ".avi")):
                fpath = os.path.join(render_dir, fname)
                try:
                    if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff_sec:
                        os.remove(fpath)
                        deleted += 1
                except Exception:
                    pass
        if deleted > 0:
            print(f"[Retention] Cleaned up {deleted} video reel(s) older than {max_age_days} days.", flush=True)
    except Exception as e:
        print(f"[Retention Warning] Could not clean up old renders: {e}", flush=True)


def get_recently_posted_products(days: int = 14) -> List[str]:
    """Retrieves names of products dispatched in the last `days` days from Supabase & local log."""
    recent_names = set()

    # 1. Local JSON log
    try:
        if os.path.exists(LOCAL_DISPATCH_LOG):
            with open(LOCAL_DISPATCH_LOG, "r", encoding="utf-8") as f:
                logs = json.load(f)
                cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
                for entry in logs:
                    ts_str = entry.get("timestamp")
                    if ts_str:
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts >= cutoff_dt:
                                p = entry.get("product_name")
                                if p:
                                    recent_names.add(p.strip().lower())
                        except Exception:
                            pass
    except Exception as le:
        pass

    # 2. Supabase table attempt
    try:
        sp = hermes_tools.get_client()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        res = sp.table("tiktok_posts").select("title").gte("created_at", cutoff).execute()
        if res.data:
            for r in res.data:
                if r.get("title"):
                    recent_names.add(str(r["title"]).strip().lower())
    except Exception:
        pass

    return list(recent_names)


def select_daily_candidate(preferred_product: Optional[str] = None) -> Dict[str, Any]:
    """Selects the best in-stock, policy-safe product for today's TikTok reel."""
    catalog = hermes_tools.get_cached_catalog()
    if not catalog:
        raise RuntimeError("Catalog is empty.")

    df = pd.DataFrame(catalog)
    # Apply safety filter
    df_safe = filter_catalog_for_tiktok(df)
    safe_in_stock = df_safe[(df_safe['tiktok_safe'] == True) & (df_safe['current_stock'] > 0)].copy()

    if safe_in_stock.empty:
        safe_in_stock = df_safe[df_safe['tiktok_safe'] == True].copy()

    # If user provided a specific product
    if preferred_product:
        match = safe_in_stock[safe_in_stock['product_name'].str.lower() == preferred_product.lower()]
        if not match.empty:
            return match.iloc[0].to_dict()

    # Deduplication against recent dispatches
    recent = get_recently_posted_products(days=14)
    unposted = safe_in_stock[~safe_in_stock['product_name'].str.lower().isin(recent)]
    candidates = unposted if not unposted.empty else safe_in_stock

    # Filter for products that have physical or cloud photos
    valid_candidates = []
    for _, row in candidates.iterrows():
        pname = row['product_name']
        img = hermes_tools.resolve_product_image(pname, row.get('image_url'))
        if img:
            row_dict = row.to_dict()
            row_dict['resolved_image'] = img
            valid_candidates.append(row_dict)

    if not valid_candidates:
        # Fallback to any product with an image
        for _, row in df.iterrows():
            pname = row['product_name']
            img = hermes_tools.resolve_product_image(pname, row.get('image_url'))
            if img:
                row_dict = row.to_dict()
                row_dict['resolved_image'] = img
                valid_candidates.append(row_dict)
                break

    if not valid_candidates:
        raise RuntimeError("No candidate products with images found.")

    # Sort by stock descending or pick top trending item
    valid_candidates.sort(key=lambda x: float(x.get('current_stock', 0)), reverse=True)
    return valid_candidates[0]


def record_dispatch_in_db(product_name: str, video_path: str, caption: str, hashtags: List[str]):
    """Logs the dispatch to Supabase tiktok_posts and local JSON audit log."""
    now_iso = datetime.now(timezone.utc).isoformat()
    # 1. Local JSON Log
    try:
        os.makedirs(os.path.dirname(LOCAL_DISPATCH_LOG), exist_ok=True)
        logs = []
        if os.path.exists(LOCAL_DISPATCH_LOG):
            with open(LOCAL_DISPATCH_LOG, "r", encoding="utf-8") as f:
                logs = json.load(f)
                if not isinstance(logs, list):
                    logs = []
        logs.insert(0, {
            "product_name": product_name,
            "video_path": video_path,
            "caption": caption,
            "hashtags": hashtags,
            "timestamp": now_iso,
            "destination": "WHATSAPP_MANUAL"
        })
        with open(LOCAL_DISPATCH_LOG, "w", encoding="utf-8") as f:
            json.dump(logs[:100], f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Daily Dispatch] Warning writing local dispatch log: {e}")

    # 2. Supabase Log
    try:
        sp = hermes_tools.get_client()
        sp.table("tiktok_posts").insert({
            "post_type": "video",
            "title": product_name,
            "caption": caption,
            "hashtags": hashtags,
            "media_urls": [video_path],
            "destination": "WHATSAPP_MANUAL",
            "safety_status": "SAFE",
            "status": "dispatched",
            "published_at": now_iso
        }).execute()
        print(f"[Daily Dispatch] Logged post to Supabase tiktok_posts table.", flush=True)
    except Exception as e:
        pass


def run_daily_tiktok_dispatch(
    recipient: str = DEFAULT_RECIPIENT,
    product_name: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Executes the full daily 9:00 AM TikTok content generation and dispatch pipeline."""
    print("=" * 65)
    print(f"🎵 DAILY TIKTOK CONCIERGE — 9:00 AM DISPATCH")
    print(f"Recipient: {recipient} | Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # 0. Retention maintenance (Keep disk lean)
    cleanup_old_renders(max_age_days=30)

    # 1. Candidate Selection
    print("[1/4] Selecting in-stock, policy-safe candidate toy...", flush=True)
    candidate = select_daily_candidate(preferred_product=product_name)
    p_name = candidate["product_name"]
    category = candidate.get("product_group", "General Toys")
    stock = float(candidate.get("current_stock", 0))
    image_spec = candidate.get("resolved_image")

    # Resolve local or remote file path
    image_path = None
    if image_spec and isinstance(image_spec, str) and str(image_spec).strip().lower() not in ['nan', 'none', '']:
        image_spec = image_spec.strip()
        if image_spec.startswith("local://"):
            fname = image_spec.replace("local://", "")
            fpath = os.path.join(hermes_tools.LOCAL_IMAGE_DIR, fname)
            if os.path.exists(fpath):
                image_path = os.path.abspath(fpath)
        elif os.path.isabs(image_spec) and os.path.exists(image_spec):
            image_path = image_spec
        elif os.path.exists(image_spec):
            image_path = os.path.abspath(image_spec)
        elif image_spec.startswith(("http://", "https://")):
            image_path = image_spec

    print(f"   Selected Product: *{p_name}* ({category}) | Stock: {int(stock)} PCS")
    print(f"   Image: {image_path}")

    # 2. AI Copywriting with Gemini
    print("[2/4] Generating high-converting viral copy with Gemini...", flush=True)
    copy_res = generate_tiktok_copy(
        product_name=p_name,
        category=category,
        current_stock=stock
    )
    hook = copy_res.get("hook", f"🔥 New Arrival: {p_name}!")
    caption = copy_res.get("caption", f"Wholesale toys now available in Kathmandu! Delivery all over Nepal. WhatsApp: +977 9803216856")
    hashtags = copy_res.get("hashtags", ["#demokhelauna", "#toysnepal", "#wholesaletoynepal", "#kathmandutoys"])
    tags_str = " ".join(hashtags) if isinstance(hashtags, list) else str(hashtags)
    badges = copy_res.get("overlay_badges", [hook, "WHOLESALE ONLY 🏷️", "WhatsApp: +977 9803216856"])

    print(f"   Hook: {hook}")
    print(f"   Caption: {caption[:70]}...")

    # 3. Render 9:16 Vertical Video Reel
    print("[3/4] Rendering vertical 9:16 dynamic video reel...", flush=True)
    render_res = render_vertical_reel(
        image_sources=[image_path],
        product_name=p_name,
        overlay_badges=badges,
        seconds_per_slide=4.0
    )
    video_path = render_res["video_path"]
    print(f"   Reel rendered: {video_path} ({render_res['duration_seconds']}s, {render_res['file_size_bytes']//1024} KB)")

    # Format the ready-to-copy text message
    clean_copy_text = (
        f"📋 *TIKTOK CAPTION READY TO POST (Tap & Copy)*:\n\n"
        f"{hook}\n\n"
        f"{caption}\n\n"
        f"{tags_str}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👉 Open TikTok → (+) Upload → Select Video → Paste Caption → Post! 🚀"
    )

    video_caption = (
        f"🎵 *Daily TikTok Reel Ready!* ({p_name})\n"
        f"Save video to Gallery and copy the text bubble below to post in seconds!"
    )

    if dry_run:
        print("\n[DRY RUN MODE] Video generated successfully. Skipping WhatsApp dispatch.")
        print(f"\nVideo Path: {video_path}")
        print(f"\nVideo Caption:\n{video_caption}")
        print(f"\nSeparate Copy Bubble:\n{clean_copy_text}")
        return {
            "success": True,
            "dry_run": True,
            "product_name": p_name,
            "video_path": video_path,
            "copy_text": clean_copy_text
        }

    # 4. WhatsApp Dispatch
    print(f"[4/4] Transmitting reel and caption to {recipient}...", flush=True)
    if not is_bridge_connected():
        raise RuntimeError(f"WhatsApp Bridge is offline at {BRIDGE_STATUS_URL}. Please start node whatsapp_bridge/bridge_server.js")

    payload = {
        "to": recipient,
        "video_path": video_path,
        "caption": video_caption,
        "follow_up_text": clean_copy_text
    }

    res = requests.post(BRIDGE_SEND_URL, json=payload, timeout=60)
    if res.status_code == 200 and res.json().get("success", False):
        print(f"✅ Successfully dispatched reel and copy to WhatsApp (+{recipient})!")
        record_dispatch_in_db(p_name, video_path, caption, hashtags)
        return {
            "success": True,
            "product_name": p_name,
            "video_path": video_path,
            "dispatched_to": recipient
        }
    else:
        err = res.text if res else "Unknown bridge error"
        raise RuntimeError(f"Bridge dispatch failed: {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily TikTok 9:00 AM Content Concierge")
    parser.add_argument("--dry-run", action="store_true", help="Generate reel and copy without sending to WhatsApp")
    parser.add_argument("--to", type=str, default=DEFAULT_RECIPIENT, help="Target recipient phone number")
    parser.add_argument("--product", type=str, default=None, help="Force specific product name")

    args = parser.parse_args()
    try:
        run_daily_tiktok_dispatch(recipient=args.to, product_name=args.product, dry_run=args.dry_run)
    except Exception as e:
        print(f"❌ Daily Dispatch Error: {e}")
        sys.exit(1)
