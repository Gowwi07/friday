"""
FRIDAY — Twilio Webhook Router

Receives incoming messages from Twilio's WhatsApp Sandbox.
Twilio posts messages as Form Data (x-www-form-urlencoded).
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, BackgroundTasks
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


@router.post("/webhook")
async def receive_message(
    background_tasks: BackgroundTasks,
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    MessageSid: str = Form(...),
    NumMedia: int = Form(0),
):
    """
    Twilio Webhook endpoint. 
    Accepts x-www-form-urlencoded webhook POST.
    """
    logger.info(f"\n📩 Incoming Twilio msg from {From}: {Body[:80]}")

    # Process message in background to avoid blocking Twilio response (15s limit)
    background_tasks.add_task(
        _process_message,
        from_number=From,
        body=Body,
        msg_id=MessageSid,
        has_media=(NumMedia > 0),
    )

    return {"status": "ok"}


async def _process_message(
    from_number: str,
    body: str,
    msg_id: str,
    has_media: bool,
):
    """
    Full AI pipeline for a single incoming message from Twilio.
    """
    from database.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            # ── Log raw message ────────────────────────────────────────────
            raw_msg = IncomingMessage(
                whatsapp_msg_id=msg_id,
                from_number=from_number,
                from_name=from_number,  # Twilio only provides number
                body=body,
                message_type=MessageType.CHAT,
                is_forwarded=False,
                has_media=has_media,
                timestamp=datetime.utcnow(),
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
