"""
DayBook Analytics — Hermes AI Knowledge Base & Catalog Sync Page
Provides dashboard-controlled synchronization of product photos, tags,
live stock balances, and average selling prices into our Primary Supabase Database.
Hermes Agent queries the resulting `hermes_items` table directly with zero bafa_v2 connection.
"""

import streamlit as st
import pandas as pd
import datetime
import os
import db
from ui_utils import apply_global_styles, format_currency, format_qty
from hermes_engine import sync_hermes_items, get_hermes_items_df, HERMES_CACHE_CSV

st.set_page_config(
    page_title="Hermes Knowledge Base — DayBook Analytics",
    page_icon="🤖",
    layout="wide"
)

apply_global_styles()

# Custom styles for product cards and tag chips
st.markdown("""
<style>
    .hermes-header {
        font-size: 1.85rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 0.2rem;
    }
    .hermes-sub {
        font-size: 0.95rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .sync-card {
        background: linear-gradient(135deg, #EFF6FF 0%, #F8FAFC 100%);
        border: 1px solid #BFDBFE;
        border-radius: 10px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }
    .product-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 10px;
        padding: 12px;
        margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
        transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .product-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        border-color: #CBD5E1;
    }
    .tag-chip {
        display: inline-block;
        background-color: #EEF2FF;
        color: #4338CA;
        font-size: 0.72rem;
        font-weight: 600;
        padding: 2px 7px;
        border-radius: 4px;
        margin-right: 4px;
        margin-bottom: 4px;
        border: 1px solid #C7D2FE;
    }
    .stock-badge-positive {
        display: inline-block;
        background-color: #DCFCE7;
        color: #15803D;
        font-size: 0.75rem;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 4px;
        border: 1px solid #BBF7D0;
    }
    .stock-badge-zero {
        display: inline-block;
        background-color: #FEE2E2;
        color: #B91C1C;
        font-size: 0.75rem;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 4px;
        border: 1px solid #FECACA;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="hermes-header">🤖 Hermes AI Knowledge Base & Catalog Sync</div>', unsafe_allow_html=True)
st.markdown('<div class="hermes-sub">Manage product photos, catalog tags, live stock balances, and average selling prices for Hermes Agent. Hermes queries this data directly from our Primary Database.</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# 1. Sync Control Card
# ---------------------------------------------------------------------------
st.markdown('<div class="sync-card">', unsafe_allow_html=True)
col_sync1, col_sync2 = st.columns([3, 1])

with col_sync1:
    st.markdown("### 🔄 Knowledge Base Synchronization")
    st.markdown(
        "Pulls latest product photos, tags, and catalog prices from Bafa (read-only), "
        "computes live stock balances (`Opening Stock + Purchases - Sales`) and last-month "
        "average selling rates from our DayBook, and upserts all records into table **`hermes_items`** in our Primary Database."
    )

with col_sync2:
    st.write("")
    st.write("")
    sync_btn = st.button("🚀 Sync Knowledge Base Now", type="primary", use_container_width=True)

st.markdown('</div>', unsafe_allow_html=True)

# Handle Sync Execution
if sync_btn:
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(pct, msg):
        progress_bar.progress(pct)
        status_text.info(f"⏳ {msg}")

    try:
        summary = sync_hermes_items(progress_callback=update_progress)
        progress_bar.progress(1.0)
        status_text.empty()
        st.success(
            f"✅ **Sync Successful!** Synchronized {summary['inserted_or_updated']:,} products to Primary Supabase DB. "
            f"Photos: {summary['with_photos']:,} | Tags: {summary['with_tags']:,} | In Stock: {summary['with_positive_stock']:,}"
        )
        st.cache_data.clear()
    except Exception as e:
        status_text.empty()
        st.error(f"❌ **Sync Failed:** {e}")

# ---------------------------------------------------------------------------
# 2. Load Data & Top KPIs
# ---------------------------------------------------------------------------
df = get_hermes_items_df()

if df.empty:
    st.warning("⚠️ No records found in `hermes_items`. Click **'Sync Knowledge Base Now'** above to populate the knowledge base.")
    st.stop()

# Ensure required columns
for col in ['product_name', 'current_stock', 'selling_price', 'catalog_price', 'rmb_price', 'image_url', 'tags', 'product_group', 'last_sold_month']:
    if col not in df.columns:
        df[col] = None

total_items = len(df)
with_photos = int(df['image_url'].notna().sum())
with_tags = int(df['tags'].notna().sum())
in_stock = int((pd.to_numeric(df['current_stock'], errors='coerce') > 0).sum())
with_rmb = int(df['rmb_price'].notna().sum())

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("📦 Total Products", f"{total_items:,}")
kpi2.metric("📸 With Photos", f"{with_photos:,}", f"{int(with_photos/total_items*100)}% coverage")
kpi3.metric("🏷️ With Tags", f"{with_tags:,}", f"{int(with_tags/total_items*100)}% coverage")
kpi4.metric("✅ In Stock", f"{in_stock:,}", f"{int(in_stock/total_items*100)}% in stock")
kpi5.metric("¥ RMB Invoices", f"{with_rmb:,}", "China factory cost")

st.divider()

# ---------------------------------------------------------------------------
# 3. Hermes Live Search & Inspector
# ---------------------------------------------------------------------------
st.subheader("🔍 Hermes Knowledge Base Inspector")
st.caption("Inspect and test what Hermes Agent sees when answering questions or looking up photos")

# Extract unique tags for dropdown
all_tags = set()
for t_str in df['tags'].dropna():
    for t in str(t_str).split(';'):
        cleaned = t.strip().upper()
        if cleaned:
            all_tags.add(cleaned)
sorted_tags = ['All Tags'] + sorted(list(all_tags))

c_filt1, c_filt2, c_filt3, c_filt4 = st.columns([2, 1.5, 1, 1])

with c_filt1:
    search_query = st.text_input("Search Product Name", placeholder="e.g. 2620, Gun, Car, Doll, Clay...").strip()

with c_filt2:
    selected_tag = st.selectbox("Filter by Tag", sorted_tags)

with c_filt3:
    stock_filter = st.selectbox("Stock Status", ["All Items", "In Stock Only (> 0)", "Out of Stock (<= 0)"])

with c_filt4:
    photo_filter = st.checkbox("Has Photo Only", value=False)

# Apply filters
filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df['product_name'].str.contains(search_query, case=False, na=False)]

if selected_tag != 'All Tags':
    filtered_df = filtered_df[filtered_df['tags'].str.contains(selected_tag, case=False, na=False)]

if stock_filter == "In Stock Only (> 0)":
    filtered_df = filtered_df[pd.to_numeric(filtered_df['current_stock'], errors='coerce') > 0]
elif stock_filter == "Out of Stock (<= 0)":
    filtered_df = filtered_df[pd.to_numeric(filtered_df['current_stock'], errors='coerce') <= 0]

if photo_filter:
    filtered_df = filtered_df[filtered_df['image_url'].notna() & (filtered_df['image_url'] != '')]

st.markdown(f"**Showing {len(filtered_df):,} matching products** (sorted by Current Stock descending):")

# View Mode Switcher
tab_chat, tab_grid, tab_table = st.tabs(["💬 Chat with Google Hermes", "🖼️ Photo Cards Grid", "📋 Detailed Data Table"])

with tab_chat:
    st.markdown("#### 🤖 Live Assistant Simulator (Powered by Google Gemini & Primary Supabase)")
    st.caption("Ask questions in English or Nepali. Gemini queries live stock, wholesale prices, and product photos with zero hallucination.")

    from google_hermes_engine import ask_hermes

    if 'hermes_chat_history' not in st.session_state:
        st.session_state.hermes_chat_history = [
            {"role": "assistant", "content": "Hello! I am Hermes, your inventory assistant. Ask me about product stock, wholesale prices, or ask for product photos (e.g., 'Give me RC item photos', 'Stock of 360-1', 'Show me dolls')."}
        ]

    # Quick prompt buttons
    st.markdown("**Quick Prompts:**")
    qp1, qp2, qp3, qp4 = st.columns(4)
    quick_query = None
    if qp1.button("🏎️ RC item photos", use_container_width=True):
        quick_query = "Give me RC item photos"
    if qp2.button("📦 Stock of 360-1", use_container_width=True):
        quick_query = "What is the stock and price of 360-1?"
    if qp3.button("🎎 Dolls in stock", use_container_width=True):
        quick_query = "Show me dolls in stock with photos"
    if qp4.button("🔫 Guns with photos", use_container_width=True):
        quick_query = "Give me photos of guns in stock"

    # Display chat history
    for chat_msg in st.session_state.hermes_chat_history:
        with st.chat_message(chat_msg["role"]):
            st.markdown(chat_msg["content"])

    # Chat input
    user_prompt = st.chat_input("Type your question for Hermes...") or quick_query

    if user_prompt:
        st.session_state.hermes_chat_history.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            with st.spinner("Hermes is querying Supabase database via Google Gemini..."):
                response_data = ask_hermes(user_prompt)
                reply_text = response_data["reply"]
                st.markdown(reply_text)
                if response_data.get("image_urls"):
                    st.caption(f"📱 WhatsApp Dispatch: {len(response_data['image_urls'])} image messages attached.")
        
        st.session_state.hermes_chat_history.append({"role": "assistant", "content": reply_text})
        st.rerun()

with tab_grid:

    if filtered_df.empty:
        st.info("No products match your filter criteria.")
    else:
        # Display cards in 3 columns
        num_cols = 3
        items_to_show = filtered_df.head(60).to_dict('records')
        
        for row_start in range(0, len(items_to_show), num_cols):
            row_items = items_to_show[row_start:row_start + num_cols]
            cols = st.columns(num_cols)
            
            for col_idx, item in enumerate(row_items):
                with cols[col_idx]:
                    stock_val = float(item['current_stock']) if pd.notna(item['current_stock']) else 0.0
                    sp_val = float(item['selling_price']) if pd.notna(item['selling_price']) else 0.0
                    rmb_val = float(item['rmb_price']) if pd.notna(item['rmb_price']) else None
                    image_url = item.get('image_url')
                    tags_str = item.get('tags')
                    last_sold = item.get('last_sold_month')

                    # Card Container
                    with st.container(border=True):
                        # Image thumbnail
                        if image_url and str(image_url).startswith("http"):
                            st.image(image_url, use_container_width=True)
                        else:
                            st.markdown(
                                '<div style="height: 140px; background-color: #F1F5F9; border-radius: 6px; '
                                'display: flex; align-items: center; justify-content: center; color: #94A3B8; '
                                'font-size: 0.85rem; font-weight: 500;">📷 No Photo Available</div>',
                                unsafe_allow_html=True
                            )
                        
                        st.markdown(f"**{item['product_name']}**")
                        
                        # Stock and Price Row
                        c_s, c_p = st.columns(2)
                        with c_s:
                            if stock_val > 0:
                                st.markdown(f'<span class="stock-badge-positive">📦 Stock: {stock_val:,.0f} PCS</span>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'<span class="stock-badge-zero">📦 Stock: {stock_val:,.0f} PCS</span>', unsafe_allow_html=True)
                        
                        with c_p:
                            st.markdown(f"**💰 Rs. {sp_val:,.2f}**")
                            if last_sold:
                                st.caption(f"Sold in: {last_sold}")
                        
                        if rmb_val:
                            st.caption(f"Factory RMB: **¥ {rmb_val:,.3f}**")

                        # Tags Chips
                        if tags_str:
                            tags_html = "".join([f'<span class="tag-chip">{t.strip()}</span>' for t in str(tags_str).split(';') if t.strip()])
                            st.markdown(tags_html, unsafe_allow_html=True)

with tab_table:
    display_cols = [
        'product_name',
        'current_stock',
        'selling_price',
        'catalog_price',
        'rmb_price',
        'tags',
        'last_sold_month',
        'product_group',
        'image_url'
    ]
    st.dataframe(
        filtered_df[display_cols].rename(columns={
            'product_name': 'Product Name',
            'current_stock': 'Current Stock',
            'selling_price': 'Selling Price (Rs.)',
            'catalog_price': 'Catalog Price (Rs.)',
            'rmb_price': 'RMB Price (¥)',
            'tags': 'Tags',
            'last_sold_month': 'Last Sold Month',
            'product_group': 'Category',
            'image_url': 'Photo URL'
        }),
        use_container_width=True,
        hide_index=True
    )

st.divider()

# ---------------------------------------------------------------------------
# 4. Hermes Developer & Agent Integration Guide
# ---------------------------------------------------------------------------
with st.expander("🛠️ Hermes Agent Architecture & Query Reference (For Developers)"):
    st.markdown("""
    ### How Hermes Queries This Data (Strictly Primary DB)
    Hermes Agent connects **solely** to our Primary Supabase Database (`nepal toys`). It never connects to `bafa_v2`.
    
    #### 1. When a user asks: *"Give me RC item photos"*
    Hermes executes this single query on our Primary DB:
    ```sql
    SELECT product_name, current_stock, selling_price, image_url, tags
    FROM hermes_items
    WHERE tags ILIKE '%RC%'
      AND image_url IS NOT NULL
      AND current_stock > 0
    ORDER BY current_stock DESC
    LIMIT 5;
    ```
    
    #### 2. When a user asks: *"What is the stock and selling price of 360-1?"*
    Hermes executes:
    ```sql
    SELECT product_name, current_stock, selling_price, rmb_price, image_url
    FROM hermes_items
    WHERE product_name ILIKE '%360-1%';
    ```
    
    #### 3. Python Helper Function for Hermes:
    ```python
    from hermes_engine import hermes_query_items
    
    # Get top 5 in-stock RC items with photos
    rc_items = hermes_query_items(tag="RC", in_stock_only=True, has_photo_only=True, limit=5)
    for item in rc_items:
        print(f"Product: {item['product_name']}, Stock: {item['current_stock']}, Photo: {item['image_url']}")
    ```
    """)
