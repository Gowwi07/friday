"""
FRIDAY — Events REST API

Endpoints to view, search, and manage events.
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.database import get_db
from database.models import Event, ReminderPlan, EventStatus
from time_utils import now_ist

router = APIRouter(prefix="/events", tags=["events"])


class EventResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    category: Optional[str]
    priority: Optional[str]
    event_datetime: Optional[datetime]
    deadline: Optional[datetime]
    venue: Optional[str]
    link: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=List[EventResponse])
async def list_events(
    status: Optional[str] = Query(None, description="Filter by status"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List all events with optional filters."""
    query = select(Event).order_by(
        Event.event_datetime.asc().nullslast(),
        Event.deadline.asc().nullslast(),
        Event.created_at.desc(),
    )
    if status:
        query = query.where(Event.status == status)
    if category:
        query = query.where(Event.category == category)

    result = await db.execute(query.limit(limit))
    events = result.scalars().all()
    return events


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single event by ID."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.patch("/{event_id}/complete")
async def complete_event(event_id: str, db: AsyncSession = Depends(get_db)):
    """Mark an event as complete via REST API."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event.status = EventStatus.COMPLETED
    event.completed_at = now_ist()
    await db.commit()
    return {"status": "ok", "message": f"'{event.title}' marked complete"}


@router.delete("/{event_id}")
async def delete_event(event_id: str, db: AsyncSession = Depends(get_db)):
    """Delete an event and its reminders."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event.status = EventStatus.CANCELLED
    await db.commit()
    return {"status": "ok"}
