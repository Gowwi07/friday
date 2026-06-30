# FRIDAY — Setup Guide (Twilio Edition)

## Step 1: Setup Twilio WhatsApp Sandbox (Takes 2 minutes)

### 1.1 Sign up for Twilio
1. Go to **https://www.twilio.com/try-twilio** and sign up for a free account.
2. In the Twilio Console homepage, scroll down to the **Account Info** section.
3. Copy these two values:
   - **Account SID**
   - **Auth Token**

### 1.2 Access the WhatsApp Sandbox
1. In the left sidebar, navigate to: **Messaging → Try it out → Send a WhatsApp Message**.
2. You'll see instructions to join the Sandbox:
   - **Sandbox Number**: e.g., `+1 415 523 8886`
   - **Join Code**: e.g., `join [some-word]`
3. Send that Join Code message from your personal phone number to the Sandbox Number. 
4. Twilio will reply confirming your phone is linked!

### 1.3 Fill in `backend/.env`
Update your local environment variables in `backend/.env`:
```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxx   (your Account SID)
TWILIO_AUTH_TOKEN=your_auth_token_here          (your Auth Token)
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886    (keep as-is or use your Twilio number)
MY_WHATSAPP_NUMBER=whatsapp:+919876543210       (your personal phone number with country code)
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

## Step 4: Hook the Webhook to Twilio Sandbox

Once deployed, copy the Webhook URL from the deploy output (e.g. `https://friday-backend-xxxx-el.a.run.app/webhook`).

1. Go back to your Twilio Console: **Messaging → Settings → WhatsApp Sandbox Settings**.
2. Paste your webhook URL in **"When a message comes in"**:
   - URL: `https://friday-backend-xxxx-el.a.run.app/webhook`
   - Method: `POST` (or Webhook)
3. Click **Save**.

---

## Step 5: Test FRIDAY!

Send a message from your personal WhatsApp to the **Twilio Sandbox number** (`+1 415 523 8886`):
```
TCS PPT tomorrow at 1:30 PM in Centenary Auditorium
```

FRIDAY should process it and reply right back via Twilio! 🎉
```
📋 What's pending?
```
Should return your active tasks directly in WhatsApp!
