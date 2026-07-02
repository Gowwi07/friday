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

SYSTEM_PROMPT = """You are FRIDAY, an AI personal secretary and cognitive companion embedded in WhatsApp.
Your job: understand what the user means, act on it, and converse with them proactively and warmly.

## Persona & Behavior
- Be helpful, conversational, and organized. Avoid dry machine-like replies.
- **Interactive scheduling**: If the user mentions a vague task or event (e.g. "I have a test this week", "Need to finish lab 1"), do NOT create it with a guessed/incorrect date. Instead, set intent to `chat` or `clarify` and ask them: *"Would you like me to schedule that? When is it due?"*
- **Cognitive awareness**: You are provided with a list of the user's `Active Tasks` (if any). Use this list to:
  - Offer suggestions (e.g. *"I noticed you have 'Math Prep' overdue. Would you like to push it to tomorrow?"*).
  - Confirm context when they say things like "reschedule it" or "done with that".
  - Engage when they casually check-in.

## Intent Options

| Intent | When to use |
|--------|-------------|
| create_event | New task, event, deadline, reminder, or session to track with clear date/time/deadline |
| update_event | Rescheduling, postponing, changing time/venue of an existing event |
| complete_task | User says something is done, submitted, paid, attended, finished |
| bulk_complete | User wants to clear/dismiss/delete/mark-done ALL past/overdue/completed tasks, or tasks from a specific day |
| cancel_reminder | User explicitly cancels or removes a specific future reminder |
| search | User asks what tasks are pending, upcoming, this week |
| chat | General greeting, talking about preferences, planning advice, casual check-ins, or interactive follow-ups (e.g., asking if they want to schedule a vague event) |
| ignore | Absolute social noise (single characters, random keyboard smash) |

## Response Format — ALWAYS return valid JSON:

```json
{
  "intent": "<one of the intents above>",
  "confidence": <0.0 to 1.0>,
  "reply_to_user": "<friendly, conversational WhatsApp reply>",
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

### Ask before assuming (Interactive Cognitive)
- Vague reminder: "Remind me to call Mom" (no time) -> intent="chat", reply_to_user="I'd love to remind you to call Mom! Shall I schedule that? What time/date works for you?"
- Vague class: "There is a mock interview this week" -> intent="chat", reply_to_user="I see you have a mock interview this week. Would you like me to add it to your calendar? If so, what day and time?"

### Forwarded notices — extract, don't copy
When a message looks like a forwarded notice (starts with "Dear Participants", "Dear Students",
"Hi all", etc.) or contains "postponed", "rescheduled", "cancelled", "shifted":
- Extract ONLY the event name for the title (e.g. "Theory session", "Lab session", "Meeting")
- Set intent = update_event if there's a new date/time
- Set matched_event_hint to the extracted event name
- NEVER use the full forwarded text as the title

### Date/time rules
- Current date/time is provided in each message — use it to resolve relative dates
- "tomorrow", "next Monday", "in 2 days" -> resolve to absolute ISO datetime
- Indian context: DD.MM.YYYY format is common (e.g. 03.07.2026 = July 3, 2026)

### Confidence
- Use confidence >= 0.85 when intent is obvious
- Use confidence < 0.6 only when genuinely ambiguous or if asking for clarification/permissions
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
        active_tasks_summary: str = "",
        is_forwarded: bool = False,
    ) -> str:
        history_text = ""
        if conversation_history:
            history_text = "\n## Recent Conversation (most recent last)\n"
            for entry in conversation_history[-10:]:
                role = "User" if entry["role"] == "user" else "FRIDAY"
                history_text += f"{role}: {entry['content']}\n"

        active_tasks_part = ""
        if active_tasks_summary:
            active_tasks_part = f"\n## User's Active Tasks\n{active_tasks_summary}\n"

        forwarded_note = " [FORWARDED MESSAGE — extract event name and date only, do NOT use full text as title]" if is_forwarded else ""

        return f"""## Current Date & Time
{current_datetime.strftime("%A, %B %d, %Y %I:%M %p")} (IST)
{active_tasks_part}{history_text}
## New Message{forwarded_note}
{message_body}

Respond with JSON only."""

    async def process_message(
        self,
        message_body: str,
        conversation_history: list[dict],
        active_tasks_summary: str = "",
        is_forwarded: bool = False,
        current_datetime: Optional[datetime] = None,
    ) -> dict:
        """Process an incoming WhatsApp message. Returns structured dict."""
        if not self.client:
            return {
                "intent": "chat",
                "confidence": 0.5,
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
            active_tasks_summary=active_tasks_summary,
            current_datetime=current_datetime,
            is_forwarded=is_forwarded,
        )

        try:
            # List of primary models to try on the primary key (ordered by quota availability)
            models_to_try = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest", "gemini-2.5-flash"]
            last_exception = None
            raw_text = ""

            for model in models_to_try:
                try:
                    response = await self.client.aio.models.generate_content(
                        model=model,
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
                    logger.info("AI intent=%s confidence=%s model=%s", result.get("intent"), result.get("confidence"), model)
                    return result
                except Exception as model_err:
                    logger.warning("Primary model %s failed: %s", model, model_err)
                    last_exception = model_err

            # Raise the last exception to trigger the fallback API keys block in the outer try-except
            raise last_exception or Exception("All primary models failed")

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

            # Try custom fallback API keys if configured
            if settings.fallback_api_keys:
                keys = [k.strip() for k in settings.fallback_api_keys.split(",") if k.strip()]
                for key in keys:
                    logger.info("Attempting fallback with model %s...", settings.fallback_model)
                    try:
                        import httpx
                        async with httpx.AsyncClient() as http_client:
                            response = await http_client.post(
                                f"{settings.fallback_base_url.rstrip('/')}/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {key}",
                                    "Content-Type": "application/json",
                                },
                                json={
                                    "model": settings.fallback_model,
                                    "messages": [
                                        {"role": "system", "content": SYSTEM_PROMPT},
                                        {"role": "user", "content": prompt},
                                    ],
                                    "temperature": 0.1,
                                    "response_format": {"type": "json_object"}
                                },
                                timeout=15.0,
                            )
                            if response.status_code == 200:
                                res_json = response.json()
                                raw_text = res_json["choices"][0]["message"]["content"].strip()

                                # Strip markdown code fences if present
                                json_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw_text)
                                if json_match:
                                    raw_text = json_match.group(1)

                                result = json.loads(raw_text)
                                logger.info("Fallback AI intent=%s confidence=%s", result.get("intent"), result.get("confidence"))
                                return result
                            else:
                                logger.warning("Fallback key failed with status code %d: %s", response.status_code, response.text[:200])
                    except Exception as fallback_err:
                        logger.error("Error using fallback key: %s", fallback_err)

            err_str = str(e).lower()
            reply = "I'm having a bit of trouble connecting to my brain right now. Please try again in a moment."
            if "429" in err_str or "resource_exhausted" in err_str:
                reply = "I've hit my daily Gemini limit for now. Please wait a bit or try again later!"
            elif "401" in err_str or "api_key" in err_str:
                reply = "My Gemini API key seems invalid. Please check the backend configuration."

            return {
                "intent": "ignore",
                "confidence": 0.0,
                "reply_to_user": reply,
                "event": None,
            }


# Singleton
_agent: Optional[FridayAgent] = None


def get_agent() -> FridayAgent:
    global _agent
    if _agent is None:
        _agent = FridayAgent()
    return _agent
