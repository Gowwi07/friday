"""
FRIDAY — SQLAlchemy Database Models

Tables:
  - events           : Tasks/events extracted from messages
  - reminder_plans   : Scheduled reminder entries per event
  - reminder_history : Log of sent reminders
  - messages         : All raw incoming messages
  - conversation_memory : AI conversation context
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Integer,
    ForeignKey, Enum, Float
)
from sqlalchemy.orm import relationship, DeclarativeBase


def _uuid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ─── Enums ────────────────────────────────────────────────────────────────────

class EventStatus(str, PyEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SNOOZED = "snoozed"
    EXPIRED = "expired"


class EventCategory(str, PyEnum):
    PLACEMENT = "Placement"
    COLLEGE = "College"
    ASSIGNMENT = "Assignment"
    INTERNSHIP = "Internship"
    INTERVIEW = "Interview"
    PERSONAL = "Personal"
    HEALTH = "Health"
    SHOPPING = "Shopping"
    BILL = "Bill"
    SUBSCRIPTION = "Subscription"
    FINANCE = "Finance"
    TRAVEL = "Travel"
    FAMILY = "Family"
    MISCELLANEOUS = "Miscellaneous"


class EventPriority(str, PyEnum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class ReminderStatus(str, PyEnum):
    PENDING = "pending"
    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


class MessageType(str, PyEnum):
    CHAT = "chat"
    IMAGE = "image"
    DOCUMENT = "document"
    AUDIO = "audio"
    VIDEO = "video"
    STICKER = "sticker"
    OTHER = "other"


# ─── Models ───────────────────────────────────────────────────────────────────

class Event(Base):
    """
    Represents a task, deadline, or event extracted from a WhatsApp message.
    """
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(Enum(EventCategory), default=EventCategory.MISCELLANEOUS)
    priority = Column(Enum(EventPriority), default=EventPriority.MEDIUM)

    # Timing
    event_datetime = Column(DateTime, nullable=True)   # When the event occurs
    deadline = Column(DateTime, nullable=True)          # Submission/payment deadline
    is_recurring = Column(Boolean, default=False)
    recurrence_rule = Column(String, nullable=True)     # e.g. "weekly:monday"

    # Details
    venue = Column(String(500), nullable=True)
    link = Column(Text, nullable=True)
    contact = Column(String(500), nullable=True)
    estimated_effort_hours = Column(Float, nullable=True)

    # State
    status = Column(Enum(EventStatus), default=EventStatus.ACTIVE)
    source_message = Column(Text, nullable=True)        # Original forwarded text
    user_phone = Column(String(50), nullable=True)      # Who sent this

    # AI metadata
    ai_confidence = Column(Float, nullable=True)        # 0.0 – 1.0
    ai_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    reminder_plans = relationship("ReminderPlan", back_populates="event", cascade="all, delete-orphan")
    reminder_history = relationship("ReminderHistory", back_populates="event", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Event id={self.id[:8]} title='{self.title}' status={self.status}>"


class ReminderPlan(Base):
    """
    A single scheduled reminder for an event.
    The scheduler checks this table every minute.
    """
    __tablename__ = "reminder_plans"

    id = Column(String, primary_key=True, default=_uuid)
    event_id = Column(String, ForeignKey("events.id"), nullable=False)

    scheduled_at = Column(DateTime, nullable=False)     # When to send
    reminder_type = Column(String(100), nullable=False) # e.g. "1d_before", "morning_of", "follow_up"
    message_template = Column(Text, nullable=True)      # Pre-built message text
    status = Column(Enum(ReminderStatus), default=ReminderStatus.PENDING)

    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    event = relationship("Event", back_populates="reminder_plans")

    def __repr__(self):
        return f"<ReminderPlan id={self.id[:8]} type={self.reminder_type} at={self.scheduled_at}>"


class ReminderHistory(Base):
    """
    Log of every reminder message actually sent to the user.
    """
    __tablename__ = "reminder_history"

    id = Column(String, primary_key=True, default=_uuid)
    event_id = Column(String, ForeignKey("events.id"), nullable=False)
    message_sent = Column(Text, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    user_response = Column(Text, nullable=True)     # What user replied
    response_at = Column(DateTime, nullable=True)

    event = relationship("Event", back_populates="reminder_history")


class IncomingMessage(Base):
    """
    Raw log of every WhatsApp message received.
    Used for auditing and context retrieval.
    """
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=_uuid)
    whatsapp_msg_id = Column(String, unique=True, nullable=True)
    from_number = Column(String(50), nullable=False)
    from_name = Column(String(200), nullable=True)
    body = Column(Text, nullable=True)
    message_type = Column(Enum(MessageType), default=MessageType.CHAT)
    is_forwarded = Column(Boolean, default=False)
    has_media = Column(Boolean, default=False)
    media_mimetype = Column(String(100), nullable=True)
    media_filename = Column(String(500), nullable=True)

    # AI processing result
    intent = Column(String(50), nullable=True)      # "create_event", "complete_task", etc.
    processed = Column(Boolean, default=False)
    linked_event_id = Column(String, ForeignKey("events.id"), nullable=True)

    timestamp = Column(DateTime, nullable=True)
    received_at = Column(DateTime, default=datetime.utcnow)


class ConversationMemory(Base):
    """
    Short-term conversation context. Sent to Gemini with each new message
    so the AI can understand references like "Actually make it 11."
    """
    __tablename__ = "conversation_memory"

    id = Column(String, primary_key=True, default=_uuid)
    role = Column(String(20), nullable=False)        # "user" or "assistant"
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    linked_event_id = Column(String, nullable=True)  # Which event this relates to
