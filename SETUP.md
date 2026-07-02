# FRIDAY — Setup Guide (Meta Edition)

## Step 1: Meta WhatsApp Business API Setup

### 1.1 Create a Meta Developer App
1. Go to **https://developers.facebook.com**
2. Click **My Apps → Create App**
3. Select **Business** → Next
4. Enter app name: `FRIDAY` → Create
5. On the dashboard, click **Add Product** → find **WhatsApp** → click **Set Up**

### 1.2 Get Your Credentials
In your app dashboard → **WhatsApp → API Setup**:

- **Phone Number ID**: Copy the ID shown under the "From" section.
- **Access Token**: Copy the temporary token shown (valid 24h for testing).
- **WhatsApp Business Account ID**: Also shown on this page.

### 1.3 Add Your Number as Test Recipient
- Under the **To** field, click **Add phone number**.
- Add YOUR personal WhatsApp number.
- Verify with the OTP sent to your phone.

### 1.4 Fill in backend/.env
```env
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxx...   (your access token)
WHATSAPP_PHONE_NUMBER_ID=1234567890   (the Phone Number ID)
WHATSAPP_VERIFY_TOKEN=choose_a_long_private_random_value
MY_WHATSAPP_NUMBER=919876543210   (your personal number, no + or spaces)
```

---

## Step 2: Database — Neon PostgreSQL (Free, Always-On)

1. Go to **https://neon.tech** → Sign up free.
2. Create or open your FRIDAY database project.
3. Locate your pooled connection string on the Neon dashboard.
4. Use the async SQLAlchemy format in Render and local `.env`:
   ```
   postgresql+asyncpg://USER:PASSWORD@HOST/DBNAME?ssl=require
   ```

---

## Step 3: Deploy to Render Free

The repository includes `render.yaml`, which defines the `friday-backend`
service using Render's free Docker web service.

1. Sign in to **https://render.com** with GitHub.
2. Create a new Blueprint or web service from this repository.
3. Select the `friday-backend` service from `render.yaml`.
4. Add these environment variables in Render:
   - `GEMINI_API_KEY`
   - `WHATSAPP_ACCESS_TOKEN`
   - `WHATSAPP_PHONE_NUMBER_ID`
   - `WHATSAPP_VERIFY_TOKEN`
   - `MY_WHATSAPP_NUMBER`
   - `DATABASE_URL`
   - `CRON_SECRET`
5. Deploy the service and copy its public Render URL.

The GitHub Actions workflow `.github/workflows/keep-friday-awake.yml` calls
`/maintenance` every 5 minutes so Render Free can wake the service and process
scheduled reminders. Add matching GitHub repository secrets:

- `FRIDAY_RENDER_URL`: the Render service URL without a trailing slash
- `FRIDAY_CRON_SECRET`: the same value as Render's `CRON_SECRET`

---

## Step 4: Register Webhook with Meta

Once deployed, copy the Render webhook URL, for example:
`https://friday-backend-xxxx.onrender.com/webhook`.

1. Go to **Meta App → WhatsApp → Configuration**.
2. Click **Edit** under **Webhook**.
3. Callback URL: `https://friday-backend-xxxx.onrender.com/webhook`
4. Verify Token: the exact private value you set as `WHATSAPP_VERIFY_TOKEN` in Render.
5. Click **Verify and Save**.
6. Under Webhook Fields, click **Manage** and subscribe to **`messages`**.

---

## Step 5: Test FRIDAY!

Send a message from your personal WhatsApp to **FRIDAY's Meta Business number**:
```
TCS PPT tomorrow at 1:30 PM in Centenary Auditorium
```
FRIDAY should reply to your chat instantly!
