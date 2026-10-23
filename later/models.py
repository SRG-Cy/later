from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["return_window", "warranty", "bill", "appointment", "deadline", "event_tickets", "other"]
Status = Literal["reading", "needs_info", "scheduled", "reminded", "done", "snoozed", "cancelled", "failed"]
Source = Literal["photo", "text", "voice"]


class Facts(BaseModel):
    """What the model saw. Dates are copied, never computed."""

    kind: Kind
    title: str
    action: str
    anchor_date: date | None = None
    explicit_due: datetime | date | None = None
    window_days: int | None = Field(default=None, ge=0, le=3650)
    window_months: int | None = Field(default=None, ge=0, le=120)
    org: str | None = None
    evidence: str
    confidence: float = Field(ge=0, le=1)


class Resolved(BaseModel):
    due_at: datetime
    remind_at: datetime
    late: bool


class Item(BaseModel):
    id: str
    created_at: datetime
    source: Source
    raw_text: str
    facts: Facts | None = None
    resolved: Resolved | None = None
    status: Status
