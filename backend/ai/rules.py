"""
Deterministic parsing for common FRIDAY requests.

These rules keep simple reminders off the Gemini quota path and provide a
fallback when the free API limit is exhausted.
"""

import re
from datetime import datetime, timedelta

from time_utils import to_ist_naive


TIME_RE = re.compile(
    r"(?<![./-])\b(?:at\s*)?(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b(?![./-]\d)",
    re.IGNORECASE,
)
RANGE_TIME_RE = re.compile(
    r"(?<![./-])\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*(?:-|to)\s*"
    r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?(?:"
    r"[./-](\d{1,2})(?:[./-](\d{2,4}))?|"
    r"\s+(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"(?:\s+(\d{2,4}))?)\b",
    re.IGNORECASE,
)
REMINDER_WORD_RE = re.compile(
    r"\b(remind me|msg me|message me|ping me|send me|tell me|remember|notify me)\b",
    re.IGNORECASE,
)
TRACK_WORD_RE = re.compile(
    r"\b(due|deadline|assessment|assignment|meeting|session|appointment|interview|"
    r"ppt|presentation|exam|test|bill|renew|renewal|expires?|payment|submit|"
    r"held|scheduled|rescheduled|postponed|lab session|theory class|practical|seminar|workshop)\b",
    re.IGNORECASE,
)
COMPLETE_RE = re.compile(
    r"\b(done|completed?|submitted?|paid|finished|attended|renewed|uploaded|closed)\b",
    re.IGNORECASE,
)
SEARCH_RE = re.compile(
    r"\b(pending|upcoming|task list|my tasks|summary|what'?s due|show .*tasks?|"
    r"weekly plan|this week|show week|week plan|week schedule)\b",
    re.IGNORECASE,
)
UPDATE_RE = re.compile(
    r"\b(updated?|changed?|rescheduled|postponed|new venue|venue changed|time changed)\b",
    re.IGNORECASE,
)
BULK_COMPLETE_RE = re.compile(
    r"\b(delete|clear|remove|dismiss|complete|mark)\b.*\b(completed?|done|ended|past|overdue)\b",
    re.IGNORECASE,
)

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


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


def _parse_date(message: str, current_datetime: datetime) -> datetime:
    base = to_ist_naive(current_datetime)
    lower = message.lower()

    match = DATE_RE.search(message)
    if not match:
        if "tomorrow" in lower:
            return base + timedelta(days=1)
        if "today" in lower or "tonight" in lower:
            return base
        return base

    day = int(match.group(1))
    numeric_month = match.group(2)
    numeric_year = match.group(3)
    named_month = match.group(4)
    named_year = match.group(5)
    month = int(numeric_month) if numeric_month else MONTHS[named_month.lower()]
    year = int(numeric_year or named_year or base.year)
    if year < 100:
        year += 2000

    try:
        parsed = base.replace(year=year, month=month, day=day)
    except ValueError:
        return base

    if not numeric_year and not named_year and parsed.date() < base.date():
        try:
            parsed = parsed.replace(year=year + 1)
        except ValueError:
            pass
    return parsed


def _parse_datetime(message: str, current_datetime: datetime) -> datetime | None:
    range_match = RANGE_TIME_RE.search(message)
    time_match = range_match or TIME_RE.search(message)
    date_base = _parse_date(message, current_datetime)
    lower = message.lower()

    if time_match:
        if range_match and not range_match.group(3):
            start = range_match.group(1)
            minute = f":{range_match.group(2)}" if range_match.group(2) else ""
            meridiem = range_match.group(6)
            synthetic = re.search(TIME_RE, f"{start}{minute} {meridiem}")
            parsed = _parse_time(synthetic, date_base) if synthetic else None
        else:
            parsed = _parse_time(time_match, date_base)
        if parsed:
            if any(word in lower for word in ("today", "tonight", "tomorrow")) or DATE_RE.search(message):
                return parsed.replace(
                    year=date_base.year,
                    month=date_base.month,
                    day=date_base.day,
                )
            return parsed

    if DATE_RE.search(message) or any(word in lower for word in ("today", "tonight", "tomorrow")):
        default_hour = 23 if any(word in lower for word in ("due", "deadline", "submit", "closes", "expires")) else 9
        default_minute = 59 if default_hour == 23 else 0
        return date_base.replace(hour=default_hour, minute=default_minute, second=0, microsecond=0)

    return None


def _clean_title(message: str, time_match: re.Match) -> str:
    title = message[: time_match.start()] + message[time_match.end() :]
    title = re.sub(r"\b(today|tomorrow|at|by|on)\b", " ", title, flags=re.IGNORECASE)
    title = REMINDER_WORD_RE.sub(" ", title)
    title = re.sub(r"\b(ok|okay|yes|sure|please|to|a|an|the|about)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" .,-")
    return title or "Reminder"


def _title_from_message(message: str, scheduled: datetime | None = None) -> str:
    title = re.sub(r"https?://\S+", " ", message)
    title = DATE_RE.sub(" ", title)
    title = TIME_RE.sub(" ", title)
    title = REMINDER_WORD_RE.sub(" ", title)
    title = re.sub(
        r"\b(today|tomorrow|tonight|at|by|on|from|to|pm|am|dear participants|regards|thank you|please|make a note|of the change)\b",
        " ",
        title,
        flags=re.IGNORECASE,
    )
    lines = [line.strip(" .,-") for line in title.splitlines() if line.strip(" .,-")]
    meaningful = next((line for line in lines if len(line) >= 4), "")
    meaningful = re.sub(r"\s+", " ", meaningful).strip(" .,-")
    if not meaningful:
        meaningful = "Reminder"
    if len(meaningful) > 80:
        meaningful = meaningful[:77].rstrip() + "..."
    return meaningful


def _category_for(message: str) -> str:
    lower = message.lower()
    if any(word in lower for word in ("assignment", "assessment", "submit", "lab", "deadline")):
        return "Assignment"
    if any(word in lower for word in ("placement", "ppt", "company", "industry session")):
        return "Placement"
    if any(word in lower for word in ("bill", "payment", "electricity")):
        return "Bill"
    if any(word in lower for word in ("netflix", "subscription", "renew", "expires")):
        return "Subscription"
    if any(word in lower for word in ("doctor", "hospital", "medicine", "health")):
        return "Health"
    if any(word in lower for word in ("interview", "internship")):
        return "Interview"
    if any(word in lower for word in ("class", "session", "meeting", "exam", "test")):
        return "College"
    return "Personal"


def _priority_for(message: str, scheduled: datetime | None, current_datetime: datetime) -> str:
    lower = message.lower()
    if any(word in lower for word in ("urgent", "deadline", "due today", "closes today", "assessment")):
        return "High"
    if scheduled and scheduled - to_ist_naive(current_datetime) <= timedelta(hours=24):
        return "High"
    return "Medium"


def _extract_link(message: str) -> str | None:
    match = re.search(r"https?://\S+", message)
    return match.group(0).rstrip(".,)") if match else None


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


def try_parse_local_intent(message_body: str, current_datetime: datetime) -> dict | None:
    """Fast local classifier for common commands and forwarded notices."""
    body = (message_body or "").strip()
    if not body:
        return None

    lower = body.lower()
    if SEARCH_RE.search(lower):
        return {
            "intent": "search",
            "confidence": 0.95,
            "reply_to_user": "",
            "event": None,
            "search_query": body,
            "matched_event_hint": None,
        }

    if BULK_COMPLETE_RE.search(lower) and len(body.split()) <= 12:
        return {
            "intent": "bulk_complete",
            "confidence": 0.95,
            "reply_to_user": "",
            "event": None,
            "search_query": None,
            "matched_event_hint": None,
            "bulk_scope": "overdue",
        }

    if COMPLETE_RE.search(lower) and len(body.split()) <= 8:
        hint = COMPLETE_RE.sub(" ", body).strip(" .,-") or None
        return {
            "intent": "complete_task",
            "confidence": 0.9,
            "reply_to_user": "",
            "event": None,
            "search_query": None,
            "matched_event_hint": hint,
        }

    scheduled = _parse_datetime(body, current_datetime)
    if not UPDATE_RE.search(body):
        simple = try_parse_create_event(body, current_datetime)
        if simple:
            return simple

    if not scheduled or not TRACK_WORD_RE.search(body):
        return None

    category = _category_for(body)
    title = _title_from_message(body, scheduled)
    is_deadline = bool(re.search(r"\b(due|deadline|submit|submission|closes|expires|renew|bill|payment)\b", lower))
    intent = "update_event" if UPDATE_RE.search(body) else "create_event"
    priority = _priority_for(body, scheduled, current_datetime)

    event = {
        "title": title[:500],
        "description": body,
        "category": category,
        "priority": priority,
        "event_datetime": None if is_deadline else scheduled.isoformat(),
        "deadline": scheduled.isoformat() if is_deadline else None,
        "venue": None,
        "link": _extract_link(body),
        "contact": None,
        "estimated_effort_hours": None,
        "is_recurring": False,
        "recurrence_rule": None,
    }
    reply_title = title if title != "Reminder" else "this"
    reply = f"Got it! I've saved *{reply_title}* for {scheduled.strftime('%d %b %Y, %I:%M %p')}."
    if intent == "update_event":
        reply = f"Got it! I've updated *{reply_title}* to {scheduled.strftime('%d %b %Y, %I:%M %p')}."

    return {
        "intent": intent,
        "confidence": 0.86,
        "reply_to_user": reply,
        "event": event,
        "search_query": None,
        "matched_event_hint": title,
    }
