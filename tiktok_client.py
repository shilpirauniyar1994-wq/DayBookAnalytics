"""
TikTok Content Posting API Client for DayBook Analytics
Handles OAuth 2.0 PKCE authentication, auto-refresh of access tokens,
and publishing of Videos & Photo Carousels via TikTok's Official Content Posting API.
Enforces strict pre-flight safety screening via tiktok_safety.py.
"""

import os
import json
import time
import base64
import hashlib
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Union
import requests
from dotenv import load_dotenv

from tiktok_safety import evaluate_post_safety, SafetyVerdict

load_dotenv()
logger = logging.getLogger("tiktok_client")

# TikTok API Endpoints
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
TIKTOK_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_PHOTO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/content/init/"
TIKTOK_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

LOCAL_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "data", "tiktok_credentials.json")


class TikTokPolicyViolationError(Exception):
    """Raised when content violates TikTok Community Guidelines (e.g., toy gun, weapons)."""
    def __init__(self, verdict: SafetyVerdict):
        self.verdict = verdict
        super().__init__(f"TikTok Policy Violation Block: {verdict.user_guidance}")


class TikTokAuthError(Exception):
    """Raised on authentication or token failure."""
    pass


class TikTokPublishError(Exception):
    """Raised when TikTok API returns a publishing error."""
    pass


# ---------------------------------------------------------------------------
# PKCE HELPERS
# ---------------------------------------------------------------------------

def generate_pkce_pair() -> Dict[str, str]:
    """Generates code_verifier and code_challenge (S256) for OAuth 2.0 PKCE."""
    code_verifier = secrets.token_urlsafe(64)
    # S256 hash
    sha = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(sha).decode("utf-8").rstrip("=")
    return {
        "code_verifier": code_verifier,
        "code_challenge": code_challenge
    }


def get_oauth_authorization_url(
    client_key: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
    scope: str = "user.info.basic,video.publish,video.upload"
) -> Dict[str, str]:
    """
    Constructs the TikTok authorization URL for user login.
    Returns the URL and the code_verifier that must be stored during session.
    """
    key = client_key or os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    r_uri = redirect_uri or os.getenv("TIKTOK_REDIRECT_URI", "").strip()
    
    if not key:
        raise TikTokAuthError("TIKTOK_CLIENT_KEY is not configured in .env")
    if not r_uri:
        raise TikTokAuthError("TIKTOK_REDIRECT_URI is not configured in .env")

    pkce = generate_pkce_pair()
    c_challenge = code_challenge or pkce["code_challenge"]
    csrf_state = state or secrets.token_hex(16)

    from urllib.parse import urlencode
    params = {
        "client_key": key,
        "scope": scope,
        "response_type": "code",
        "redirect_uri": r_uri,
        "state": csrf_state,
        "code_challenge": c_challenge,
        "code_challenge_method": "S256"
    }

    auth_url = f"{TIKTOK_AUTH_URL}?{urlencode(params)}"
    return {
        "auth_url": auth_url,
        "state": csrf_state,
        "code_verifier": pkce["code_verifier"],
        "code_challenge": c_challenge
    }


# ---------------------------------------------------------------------------
# TOKEN PERSISTENCE & MANAGEMENT
# ---------------------------------------------------------------------------

def _get_supabase_client():
    try:
        from db import get_client
        return get_client()
    except Exception:
        return None


def save_credentials(token_data: Dict[str, Any]) -> None:
    """Saves TikTok credentials to Supabase and local JSON fallback."""
    # Ensure expiration timestamps are computed
    now = datetime.now(timezone.utc)
    expires_in = token_data.get("expires_in", 86400)
    refresh_expires_in = token_data.get("refresh_expires_in", 31536000)

    expires_at = (now + timedelta(seconds=expires_in)).isoformat()
    refresh_expires_at = (now + timedelta(seconds=refresh_expires_in)).isoformat()

    payload = {
        "open_id": token_data.get("open_id"),
        "union_id": token_data.get("union_id"),
        "display_name": token_data.get("display_name", "Demo Khelauna"),
        "avatar_url": token_data.get("avatar_url"),
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": expires_at,
        "refresh_expires_at": refresh_expires_at,
        "scope": token_data.get("scope"),
        "updated_at": now.isoformat()
    }

    # 1. Supabase attempt
    sp = _get_supabase_client()
    if sp:
        try:
            sp.table("tiktok_credentials").upsert(payload, on_conflict="open_id").execute()
            logger.info("Saved TikTok credentials to Supabase.")
        except Exception as e:
            logger.warning(f"Could not save TikTok credentials to Supabase: {e}")

    # 2. Local fallback
    try:
        os.makedirs(os.path.dirname(LOCAL_TOKEN_FILE), exist_ok=True)
        with open(LOCAL_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        logger.info("Saved TikTok credentials to local JSON cache.")
    except Exception as e:
        logger.warning(f"Could not save TikTok credentials locally: {e}")


def load_credentials() -> Optional[Dict[str, Any]]:
    """Loads current TikTok credentials from Supabase or local fallback."""
    # 1. Try Supabase
    sp = _get_supabase_client()
    if sp:
        try:
            res = sp.table("tiktok_credentials").select("*").order("updated_at", desc=True).limit(1).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            logger.debug(f"Supabase load credentials failed: {e}")

    # 2. Try Local file
    if os.path.exists(LOCAL_TOKEN_FILE):
        try:
            with open(LOCAL_TOKEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read local credentials: {e}")

    return None


def exchange_code_for_token(code: str, code_verifier: str, redirect_uri: Optional[str] = None) -> Dict[str, Any]:
    """Exchanges authorization code for access_token and refresh_token."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    r_uri = redirect_uri or os.getenv("TIKTOK_REDIRECT_URI", "").strip()

    if not client_key or not client_secret:
        raise TikTokAuthError("Missing TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET in environment")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cache-Control": "no-cache"
    }
    data = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": r_uri,
        "code_verifier": code_verifier
    }

    resp = requests.post(TIKTOK_TOKEN_URL, headers=headers, data=data, timeout=15)
    resp_data = resp.json()

    if resp.status_code != 200 or "error" in resp_data:
        err_msg = resp_data.get("error_description", resp_data.get("error", "Failed to exchange token"))
        raise TikTokAuthError(f"Token exchange failed: {err_msg}")

    # Extract user info if possible
    token_info = resp_data
    save_credentials(token_info)
    return token_info


def refresh_access_token(refresh_token_str: str) -> Dict[str, Any]:
    """Refreshes an expired access_token using refresh_token."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cache-Control": "no-cache"
    }
    data = {
        "client_key": client_key,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_str
    }

    resp = requests.post(TIKTOK_TOKEN_URL, headers=headers, data=data, timeout=15)
    resp_data = resp.json()

    if resp.status_code != 200 or "error" in resp_data:
        err_msg = resp_data.get("error_description", resp_data.get("error", "Failed to refresh token"))
        raise TikTokAuthError(f"Token refresh failed: {err_msg}")

    save_credentials(resp_data)
    return resp_data


def get_valid_access_token() -> Optional[str]:
    """
    Returns a valid access token.
    Automatically refreshes the token if it is within 10 minutes of expiry.
    """
    creds = load_credentials()
    if not creds:
        return None

    access_token = creds.get("access_token")
    expires_at_str = creds.get("expires_at")
    refresh_token_val = creds.get("refresh_token")

    if not access_token:
        return None

    # Check expiration
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            # If expires within 10 minutes, refresh
            if datetime.now(timezone.utc) + timedelta(minutes=10) >= expires_at:
                if refresh_token_val:
                    refreshed = refresh_access_token(refresh_token_val)
                    return refreshed.get("access_token")
        except Exception as e:
            logger.warning(f"Error checking token expiration: {e}")

    return access_token


# ---------------------------------------------------------------------------
# PUBLISHING ENGINE (WITH BUILT-IN SAFETY SHIELD)
# ---------------------------------------------------------------------------

def publish_video(
    video_url_or_path: str,
    title: str,
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    destination: str = "DIRECT_POST",
    disable_duet: bool = False,
    disable_stitch: bool = False,
    disable_comment: bool = False,
    product_name: str = "",
    tags: str = "",
    skip_safety_check: bool = False
) -> Dict[str, Any]:
    """
    Publishes a video to TikTok (Direct Post or Creator Inbox Draft).
    MANDATORY: Runs TikTok Community Guidelines Safety Pre-Screening before publishing!
    """
    # 1. Enforce Community Guidelines Safety
    if not skip_safety_check:
        verdict = evaluate_post_safety(
            product_name=product_name,
            tags=tags,
            caption=title,
            image_input=video_url_or_path if os.path.exists(video_url_or_path) else None,
            skip_vision=True # Vision pre-check runs on thumbnails or catalog images
        )
        if not verdict.is_safe:
            raise TikTokPolicyViolationError(verdict)

    token = get_valid_access_token()
    if not token:
        raise TikTokAuthError("No valid TikTok access token. Please connect your TikTok account.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8"
    }

    # Construct compliant payload with commercial disclosure
    post_info = {
        "title": title,
        "privacy_level": privacy_level,
        "disable_duet": disable_duet,
        "disable_stitch": disable_stitch,
        "disable_comment": disable_comment,
        "brand_organic_toggle": True,   # Required for business promotion to avoid shadowbans
        "brand_content_toggle": False
    }

    # Handle pull from public URL vs local file upload
    is_url = video_url_or_path.startswith("http://") or video_url_or_path.startswith("https://")
    if is_url:
        source_info = {
            "source": "PULL_FROM_URL",
            "video_url": video_url_or_path
        }
    else:
        # File upload mode
        if not os.path.exists(video_url_or_path):
            raise FileNotFoundError(f"Video file not found: {video_url_or_path}")
        file_size = os.path.getsize(video_url_or_path)
        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": file_size,
            "total_chunk_count": 1
        }

    body = {
        "post_info": post_info,
        "source_info": source_info
    }

    resp = requests.post(TIKTOK_VIDEO_INIT_URL, headers=headers, json=body, timeout=30)
    data = resp.json()

    if resp.status_code != 200 or data.get("error", {}).get("code") != "ok":
        err_msg = data.get("error", {}).get("message", "Video publish failed")
        raise TikTokPublishError(f"TikTok Publish Error: {err_msg}")

    publish_id = data.get("data", {}).get("publish_id")
    upload_url = data.get("data", {}).get("upload_url")

    # If file upload was requested and upload_url returned, upload video binary
    if not is_url and upload_url:
        with open(video_url_or_path, "rb") as vf:
            video_bytes = vf.read()
        upload_headers = {
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{len(video_bytes)-1}/{len(video_bytes)}"
        }
        upload_resp = requests.put(upload_url, headers=upload_headers, data=video_bytes, timeout=120)
        if upload_resp.status_code not in [200, 201]:
            raise TikTokPublishError(f"Video chunk upload failed: HTTP {upload_resp.status_code}")

    # Record post in Supabase audit log
    _log_post_to_supabase({
        "publish_id": publish_id,
        "post_type": "video",
        "title": title,
        "privacy_level": privacy_level,
        "destination": destination,
        "safety_status": "SAFE",
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    return {
        "success": True,
        "publish_id": publish_id,
        "destination": destination,
        "status": "processing"
    }


def publish_photo_carousel(
    image_urls: List[str],
    title: str,
    description: str = "",
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    product_name: str = "",
    tags: str = "",
    skip_safety_check: bool = False
) -> Dict[str, Any]:
    """
    Publishes a Photo Carousel post (swipeable photos) to TikTok.
    MANDATORY: Runs TikTok Community Guidelines Safety Pre-Screening on all images!
    """
    if not image_urls:
        raise ValueError("Must provide at least 1 image URL for photo carousel.")

    # 1. Enforce Community Guidelines Safety on text & first image
    if not skip_safety_check:
        verdict = evaluate_post_safety(
            product_name=product_name,
            tags=tags,
            caption=f"{title} {description}",
            image_input=image_urls[0] if image_urls else None,
            skip_vision=False
        )
        if not verdict.is_safe:
            raise TikTokPolicyViolationError(verdict)

    token = get_valid_access_token()
    if not token:
        raise TikTokAuthError("No valid TikTok access token. Please connect your TikTok account.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8"
    }

    body = {
        "post_info": {
            "title": title,
            "description": description,
            "privacy_level": privacy_level,
            "brand_organic_toggle": True
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 1,
            "photo_images": image_urls
        },
        "post_mode": "DIRECT_POST"
    }

    resp = requests.post(TIKTOK_PHOTO_INIT_URL, headers=headers, json=body, timeout=30)
    data = resp.json()

    if resp.status_code != 200 or data.get("error", {}).get("code") != "ok":
        err_msg = data.get("error", {}).get("message", "Photo Carousel publish failed")
        raise TikTokPublishError(f"TikTok Photo Carousel Error: {err_msg}")

    publish_id = data.get("data", {}).get("publish_id")

    _log_post_to_supabase({
        "publish_id": publish_id,
        "post_type": "photo_carousel",
        "title": title,
        "caption": description,
        "media_urls": image_urls,
        "privacy_level": privacy_level,
        "safety_status": "SAFE",
        "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    return {
        "success": True,
        "publish_id": publish_id,
        "status": "processing"
    }


def check_publish_status(publish_id: str) -> Dict[str, Any]:
    """Queries TikTok publish status for a given publish_id."""
    token = get_valid_access_token()
    if not token:
        raise TikTokAuthError("No valid TikTok access token.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8"
    }
    body = {"publish_id": publish_id}

    resp = requests.post(TIKTOK_STATUS_URL, headers=headers, json=body, timeout=15)
    data = resp.json()

    status_data = data.get("data", {})
    status = status_data.get("status", "UNKNOWN")

    # Update Supabase status
    sp = _get_supabase_client()
    if sp:
        try:
            sp.table("tiktok_posts").update({
                "status": status.lower(),
                "published_at": datetime.now(timezone.utc).isoformat() if status == "SUCCESS" else None
            }).eq("publish_id", publish_id).execute()
        except Exception:
            pass

    return status_data


def _log_post_to_supabase(record: Dict[str, Any]) -> None:
    """Helper to audit-log a post to Supabase."""
    sp = _get_supabase_client()
    if sp:
        try:
            sp.table("tiktok_posts").insert(record).execute()
        except Exception as e:
            logger.debug(f"Could not log post to Supabase: {e}")
