# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Provider-neutral payment models and asynchronous adapter contract."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_serializer,
    field_validator,
)

_MAX_METADATA_ITEMS = 14
_MAX_TEXT = 256


class PaymentStatus(StrEnum):
    """Normalized lifecycle states shared by supported payment providers."""

    CREATED = "created"
    REQUIRES_ACTION = "requires_action"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RefundStatus(StrEnum):
    """Normalized refund states; providers may expose more detailed states."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


def _safe_text(value: str, label: str, maximum: int = _MAX_TEXT) -> str:
    """Reject empty, oversized, or control-bearing provider-bound identifiers."""
    if (
        not value
        or len(value) > maximum
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(f"{label} must be nonempty bounded text without control characters.")
    return value


class PaymentRequest(BaseModel):
    """Provider-neutral request to create one payment attempt.

    Amounts are integer minor units (for example, paise or cents); floating point amounts are
    intentionally excluded. ``reference`` should be a stable merchant order identifier.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    amount_minor: StrictInt = Field(gt=0, le=10**12)
    currency: StrictStr = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    reference: StrictStr = Field(min_length=1, max_length=40)
    metadata: Mapping[StrictStr, StrictStr] = Field(default_factory=dict)

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        return _safe_text(value, "Payment reference", 40)

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping) or len(value) > _MAX_METADATA_ITEMS:
            raise ValueError("Payment metadata must have at most 14 entries.")
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise ValueError("Payment metadata keys and values must be strings.")
            _safe_text(key, "Metadata key")
            _safe_text(item, "Metadata value")
            normalized[key] = item
        return normalized

    def model_post_init(self, __context: object) -> None:
        """Prevent callers from mutating validated provider-bound metadata."""
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @field_serializer("metadata")
    def serialize_metadata(self, value: Mapping[str, str]) -> dict[str, str]:
        """Keep JSON-compatible model dumps while exposing immutable metadata."""
        return dict(value)


class PaymentSession(BaseModel):
    """Created or retrieved payment resource with provider-specific continuation token."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider: StrictStr = Field(min_length=1, max_length=64)
    provider_id: StrictStr = Field(min_length=1, max_length=255)
    provider_resource: StrictStr = Field(min_length=1, max_length=64)
    reference: StrictStr | None = Field(default=None, max_length=40)
    amount_minor: StrictInt = Field(ge=0, le=10**12)
    currency: StrictStr = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    status: PaymentStatus
    client_token: StrictStr | None = Field(default=None, max_length=1024)
    created_at: datetime | None = None

    @field_validator("provider", "provider_id", "provider_resource")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _safe_text(value, "Payment provider identifier", 255)

    @field_validator("reference", "client_token")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        return _safe_text(value, "Payment value", 1024) if value is not None else None

    @field_validator("created_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Payment timestamps must include timezone information.")
        return value


class RefundRequest(BaseModel):
    """Request a full or partial refund against a provider payment identifier."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    payment_id: StrictStr = Field(min_length=1, max_length=255)
    reference: StrictStr = Field(min_length=1, max_length=40)
    amount_minor: StrictInt | None = Field(default=None, gt=0, le=10**12)

    @field_validator("payment_id")
    @classmethod
    def validate_payment_id(cls, value: str) -> str:
        return _safe_text(value, "Payment ID", 255)

    @field_validator("reference")
    @classmethod
    def validate_refund_reference(cls, value: str) -> str:
        return _safe_text(value, "Refund reference", 40)


class RefundResult(BaseModel):
    """Normalized result from a refund request."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider: StrictStr = Field(min_length=1, max_length=64)
    provider_id: StrictStr = Field(min_length=1, max_length=255)
    payment_id: StrictStr = Field(min_length=1, max_length=255)
    amount_minor: StrictInt = Field(gt=0, le=10**12)
    currency: StrictStr = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    status: RefundStatus = RefundStatus.PENDING


class VerifiedWebhook(BaseModel):
    """Authenticity-verified event metadata; raw provider payloads are not logged or retained."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider: StrictStr = Field(min_length=1, max_length=64)
    event_id: StrictStr | None = Field(default=None, max_length=255)
    event_type: StrictStr = Field(min_length=1, max_length=255)
    payment_id: StrictStr | None = Field(default=None, max_length=255)
    occurred_at: datetime | None = None

    @field_validator("provider", "event_type")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _safe_text(value, "Webhook identifier", 255)

    @field_validator("event_id", "payment_id")
    @classmethod
    def validate_optional_ids(cls, value: str | None) -> str | None:
        return _safe_text(value, "Webhook ID", 255) if value is not None else None

    @field_validator("occurred_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Webhook timestamps must include timezone information.")
        return value


class WebhookEnvelope(BaseModel):
    """Verified event plus exact provider bytes for a separately running consumer."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    provider: StrictStr = Field(min_length=1, max_length=64)
    account_id: StrictStr = Field(min_length=1, max_length=128)
    event_id: StrictStr = Field(min_length=1, max_length=255)
    event_type: StrictStr = Field(min_length=1, max_length=255)
    payment_id: StrictStr | None = Field(default=None, max_length=255)
    occurred_at: datetime | None = None
    raw_body: bytes = Field(repr=False, min_length=1, max_length=716_800)

    @field_validator("provider", "account_id", "event_id", "event_type")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _safe_text(value, "Webhook envelope identifier", 255)

    @field_validator("payment_id")
    @classmethod
    def validate_payment_id(cls, value: str | None) -> str | None:
        return _safe_text(value, "Webhook payment ID", 255) if value is not None else None

    @field_validator("occurred_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Webhook timestamps must include timezone information.")
        return value

    @field_validator("raw_body")
    @classmethod
    def validate_raw_body(cls, value: bytes) -> bytes:
        if not isinstance(value, bytes) or not value:
            raise ValueError("Webhook raw_body must contain nonempty bytes.")
        return value


@runtime_checkable
class PaymentProvider(Protocol):
    """Async payment capability implemented by provider adapter packages."""

    async def create_payment(self, request: PaymentRequest) -> PaymentSession:
        """Create a provider payment resource, using a stable reference where supported."""

    async def get_payment(self, provider_id: str) -> PaymentSession:
        """Retrieve the provider payment resource by its provider-issued identifier."""

    async def refund(self, request: RefundRequest) -> RefundResult:
        """Create a provider refund; availability and idempotency semantics vary by provider."""

    def verify_webhook(self, raw_body: bytes, signature: str) -> VerifiedWebhook:
        """Verify a webhook using the exact raw body and configured webhook secret."""

    async def aclose(self) -> None:
        """Release provider client resources owned by the adapter."""


__all__ = [
    "PaymentProvider",
    "PaymentRequest",
    "PaymentSession",
    "PaymentStatus",
    "RefundRequest",
    "RefundResult",
    "RefundStatus",
    "VerifiedWebhook",
    "WebhookEnvelope",
]
