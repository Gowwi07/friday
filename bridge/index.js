/**
 * FRIDAY WhatsApp Bridge
 * 
 * Uses whatsapp-web.js to listen for incoming WhatsApp messages
 * and forward them to the FastAPI backend via HTTP POST.
 * 
 * Also exposes a small Express server so the backend can
 * send outbound WhatsApp messages back to the user.
 */

require("dotenv").config();
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode-terminal");
const axios = require("axios");
const express = require("express");

// ─── Config ────────────────────────────────────────────────────────────────
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || "3000");

// ─── WhatsApp Client ────────────────────────────────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({ clientId: "friday" }),
  puppeteer: {
    headless: true,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-accelerated-2d-canvas",
      "--no-first-run",
      "--disable-gpu",
    ],
  },
});

// QR Code — scan this with your phone to link WhatsApp Web
client.on("qr", (qr) => {
  console.log("\n📱 Scan this QR code with your WhatsApp:\n");
  qrcode.generate(qr, { small: true });
  console.log("\nWaiting for authentication...\n");
});

client.on("authenticated", () => {
  console.log("✅ WhatsApp authenticated successfully!");
});

client.on("ready", () => {
  console.log(`🚀 FRIDAY WhatsApp Bridge is ready!`);
  console.log(`📡 Forwarding messages to: ${BACKEND_URL}/webhook`);
});

client.on("auth_failure", (msg) => {
  console.error("❌ WhatsApp authentication failed:", msg);
});

client.on("disconnected", (reason) => {
  console.log("⚠️  WhatsApp disconnected:", reason);
});

// ─── Incoming Message Handler ───────────────────────────────────────────────
client.on("message", async (msg) => {
  try {
    // Only process messages from yourself (personal use)
    // or adjust to accept from any sender
    const chat = await msg.getChat();
    const contact = await msg.getContact();

    const payload = {
      message_id: msg.id.id,
      from: msg.from,           // e.g. "919876543210@c.us"
      from_name: contact.pushname || contact.name || msg.from,
      body: msg.body,
      type: msg.type,           // "chat", "image", "document", etc.
      timestamp: msg.timestamp,
      is_forwarded: msg.isForwarded,
      has_media: msg.hasMedia,
      chat_name: chat.name,
    };

    // If it has media (image/PDF), download and attach base64
    if (msg.hasMedia) {
      try {
        const media = await msg.downloadMedia();
        payload.media = {
          mimetype: media.mimetype,
          data: media.data,       // base64
          filename: media.filename,
        };
      } catch (err) {
        console.warn("⚠️  Could not download media:", err.message);
      }
    }

    console.log(`\n📩 Message from ${payload.from_name}: ${payload.body?.substring(0, 80)}...`);

    // Forward to FRIDAY backend
    const response = await axios.post(`${BACKEND_URL}/webhook`, payload, {
      timeout: 30000,
      headers: { "Content-Type": "application/json" },
    });

    console.log(`✅ Backend responded: ${response.status}`);
  } catch (err) {
    console.error("❌ Error forwarding message to backend:", err.message);
  }
});

// ─── Express Server (Backend → WhatsApp outbound) ──────────────────────────
const app = express();
app.use(express.json({ limit: "10mb" }));

/**
 * POST /send
 * Body: { to: "919876543210@c.us", message: "Hello!" }
 * 
 * Called by the FastAPI backend to send WhatsApp messages.
 */
app.post("/send", async (req, res) => {
  const { to, message } = req.body;

  if (!to || !message) {
    return res.status(400).json({ error: "Missing 'to' or 'message'" });
  }

  try {
    await client.sendMessage(to, message);
    console.log(`📤 Sent message to ${to}: ${message.substring(0, 60)}...`);
    res.json({ success: true });
  } catch (err) {
    console.error("❌ Failed to send WhatsApp message:", err.message);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /status
 * Health check endpoint.
 */
app.get("/status", async (req, res) => {
  const state = await client.getState().catch(() => "DISCONNECTED");
  res.json({
    status: "ok",
    whatsapp_state: state,
    timestamp: new Date().toISOString(),
  });
});

app.listen(BRIDGE_PORT, () => {
  console.log(`🌐 Bridge HTTP server listening on port ${BRIDGE_PORT}`);
});

// ─── Start WhatsApp Client ──────────────────────────────────────────────────
console.log("🔄 Initializing FRIDAY WhatsApp Bridge...");
client.initialize();
