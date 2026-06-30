@echo off
echo.
echo  ╔═══════════════════════════════════════╗
echo  ║  FRIDAY - Local Server with Cloudflare ║
echo  ╚═══════════════════════════════════════╝
echo.
echo  Starting FastAPI local backend...
echo  (Connecting to Neon PostgreSQL + Gemini API)
echo.

REM --- Check backend config ---
findstr /C:"your_whatsapp_access_token_here" backend\.env >nul 2>&1
if not errorlevel 1 (
    echo  ⚠️  WARNING: WhatsApp credentials in backend/.env are not set yet!
    echo  Please fill them in before starting.
    echo.
)

REM --- Start Cloudflare Tunnel in a new window ---
echo  Exposing port 8000 using Cloudflare Tunnel...
start "FRIDAY Webhook Tunnel" cmd /k "bin\cloudflared.exe tunnel --url http://localhost:8000"

REM --- Start Backend ---
echo  Starting FastAPI backend on http://localhost:8000 ...
echo  API Docs: http://localhost:8000/docs
echo.
cd backend
call .\venv\Scripts\activate
uvicorn main:app --reload --port 8000

pause
