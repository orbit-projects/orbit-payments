from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orbit_payments import PaymentRequest, PaymentSession, PaymentStatus


def test_payment_request_uses_integer_minor_units_and_immutable_metadata() -> None:
    request = PaymentRequest(
        amount_minor=1250,
        currency="INR",
        reference="order-1",
        metadata={"customer": "cust-1"},
    )

    with pytest.raises(TypeError):
        request.metadata["customer"] = "changed"  # type: ignore[index]
    assert request.model_dump(mode="json")["metadata"] == {"customer": "cust-1"}


@pytest.mark.parametrize("amount", [0, -1, 1.5, True])
def test_payment_request_rejects_invalid_amounts(amount: object) -> None:
    with pytest.raises(ValidationError):
        PaymentRequest(amount_minor=amount, currency="USD", reference="order-1")


def test_payment_session_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        PaymentSession(
            provider="provider",
            provider_id="id",
            provider_resource="payment",
            amount_minor=10,
            currency="USD",
            status=PaymentStatus.CREATED,
            created_at=datetime(2026, 1, 1),
        )

    valid = PaymentSession(
        provider="provider",
        provider_id="id",
        provider_resource="payment",
        amount_minor=10,
        currency="USD",
        status=PaymentStatus.CREATED,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert valid.created_at is not None and valid.created_at.utcoffset().total_seconds() == 0
