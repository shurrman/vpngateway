"""Common API models."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel


class ApiResponse(BaseModel):
    status: str = "ok"
    data: Any = None
    error: str | None = None
    log: str | None = None
    timestamp: datetime = None

    def __init__(self, **kwargs):
        if "timestamp" not in kwargs or kwargs["timestamp"] is None:
            kwargs["timestamp"] = datetime.now(timezone.utc)
        super().__init__(**kwargs)


def ok(data: Any = None, log: str | None = None) -> dict:
    return ApiResponse(status="ok", data=data, log=log).model_dump()


def error(message: str, data: Any = None) -> dict:
    return ApiResponse(status="error", error=message, data=data).model_dump()
