"""
Hermes Catalog Reader — Strictly Read-Only Client for Bafa Product Catalog & Media
Connects to the secondary Supabase project (ktlzbplvxmpxzbbsxbid.supabase.co)
to query product photos, catalog prices, and tags.
"""

from typing import List, Dict, Any, Optional
import pandas as pd
from supabase import create_client, Client

CATALOG_URL = "https://ktlzbplvxmpxzbbsxbid.supabase.co"
CATALOG_KEY = "sb_publishable_PVwz5LDTZzJr9kqbgD2A3g_mdMZajai"

_catalog_client: Optional[Client] = None

def get_catalog_client() -> Client:
    """Initialize and return read-only Supabase client for product catalog."""
    global _catalog_client
    if _catalog_client is None:
        _catalog_client = create_client(CATALOG_URL, CATALOG_KEY)
    return _catalog_client

def get_all_catalog_products() -> pd.DataFrame:
    """Fetch all products with image URLs, tags, and catalog prices (Read-Only)."""
    client = get_catalog_client()
    all_rows = []
    offset = 0
    page_size = 1000

    while True:
        res = client.table('products').select('*').range(offset, offset + page_size - 1).execute()
        if not res.data:
            break
        all_rows.extend(res.data)
        if len(res.data) < page_size:
            break
        offset += page_size

    df = pd.DataFrame(all_rows)
    if not df.empty and 'id' in df.columns:
        df = df.rename(columns={'id': 'product_name', 'price': 'catalog_price'})
    return df

def get_photos_by_tag(tag: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Find products with photo URLs matching a specific tag (e.g. 'RC', 'DOLL', 'GUN')."""
    client = get_catalog_client()
    tag_clean = tag.strip().upper()
    res = client.table('products') \
        .select('id, tags, image_url, price, selling_price') \
        .ilike('tags', f'%{tag_clean}%') \
        .not_.is_('image_url', 'null') \
        .limit(limit) \
        .execute()
    return res.data or []

def get_photo_for_product(product_name: str) -> Optional[str]:
    """Retrieve public photo URL for a single product name."""
    client = get_catalog_client()
    res = client.table('products') \
        .select('image_url') \
        .eq('id', product_name.strip()) \
        .limit(1) \
        .execute()
    if res.data and res.data[0].get('image_url'):
        return res.data[0]['image_url']
    return None

def get_all_tags_summary() -> Dict[str, int]:
    """Get frequency count of all available tags across products."""
    df = get_all_catalog_products()
    if df.empty or 'tags' not in df.columns:
        return {}
    tag_counts = {}
    for tags_str in df['tags'].dropna():
        for t in str(tags_str).split(';'):
            t_clean = t.strip().upper()
            if t_clean:
                tag_counts[t_clean] = tag_counts.get(t_clean, 0) + 1
    return dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True))

if __name__ == '__main__':
    print("Testing Hermes Catalog Reader (Read-Only)...")
    tags = get_all_tags_summary()
    print(f"Total unique tags: {len(tags)}")
    print("Top 10 tags:", list(tags.items())[:10])
    
    rc_photos = get_photos_by_tag("RC", limit=3)
    print(f"\nFound {len(rc_photos)} sample RC photos:")
    for r in rc_photos:
        print(f"  - {r['id']}: {r.get('image_url')}")
