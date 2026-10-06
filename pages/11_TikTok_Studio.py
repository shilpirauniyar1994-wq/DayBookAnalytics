"""
DayBook Analytics — TikTok Marketing Studio (Demo Khelauna)
Enables automated, policy-safe video reel creation, AI copywriting,
and TikTok publishing (Direct Post or Creator Inbox Drafts).
Guards against TikTok Community Guidelines violations with real-time pre-moderation.
"""

import os
import sys
import json
import time
from typing import Dict, Any, List, Optional
import streamlit as st
import pandas as pd
from PIL import Image

from ui_utils import apply_global_styles
from tiktok_safety import (
    evaluate_post_safety,
    screen_text_for_policy,
    screen_image_with_vision,
    filter_catalog_for_tiktok,
    SafetyVerdict
)
from tiktok_engine import generate_tiktok_copy, render_vertical_reel
from tiktok_client import (
    load_credentials,
    save_credentials,
    get_oauth_authorization_url,
    exchange_code_for_token,
    publish_video,
    publish_photo_carousel,
    check_publish_status,
    TikTokPolicyViolationError,
    TikTokAuthError,
    TikTokPublishError
)

# Page configuration
st.set_page_config(
    page_title="TikTok Studio — DayBook Analytics",
    page_icon="🎵",
    layout="wide"
)

apply_global_styles()

# Custom Styling for TikTok Studio
st.markdown("""
<style>
    .tt-header {
        font-size: 1.85rem;
        font-weight: 800;
        color: #0F172A;
        margin-bottom: 0.2rem;
    }
    .tt-sub {
        font-size: 0.95rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .shield-badge-safe {
        background-color: #ECFDF5;
        border: 1px solid #10B981;
        color: #065F46;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .shield-badge-blocked {
        background-color: #FEF2F2;
        border: 1px solid #EF4444;
        color: #991B1B;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .metric-card-tt {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# CATALOG LOADER HELPER
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_tiktok_catalog():
    """Loads products from Bafa/Supabase catalog and tags with TikTok safety status."""
    try:
        from HermesData.catalog_reader import get_all_catalog_products
        df = get_all_catalog_products()
        if not df.empty:
            df = filter_catalog_for_tiktok(df)
            return df
    except Exception as e:
        st.warning(f"Could not load Bafa catalog: {e}")

    # Fallback minimal df
    return pd.DataFrame()


def get_clean_image_source(raw_url: Any, product_name: str = "") -> Optional[str]:
    """Returns valid string image URL or local file path, or None if invalid/missing/NaN."""
    if raw_url is not None and not pd.isna(raw_url):
        raw_str = str(raw_url).strip()
        if raw_str and raw_str.lower() not in ["none", "nan", "null", ""]:
            return raw_str

    # Fallback to local image index in HermesData/assets/images
    try:
        from hermes_tools import resolve_product_image, LOCAL_IMAGE_DIR
        resolved = resolve_product_image(product_name, None)
        if resolved and resolved.startswith("local://"):
            local_name = resolved.replace("local://", "")
            local_path = os.path.join(LOCAL_IMAGE_DIR, local_name)
            if os.path.exists(local_path):
                return local_path
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# HEADER & TOP STATUS BAR
# ---------------------------------------------------------------------------
col_head1, col_head2 = st.columns([3, 1])

with col_head1:
    st.markdown('<div class="tt-header">🎵 TikTok Marketing Studio</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="tt-sub">Auto-generate 9:16 vertical reels, AI copy, and publish directly to TikTok or save to Drafts — protected by <b>Zero-Strike Community Guidelines Shield</b>.</div>',
        unsafe_allow_html=True
    )

with col_head2:
    creds = load_credentials()
    if creds and creds.get("access_token"):
        account_name = creds.get("display_name", "Demo Khelauna")
        st.markdown(
            f'<div class="shield-badge-safe">🟢 Connected: <b>@{account_name}</b></div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="shield-badge-blocked">⚠️ TikTok: Disconnected / Sandbox</div>',
            unsafe_allow_html=True
        )

# ---------------------------------------------------------------------------
# TABS
# ---------------------------------------------------------------------------
tab_create, tab_scanner, tab_connect, tab_history = st.tabs([
    "🎬 Create Post & Reels",
    "🛡️ Policy Safety Scanner",
    "🔗 Connect TikTok Account",
    "📊 Post History & Queue"
])

# ===========================================================================
# TAB 1: CREATE POST & REELS
# ===========================================================================
with tab_create:
    catalog_df = load_tiktok_catalog()

    col_cfg, col_preview = st.columns([1, 1], gap="large")

    with col_cfg:
        st.subheader("1. Select Content Source")
        post_mode = st.radio(
            "Content Mode:",
            ["🛍️ Catalog Auto-Reel (Recommended)", "📸 Photo Carousel", "📹 Custom Shop Video"],
            horizontal=True
        )

        selected_product = None
        selected_photo_url = None
        prod_price = 0.0
        prod_stock = 0.0

        if post_mode == "🛍️ Catalog Auto-Reel (Recommended)":
            if not catalog_df.empty:
                # Add safety filter toggle
                only_safe = st.checkbox("Show Only TikTok-Safe Products", value=True)
                filtered_df = catalog_df[catalog_df['tiktok_safe'] == True] if only_safe else catalog_df

                product_options = filtered_df['product_name'].tolist()
                prod_choice = st.selectbox(
                    "Select Product from Inventory:",
                    options=product_options,
                    index=0 if product_options else None
                )

                if prod_choice:
                    row = catalog_df[catalog_df['product_name'] == prod_choice].iloc[0]
                    selected_product = str(row['product_name'])
                    raw_photo = row.get('image_url')
                    selected_photo_url = get_clean_image_source(raw_photo, selected_product)
                    prod_price = float(row.get('selling_price', row.get('catalog_price', 0)) or 0)
                    is_safe = bool(row.get('tiktok_safe', True))
                    status_reason = str(row.get('tiktok_reason', ''))

                    if not is_safe:
                        st.error(
                            f"🚨 **POLICY BLOCK**: '{selected_product}' is classified as high-risk under TikTok "
                            f"Community Guidelines ({status_reason}).\n\n"
                            "Posting imitation weapons or toy guns will result in an account suspension. Video generation disabled."
                        )
                    else:
                        st.success(f"✅ **TikTok Compliant**: Verified safe for promotion ({status_reason}).")

                    if selected_photo_url:
                        st.image(selected_photo_url, caption=f"{selected_product} | Wholesale Only 🏷️", width=220)
                    else:
                        st.info("📷 No photo attached in catalog for this item. Using default showroom visual.")
            else:
                st.info("No catalog loaded. Enter product details manually below.")
                selected_product = st.text_input("Product Name:", "360-1 RC Stunt Car")

        elif post_mode == "📸 Photo Carousel":
            st.info("Create a swipeable photo post for TikTok.")
            carousel_name = st.text_input("Album / Product Name:", "New Toy Arrivals This Week")
            uploaded_photos = st.file_uploader("Upload 2–5 Product Photos:", accept_multiple_files=True, type=["jpg", "jpeg", "png"])
            selected_product = carousel_name

        elif post_mode == "📹 Custom Shop Video":
            st.info("Upload video shot on your phone at godown/shop.")
            selected_product = st.text_input("Product Featured:", "RC Drone With Dual Camera")
            uploaded_video = st.file_uploader("Upload Video (MP4/MOV, 9:16 vertical):", type=["mp4", "mov"])

        st.caption("🔒 **Price Privacy Guard**: Wholesale rates are strictly hidden from TikTok videos & public captions to protect your retailers' profit margins.")

        st.markdown("---")
        st.subheader("2. AI Copywriting & Settings")
        custom_notes = st.text_input("Custom Promotion Angle / Notes:", placeholder="e.g. Festival wholesale special, bulk carton discounts")

        if st.button("✨ Generate Viral Copy with Gemini AI", use_container_width=True):
            if selected_product:
                with st.spinner("Gemini is generating high-converting TikTok copy (no public prices)..."):
                    try:
                        copy_data = generate_tiktok_copy(
                            product_name=selected_product,
                            price=prod_price,
                            custom_notes=custom_notes
                        )
                        st.session_state["tt_hook"] = copy_data.get("hook", "")
                        st.session_state["tt_caption"] = copy_data.get("caption", "")
                        st.session_state["tt_hashtags"] = " ".join(copy_data.get("hashtags", []))
                        st.session_state["tt_badges"] = copy_data.get("overlay_badges", [])
                        st.success("Generated viral TikTok copy!")
                    except TikTokPolicyViolationError as pe:
                        st.error(f"🚨 {pe}")
                    except Exception as ex:
                        st.error(f"Failed to generate copy: {ex}")

        # Editable Caption Fields
        hook_val = st.session_state.get("tt_hook", f"🔥 New Arrival: {selected_product or 'Demo Khelauna'}!")
        caption_val = st.session_state.get("tt_caption", f"Wholesale toys available in Kathmandu! Delivery all over Nepal. Wholesale inquiries: +977 9803216856")
        hashtags_val = st.session_state.get("tt_hashtags", "#demokhelauna #toysnepal #wholesaletoynepal #kathmandutoys")

        edit_hook = st.text_input("On-Screen Video Hook:", value=hook_val)
        edit_caption = st.text_area("Post Caption:", value=caption_val, height=90)
        edit_tags = st.text_input("Hashtags:", value=hashtags_val)

        dest_choice = st.selectbox(
            "Publishing Destination:",
            ["📥 Save to TikTok Drafts (Creator Inbox) — Recommended", "🚀 Publish Directly to Public Feed"]
        )

    with col_preview:
        st.subheader("3. Video Reel Preview & Publishing")

        # Video Render Action
        if st.button("🎬 Render 9:16 Video Reel", type="primary", use_container_width=True):
            if not selected_product:
                st.warning("Please select or enter a product first.")
            else:
                image_src = selected_photo_url or "HermesData/assets/images/006-6 Pull Line Car.jpg"
                badges_to_use = [edit_hook, "WHOLESALE ONLY 🏷️", "WhatsApp: +977 9803216856"]

                with st.spinner("Rendering 9:16 dynamic reel with Ken Burns zoom & branding..."):
                    try:
                        render_res = render_vertical_reel(
                            image_sources=[image_src],
                            product_name=selected_product,
                            price=prod_price,
                            overlay_badges=badges_to_use,
                            seconds_per_slide=4.0
                        )
                        st.session_state["rendered_video_path"] = render_res["video_path"]
                        st.success("Reel rendered successfully!")
                    except TikTokPolicyViolationError as pe:
                        st.error(f"🚨 Community Policy Shield Triggered: {pe}")
                    except Exception as ex:
                        st.error(f"Rendering failed: {ex}")

        # Show rendered video player if available
        rendered_path = st.session_state.get("rendered_video_path")
        if rendered_path and os.path.exists(rendered_path):
            st.video(rendered_path)
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                with open(rendered_path, "rb") as vf:
                    st.download_button(
                        label="⬇️ Download Reel MP4",
                        data=vf.read(),
                        file_name=os.path.basename(rendered_path),
                        mime="video/mp4",
                        use_container_width=True
                    )
            with col_d2:
                if st.button("🎵 Upload to TikTok", type="primary", use_container_width=True):
                    with st.spinner("Uploading to TikTok with Community Guidelines compliance..."):
                        try:
                            destination_flag = "DRAFT_INBOX" if "Drafts" in dest_choice else "DIRECT_POST"
                            pub_res = publish_video(
                                video_url_or_path=rendered_path,
                                title=f"{edit_caption}\n\n{edit_tags}",
                                destination=destination_flag,
                                product_name=selected_product or ""
                            )
                            st.success(f"🎉 Successfully uploaded to TikTok! Publish ID: {pub_res.get('publish_id')}")
                        except TikTokAuthError as ae:
                            st.warning(f"TikTok Authentication Notice: {ae}\n(Visit 'Connect TikTok Account' tab to link your account or verify Developer Sandbox tokens).")
                        except TikTokPolicyViolationError as pve:
                            st.error(f"🚨 Pre-flight Safety Blocked Publish: {pve}")
                        except Exception as pe:
                            st.error(f"Upload error: {pe}")
        else:
            st.info("Render a video reel or upload content to preview it here.")


# ===========================================================================
# TAB 2: POLICY SAFETY SCANNER (TOY GUN & WEAPON SHIELD)
# ===========================================================================
with tab_scanner:
    st.subheader("🛡️ TikTok Community Guidelines Safety Pre-Screening")
    st.markdown(
        "Upload any toy image or enter a product title to test against TikTok's automated weapons "
        "and dangerous goods classifiers before posting."
    )

    col_s1, col_s2 = st.columns([1, 1], gap="large")

    with col_s1:
        test_title = st.text_input("Test Product Title / Tags:", placeholder="e.g. 009 Soft Pellet Revolver, Pichkari 500")
        test_img = st.file_uploader("Upload Image to Inspect:", type=["jpg", "jpeg", "png"])

        if st.button("🔍 Run Full Safety & Policy Inspection", type="primary", use_container_width=True):
            if not test_title and not test_img:
                st.warning("Please provide either a product title or upload an image.")
            else:
                with st.spinner("Scanning against TikTok Community Guidelines & Dangerous Goods policies..."):
                    img_bytes = test_img.read() if test_img else None
                    verdict = evaluate_post_safety(
                        product_name=test_title,
                        image_input=img_bytes,
                        skip_vision=(img_bytes is None)
                    )
                    st.session_state["scan_verdict"] = verdict

    with col_s2:
        verdict = st.session_state.get("scan_verdict")
        if verdict:
            if verdict.is_safe:
                st.markdown('<div class="shield-badge-safe">✅ 100% TIKTOK COMPLIANT — APPROVED</div>', unsafe_allow_html=True)
                st.success(verdict.user_guidance)
            else:
                st.markdown('<div class="shield-badge-blocked">🚨 HIGH RISK OF COMMUNITY STRIKE — BLOCKED</div>', unsafe_allow_html=True)
                st.error(verdict.user_guidance)
                st.markdown(f"**Violated Policies Detected**: `{', '.join(verdict.flags)}`")
                if verdict.reasons:
                    st.markdown("**AI Inspection Analysis**:")
                    for r in verdict.reasons:
                        st.info(r)

    st.markdown("---")
    st.subheader("📚 TikTok Policy Reference for Demo Khelauna")
    col_pol1, col_pol2 = st.columns(2)
    with col_pol1:
        st.error("""
        ### ❌ Strictly Prohibited on TikTok:
        - **Toy Guns & Blasters**: Even plastic, water guns, bubble guns, or sound guns trigger automated computer vision weapon classifiers.
        - **Imitation Weapons**: Toy swords, ninja stars, knives, slingshots, bow & arrows.
        - **Pyrotechnics**: Firecrackers, party poppers with gunpowder.
        """)
    with col_pol2:
        st.success("""
        ### ✅ Safe & High-Performing on TikTok:
        - **RC Vehicles**: Stunt cars, drift cars, 4WD climbing jeeps, battery bikes.
        - **Educational & Novelty**: Dancing cactus, magic slates, writing pads, puzzles.
        - **Dolls & Roleplay**: Barbie sets, kitchen sets, doctor sets, beauty sets.
        - **Party Items**: Birthday foil balloons, decorative banners, party masks.
        """)


# ===========================================================================
# TAB 3: CONNECT TIKTOK ACCOUNT (OAUTH 2.0 PKCE)
# ===========================================================================
with tab_connect:
    st.subheader("🔗 TikTok Developer App & Account Link")
    st.markdown("""
    To publish directly or send drafts to your TikTok app:
    1. Register your app at **[developers.tiktok.com](https://developers.tiktok.com)**.
    2. Add your TikTok handle (`@demokhelauna`) as an **Authorized Sandbox Tester**.
    3. Enter your Developer Client Key and Secret below.
    """)

    creds_stored = load_credentials() or {}

    col_o1, col_o2 = st.columns(2)
    with col_o1:
        client_key = st.text_input("TikTok Client Key:", value=os.getenv("TIKTOK_CLIENT_KEY", ""))
        client_secret = st.text_input("TikTok Client Secret:", type="password", value=os.getenv("TIKTOK_CLIENT_SECRET", ""))
        redirect_uri = st.text_input("OAuth Redirect URI:", value=os.getenv("TIKTOK_REDIRECT_URI", "https://analytics-production-a23f.up.railway.app/TikTok_Studio"))

        if st.button("Generate TikTok Authorization Link"):
            try:
                auth_data = get_oauth_authorization_url(
                    client_key=client_key,
                    redirect_uri=redirect_uri
                )
                st.session_state["tt_code_verifier"] = auth_data["code_verifier"]
                st.markdown(f"👉 **[Click Here to Authorize on TikTok]({auth_data['auth_url']})**")
                st.info("Log in with your TikTok account on the page that opens, and copy the `code` from the redirect URL.")
            except Exception as e:
                st.error(f"Auth URL Error: {e}")

    with col_o2:
        st.markdown("#### Complete Authorization")
        auth_code = st.text_input("Paste Authorization Code (from callback URL):")
        verifier = st.text_input("Code Verifier:", value=st.session_state.get("tt_code_verifier", ""))

        if st.button("Exchange Code for Access Token", type="primary"):
            if not auth_code or not verifier:
                st.warning("Please provide both Authorization Code and Code Verifier.")
            else:
                with st.spinner("Exchanging token with TikTok..."):
                    try:
                        token_info = exchange_code_for_token(auth_code, verifier, redirect_uri=redirect_uri)
                        st.success("Successfully connected TikTok account!")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Token Exchange Failed: {ex}")

    st.markdown("---")
    st.markdown("#### Current Connection Status")
    if creds_stored.get("access_token"):
        st.json({
            "Display Name": creds_stored.get("display_name"),
            "Open ID": creds_stored.get("open_id"),
            "Expires At": creds_stored.get("expires_at"),
            "Scope": creds_stored.get("scope")
        })
        if st.button("Disconnect TikTok Account"):
            save_credentials({"access_token": "", "refresh_token": ""})
            st.success("Disconnected.")
            st.rerun()
    else:
        st.info("No active credentials stored.")


# ===========================================================================
# TAB 4: POST HISTORY & AUDIT LOG
# ===========================================================================
with tab_history:
    st.subheader("📊 Published Posts & Audit Log")
    try:
        from db import get_client
        sp = get_client()
        if sp:
            res = sp.table("tiktok_posts").select("*").order("created_at", desc=True).limit(30).execute()
            if res.data:
                df_posts = pd.DataFrame(res.data)
                st.dataframe(df_posts, use_container_width=True)
            else:
                st.info("No TikTok posts recorded in Supabase yet.")
        else:
            st.info("Supabase client not active. Posts will be logged locally.")
    except Exception as e:
        st.info(f"Post log query: {e}")

    # Show local rendered files
    renders_dir = "data/tiktok_renders"
    if os.path.exists(renders_dir):
        files = os.listdir(renders_dir)
        if files:
            st.markdown("#### 📁 Locally Rendered Reels")
            for f in files[-5:]:
                st.text(f"• {f}")
