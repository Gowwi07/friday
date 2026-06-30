"""
FRIDAY — Reminder Planner

Given an event, generates an intelligent reminder schedule.
Different event types get different reminder cadences.
"""

from datetime import datetime, timedelta
from typing import Optional
import logging

from database.models import EventCategory, EventPriority
from time_utils import now_ist, to_ist_naive

logger = logging.getLogger(__name__)


def plan_reminders(
    event_datetime: Optional[datetime],
    deadline: Optional[datetime],
    category: str,
    priority: str,
    title: str,
    venue: Optional[str] = None,
) -> list[dict]:
    """
    Returns a list of reminder dicts:
    [
      {
        "scheduled_at": datetime,
        "reminder_type": str,
        "message_template": str,
      },
      ...
    ]

    Smart rules by category:
    - Exam/Interview: 7d, 3d, 1d, morning, 1h before
    - Assignment/Lab: 3d, 1d, morning, 2h before deadline
    - Meeting/PPT: 1d, morning, 1h, 15min before
    - Bill/Subscription: 3d, 1d, same day
    - Personal/Health: 1d, morning, 1h before
    - Recurring: just the morning of
    """
    now = now_ist()
    reminders = []
    ref_time = event_datetime or deadline

    if not ref_time:
        logger.warning(f"No datetime for event '{title}', skipping reminder planning.")
        return []

    ref_time = to_ist_naive(ref_time)
    if ref_time < now:
        logger.warning(f"Event '{title}' is in the past, skipping.")
        return []

    venue_text = f"\n📍 Venue: {venue}" if venue else ""
    days_until = (ref_time - now).days

    # ─── Category-specific reminder rules ─────────────────────────────────

    cat = category if isinstance(category, str) else category.value
    pri = priority if isinstance(priority, str) else priority.value

    def add(delta_before: timedelta, rtype: str, template: str):
        fire_at = ref_time - delta_before
        if fire_at > now:
            reminders.append({
                "scheduled_at": fire_at,
                "reminder_type": rtype,
                "message_template": template,
            })

    def add_at_time(template: str):
        if ref_time > now:
            reminders.append({
                "scheduled_at": ref_time,
                "reminder_type": "at_time",
                "message_template": template,
            })

    if cat in ("Placement", "Interview", "Internship"):
        # ─ High-stakes events ─
        add(timedelta(days=7), "7d_before",
            f"📋 *{title}* is in 7 days!\nStart preparing now.{venue_text}")
        add(timedelta(days=3), "3d_before",
            f"📋 *{title}* is in 3 days.\nHave you started preparing?{venue_text}")
        add(timedelta(days=1), "1d_before",
            f"⚠️ *{title}* is TOMORROW.\nMake sure your documents/resume are ready!{venue_text}")
        # Morning of event
        morning_of = ref_time.replace(hour=7, minute=0, second=0, microsecond=0)
        if morning_of > now:
            reminders.append({
                "scheduled_at": morning_of,
                "reminder_type": "morning_of",
                "message_template": f"🌅 Good morning! *{title}* is today at {ref_time.strftime('%I:%M %p')}.{venue_text}\nAre you prepared?",
            })
        add(timedelta(hours=2), "2h_before",
            f"⏰ *{title}* starts in 2 hours!{venue_text}\nAre you getting ready?")
        add(timedelta(hours=1), "1h_before",
            f"🔔 *{title}* starts in 1 hour!{venue_text}")
        add(timedelta(minutes=15), "15min_before",
            f"🚨 *{title}* starts in 15 minutes!{venue_text}\nAre you on your way?")
        add_at_time(f"🚨 *{title}* is starting now!{venue_text}")

    elif cat in ("Assignment", "College"):
        # ─ Deadlines ─
        add(timedelta(days=3), "3d_before",
            f"📝 *{title}* deadline is in 3 days.\nHave you started?")
        add(timedelta(days=1), "1d_before",
            f"⚠️ *{title}* is due TOMORROW.\nGet it done tonight!")
        # Morning of
        morning_of = ref_time.replace(hour=7, minute=0, second=0, microsecond=0)
        if morning_of > now:
            reminders.append({
                "scheduled_at": morning_of,
                "reminder_type": "morning_of",
                "message_template": f"🌅 *{title}* is due today at {ref_time.strftime('%I:%M %p')}!\nPriority: URGENT!",
            })
        add(timedelta(hours=2), "2h_before",
            f"🚨 *{title}* deadline in 2 hours!\nHave you submitted?")
        add_at_time(f"🚨 *{title}* is due now!")

    elif cat in ("Bill", "Subscription", "Finance"):
        # ─ Payment deadlines ─
        add(timedelta(days=3), "3d_before",
            f"💰 *{title}* is due in 3 days.\nPay before it expires!")
        add(timedelta(days=1), "1d_before",
            f"⚠️ *{title}* is due TOMORROW.")
        add(timedelta(hours=2), "same_day",
            f"🔴 *{title}* is due today! Don't forget to pay.")
        add_at_time(f"🔴 *{title}* is due now. Don't forget to pay.")

    elif cat in ("Personal", "Health", "Family"):
        # ─ Personal appointments ─
        add(timedelta(days=1), "1d_before",
            f"📅 Reminder: *{title}* is tomorrow at {ref_time.strftime('%I:%M %p')}.{venue_text}")
        morning_of = ref_time.replace(hour=7, minute=0, second=0, microsecond=0)
        if morning_of > now:
            reminders.append({
                "scheduled_at": morning_of,
                "reminder_type": "morning_of",
                "message_template": f"🌅 *{title}* is today at {ref_time.strftime('%I:%M %p')}.{venue_text}",
            })
        add(timedelta(hours=1), "1h_before",
            f"⏰ *{title}* is in 1 hour!{venue_text}")
        add_at_time(f"⏰ Reminder: *{title}*{venue_text}")

    else:
        # ─ Generic ─
        if days_until >= 3:
            add(timedelta(days=1), "1d_before",
                f"📅 Reminder: *{title}* is tomorrow.")
        morning_of = ref_time.replace(hour=7, minute=0, second=0, microsecond=0)
        if morning_of > now:
            reminders.append({
                "scheduled_at": morning_of,
                "reminder_type": "morning_of",
                "message_template": f"🌅 *{title}* is today at {ref_time.strftime('%I:%M %p')}.{venue_text}",
            })
        add(timedelta(hours=1), "1h_before",
            f"⏰ *{title}* is in 1 hour!{venue_text}")
        add_at_time(f"⏰ Reminder: *{title}*{venue_text}")

    # ─── Follow-up reminder (30 min after event) ──────────────────────────
    follow_up = ref_time + timedelta(minutes=30)
    if follow_up > now:
        reminders.append({
            "scheduled_at": follow_up,
            "reminder_type": "follow_up",
            "message_template": f"✅ Did you complete *{title}*?\nReply *Done* to mark it complete, or *Snooze* to remind you later.",
        })

    reminders.sort(key=lambda x: x["scheduled_at"])
    logger.info(f"Planned {len(reminders)} reminders for '{title}'")
    return reminders
