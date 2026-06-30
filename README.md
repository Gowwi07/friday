# FRIDAY — AI WhatsApp Secretary 🤖

> Forward Anything → AI Handles Everything

FRIDAY is an AI-powered personal secretary that lives in WhatsApp. Forward any message — placement announcements, assignment deadlines, bills, appointments — and FRIDAY automatically extracts the task, creates smart reminders, follows up, and tracks completion.

---

## Quick Start

### Prerequisites
- Python 3.11+
- A Gemini API key (free at https://aistudio.google.com)
- A Meta WhatsApp Business app and Cloud API credentials
- A PostgreSQL database for deployment (Neon works well)

### 1. Configure Environment

**Backend** — edit `backend/.env`:
```env
GEMINI_API_KEY=your_key_here
WHATSAPP_ACCESS_TOKEN=your_meta_access_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_VERIFY_TOKEN=choose_a_private_verify_token
MY_WHATSAPP_NUMBER=91XXXXXXXXXX
DATABASE_URL=postgresql+asyncpg://...
```

### 2. Install Dependencies

```powershell
# Backend (Python)
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start FRIDAY

**Terminal 1 — Backend:**
```powershell
cd backend
.\venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

### 4. Connect the webhook

For local testing, follow [TUNNEL.md](TUNNEL.md). For production, follow
[SETUP.md](SETUP.md) and deploy the backend with `python deploy.py`. Register
the resulting public `/webhook` URL in the Meta developer console.

The `bridge/` directory is retained only as an optional legacy adapter. The
production application uses Meta's official WhatsApp Cloud API and does not
require a QR code or a continuously running browser.

---

## Usage

### Create Tasks (just send naturally)
```
Team meeting tomorrow 10 AM
```
```
Submit Lab 2 assessment by 11:59 PM tonight
```
```
Netflix renewal July 15
```
```
TCS PPT - July 1, 1:30 PM, Centenary Auditorium
```

### Mark Complete
```
Done
Paid
Submitted
Attended
```

### Check What's Pending
```
What's pending?
```

---

## Architecture

```
Your WhatsApp
     │
     ▼
Meta WhatsApp Cloud API
     │ HTTPS webhook
     ▼
FastAPI Backend (Python / Cloud Run)
     ├── Gemini 2.5 Flash AI
     │     ├── Intent Classification
     │     ├── Entity Extraction
     │     └── Reminder Planning
     ├── PostgreSQL / SQLite Database
     │     ├── Events
     │     ├── Reminder Plans
     │     └── Conversation Memory
     └── APScheduler
           ├── Minute-level reminder checker
           ├── Morning brief (7 AM)
           └── Night summary (10 PM)
```

---

## API Docs
Visit http://localhost:8000/docs for interactive Swagger UI.

---

## Project Structure
```
FRIDAY/
├── bridge/           ← optional legacy local adapter
│   ├── index.js
│   └── package.json
├── backend/          ← Python FastAPI backend
│   ├── main.py
│   ├── config.py
│   ├── ai/           ← Gemini agent + reminder planner
│   ├── api/          ← Webhook + REST endpoints
│   ├── database/     ← SQLAlchemy models + DB session
│   ├── scheduler/    ← APScheduler jobs
│   └── services/     ← WhatsApp sender, summary, reminder logic
└── README.md
```
