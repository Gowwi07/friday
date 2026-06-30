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
from ai.rules import try_parse_create_event
from api import webhook
from database.database import AsyncSessionLocal, engine
from database.models import Base, Event, IncomingMessage, ReminderPlan, ScheduledJobRun
from time_utils import IST, parse_iso_datetime


class FakeAgent:
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

    async def test_simple_reminder_is_created_without_ai_call(self):
        agent = AsyncMock()
        with patch.object(webhook, "get_agent", return_value=agent), patch.object(
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

        agent.process_message.assert_not_called()
        async with AsyncSessionLocal() as db:
            event = await db.scalar(select(Event))
            plans = (await db.execute(select(ReminderPlan))).scalars().all()

        self.assertEqual(event.title, "c++ study")
        self.assertTrue(any(plan.reminder_type == "at_time" for plan in plans))

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
