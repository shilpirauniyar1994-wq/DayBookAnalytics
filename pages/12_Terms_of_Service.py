"""
DayBook Analytics / Demo Khelauna — Terms of Service
Official Terms of Service for TikTok Developer App and Platform Integration.
"""

import streamlit as st
from ui_utils import apply_global_styles

st.set_page_config(
    page_title="Terms of Service — Demo Khelauna",
    page_icon="📜",
    layout="wide"
)

apply_global_styles()

st.title("📜 Terms of Service")
st.caption("Last Updated: October 6, 2026 | Demo Khelauna (Kathmandu, Nepal)")

st.markdown("""
### 1. Acceptance of Terms
By accessing or using the **Demo Khelauna Studio** platform, **DayBook Analytics**, and associated integrations (including the TikTok Content Posting integration), you agree to be bound by these Terms of Service. If you do not agree to these terms, please do not use the services.

### 2. Description of Service
Demo Khelauna Studio is a private business analytics, inventory management, and marketing software platform operated by Demo Khelauna, a wholesale toy and novelty importer based in Kathmandu, Nepal. The platform provides internal inventory tracking, catalog viewing, AI-assisted marketing copy, and publishing capabilities to authorized social media channels (including TikTok).

### 3. TikTok Platform Integration & Compliance
- **Content Responsibility**: All videos, photos, carousels, captions, and media generated or uploaded through this platform comply with **TikTok Community Guidelines** and TikTok Terms of Service.
- **Prohibited Content**: The platform strictly prohibits and actively blocks the promotion, depiction, or marketing of weapons, imitation firearms, toy guns, explosives, violence, or harmful goods.
- **Commercial Disclosures**: All promotional posts published via this platform are tagged with appropriate commercial disclosure metadata (`brand_organic`) in accordance with TikTok advertising and commercial content policies.
- **Wholesale Price Privacy**: Wholesale pricing is kept confidential between Demo Khelauna and registered wholesale buyers and is not publicly advertised on social media feeds.

### 4. User Accounts and Authorization
Access to social media publishing features is restricted to authorized representatives of Demo Khelauna. You are responsible for safeguarding your login credentials, API keys, and OAuth access tokens.

### 5. Intellectual Property
All product photographs, logos, brand names, and creative assets published by Demo Khelauna remain the property of Demo Khelauna or their respective manufacturers.

### 6. Limitation of Liability
The software and its integrations are provided on an "as is" and "as available" basis. Demo Khelauna shall not be liable for any indirect, incidental, or consequential damages resulting from third-party social media platform downtime, API modifications, or account actions taken by third-party platforms.

### 7. Contact Us
For any inquiries regarding these Terms of Service:
- **Business**: Demo Khelauna (Wholesale Toys & Party Supplies)
- **Location**: Kathmandu, Nepal
- **Phone / WhatsApp**: +977 9803216856
- **Email**: info@demokhelauna.com
""")
