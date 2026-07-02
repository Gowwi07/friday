"""
FRIDAY — Daily Summary Service

Generates personalized morning brief and night summary messages per user.
All messages are sent via WhatsApp and formatted with WhatsApp markdown.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Event, EventStatus, EventPriority, IncomingMessage
from time_utils import now_ist
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── Emoji / priority maps ────────────────────────────────────────────────────

PRIORITY_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟡",
}

# ─── Quote pools (rotate by day ordinal) ─────────────────────────────────────

MORNING_QUOTES = [
    "Today is full of possibility. Make it count.",
    "Small consistent steps beat big occasional leaps.",
    "You've handled every hard day so far. This one's no different.",
    "Plan your day before your day plans you.",
    "Discipline is choosing between what you want now and what you want most.",
    "One task at a time. That's all it takes.",
    "Start. The rest follows.",
    "Your future self is watching — make them proud today.",
    "Clarity before coffee. Plan first, then act.",
    "Great days are built by great mornings.",
    "Do it scared if you have to — just do it.",
    "Focus on progress, not perfection.",
    "The best time to start is right now.",
    "Today's effort is tomorrow's advantage.",
]

GOOD_NIGHT_QUOTES = [
    "Small steps count. Rest is part of the work.",
    "Close the day gently; tomorrow gets a fresh page.",
    "You do not need to finish everything to have moved forward.",
    "A calm night makes a sharper morning.",
    "Progress compounds quietly. Sleep well.",
    "Let the unfinished things wait outside the door tonight.",
    "You showed up today. That matters.",
    "Good planning starts with good rest.",
    "One steady day at a time.",
    "Recharge now; your future self will thank you.",
    "A rested mind is a sharper mind.",
    "Celebrate every small win — they add up.",
    "Tomorrow starts with tonight's rest.",
    "Every ending is a fresh beginning in disguise.",
]


def _morning_quote(now: datetime) -> str:
    return MORNING_QUOTES[now.toordinal() % len(MORNING_QUOTES)]


def _night_quote(now: datetime) -> str:
    return GOOD_NIGHT_QUOTES[now.toordinal() % len(GOOD_NIGHT_QUOTES)]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _priority_value(priority) -> str:
    return priority.value if hasattr(priority, "value") else str(priority)


def _date_time_label(value: datetime) -> str:
    return f"{value.day} {value.strftime('%b, %I:%M %p')}"


def _event_ref(event: Event) -> datetime | None:
    return event.event_datetime or event.deadline


def _event_line(event: Event, show_date: bool = False) -> str:
    ref = _event_ref(event)
    emoji = PRIORITY_EMOJI.get(_priority_value(event.priority), "⚪")
    if not ref:
        return f"  {emoji} {event.title}"
    today = now_ist().date()
    if show_date and ref.date() != today:
        label = ref.strftime("%a %d %b, %I:%M %p")
    else:
        label = ref.strftime("%I:%M %p") if ref.date() == today else _date_time_label(ref)
    return f"  {emoji} {event.title} — {label}"


async def _active_events(db: AsyncSession, user_phone: str) -> list[Event]:
    result = await db.execute(
        select(Event)
        .where(Event.status == EventStatus.ACTIVE, Event.user_phone == user_phone)
        .order_by(Event.event_datetime.asc().nullslast(), Event.deadline.asc().nullslast())
    )
    return list(result.scalars().all())


async def _get_display_name(db: AsyncSession, user_phone: str) -> str:
    """Return the user's display name from message history, or fall back to settings."""
    # Try settings first (fastest path)
    if settings.user_name:
        return settings.user_name
    # Query most recent from_name from messages
    result = await db.scalar(
        select(IncomingMessage.from_name)
        .where(
            IncomingMessage.from_number == user_phone,
            IncomingMessage.from_name.isnot(None),
        )
        .order_by(IncomingMessage.received_at.desc())
        .limit(1)
    )
    if result and result != user_phone:
        # Use only the first name if it's a full name
        return result.strip().split()[0]
    return ""


# ─── Morning Brief ────────────────────────────────────────────────────────────

async def generate_morning_brief(db: AsyncSession, user_phone: str) -> str:
    """
    Generate a morning brief showing today's tasks and upcoming events for a specific user.
    Always includes the Today's Plan section even when empty.
    """
    now = now_ist()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59)
    tomorrow_start = today_end + timedelta(seconds=1)
    tomorrow_end = tomorrow_start + timedelta(days=1)

    events = await _active_events(db, user_phone)
    name = await _get_display_name(db, user_phone)

    today_events = []
    tomorrow_events = []
    upcoming_events = []
    overdue_events = []

    for evt in events:
        ref = _event_ref(evt)
        if not ref:
            continue
        if ref < today_start:
            overdue_events.append(evt)
        elif today_start <= ref <= today_end:
            today_events.append(evt)
        elif tomorrow_start <= ref <= tomorrow_end:
            tomorrow_events.append(evt)
        elif ref <= now + timedelta(days=7):
            upcoming_events.append(evt)

    # ── Header ────────────────────────────────────────────────────────────────
    greeting = f"Good morning, {name}! 🌅" if name else "Good morning! 🌅"
    lines = [
        f"☀️ *{greeting}*",
        f"_{now.strftime('%A, %B %d')}_",
        f"_{_morning_quote(now)}_",
        "",
    ]

    # ── Overdue ───────────────────────────────────────────────────────────────
    if overdue_events:
        lines.append("🚨 *Overdue — Needs Attention*")
        for e in overdue_events[:3]:
            emoji = PRIORITY_EMOJI.get(_priority_value(e.priority), "⚪")
            ref = _event_ref(e)
            ref_str = f" ({_date_time_label(ref)})" if ref else ""
            lines.append(f"  {emoji} {e.title}{ref_str}")
        lines.append("")

    # ── Today's Plan (always shown) ───────────────────────────────────────────
    lines.append("📅 *Today's Plan*")
    if today_events:
        for e in today_events:
            lines.append(_event_line(e))
    else:
        lines.append("  ✨ No fixed tasks scheduled today.")
    lines.append("")

    # ── Tomorrow ──────────────────────────────────────────────────────────────
    if tomorrow_events:
        lines.append("📆 *Tomorrow*")
        for e in tomorrow_events:
            lines.append(_event_line(e))
        lines.append("")

    # ── This Week ─────────────────────────────────────────────────────────────
    if upcoming_events:
        lines.append("🗓️ *Coming Up This Week*")
        for e in upcoming_events[:5]:
            ref = _event_ref(e)
            lines.append(f"  • {e.title} ({ref.strftime('%a %d %b')})")
        lines.append("")

    lines.append("Reply *What's pending?* to see all tasks, or *weekly plan* for the full week.")
    return "\n".join(lines)


# ─── Night Summary ────────────────────────────────────────────────────────────

async def generate_night_summary(db: AsyncSession, user_phone: str) -> str:
    """
    Generate an end-of-day summary with full day review, completed tasks,
    incomplete tasks, tomorrow's full schedule, and a rotating quote.
    """
    now = now_ist()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    tomorrow_start = today_start + timedelta(days=1)
    tomorrow_end = tomorrow_start + timedelta(days=1)

    name = await _get_display_name(db, user_phone)

    # Completed today
    result = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.COMPLETED,
            Event.completed_at >= today_start,
            Event.user_phone == user_phone,
        )
    )
    completed = list(result.scalars().all())

    # All active events
    result2 = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.ACTIVE,
            Event.user_phone == user_phone,
        )
        .order_by(Event.event_datetime.asc().nullslast())
    )
    active = list(result2.scalars().all())

    # Created today
    result3 = await db.execute(
        select(Event)
        .where(
            Event.user_phone == user_phone,
            Event.created_at >= today_start,
            Event.created_at <= today_end,
        )
    )
    created_today = list(result3.scalars().all())

    # Messages reviewed today — use select_from to be Postgres-safe
    msg_count = await db.scalar(
        select(func.count())
        .select_from(IncomingMessage)
        .where(
            IncomingMessage.from_number == user_phone,
            IncomingMessage.received_at >= today_start,
            IncomingMessage.received_at <= today_end,
        )
    ) or 0

    # Tomorrow's events (full list, not just first)
    tomorrow_events = [
        e for e in active
        if _event_ref(e) and tomorrow_start <= _event_ref(e) < tomorrow_end
    ]

    # Overdue / pending from today
    pending_today = [
        e for e in active
        if _event_ref(e) and _event_ref(e) <= now
    ]

    # ── Header ────────────────────────────────────────────────────────────────
    farewell = f"Good night, {name}! 🌙" if name else "Good night! 🌙"
    lines = [
        f"🌙 *{farewell}*",
        f"_{now.strftime('%A, %B %d')}_",
        f"_{_night_quote(now)}_",
        "",
        "*📊 Full Day Summary*",
        f"  • Messages reviewed: {msg_count}",
        f"  • New tasks captured: {len(created_today)}",
        f"  • Tasks completed: {len(completed)}",
        f"  • Tasks still active: {len(active)}",
        "",
    ]

    # ── Completed Today ───────────────────────────────────────────────────────
    if completed:
        lines.append("✅ *Completed Today*")
        for e in completed:
            lines.append(f"  ✅ {e.title}")
        lines.append("")

    # ── Incomplete / Overdue ─────────────────────────────────────────────────
    if pending_today:
        lines.append("❌ *Incomplete / Overdue*")
        for e in pending_today:
            lines.append(f"  ❌ {e.title}")
        lines.append("")

    # ── Tomorrow's Schedule (full list) ───────────────────────────────────────
    if tomorrow_events:
        lines.append(f"📅 *Tomorrow ({tomorrow_start.strftime('%A, %d %b')})*")
        for e in tomorrow_events:
            ref = _event_ref(e)
            emoji = PRIORITY_EMOJI.get(_priority_value(e.priority), "⚪")
            lines.append(f"  {emoji} {e.title} — {ref.strftime('%I:%M %p')}")
    else:
        lines.append("✨ *Tomorrow looks clear.* Rest well!")

    lines.append("")
    lines.append("Sleep well. I'll have the morning plan ready when you wake up. 💤")
    return "\n".join(lines)


# ─── Weekly Plan ─────────────────────────────────────────────────────────────

async def generate_weekly_plan(db: AsyncSession, user_phone: str) -> str:
    """
    Generate a calendar-style weekly plan from active events.
    Shows all 7 days, marking empty days as free.
    """
    now = now_ist()
    week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)

    all_events = await _active_events(db, user_phone)
    week_events = [
        event for event in all_events
        if _event_ref(event) and week_start <= _event_ref(event) < week_end
    ]

    name = await _get_display_name(db, user_phone)
    name_part = f", {name}" if name else ""

    header = (
        f"🗓️ *Your Week{name_part}*\n"
        f"_{week_start.strftime('%d %b')} — {(week_end - timedelta(days=1)).strftime('%d %b %Y')}_\n"
    )

    if not week_events:
        return (
            header
            + "No fixed events this week. Forward notices here and I'll build the calendar as they arrive.\n"
            + "\nReply *What's pending?* to see all tracked tasks."
        )

    lines = [header]

    for offset in range(7):
        day = week_start + timedelta(days=offset)
        day_events = [e for e in week_events if _event_ref(e).date() == day.date()]
        day_label = day.strftime("%A, %d %b")

        if day_events:
            lines.append(f"*{day_label}*")
            for event in day_events:
                lines.append(_event_line(event))
        else:
            # Mark free days explicitly
            if offset == 0:
                lines.append(f"*{day_label}* — ✨ Clear")
            else:
                lines.append(f"*{day_label}* — ✨ Free")
        lines.append("")

    # Focus first — high priority events
    high_priority = [
        event for event in week_events
        if _priority_value(event.priority) == EventPriority.HIGH.value
    ]
    if high_priority:
        lines.append("🔴 *Focus First This Week*")
        lines.extend(f"  • {event.title}" for event in high_priority[:5])
        lines.append("")

    lines.append(f"_{len(week_events)} event{'s' if len(week_events) != 1 else ''} this week. Reply *What's pending?* for full list._")
    return "\n".join(lines).strip()


# ─── Task List ────────────────────────────────────────────────────────────────

async def generate_task_list(db: AsyncSession, user_phone: str) -> str:
    """
    Generate a response to 'What's pending?' or 'What's on my plate?' for a specific user.
    """
    now = now_ist()

    result = await db.execute(
        select(Event)
        .where(
            Event.status == EventStatus.ACTIVE,
            Event.user_phone == user_phone,
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
        ref = _event_ref(e)
        if not ref:
            later.append(e)
            continue
        days = (ref.date() - now.date()).days
        if days < 0:
            urgent.append(e)
        elif days == 0:
            today.append(e)
        elif days <= 7:
            this_week.append(e)
        else:
            later.append(e)

    lines = ["📋 *Your Active Tasks*\n"]

    def fmt(e: Event) -> str:
        ref = _event_ref(e)
        emoji = PRIORITY_EMOJI.get(_priority_value(e.priority), "⚪")
        date_str = _date_time_label(ref) if ref else ""
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
