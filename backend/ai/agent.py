"""
FRIDAY — Gemini AI Agent (Core Orchestrator)

Uses the new google-genai SDK (google.genai).
Intent classification + entity extraction for incoming WhatsApp messages.
"""

import json
import re
import logging
from datetime import datetime
from typing import Optional

from google import genai
from google.genai import types

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SYSTEM_PROMPT = """You are FRIDAY, an AI personal secretary that runs inside WhatsApp.

Your ONLY job is to help the user manage their tasks, events, and deadlines.

## Your Responsibilities
For every message the user sends or forwards, determine:
- Is this an event/task that needs tracking?
- Does it update an existing event?
- Is the user completing/cancelling a task?
- Is the user asking a question about their tasks?
- Or should it be ignored?

## Response Format
ALWAYS respond with a valid JSON object matching this schema:

```json
{
  "intent": "<one of: create_event | update_event | complete_task | cancel_reminder | search | clarify | ignore>",
  "confidence": <0.0 to 1.0>,
  "reply_to_user": "<friendly WhatsApp message to send back>",
  "event": {
    "title": "<short title>",
    "description": "<full description>",
    "category": "<Placement|College|Assignment|Internship|Interview|Personal|Health|Shopping|Bill|Subscription|Finance|Travel|Family|Miscellaneous>",
    "priority": "<High|Medium|Low>",
    "event_datetime": "<ISO 8601 datetime or null>",
    "deadline": "<ISO 8601 datetime or null>",
    "venue": "<location or null>",
    "link": "<URL or null>",
    "contact": "<person/contact or null>",
    "estimated_effort_hours": <number or null>,
    "is_recurring": <true|false>,
    "recurrence_rule": "<e.g. 'weekly:monday' or null>"
  },
  "search_query": "<if intent is search, what to search for>",
  "matched_event_hint": "<if intent is update/complete, describe which existing event this refers to>"
}
```

## Rules
1. If unsure, set confidence < 0.7 and ask for clarification in reply_to_user.
2. For casual messages like "ok", "thanks", "haha", set intent = "ignore".
3. For "Happy Birthday everyone", "Good morning group", set intent = "ignore".
4. For "Done", "Paid", "Submitted", "Finished", "Completed", "Attended" — set intent = "complete_task".
5. The current date/time context will be provided in each message.
6. Use Indian context: dates like "July 10" or "tomorrow 3 PM" should be parsed correctly.
7. Reply in a friendly but concise tone. Use emojis sparingly.
8. If event_datetime or deadline refers to a relative date, resolve it to absolute ISO datetime based on current_datetime provided.

## Examples of what to IGNORE
- "Happy Birthday everyone"
- "Ok noted"
- "Thanks"
- "Sure"

## Examples of what to TRACK
- "Team meeting tomorrow 10 AM"
- "Submit lab 2 by tonight 11:59 PM"
- "Netflix renews July 15"
- "Electricity bill due July 8"
- "Doctor appointment Monday 5 PM"
- "TCS PPT - July 1, 1:30 PM, Centenary Auditorium"
"""


class FridayAgent:
    """Main AI agent for FRIDAY using google-genai SDK."""

    def __init__(self):
        self.client = genai.Client(api_key=settings.gemini_api_key)
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
            history_text = "\n## Recent Conversation History\n"
            for entry in conversation_history[-10:]:
                role = "You" if entry["role"] == "user" else "FRIDAY"
                history_text += f"{role}: {entry['content']}\n"

        forwarded_note = " [This message was forwarded from another chat]" if is_forwarded else ""

        return f"""## Current Date & Time
{current_datetime.strftime("%A, %B %d, %Y %I:%M %p")} (IST)

{history_text}

## New Message{forwarded_note}
{message_body}

Respond with the JSON schema described in your instructions."""

    async def process_message(
        self,
        message_body: str,
        conversation_history: list[dict],
        is_forwarded: bool = False,
        current_datetime: Optional[datetime] = None,
    ) -> dict:
        """Process an incoming WhatsApp message. Returns structured dict."""
        if current_datetime is None:
            current_datetime = datetime.now()

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
                ),
            )

            raw_text = response.text.strip()

            # Strip markdown code fences if present
            json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw_text)
            if json_match:
                raw_text = json_match.group(1)

            result = json.loads(raw_text)
            logger.info(f"AI intent: {result.get('intent')} confidence: {result.get('confidence')}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini JSON: {e}\nRaw: {raw_text[:300]}")
            return {
                "intent": "clarify",
                "confidence": 0.0,
                "reply_to_user": "I had trouble understanding that. Could you rephrase?",
                "event": None,
            }
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return {
                "intent": "ignore",
                "confidence": 0.0,
                "reply_to_user": "I'm having trouble right now. Please try again in a moment.",
                "event": None,
            }


# Singleton
_agent: Optional[FridayAgent] = None


def get_agent() -> FridayAgent:
    global _agent
    if _agent is None:
        _agent = FridayAgent()
    return _agent
