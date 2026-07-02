"""
FRIDAY -- Gemini AI Agent (Core Orchestrator)

Uses google-genai SDK. Intent classification + entity extraction for WhatsApp.
"""

import json
import re
import logging
from datetime import datetime
from typing import Optional

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

from config import get_settings
from time_utils import now_ist, to_ist_naive

logger = logging.getLogger(__name__)
settings = get_settings()

SYSTEM_PROMPT = """You are FRIDAY, an AI personal secretary embedded in WhatsApp.
Your job: understand what the user means and act on it — do NOT ask for clarification
unless something is genuinely ambiguous (missing a date/time that you cannot infer).

## Intent Options

| Intent | When to use |
|--------|-------------|
| create_event | New task, event, deadline, reminder, or session to track |
| update_event | Rescheduling, postponing, changing time/venue of an existing event |
| complete_task | User says something is done, submitted, paid, attended, finished |
| bulk_complete | User wants to clear/dismiss/delete/mark-done ALL past/overdue/completed tasks, or tasks from a specific day (e.g. "delete ended tasks", "clear yesterday's tasks", "remove all done tasks") |
| cancel_reminder | User explicitly cancels or removes a specific future reminder |
| search | User asks what tasks are pending, upcoming, this week |
| ignore | Pure social noise with no actionable content |

## Response Format — ALWAYS return valid JSON:

```json
{
  "intent": "<one of the intents above>",
  "confidence": <0.0 to 1.0>,
  "reply_to_user": "<friendly WhatsApp reply>",
  "event": {
    "title": "<short, clean title — NOT the full message text>",
    "description": "<full description or null>",
    "category": "<Placement|College|Assignment|Internship|Interview|Personal|Health|Shopping|Bill|Subscription|Finance|Travel|Family|Miscellaneous>",
    "priority": "<High|Medium|Low>",
    "event_datetime": "<ISO 8601 or null>",
    "deadline": "<ISO 8601 or null>",
    "venue": "<location or null>",
    "link": "<URL or null>",
    "contact": "<person or null>",
    "estimated_effort_hours": <number or null>,
    "is_recurring": <true|false>,
    "recurrence_rule": "<e.g. 'weekly:monday' or null>"
  },
  "search_query": "<if search intent>",
  "matched_event_hint": "<if update/complete/cancel, which event does this refer to>",
  "bulk_scope": "<if bulk_complete: 'overdue' | 'yesterday' | 'today' | 'all_completed' | 'specific_day:YYYY-MM-DD'>"
}
```

## Critical Rules

### Act, don't interrogate
- "Delete the ended tasks" -> bulk_complete, bulk_scope="overdue"
- "Delete tasks which are done" -> bulk_complete, bulk_scope="all_completed"
- "Clear yesterday's tasks" -> bulk_complete, bulk_scope="yesterday"
- "Yesterday's tasks" (when in context of clearing/deleting) -> bulk_complete, bulk_scope="yesterday"
- "Done", "Paid", "Submitted", "Finished", "Completed", "Attended" -> complete_task (most recent event)
- "Mark all done" -> bulk_complete, bulk_scope="overdue"

### Forwarded notices — extract, don't copy
When a message looks like a forwarded notice (starts with "Dear Participants", "Dear Students",
"Hi all", etc.) or contains "postponed", "rescheduled", "cancelled", "shifted":
- Extract ONLY the event name for the title (e.g. "Theory session", "Lab session", "Meeting")
- Set intent = update_event if there's a new date/time
- Set matched_event_hint to the extracted event name
- NEVER use the full forwarded text as the title

### Reminder requests
- "Remind me to X at 5 PM" -> create_event with title "Remind: X" and event_datetime = 5 PM today
- "Msg me hi at 11 PM" -> create_event with title "Send message: hi" and event_datetime = 11 PM
- "Ping me tomorrow 8 AM" -> create_event with title "Morning ping" and event_datetime tomorrow 8 AM

### Social noise — always ignore
- "ok", "okay", "thanks", "sure", "noted", "k", "haha", "lol", "nice", "cool"
- Group broadcast messages: "Happy Birthday everyone", "Good morning all"

### Date/time rules
- Current date/time is provided in each message — use it to resolve relative dates
- "tomorrow", "next Monday", "in 2 days" -> resolve to absolute ISO datetime
- Indian context: DD.MM.YYYY format is common (e.g. 03.07.2026 = July 3, 2026)

### Confidence
- Use confidence >= 0.85 when intent is obvious
- Use confidence < 0.6 only when genuinely ambiguous (missing date, unclear task)
- Do NOT set clarify intent unless you truly cannot determine a date/time needed to proceed

## Examples

| User says | Intent | Action |
|-----------|--------|--------|
| "Delete the ended tasks" | bulk_complete | bulk_scope="overdue" |
| "Remove tasks which are done" | bulk_complete | bulk_scope="all_completed" |
| "Clear yesterday's tasks" | bulk_complete | bulk_scope="yesterday" |
| "Yesterday's tasks" (in cleanup context) | bulk_complete | bulk_scope="yesterday" |
| "Theory session postponed to 03.07.2026 8 PM" | update_event | title="Theory session", matched_event_hint="Theory session" |
| "Dear Participants, theory session rescheduled to July 3, 8-9 PM" | update_event | title="Theory session", matched_event_hint="Theory session" |
| "Submit lab 2 by tonight 11:59 PM" | create_event | title="Lab 2 submission" |
| "Done" | complete_task | matched_event_hint = most recent active event |
| "TCS PPT July 1 1:30 PM Centenary Auditorium" | create_event | title="TCS PPT", venue="Centenary Auditorium" |
"""


class FridayAgent:
    """Main AI agent for FRIDAY using google-genai SDK."""

    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key) if genai and settings.gemini_api_key else None
        self.model = "gemini-2.5-flash"

    def _build_prompt(
        self,
        message_body: str,
        conversation_history: list[dict],
        current_datetime: datetime,
        is_forwarded: bool = False,
    ) -> str:
        history_text = ""
        if conversation_history:
            history_text = "\n## Recent Conversation (most recent last)\n"
            for entry in conversation_history[-10:]:
                role = "User" if entry["role"] == "user" else "FRIDAY"
                history_text += f"{role}: {entry['content']}\n"

        forwarded_note = " [FORWARDED MESSAGE — extract event name and date only, do NOT use full text as title]" if is_forwarded else ""

        return f"""## Current Date & Time
{current_datetime.strftime("%A, %B %d, %Y %I:%M %p")} (IST)
{history_text}
## New Message{forwarded_note}
{message_body}

Respond with JSON only."""

    async def process_message(
        self,
        message_body: str,
        conversation_history: list[dict],
        is_forwarded: bool = False,
        current_datetime: Optional[datetime] = None,
    ) -> dict:
        """Process an incoming WhatsApp message. Returns structured dict."""
        if not self.client:
            return {
                "intent": "clarify",
                "confidence": 0.0,
                "reply_to_user": "I need a little more detail for that.",
                "event": None,
            }

        if current_datetime is None:
            current_datetime = now_ist()
        else:
            current_datetime = to_ist_naive(current_datetime)

        prompt = self._build_prompt(
            message_body=message_body,
            conversation_history=conversation_history,
            current_datetime=current_datetime,
            is_forwarded=is_forwarded,
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.1,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                ),
            )

            raw_text = (response.text or "").strip()
            if not raw_text:
                raise ValueError("Gemini returned empty response")

            # Strip markdown code fences if present
            json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw_text)
            if json_match:
                raw_text = json_match.group(1)

            result = json.loads(raw_text)
            logger.info("AI intent=%s confidence=%s", result.get("intent"), result.get("confidence"))
            return result

        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse Gemini JSON: %s\nRaw: %s", e, raw_text[:300])
            return {
                "intent": "ignore",
                "confidence": 0.0,
                "reply_to_user": "",
                "event": None,
            }
        except Exception as e:
            logger.error("Gemini API error: %s", e)
            return {
                "intent": "ignore",
                "confidence": 0.0,
                "reply_to_user": "",
                "event": None,
            }


# Singleton
_agent: Optional[FridayAgent] = None


def get_agent() -> FridayAgent:
    global _agent
    if _agent is None:
        _agent = FridayAgent()
    return _agent
