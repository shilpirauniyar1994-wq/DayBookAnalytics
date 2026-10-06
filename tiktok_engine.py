"""
TikTok Content & Video Generator Engine for DayBook Analytics (Demo Khelauna)
1. AI Copywriting: Generates viral hooks, wholesale captions, and hashtags using Gemini.
2. Video Reel Generator: Creates vertical 9:16 (720x1280) dynamic MP4 reels from product photos
   with smooth Ken Burns motion, blurred background framing, pricing cards, and WhatsApp CTAs.
3. Strict Safety: Enforces TikTok Community Guidelines pre-screening before generating any media.
"""

import os
import re
import json
import logging
from io import BytesIO
from typing import Dict, Any, List, Optional, Union, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
import cv2
import requests
from dotenv import load_dotenv

from tiktok_safety import evaluate_post_safety, screen_text_for_policy, SafetyVerdict
from tiktok_client import TikTokPolicyViolationError

load_dotenv()
logger = logging.getLogger("tiktok_engine")

# ---------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# ---------------------------------------------------------------------------
OUTPUT_WIDTH = 720
OUTPUT_HEIGHT = 1280
FPS = 24
SECONDS_PER_SLIDE = 3.5

DEFAULT_HASHTAGS = [
    "#demokhelauna", "#toysnepal", "#wholesaletoynepal",
    "#kathmandutoys", "#toyshopnepal", "#newarrivals", "#nepalbusiness"
]

DEFAULT_CONTACT = "+977 9803216856"
DEFAULT_BRAND = "DEMO KHELAUNA | WHOLESALE TOYS"


# ---------------------------------------------------------------------------
# 1. AI COPYWRITER (POWERED BY GEMINI)
# ---------------------------------------------------------------------------

def generate_tiktok_copy(
    product_name: str,
    category: str = "",
    price: Optional[float] = None,
    current_stock: Optional[float] = None,
    custom_notes: str = ""
) -> Dict[str, Any]:
    """
    Generates high-converting, policy-safe TikTok copywriting for Demo Khelauna:
    - Viral hook
    - Caption tailored to toy store owners, retailers, and gift shoppers in Nepal
    - Relevant hashtags
    - 3-4 short on-screen overlay text badges for the video reel
    """
    # 1. Immediate Safety Pre-check
    text_check = screen_text_for_policy(f"{product_name} {category} {custom_notes}")
    if text_check["violates"]:
        raise TikTokPolicyViolationError(
            SafetyVerdict(
                is_safe=False,
                status="BLOCKED",
                risk_level="HIGH",
                flags=text_check["flags"],
                reasons=[text_check["reason"]],
                user_guidance=f"Cannot generate TikTok copy for restricted item: {product_name}."
            )
        )

    # 2. Build Gemini prompt
    price_str = f"Rs. {int(round(price))}" if price and price > 0 else "Best Wholesale Rate"
    stock_str = f"{int(round(current_stock))} PCS in stock" if current_stock and current_stock > 0 else "In Stock"

    prompt = f"""You are the social media marketing director for Demo Khelauna, a leading wholesale toy and novelty importer located in Kathmandu, Nepal.
We sell wholesale to toy shops, stationery stores, gift centers, schools, and parents across all 7 provinces of Nepal.
Contact number for orders: +977 9803216856.

Generate an engaging, viral, policy-compliant TikTok post copy for this product:
- Product Name: {product_name}
- Category: {category or 'General Toys'}
- Wholesale Price: {price_str}
- Stock Availability: {stock_str}
- Extra Notes: {custom_notes or 'New arrival, wholesale bulk carton discounts available'}

RULES:
1. STRICT TIKTOK COMPLIANCE: Do NOT mention guns, weapons, warfare, or violence.
2. Tone: Exciting, energetic, trustworthy wholesale business. Use natural mix of English and popular Nepali terms (e.g. 'Dhamaka rate', 'Kathmandu ma wholesale', 'Delivery across Nepal').
3. Audience: Toy store retailers & parents looking for wholesale toy rates.

Respond strictly in valid JSON with this format:
{{
  "hook": "Short punchy 1-line hook (max 7 words)",
  "caption": "Full caption with product highlights, wholesale call-to-action, and phone number (max 30 words)",
  "hashtags": ["#demokhelauna", "#toysnepal", "#wholesaletoynepal", "#kathmandutoys", ...],
  "overlay_badges": [
    "Short 3-4 word phrase for slide 1",
    "Short 3-4 word phrase for slide 2 (e.g. Wholesale Rs. XXX)",
    "Short 3-4 word phrase for slide 3 (e.g. WhatsApp 9803216856)"
  ]
}}
"""

    try:
        from google import genai
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return _fallback_copy(product_name, price_str)

        client = genai.Client(api_key=api_key)
        model_candidates = ["gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"]
        res = None
        for m in model_candidates:
            try:
                res = client.models.generate_content(
                    model=m,
                    contents=prompt
                )
                if res and res.text:
                    break
            except Exception:
                continue

        if not res or not res.text:
            raise RuntimeError("Gemini returned empty response")

        clean_text = res.text.strip()
        clean_text = re.sub(r"^```json\s*", "", clean_text, flags=re.MULTILINE)
        clean_text = re.sub(r"^```\s*", "", clean_text, flags=re.MULTILINE)
        data = json.loads(clean_text)

        # Safety sanitize generated text
        full_gen = f"{data.get('hook', '')} {data.get('caption', '')} {' '.join(data.get('hashtags', []))}"
        post_check = screen_text_for_policy(full_gen)
        if post_check["violates"]:
            return _fallback_copy(product_name, price_str)

        return {
            "hook": data.get("hook", f"New Arrival: {product_name}"),
            "caption": data.get("caption", f"{product_name} now in stock at Demo Khelauna! Wholesale rates. WhatsApp: {DEFAULT_CONTACT}"),
            "hashtags": data.get("hashtags", DEFAULT_HASHTAGS),
            "overlay_badges": data.get("overlay_badges", [
                "Demo Khelauna Wholesale",
                f"Wholesale: {price_str}",
                f"WhatsApp: {DEFAULT_CONTACT}"
            ])
        }

    except Exception as e:
        logger.warning(f"Gemini copy generation failed: {e}. Using fallback.")
        return _fallback_copy(product_name, price_str)


def _fallback_copy(product_name: str, price_str: str) -> Dict[str, Any]:
    return {
        "hook": f"🔥 New Arrival: {product_name}!",
        "caption": f"Top quality {product_name} available at Demo Khelauna! Best wholesale prices in Kathmandu. Delivery all over Nepal 🚚. WhatsApp orders: {DEFAULT_CONTACT}",
        "hashtags": DEFAULT_HASHTAGS,
        "overlay_badges": [
            "Demo Khelauna Wholesale",
            f"Wholesale: {price_str}",
            f"Order: {DEFAULT_CONTACT}"
        ]
    }


# ---------------------------------------------------------------------------
# 2. IMAGE PREPARATION & FRAME COMPOSITION
# ---------------------------------------------------------------------------

def _load_image(img_input: Union[str, bytes, Image.Image]) -> Optional[Image.Image]:
    """Helper to load image from path, URL, bytes, or Image object."""
    try:
        if isinstance(img_input, Image.Image):
            return img_input.copy()
        elif isinstance(img_input, bytes):
            return Image.open(BytesIO(img_input))
        elif isinstance(img_input, str):
            if img_input.startswith("http://") or img_input.startswith("https://"):
                resp = requests.get(img_input, timeout=12)
                resp.raise_for_status()
                return Image.open(BytesIO(resp.content))
            elif os.path.exists(img_input):
                return Image.open(img_input)
    except Exception as e:
        logger.warning(f"Could not load image: {e}")
    return None


def _get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Attempts to load a standard system font, falls back to default."""
    font_names = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    ]
    for fn in font_names:
        try:
            return ImageFont.truetype(fn, size)
        except Exception:
            continue
    return ImageFont.load_default()


def create_blurred_background(img: Image.Image, width: int = OUTPUT_WIDTH, height: int = OUTPUT_HEIGHT) -> Image.Image:
    """Creates a stylish blurred, dimmed background canvas filling 9:16 vertical."""
    # Scale to fill canvas with crop
    aspect_target = width / height
    img_w, img_h = img.size
    aspect_img = img_w / img_h

    if aspect_img > aspect_target:
        new_h = height
        new_w = int(height * aspect_img)
    else:
        new_w = width
        new_h = int(width / aspect_img)

    bg = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    # Center crop
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    bg = bg.crop((left, top, left + width, top + height))

    # Heavy blur for modern aesthetic
    bg = bg.filter(ImageFilter.GaussianBlur(30))

    # Darken overlay (35% black) for contrast
    dark_overlay = Image.new("RGBA", (width, height), (0, 0, 0, 110))
    bg.paste(dark_overlay, (0, 0), dark_overlay)
    return bg.convert("RGB")


def render_single_frame(
    base_bg: Image.Image,
    product_img: Image.Image,
    scale: float,
    product_name: str,
    price_text: str,
    overlay_badge: str,
    brand_title: str = DEFAULT_BRAND,
    contact_text: str = DEFAULT_CONTACT
) -> np.ndarray:
    """
    Renders a single video frame with product image, smooth zoom,
    branding header, dynamic middle badge, and bottom pricing card.
    Returns RGB numpy array for OpenCV.
    """
    frame = base_bg.copy()

    # 1. Product Image with Zoom Scale (Ken Burns Effect)
    max_box_w = int(OUTPUT_WIDTH * 0.86)
    max_box_h = int(OUTPUT_HEIGHT * 0.48)

    p_w, p_h = product_img.size
    fit_scale = min(max_box_w / p_w, max_box_h / p_h) * scale
    draw_w = max(10, int(p_w * fit_scale))
    draw_h = max(10, int(p_h * fit_scale))

    scaled_p = product_img.resize((draw_w, draw_h), Image.Resampling.LANCZOS)

    # Center position of product
    center_y = int(OUTPUT_HEIGHT * 0.44)
    px = (OUTPUT_WIDTH - draw_w) // 2
    py = center_y - (draw_h // 2)

    # Optional white card background behind product for clean presentation
    card_margin = 14
    card_rect = [px - card_margin, py - card_margin, px + draw_w + card_margin, py + draw_h + card_margin]
    card_overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(card_overlay)
    c_draw.rounded_rectangle(card_rect, radius=20, fill=(255, 255, 255, 240))
    frame.paste(card_overlay, (0, 0), card_overlay)

    # Paste product
    if scaled_p.mode == "RGBA":
        frame.paste(scaled_p, (px, py), scaled_p)
    else:
        frame.paste(scaled_p, (px, py))

    draw = ImageDraw.Draw(frame)

    # 2. TOP BRANDING BANNER
    font_brand = _get_font(26, bold=True)
    brand_pill = [40, 50, OUTPUT_WIDTH - 40, 110]
    draw.rounded_rectangle(brand_pill, radius=30, fill=(20, 20, 20))
    # Brand text centered
    draw.text((OUTPUT_WIDTH // 2, 80), brand_title, fill=(255, 215, 0), font=font_brand, anchor="mm")

    # 3. DYNAMIC MIDDLE BADGE (HOOK / PROMO TEXT)
    if overlay_badge:
        font_badge = _get_font(30, bold=True)
        badge_y = py - card_margin - 55
        if badge_y < 125:
            badge_y = 135
        badge_rect = [60, badge_y - 25, OUTPUT_WIDTH - 60, badge_y + 25]
        draw.rounded_rectangle(badge_rect, radius=25, fill=(230, 40, 40))
        draw.text((OUTPUT_WIDTH // 2, badge_y), overlay_badge.upper(), fill=(255, 255, 255), font=font_badge, anchor="mm")

    # 4. BOTTOM INFO CARD (Product Name + Price + Stock)
    card_top = int(OUTPUT_HEIGHT * 0.70)
    card_bottom = int(OUTPUT_HEIGHT * 0.88)
    info_card = [30, card_top, OUTPUT_WIDTH - 30, card_bottom]
    draw.rounded_rectangle(info_card, radius=24, fill=(255, 255, 255))

    # Product Name
    font_name = _get_font(32, bold=True)
    draw.text((50, card_top + 30), product_name[:32], fill=(20, 20, 20), font=font_name)

    # Wholesale Price Pill
    font_price = _get_font(38, bold=True)
    draw.text((50, card_top + 80), price_text, fill=(0, 140, 50), font=font_price)

    # In Stock Badge
    font_stock = _get_font(20, bold=True)
    stock_rect = [OUTPUT_WIDTH - 210, card_top + 80, OUTPUT_WIDTH - 50, card_top + 120]
    draw.rounded_rectangle(stock_rect, radius=15, fill=(220, 245, 220))
    draw.text((OUTPUT_WIDTH - 130, card_top + 100), "IN STOCK 📦", fill=(20, 120, 30), font=font_stock, anchor="mm")

    # 5. FOOTER CALL-TO-ACTION (WhatsApp & Delivery)
    footer_rect = [30, OUTPUT_HEIGHT - 100, OUTPUT_WIDTH - 30, OUTPUT_HEIGHT - 40]
    draw.rounded_rectangle(footer_rect, radius=25, fill=(37, 211, 102))  # WhatsApp green
    font_footer = _get_font(24, bold=True)
    footer_msg = f"📱 WhatsApp Orders: {contact_text} | Nepal-wide 🚚"
    draw.text((OUTPUT_WIDTH // 2, OUTPUT_HEIGHT - 70), footer_msg, fill=(255, 255, 255), font=font_footer, anchor="mm")

    return np.array(frame)


# ---------------------------------------------------------------------------
# 3. VIDEO REEL GENERATOR (9:16 VERTICAL MP4)
# ---------------------------------------------------------------------------

def render_vertical_reel(
    image_sources: List[Union[str, bytes, Image.Image]],
    product_name: str,
    price: Optional[float] = None,
    current_stock: Optional[float] = None,
    output_path: Optional[str] = None,
    overlay_badges: Optional[List[str]] = None,
    seconds_per_slide: float = SECONDS_PER_SLIDE,
    skip_safety_check: bool = False
) -> Dict[str, Any]:
    """
    Renders a vertical 9:16 MP4 reel ready for TikTok.
    - Features Ken Burns smooth zoom animation
    - Blended background
    - Product detail card and wholesale pricing
    - WhatsApp order badge
    - Pre-flight TikTok Community Guidelines verification
    """
    if not image_sources:
        raise ValueError("Must provide at least 1 image source to render video reel.")

    # 1. Enforce Community Guidelines Safety
    if not skip_safety_check:
        verdict = evaluate_post_safety(
            product_name=product_name,
            image_input=image_sources[0],
            skip_vision=False
        )
        if not verdict.is_safe:
            raise TikTokPolicyViolationError(verdict)

    # 2. Load and validate images
    loaded_images = []
    for src in image_sources:
        img = _load_image(src)
        if img:
            loaded_images.append(img.convert("RGBA"))

    if not loaded_images:
        raise ValueError("None of the provided image sources could be loaded.")

    # 3. Output file path
    if not output_path:
        os.makedirs("data/tiktok_renders", exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', product_name)[:20]
        output_path = f"data/tiktok_renders/reel_{safe_name}_{int(np.random.randint(1000, 9999))}.mp4"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 4. Prepare text elements
    price_text = f"Wholesale: Rs. {int(round(price))}" if price and price > 0 else "Best Wholesale Rate"
    badges = overlay_badges or [
        "DEMO KHELAUNA WHOLESALE",
        f"{price_text}",
        f"WHATSAPP: {DEFAULT_CONTACT}"
    ]

    # 5. Initialize OpenCV VideoWriter
    # Use MP4V codec (broadest cross-platform compatibility)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, FPS, (OUTPUT_WIDTH, OUTPUT_HEIGHT))

    frames_per_slide = int(FPS * seconds_per_slide)

    try:
        for idx, p_img in enumerate(loaded_images):
            # Pre-compute blurred background once per slide
            base_bg = create_blurred_background(p_img.convert("RGB"))
            current_badge = badges[idx % len(badges)]

            # Generate frames with Ken Burns Zoom (1.0 -> 1.08)
            for f_idx in range(frames_per_slide):
                progress = f_idx / frames_per_slide
                zoom_scale = 1.0 + (0.08 * progress)

                # Render PIL frame
                frame_rgb = render_single_frame(
                    base_bg=base_bg,
                    product_img=p_img,
                    scale=zoom_scale,
                    product_name=product_name,
                    price_text=price_text,
                    overlay_badge=current_badge
                )

                # Convert RGB to BGR for OpenCV
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                out.write(frame_bgr)

    finally:
        out.release()

    total_duration = len(loaded_images) * seconds_per_slide
    file_size_bytes = os.path.getsize(output_path) if os.path.exists(output_path) else 0

    return {
        "success": True,
        "video_path": os.path.abspath(output_path),
        "duration_seconds": total_duration,
        "file_size_bytes": file_size_bytes,
        "product_name": product_name,
        "resolution": f"{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}",
        "fps": FPS
    }
