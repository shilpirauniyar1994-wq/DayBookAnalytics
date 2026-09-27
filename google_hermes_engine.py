"""
Google Hermes Engine — Powered by Google Gemini & Primary Supabase Database
Provides intelligent catalog querying, live stock lookups, wholesale pricing,
and photo retrieval using Google Gemini's native tool calling.
"""

import os
import re
import time
import json
import difflib
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

2. PHOTO RENDERING & CATALOG PRESENTATION (CONDITIONAL):
   - VERY IMPORTANT: Photos should ONLY be included if the user explicitly requested photos, pictures, or images (or words like 'photo', 'pic', 'foto', 'tasbir', etc.).
   - If the user only asks for stock, price, rate, availability, or costing (e.g. "360-1 stock", "price of rc car", "costing of 360-1"), provide clean text details WITHOUT embedding photos.
   - When photos ARE explicitly requested:
     * Call `search_products(has_photo_only=True)`.
     * ALWAYS PRESENT ALL ITEMS RETURNED BY THE TOOL. Do NOT artificially truncate after 4 or 5 items! If the tool returns 10, 15, or 20 items, display ALL of them.
     * For each item, embed each photo in Markdown format: ![Product Name](image_url)
     * Always display Product Name, Stock (in PCS), and Wholesale Selling Price (in Rs.) alongside the photo.
     * State the total count found at the beginning (e.g. "Found 10 matching RC items in stock:"). If only a few items exist (e.g. 4 items), explain that these are all the available products currently in stock.

3. COSTING & CONFIDENTIALITY RULES (IMPORTANT):
   - Regular Customer Inquiries:
     If the user does NOT explicitly ask for cost or costing, show ONLY the Wholesale Selling Price (in Rs.), Stock (in PCS), and Photo (if requested). Do NOT volunteer purchase cost or margins to regular customers.
   - Explicit Costing Inquiries:
     When the user asks for "cost", "costing", "purchase rate", "factory rate", or "RMB":
     Provide complete transparency for the item(s):
     * Product Name & Live Stock (in PCS)
     * Wholesale Selling Rate: Rs. X
     * Last Purchase Cost: Rs. Y (Purchased on Date, Supplier: Name, if recorded)
     * China Factory Cost (RMB): ¥ Z.ZZ RMB (if recorded)
     * Photo (if requested and available)
     If a cost or RMB figure is not recorded for that item, politely say "Purchase cost / RMB rate is not recorded in the database for this item."

4. SMART NEAREST-MATCH & TYPO HANDLING:
   - Wholesale customers frequently type typos, missing spaces, missing hyphens, or colloquial terms (e.g. 'BF430', '3601', '3333', 'batry car', 'candel', 'watergan', 'gudiya', 'gaadi').
   - When `search_products` or `get_product_costing` returns `is_nearest_match=True`:
     - Clearly explain: "I couldn't find an exact match for '{searched_keyword}', but here is the closest matching product in our inventory:"
     - Present the found item(s) with Product Name, exact stock in PCS, price, costing (if asked), and photo (if requested).
     - Politely ask: "Did you mean this item?"
   - Never say an item was not found if nearest matching products were returned!

5. LANGUAGE ADAPTATION:
   - If the user asks in Nepali (e.g. "Malai rc item ko photo patahu" or "360-1 ko costing kati ho"), reply naturally in Nepali while listing all relevant details.
   - If the user asks in Hindi or English, respond in their respective language.

6. ACCURACY:
   - Only quote information retrieved from the database tools. If an item is not found, state it clearly.
"""

# Available models in priority order (fastest first)
MODEL_CANDIDATES = [
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
]

PHOTO_KEYWORDS = {
    "photo", "photos", "pic", "pics", "picture", "pictures",
    "image", "images", "img", "imgs", "snap", "snaps",
    "foto", "fotos", "futo", "futos", "poto", "potos", "phota", "fota",
    "tasbir", "tasvir", "tasveer", "chitra", "photu", "phpto"
}

def is_photo_requested(text: str) -> bool:
    """
    Determines if the user explicitly requested photos or used a spelling/typo similar to photo.
    Returns True ONLY if photo/pic intent is detected.
    """
    if not text:
        return False
    # Clean and tokenize words
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', text.lower())
    words = clean.split()

    # 1. Direct keyword match
    for w in words:
        if w in PHOTO_KEYWORDS:
            return True

    # 2. Check compound phrases or subwords
    text_lower = text.lower()
    for kw in ["photo", "foto", "tasbir", "tasvir", "picture", "chitra"]:
        if kw in text_lower:
            return True

    # 3. Fuzzy similarity for typos (e.g. 'phtoo', 'photu', 'pictur', 'fotu')
    targets = ["photo", "photos", "picture", "pictures", "image"]
    for w in words:
        if len(w) >= 4:
            for t in targets:
                ratio = difflib.SequenceMatcher(None, w, t).ratio()
                if ratio >= 0.75:
                    return True

    return False

def ask_hermes(user_message: str) -> Dict[str, Any]:
    """
    Sends a text query to Google Gemini with Supabase search and costing tools.
    Enforces that photos are only returned if the user explicitly requested them.
    Returns:
        {
            "reply": str, # Markdown text response
            "image_urls": list[str], # Extracted photo URLs for WhatsApp media
            "status": "success" | "error"
        }
    """
    client = get_gemini_client()
    last_err = None
    photo_wanted = is_photo_requested(user_message)

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

            if photo_wanted:
                # Extract image URLs from markdown for WhatsApp media sending
                image_urls = re.findall(r'!\[.*?\]\(((?:https?://|local://).*?\.(?:jpe?g|png|webp)|[^\s\)]+)\)', reply_text, re.IGNORECASE)
            else:
                # User did not request photos - strip any markdown images Gemini might have included
                reply_text = re.sub(r'!\[.*?\]\(((?:https?://|local://).*?\.(?:jpe?g|png|webp)|[^\s\)]+)\)\n?', '', reply_text, flags=re.IGNORECASE).strip()
                image_urls = []

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
