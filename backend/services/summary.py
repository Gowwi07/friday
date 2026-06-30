"""
FRIDAY — Daily Summary Service
Generates personalized morning brief and night summary messages per user.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Event, EventStatus, EventPriority

logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟡",
}


async def generate_morning_brief(db: AsyncSession, user_phone: str) -> str:
    """
    Generate a morning brief showing today's tasks and upcoming events for a specific user.
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59)
    tomorrow_end = today_end + timedelta(days=1)

    # Get active events for this user
    result = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.ACTIVE,
            Event.user_phone == user_phone
        )
        .order_by(Event.event_datetime.asc().nullslast(), Event.deadline.asc().nullslast())
    )
    events = result.scalars().all()

    today_events = []
    tomorrow_events = []
    upcoming_events = []
    overdue_events = []

    for evt in events:
        ref = evt.event_datetime or evt.deadline
        if not ref:
            continue
        if ref < now:
            overdue_events.append(evt)
        elif today_start <= ref <= today_end:
            today_events.append(evt)
        elif today_end < ref <= tomorrow_end:
            tomorrow_events.append(evt)
        elif ref <= now + timedelta(days=7):
            upcoming_events.append(evt)

    lines = [f"☀️ *Good morning!*\n_{now.strftime('%A, %B %d')}_\n"]

    if not any([today_events, tomorrow_events, overdue_events]):
        lines.append("✨ Your schedule is clear today. Have a great day!")
        return "\n".join(lines)

    if overdue_events:
        lines.append("🚨 *Overdue — Needs Attention*")
        for e in overdue_events[:3]:
            emoji = PRIORITY_EMOJI.get(e.priority, "⚪")
            lines.append(f"  {emoji} {e.title}")
        lines.append("")

    if today_events:
        lines.append("📅 *Today*")
        for e in today_events:
            emoji = PRIORITY_EMOJI.get(e.priority, "⚪")
            time_str = e.event_datetime.strftime("%I:%M %p") if e.event_datetime else "Deadline today"
            lines.append(f"  {emoji} {e.title} — {time_str}")
        lines.append("")

    if tomorrow_events:
        lines.append("📆 *Tomorrow*")
        for e in tomorrow_events:
            emoji = PRIORITY_EMOJI.get(e.priority, "⚪")
            time_str = e.event_datetime.strftime("%I:%M %p") if e.event_datetime else ""
            lines.append(f"  {emoji} {e.title} {time_str}".strip())
        lines.append("")

    if upcoming_events:
        lines.append("🗓️ *This Week*")
        for e in upcoming_events[:5]:
            ref = e.event_datetime or e.deadline
            lines.append(f"  • {e.title} ({ref.strftime('%a %b %d')})")
        lines.append("")

    lines.append("Reply *What's pending?* to see all tasks.")
    return "\n".join(lines)


async def generate_night_summary(db: AsyncSession, user_phone: str) -> str:
    """
    Generate an end-of-day summary for a specific user.
    """
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Completed today
    result = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.COMPLETED,
            Event.completed_at >= today_start,
            Event.user_phone == user_phone
        )
    )
    completed = result.scalars().all()

    # Still active + past
    result2 = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.ACTIVE,
            Event.user_phone == user_phone
        )
        .order_by(Event.event_datetime.asc().nullslast())
    )
    active = result2.scalars().all()

    # Tomorrow's events
    tomorrow_start = today_start + timedelta(days=1)
    tomorrow_end = tomorrow_start + timedelta(days=1)
    tomorrow_events = [
        e for e in active
        if (e.event_datetime or e.deadline) and
        tomorrow_start <= (e.event_datetime or e.deadline) < tomorrow_end
    ]

    lines = [f"🌙 *End of Day Summary*\n_{now.strftime('%A, %B %d')}_\n"]

    if completed:
        lines.append("✅ *Completed Today*")
        for e in completed:
            lines.append(f"  ✅ {e.title}")
        lines.append("")

    pending_today = [
        e for e in active
        if (e.event_datetime or e.deadline) and
        (e.event_datetime or e.deadline) < now + timedelta(hours=2)
    ]
    if pending_today:
        lines.append("❌ *Incomplete / Overdue*")
        for e in pending_today:
            lines.append(f"  ❌ {e.title}")
        lines.append("")

    if tomorrow_events:
        first = tomorrow_events[0]
        ref = first.event_datetime or first.deadline
        lines.append(f"📅 *Tomorrow's first task*\n  {first.title} — {ref.strftime('%I:%M %p')}")
    else:
        lines.append("✨ No tasks scheduled for tomorrow.")

    lines.append("\nGet some rest! 😴")
    return "\n".join(lines)


async def generate_task_list(db: AsyncSession, user_phone: str) -> str:
    """
    Generate a response to 'What's pending?' or 'What's on my plate?' for a specific user.
    """
    now = datetime.now()

    result = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.ACTIVE,
            Event.user_phone == user_phone
        )
        .order_by(Event.event_datetime.asc().nullslast(), Event.deadline.asc().nullslast())
    )
    events = result.scalars().all()

    if not events:
        return "🎉 Nothing pending! You're all caught up."

    urgent = []
    today = []
    this_week = []
    later = []

    for e in events:
        ref = e.event_datetime or e.deadline
        if not ref:
            later.append(e)
            continue
        days = (ref - now).days
        if days < 0:
            urgent.append(e)
        elif days == 0:
            today.append(e)
        elif days <= 7:
            this_week.append(e)
        else:
            later.append(e)

    lines = ["📋 *Your Active Tasks*\n"]

    def fmt(e):
        ref = e.event_datetime or e.deadline
        emoji = PRIORITY_EMOJI.get(e.priority, "⚪")
        date_str = ref.strftime("%-d %b, %I:%M %p") if ref else ""
        return f"  {emoji} {e.title}" + (f" — {date_str}" if date_str else "")

    if urgent:
        lines.append("🚨 *Overdue*")
        lines.extend(fmt(e) for e in urgent)
        lines.append("")
    if today:
        lines.append("🔥 *Due Today*")
        lines.extend(fmt(e) for e in today)
        lines.append("")
    if this_week:
        lines.append("📅 *This Week*")
        lines.extend(fmt(e) for e in this_week)
        lines.append("")
    if later:
        lines.append("🗓️ *Later*")
        lines.extend(fmt(e) for e in later[:5])

    return "\n".join(lines)
