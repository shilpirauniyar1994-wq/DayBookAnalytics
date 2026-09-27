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
    fetchLatestBaileysVersion,
    downloadMediaMessage
} = require('@whiskeysockets/baileys');
const pino = require('pino');
const QRCode = require('qrcode');
const axios = require('axios');
const fs = require('fs');
const path = require('path');
const net = require('net');

// Single-instance lock on port 5006 to prevent duplicate processes
const LOCK_PORT = 5006;
const lockServer = net.createServer();
lockServer.once('error', (err) => {
    if (err.code === 'EADDRINUSE') {
        console.log('[Bridge] Another instance of bridge_server.js is already running. Exiting duplicate process.');
        process.exit(0);
    }
});
lockServer.listen(LOCK_PORT, '127.0.0.1');

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

// Safely clear contents of auth folder (compatible with mounted volumes)
function clearAuthDir() {
    try {
        if (fs.existsSync(AUTH_DIR)) {
            const files = fs.readdirSync(AUTH_DIR);
            for (const file of files) {
                try {
                    fs.rmSync(path.join(AUTH_DIR, file), { recursive: true, force: true });
                } catch (_) {}
            }
        }
    } catch (e) {
        console.error('[Bridge] Error clearing auth files:', e.message);
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

    // Ensure auth directory exists
    if (!fs.existsSync(AUTH_DIR)) {
        try { fs.mkdirSync(AUTH_DIR, { recursive: true }); } catch (_) {}
    }

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
        browser: ['DayBook Hermes', 'Desktop', '1.0.0'],
        syncFullHistory: false,
        generateHighQualityLinkPreview: true,
    });

    sock.ev.on('creds.update', saveCreds);

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
                    phone_number: null,
                    user_name: null,
                    updated_at: new Date().toISOString()
                });
            } catch (err) {
                console.error('[Bridge] Failed to write qr.png:', err.message);
            }
        }

        if (connection === 'close') {
            const statusCode = (lastDisconnect?.error)?.output?.statusCode;
            const isLoggedOut = statusCode === DisconnectReason.loggedOut;
            const shouldReconnect = !isLoggedOut;
            const reason = lastDisconnect?.error?.message || `Status code ${statusCode}`;

            console.log(`[Bridge] Connection closed (${reason}). Reconnecting: ${shouldReconnect}`);

            if (fs.existsSync(QR_FILE)) {
                try { fs.unlinkSync(QR_FILE); } catch (_) {}
            }

            if (isLoggedOut) {
                console.log('[Bridge] User logged out. Clearing auth credentials...');
                clearAuthDir();
                updateStatus({
                    status: 'scan_qr',
                    qr_available: false,
                    phone_number: null,
                    user_name: null,
                    last_error: 'Logged out. Ready for new QR code.'
                });
                setTimeout(startBridge, 2000);
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

    sock.ev.on('messages.upsert', async (m) => {
        if (m.type !== 'notify') return;

        for (const msg of m.messages) {
            if (msg.key.fromMe) continue;
            if (msg.key.remoteJid === 'status@broadcast') continue;
            const senderJid = msg.key.remoteJid;
            const pushName = msg.pushName || 'Customer';
            const senderPhone = senderJid.split('@')[0];
            const isGroup = senderJid.endsWith('@g.us');

            const messageContent = 
                msg.message?.ephemeralMessage?.message ||
                msg.message?.viewOnceMessage?.message ||
                msg.message?.viewOnceMessageV2?.message ||
                msg.message;

            const imageMsg = messageContent?.imageMessage;
            const isImage = !!imageMsg;
            let imageBase64 = null;
            let mimeType = 'image/jpeg';

            if (isImage) {
                try {
                    console.log(`[Bridge] Downloading incoming photo from ${pushName} (+${senderPhone})...`);
                    const imgBuffer = await downloadMediaMessage(
                        msg,
                        'buffer',
                        {},
                        {
                            logger: pino({ level: 'silent' }),
                            reuploadRequest: sock.updateMediaMessage
                        }
                    );
                    if (imgBuffer && imgBuffer.length > 0) {
                        imageBase64 = imgBuffer.toString('base64');
                        mimeType = imageMsg.mimetype || 'image/jpeg';
                        console.log(`[Bridge] Downloaded photo (${(imgBuffer.length / 1024).toFixed(1)} KB, type: ${mimeType})`);
                    }
                } catch (err) {
                    console.error('[Bridge] Error downloading image media:', err.message);
                }
            }

            const text = 
                messageContent?.conversation ||
                messageContent?.extendedTextMessage?.text ||
                imageMsg?.caption ||
                '';

            const trimmedText = text.trim();
            if (!trimmedText && !imageBase64) continue;

            const displayMsg = trimmedText || (imageBase64 ? '[Sent a photo]' : '');
            console.log(`[Bridge] Incoming from ${pushName} (+${senderPhone}): "${displayMsg}"`);

            logMessage({
                direction: 'in',
                from: senderPhone,
                name: pushName,
                is_group: isGroup,
                text: displayMsg
            });

            try {
                await sock.sendPresenceUpdate('composing', senderJid);
            } catch (_) {}

            try {
                const response = await axios.post(PYTHON_API_URL, {
                    message: trimmedText,
                    image_base64: imageBase64,
                    mime_type: mimeType,
                    sender: senderPhone,
                    push_name: pushName
                }, {
                    timeout: 60000,
                    headers: { 'Content-Type': 'application/json' }
                });

                const data = response.data;
                const replyText = data?.reply || "I've checked the catalog, but couldn't retrieve the details.";
                const images = Array.isArray(data?.images) ? data.images : [];

                await sock.sendMessage(senderJid, { text: replyText }, { quoted: msg });

                if (images.length > 0) {
                    console.log(`[Bridge] Sending ${images.length} product photos to +${senderPhone}...`);
                    for (const img of images) {
                        const imgUrl = typeof img === 'string' ? img : img.url;
                        const imgPath = typeof img === 'object' ? img.path : null;
                        const caption = typeof img === 'string' ? '' : (img.caption || '');

                        try {
                            if (imgPath && fs.existsSync(imgPath)) {
                                console.log(`[Bridge] Sending local image: ${imgPath}`);
                                await sock.sendMessage(senderJid, {
                                    image: fs.readFileSync(imgPath),
                                    caption: caption
                                });
                                await new Promise((r) => setTimeout(r, 600));
                            } else if (imgUrl) {
                                console.log(`[Bridge] Sending remote image: ${imgUrl}`);
                                await sock.sendMessage(senderJid, {
                                    image: { url: imgUrl },
                                    caption: caption
                                });
                                await new Promise((r) => setTimeout(r, 600));
                            }
                        } catch (imgErr) {
                            console.error(`[Bridge] Failed to send image (${imgPath || imgUrl}):`, imgErr.message);
                        }
                    }
                }

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

updateStatus({ status: 'offline', qr_available: false });

startBridge().catch((err) => {
    console.error('[Bridge] Fatal error on start:', err);
    updateStatus({ status: 'error', last_error: err.message });
});
