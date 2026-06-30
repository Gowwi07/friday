"""
Deterministic parsing for common FRIDAY requests.

These rules keep simple reminders off the Gemini quota path and provide a
fallback when the free API limit is exhausted.
"""

import re
from datetime import datetime, timedelta

from time_utils import to_ist_naive


TIME_RE = re.compile(r"\b(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
REMINDER_WORD_RE = re.compile(
    r"\b(remind me|msg me|message me|ping me|send me|tell me)\b",
    re.IGNORECASE,
)


def _parse_time(match: re.Match, current_datetime: datetime) -> datetime | None:
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    meridiem = (match.group(3) or "").lower()

    if minute > 59:
        return None
    if meridiem:
        if hour < 1 or hour > 12:
            return None
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    elif hour > 23:
        return None

    base = to_ist_naive(current_datetime)
    lower = match.string.lower()
    if "tomorrow" in lower:
        base += timedelta(days=1)

    scheduled = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if "tomorrow" not in lower and scheduled <= to_ist_naive(current_datetime):
        scheduled += timedelta(days=1)
    return scheduled


def _clean_title(message: str, time_match: re.Match) -> str:
    title = message[: time_match.start()] + message[time_match.end() :]
    title = re.sub(r"\b(today|tomorrow|at|by|on)\b", " ", title, flags=re.IGNORECASE)
    title = REMINDER_WORD_RE.sub(" ", title)
    title = re.sub(r"\b(ok|okay|yes|sure|please|to|a|an|the|about)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .,-")
    return title or "Reminder"


def try_parse_create_event(message_body: str, current_datetime: datetime) -> dict | None:
    """Return a create_event AI-shaped result for obvious reminder messages."""
    body = (message_body or "").strip()
    if not body:
        return None

    lower = body.lower()
    has_reminder_word = bool(REMINDER_WORD_RE.search(body))
    has_date_word = "tomorrow" in lower or "today" in lower
    time_match = TIME_RE.search(body)

    if not time_match or not (has_reminder_word or has_date_word):
        return None

    scheduled = _parse_time(time_match, current_datetime)
    if not scheduled:
        return None

    title = _clean_title(body, time_match)
    if has_reminder_word and title.lower() != "reminder":
        title = f"Message {title}"

    return {
        "intent": "create_event",
        "confidence": 0.95,
        "reply_to_user": f"Got it! I'll remind you about *{title}* at {scheduled.strftime('%I:%M %p')}.",
        "event": {
            "title": title[:500],
            "description": body,
            "category": "Personal",
            "priority": "Medium",
            "event_datetime": scheduled.isoformat(),
            "deadline": None,
            "venue": None,
            "link": None,
            "contact": None,
            "estimated_effort_hours": None,
            "is_recurring": False,
            "recurrence_rule": None,
        },
        "search_query": None,
        "matched_event_hint": None,
    }
