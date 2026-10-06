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
_cost_cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes in-memory cache

LOCAL_IMAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "HermesData", "assets", "images"))
_local_images_index: Dict[str, str] = {}
_local_images_indexed = False

def get_local_images_index() -> Dict[str, str]:
    """Indexes physical images in HermesData/assets/images by normalized product name."""
    global _local_images_index, _local_images_indexed
    if not _local_images_indexed:
        if os.path.exists(LOCAL_IMAGE_DIR):
            for fname in os.listdir(LOCAL_IMAGE_DIR):
                ext = os.path.splitext(fname)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    base = os.path.splitext(fname)[0]
                    norm = normalize_text(base)
                    if norm:
                        _local_images_index[norm] = fname
                    _local_images_index[base.lower().strip()] = fname
        _local_images_indexed = True
    return _local_images_index

def resolve_product_image(product_name: str, existing_url: Optional[str] = None) -> Optional[str]:
    """
    Returns existing cloud image_url if valid.
    Otherwise falls back to physical local image file in HermesData/assets/images/.
    """
    if existing_url and str(existing_url).strip() and str(existing_url).strip().lower() not in ['none', 'null', 'nan']:
        return str(existing_url).strip()

    idx = get_local_images_index()
    p_norm = normalize_text(product_name)
    p_lower = str(product_name).strip().lower()

    local_file = idx.get(p_norm) or idx.get(p_lower)
    if local_file:
        return f"local://{local_file}"
    return None

def get_client():
    global _client
    if _client is None:
        if not SUPABASE_KEY:
            raise ValueError("SUPABASE_KEY environment variable is not set!")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def get_purchase_cost_for_products(product_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetches the latest purchase cost (rate in NPR, purchase date, supplier) from line_items
    for a list of product names, using in-memory cache.
    """
    global _cost_cache
    client = get_client()
    needed = [p for p in product_names if p and p not in _cost_cache]
    if needed:
        try:
            res = client.table("line_items").select(
                "product_name, rate, date, party_name"
            ).eq("voucher_category", "Purchase").in_(
                "product_name", needed[:50]
            ).order("date", desc=True).execute()

            for r in res.data or []:
                p = r.get("product_name", "").strip()
                if p and p not in _cost_cache:
                    _cost_cache[p] = {
                        "cost_price": float(r["rate"]) if r.get("rate") is not None else None,
                        "last_purchase_date": r.get("date"),
                        "last_supplier": r.get("party_name")
                    }
        except Exception as e:
            print(f"[Hermes Tools] Warning: Failed to fetch purchase cost: {e}")

    return {p: _cost_cache.get(p, {}) for p in product_names}

def enrich_items_with_costing(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Enriches product item dictionaries with latest purchase costing details."""
    if not items:
        return items
    names = [it.get("product_name") for it in items if it.get("product_name")]
    costs = get_purchase_cost_for_products(names)
    for it in items:
        name = it.get("product_name")
        c_info = costs.get(name, {})
        it["cost_price"] = c_info.get("cost_price")
        it["last_purchase_date"] = c_info.get("last_purchase_date")
        it["supplier"] = c_info.get("last_supplier")
    return items

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
                for it in items:
                    it["image_url"] = resolve_product_image(it.get("product_name"), it.get("image_url"))
                _catalog_cache = items
                _catalog_cache_time = now
        except Exception as e:
            print(f"[Hermes Tools] Warning: Failed to refresh catalog cache: {e}")
            if not _catalog_cache:
                return []
    return _catalog_cache

def invalidate_catalog_cache():
    """Forces cache refresh on next call to get_cached_catalog()."""
    global _catalog_cache, _catalog_cache_time, _cost_cache
    _catalog_cache = []
    _catalog_cache_time = 0
    _cost_cache = {}

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
        items = db_query.order("current_stock", desc=True).limit(safe_limit * 2 if has_photo_only else safe_limit).execute().data or []
        for it in items:
            it["image_url"] = resolve_product_image(it.get("product_name"), it.get("image_url"))
        if has_photo_only:
            items = [it for it in items if it.get("image_url")][:safe_limit]
        items = enrich_items_with_costing(items)
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

    items = db_query.order("current_stock", desc=True).limit(safe_limit * 2 if has_photo_only else safe_limit).execute().data or []
    for it in items:
        it["image_url"] = resolve_product_image(it.get("product_name"), it.get("image_url"))
    if has_photo_only:
        items = [it for it in items if it.get("image_url")][:safe_limit]

    # If direct SQL found matches, return them immediately
    if len(items) > 0:
        items = enrich_items_with_costing(items)
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
        nearest_items = enrich_items_with_costing(nearest_items)
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

def get_product_costing(product_name: str) -> Dict[str, Any]:
    """
    Look up confidential costing, purchase cost history, and China factory RMB price
    for a specific product or code (e.g. '360-1', '298-1 Gun', 'Clay', 'BF430').
    Call this tool whenever the user explicitly asks for 'cost', 'costing', 'purchase rate',
    'landing cost', 'kharcha', 'factory price', or 'RMB price'.

    Args:
        product_name: Name or code of the item to get costing for
    """
    if not product_name or str(product_name).strip() in ["", "none", "null"]:
        return {"error": "Please provide a product name or item code to check costing."}

    k = str(product_name).strip()
    # Find matching products (even if out of stock, since costing can be asked for historical items)
    matched_items = find_nearest_products(query=k, limit=5, in_stock_only=False)
    if not matched_items:
        return {
            "searched_keyword": k,
            "found": False,
            "message": f"No product matching '{k}' was found in the catalog."
        }

    matched_items = enrich_items_with_costing(matched_items)

    formatted_results = []
    for item in matched_items:
        formatted_results.append({
            "product_name": item.get("product_name"),
            "current_stock_pcs": item.get("current_stock", 0.0),
            "wholesale_selling_price_rs": item.get("selling_price", 0.0),
            "purchase_cost_rs": item.get("cost_price"),
            "last_purchase_date": item.get("last_purchase_date"),
            "supplier": item.get("supplier"),
            "china_factory_cost_rmb": item.get("rmb_price"),
            "image_url": item.get("image_url")
        })

    return {
        "searched_keyword": k,
        "found": True,
        "count": len(formatted_results),
        "primary_item": formatted_results[0],
        "other_matches": formatted_results[1:],
        "is_nearest_match": normalize_text(k) != normalize_text(formatted_results[0]["product_name"])
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

def create_tiktok_reel(product_name: str) -> Dict[str, Any]:
    """
    Generate an automated vertical 9:16 TikTok reel and viral marketing copy for a product,
    saving it to TikTok drafts. Strictly enforces TikTok Community Guidelines (blocks toy guns/weapons).

    Args:
        product_name: The name or code of the product to create a TikTok reel for (e.g. '360-1', 'RC Car').
    """
    from tiktok_safety import evaluate_post_safety
    from tiktok_engine import generate_tiktok_copy, render_vertical_reel
    from tiktok_client import TikTokPolicyViolationError

    # 1. Search product in inventory
    search_res = search_products(search_term=product_name, in_stock_only=False, limit=1)
    items = search_res.get("items", [])
    if not items:
        return {
            "status": "not_found",
            "message": f"Could not find product matching '{product_name}' in inventory to create a TikTok reel."
        }

    item = search_res["items"][0]
    p_name = item.get("product_name", product_name)
    price = float(item.get("selling_price", 0) or 0)
    stock = float(item.get("current_stock", 0) or 0)
    img_url = item.get("image_url") or ""

    # Resolve local or cloud image
    resolved_img = resolve_product_image(p_name, img_url)
    if resolved_img and resolved_img.startswith("local://"):
        local_filename = resolved_img.replace("local://", "")
        resolved_img = os.path.join(LOCAL_IMAGE_DIR, local_filename)

    # 2. Safety evaluation
    safety = evaluate_post_safety(
        product_name=p_name,
        tags=item.get("tags", ""),
        image_input=resolved_img if resolved_img and os.path.exists(resolved_img) else None,
        skip_vision=False
    )

    if not safety.is_safe:
        return {
            "status": "policy_blocked",
            "product_name": p_name,
            "message": (
                f"🚨 TIKTOK POLICY SHIELD TRIGGERED: Cannot create TikTok reel for '{p_name}'. "
                f"Reason: {safety.user_guidance}. Imitation firearms and toy weapons are strictly "
                "banned under TikTok Community Guidelines to prevent account strikes."
            )
        }

    # 3. Generate Copy & Video
    try:
        copy_res = generate_tiktok_copy(product_name=p_name, price=price, current_stock=stock)
        img_source = resolved_img if resolved_img and os.path.exists(resolved_img) else "HermesData/assets/images/006-6 Pull Line Car.jpg"

        video_res = render_vertical_reel(
            image_sources=[img_source],
            product_name=p_name,
            price=price,
            current_stock=stock,
            overlay_badges=copy_res.get("overlay_badges")
        )

        return {
            "status": "success",
            "product_name": p_name,
            "wholesale_price": price,
            "current_stock": stock,
            "hook": copy_res.get("hook"),
            "caption": copy_res.get("caption"),
            "hashtags": " ".join(copy_res.get("hashtags", [])),
            "video_path": video_res.get("video_path"),
            "message": f"✅ TikTok 9:16 vertical reel created for '{p_name}' and saved to drafts with viral caption & tags!"
        }
    except Exception as ex:
        return {
            "status": "error",
            "message": f"Failed to generate TikTok reel for '{p_name}': {str(ex)}"
        }
