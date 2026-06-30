"""
FRIDAY — APScheduler Jobs

Scheduled tasks:
1. check_reminders()  — runs every minute, fires due reminders to their creators
2. morning_brief()    — sends personalized briefs to all active users
3. night_summary()    — sends personalized summaries to all active users
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, update

from database.database import AsyncSessionLocal
from database.models import ReminderPlan, ReminderHistory, Event, EventStatus, ReminderStatus
from services.whatsapp import send_whatsapp_message
from services.summary import generate_morning_brief, generate_night_summary
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def check_reminders():
    """
    Runs every minute. Checks for due reminder plans and sends them to the event creator.
    """
    now = datetime.now()
    window_end = now + timedelta(minutes=1)

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(ReminderPlan)
                .join(Event, ReminderPlan.event_id == Event.id)
                .where(
                    ReminderPlan.status == ReminderStatus.PENDING,
                    ReminderPlan.scheduled_at <= window_end,
                    Event.status == EventStatus.ACTIVE,
                )
            )
            due_plans = result.scalars().all()

            for plan in due_plans:
                event_result = await db.get(Event, plan.event_id)
                if not event_result or not event_result.user_phone:
                    continue

                message = plan.message_template or f"⏰ Reminder: *{event_result.title}*"
                success = await send_whatsapp_message(event_result.user_phone, message)

                if success:
                    plan.status = ReminderStatus.SENT
                    plan.sent_at = now

                    # Log to history
                    history = ReminderHistory(
                        event_id=event_result.id,
                        message_sent=message,
                        sent_at=now,
                    )
                    db.add(history)
                    logger.info(f"📤 Sent reminder '{plan.reminder_type}' to {event_result.user_phone} for '{event_result.title}'")
                else:
                    plan.status = ReminderStatus.FAILED
                    logger.warning(f"❌ Failed to send reminder to {event_result.user_phone} for '{event_result.title}'")

            if due_plans:
                await db.commit()
        except Exception as e:
            logger.error(f"Error in check_reminders: {e}")


async def _get_all_active_users(db) -> list[str]:
    """Query database to find all phone numbers that have interacted with FRIDAY."""
    result = await db.execute(
        select(Event.user_phone).distinct().where(Event.user_phone.isnot(None))
    )
    phones = list(result.scalars().all())
    
    # Also default to settings number if not present
    if settings.my_whatsapp_number and settings.my_whatsapp_number not in phones:
        phones.append(settings.my_whatsapp_number)
    return phones


async def send_morning_brief():
    """Send personalized morning agenda to all active users."""
    logger.info("🌅 Sending morning briefs...")
    async with AsyncSessionLocal() as db:
        try:
            users = await _get_all_active_users(db)
            for user in users:
                message = await generate_morning_brief(db, user)
                await send_whatsapp_message(user, message)
        except Exception as e:
            logger.error(f"Error in morning brief: {e}")


async def send_night_summary():
    """Send personalized end-of-day summary to all active users."""
    logger.info("🌙 Sending night summaries...")
    async with AsyncSessionLocal() as db:
        try:
            users = await _get_all_active_users(db)
            for user in users:
                message = await generate_night_summary(db, user)
                await send_whatsapp_message(user, message)
        except Exception as e:
            logger.error(f"Error in night summary: {e}")


def start_scheduler():
    """Initialize and start all scheduled jobs."""
    # Run every minute to check due reminders
    scheduler.add_job(
        check_reminders,
        trigger="interval",
        minutes=1,
        id="check_reminders",
        name="Check Due Reminders",
        replace_existing=True,
    )

    # Morning brief at configured time (IST)
    scheduler.add_job(
        send_morning_brief,
        trigger=CronTrigger(
            hour=settings.morning_brief_hour,
            minute=settings.morning_brief_minute,
            timezone="Asia/Kolkata",
        ),
        id="morning_brief",
        name="Morning Brief",
        replace_existing=True,
    )

    # Night summary at configured time (IST)
    scheduler.add_job(
        send_night_summary,
        trigger=CronTrigger(
            hour=settings.night_summary_hour,
            minute=settings.night_summary_minute,
            timezone="Asia/Kolkata",
        ),
        id="night_summary",
        name="Night Summary",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"⏰ Scheduler started. Morning brief at {settings.morning_brief_hour:02d}:{settings.morning_brief_minute:02d} IST, "
        f"Night summary at {settings.night_summary_hour:02d}:{settings.night_summary_minute:02d} IST"
    )


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("⏰ Scheduler stopped.")
