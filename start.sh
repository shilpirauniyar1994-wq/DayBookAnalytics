#!/bin/bash
set -e

APP_PORT="${PORT:-8501}"

# Ensure full permissions on mounted volume directory
mkdir -p /app/whatsapp_bridge/auth_info_baileys
chmod -R 777 /app/whatsapp_bridge/auth_info_baileys || true

echo "=== [1/3] Starting Hermes WhatsApp API Server (Port 5005) ==="
python3 whatsapp_api_server.py &

echo "=== [2/3] Starting WhatsApp Baileys Bridge Server ==="
(cd whatsapp_bridge && node bridge_server.js) &

echo "=== [3/3] Starting Streamlit Dashboard (Port $APP_PORT) ==="
exec python3 -m streamlit run app.py \
    --server.port "$APP_PORT" \
    --server.address 0.0.0.0 \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --server.headless true
