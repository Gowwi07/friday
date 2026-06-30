# FRIDAY — Local Webhook Tunnel Setup (Cloudflare)

Since Meta's servers cannot reach `localhost` directly, we use **Cloudflare Tunnel** (`cloudflared`) to expose your local FastAPI server to the internet.

This is highly secure, fast, and does not require Node.js or `npm`.

## 1. Run FRIDAY Locally
Double-click **`start.bat`** in the project root. This will open two terminal windows:
1. **FRIDAY Backend**: Runs FastAPI on `http://localhost:8000`.
2. **FRIDAY Webhook Tunnel**: Runs `bin\cloudflared.exe` to expose port 8000.

---

## 2. Get Your Webhook URL
Look at the **Tunnel** terminal window (titled "FRIDAY Webhook Tunnel"). It will display a block like:
```text
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://projects-promises-organizational-illustration.trycloudflare.com                   |
+--------------------------------------------------------------------------------------------+
```

Copy that URL and append `/webhook` to the end of it:
```text
https://projects-promises-organizational-illustration.trycloudflare.com/webhook
```

---

## 3. Register Webhook with Meta (WhatsApp Business)
1. Go to **[developers.facebook.com/apps](https://developers.facebook.com/apps)** → Your App.
2. Left sidebar: **WhatsApp → Configuration**.
3. Under **Webhook**, click **Edit**:
   - **Callback URL**: Paste your Cloudflare Webhook URL (ends in `.trycloudflare.com/webhook`)
   - **Verify Token**: `friday_webhook_secret_2026`
4. Click **Verify and Save**.
5. Click **Manage** under Webhook Fields and subscribe to **`messages`**.

---

## 4. Keeping it Persistent
- The tunnel runs as long as the console window is open.
- When you close and reopen `start.bat`, a new quick tunnel URL will be generated. You'll just need to update it once in the Meta developer panel.
