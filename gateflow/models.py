from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator


def normalise_prefix(prefix: str) -> str:
    """Strip leading/trailing slashes and collapse multiple slashes."""
    stripped = prefix.strip("/")
    if not stripped:
        raise ValueError("Route prefix cannot be empty")
    if ".." in stripped:
        raise ValueError("Route prefix cannot contain '..'")
    return re.sub(r"/+", "/", stripped)


class APIKeyRecord(BaseModel):
    user_id: str
    tier: str
    active: int = Field(..., ge=0, le=1)
    expires_at: int | None = Field(default=None)
    rate_limit_custom: int = Field(default=-1)
    rate_limit_custom_refill: int | None = Field(default=None)
    request_count_lifetime: int = Field(default=0)
    # Comma-separated list of allowed IPs or CIDRs. Empty or "*" allows all.
    allowed_ips: str = Field(default="")

    @field_validator(
        "active",
        "expires_at",
        "rate_limit_custom",
        "rate_limit_custom_refill",
        "request_count_lifetime",
        mode="before",
    )
    @classmethod
    def _coerce_int(cls, v: Any) -> int | None:
        if v is None:
            return None
        return int(v)

    def to_hash(self) -> dict[str, str]:
        """Return a Redis-hash compatible mapping with no None values."""
        data = self.model_dump()
        if data.get("expires_at") is None:
            data.pop("expires_at", None)
        return {k: str(v) for k, v in data.items() if v is not None}


class TierConfig(BaseModel):
    capacity: int
    refill_rate: float
    window_info: str = "1s"
    monthly_quota: int = -1

    @field_validator("capacity", "refill_rate", mode="before")
    @classmethod
    def _coerce_numbers(cls, v: Any, info):
        if info.field_name == "capacity":
            return int(v)
        return float(v)


@dataclass
class Route:
    prefix: str
    target_url: str
    fallback_url: str | None
    strip_prefix: bool
    requires_auth: bool
    allowed_methods: set[str]

    @classmethod
    def from_json(cls, prefix: str, raw: str) -> Route:
        data = json.loads(raw)
        methods = data["allowed_methods"]
        if methods == "*":
            allowed: set[str] = set()
        else:
            allowed = {m.strip().upper() for m in methods.split(",")}
        return cls(
            prefix=normalise_prefix(prefix),
            target_url=data["target_url"],
            fallback_url=data.get("fallback_url"),
            strip_prefix=data["strip_prefix"],
            requires_auth=data["requires_auth"],
            allowed_methods=allowed,
        )

    def to_json(self) -> str:
        methods = "*" if not self.allowed_methods else ",".join(sorted(self.allowed_methods))
        return json.dumps(
            {
                "target_url": self.target_url,
                "fallback_url": self.fallback_url,
                "strip_prefix": self.strip_prefix,
                "requires_auth": self.requires_auth,
                "allowed_methods": methods,
            }
        )

    def allows(self, method: str) -> bool:
        return not self.allowed_methods or method.upper() in self.allowed_methods
