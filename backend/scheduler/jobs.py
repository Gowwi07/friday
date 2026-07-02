"""
FRIDAY — APScheduler Jobs

Scheduled tasks:
1. check_reminders()  — runs every minute, fires due reminders to their creators
2. morning_brief()    — sends wake-time personalized briefs to all active users
3. night_summary()    — sends personalized summaries to all active users
4. weekly_plan()      — sends a Monday weekly calendar plan
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.database import AsyncSessionLocal
from database.models import (
    ReminderPlan, ReminderHistory, Event, EventStatus, ReminderStatus,
    ScheduledJobRun,
)
from services.whatsapp import send_whatsapp_message
from services.summary import (
    generate_morning_brief,
    generate_night_summary,
    generate_weekly_plan,
)
from config import get_settings
from time_utils import now_ist

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


# ─── Reminder checker ─────────────────────────────────────────────────────────

async def check_reminders():
    """
    Runs every minute. Checks for due reminder plans and sends them to the event creator.
    """
    now = now_ist()
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
                    history = ReminderHistory(
                        event_id=event_result.id,
                        message_sent=message,
                        sent_at=now,
                    )
                    db.add(history)
                    logger.info(
                        "📤 Sent reminder '%s' to %s for '%s'",
                        plan.reminder_type, event_result.user_phone[:8], event_result.title
                    )
                else:
                    plan.status = ReminderStatus.FAILED
                    logger.warning(
                        "❌ Failed to send reminder to %s for '%s'",
                        event_result.user_phone[:8], event_result.title
                    )

            if due_plans:
                await db.commit()
        except Exception as e:
            logger.error("Error in check_reminders: %s", e)


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_all_active_users(db) -> list[str]:
    """Query database to find all phone numbers that have interacted with FRIDAY."""
    result = await db.execute(
        select(Event.user_phone).distinct().where(Event.user_phone.isnot(None))
    )
    phones = list(result.scalars().all())
    # Always include the owner's personal number
    if settings.my_whatsapp_number and settings.my_whatsapp_number not in phones:
        phones.append(settings.my_whatsapp_number)
    return phones


async def _claim_daily_job(job_name: str) -> bool:
    """Ensure daily summaries run at most once per day even if the server restarts."""
    today = now_ist().date().isoformat()
    async with AsyncSessionLocal() as db:
        db.add(ScheduledJobRun(
            job_key=f"{job_name}:{today}",
            job_name=job_name,
            run_date=today,
        ))
        try:
            await db.commit()
            return True
        except IntegrityError:
            await db.rollback()
            return False


# ─── Scheduled jobs ───────────────────────────────────────────────────────────

async def send_morning_brief():
    """Send personalized morning agenda to all active users (one per user, isolated)."""
    if not await _claim_daily_job("morning_brief"):
        return
    logger.info("🌅 Sending morning briefs...")
    async with AsyncSessionLocal() as db:
        users = await _get_all_active_users(db)
    for user in users:
        try:
            async with AsyncSessionLocal() as db:
                message = await generate_morning_brief(db, user)
            await send_whatsapp_message(user, message)
            logger.info("✅ Morning brief sent to %s", user[:8])
        except Exception as e:
            logger.error("Error sending morning brief to %s: %s", user[:8], e)


async def send_night_summary():
    """Send personalized end-of-day summary to all active users."""
    if not await _claim_daily_job("night_summary"):
        return
    logger.info("🌙 Sending night summaries...")
    async with AsyncSessionLocal() as db:
        users = await _get_all_active_users(db)
    for user in users:
        try:
            async with AsyncSessionLocal() as db:
                message = await generate_night_summary(db, user)
            await send_whatsapp_message(user, message)
            logger.info("✅ Night summary sent to %s", user[:8])
        except Exception as e:
            logger.error("Error sending night summary to %s: %s", user[:8], e)


async def send_weekly_plan():
    """Send a calendar-style weekly plan to all active users once each Monday."""
    if now_ist().weekday() != 0:
        return
    if not await _claim_daily_job("weekly_plan"):
        return
    logger.info("🗓️ Sending weekly plans...")
    async with AsyncSessionLocal() as db:
        users = await _get_all_active_users(db)
    for user in users:
        try:
            async with AsyncSessionLocal() as db:
                message = await generate_weekly_plan(db, user)
            await send_whatsapp_message(user, message)
            logger.info("✅ Weekly plan sent to %s", user[:8])
        except Exception as e:
            logger.error("Error sending weekly plan to %s: %s", user[:8], e)


# ─── Scheduler lifecycle ─────────────────────────────────────────────────────

def start_scheduler():
    """Initialize and start all scheduled jobs."""
    # Check due reminders every minute
    scheduler.add_job(
        check_reminders,
        trigger="interval",
        minutes=1,
        id="check_reminders",
        name="Check Due Reminders",
        replace_existing=True,
    )

    # Morning brief at user's configured wake-up time (IST)
    scheduler.add_job(
        send_morning_brief,
        trigger=CronTrigger(
            hour=settings.wake_up_hour,
            minute=settings.wake_up_minute,
            timezone="Asia/Kolkata",
        ),
        id="morning_brief",
        name="Morning Brief",
        replace_existing=True,
    )

    # Weekly plan every Monday at wake-up time
    scheduler.add_job(
        send_weekly_plan,
        trigger=CronTrigger(
            day_of_week="mon",
            hour=settings.wake_up_hour,
            minute=settings.wake_up_minute,
            timezone="Asia/Kolkata",
        ),
        id="weekly_plan",
        name="Weekly Plan",
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
        "⏰ Scheduler started. Morning brief at %02d:%02d IST, "
        "Night summary at %02d:%02d IST",
        settings.wake_up_hour, settings.wake_up_minute,
        settings.night_summary_hour, settings.night_summary_minute,
    )


def stop_scheduler():
    """Stop the scheduler gracefully."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("⏰ Scheduler stopped.")


async def run_maintenance() -> dict:
    """Run work that must survive free-host sleep/wake cycles.

    Called by the /maintenance endpoint which is hit by GitHub Actions
    cron on free Render instances that can sleep.
    """
    await check_reminders()
    now = now_ist()
    morning_due = (now.hour, now.minute) >= (
        settings.wake_up_hour, settings.wake_up_minute
    )
    night_due = (now.hour, now.minute) >= (
        settings.night_summary_hour, settings.night_summary_minute
    )
    if morning_due:
        await send_morning_brief()
    if morning_due and now.weekday() == 0:
        await send_weekly_plan()
    if night_due:
        await send_night_summary()
    return {"status": "ok", "checked_at": now.isoformat()}
