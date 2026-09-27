"""
Hermes Photo Sync Tool — Uploads local physical photos to Primary Supabase Storage
and links them to hermes_items table.
"""

import os
import sys
import mimetypes
from typing import Dict, List, Any
from dotenv import load_dotenv

# Ensure UTF-8 stdout
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

from hermes_tools import get_client, normalize_text

BUCKET_NAME = "product_photos"
LOCAL_IMAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "HermesData", "assets", "images"))

def sync_photos():
    client = get_client()
    if not os.path.exists(LOCAL_IMAGE_DIR):
        print(f"[ERROR] Image directory does not exist: {LOCAL_IMAGE_DIR}")
        return

    # 1. Ensure storage bucket exists
    try:
        existing_buckets = [b.name for b in client.storage.list_buckets()]
        if BUCKET_NAME not in existing_buckets:
            client.storage.create_bucket(BUCKET_NAME, options={'public': True})
            print(f"Created public bucket '{BUCKET_NAME}'")
    except Exception as e:
        print(f"Bucket check notice: {e}")

    # 2. Build local image file index
    local_files = [f for f in os.listdir(LOCAL_IMAGE_DIR) if os.path.splitext(f)[1].lower() in ['.jpg', '.jpeg', '.png', '.webp']]
    print(f"Found {len(local_files)} physical image files in {LOCAL_IMAGE_DIR}")

    local_index: Dict[str, str] = {}
    for f in local_files:
        base = os.path.splitext(f)[0]
        norm = normalize_text(base)
        if norm:
            local_index[norm] = f
        local_index[base.lower().strip()] = f

    # 3. Fetch all products from hermes_items
    items = []
    offset = 0
    while True:
        res = client.table("hermes_items").select("id, product_name, image_url").range(offset, offset + 999).execute()
        rows = res.data or []
        items.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000

    print(f"Fetched {len(items)} products from hermes_items")

    to_upload = []
    for it in items:
        pname = it["product_name"]
        has_url = bool(it.get("image_url") and str(it["image_url"]).strip() not in ['', 'None', 'null', 'nan'])
        if not has_url:
            pnorm = normalize_text(pname)
            plower = pname.lower().strip()
            match_file = local_index.get(pnorm) or local_index.get(plower)
            if match_file:
                to_upload.append((it["id"], pname, match_file))

    print(f"Products needing photo upload & link: {len(to_upload)}")

    uploaded_count = 0
    updated_db_count = 0

    # Cache uploaded files to avoid re-uploading duplicate image files
    file_to_url: Dict[str, str] = {}

    for idx, (p_id, p_name, f_name) in enumerate(to_upload, start=1):
        file_path = os.path.join(LOCAL_IMAGE_DIR, f_name)
        if not os.path.exists(file_path):
            continue

        public_url = file_to_url.get(f_name)
        if not public_url:
            # Upload file to Supabase storage
            content_type, _ = mimetypes.guess_type(file_path)
            content_type = content_type or "image/jpeg"
            try:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                client.storage.from_(BUCKET_NAME).upload(
                    path=f_name,
                    file=file_bytes,
                    file_options={"content-type": content_type, "upsert": "true"}
                )
                uploaded_count += 1
            except Exception as e:
                # If file already exists, that's fine, we still get public url
                pass

            public_url = client.storage.from_(BUCKET_NAME).get_public_url(f_name)
            file_to_url[f_name] = public_url

        # Update hermes_items in database
        try:
            client.table("hermes_items").update({"image_url": public_url}).eq("id", p_id).execute()
            updated_db_count += 1
            if idx % 25 == 0 or idx == len(to_upload):
                print(f"[{idx}/{len(to_upload)}] Linked '{p_name}' -> {f_name}")
        except Exception as e:
            print(f"Error updating DB for {p_name}: {e}")

    print("\n" + "=" * 60)
    print(f">> Sync Finished: {updated_db_count} products updated with photo URLs!")
    print("=" * 60)

if __name__ == "__main__":
    sync_photos()
