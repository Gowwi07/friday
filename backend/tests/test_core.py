"""Regression tests for FRIDAY's webhook and reminder pipeline."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["APP_ENV"] = "test"
os.environ["CRON_SECRET"] = "test-cron-secret"

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from ai.planner import plan_reminders
from ai.rules import try_parse_create_event, try_parse_local_intent
from api import webhook
from database.database import AsyncSessionLocal, engine
from database.models import Base, Event, IncomingMessage, ReminderPlan, ScheduledJobRun
from services.reminder import create_event_from_ai
from services.summary import generate_morning_brief, generate_night_summary, generate_weekly_plan
from time_utils import IST, parse_iso_datetime


class FakeAgent:
    """Simulates a configured Gemini agent (client is truthy)."""
    client = True  # must be truthy so the Gemini-first path runs

    async def process_message(self, **_kwargs):
        future = datetime.now(IST) + timedelta(days=2)
        return {
            "intent": "create_event",
            "confidence": 0.95,
            "reply_to_user": "Saved.",
            "event": {
                "title": "Timezone regression test",
                "category": "NotARealCategory",
                "priority": "Urgent",
                "event_datetime": future.isoformat(),
            },
        }


class NoGeminiAgent:
    """Simulates an unconfigured agent (client is falsy) -> triggers local-rules fallback."""
    client = None

    async def process_message(self, **_kwargs):
        raise RuntimeError("Should not be called when client is None")


class TimeTests(unittest.TestCase):
    def test_offset_datetime_is_converted_to_naive_ist(self):
        parsed = parse_iso_datetime("2026-07-01T12:00:00Z")
        self.assertEqual(parsed, datetime(2026, 7, 1, 17, 30))
        self.assertIsNone(parsed.tzinfo)

    def test_planner_accepts_timezone_aware_datetime(self):
        future = datetime.now(timezone.utc) + timedelta(days=2)
        reminders = plan_reminders(future, None, "Personal", "Medium", "Test")
        self.assertTrue(reminders)
        self.assertTrue(all(item["scheduled_at"].tzinfo is None for item in reminders))

    def test_planner_includes_at_time_reminder_for_near_term_events(self):
        future = datetime.now(IST) + timedelta(minutes=4)
        reminders = plan_reminders(future, None, "Personal", "Medium", "Message me hi")
        self.assertTrue(any(item["reminder_type"] == "at_time" for item in reminders))

    def test_rules_parse_common_reminders_without_ai(self):
        current = datetime(2026, 6, 30, 23, 26, tzinfo=IST)

        study = try_parse_create_event("Tomorrow 5pm c++ study", current)
        self.assertEqual(study["intent"], "create_event")
        self.assertEqual(study["event"]["title"], "c++ study")
        self.assertEqual(parse_iso_datetime(study["event"]["event_datetime"]), datetime(2026, 7, 1, 17, 0))

        message = try_parse_create_event("Ok msg me a hi at 23:30", current)
        self.assertEqual(message["event"]["title"], "Message hi")
        self.assertEqual(parse_iso_datetime(message["event"]["event_datetime"]), datetime(2026, 6, 30, 23, 30))

    def test_rules_parse_forwarded_reschedule_without_confusing_date_as_time(self):
        current = datetime(2026, 7, 2, 19, 52, tzinfo=IST)
        result = try_parse_local_intent(
            "Dear Participants\nToday's theory session has been postponed and rescheduled to 03.07.2026, time 8 to 9 pm.",
            current,
        )

        self.assertEqual(result["intent"], "update_event")
        self.assertEqual(parse_iso_datetime(result["event"]["event_datetime"]), datetime(2026, 7, 3, 20, 0))

    def test_rules_parse_completion_without_ai(self):
        current = datetime(2026, 7, 2, 19, 52, tzinfo=IST)
        result = try_parse_local_intent("Completed core assessment", current)
        self.assertEqual(result["intent"], "complete_task")
        self.assertEqual(result["matched_event_hint"], "core assessment")

    def test_rules_weekly_plan_routes_to_search(self):
        """'weekly plan' message should resolve to search intent without Gemini."""
        current = datetime(2026, 7, 2, 10, 0, tzinfo=IST)
        result = try_parse_local_intent("weekly plan", current)
        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "search")

    def test_rules_this_week_routes_to_search(self):
        """'this week' message should resolve to search intent without Gemini."""
        current = datetime(2026, 7, 2, 10, 0, tzinfo=IST)
        result = try_parse_local_intent("this week", current)
        self.assertIsNotNone(result)
        self.assertEqual(result["intent"], "search")


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def test_message_pipeline_creates_one_event_and_is_idempotent(self):
        with patch.object(webhook, "get_agent", return_value=FakeAgent()), patch.object(
            webhook, "send_whatsapp_message", new=AsyncMock(return_value=True)
        ) as sender:
            kwargs = dict(
                from_number="919999999999",
                from_name="Test User",
                body="Meeting in two days",
                msg_id="wamid.test-1",
                msg_type="text",
                timestamp=1782840000,
            )
            await webhook._process_message(**kwargs)
            await webhook._process_message(**kwargs)

        async with AsyncSessionLocal() as db:
            event_count = await db.scalar(select(func.count()).select_from(Event))
            message_count = await db.scalar(select(func.count()).select_from(IncomingMessage))
            event = await db.scalar(select(Event))

        self.assertEqual(event_count, 1)
        self.assertEqual(message_count, 1)
        self.assertEqual(event.category.value, "Miscellaneous")
        self.assertEqual(event.priority.value, "Medium")
        sender.assert_awaited_once()

        async with AsyncSessionLocal() as db:
            plans = (await db.execute(select(ReminderPlan))).scalars().all()
        self.assertTrue(any(plan.reminder_type == "at_time" for plan in plans))

    async def test_simple_reminder_created_via_local_rules_when_no_gemini(self):
        """When Gemini is not configured (client=None), local rules extract the event."""
        with patch.object(webhook, "get_agent", return_value=NoGeminiAgent()), patch.object(
            webhook, "send_whatsapp_message", new=AsyncMock(return_value=True)
        ):
            await webhook._process_message(
                from_number="919999999999",
                from_name="Test User",
                body="Tomorrow 5pm c++ study",
                msg_id="wamid.simple-1",
                msg_type="text",
                timestamp=1782840000,
            )

        async with AsyncSessionLocal() as db:
            event = await db.scalar(select(Event))
            plans = (await db.execute(select(ReminderPlan))).scalars().all()

        # Local rules should have captured the event
        self.assertIsNotNone(event)
        self.assertEqual(event.title, "c++ study")
        self.assertTrue(any(plan.reminder_type == "at_time" for plan in plans))

    async def test_forwarded_update_reuses_existing_event(self):
        with patch.object(webhook, "send_whatsapp_message", new=AsyncMock(return_value=True)):
            await webhook._process_message(
                from_number="919999999999",
                from_name="Test User",
                body="Theory session tomorrow 8 pm",
                msg_id="wamid.update-1",
                msg_type="text",
                timestamp=1782840000,
            )
            await webhook._process_message(
                from_number="919999999999",
                from_name="Test User",
                body="Dear Participants\nToday's theory session has been postponed and rescheduled to 03.07.2026, time 8 to 9 pm.",
                msg_id="wamid.update-2",
                msg_type="text",
                timestamp=1782840000,
                is_forwarded=True,
            )

        async with AsyncSessionLocal() as db:
            events = (await db.execute(select(Event))).scalars().all()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_datetime, datetime(2026, 7, 3, 20, 0))

    async def test_same_course_different_datetime_stays_separate(self):
        """Same course title on different dates must create separate events."""
        async with AsyncSessionLocal() as db:
            base = {
                "intent": "create_event",
                "confidence": 0.95,
                "reply_to_user": "Saved.",
                "event": {
                    "title": "Theory session",
                    "category": "College",
                    "priority": "Medium",
                    "event_datetime": "2026-07-03T20:00:00",
                },
            }
            await create_event_from_ai(db, base, "Theory session 03.07.2026 8 pm", "919999999999")
            await create_event_from_ai(
                db,
                {
                    **base,
                    "event": {
                        **base["event"],
                        "event_datetime": "2026-07-10T20:00:00",
                    },
                },
                "Theory session 10.07.2026 8 pm",
                "919999999999",
            )

        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count()).select_from(Event))

        self.assertEqual(count, 2)

    async def test_same_course_close_datetime_merges(self):
        """Same course title within 6h window is treated as duplicate update."""
        async with AsyncSessionLocal() as db:
            base = {
                "intent": "create_event",
                "confidence": 0.95,
                "reply_to_user": "Saved.",
                "event": {
                    "title": "Theory session",
                    "category": "College",
                    "priority": "Medium",
                    "event_datetime": "2026-07-03T20:00:00",
                },
            }
            await create_event_from_ai(db, base, "Theory session 8 pm", "919999999999")
            # Same day, 1 hour offset — should merge
            await create_event_from_ai(
                db,
                {**base, "event": {**base["event"], "event_datetime": "2026-07-03T21:00:00"}},
                "Theory session 9 pm",
                "919999999999",
            )

        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count()).select_from(Event))

        # Should be 1 (second was treated as update)
        self.assertEqual(count, 1)

    async def test_different_lab_numbers_stay_separate(self):
        """Lab 1 and Lab 2 on same date must remain separate events (only 'theory' / 'session' words differ)."""
        async with AsyncSessionLocal() as db:
            lab1 = {
                "intent": "create_event",
                "confidence": 0.95,
                "reply_to_user": "Saved.",
                "event": {
                    "title": "Lab assessment 1",
                    "category": "Assignment",
                    "priority": "High",
                    "event_datetime": "2026-07-10T14:00:00",
                },
            }
            lab2 = {
                **lab1,
                "event": {**lab1["event"], "title": "Lab assessment 2"},
            }
            await create_event_from_ai(db, lab1, "Lab 1", "919999999999")
            await create_event_from_ai(db, lab2, "Lab 2", "919999999999")

        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count()).select_from(Event))

        # "assessment" is the only >3-char word shared and that alone is below threshold of 2
        # so they stay separate
        self.assertEqual(count, 2)

    async def test_assistant_summaries_include_plan_quote_and_week(self):
        async with AsyncSessionLocal() as db:
            await create_event_from_ai(
                db,
                {
                    "intent": "create_event",
                    "confidence": 0.95,
                    "reply_to_user": "Saved.",
                    "event": {
                        "title": "Lab assessment",
                        "category": "Assignment",
                        "priority": "High",
                        "deadline": (datetime.now(IST) + timedelta(days=1)).isoformat(),
                    },
                },
                "Lab assessment due tomorrow",
                "919999999999",
            )
            morning = await generate_morning_brief(db, "919999999999")
            night = await generate_night_summary(db, "919999999999")
            weekly = await generate_weekly_plan(db, "919999999999")

        # Morning: greeting + quote + plan section
        self.assertIn("Good morning", morning)
        self.assertIn("Today's Plan", morning)
        # Morning should always have quote
        self.assertIn("_", morning)  # italic quote

        # Night: greeting + quote + summary sections
        self.assertIn("Good night", night)
        self.assertIn("Full Day Summary", night)

        # Weekly: header + event listed
        self.assertIn("Your Week", weekly)
        self.assertIn("Lab assessment", weekly)

    async def test_night_summary_message_count_does_not_crash(self):
        """func.count() with select_from() must not raise an error."""
        async with AsyncSessionLocal() as db:
            # No messages in DB — should return 0 cleanly
            night = await generate_night_summary(db, "919000000000")
        self.assertIn("Good night", night)
        self.assertIn("Messages reviewed: 0", night)

    async def test_daily_job_claim_is_idempotent(self):
        from scheduler.jobs import _claim_daily_job

        self.assertTrue(await _claim_daily_job("test_brief"))
        self.assertFalse(await _claim_daily_job("test_brief"))
        async with AsyncSessionLocal() as db:
            count = await db.scalar(select(func.count()).select_from(ScheduledJobRun))
        self.assertEqual(count, 1)


class WebhookPayloadTests(unittest.TestCase):
    def test_bridge_payload_is_accepted(self):
        app = FastAPI()
        app.include_router(webhook.router)
        process = AsyncMock()
        with patch.object(webhook, "_process_message", new=process):
            with TestClient(app) as client:
                response = client.post(
                    "/webhook",
                    json={
                        "message_id": "bridge-1",
                        "from": "919999999999@c.us",
                        "from_name": "Bridge User",
                        "body": "Remember this",
                        "type": "chat",
                        "timestamp": 1782840000,
                        "is_forwarded": True,
                        "context": {"id": "quoted-1"},
                    },
                )

        self.assertEqual(response.status_code, 200)
        process.assert_awaited_once()
        self.assertEqual(process.await_args.kwargs["body"], "Remember this")
        self.assertTrue(process.await_args.kwargs["is_forwarded"])
        self.assertEqual(process.await_args.kwargs["quoted_msg_id"], "quoted-1")


if __name__ == "__main__":
    unittest.main()
