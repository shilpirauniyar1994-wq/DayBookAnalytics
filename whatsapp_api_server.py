"""
WhatsApp API Server — Native Multi-Threaded HTTP Server for Google Hermes AI Engine
Bridges Baileys WhatsApp client with Google Gemini catalog and inventory search.
Runs on http://127.0.0.1:5005
"""

import os
import sys
import json
import re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import List, Dict, Any, Tuple
from google_hermes_engine import ask_hermes, is_photo_requested

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

PORT = 5005
LOCAL_IMAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "HermesData", "assets", "images"))

def format_markdown_for_whatsapp(raw_text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Transforms markdown into WhatsApp-friendly text formatting and extracts
    all embedded images (both remote URLs and local server filepaths) with their captions.
    """
    # 1. Extract markdown images ![alt](target)
    img_matches = re.findall(r'!\[(.*?)\]\(((?:https?://|local://).*?\.(?:jpe?g|png|webp)|[^\s\)]+)\)', raw_text, re.IGNORECASE)
    images = []
    for alt, target in img_matches:
        caption = f"*{alt}*" if alt else ""
        if target.startswith(("http://", "https://")):
            images.append({"url": target, "path": None, "caption": caption})
        elif target.startswith("local://"):
            fname = target[8:]
            fpath = os.path.join(LOCAL_IMAGE_DIR, fname)
            if os.path.exists(fpath):
                images.append({"url": None, "path": fpath, "caption": caption})
        elif os.path.isabs(target) and os.path.exists(target):
            images.append({"url": None, "path": target, "caption": caption})
        else:
            fpath = os.path.join(LOCAL_IMAGE_DIR, os.path.basename(target))
            if os.path.exists(fpath):
                images.append({"url": None, "path": fpath, "caption": caption})

    # 2. Fallback: If no markdown images found but raw image URLs exist
    if not images:
        raw_urls = re.findall(r'(https?://[^\s\)]+?\.(?:jpg|jpeg|png|webp))', raw_text, re.IGNORECASE)
        for u in raw_urls:
            images.append({"url": u, "path": None, "caption": ""})

    text = raw_text

    # 3. Strip out the ![alt](url) tags from text
    text = re.sub(r'!\[.*?\]\(((?:https?://|local://).*?\.(?:jpe?g|png|webp)|[^\s\)]+)\)\n?', '', text, flags=re.IGNORECASE)

    # 4. Convert headers (### Title) to WhatsApp bold (*Title*)
    text = re.sub(r'#{1,6}\s*(.*)', r'*\1*', text)

    # 5. Convert markdown bold (**text**) to WhatsApp bold (*text*)
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)

    # 6. Convert markdown list dashes to bullet points
    text = re.sub(r'^\s*[\*\-]\s+', '• ', text, flags=re.MULTILINE)

    # 7. Convert horizontal rules to simple dividers
    text = re.sub(r'\*{3,}|-{3,}', '────────────────', text)

    # 8. Clean up extra blank lines
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    return text, images

class HermesRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, data: Dict[str, Any]):
        try:
            response_bytes = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(response_bytes)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
            self.wfile.write(response_bytes)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        if self.path in ['/', '/health']:
            self._send_json(200, {
                "status": "online",
                "service": "Hermes WhatsApp AI Backend",
                "engine": "Google Gemini"
            })
        else:
            self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        if self.path == '/chat':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                payload = json.loads(body) if body else {}
            except Exception as e:
                self._send_json(400, {"error": f"Invalid JSON payload: {e}"})
                return

            user_msg = str(payload.get('message', '')).strip()
            sender = payload.get('sender', 'Unknown')
            push_name = payload.get('push_name', 'Customer')

            if not user_msg:
                self._send_json(400, {"error": "Message parameter is required"})
                return

            photo_wanted = is_photo_requested(user_msg)
            print(f"[API Server] Incoming message from {push_name} ({sender}): {user_msg} [Photo Requested: {photo_wanted}]", flush=True)

            try:
                # Query Google Hermes Engine
                result = ask_hermes(user_msg)

                raw_reply = result.get("reply", "")
                model_used = result.get("model_used")
                status = result.get("status", "success")

                # Format text and extract images
                wa_text, extracted_images = format_markdown_for_whatsapp(raw_reply)

                if not photo_wanted:
                    # Enforce zero images when photos were not explicitly requested
                    extracted_images = []
                else:
                    # Deduplicate and ensure all photo URLs from engine are present
                    existing_urls = {img["url"] for img in extracted_images if img.get("url")}
                    for u in result.get("image_urls", []):
                        if u not in existing_urls:
                            extracted_images.append({"url": u, "path": None, "caption": ""})
                            existing_urls.add(u)

                print(f"[API Server] Responded with {len(extracted_images)} images via {model_used}", flush=True)

                self._send_json(200, {
                    "status": status,
                    "reply": wa_text,
                    "images": extracted_images,
                    "model_used": model_used
                })
            except (BrokenPipeError, ConnectionResetError):
                print(f"[API Server] Client disconnected before response could be sent for {sender}", flush=True)
            except Exception as e:
                print(f"[API Server] Error processing message: {e}", flush=True)
                try:
                    self._send_json(500, {
                        "status": "error",
                        "reply": "Sorry, an internal error occurred while querying inventory.",
                        "images": [],
                        "error": str(e)
                    })
                except Exception:
                    pass
        else:
            self._send_json(404, {"error": "Endpoint Not Found"})

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f"[HTTP] {self.address_string()} - {format % args}\n")

def run_server():
    server_address = ('127.0.0.1', PORT)
    httpd = ThreadingHTTPServer(server_address, HermesRequestHandler)
    print(f"[Hermes WhatsApp API Backend] listening on http://127.0.0.1:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Hermes WhatsApp API Backend...", flush=True)
        httpd.server_close()

if __name__ == "__main__":
    run_server()
