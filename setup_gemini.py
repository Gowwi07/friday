"""
FRIDAY - Gemini API Key Setup Helper

Run this script to get a Gemini API key and configure your .env file.
Usage: python setup_gemini.py
"""

import subprocess
import sys
import os
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    env_path = Path(__file__).parent / "backend" / ".env"

    print("=" * 60)
    print("  FRIDAY - Gemini API Setup")
    print("=" * 60)
    print()

    # Try to get key via gcloud (Application Default Credentials)
    print("1. Checking gcloud authentication...")
    try:
        result = subprocess.run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print("   OK - gcloud authenticated!\n")
        else:
            print("   NOTE: gcloud not authenticated (that's fine)\n")
    except FileNotFoundError:
        print("   NOTE: gcloud not in PATH (that's fine)\n")
    except Exception as e:
        print(f"   NOTE: gcloud check skipped ({e})\n")

    print("2. Get your FREE Gemini API key:")
    print("   → Open: https://aistudio.google.com/app/apikey")
    print("   → Sign in with your Google account")
    print("   → Click 'Create API Key'")
    print("   → Copy the key\n")

    api_key = input("Paste your Gemini API key here: ").strip()

    if not api_key:
        print("❌ No key entered. Exiting.")
        sys.exit(1)

    print("\n3. Enter your WhatsApp number (with country code, no spaces or dashes):")
    print("   Example: 919876543210  (for +91 98765 43210)")
    phone = input("WhatsApp number: ").strip()
    whatsapp_number = f"{phone}@c.us" if phone else ""

    # Update .env
    if env_path.exists():
        content = env_path.read_text()
        content = content.replace("your_gemini_api_key_here", api_key)
        if whatsapp_number:
            content = content.replace("91XXXXXXXXXX@c.us", whatsapp_number)
        env_path.write_text(content)
        print(f"\n✅ Updated: {env_path}")
    else:
        print(f"\n❌ .env file not found at {env_path}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  Setup complete! Next steps:")
    print("=" * 60)
    print()
    print("  Terminal 1 — Start backend:")
    print("    cd backend")
    print("    .\\venv\\Scripts\\activate")
    print("    uvicorn main:app --reload --port 8000")
    print()
    print("  Terminal 2 — Start WhatsApp bridge:")
    print("    cd bridge")
    print("    npm start")
    print()
    print("  Then scan the QR code with your WhatsApp!")
    print()


if __name__ == "__main__":
    main()
