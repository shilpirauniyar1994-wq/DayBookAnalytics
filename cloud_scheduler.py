"""
24/7 Cloud Background Scheduler for DayBook Analytics (Runs on Railway)
Fires daily automated WhatsApp dispatches at 09:00 AM (Asia/Kathmandu, UTC+05:45).
Supports:
  - Slow-Moving Inventory Photos Broadcast Pack (broadcast_slow_moving.py)
  - Daily TikTok Video Reel Concierge (daily_tiktok_dispatch.py)
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="[Cloud Scheduler %(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("cloud_scheduler")

# Kathmandu Timezone (UTC +05:45)
KATHMANDU_TZ = timezone(timedelta(hours=5, minutes=45))

TARGET_PHONE = os.getenv("TIKTOK_MANUAL_DISPATCH_PHONE", "+9779851155318")
DISPATCH_TIME = os.getenv("DAILY_DISPATCH_TIME", "09:00")  # HH:MM format
DISPATCH_WINDOW_END = os.getenv("DAILY_DISPATCH_WINDOW_END", "11:00")  # Morning catch-up window end
DISPATCH_MODE = os.getenv("DAILY_DISPATCH_MODE", "photos")  # "photos", "video", or "both"
ITEMS_PER_GROUP = int(os.getenv("BROADCAST_ITEMS_PER_GROUP", "5"))  # 5 items per group default
FLAG_FILE = os.path.join(os.path.dirname(__file__), "data", "trigger_broadcast.flag")
STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "last_cloud_dispatch.json")


def is_bridge_ready() -> bool:
    """Checks if Baileys bridge is connected to WhatsApp on localhost:5006."""
    import requests
    try:
        r = requests.get("http://127.0.0.1:5006/status", timeout=5)
        if r.status_code == 200:
            data = r.json()
            return bool(data.get("is_connected") or data.get("status") == "connected")
    except Exception:
        pass
    return False


def load_last_dispatch_date() -> Optional[str]:
    """Loads the last successful dispatch date from disk to prevent duplicate sends across restarts."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_dispatched_date")
    except Exception as e:
        logger.warning(f"Could not read dispatch state file: {e}")
    return None


def record_dispatch_success(date_str: str):
    """Persists successful dispatch date to disk."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "last_dispatched_date": date_str,
                "dispatched_at": datetime.now(KATHMANDU_TZ).isoformat(),
                "mode": DISPATCH_MODE,
                "target_phone": TARGET_PHONE,
                "items_per_group": ITEMS_PER_GROUP
            }, f, indent=2)
        logger.info(f"💾 Persisted dispatch state for {date_str} to {STATE_FILE}")
    except Exception as e:
        logger.warning(f"Could not persist dispatch state: {e}")


def execute_daily_dispatch() -> bool:
    """Runs the selected daily dispatch (Photos pack, TikTok video reel, or both)."""
    logger.info(f"🚀 Triggering daily dispatch (Mode: {DISPATCH_MODE}) to {TARGET_PHONE}...")
    any_success = False

    # 1. Slow-Moving Photos Broadcast Pack
    if DISPATCH_MODE in ["photos", "both"]:
        try:
            logger.info(f"Starting Slow-Moving Photos Broadcast Pack dispatch ({ITEMS_PER_GROUP} items per group = {ITEMS_PER_GROUP * 5} total)...")
            import broadcast_slow_moving
            broadcast_slow_moving.send_broadcast_pack(recipient=TARGET_PHONE, items_per_category=ITEMS_PER_GROUP)
            logger.info(f"✅ Slow-Moving Photos Broadcast Pack ({ITEMS_PER_GROUP} per group) dispatched successfully!")
            any_success = True
        except Exception as e:
            logger.error(f"❌ Failed to dispatch Photos Broadcast Pack: {e}", exc_info=True)

    # 2. Daily TikTok Video Reel Concierge
    if DISPATCH_MODE in ["video", "both"]:
        try:
            logger.info("Starting Daily TikTok Video Reel Concierge dispatch...")
            import daily_tiktok_dispatch
            res = daily_tiktok_dispatch.run_daily_tiktok_dispatch(recipient=TARGET_PHONE)
            logger.info(f"✅ Daily TikTok Video Reel dispatched: {res.get('product_name')}")
            any_success = True
        except Exception as e:
            logger.error(f"❌ Failed to dispatch Daily TikTok Reel: {e}", exc_info=True)

    return any_success


def scheduler_loop():
    """Main continuous scheduler loop."""
    logger.info("=======================================================")
    logger.info("⏰ DayBook Analytics 24/7 Cloud Scheduler Started")
    logger.info(f"   Target Phone : {TARGET_PHONE}")
    logger.info(f"   Window       : {DISPATCH_TIME} - {DISPATCH_WINDOW_END} (Asia/Kathmandu)")
    logger.info(f"   Mode         : {DISPATCH_MODE}")
    logger.info(f"   Items/Group  : {ITEMS_PER_GROUP} items (Total: {ITEMS_PER_GROUP * 5})")
    logger.info("=======================================================")

    last_dispatched_date: Optional[str] = load_last_dispatch_date()
    if last_dispatched_date:
        logger.info(f"ℹ️ Loaded last dispatch date from disk: {last_dispatched_date}")

    while True:
        try:
            now_ktm = datetime.now(KATHMANDU_TZ)
            current_time_str = now_ktm.strftime("%H:%M")
            current_date_str = now_ktm.strftime("%Y-%m-%d")

            # Check for manual trigger flag file
            if os.path.exists(FLAG_FILE):
                logger.info(f"⚡ Instant manual trigger flag detected at {FLAG_FILE}!")
                try:
                    os.remove(FLAG_FILE)
                except Exception:
                    pass
                if execute_daily_dispatch():
                    last_dispatched_date = current_date_str
                    record_dispatch_success(current_date_str)

            # Check if we are inside the daily morning dispatch window (09:00 - 11:00 AM) and haven't run today
            in_window = (DISPATCH_TIME <= current_time_str <= DISPATCH_WINDOW_END)
            if in_window and last_dispatched_date != current_date_str:
                logger.info(f"🔔 Morning dispatch window active ({current_time_str} KTM) for date: {current_date_str}")

                # Verify WhatsApp bridge is online, wait up to 60s if initializing
                bridge_ok = False
                for attempt in range(6):
                    if is_bridge_ready():
                        bridge_ok = True
                        break
                    logger.warning(f"Bridge not ready on port 5006, waiting 10s (attempt {attempt+1}/6)...")
                    time.sleep(10)

                if bridge_ok:
                    if execute_daily_dispatch():
                        last_dispatched_date = current_date_str
                        record_dispatch_success(current_date_str)
                    else:
                        logger.warning("Daily dispatch attempted but encountered errors; will retry in next loop cycle if still in window.")
                else:
                    logger.error("🚨 Skipping scheduled dispatch attempt: WhatsApp Bridge is offline or not connected on port 5006.")

            # Sleep 20 seconds before checking again
            time.sleep(20)

        except Exception as loop_err:
            logger.error(f"Unexpected error in scheduler loop: {loop_err}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    scheduler_loop()
