"""
Google Hermes Engine — Powered by Google Gemini & Primary Supabase Database
Provides intelligent catalog querying, live stock lookups, wholesale pricing,
and photo retrieval using Google Gemini's native tool calling.
"""

import os
import re
import time
import json
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from hermes_tools import search_products, get_product_costing

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

_client = None

def get_gemini_client():
    global _client
    if _client is None:
        key = os.getenv("GOOGLE_API_KEY")
        if not key:
            raise ValueError("GOOGLE_API_KEY is not set in environment or .env!")
        _client = genai.Client(api_key=key)
    return _client

SYSTEM_INSTRUCTION = """You are Hermes, the intelligent inventory, catalog, and sales assistant for Demo Khelauna (Wholesale Toys & Party Supplies).
Your job is to look up live stock levels, wholesale prices, share product photos, and look up costing from our Supabase database.

Rules:
1. TOOL CALLING:
   - When the user asks for items, stock, prices, or photos, call `search_products`.
   - When the user explicitly asks for "cost", "costing", "purchase rate", "purchase price", "kharcha", "RMB price", "factory price", or "supplier rate", call `get_product_costing(product_name=...)`.
   - Default search limit is 15. If the user asks for "all" items or a broad catalog list, specify `limit=20` or `limit=25`.
   - Example: If user asks for "RC items" or "give me rc item photos", call `search_products(search_term="RC", has_photo_only=True, limit=15)`.
   - Example: If user asks for "all mala items", call `search_products(search_term="MALA", has_photo_only=True, limit=25)`.
   - Example: If user asks for "360-1", call `search_products(search_term="360-1")`.
   - Example: If user asks "What is the cost of 360-1?" or "Costing for RC car" or "360-1 ko costing kati ho", call `get_product_costing(product_name="360-1")`.

2. PHOTO RENDERING & CATALOG PRESENTATION:
   - If user asks for photos or pictures, call `search_products(has_photo_only=True)`.
   - ALWAYS PRESENT ALL ITEMS RETURNED BY THE TOOL. Do NOT artificially truncate after 4 or 5 items! If the tool returns 10, 15, or 20 items, display ALL of them.
   - For each item, embed each photo in Markdown format: ![Product Name](image_url)
   - Always display Product Name, Stock (in PCS), and Wholesale Selling Price (in Rs.) alongside the photo.
   - State the total count found at the beginning (e.g. "Found 10 matching RC items in stock:"). If only a few items exist (e.g. 4 items), explain that these are all the available products currently in stock.

3. COSTING & CONFIDENTIALITY RULES (IMPORTANT):
   - Regular Customer Inquiries:
     If the user does NOT explicitly ask for cost or costing, show ONLY the Wholesale Selling Price (in Rs.), Stock (in PCS), and Photo. Do NOT volunteer purchase cost or margins to regular customers.
   - Explicit Costing Inquiries:
     When the user asks for "cost", "costing", "purchase rate", "factory rate", or "RMB":
     Provide complete transparency for the item(s):
     * Product Name & Live Stock (in PCS)
     * Wholesale Selling Rate: Rs. X
     * Last Purchase Cost: Rs. Y (Purchased on Date, Supplier: Name, if recorded)
     * China Factory Cost (RMB): ¥ Z.ZZ RMB (if recorded)
     * Photo (if available)
     If a cost or RMB figure is not recorded for that item, politely say "Purchase cost / RMB rate is not recorded in the database for this item."

4. SMART NEAREST-MATCH & TYPO HANDLING:
   - Wholesale customers frequently type typos, missing spaces, missing hyphens, or colloquial terms (e.g. 'BF430', '3601', '3333', 'batry car', 'candel', 'watergan', 'gudiya', 'gaadi').
   - When `search_products` or `get_product_costing` returns `is_nearest_match=True`:
     - Clearly explain: "I couldn't find an exact match for '{searched_keyword}', but here is the closest matching product in our inventory:"
     - Present the found item(s) with Product Name, exact stock in PCS, price, costing (if asked), and photo.
     - Politely ask: "Did you mean this item?"
   - Never say an item was not found if nearest matching products were returned!

5. LANGUAGE ADAPTATION:
   - If the user asks in Nepali (e.g. "Malai rc item ko photo patahu" or "360-1 ko costing kati ho"), reply naturally in Nepali while listing all relevant details.
   - If the user asks in Hindi or English, respond in their respective language.

6. ACCURACY:
7. VISUAL PRODUCT MATCHING (PHOTO INPUT):
   - When the user sends a photo of an item, toy, box, or packaging:
     a) FIRST: Carefully examine the packaging and product for any printed Model Numbers, Item Numbers, Art Numbers, or Codes (e.g. '3398-1', '953Y', '6608', '8802', 'JH-808', 'NO. XXXX', 'Item No.').
     b) SECOND: If a model code or item number is found, immediately call `search_products(search_term=extracted_code)`.
     c) THIRD: If no code is visible (e.g., loose, unboxed toy), identify the physical object, category, color, and key features (e.g., 'bubble gun', 'rc crawler yellow', 'kitchen suitcase'), and call `search_products(search_term=key_feature_or_category)`.
     d) If an exact match is found, present:
        📸 *Product Identified!*
        📦 *[Product Name]*
        • Live Stock: [Stock in PCS]
        • Wholesale Rate: Rs. [Price]
        • Status: [In Stock / Out of Stock]
        • Photo: Embed our official catalog photo: ![Product Name](image_url)
     e) If multiple possible items match, list the top 2-3 options with their photos, names, stock, and prices, and ask: 'Which of these matches the item you are looking for?'
"""

# Available models in priority order
MODEL_CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-pro-latest",
]

def ask_hermes_with_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    user_message: str = ""
) -> Dict[str, Any]:
    """
    High-Speed 2-Step Visual Product Search:
    Step 1: Rapid multimodal visual inspection to extract printed codes (OCR) and visual features (~2-3s).
    Step 2: High-speed local/Supabase catalog search and response generation (~1s).
    Total response time: < 5 seconds without fragile multi-turn tool calling.
    """
    client = get_gemini_client()
    last_err = None

    vision_prompt = (
        "Examine this toy product photo.\n"
        "1. Extract any printed model number, item number, art number, or code on the box or product (e.g. '3398-1', '953Y', '6608', '8802', 'JH-808') or null if none.\n"
        "2. Provide 1 to 3 words best suited to search for this product in a wholesale toy catalog (e.g. 'Dart Gun', 'RC Crawler', 'Bubble Gun').\n"
        "3. Provide a clear 1-sentence physical description of the toy (color, type, features).\n"
        "Return strictly in JSON format: {\"code\": \"...\" or null, \"search_query\": \"...\", \"description\": \"...\"}"
    )

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    contents = [image_part, vision_prompt]

    parsed_vision = None
    used_model = None

    for model_name in MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            resp_text = response.text or "{}"
            parsed_vision = json.loads(resp_text)
            used_model = model_name
            break
        except Exception as e:
            last_err = e
            time.sleep(0.5)
            continue

    if not parsed_vision:
        return {
            "reply": f"Sorry, I encountered an error analyzing the photo: {last_err}",
            "image_urls": [],
            "model_used": None,
            "status": "error"
        }

    # Step 2: Query database with extracted code / search query
    code = parsed_vision.get("code")
    search_q = parsed_vision.get("search_query", "")
    desc = parsed_vision.get("description", "Product")

    # Prioritize exact model code if found; fallback to visual keywords
    primary_query = code if (code and str(code).lower() != "null") else search_q

    # Check if user asked for costing
    u_lower = (user_message or "").lower()
    wants_cost = any(k in u_lower for k in ["cost", "costing", "purchase", "kharcha", "rmb", "factory"])

    search_result = search_products(search_term=primary_query, limit=5)
    items = search_result.get("items", [])

    # If code search yielded nothing, fallback to visual category/query
    if not items and code and search_q and search_q.lower() != str(code).lower():
        search_result = search_products(search_term=search_q, limit=5)
        items = search_result.get("items", [])

    reply_lines = []
    reply_lines.append(f"📸 *Product Identified:* {desc}")
    if code:
        reply_lines.append(f"🏷️ *Detected Code / Model:* `{code}`")
    reply_lines.append("")

    image_urls = []

    if items:
        reply_lines.append(f"Found {len(items)} matching product(s) in catalog:")
        for it in items:
            p_name = it.get("product_name", "Unknown")
            stock = int(it.get("current_stock", 0))
            price = it.get("selling_price", 0)
            img_u = it.get("image_url")
            stock_status = "In Stock ✅" if stock > 0 else "Out of Stock ❌"

            reply_lines.append(f"• *{p_name}*")
            reply_lines.append(f"  - Stock: {stock:,} PCS ({stock_status})")
            reply_lines.append(f"  - Wholesale Rate: Rs. {price:,.2f}")

            if wants_cost:
                cost_info = get_product_costing(product_name=p_name)
                c_price = cost_info.get("last_purchase_price")
                rmb = cost_info.get("rmb_price")
                cost_desc = f"Rs. {c_price:,.2f}" if c_price else "Not recorded"
                rmb_desc = f"¥ {rmb:.2f} RMB" if rmb else "Not recorded"
                reply_lines.append(f"  - Purchase Cost: {cost_desc} | Factory: {rmb_desc}")

            if img_u:
                reply_lines.append(f"  - ![{p_name}]({img_u})")
                image_urls.append(img_u)

            reply_lines.append("")

        reply_lines.append("Here is our official catalog picture for side-by-side comparison.")
    else:
        reply_lines.append("⚠️ This specific product was not found in our current inventory catalog or is out of stock.")

    final_reply = "\n".join(reply_lines).strip()

    return {
        "reply": final_reply,
        "image_urls": image_urls,
        "model_used": used_model,
        "status": "success"
    }

def ask_hermes(user_message: str) -> Dict[str, Any]:
    """
    Sends a text query to Google Gemini with Supabase search and costing tools.
    Returns:
        {
            "reply": str, # Markdown text response
            "image_urls": list[str], # Extracted photo URLs for WhatsApp media
            "status": "success" | "error"
        }
    """
    client = get_gemini_client()
    last_err = None

    for model_name in MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_message,
                config=types.GenerateContentConfig(
                    tools=[search_products, get_product_costing],
                    system_instruction=SYSTEM_INSTRUCTION,
                )
            )

            reply_text = response.text or ""

            # Extract image URLs from markdown for WhatsApp media sending
            image_urls = re.findall(r'!\[.*?\]\(((?:https?://|local://).*?\.(?:jpe?g|png|webp)|[^\s\)]+)\)', reply_text, re.IGNORECASE)

            return {
                "reply": reply_text,
                "image_urls": image_urls,
                "model_used": model_name,
                "status": "success"
            }
        except Exception as e:
            last_err = e
            time.sleep(1)
            continue

    return {
        "reply": f"Sorry, I encountered an error checking inventory: {last_err}",
        "image_urls": [],
        "model_used": None,
        "status": "error"
    }

if __name__ == "__main__":
    print("Testing Google Hermes Engine...")
    res = ask_hermes("Give me RC item photos")
    print("\nReply:\n", res["reply"])
    print("\nImages found:", len(res["image_urls"]))
