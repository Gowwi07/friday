"""
FRIDAY — WhatsApp Business Cloud API Webhook

Meta sends two types of requests to this endpoint:
1. GET  /webhook  → Webhook verification (one-time setup)
2. POST /webhook  → Incoming messages

Meta Cloud API message format is very different from Twilio's.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request, Query, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from database.database import get_db
from database.models import IncomingMessage, EventStatus, MessageType
from ai.agent import get_agent
from services.reminder import (
    create_event_from_ai,
    mark_event_complete,
    find_best_matching_event,
    save_conversation_turn,
    get_conversation_history,
)
from services.whatsapp import send_whatsapp_message
from services.summary import generate_task_list
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


# ─── Webhook Verification (GET) ───────────────────────────────────────────────
@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta calls this once when you register the webhook.
    It verifies that the URL is controlled by you via the verify_token.
    """
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("✅ Meta WhatsApp webhook verified!")
        return int(hub_challenge)  # Must return the challenge as plain integer/text
    else:
        logger.warning(f"❌ Meta webhook verification failed. Token mismatch.")
        raise HTTPException(status_code=403, detail="Verification failed")


# ─── Incoming Messages (POST) ─────────────────────────────────────────────────
@router.post("/webhook")
async def receive_message(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Meta posts all incoming WhatsApp events here.
    We extract text messages and run the AI pipeline.
    """
    payload = await request.json()

    # Meta wraps everything in entry[].changes[]
    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
    except (IndexError, AttributeError):
        return {"status": "ok"}  # Not a message event (e.g. status update)

    if not messages:
        return {"status": "ok"}  # Could be delivery/read receipts

    # Process each message
    for msg in messages:
        msg_type = msg.get("type", "text")
        from_number = msg.get("from", "")  # e.g. "919876543210"
        msg_id = msg.get("id", "")
        timestamp = int(msg.get("timestamp", 0))

        # Get contact name
        from_name = from_number
        if contacts:
            from_name = contacts[0].get("profile", {}).get("name", from_number)

        # Extract text body
        body = ""
        if msg_type == "text":
            body = msg.get("text", {}).get("body", "").strip()
        elif msg_type == "image":
            # Image with optional caption
            body = msg.get("image", {}).get("caption", "[Image sent]")
        elif msg_type == "document":
            body = msg.get("document", {}).get("filename", "[Document sent]")
        elif msg_type == "audio":
            body = "[Voice note sent]"
        else:
            body = f"[{msg_type} message]"

        if not body:
            continue

        logger.info(f"\n📩 From {from_name} ({from_number}): {body[:80]}")

        # Process in background so we return 200 quickly (Meta requires fast response)
        background_tasks.add_task(
            _process_message,
            from_number=from_number,
            from_name=from_name,
            body=body,
            msg_id=msg_id,
            msg_type=msg_type,
            timestamp=timestamp,
        )

    return {"status": "ok"}


async def _process_message(
    from_number: str,
    from_name: str,
    body: str,
    msg_id: str,
    msg_type: str,
    timestamp: int,
):
    """
    Full AI pipeline for a single incoming message from Meta.
    """
    from database.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            # ── Log raw message ────────────────────────────────────────────
            raw_msg = IncomingMessage(
                whatsapp_msg_id=msg_id,
                from_number=from_number,
                from_name=from_name,
                body=body,
                message_type=MessageType.CHAT if msg_type == "text" else MessageType.IMAGE,
                is_forwarded=False,
                has_media=(msg_type != "text"),
                timestamp=datetime.fromtimestamp(timestamp) if timestamp else None,
            )
            db.add(raw_msg)
            await db.flush()

            # ── Quick keyword shortcuts (no AI needed) ─────────────────────
            search_keywords = [
                "what's pending", "whats pending", "what is pending",
                "what's on my plate", "show tasks", "pending tasks",
                "show all", "task list", "my tasks",
            ]
            if any(k in body.lower() for k in search_keywords):
                task_list = await generate_task_list(db)
                await send_whatsapp_message(from_number, task_list)
                await save_conversation_turn(db, "user", body)
                await save_conversation_turn(db, "assistant", task_list)
                await db.commit()
                return

            # ── Get conversation history ────────────────────────────────────
            history = await get_conversation_history(db, limit=10)

            # ── Run AI Agent ───────────────────────────────────────────────
            agent = get_agent()
            ai_result = await agent.process_message(
                message_body=body,
                conversation_history=history,
                is_forwarded=False,
                current_datetime=datetime.now(),
            )

            intent = ai_result.get("intent", "ignore")
            reply = ai_result.get("reply_to_user", "")
            confidence = ai_result.get("confidence", 0.0)

            logger.info(f"AI → intent={intent} confidence={confidence:.2f}")

            linked_event_id = None

            # ── Handle Intent ───────────────────────────────────────────────
            if intent == "create_event" and confidence >= 0.65:
                event = await create_event_from_ai(
                    db=db,
                    ai_result=ai_result,
                    source_message=body,
                    user_phone=from_number,
                )
                if event:
                    linked_event_id = event.id
                    raw_msg.intent = "create_event"
                    raw_msg.linked_event_id = event.id
                    raw_msg.processed = True

            elif intent == "complete_task":
                hint = ai_result.get("matched_event_hint")
                event = await find_best_matching_event(db, hint, from_number)
                if event:
                    await mark_event_complete(db, event)
                    linked_event_id = event.id
                    raw_msg.intent = "complete_task"
                    raw_msg.linked_event_id = event.id
                    raw_msg.processed = True
                    if not reply:
                        reply = f"✅ Got it! *{event.title}* marked as completed."

            elif intent == "search":
                task_list = await generate_task_list(db)
                reply = task_list
                raw_msg.intent = "search"
                raw_msg.processed = True

            else:
                raw_msg.intent = intent

            # ── Save conversation ───────────────────────────────────────────
            await save_conversation_turn(db, "user", body, linked_event_id)
            if reply:
                await save_conversation_turn(db, "assistant", reply, linked_event_id)

            await db.commit()

            # ── Send reply ─────────────────────────────────────────────────
            if reply:
                await send_whatsapp_message(from_number, reply)

        except Exception as e:
            logger.error(f"Error processing message from {from_number}: {e}", exc_info=True)
            await db.rollback()
