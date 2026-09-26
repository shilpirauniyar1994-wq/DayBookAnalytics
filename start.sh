#!/bin/bash
set -e

echo "=== [1/3] Starting Hermes WhatsApp API Server (Port 5005) ==="
python3 whatsapp_api_server.py &

echo "=== [2/3] Starting WhatsApp Baileys Bridge Server ==="
(cd whatsapp_bridge && node bridge_server.js) &

echo "=== [3/3] Starting Streamlit Dashboard (Port 7860) ==="
exec python3 -m streamlit run app.py \
    --server.port 7860 \
    --server.address 0.0.0.0 \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    --server.headless true
