"""
FRIDAY — Twilio WhatsApp API Sender

Sends messages via Twilio's API to WhatsApp.
Uses standard HTTP POST with Basic Auth.
"""

import httpx
import logging
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _normalize_phone(phone: str) -> str:
    """
    Ensure the number has the 'whatsapp:' prefix.
    e.g., '919876543210' -> 'whatsapp:+919876543210'
          'whatsapp:919876543210' -> 'whatsapp:+919876543210'
          '+919876543210' -> 'whatsapp:+919876543210'
    """
    cleaned = phone.strip()
    if cleaned.startswith("whatsapp:"):
        num_part = cleaned.split(":", 1)[1]
        if not num_part.startswith("+"):
            return f"whatsapp:+{num_part}"
        return cleaned
    
    if not cleaned.startswith("+"):
        return f"whatsapp:+{cleaned}"
    
    return f"whatsapp:{cleaned}"


async def send_whatsapp_message(to: str, message: str) -> bool:
    """
    Send a WhatsApp message via Twilio.

    Args:
        to: Recipient phone number (e.g. 'whatsapp:+919876543210')
        message: The message body to send.
    """
    if not to:
        to = settings.my_whatsapp_number

    if not to:
        logger.error("No recipient number configured. Set MY_WHATSAPP_NUMBER in .env")
        return False

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.error("Twilio credentials not configured in .env")
        return False

    to_formatted = _normalize_phone(to)
    from_formatted = _normalize_phone(settings.twilio_whatsapp_number)

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"

    # Twilio expects urlencoded form data
    payload = {
        "To": to_formatted,
        "From": from_formatted,
        "Body": message,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                data=payload,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
            response.raise_for_status()
            logger.info(f"✅ Sent Twilio WhatsApp to {to_formatted}: {message[:60]}...")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Twilio API error {e.response.status_code}: {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send Twilio WhatsApp message: {e}")
        return False


async def send_to_me(message: str) -> bool:
    """Shortcut to send a message to the configured personal number."""
    return await send_whatsapp_message(settings.my_whatsapp_number, message)
