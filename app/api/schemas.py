"""HTTP request/response shapes.

Pydantic lives only here — this is the one place untrusted JSON enters.
Everything inward of this module speaks dataclasses.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["naive", "tiered"]


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str = Field(min_length=1, max_length=4000)
    mode: Mode = "tiered"


class InspectRequest(BaseModel):
    user_id: str
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = "inspect"


class AblationRequest(BaseModel):
    user_id: str
    memory_ids: list[str] | None = None
    sample: int = 12
