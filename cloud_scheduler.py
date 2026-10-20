"""
24/7 Cloud Background Scheduler for DayBook Analytics (Runs on Railway)
Fires daily automated WhatsApp dispatches at 09:00 AM (Asia/Kathmandu, UTC+05:45).
Supports:
  - 50 Slow-Moving Inventory Photos Broadcast Pack (broadcast_slow_moving.py)
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
DISPATCH_MODE = os.getenv("DAILY_DISPATCH_MODE", "photos")  # "photos", "video", or "both"
FLAG_FILE = os.path.join(os.path.dirname(__file__), "data", "trigger_broadcast.flag")


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


def execute_daily_dispatch():
    """Runs the selected daily dispatch (Photos pack, TikTok video reel, or both)."""
    logger.info(f"🚀 Triggering daily dispatch (Mode: {DISPATCH_MODE}) to {TARGET_PHONE}...")

    # 1. Slow-Moving Photos Broadcast Pack
    if DISPATCH_MODE in ["photos", "both"]:
        try:
            logger.info("Starting 50 Slow-Moving Photos Broadcast Pack dispatch...")
            import broadcast_slow_moving
            broadcast_slow_moving.send_broadcast_pack(recipient=TARGET_PHONE)
            logger.info("✅ 50 Slow-Moving Photos Broadcast Pack dispatched successfully!")
        except Exception as e:
            logger.error(f"❌ Failed to dispatch Photos Broadcast Pack: {e}", exc_info=True)

    # 2. Daily TikTok Video Reel Concierge
    if DISPATCH_MODE in ["video", "both"]:
        try:
            logger.info("Starting Daily TikTok Video Reel Concierge dispatch...")
            import daily_tiktok_dispatch
            res = daily_tiktok_dispatch.run_daily_tiktok_dispatch(recipient=TARGET_PHONE)
            logger.info(f"✅ Daily TikTok Video Reel dispatched: {res.get('product_name')}")
        except Exception as e:
            logger.error(f"❌ Failed to dispatch Daily TikTok Reel: {e}", exc_info=True)


def scheduler_loop():
    """Main continuous scheduler loop."""
    logger.info("=======================================================")
    logger.info("⏰ DayBook Analytics 24/7 Cloud Scheduler Started")
    logger.info(f"   Target Phone : {TARGET_PHONE}")
    logger.info(f"   Scheduled At : {DISPATCH_TIME} AM (Asia/Kathmandu)")
    logger.info(f"   Mode         : {DISPATCH_MODE}")
    logger.info("=======================================================")

    last_dispatched_date: Optional[str] = None

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
                execute_daily_dispatch()

            # Check if it's 09:00 AM and hasn't run yet today
            if current_time_str == DISPATCH_TIME and last_dispatched_date != current_date_str:
                logger.info(f"🔔 09:00 AM trigger reached for Kathmandu date: {current_date_str}")

                # Verify WhatsApp bridge is online, wait up to 60s if initializing
                bridge_ok = False
                for attempt in range(6):
                    if is_bridge_ready():
                        bridge_ok = True
                        break
                    logger.warning(f"Bridge not ready on port 5006, waiting 10s (attempt {attempt+1}/6)...")
                    time.sleep(10)

                if bridge_ok:
                    execute_daily_dispatch()
                    last_dispatched_date = current_date_str
                else:
                    logger.error("🚨 Skipping scheduled dispatch: WhatsApp Bridge is offline or not connected on port 5006.")

            # Sleep 20 seconds before checking again
            time.sleep(20)

        except Exception as loop_err:
            logger.error(f"Unexpected error in scheduler loop: {loop_err}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    scheduler_loop()
