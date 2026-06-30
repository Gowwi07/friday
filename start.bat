@echo off
echo.
echo  ========================================
echo    FRIDAY - AI WhatsApp Secretary (Dev)
echo  ========================================
echo.
echo  (Local dev mode - for testing only)
echo  Production runs on Google Cloud Run.
echo.

REM --- Check config ---
findstr /C:"your_whatsapp_access_token_here" backend\.env >nul 2>&1
if not errorlevel 1 (
    echo  WARNING: WhatsApp API not configured yet.
    echo  See SETUP.md for instructions.
    echo.
)

REM --- Start Backend ---
echo  Starting FRIDAY backend on http://localhost:8000 ...
echo  API Docs: http://localhost:8000/docs
echo.
cd backend
call .\venv\Scripts\activate
uvicorn main:app --reload --port 8000

pause
