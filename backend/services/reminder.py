"""
FRIDAY — Reminder Service

Handles creation, updating, and cancellation of reminder plans.
Also handles completion detection.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Event, ReminderPlan, ReminderHistory, ConversationMemory,
    EventStatus, ReminderStatus, EventCategory, EventPriority
)
from ai.planner import plan_reminders

logger = logging.getLogger(__name__)


async def create_event_from_ai(
    db: AsyncSession,
    ai_result: dict,
    source_message: str,
    user_phone: str,
) -> Optional[Event]:
    """
    Create an Event + its ReminderPlans from the AI extraction result.
    Returns the created Event.
    """
    event_data = ai_result.get("event") or {}
    if not event_data:
        return None

    # Parse datetimes
    def parse_dt(val) -> Optional[datetime]:
        if not val:
            return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None

    event = Event(
        title=event_data.get("title", "Untitled"),
        description=event_data.get("description"),
        category=event_data.get("category", EventCategory.MISCELLANEOUS),
        priority=event_data.get("priority", EventPriority.MEDIUM),
        event_datetime=parse_dt(event_data.get("event_datetime")),
        deadline=parse_dt(event_data.get("deadline")),
        venue=event_data.get("venue"),
        link=event_data.get("link"),
        contact=event_data.get("contact"),
        estimated_effort_hours=event_data.get("estimated_effort_hours"),
        is_recurring=event_data.get("is_recurring", False),
        recurrence_rule=event_data.get("recurrence_rule"),
        status=EventStatus.ACTIVE,
        source_message=source_message,
        user_phone=user_phone,
        ai_confidence=ai_result.get("confidence", 0.8),
    )

    db.add(event)
    await db.flush()  # Get event.id

    # Generate and store reminder plans
    reminder_list = plan_reminders(
        event_datetime=event.event_datetime,
        deadline=event.deadline,
        category=event.category,
        priority=event.priority,
        title=event.title,
        venue=event.venue,
    )

    for r in reminder_list:
        plan = ReminderPlan(
            event_id=event.id,
            scheduled_at=r["scheduled_at"],
            reminder_type=r["reminder_type"],
            message_template=r["message_template"],
            status=ReminderStatus.PENDING,
        )
        db.add(plan)

    await db.commit()
    await db.refresh(event)

    logger.info(f"✅ Created event '{event.title}' with {len(reminder_list)} reminders")
    return event


async def mark_event_complete(
    db: AsyncSession,
    event: Event,
) -> None:
    """Mark an event as completed and cancel pending reminders."""
    event.status = EventStatus.COMPLETED
    event.completed_at = datetime.utcnow()

    # Cancel all pending reminders except follow-ups already sent
    result = await db.execute(
        select(ReminderPlan).where(
            ReminderPlan.event_id == event.id,
            ReminderPlan.status == ReminderStatus.PENDING,
        )
    )
    pending = result.scalars().all()
    for plan in pending:
        plan.status = ReminderStatus.SKIPPED

    await db.commit()
    logger.info(f"✅ Event '{event.title}' marked complete. {len(pending)} reminders cancelled.")


async def find_best_matching_event(
    db: AsyncSession,
    hint: Optional[str],
    user_phone: str,
) -> Optional[Event]:
    """
    Try to find the most relevant active event based on the AI's hint.
    Returns the most recently created active event if no better match found.
    """
    result = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.ACTIVE,
            Event.user_phone == user_phone,
        )
        .order_by(Event.created_at.desc())
        .limit(20)
    )
    events = result.scalars().all()

    if not events:
        return None

    if not hint:
        return events[0]  # Most recent

    # Simple keyword match
    hint_lower = hint.lower()
    for event in events:
        if event.title and any(
            word in event.title.lower()
            for word in hint_lower.split()
            if len(word) > 3
        ):
            return event

    return events[0]  # Fallback to most recent


async def save_conversation_turn(
    db: AsyncSession,
    role: str,
    content: str,
    linked_event_id: Optional[str] = None,
) -> None:
    """Append a message to conversation memory."""
    mem = ConversationMemory(
        role=role,
        content=content,
        linked_event_id=linked_event_id,
    )
    db.add(mem)
    await db.commit()


async def get_conversation_history(
    db: AsyncSession,
    limit: int = 10,
) -> list[dict]:
    """Fetch recent conversation history for AI context."""
    result = await db.execute(
        select(ConversationMemory)
        .order_by(ConversationMemory.timestamp.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    rows.reverse()  # Chronological order
    return [{"role": r.role, "content": r.content} for r in rows]
