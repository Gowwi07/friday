"""
FRIDAY -- WhatsApp Business Cloud API Webhook

Meta sends two types of requests to this endpoint:
  GET  /webhook  -> Webhook verification (one-time setup)
  POST /webhook  -> Incoming messages
"""

import logging
from datetime import timedelta

from fastapi import APIRouter, Request, Query, HTTPException, BackgroundTasks
from sqlalchemy import select

from database.models import IncomingMessage, EventStatus, MessageType
from ai.agent import get_agent
from ai.rules import try_parse_local_intent
from services.reminder import (
    create_event_from_ai,
    update_event_from_ai,
    mark_event_complete,
    bulk_complete_events,
    find_best_matching_event,
    save_conversation_turn,
    get_conversation_history,
)
from services.whatsapp import send_whatsapp_message
from services.summary import generate_task_list, generate_weekly_plan
from config import get_settings
from time_utils import from_unix_timestamp, now_ist

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta calls this once when you register the webhook."""
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        logger.info("Meta WhatsApp webhook verified!")
        return int(hub_challenge)
    logger.warning("Meta webhook verification failed.")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """Meta posts all incoming WhatsApp events here."""
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be an object")

    try:
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
    except (IndexError, TypeError, AttributeError):
        messages, contacts = [], []

    # Optional whatsapp-web.js bridge uses a compact flat payload
    if not messages and payload.get("message_id") and payload.get("from"):
        bridge_type = payload.get("type", "chat")
        messages = [{
            "id": payload.get("message_id"),
            "from": payload.get("from"),
            "timestamp": payload.get("timestamp", 0),
            "type": "text" if bridge_type == "chat" else bridge_type,
            "text": {"body": payload.get("body", "")},
            "context": payload.get("context") or {},
            "_body": payload.get("body", ""),
            "_is_forwarded": bool(payload.get("is_forwarded")),
        }]
        contacts = [{"wa_id": payload.get("from"), "profile": {"name": payload.get("from_name")}}]

    if not messages:
        return {"status": "ok"}

    for msg in messages:
        msg_type = msg.get("type", "text")
        from_number = msg.get("from", "")
        msg_id = msg.get("id", "")
        try:
            timestamp = int(msg.get("timestamp", 0))
        except (TypeError, ValueError):
            timestamp = 0

        from_name = from_number
        if contacts:
            from_name = contacts[0].get("profile", {}).get("name", from_number)

        body = ""
        if msg_type == "text":
            body = msg.get("text", {}).get("body", "").strip()
        elif msg_type == "image":
            body = msg.get("image", {}).get("caption", "[Image sent]")
        elif msg_type == "document":
            body = msg.get("document", {}).get("filename", "[Document sent]")
        elif msg_type == "audio":
            body = "[Voice note sent]"
        else:
            body = f"[{msg_type} message]"

        body = (msg.get("_body") or body or "").strip()
        if not body:
            continue

        logger.info("Incoming from %s: %s", from_number[:8], body[:80])

        background_tasks.add_task(
            _process_message,
            from_number=from_number,
            from_name=from_name,
            body=body,
            msg_id=msg_id,
            msg_type=msg_type,
            timestamp=timestamp,
            quoted_msg_id=(msg.get("context") or {}).get("id"),
            is_forwarded=bool(msg.get("_is_forwarded", False)),
        )

    return {"status": "ok"}


async def _process_message(
    from_number: str,
    from_name: str,
    body: str,
    msg_id: str,
    msg_type: str,
    timestamp: int,
    quoted_msg_id=None,
    is_forwarded: bool = False,
):
    """
    Full AI pipeline:
      1. Deduplicate (Meta retries webhooks)
      2. Log raw message to DB
      3. Fast-path keyword commands (task list / weekly plan / snooze)
      4. Gemini-first for all context-dependent messages (full conversation history)
         Local rules only as fallback when Gemini unavailable or low-confidence
      5. Execute intent (create / update / complete / search)
      6. Send reply
    """
    from database.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            # 1. Deduplicate
            if msg_id:
                existing = await db.scalar(
                    select(IncomingMessage.id).where(IncomingMessage.whatsapp_msg_id == msg_id)
                )
                if existing:
                    logger.info("Ignoring duplicate message %s", msg_id)
                    return

            # 2. Log raw message
            message_type = {
                "text": MessageType.CHAT,
                "chat": MessageType.CHAT,
                "image": MessageType.IMAGE,
                "document": MessageType.DOCUMENT,
                "audio": MessageType.AUDIO,
                "video": MessageType.VIDEO,
                "sticker": MessageType.STICKER,
            }.get(msg_type, MessageType.OTHER)

            raw_msg = IncomingMessage(
                whatsapp_msg_id=msg_id,
                from_number=from_number,
                from_name=from_name,
                body=body,
                message_type=message_type,
                is_forwarded=is_forwarded,
                has_media=(msg_type != "text"),
                timestamp=from_unix_timestamp(timestamp) if timestamp else None,
            )
            db.add(raw_msg)
            await db.flush()

            # 3. Fast-path keyword commands (no AI needed)
            body_lower = body.lower().strip()

            trivial = {"ok", "okay", "thanks", "thank you", "noted", "k", "haha", "lol", "nice", "cool"}
            if body_lower in trivial:
                await db.commit()
                return

            search_keywords = [
                "what's pending", "whats pending", "what is pending",
                "what's on my plate", "show tasks", "pending tasks",
                "show all", "task list", "my tasks", "upcoming tasks",
                "upcoming task", "what's upcoming", "whats upcoming",
                "what is upcoming", "what are my tasks",
            ]
            weekly_keywords = [
                "weekly plan", "this week", "show week", "week plan",
                "week schedule", "my week", "show weekly",
            ]
            snooze_keywords = ["snooze", "remind me later", "not now"]

            if any(k in body_lower for k in search_keywords):
                task_list = await generate_task_list(db, from_number)
                await send_whatsapp_message(from_number, task_list)
                await save_conversation_turn(db, "user", body, user_phone=from_number)
                await save_conversation_turn(db, "assistant", task_list, user_phone=from_number)
                await db.commit()
                return

            if any(k in body_lower for k in weekly_keywords):
                weekly = await generate_weekly_plan(db, from_number)
                await send_whatsapp_message(from_number, weekly)
                await save_conversation_turn(db, "user", body, user_phone=from_number)
                await save_conversation_turn(db, "assistant", weekly, user_phone=from_number)
                await db.commit()
                return

            if any(k in body_lower for k in snooze_keywords):
                snooze_event = await find_best_matching_event(db, None, from_number)
                if snooze_event:
                    snooze_at = now_ist() + timedelta(minutes=30)
                    from database.models import ReminderPlan, ReminderStatus
                    db.add(ReminderPlan(
                        event_id=snooze_event.id,
                        scheduled_at=snooze_at,
                        reminder_type="snooze",
                        message_template=(
                            f"Snoozed: *{snooze_event.title}*\n"
                            "Reply *Done* when complete, or *Snooze* to push again."
                        ),
                        status=ReminderStatus.PENDING,
                    ))
                    snooze_reply = f"Got it! Reminding you about *{snooze_event.title}* in 30 minutes."
                    await send_whatsapp_message(from_number, snooze_reply)
                    await save_conversation_turn(db, "user", body, user_phone=from_number)
                    await save_conversation_turn(db, "assistant", snooze_reply, user_phone=from_number)
                    await db.commit()
                return

            # 4. Gemini-first AI pipeline
            # Gemini gets full conversation history so it understands context:
            #   "that session" -> resolves from prior conversation
            #   "reschedule it to Friday" -> knows which event is "it"
            #   "actually make it 11 AM" -> correction to last-created event
            # Local rules only used when Gemini unavailable or low-confidence.
            history = await get_conversation_history(db, from_number, limit=10)

            ai_body = body
            if quoted_msg_id:
                quoted_body = await db.scalar(
                    select(IncomingMessage.body).where(
                        IncomingMessage.whatsapp_msg_id == quoted_msg_id,
                        IncomingMessage.from_number == from_number,
                    )
                )
                if quoted_body:
                    ai_body = f"Replying to earlier: {quoted_body}\nUser: {body}"

            current_time = now_ist()
            agent = get_agent()

            if agent.client:
                ai_result = await agent.process_message(
                    message_body=ai_body,
                    conversation_history=history,
                    is_forwarded=is_forwarded,
                    current_datetime=current_time,
                )
                # If Gemini is uncertain, let local rules have a try
                if (
                    ai_result.get("intent") in ("ignore", "clarify")
                    and ai_result.get("confidence", 0) < 0.5
                ):
                    local = try_parse_local_intent(ai_body, current_time)
                    if local and local.get("confidence", 0) >= 0.85:
                        logger.info("Local rule overrode low-confidence Gemini result")
                        ai_result = local
            else:
                # Fallback: no Gemini key configured
                ai_result = try_parse_local_intent(ai_body, current_time) or {
                    "intent": "ignore",
                    "confidence": 0.0,
                    "reply_to_user": "",
                    "event": None,
                }

            intent = ai_result.get("intent", "ignore")
            reply = ai_result.get("reply_to_user", "")
            confidence = ai_result.get("confidence", 0.0)

            logger.info("AI intent=%s confidence=%.2f", intent, confidence)

            linked_event_id = None

            # 5. Execute intent
            if intent == "create_event" and confidence >= 0.65:
                event = await create_event_from_ai(
                    db=db, ai_result=ai_result, source_message=body, user_phone=from_number,
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
                        reply = f"Got it! *{event.title}* marked as completed."

            elif intent == "update_event" and confidence >= 0.65:
                hint = ai_result.get("matched_event_hint")
                event = await find_best_matching_event(db, hint, from_number)
                if event:
                    await update_event_from_ai(db, event, ai_result)
                    linked_event_id = event.id
                    raw_msg.intent = "update_event"
                    raw_msg.linked_event_id = event.id
                    raw_msg.processed = True
                    if not reply:
                        reply = f"Got it! Updated *{event.title}*."
                else:
                    # No existing event found -> create instead
                    event = await create_event_from_ai(
                        db=db,
                        ai_result={**ai_result, "intent": "create_event"},
                        source_message=body,
                        user_phone=from_number,
                    )
                    if event:
                        linked_event_id = event.id
                        raw_msg.intent = "create_event"
                        raw_msg.linked_event_id = event.id
                        raw_msg.processed = True

            elif intent == "bulk_complete":
                scope = ai_result.get("bulk_scope") or "overdue"
                completed = await bulk_complete_events(db, from_number, scope)
                raw_msg.intent = "bulk_complete"
                raw_msg.processed = True
                if completed:
                    titles = "\n".join(f"  - {t}" for t in completed[:10])
                    overflow = f"\n  ...and {len(completed) - 10} more" if len(completed) > 10 else ""
                    reply = f"Done! Cleared {len(completed)} task(s):\n{titles}{overflow}"
                else:
                    reply = "No matching tasks found to clear."

            elif intent == "search":
                task_list = await generate_task_list(db, from_number)
                reply = task_list
                raw_msg.intent = "search"
                raw_msg.processed = True

            else:
                raw_msg.intent = intent

            await save_conversation_turn(db, "user", body, linked_event_id, from_number)
            if reply:
                await save_conversation_turn(db, "assistant", reply, linked_event_id, from_number)

            await db.commit()

            # 6. Send reply
            if reply:
                await send_whatsapp_message(from_number, reply)

        except Exception as e:
            logger.error("Error processing message from %s: %s", from_number, e, exc_info=True)
            await db.rollback()
