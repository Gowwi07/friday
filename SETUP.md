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
WHATSAPP_VERIFY_TOKEN=friday_webhook_secret_2026   (keep this as-is)
MY_WHATSAPP_NUMBER=919876543210   (your personal number, no + or spaces)
```

---

## Step 2: Database — Neon PostgreSQL (Free, Always-On)

1. Go to **https://neon.tech** → Sign up free.
2. The browser subagent has already created a project named `polished-moon-36681946`.
3. Locate your connection details on the Neon dashboard.
4. Copy the connection string (already configured in your local `.env`!):
   ```
   postgresql+asyncpg://neondb_owner:npg_gA2ZhF7jeHDB@ep-nameless-math-aivxsr2z-pooler.c-4.us-east-1.aws.neon.tech/neondb?ssl=require
   ```

---

## Step 3: Deploy to Google Cloud Run

### 3.1 Set your GCP Project
First, make sure your gcloud CLI points to your target GCP Project ID:
```powershell
gcloud config set project YOUR_PROJECT_ID
```

### 3.2 Run the Deploy Script
```powershell
python deploy.py
```
This script will build the Docker container, enable Google Cloud Run APIs, deploy it, and output the **Service URL**.

---

## Step 4: Register Webhook with Meta

Once deployed, copy the Webhook URL from the deploy output (e.g. `https://friday-backend-xxxx.a.run.app/webhook`).

1. Go to **Meta App → WhatsApp → Configuration**.
2. Click **Edit** under **Webhook**.
3. Callback URL: `https://friday-backend-xxxx.a.run.app/webhook`
4. Verify Token: `friday_webhook_secret_2026`
5. Click **Verify and Save**.
6. Under Webhook Fields, click **Manage** and subscribe to **`messages`**.

---

## Step 5: Test FRIDAY!

Send a message from your personal WhatsApp to **FRIDAY's Meta Business number**:
```
TCS PPT tomorrow at 1:30 PM in Centenary Auditorium
```
FRIDAY should reply to your chat instantly!
