"""
FRIDAY Backend — Configuration
Loads settings from .env file.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "FRIDAY"
    app_env: str = "development"
    log_level: str = "INFO"
    cron_secret: str = ""

    # Owner's preferred first name for personalized greetings
    user_name: str = ""

    # Gemini AI
    gemini_api_key: str = ""

    # Fallback LLM APIs
    fallback_api_keys: str = ""
    fallback_base_url: str = "https://aiapiv2.pekpik.com/v1"
    fallback_model: str = "gemini-2.5-flash"

    # WhatsApp Business Cloud API (Meta)
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""

    # Your personal WhatsApp number (where FRIDAY sends reminders)
    # Format: 919876543210 (no + or @c.us)
    my_whatsapp_number: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./friday.db"

    # Scheduler — wake-up time drives the morning brief
    wake_up_hour: int = 7
    wake_up_minute: int = 0

    # Night summary time
    night_summary_hour: int = 22
    night_summary_minute: int = 0

    # Legacy aliases — kept so old .env files with MORNING_BRIEF_HOUR still work
    morning_brief_hour: int = -1   # -1 = use wake_up_hour
    morning_brief_minute: int = -1  # -1 = use wake_up_minute

    @property
    def effective_morning_hour(self) -> int:
        return self.wake_up_hour if self.morning_brief_hour == -1 else self.morning_brief_hour

    @property
    def effective_morning_minute(self) -> int:
        return self.wake_up_minute if self.morning_brief_minute == -1 else self.morning_brief_minute

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
