"""
DayBook Analytics / Demo Khelauna — Privacy Policy
Official Privacy Policy for TikTok Developer App and Platform Integration.
"""

import streamlit as st
from ui_utils import apply_global_styles

st.set_page_config(
    page_title="Privacy Policy — Demo Khelauna",
    page_icon="🔒",
    layout="wide"
)

apply_global_styles()

st.title("🔒 Privacy Policy")
st.caption("Last Updated: October 6, 2026 | Demo Khelauna (Kathmandu, Nepal)")

st.markdown("""
### 1. Introduction
Demo Khelauna ("we", "our", or "us") operates the **Demo Khelauna Studio** and **DayBook Analytics** platform. This Privacy Policy explains how we collect, use, and protect information when you use our services, including our TikTok Developer integration.

### 2. Information We Collect
- **TikTok Account Information**: When you authorize our application via TikTok OAuth 2.0, we collect basic profile metadata (your TikTok username, display name, and avatar URL) provided by the `user.info.basic` scope.
- **OAuth Authentication Tokens**: We securely store access tokens and refresh tokens in encrypted database storage solely to authenticate API requests to publish videos or drafts on your behalf.
- **Media & Post Content**: We process product images, video reels, and promotional captions created for publishing to your TikTok account.

### 3. How We Use Information
We use your information exclusively to:
- Authenticate your TikTok developer connection.
- Render dynamic 9:16 vertical video reels of wholesale toy products.
- Upload posts or draft reels to your authorized TikTok account (`video.publish` and `video.upload`).
- Maintain an audit log of published posts within your private business dashboard.

### 4. Data Sharing & Third Parties
- **No Selling of Data**: We **never** sell, rent, or trade your personal data, customer contacts, or TikTok credentials to third parties.
- **Third-Party Services**: We communicate with TikTok APIs (ByteDance Ltd.) for posting media, and Supabase for secure cloud database storage.

### 5. Data Security & Retention
- All OAuth credentials and tokens are transmitted over TLS/SSL encryption and stored in secure cloud infrastructure.
- Tokens can be revoked or deleted at any time by disconnecting your TikTok account via Tab 3 of the TikTok Studio dashboard.

### 6. User Rights & Data Deletion
You may request deletion of any stored credentials, logs, or associated media at any time by contacting us via WhatsApp or email. You may also revoke our application's access directly in your TikTok account settings under **Settings & Privacy -> Security & Permissions -> Apps & Services**.

### 7. Contact Us
For questions regarding this Privacy Policy:
- **Business**: Demo Khelauna (Wholesale Toys & Party Supplies)
- **Location**: Kathmandu, Nepal
- **Phone / WhatsApp**: +977 9803216856
- **Email**: privacy@demokhelauna.com
""")
