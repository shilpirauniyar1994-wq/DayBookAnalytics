import os
import json
import re
import difflib
from typing import Optional
from dotenv import load_dotenv
from hermes_tools import search_products

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

MODEL_NAME = "upstage/solar-pro-3"

_client = None

def _get_openrouter_client():
    global _client
    if _client is None:
        if not OPENROUTER_API_KEY:
            raise ValueError("OPENROUTER_API_KEY is missing from your .env file!")
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("openai package is not installed. Run `pip install openai` to use hermes_agent.")
        _client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    return _client

KNOWN_TAGS = {
    "RC", "DOLL", "GUN", "PATTA", "MELA", "CAR", "CLAY", "FACTORY",
    "INDIAN", "BATTERY", "BIRTHDAY", "CANDLE", "STATIONERY", "DOZER",
    "BALL", "BALLOON", "RIDEON", "DORI", "FANCY"
}

def extract_keyword_from_text(text: str) -> Optional[str]:
    """Fallback extractor to automatically rescue lazy LLM calls."""
    stop_words = {
        'give', 'me', 'photos', 'photo', 'item', 'items', 'show', 'of', 'in',
        'stock', 'the', 'what', 'is', 'price', 'do', 'you', 'have', 'any',
        'please', 'can', 'with', 'picture', 'pictures', 'i', 'want', 'see',
        'to', 'for', 'a', 'an', 'are', 'there'
    }
    clean = re.sub(r'[^a-zA-Z0-9\s-]', ' ', text).strip()
    words = [w for w in clean.split() if w.lower() not in stop_words]
    for w in words:
        if w.upper() in KNOWN_TAGS:
            return w.upper()
    return words[0] if words else None

SYSTEM_PROMPT = """You are Hermes, the intelligent inventory and sales assistant for Demo Khelauna (Wholesale Toys & Party Supplies).
Your job is to look up live stock levels, wholesale prices, and share product photos from our Supabase database.

Rules:
1. SEARCHING:
   - When the user asks for a category, product name, or tag (e.g. "RC", "DOLL", "GUN", "360-1", "CAR"):
     You MUST call `search_products` with `search_term="<keyword>"`.
     Example: For "RC items", call `search_products(search_term="RC", has_photo_only=True)`.
   - NEVER call `search_products` without setting `search_term`!
   - NEVER mislabel an unrelated item (like a flower or candle) as an RC item or toy!

2. PHOTO RENDERING:
   Whenever the user asks for photos or pictures:
   - Call `search_products` with `has_photo_only=True`.
   - Embed each photo in Markdown: ![Product Name](image_url)
   - Always display Product Name, Stock (PCS), and Wholesale Selling Price (Rs.) alongside the photo.

3. MISSPELLED TAGS:
   If `search_products` returns `items: []` and provides `suggested_tags`:
   - Ask if the user meant one of the suggested tags (e.g. "Did you mean DOLL?").
   - Offer the suggested tags to choose from.

4. STOCK STATUS:
   - If stock > 0: State "In Stock: X PCS".
   - If stock <= 0: State "Currently Out of Stock".
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Look up product inventory, live stock balance, wholesale selling prices, and product photo URLs from Supabase. Searches across product names and category tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "REQUIRED. The product name, keyword, or category tag to search for (e.g. 'RC', 'DOLL', 'GUN', '360-1', 'Clay', 'Car')."
                    },
                    "in_stock_only": {
                        "type": "boolean",
                        "description": "Whether to return only items currently in stock. Defaults to true."
                    },
                    "has_photo_only": {
                        "type": "boolean",
                        "description": "Whether to return only items with photos. Set true when user asks for photos or pictures."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of products to return (default 4)."
                    }
                },
                "required": ["search_term"]
            }
        }
    }
]

def chat_with_hermes():
    print("=" * 65)
    print(">> Hermes AI Agent is Ready! (Powered by Solar Pro & Supabase)")
    print(">> Type your question (or type 'exit' to quit)")
    print("=" * 65)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit", "q"]:
                print("Goodbye!")
                break

            messages.append({"role": "user", "content": user_input})
            print("\nHermes is searching...")

            response = _get_openrouter_client().chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
            )

            response_msg = response.choices[0].message

            if response_msg.tool_calls:
                messages.append(response_msg)

                for tool_call in response_msg.tool_calls:
                    func_name = tool_call.function.name
                    func_args = json.loads(tool_call.function.arguments)

                    # Auto-rescue if LLM omitted search_term
                    if func_name == "search_products":
                        k = func_args.get("search_term") or func_args.get("keyword") or func_args.get("query") or func_args.get("tag")
                        if not k or str(k).strip() in ["", "none", "null", "all"]:
                            auto_k = extract_keyword_from_text(user_input)
                            if auto_k:
                                print(f" -> [Auto-Detected Missing Search Term]: '{auto_k}'")
                                func_args["search_term"] = auto_k

                    print(f" -> [Tool Calling Supabase] {func_name}({func_args})")

                    if func_name == "search_products":
                        tool_result = search_products(**func_args)
                    else:
                        tool_result = {"error": "Unknown tool"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result),
                    })

                final_response = _get_openrouter_client().chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages,
                )
                reply = final_response.choices[0].message.content
            else:
                reply = response_msg.content

            messages.append({"role": "assistant", "content": reply})
            print(f"\nHermes:\n{reply}\n")

        except Exception as e:
            print(f"\n[Error] {e}")

if __name__ == "__main__":
    chat_with_hermes()
