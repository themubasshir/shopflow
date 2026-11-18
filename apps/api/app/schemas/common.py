from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: dict[str, Any] = {}


class HealthResponse(BaseModel):
    status: str
    database: str
    environment: str
    version: str


class Paginated[T](ORMModel):
    items: list[T]
    total: int
    limit: int
    offset: int
