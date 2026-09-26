"""
Hermes Tools — Standalone Client Library for Hermes Agent
Drop this file into Hermes's project or import it to give Hermes instant,
secure access to product stock, wholesale prices, photos, and auto-correcting tag suggestions.

Required Environment Variables:
    SUPABASE_URL = "https://suemxvpciooyxzaapuwm.supabase.co"
    SUPABASE_ANON_KEY = "<your_publishable_key>"
"""

import os
import difflib
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://suemxvpciooyxzaapuwm.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")


_client = None

def get_client():
    global _client
    if _client is None:
        if not SUPABASE_KEY:
            raise ValueError("SUPABASE_ANON_KEY (Publishable Key) environment variable is not set!")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def search_products(
    search_term: Optional[str] = None,
    query: Optional[str] = None,
    tag: Optional[str] = None,
    in_stock_only: bool = True,
    has_photo_only: bool = False,
    limit: int = 15
) -> Dict[str, Any]:
    """
    Search product inventory, wholesale prices, and product photo URLs.
    Searches across both product_name and tags.

    Args:
        search_term: Product keyword or tag (e.g. 'RC', 'DOLL', 'GUN', '360-1', 'Clay', 'all')
        query: Alias for search_term
        tag: Alias for search_term
        in_stock_only: Only return items with stock > 0 (default True)
        has_photo_only: Only return items with photos (default False, set True when asked for pictures)
        limit: Max products to return (default 15, max 30)
    """
    client = get_client()
    db_query = client.table("hermes_items").select(
        "product_name, current_stock, selling_price, rmb_price, image_url, tags, product_group, last_sold_month"
    )

    # Determine unified search term
    keyword = search_term or tag or query
    if not keyword or str(keyword).strip() in ["", "none", "null"]:
        return {
            "searched_keyword": None,
            "count": 0,
            "items": [],
            "error": "Missing search keyword! You must specify what product or category to search for (e.g. search_term='RC', search_term='Doll', search_term='Gun'). Do not leave search_term blank."
        }

    k = str(keyword).strip()
    if k.lower() in ["all", "everything", "catalog", "all items", "all products"]:
        if in_stock_only:
            db_query = db_query.gt("current_stock", 0)
        if has_photo_only:
            db_query = db_query.not_.is_("image_url", "null")
    else:
        # Search BOTH tags and product_name simultaneously
        db_query = db_query.or_(f"tags.ilike.%{k}%,product_name.ilike.%{k}%")
        if in_stock_only:
            db_query = db_query.gt("current_stock", 0)
        if has_photo_only:
            db_query = db_query.not_.is_("image_url", "null")

    # Clamped limit up to 30 items
    safe_limit = max(1, min(int(limit) if limit else 15, 30))
    items = db_query.order("current_stock", desc=True).limit(safe_limit).execute().data or []

    # If keyword returned 0 items, find closest matching tags
    suggested_tags = []
    if len(items) == 0 and k.lower() not in ["all", "everything", "catalog"]:
        suggested_tags = get_tag_suggestions(k)

    return {
        "searched_keyword": keyword,
        "count": len(items),
        "items": items,
        "suggested_tags": suggested_tags if len(items) == 0 else []
    }


def get_tag_suggestions(misspelled_tag: str, limit: int = 6) -> List[Dict[str, Any]]:
    """
    Finds closest matching available tags when a tag is misspelled (e.g. 'dols' -> 'DOLL').
    """
    client = get_client()
    res = client.table("hermes_items").select("tags").not_.is_("tags", "null").execute()
    tag_counts = {}
    for r in res.data or []:
        for t in str(r.get("tags") or "").split(";"):
            clean_t = t.strip().upper()
            if clean_t:
                tag_counts[clean_t] = tag_counts.get(clean_t, 0) + 1

    all_keys = list(tag_counts.keys())
    raw = misspelled_tag.strip().upper()
    close_matches = difflib.get_close_matches(raw, all_keys, n=limit, cutoff=0.45)
    substring_matches = [t for t in all_keys if raw in t or t in raw]

    seen = set()
    suggestions = []
    for t in close_matches + substring_matches:
        if t not in seen:
            seen.add(t)
            suggestions.append({"tag": t, "item_count": tag_counts[t]})

    return suggestions[:limit]

def get_popular_tags(limit: int = 10) -> List[Dict[str, Any]]:
    """Returns top active product tags in the catalog."""
    client = get_client()
    res = client.table("hermes_items").select("tags").not_.is_("tags", "null").execute()
    tag_counts = {}
    for r in res.data or []:
        for t in str(r.get("tags") or "").split(";"):
            clean_t = t.strip().upper()
            if clean_t:
                tag_counts[clean_t] = tag_counts.get(clean_t, 0) + 1
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"tag": t, "item_count": c} for t, c in sorted_tags[:limit]]
