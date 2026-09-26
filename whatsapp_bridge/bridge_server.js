/**
 * WhatsApp Multi-Device Bridge Server
 * Powered by @whiskeysockets/baileys
 * 
 * Connects directly to WhatsApp without third-party APIs or message limits.
 * Forwards user queries to Python Google Hermes backend (http://127.0.0.1:5005/chat)
 * and delivers text responses and native product photo attachments.
 */

const {
    default: makeWASocket,
    useMultiFileAuthState,
    DisconnectReason,
    fetchLatestBaileysVersion
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const QRCode = require('qrcode');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

const AUTH_DIR = path.join(__dirname, 'auth_info_baileys');
const QR_FILE = path.join(__dirname, 'qr.png');
const STATUS_FILE = path.join(__dirname, 'status.json');
const LOG_FILE = path.join(__dirname, 'messages_log.json');
const PYTHON_API_URL = 'http://127.0.0.1:5005/chat';

// Helper to write status
function updateStatus(statusObj) {
    const current = {
        status: 'initializing',
        phone_number: null,
        user_name: null,
        qr_available: false,
        last_error: null,
        updated_at: new Date().toISOString(),
        ...statusObj
    };
    try {
        fs.writeFileSync(STATUS_FILE, JSON.stringify(current, null, 2), 'utf-8');
    } catch (e) {
        console.error('Error writing status file:', e.message);
    }
}

// Helper to log recent messages
function logMessage(entry) {
    try {
        let logs = [];
        if (fs.existsSync(LOG_FILE)) {
            const raw = fs.readFileSync(LOG_FILE, 'utf-8');
            logs = JSON.parse(raw);
            if (!Array.isArray(logs)) logs = [];
        }
        logs.unshift({
            id: entry.id || Date.now().toString(),
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            ...entry
        });
        // Keep last 50
        if (logs.length > 50) logs = logs.slice(0, 50);
        fs.writeFileSync(LOG_FILE, JSON.stringify(logs, null, 2), 'utf-8');
    } catch (e) {
        console.error('Error updating message log:', e.message);
    }
}

let sock = null;

async function startBridge() {
    console.log('[Bridge] Starting WhatsApp Multi-Device connection...');
    updateStatus({ status: 'starting', qr_available: false });

    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

    let version = [2, 3000, 1015901307];
    try {
        const v = await fetchLatestBaileysVersion();
        if (v && v.version) version = v.version;
    } catch (e) {
        console.log('[Bridge] Using default Baileys version:', version.join('.'));
    }

    sock = makeWASocket({
        version,
        auth: state,
        logger: pino({ level: 'silent' }),
        printQRInTerminal: true,
        browser: ['DayBook Hermes', 'Desktop', '1.0.0'],
        syncFullHistory: false,
        generateHighQualityLinkPreview: true,
    });

    // Save auth credentials whenever updated
    sock.ev.on('creds.update', saveCreds);

    // Monitor connection events
    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log('[Bridge] New QR code generated. Scan it with WhatsApp (Linked Devices)!');
            try {
                await QRCode.toFile(QR_FILE, qr, {
                    width: 320,
                    margin: 2,
                    color: {
                        dark: '#0f172a',
                        light: '#ffffff'
                    }
                });
                updateStatus({
                    status: 'scan_qr',
                    qr_available: true,
                    updated_at: new Date().toISOString()
                });
            } catch (err) {
                console.error('[Bridge] Failed to write qr.png:', err.message);
            }
        }

        if (connection === 'close') {
            const statusCode = (lastDisconnect?.error)?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            const reason = lastDisconnect?.error?.message || `Status code ${statusCode}`;

            console.log(`[Bridge] Connection closed (${reason}). Reconnecting: ${shouldReconnect}`);

            // If QR file exists, clean it up
            if (fs.existsSync(QR_FILE)) {
                try { fs.unlinkSync(QR_FILE); } catch (_) {}
            }

            if (statusCode === DisconnectReason.loggedOut) {
                console.log('[Bridge] User logged out. Clearing auth credentials...');
                try {
                    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
                } catch (_) {}
                updateStatus({
                    status: 'logged_out',
                    qr_available: false,
                    last_error: 'Session logged out from WhatsApp.'
                });
                // Restart to show fresh QR code
                setTimeout(startBridge, 3000);
            } else {
                updateStatus({
                    status: 'reconnecting',
                    qr_available: false,
                    last_error: reason
                });
                if (shouldReconnect) {
                    setTimeout(startBridge, 3000);
                }
            }
        } else if (connection === 'open') {
            console.log('====================================================');
            console.log(' WhatsApp Bridge Connected Successfully!');
            const userJid = sock.user?.id || '';
            const phone = userJid.split(':')[0] || userJid.split('@')[0];
            const userName = sock.user?.name || 'Demo Khelauna Assistant';
            console.log(` Phone: +${phone} | Name: ${userName}`);
            console.log(' Ready to receive queries and send product photos!');
            console.log('====================================================');

            // Delete QR image when connected
            if (fs.existsSync(QR_FILE)) {
                try { fs.unlinkSync(QR_FILE); } catch (_) {}
            }

            updateStatus({
                status: 'connected',
                phone_number: phone,
                user_name: userName,
                qr_available: false,
                last_error: null
            });
        }
    });

    // Listen for incoming messages
    sock.ev.on('messages.upsert', async (m) => {
        if (m.type !== 'notify') return;

        for (const msg of m.messages) {
            // Ignore messages from self or status broadcasts
            if (msg.key.fromMe) continue;
            if (msg.key.remoteJid === 'status@broadcast') continue;
            // Ignore group messages (focus on 1-on-1 customer inquiries, or allow both)
            const isGroup = msg.key.remoteJid.endsWith('@g.us');

            // Extract message text
            const text = 
                msg.message?.conversation ||
                msg.message?.extendedTextMessage?.text ||
                msg.message?.imageMessage?.caption ||
                '';

            const trimmedText = text.trim();
            if (!trimmedText) continue;

            const senderJid = msg.key.remoteJid;
            const pushName = msg.pushName || 'Customer';
            const senderPhone = senderJid.split('@')[0];

            console.log(`[Bridge] Incoming from ${pushName} (+${senderPhone}): "${trimmedText}"`);

            // Log incoming
            logMessage({
                direction: 'in',
                from: senderPhone,
                name: pushName,
                is_group: isGroup,
                text: trimmedText
            });

            // Indicate typing indicator in WhatsApp
            try {
                await sock.sendPresenceUpdate('composing', senderJid);
            } catch (_) {}

            try {
                // Forward request to Python Google Hermes Engine
                const response = await axios.post(PYTHON_API_URL, {
                    message: trimmedText,
                    sender: senderPhone,
                    push_name: pushName
                }, {
                    timeout: 45000,
                    headers: { 'Content-Type': 'application/json' }
                });

                const data = response.data;
                const replyText = data?.reply || "I've checked the catalog, but couldn't retrieve the details.";
                const images = Array.isArray(data?.images) ? data.images : [];

                // 1. Send the text response
                await sock.sendMessage(senderJid, { text: replyText }, { quoted: msg });

                // 2. Send attached product photos natively
                if (images.length > 0) {
                    console.log(`[Bridge] Sending ${images.length} product photos to +${senderPhone}...`);
                    for (const img of images) {
                        const imgUrl = typeof img === 'string' ? img : img.url;
                        const caption = typeof img === 'string' ? '' : (img.caption || '');
                        if (imgUrl) {
                            try {
                                await sock.sendMessage(senderJid, {
                                    image: { url: imgUrl },
                                    caption: caption
                                });
                                // Small delay between image uploads for smooth delivery
                                await new Promise((r) => setTimeout(r, 600));
                            } catch (imgErr) {
                                console.error(`[Bridge] Failed to send image ${imgUrl}:`, imgErr.message);
                            }
                        }
                    }
                }

                // Log outgoing
                logMessage({
                    direction: 'out',
                    to: senderPhone,
                    name: pushName,
                    text: replyText.slice(0, 160) + (replyText.length > 160 ? '...' : ''),
                    images_sent: images.length
                });

                console.log(`[Bridge] Replied to +${senderPhone} with ${images.length} photos.`);
            } catch (err) {
                console.error('[Bridge] Error handling message:', err.message);
                const errMsg = "Sorry, our inventory server is temporarily busy. Please ask again in a moment!";
                try {
                    await sock.sendMessage(senderJid, { text: errMsg }, { quoted: msg });
                } catch (_) {}
            } finally {
                try {
                    await sock.sendPresenceUpdate('paused', senderJid);
                } catch (_) {}
            }
        }
    });
}

// Initial status write
updateStatus({ status: 'offline', qr_available: false });

startBridge().catch((err) => {
    console.error('[Bridge] Fatal error on start:', err);
    updateStatus({ status: 'error', last_error: err.message });
});
