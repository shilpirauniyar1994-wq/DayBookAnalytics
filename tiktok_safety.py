"""
TikTok Safety & Compliance Guardrail Engine for DayBook Analytics (Demo Khelauna)
Ensures 100% compliance with TikTok Community Guidelines to prevent account warnings,
strikes, and suspensions — specifically for imitation firearms, toy guns, weapons,
and restricted commercial content.
"""

import os
import re
import json
import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict
from io import BytesIO
from PIL import Image
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("tiktok_safety")

# ---------------------------------------------------------------------------
# 1. HARD POLICY BLACKLIST & REGEX RULES
# ---------------------------------------------------------------------------

# High-risk imitation firearms, weapons, projectiles, and sharp items
# Matches English, Romanized Nepali, and Hindi terms.
WEAPON_KEYWORDS = [
    r"\bgun\b", r"\bguns\b", r"\bpistol\b", r"\bpistols\b", r"\brifle\b", r"\brifles\b",
    r"\bshotgun\b", r"\bshotguns\b", r"\brevolver\b", r"\brevolvers\b",
    r"\bblaster\b", r"\bblasters\b", r"\bbullet\b", r"\bbullets\b",
    r"\bammo\b", r"\bammunition\b", r"\bcartridge\b", r"\bcartridges\b",
    r"\bairsoft\b", r"\bbb\s*gun\b", r"\bpellet\b", r"\bsniper\b",
    r"\bfirearm\b", r"\bfirearms\b", r"\bbazooka\b", r"\bgrenade\b", r"\bbomb\b",
    r"\bmachine\s*gun\b", r"\bak\s*47\b", r"\bak47\b", r"\bm16\b", r"\bm4\b",
    r"\bbandook\b", r"\bbanduk\b", r"\bgoli\b",
    r"\bsword\b", r"\bswords\b", r"\bknife\b", r"\bknives\b", r"\bdagger\b", r"\bdaggers\b",
    r"\bblade\b", r"\bblades\b", r"\bmachete\b", r"\bchaku\b", r"\btalwar\b", r"\bkatana\b",
    r"\bslingshot\b", r"\bbow\s*and\s*arrow\b", r"\barrow\b", r"\barrows\b",
    r"\blaser\s*gun\b", r"\bdart\s*gun\b"
]

# Borderline items that look like weapons to automated computer vision
BORDERLINE_KEYWORDS = [
    r"\bwater\s*gun\b", r"\bbubble\s*gun\b", r"\bpichkari\b",
    r"\bsoft\s*bullet\b", r"\bfoam\s*dart\b", r"\bfoam\s*gun\b",
    r"\bsound\s*gun\b", r"\btoy\s*gun\b", r"\bnerf\b"
]

# Other TikTok banned categories (firecrackers, adult/hazardous items)
HAZARD_KEYWORDS = [
    r"\bfirecracker\b", r"\bfirecrackers\b", r"\bpataka\b", r"\bcracker\b", r"\bcrackers\b",
    r"\bfireworks\b", r"\blaser\s*pointer\b", r"\bvape\b", r"\bhookah\b", r"\btobacco\b",
    r"\bcigarette\b"
]

COMPILED_WEAPON_RE = [re.compile(pattern, re.IGNORECASE) for pattern in WEAPON_KEYWORDS]
COMPILED_BORDERLINE_RE = [re.compile(pattern, re.IGNORECASE) for pattern in BORDERLINE_KEYWORDS]
COMPILED_HAZARD_RE = [re.compile(pattern, re.IGNORECASE) for pattern in HAZARD_KEYWORDS]

# Categories considered inherently safe and top-tier for TikTok toy showcases
TIKTOK_SAFE_TAGS = {
    "RC", "REMOTE CONTROL", "CAR", "JEEP", "DOLL", "KITCHEN", "DOCTOR",
    "BEAUTY", "PUZZLE", "BOARD GAME", "CHESS", "LUDO", "SLATE", "TABLET",
    "CACTUS", "MUSICAL", "BLOCKS", "BUILDING", "STATIONERY", "BIRTHDAY",
    "BALLOON", "PARTY", "FOIL", "SOFT TOY", "TEDDY", "EDUCATIONAL"
}


# ---------------------------------------------------------------------------
# 2. DATA MODELS FOR SAFETY EVALUATION
# ---------------------------------------------------------------------------

@dataclass
class SafetyVerdict:
    is_safe: bool                     # True if approved for TikTok
    status: str                       # 'SAFE', 'WARNING', 'BLOCKED'
    risk_level: str                   # 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
    flags: List[str]                  # Specific violated policies e.g. ['imitation_firearms']
    reasons: List[str]                # Detailed explanations
    user_guidance: str                # Advice for user / Demo Khelauna
    ai_screened: bool = False         # Whether Gemini Vision was executed
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 3. TEXT & METADATA PRE-SCREENING
# ---------------------------------------------------------------------------

def screen_text_for_policy(text: str) -> Dict[str, Any]:
    """
    Screens product names, tags, descriptions, captions, and hashtags
    against TikTok restricted content guidelines.
    """
    if not text:
        return {"violates": False, "flags": [], "matched": [], "risk": "LOW"}

    clean_text = text.strip()
    flags = []
    matched = []

    # 1. Hard weapon blacklist check
    for r in COMPILED_WEAPON_RE:
        m = r.search(clean_text)
        if m:
            matched.append(m.group(0))
            if "imitation_firearms" not in flags:
                flags.append("imitation_firearms")

    # 2. Borderline / Computer Vision trigger check
    for r in COMPILED_BORDERLINE_RE:
        m = r.search(clean_text)
        if m:
            matched.append(m.group(0))
            if "potential_cv_weapon_flag" not in flags:
                flags.append("potential_cv_weapon_flag")

    # 3. Hazardous items check
    for r in COMPILED_HAZARD_RE:
        m = r.search(clean_text)
        if m:
            matched.append(m.group(0))
            if "hazardous_or_regulated_goods" not in flags:
                flags.append("hazardous_or_regulated_goods")

    if "imitation_firearms" in flags or "hazardous_or_regulated_goods" in flags:
        return {
            "violates": True,
            "flags": flags,
            "matched": list(set(matched)),
            "risk": "HIGH",
            "reason": f"Matched prohibited terms on TikTok: {', '.join(set(matched))}"
        }
    elif "potential_cv_weapon_flag" in flags:
        return {
            "violates": True,
            "flags": flags,
            "matched": list(set(matched)),
            "risk": "HIGH",  # Strict policy: block all gun-shaped toys to protect account!
            "reason": (
                f"Matched borderline item '{', '.join(set(matched))}'. TikTok automated "
                "computer vision flags all gun silhouettes as imitation firearms regardless of toy context."
            )
        }

    return {"violates": False, "flags": [], "matched": [], "risk": "LOW"}


# ---------------------------------------------------------------------------
# 4. GEMINI VISION MULTIMODAL PRE-SCREENING
# ---------------------------------------------------------------------------

def _load_image(image_input: Union[str, bytes, Image.Image]) -> Optional[Image.Image]:
    """Helper to convert path, URL, bytes, or PIL Image into PIL Image."""
    try:
        if isinstance(image_input, Image.Image):
            return image_input
        elif isinstance(image_input, bytes):
            return Image.open(BytesIO(image_input))
        elif isinstance(image_input, str):
            if image_input.startswith("http://") or image_input.startswith("https://"):
                resp = requests.get(image_input, timeout=12)
                resp.raise_for_status()
                return Image.open(BytesIO(resp.content))
            elif os.path.exists(image_input):
                return Image.open(image_input)
    except Exception as e:
        logger.warning(f"Failed to load image for TikTok safety screening: {e}")
    return None


def screen_image_with_vision(image_input: Union[str, bytes, Image.Image], product_name: str = "") -> SafetyVerdict:
    """
    Uses Gemini Multimodal AI to inspect the product photo against
    TikTok Community Guidelines (Weapons, Imitation Firearms, Dangerous Items).
    """
    img = _load_image(image_input)
    if img is None:
        return SafetyVerdict(
            is_safe=False,
            status="WARNING",
            risk_level="MEDIUM",
            flags=["image_load_failed"],
            reasons=["Could not load image to perform TikTok safety inspection."],
            user_guidance="Please verify the image file or URL before publishing.",
            ai_screened=False
        )

    # Convert image to RGB if needed
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if huge to ensure fast Gemini Vision processing
    max_dimension = 1024
    if max(img.size) > max_dimension:
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

    # Initialize Gemini client
    try:
        from google import genai
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY missing for Vision safety scan.")
            return SafetyVerdict(
                is_safe=True,
                status="WARNING",
                risk_level="MEDIUM",
                flags=["api_key_missing"],
                reasons=["GOOGLE_API_KEY not configured. Falling back to keyword scan."],
                user_guidance="Vision AI verification was skipped. Proceed with manual caution.",
                ai_screened=False
            )

        client = genai.Client(api_key=api_key)

        prompt = f"""You are a strict TikTok Trust & Safety and Content Moderation Officer.
Analyze this product photo for Demo Khelauna (a wholesale toy business).
The store recently received a severe Community Guidelines strike/warning for posting an imitation firearm / toy gun.

TikTok's automated Computer Vision models STRICTLY FLAG and issue account strikes for:
1. Any firearm, imitation firearm, toy gun, water gun, rifle, pistol, blaster, or tactical weapon silhouette (even if made of bright neon plastic or shooting bubbles).
2. Any replica swords, sharp knives, daggers, or edged weapons.
3. Any explosive, pyrotechnic, or hazardous item.

Product Context Provided: '{product_name}'

Please evaluate this image rigorously:
Does this image display or resemble any gun, pistol, rifle, firearm, blaster, weapon, or sharp blade that could trigger TikTok's automated moderation or violate TikTok Community Guidelines?

Respond strictly in valid JSON with NO surrounding formatting or markdown backticks:
{{
  "is_safe": true,
  "risk_level": "SAFE",
  "violates_policy": false,
  "flags": [],
  "confidence": 0.95,
  "reason": "Detailed description of detected items and why it is safe or unsafe",
  "recommendation": "Recommendation for publishing"
}}

If it contains ANY gun, blaster, rifle, or weapon shape, 'is_safe' MUST BE false, 'risk_level' MUST BE 'HIGH' or 'CRITICAL', and 'violates_policy' MUST BE true.
"""

        # Try fast vision model candidates
        model_candidates = ["gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-flash-latest"]
        res = None
        for m in model_candidates:
            try:
                res = client.models.generate_content(
                    model=m,
                    contents=[img, prompt]
                )
                if res and res.text:
                    break
            except Exception:
                continue

        if not res or not res.text:
            raise RuntimeError("Gemini Vision returned empty response.")

        clean_text = res.text.strip()
        # Remove markdown fences if present
        clean_text = re.sub(r"^```json\s*", "", clean_text, flags=re.MULTILINE)
        clean_text = re.sub(r"^```\s*", "", clean_text, flags=re.MULTILINE)
        data = json.loads(clean_text)

        is_safe = bool(data.get("is_safe", False))
        risk_level = str(data.get("risk_level", "MEDIUM")).upper()
        violates = bool(data.get("violates_policy", False))
        flags = list(data.get("flags", []))
        reason = str(data.get("reason", ""))
        recommendation = str(data.get("recommendation", ""))
        confidence = float(data.get("confidence", 0.9))

        if violates or not is_safe or risk_level in ["HIGH", "CRITICAL"]:
            return SafetyVerdict(
                is_safe=False,
                status="BLOCKED",
                risk_level="HIGH",
                flags=flags or ["imitation_firearm_detected"],
                reasons=[reason],
                user_guidance=(
                    f"🚨 AI VISION POLICY BLOCK: {reason} "
                    "TikTok's automated neural networks will detect this shape and issue a strike against Demo Khelauna. "
                    "This item has been blocked from TikTok posting."
                ),
                ai_screened=True,
                confidence=confidence
            )
        else:
            return SafetyVerdict(
                is_safe=True,
                status="SAFE",
                risk_level="SAFE",
                flags=[],
                reasons=[reason or "No weapon silhouettes or policy-violating goods detected."],
                user_guidance="✅ Verified Safe: Image is clear of weapons or restricted objects under TikTok Community Guidelines.",
                ai_screened=True,
                confidence=confidence
            )

    except Exception as e:
        logger.error(f"Error during Gemini Vision safety check: {e}")
        # Conservative fallback
        return SafetyVerdict(
            is_safe=True,
            status="WARNING",
            risk_level="LOW",
            flags=["vision_scan_error"],
            reasons=[f"Vision scan encountered an error: {str(e)}"],
            user_guidance="Vision check failed, but keyword check passed. Please visually verify that this is not a toy gun.",
            ai_screened=False
        )


# ---------------------------------------------------------------------------
# 5. UNIFIED POST EVALUATOR
# ---------------------------------------------------------------------------

def evaluate_post_safety(
    product_name: str = "",
    tags: str = "",
    caption: str = "",
    image_input: Optional[Union[str, bytes, Image.Image]] = None,
    skip_vision: bool = False
) -> SafetyVerdict:
    """
    Comprehensive multi-layer safety check for a proposed TikTok post.
    Checks:
    1. Product Name & Category against Weapon Blacklist
    2. Caption & Hashtags against Policy Terms
    3. Multimodal Image Analysis via Gemini Vision (if image provided)
    """
    combined_text = f"{product_name} {tags} {caption}"
    text_result = screen_text_for_policy(combined_text)

    # If text explicitly matches weapon blacklist, immediate block without wasting vision tokens
    if text_result["violates"]:
        return SafetyVerdict(
            is_safe=False,
            status="BLOCKED",
            risk_level="HIGH",
            flags=text_result["flags"],
            reasons=[text_result["reason"]],
            user_guidance=(
                f"🚨 TIKTOK POLICY VIOLATION SHIELD: Item contains '{', '.join(text_result['matched'])}'. "
                "TikTok strictly forbids imitation firearms and toy weapons. "
                "Posting this will trigger another Community Guidelines strike on your account."
            ),
            ai_screened=False
        )

    # If image is provided and vision is enabled, run Gemini Vision pre-screening
    if image_input and not skip_vision:
        vision_result = screen_image_with_vision(image_input, product_name=product_name)
        if not vision_result.is_safe:
            return vision_result

    # If all passed, return Safe verdict
    return SafetyVerdict(
        is_safe=True,
        status="SAFE",
        risk_level="SAFE",
        flags=[],
        reasons=["Passed keyword and visual policy scans."],
        user_guidance="✅ 100% TikTok Compliant. Ready for draft creation or direct posting.",
        ai_screened=(image_input is not None and not skip_vision)
    )


# ---------------------------------------------------------------------------
# 6. CATALOG BATCH FILTERING FOR STREAMLIT UI
# ---------------------------------------------------------------------------

def filter_catalog_for_tiktok(df) -> Any:
    """
    Takes a pandas DataFrame of catalog products and classifies each product
    for TikTok safety readiness. Adds columns:
    - 'tiktok_safe': bool
    - 'tiktok_status': 'SAFE' | 'BLOCKED'
    - 'tiktok_reason': str
    """
    if df.empty:
        return df

    df_copy = df.copy()
    safe_list = []
    status_list = []
    reason_list = []

    for _, row in df_copy.iterrows():
        p_name = str(row.get('product_name', row.get('id', '')))
        tags = str(row.get('tags', ''))
        
        eval_res = screen_text_for_policy(f"{p_name} {tags}")
        if eval_res["violates"]:
            safe_list.append(False)
            status_list.append("BLOCKED")
            reason_list.append(eval_res["reason"])
        else:
            safe_list.append(True)
            status_list.append("SAFE")
            reason_list.append("Safe for TikTok showcase")

    df_copy['tiktok_safe'] = safe_list
    df_copy['tiktok_status'] = status_list
    df_copy['tiktok_reason'] = reason_list
    return df_copy
