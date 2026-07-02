"""
FRIDAY -- Reminder Service

Handles creation, updating, and completion of events and reminder plans.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Event, ReminderPlan, ReminderHistory, ConversationMemory,
    EventStatus, ReminderStatus, EventCategory, EventPriority
)
from ai.planner import plan_reminders
from time_utils import now_ist, parse_iso_datetime

logger = logging.getLogger(__name__)


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


# Words that carry discriminating meaning for duplicate detection
_STOP_SHORT = {"the", "for", "and", "but", "not", "are", "was", "has", "had"}


def _normalise_title(value: str | None) -> set[str]:
    """Extract meaningful words (>3 chars) for overlap scoring."""
    words = re.findall(r"[a-z0-9]+", (value or "").lower())
    return {word for word in words if len(word) > 3 and word not in _STOP_SHORT}


def _safe_category(value: str | None) -> str:
    return value if value in {item.value for item in EventCategory} else EventCategory.MISCELLANEOUS.value


def _safe_priority(value: str | None) -> str:
    return value if value in {item.value for item in EventPriority} else EventPriority.MEDIUM.value


async def _find_duplicate_event(
    db: AsyncSession,
    user_phone: str,
    title: str,
    event_datetime: datetime | None,
    deadline: datetime | None,
) -> Optional[Event]:
    """
    Find an existing event that matches the title + time closely enough
    to be considered a duplicate update rather than a new event.
    - Requires >=2 meaningful word overlap (>3 chars)
    - Time within 6h window
    """
    ref = event_datetime or deadline
    title_words = _normalise_title(title)
    if not title_words:
        return None

    result = await db.execute(
        select(Event)
        .where(Event.status == EventStatus.ACTIVE, Event.user_phone == user_phone)
        .order_by(Event.created_at.desc())
        .limit(50)
    )
    for event in result.scalars().all():
        overlap = title_words & _normalise_title(event.title)
        if len(overlap) < 2:
            continue
        existing_ref = event.event_datetime or event.deadline
        if ref and existing_ref and abs(existing_ref - ref) <= timedelta(hours=6):
            return event
        if not ref or not existing_ref:
            return event
    return None


async def create_event_from_ai(
    db: AsyncSession,
    ai_result: dict,
    source_message: str,
    user_phone: str,
) -> Optional[Event]:
    """Create an Event + ReminderPlans from the AI extraction result."""
    event_data = ai_result.get("event") or {}
    if not event_data:
        return None

    category = _safe_category(event_data.get("category"))
    priority = _safe_priority(event_data.get("priority"))
    event_datetime = parse_iso_datetime(event_data.get("event_datetime"))
    deadline = parse_iso_datetime(event_data.get("deadline"))
    title = (event_data.get("title") or "Untitled").strip()[:500]

    duplicate = await _find_duplicate_event(db, user_phone, title, event_datetime, deadline)
    if duplicate:
        logger.info("Updating duplicate-looking event '%s' instead of creating", duplicate.title)
        return await update_event_from_ai(db, duplicate, ai_result, source_message)

    event = Event(
        title=title,
        description=event_data.get("description"),
        category=category,
        priority=priority,
        event_datetime=event_datetime,
        deadline=deadline,
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
    await db.flush()

    reminder_list = plan_reminders(
        event_datetime=event.event_datetime,
        deadline=event.deadline,
        category=event.category,
        priority=event.priority,
        title=event.title,
        venue=event.venue,
    )

    for r in reminder_list:
        db.add(ReminderPlan(
            event_id=event.id,
            scheduled_at=r["scheduled_at"],
            reminder_type=r["reminder_type"],
            message_template=r["message_template"],
            status=ReminderStatus.PENDING,
        ))

    await db.commit()
    await db.refresh(event)

    logger.info("Created event '%s' with %d reminders", event.title, len(reminder_list))
    return event


async def update_event_from_ai(
    db: AsyncSession,
    event: Event,
    ai_result: dict,
    source_message: str | None = None,
) -> Event:
    """Update an active event and rebuild pending reminders."""
    event_data = ai_result.get("event") or {}
    if not event_data:
        return event

    if event_data.get("title") and _enum_value(event.title) in {"untitled", "reminder"}:
        event.title = event_data["title"][:500]
    if event_data.get("description"):
        event.description = event_data["description"]
    if event_data.get("category"):
        event.category = _safe_category(event_data.get("category"))
    if event_data.get("priority"):
        event.priority = _safe_priority(event_data.get("priority"))

    event_datetime = parse_iso_datetime(event_data.get("event_datetime"))
    deadline = parse_iso_datetime(event_data.get("deadline"))
    if event_datetime:
        event.event_datetime = event_datetime
        event.deadline = None
    if deadline:
        event.deadline = deadline
        event.event_datetime = None

    for field in ("venue", "link", "contact", "estimated_effort_hours", "recurrence_rule"):
        value = event_data.get(field)
        if value not in (None, ""):
            setattr(event, field, value)
    if "is_recurring" in event_data:
        event.is_recurring = bool(event_data.get("is_recurring"))
    if source_message:
        event.source_message = source_message
    event.ai_confidence = ai_result.get("confidence", event.ai_confidence)
    event.updated_at = now_ist()

    await db.execute(
        delete(ReminderPlan).where(
            ReminderPlan.event_id == event.id,
            ReminderPlan.status == ReminderStatus.PENDING,
        )
    )
    await db.flush()

    reminder_list = plan_reminders(
        event_datetime=event.event_datetime,
        deadline=event.deadline,
        category=_enum_value(event.category),
        priority=_enum_value(event.priority),
        title=event.title,
        venue=event.venue,
    )
    for r in reminder_list:
        db.add(ReminderPlan(
            event_id=event.id,
            scheduled_at=r["scheduled_at"],
            reminder_type=r["reminder_type"],
            message_template=r["message_template"],
            status=ReminderStatus.PENDING,
        ))

    await db.commit()
    await db.refresh(event)
    logger.info("Updated event '%s' with %d pending reminders", event.title, len(reminder_list))
    return event


async def mark_event_complete(
    db: AsyncSession,
    event: Event,
) -> None:
    """Mark a single event as completed and cancel its pending reminders."""
    event.status = EventStatus.COMPLETED
    event.completed_at = now_ist()

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
    logger.info("Event '%s' marked complete. %d reminders cancelled.", event.title, len(pending))


async def bulk_complete_events(
    db: AsyncSession,
    user_phone: str,
    scope: str,
) -> list[str]:
    """
    Mark a group of events as completed based on scope.

    scope values:
      "overdue"                  - all active events whose datetime is in the past
      "yesterday"                - all active events from yesterday
      "today"                    - all active events due today
      "all_completed"            - everything past its time (user says all done)
      "specific_day:YYYY-MM-DD"  - all active events on that specific date

    Returns list of completed event titles.
    """
    now = now_ist()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(Event).where(
            Event.status == EventStatus.ACTIVE,
            Event.user_phone == user_phone,
        )
    )
    all_events = result.scalars().all()

    def _ref(e: Event):
        return e.event_datetime or e.deadline

    if scope == "overdue":
        targets = [e for e in all_events if _ref(e) and _ref(e) < now]
    elif scope == "yesterday":
        yesterday_start = today_start - timedelta(days=1)
        targets = [e for e in all_events if _ref(e) and yesterday_start <= _ref(e) < today_start]
    elif scope == "today":
        tomorrow_start = today_start + timedelta(days=1)
        targets = [e for e in all_events if _ref(e) and today_start <= _ref(e) < tomorrow_start]
    elif scope == "all_completed":
        targets = [e for e in all_events if not _ref(e) or _ref(e) <= now]
    elif scope and scope.startswith("specific_day:"):
        try:
            day_str = scope.split(":", 1)[1]
            specific_day = datetime.strptime(day_str, "%Y-%m-%d")
            specific_end = specific_day + timedelta(days=1)
            targets = [e for e in all_events if _ref(e) and specific_day <= _ref(e) < specific_end]
        except Exception:
            targets = []
    else:
        # Default: treat unknown scope same as overdue
        targets = [e for e in all_events if _ref(e) and _ref(e) < now]

    completed_titles = []
    for event in targets:
        event.status = EventStatus.COMPLETED
        event.completed_at = now
        completed_titles.append(event.title)

        pending_result = await db.execute(
            select(ReminderPlan).where(
                ReminderPlan.event_id == event.id,
                ReminderPlan.status == ReminderStatus.PENDING,
            )
        )
        for plan in pending_result.scalars().all():
            plan.status = ReminderStatus.SKIPPED

    if completed_titles:
        await db.commit()
        logger.info("Bulk completed %d events (scope=%s) for %s", len(completed_titles), scope, user_phone[:8])

    return completed_titles


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
        return events[0]

    hint_lower = hint.lower()
    for event in events:
        if event.title and any(
            word in event.title.lower()
            for word in hint_lower.split()
            if len(word) > 3
        ):
            return event

    return events[0]


async def save_conversation_turn(
    db: AsyncSession,
    role: str,
    content: str,
    linked_event_id: Optional[str] = None,
    user_phone: Optional[str] = None,
) -> None:
    """Append a message to conversation memory."""
    mem = ConversationMemory(
        role=role,
        content=content,
        linked_event_id=linked_event_id,
        user_phone=user_phone,
    )
    db.add(mem)
    await db.commit()


async def get_conversation_history(
    db: AsyncSession,
    user_phone: str,
    limit: int = 10,
) -> list[dict]:
    """Fetch recent conversation history for AI context."""
    result = await db.execute(
        select(ConversationMemory)
        .where(ConversationMemory.user_phone == user_phone)
        .order_by(ConversationMemory.timestamp.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]
