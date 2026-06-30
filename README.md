# FRIDAY — AI WhatsApp Secretary 🤖

> Forward Anything → AI Handles Everything

FRIDAY is an AI-powered personal secretary that lives in WhatsApp. Forward any message — placement announcements, assignment deadlines, bills, appointments — and FRIDAY automatically extracts the task, creates smart reminders, follows up, and tracks completion.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- A Gemini API key (free at https://aistudio.google.com)

### 1. Configure Environment

**Backend** — edit `backend/.env`:
```env
GEMINI_API_KEY=your_key_here
MY_WHATSAPP_NUMBER=91XXXXXXXXXX@c.us
```

**Bridge** — edit `bridge/.env`:
```env
BACKEND_URL=http://localhost:8000
BRIDGE_PORT=3000
```

### 2. Install Dependencies

```powershell
# Backend (Python)
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# Bridge (Node.js)
cd ..\bridge
npm install
```

### 3. Start FRIDAY

**Terminal 1 — Backend:**
```powershell
cd backend
.\venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

**Terminal 2 — WhatsApp Bridge:**
```powershell
cd bridge
npm start
```

### 4. Scan QR Code
When the bridge starts, a QR code appears in the terminal.
Open WhatsApp → Settings → Linked Devices → Link a Device → scan the QR.

FRIDAY is now live! 🎉

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
whatsapp-web.js Bridge (Node.js :3000)
     │ HTTP POST /webhook
     ▼
FastAPI Backend (Python :8000)
     ├── Gemini 2.0 Flash AI
     │     ├── Intent Classification
     │     ├── Entity Extraction
     │     └── Reminder Planning
     ├── SQLite Database
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
├── bridge/           ← Node.js WhatsApp bridge
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
