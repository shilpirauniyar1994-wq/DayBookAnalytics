"""
Hermes Tools — Standalone Client Library for Hermes Agent & Google AI Engine
Provides instant, secure access to product stock, wholesale prices, photos,
code normalization, and smart nearest-match (fuzzy) search across Demo Khelauna catalog.
"""

import os
import re
import time
import difflib
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://suemxvpciooyxzaapuwm.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")

_client = None
_catalog_cache = []
_catalog_cache_time = 0
CACHE_TTL_SECONDS = 300  # 5 minutes in-memory cache

def get_client():
    global _client
    if _client is None:
        if not SUPABASE_KEY:
            raise ValueError("SUPABASE_KEY environment variable is not set!")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def get_cached_catalog() -> List[Dict[str, Any]]:
    """Loads and caches all items from Supabase in memory for instant fuzzy search."""
    global _catalog_cache, _catalog_cache_time
    now = time.time()
    if not _catalog_cache or (now - _catalog_cache_time > CACHE_TTL_SECONDS):
        client = get_client()
        items = []
        try:
            # Batch 1 (0 to 999)
            res1 = client.table("hermes_items").select(
                "product_name, current_stock, selling_price, rmb_price, image_url, tags, product_group, last_sold_month"
            ).range(0, 999).execute()
            items.extend(res1.data or [])

            # Batch 2 (1000 to 1999) if more exist
            if len(res1.data or []) == 1000:
                res2 = client.table("hermes_items").select(
                    "product_name, current_stock, selling_price, rmb_price, image_url, tags, product_group, last_sold_month"
                ).range(1000, 1999).execute()
                items.extend(res2.data or [])

            if items:
                _catalog_cache = items
                _catalog_cache_time = now
        except Exception as e:
            print(f"[Hermes Tools] Warning: Failed to refresh catalog cache: {e}")
            if not _catalog_cache:
                return []
    return _catalog_cache

COLLOQUIAL_SYNONYMS = {
    "gudiya": "DOLL",
    "gudya": "DOLL",
    "putali": "DOLL",
    "gaadi": "CAR",
    "gadi": "CAR",
    "kar": "CAR",
    "bandook": "GUN",
    "banduk": "GUN",
    "pistol": "GUN",
    "balun": "BALLOON",
    "fukka": "BALLOON",
    "batry": "BATTERY",
    "batery": "BATTERY",
    "battry": "BATTERY",
    "rubix": "CUBE",
    "rubik": "CUBE",
    "candel": "CANDLE",
    "kendel": "CANDLE",
    "slime": "CLAY",
    "cle": "CLAY",
    "popt": "POP IT",
    "popit": "POP IT",
    "chargable": "CHARGEBLE",
    "chargabl": "CHARGEBLE",
    "vater": "WATER",
    "watergan": "WATER GUN",
    "watergun": "WATER GUN"
}

def normalize_text(s: str) -> str:
    """Strips all punctuation, spaces, and hyphens to allow exact code matching."""
    return re.sub(r'[^a-z0-9]', '', str(s).lower())

def find_nearest_products(
    query: str,
    limit: int = 5,
    in_stock_only: bool = True,
    has_photo_only: bool = False
) -> List[Dict[str, Any]]:
    """
    Finds the closest matching products in the catalog using:
    1. Alphanumeric normalization (e.g. 'bf430' -> 'Bf 430', '3601' -> '360-1')
    2. Colloquial synonyms (e.g. 'gudiya' -> 'DOLL', 'gaadi' -> 'CAR')
    3. Multi-token word overlap and Levenshtein similarity scoring.
    """
    catalog = get_cached_catalog()
    if not catalog:
        return []

    q_raw = str(query).strip().lower()
    q_norm = normalize_text(q_raw)
    synonym = COLLOQUIAL_SYNONYMS.get(q_raw)

    words = [w for w in re.split(r'[\s\-_/]+', q_raw) if len(w) > 1]

    scored = []
    for item in catalog:
        stock = item.get("current_stock") or 0.0
        if in_stock_only and stock <= 0:
            continue
        if has_photo_only and not item.get("image_url"):
            continue

        p_name = item.get("product_name") or ""
        tags = str(item.get("tags") or "")
        p_norm = normalize_text(p_name)
        tags_norm = normalize_text(tags)

        score = 0.0

        # Tier 1: Alphanumeric normalized exact match (e.g. 'bf430' == 'bf430', '3601' == '3601')
        if q_norm and (q_norm == p_norm or q_norm in p_norm):
            score = 1.0
        # Tier 2: Synonym match with word boundary
        elif synonym and (re.search(r'\b' + re.escape(synonym) + r'\b', p_name, re.I) or synonym.upper() in tags.upper()):
            score = 0.95
        else:
            # Tier 3: Sequence matcher similarity
            sim_name = difflib.SequenceMatcher(None, q_raw, p_name.lower()).ratio()
            sim_norm = difflib.SequenceMatcher(None, q_norm, p_norm).ratio()
            best_sim = max(sim_name, sim_norm)

            # Tier 4: Token word matching
            if words:
                matched_words = sum(1 for w in words if w in p_name.lower() or w in tags.lower())
                token_score = (matched_words / len(words)) * 0.85
                best_sim = max(best_sim, token_score)

            if best_sim >= 0.40:
                score = best_sim

        if score > 0:
            scored.append((score, stock, item))

    # Rank by score first, then prioritize in-stock and higher stock
    scored.sort(key=lambda x: (x[0], x[1] > 0, x[1]), reverse=True)

    seen = set()
    results = []
    for s, st, it in scored:
        if it["product_name"] not in seen:
            seen.add(it["product_name"])
            results.append(it)
            if len(results) >= limit:
                break
    return results

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
    Searches across both product_name and tags, with automatic fallback
    to intelligent nearest-match (fuzzy) search when exact spelling fails.

    Args:
        search_term: Product keyword or tag (e.g. 'RC', 'DOLL', 'GUN', '360-1', 'Clay', 'all', 'BF430')
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

    keyword = search_term or tag or query
    if not keyword or str(keyword).strip() in ["", "none", "null"]:
        return {
            "searched_keyword": None,
            "count": 0,
            "items": [],
            "error": "Missing search keyword! Please specify a product or category (e.g. search_term='RC', search_term='Doll', search_term='360-1')."
        }

    k = str(keyword).strip()
    safe_limit = max(1, min(int(limit) if limit else 15, 30))

    # Handle broad catalog queries
    if k.lower() in ["all", "everything", "catalog", "all items", "all products"]:
        if in_stock_only:
            db_query = db_query.gt("current_stock", 0)
        if has_photo_only:
            db_query = db_query.not_.is_("image_url", "null")
        items = db_query.order("current_stock", desc=True).limit(safe_limit).execute().data or []
        return {
            "searched_keyword": keyword,
            "count": len(items),
            "items": items,
            "is_nearest_match": False,
            "suggested_tags": []
        }

    # Stage 1: Exact / Direct Substring SQL Search
    db_query = db_query.or_(f"tags.ilike.%{k}%,product_name.ilike.%{k}%")
    if in_stock_only:
        db_query = db_query.gt("current_stock", 0)
    if has_photo_only:
        db_query = db_query.not_.is_("image_url", "null")

    items = db_query.order("current_stock", desc=True).limit(safe_limit).execute().data or []

    # If direct SQL found matches, return them immediately
    if len(items) > 0:
        return {
            "searched_keyword": keyword,
            "count": len(items),
            "items": items,
            "is_nearest_match": False,
            "suggested_tags": []
        }

    # Stage 2: Smart Nearest-Match / Fuzzy Search (Fixes BF430 -> Bf 430, 3601 -> 360-1, candel -> Candle)
    nearest_items = find_nearest_products(
        query=k,
        limit=safe_limit,
        in_stock_only=in_stock_only,
        has_photo_only=has_photo_only
    )

    if len(nearest_items) > 0:
        return {
            "searched_keyword": keyword,
            "count": len(nearest_items),
            "items": nearest_items,
            "is_nearest_match": True,
            "message": f"No exact item found for '{keyword}'. Showing closest matching items in stock."
        }

    # Stage 3: Tag suggestions fallback
    suggested_tags = get_tag_suggestions(k)
    return {
        "searched_keyword": keyword,
        "count": 0,
        "items": [],
        "is_nearest_match": False,
        "suggested_tags": suggested_tags
    }

def get_tag_suggestions(misspelled_tag: str, limit: int = 6) -> List[Dict[str, Any]]:
    """Finds closest matching available tags when a tag is misspelled (e.g. 'dols' -> 'DOLL')."""
    catalog = get_cached_catalog()
    tag_counts = {}
    for r in catalog:
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
        if t not in seen and t in tag_counts:
            seen.add(t)
            suggestions.append({"tag": t, "item_count": tag_counts[t]})

    return suggestions[:limit]

def get_popular_tags(limit: int = 10) -> List[Dict[str, Any]]:
    """Returns top active product tags in the catalog."""
    catalog = get_cached_catalog()
    tag_counts = {}
    for r in catalog:
        for t in str(r.get("tags") or "").split(";"):
            clean_t = t.strip().upper()
            if clean_t:
                tag_counts[clean_t] = tag_counts.get(clean_t, 0) + 1
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)
    return [{"tag": t, "item_count": c} for t, c in sorted_tags[:limit]]
