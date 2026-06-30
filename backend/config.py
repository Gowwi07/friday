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

    # Gemini AI
    gemini_api_key: str = ""

    # Twilio Configuration
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = "whatsapp:+14155238886"

    # Your personal WhatsApp number (where FRIDAY sends reminders)
    # Format: whatsapp:+919876543210
    my_whatsapp_number: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./friday.db"

    # Scheduler
    morning_brief_hour: int = 7
    morning_brief_minute: int = 0
    night_summary_hour: int = 22
    night_summary_minute: int = 0

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
