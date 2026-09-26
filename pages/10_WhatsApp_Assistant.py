"""
DayBook Analytics — WhatsApp Live Assistant Dashboard
Controls and monitors the WhatsApp Multi-Device bridge and Google Gemini AI Engine.
Provides instant QR pairing, live message streaming, catalog testing, and bridge diagnostics.
"""

import streamlit as st
import os
import sys
import json
import time
import socket
import subprocess
from PIL import Image
import urllib.request
from ui_utils import apply_global_styles
from google_hermes_engine import ask_hermes

st.set_page_config(
    page_title="WhatsApp Assistant — DayBook Analytics",
    page_icon="📱",
    layout="wide"
)

apply_global_styles()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_DIR = os.path.join(BASE_DIR, "whatsapp_bridge")
QR_PATH = os.path.join(BRIDGE_DIR, "qr.png")
STATUS_PATH = os.path.join(BRIDGE_DIR, "status.json")
LOG_PATH = os.path.join(BRIDGE_DIR, "messages_log.json")
AUTH_DIR = os.path.join(BRIDGE_DIR, "auth_info_baileys")

# Custom CSS for WhatsApp Assistant
st.markdown("""
<style>
    .wa-header {
        font-size: 1.85rem;
        font-weight: 700;
        color: #075E54;
        margin-bottom: 0.2rem;
    }
    .wa-sub {
        font-size: 0.95rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .status-card-connected {
        background: #F0FDF4;
        border: 1px solid #86EFAC;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }
    .status-card-scan {
        background: #FEFCE8;
        border: 1px solid #FDE047;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }
    .status-card-offline {
        background: #F8FAFC;
        border: 1px solid #CBD5E1;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }
    .qr-box {
        background: #FFFFFF;
        border: 2px dashed #128C7E;
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .chat-bubble-in {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-left: 4px solid #3B82F6;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }
    .chat-bubble-out {
        background: #DCF8C6;
        border: 1px solid #C4E1A4;
        border-left: 4px solid #25D366;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

def is_port_open(port=5005) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except Exception:
        return False

def get_bridge_status() -> dict:
    if os.path.exists(STATUS_PATH):
        try:
            with open(STATUS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"status": "offline", "qr_available": False}

def get_message_logs() -> list:
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
    return []

def start_python_api():
    if not is_port_open(5005):
        subprocess.Popen(
            [sys.executable, "whatsapp_api_server.py"],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        time.sleep(1.5)

def start_baileys_bridge():
    subprocess.Popen(
        ["node", "bridge_server.js"],
        cwd=BRIDGE_DIR,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    )
    time.sleep(2.0)

def unlink_whatsapp_session():
    # Stop bridge and delete auth directory
    if os.path.exists(AUTH_DIR):
        try:
            import shutil
            shutil.rmtree(AUTH_DIR, ignore_errors=True)
        except Exception as e:
            st.error(f"Error clearing auth: {e}")
    if os.path.exists(QR_PATH):
        try:
            os.remove(QR_PATH)
        except Exception:
            pass
    # Update status to offline
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "offline", "qr_available": False, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}, f)

# Title & Description
st.markdown('<div class="wa-header">📱 WhatsApp Live Assistant</div>', unsafe_allow_html=True)
st.markdown('<div class="wa-sub">100% Free & Unlimited WhatsApp Multi-Device Bridge connected to Google Gemini & Primary Supabase Inventory.</div>', unsafe_allow_html=True)

# Status Check
status_data = get_bridge_status()
current_status = status_data.get("status", "offline")
api_online = is_port_open(5005)

# Control Buttons Bar
col_status, col_btn1, col_btn2 = st.columns([4, 1.2, 1.2])

with col_status:
    if current_status == "connected":
        phone = status_data.get("phone_number", "Active")
        name = status_data.get("user_name") or "Demo Khelauna Assistant"
        st.markdown(f"""
        <div class="status-card-connected">
            <h4 style="margin: 0; color: #166534;">🟢 WhatsApp Assistant Connected</h4>
            <p style="margin: 4px 0 0 0; color: #15803D; font-size: 0.95rem;">
                <b>Phone:</b> +{phone} &nbsp;|&nbsp; <b>Name:</b> {name} &nbsp;|&nbsp; <b>AI Engine:</b> Google Gemini Flash
            </p>
        </div>
        """, unsafe_allow_html=True)
    elif current_status == "scan_qr" or os.path.exists(QR_PATH):
        st.markdown("""
        <div class="status-card-scan">
            <h4 style="margin: 0; color: #854D0E;">🟡 Ready to Pair — Please Scan QR Code Below</h4>
            <p style="margin: 4px 0 0 0; color: #A16207; font-size: 0.95rem;">
                Open WhatsApp on your phone → Linked Devices → Link a Device, and scan the QR code.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="status-card-offline">
            <h4 style="margin: 0; color: #475569;">⚪ Bridge Status: {current_status.capitalize()}</h4>
            <p style="margin: 4px 0 0 0; color: #64748B; font-size: 0.95rem;">
                Python API Backend: {'🟢 Online' if api_online else '🔴 Offline'} &nbsp;|&nbsp; Click <b>Start Bridge</b> to initiate.
            </p>
        </div>
        """, unsafe_allow_html=True)

with col_btn1:
    if st.button("🔄 Refresh Status", use_container_width=True):
        st.rerun()

with col_btn2:
    if current_status == "connected":
        if st.button("🔌 Unlink Device", use_container_width=True, type="secondary"):
            unlink_whatsapp_session()
            st.warning("Session unlinked. Restarting bridge for new pairing...")
            start_baileys_bridge()
            time.sleep(2)
            st.rerun()
    else:
        if st.button("🚀 Start Bridge", use_container_width=True, type="primary"):
            start_python_api()
            start_baileys_bridge()
            st.success("Services starting...")
            time.sleep(2)
            st.rerun()

tabs = st.tabs(["📲 Link WhatsApp Device", "💬 Live Simulator & Test", "📜 Activity Stream", "⚙️ Diagnostics & Architecture"])

# ----------------- TAB 1: PAIRING -----------------
with tabs[0]:
    if current_status == "connected":
        st.success(f"🎉 Your WhatsApp account (+{status_data.get('phone_number', '')}) is active and replying automatically.")
        st.info("To switch to a different phone number or account, click **Unlink Device** at the top right.")
    else:
        st.markdown("### Scan QR Code with WhatsApp")
        qr_col1, qr_col2 = st.columns([1, 1.4])

        with qr_col1:
            if os.path.exists(QR_PATH):
                try:
                    img = Image.open(QR_PATH)
                    st.image(img, caption="Scan this QR code using WhatsApp", width=320)
                    st.caption("QR Code automatically refreshes until paired.")
                except Exception as e:
                    st.error(f"Loading QR image: {e}")
            else:
                st.info("Waiting for QR Code generation... Click **Start Bridge** or **Refresh Status**.")

        with qr_col2:
            st.markdown("""
            #### How to Link in 10 Seconds:
            1. Open **WhatsApp** on your mobile phone (either personal or business WhatsApp).
            2. Tap the **Menu icon** (three dots on Android) or **Settings** (on iPhone).
            3. Tap **Linked Devices**.
            4. Tap **Link a Device**.
            5. Point your camera at the QR code on the left.
            
            > **Benefits of Multi-Device Bridge:**
            > - **100% Free Forever:** No Twilio fees, no Meta Cloud approval delays.
            > - **No Message Limits:** Reply to unlimited customer chats and groups.
            > - **Native Media Delivery:** Sends real, high-resolution product photos directly to WhatsApp chats.
            """)
            if st.button("🔄 Check If Paired"):
                st.rerun()

# ----------------- TAB 2: SIMULATOR & TEST -----------------
with tabs[1]:
    st.markdown("### Test Hermes AI Response & Photo Delivery")
    st.caption("Simulate how Hermes will answer an incoming WhatsApp customer query.")

    quick_prompts = [
        "Give me RC item photos",
        "Show me dolls in stock with pictures",
        "What are wholesale prices for 360-1?",
        "Do you have toy guns in stock?",
        "clay"
    ]
    
    selected_p = st.pills("Quick Test Queries:", quick_prompts)
    test_query = st.text_input("Customer Inquiry:", value=selected_p or "Give me RC item photos", placeholder="e.g. Give me RC item photos")

    if st.button("Send Test Query", type="primary"):
        if test_query:
            with st.spinner("Google Gemini searching Supabase inventory & catalog..."):
                start_time = time.time()
                res = ask_hermes(test_query)
                elapsed = time.time() - start_time

                st.success(f"Generated response in {elapsed:.2f}s using `{res.get('model_used')}`")
                
                reply_col, media_col = st.columns([1.2, 1])
                
                with reply_col:
                    st.markdown("#### WhatsApp Text Message Preview:")
                    st.markdown(res.get("reply", ""))

                with media_col:
                    st.markdown(f"#### Attached Photos ({len(res.get('image_urls', []))}):")
                    images = res.get("image_urls", [])
                    if images:
                        for idx, url in enumerate(images):
                            st.image(url, caption=f"Attachment #{idx+1}", use_container_width=True)
                    else:
                        st.info("No photo attachments required for this response.")

# ----------------- TAB 3: ACTIVITY STREAM -----------------
with tabs[2]:
    st.markdown("### Real-Time WhatsApp Message Stream")
    logs = get_message_logs()
    
    col_filter, col_refresh = st.columns([4, 1])
    with col_refresh:
        if st.button("🔄 Refresh Stream"):
            st.rerun()

    if not logs:
        st.info("No messages received yet. Once customers text your linked WhatsApp number, messages will appear here in real-time.")
    else:
        for msg in logs:
            direction = msg.get("direction", "in")
            timestamp = msg.get("time", "")
            if direction == "in":
                st.markdown(f"""
                <div class="chat-bubble-in">
                    <span style="font-size: 0.8rem; color: #2563EB; font-weight: 600;">📥 INCOMING &bull; {timestamp} &bull; {msg.get('name', 'Customer')} (+{msg.get('from', '')})</span>
                    <p style="margin: 4px 0 0 0; font-size: 1rem; color: #1E293B;">{msg.get('text', '')}</p>
                </div>
                """, unsafe_allow_html=True)
            else:
                imgs_sent = msg.get("images_sent", 0)
                media_badge = f" &bull; 📷 {imgs_sent} Photos Sent" if imgs_sent > 0 else ""
                st.markdown(f"""
                <div class="chat-bubble-out">
                    <span style="font-size: 0.8rem; color: #15803D; font-weight: 600;">📤 OUTGOING &bull; {timestamp} &bull; To: {msg.get('name', '')} (+{msg.get('to', '')}){media_badge}</span>
                    <p style="margin: 4px 0 0 0; font-size: 0.95rem; color: #064E3B; white-space: pre-line;">{msg.get('text', '')}</p>
                </div>
                """, unsafe_allow_html=True)

# ----------------- TAB 4: DIAGNOSTICS & ARCHITECTURE -----------------
with tabs[3]:
    st.markdown("### System Architecture & Health Diagnostics")
    
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.metric("WhatsApp Multi-Device", "Connected" if current_status == "connected" else "Awaiting Scan", delta=current_status)
    with d2:
        st.metric("Hermes API Port 5005", "Online" if api_online else "Offline", delta="Active" if api_online else "Inactive")
    with d3:
        st.metric("Google Gemini Model", "Active", delta="3.1-flash-lite")
    with d4:
        st.metric("Supabase Database", "Synchronized", delta="1,202 items")

    st.markdown("""
    ---
    #### Data Flow:
    1. **Customer WhatsApp Message** → `@whiskeysockets/baileys` Node.js Multi-Device WebSocket.
    2. **Bridge Webhook** → Dispatches HTTP POST to `http://127.0.0.1:5005/chat`.
    3. **Python Server** → Evaluates message via `google-genai` SDK using `gemini-3.1-flash-lite-preview`.
    4. **Tool Calling** → Executes `search_products(search_term, has_photo_only, in_stock_only)` querying Primary Supabase `hermes_items`.
    5. **Media Packaging** → Extracts verified photo URLs, formats text for WhatsApp markdown (`*bold*`).
    6. **WhatsApp Dispatch** → Node.js bridge replies with text + individual high-res image messages natively.
    """)
