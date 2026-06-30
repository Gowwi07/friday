"""
FRIDAY — WhatsApp Business Cloud API Sender

Sends messages via Meta's official WhatsApp Cloud API.
No local bridge needed — works from anywhere (Cloud Run, etc.).

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""

import httpx
import logging
from typing import Optional

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Meta Graph API base
GRAPH_API_URL = "https://graph.facebook.com/v20.0"


def _phone_to_wa_id(phone: str) -> str:
    """
    Normalize phone number to WhatsApp format.
    Accepts: '919876543210', '+919876543210', '919876543210@c.us'
    Returns: '919876543210'
    """
    return phone.replace("+", "").replace("@c.us", "").replace(" ", "").replace("whatsapp:", "").strip()


async def send_whatsapp_message(to: str, message: str) -> bool:
    """
    Send a WhatsApp text message via Meta Cloud API.

    Args:
        to: Recipient phone number (any format)
        message: Text to send (supports WhatsApp markdown: *bold*, _italic_)

    Returns:
        True if sent successfully, False otherwise.
    """
    if not to:
        to = settings.my_whatsapp_number

    if not to:
        logger.error("No recipient number. Set MY_WHATSAPP_NUMBER in .env")
        return False

    if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
        logger.error("WhatsApp API not configured. Set WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN in .env")
        return False

    wa_id = _phone_to_wa_id(to)
    url = f"{GRAPH_API_URL}/{settings.whatsapp_phone_number_id}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message,
        },
    }

    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            logger.info(f"✅ Sent Meta WhatsApp to {wa_id[:8]}...: {message[:60]}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Meta WhatsApp API error {e.response.status_code}: {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send Meta WhatsApp message: {e}")
        return False


async def send_to_me(message: str) -> bool:
    """Shortcut: send a message to the configured personal number."""
    return await send_whatsapp_message(settings.my_whatsapp_number, message)
