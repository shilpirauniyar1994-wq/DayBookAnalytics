"""
Google Hermes Engine — Powered by Google Gemini & Primary Supabase Database
Provides intelligent catalog querying, live stock lookups, wholesale pricing,
and photo retrieval using Google Gemini's native tool calling.
"""

import os
import re
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from hermes_tools import search_products

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
Your job is to look up live stock levels, wholesale prices, and share product photos from our Supabase database.

Rules:
1. TOOL CALLING:
   - When the user asks for items, stock, prices, or photos, ALWAYS call `search_products`.
   - Default search limit is 15. If the user asks for "all" items or a broad catalog list, specify `limit=20` or `limit=25`.
   - Example: If user asks for "RC items" or "give me rc item photos", call `search_products(search_term="RC", has_photo_only=True, limit=15)`.
   - Example: If user asks for "all mala items", call `search_products(search_term="MALA", has_photo_only=True, limit=25)`.
   - Example: If user asks for "360-1", call `search_products(search_term="360-1")`.

2. PHOTO RENDERING & CATALOG PRESENTATION:
   - If user asks for photos or pictures, call `search_products(has_photo_only=True)`.
   - ALWAYS PRESENT ALL ITEMS RETURNED BY THE TOOL. Do NOT artificially truncate after 4 or 5 items! If the tool returns 10, 15, or 20 items, display ALL of them.
   - For each item, embed each photo in Markdown format: ![Product Name](image_url)
   - Always display Product Name, Stock (in PCS), and Wholesale Selling Price (in Rs.) alongside the photo.
   - State the total count found at the beginning (e.g. "Found 10 matching RC items in stock:"). If only a few items exist (e.g. 4 items), explain that these are all the available products currently in stock.

3. SMART NEAREST-MATCH & TYPO HANDLING:
   - Wholesale customers frequently type typos, missing spaces, missing hyphens, or colloquial terms (e.g. 'BF430', '3601', '3333', 'batry car', 'candel', 'watergan', 'gudiya', 'gaadi').
   - When `search_products` returns `is_nearest_match=True`:
     - Clearly explain: "I couldn't find an exact match for '{searched_keyword}', but here is the closest matching product in our inventory:"
     - Present the found item(s) with Product Name, exact stock in PCS, wholesale price, and photo.
     - Politely ask: "Did you mean this item?"
   - Never say an item was not found if `search_products` returned nearest matching products!

4. LANGUAGE ADAPTATION:
   - If the user asks in Nepali (e.g. "Malai rc item ko photo patahu" or "BF430 ko stock kati cha"), reply naturally in Nepali while listing all products and photos.
   - If the user asks in Hindi or English, respond in their respective language.

5. ACCURACY:
   - Only return genuine matching products from the database tool. Never invent or re-label unrelated products!
"""

# Available models in priority order
MODEL_CANDIDATES = [
    "gemini-3.1-flash-lite-preview",
    "gemini-flash-latest",
    "gemini-3.5-flash",
]

def ask_hermes(user_message: str) -> Dict[str, Any]:
    """
    Sends a query to Google Gemini with Supabase search tool.
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
                    tools=[search_products],
                    system_instruction=SYSTEM_INSTRUCTION,
                )
            )

            reply_text = response.text or ""

            # Extract image URLs from markdown for WhatsApp media sending
            image_urls = re.findall(r'!\[.*?\]\((https?://[^\s\)]+)\)', reply_text)

            return {
                "reply": reply_text,
                "image_urls": image_urls,
                "model_used": model_name,
                "status": "success"
            }
        except Exception as e:
            last_err = e
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
