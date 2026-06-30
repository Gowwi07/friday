#!/usr/bin/env python3
"""
FRIDAY — Google Cloud Run Deployment Script (Twilio Edition)

Deploys the backend to Cloud Run with all environment variables.
Run from the project root: python deploy.py

Requirements:
  - gcloud CLI authenticated (gcloud auth login)
  - A GCP project set (gcloud config set project YOUR_PROJECT_ID)
  - backend/.env filled in with all values
"""

import subprocess
import sys
import os
from pathlib import Path
from dotenv import dotenv_values

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ENV_FILE = Path(__file__).parent / "backend" / ".env"
SERVICE_NAME = "friday-backend"
REGION = "asia-south1"  # Mumbai — closest to India


def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    print(f"\n$ {' '.join(cmd)}")
    use_shell = sys.platform == "win32"
    return subprocess.run(cmd, check=check, text=True, shell=use_shell)


def get_project_id() -> str:
    use_shell = sys.platform == "win32"
    result = subprocess.run(
        ["gcloud", "config", "get-value", "project"],
        capture_output=True, text=True, shell=use_shell
    )
    return result.stdout.strip()


def main():
    print("=" * 60)
    print("  FRIDAY - Google Cloud Run Deploy (Twilio Edition)")
    print("=" * 60)

    # 1. Check project
    project_id = get_project_id()
    if not project_id or project_id == "(unset)":
        print("\nERROR: No GCP project set.")
        print("Run: gcloud config set project YOUR_PROJECT_ID")
        sys.exit(1)
    print(f"\nProject: {project_id}")
    print(f"Region:  {REGION}")
    print(f"Service: {SERVICE_NAME}")

    # 2. Load env vars
    if not ENV_FILE.exists():
        print(f"\nERROR: {ENV_FILE} not found")
        sys.exit(1)

    env = dotenv_values(ENV_FILE)

    # Check required vars
    required = ["GEMINI_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "MY_WHATSAPP_NUMBER"]
    missing = [k for k in required if not env.get(k) or "your_" in env.get(k, "")]
    if missing:
        print(f"\nERROR: Missing required .env values: {missing}")
        print(f"Please fill in backend/.env before deploying.")
        sys.exit(1)

    # 3. Enable required APIs
    print("\nEnabling required Google APIs...")
    run(["gcloud", "services", "enable",
         "run.googleapis.com",
         "cloudbuild.googleapis.com",
         "--project", project_id])

    # 4. Build env var string for Cloud Run
    env_vars = ",".join([
        f"GEMINI_API_KEY={env['GEMINI_API_KEY']}",
        f"TWILIO_ACCOUNT_SID={env['TWILIO_ACCOUNT_SID']}",
        f"TWILIO_AUTH_TOKEN={env['TWILIO_AUTH_TOKEN']}",
        f"TWILIO_WHATSAPP_NUMBER={env.get('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')}",
        f"MY_WHATSAPP_NUMBER={env['MY_WHATSAPP_NUMBER']}",
        f"DATABASE_URL={env.get('DATABASE_URL', '')}",
        "APP_ENV=production",
        f"MORNING_BRIEF_HOUR={env.get('MORNING_BRIEF_HOUR', '7')}",
        f"MORNING_BRIEF_MINUTE={env.get('MORNING_BRIEF_MINUTE', '0')}",
        f"NIGHT_SUMMARY_HOUR={env.get('NIGHT_SUMMARY_HOUR', '22')}",
        f"NIGHT_SUMMARY_MINUTE={env.get('NIGHT_SUMMARY_MINUTE', '0')}",
    ])

    # 5. Deploy to Cloud Run
    print(f"\nDeploying to Cloud Run ({REGION})...")
    run([
        "gcloud", "run", "deploy", SERVICE_NAME,
        "--source", str(Path(__file__).parent / "backend"),
        "--region", REGION,
        "--platform", "managed",
        "--allow-unauthenticated",   # Webhook must be publicly accessible
        "--set-env-vars", env_vars,
        "--memory", "512Mi",
        "--cpu", "1",
        "--min-instances", "1",      # Keep 1 always warm (for scheduler)
        "--max-instances", "3",
        "--timeout", "60",
        "--project", project_id,
    ])

    # 6. Get the deployed URL
    result = subprocess.run([
        "gcloud", "run", "services", "describe", SERVICE_NAME,
        "--region", REGION,
        "--format", "value(status.url)",
        "--project", project_id,
    ], capture_output=True, text=True)
    service_url = result.stdout.strip()

    print("\n" + "=" * 60)
    print("  FRIDAY deployed successfully!")
    print("=" * 60)
    print(f"\n  Service URL: {service_url}")
    print(f"\n  WhatsApp Webhook URL:")
    print(f"  {service_url}/webhook")
    print(f"\n  Next: Register this webhook URL in the Twilio Sandbox Configuration")
    print("\n  API Docs (local): http://localhost:8000/docs")


if __name__ == "__main__":
    main()
