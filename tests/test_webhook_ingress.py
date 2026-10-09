from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

import pytest
from orbit_workers import WorkDelivery, WorkMessage

from orbit_payments import (
    PaymentWebhookDeliveryError,
    PaymentWebhookError,
    PaymentWebhookIngress,
    PaymentWebhookWorker,
    VerifiedWebhook,
    WebhookEnvelope,
)


class _Provider:
    def __init__(self, event: VerifiedWebhook | None = None) -> None:
        self.event = event or VerifiedWebhook(
            provider="stripe",
            event_id="evt_123",
            event_type="payment_intent.succeeded",
            payment_id="pi_123",
            occurred_at=datetime.now(UTC),
        )
        self.received: tuple[bytes, str] | None = None

    def verify_webhook(self, raw_body: bytes, signature: str) -> VerifiedWebhook:
        self.received = (raw_body, signature)
        return self.event

    async def create_payment(self, request: object) -> object:
        raise NotImplementedError

    async def get_payment(self, provider_id: str) -> object:
        raise NotImplementedError

    async def refund(self, request: object) -> object:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class _Publisher:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.messages: list[WorkMessage] = []

    async def publish(self, message: WorkMessage) -> None:
        if self.error is not None:
            raise self.error
        self.messages.append(message)


class _Delivery(WorkDelivery):
    def __init__(self, message: WorkMessage) -> None:
        self._message = message
        self._attempt = 1
        self.acked = False

    @property
    def message(self) -> WorkMessage:
        return self._message

    @property
    def attempt(self) -> int:
        return self._attempt

    async def ack(self) -> None:
        self.acked = True

    async def retry(self, delay: float) -> None:
        raise AssertionError("successful handler should not retry")

    async def reject(self) -> None:
        raise AssertionError("successful handler should not reject")


class _WorkQueue:
    def __init__(self, delivery: _Delivery) -> None:
        self.delivery = delivery
        self.received = False

    async def receive(self, *, timeout: float) -> WorkDelivery | None:
        if not self.received:
            self.received = True
            return self.delivery
        await asyncio.Future()


@pytest.mark.asyncio
async def test_ingress_verifies_raw_bytes_and_publishes_original_envelope() -> None:
    raw_body = b'{"event":"payment_intent.succeeded"}'
    provider = _Provider()
    publisher = _Publisher()
    ingress = PaymentWebhookIngress(
        provider,
        publisher,
        queue="payments.webhooks",
        account_id="merchant-a",
    )

    event = await ingress.accept(raw_body, "signature")

    assert event.event_id == "evt_123"
    assert provider.received == (raw_body, "signature")
    message = publisher.messages[0]
    assert message.queue == "payments.webhooks"
    assert message.headers["provider"] == "stripe"
    envelope = WebhookEnvelope.model_validate_json(message.payload)
    assert envelope.account_id == "merchant-a"
    assert envelope.raw_body == raw_body
    assert envelope.event_id == "evt_123"


@pytest.mark.asyncio
async def test_ingress_derives_deterministic_message_id_from_scoped_identity() -> None:
    first = _Publisher()
    second = _Publisher()
    ingress_a = PaymentWebhookIngress(
        _Provider(), first, queue="payments.webhooks", account_id="merchant-a"
    )
    ingress_b = PaymentWebhookIngress(
        _Provider(), second, queue="payments.webhooks", account_id="merchant-a"
    )

    await ingress_a.accept(b"{}", "signature")
    await ingress_b.accept(b"{}", "signature")

    assert first.messages[0].message_id == second.messages[0].message_id
    assert first.messages[0].message_id.startswith("payment-")


@pytest.mark.asyncio
async def test_ingress_never_accepts_event_without_stable_identity() -> None:
    provider = _Provider(
        VerifiedWebhook(provider="razorpay", event_id=None, event_type="payment.captured")
    )
    publisher = _Publisher()
    ingress = PaymentWebhookIngress(
        provider, publisher, queue="payments.webhooks", account_id="merchant-a"
    )

    with pytest.raises(PaymentWebhookError, match="stable event identity"):
        await ingress.accept(b"{}", "signature")
    assert publisher.messages == []


@pytest.mark.asyncio
async def test_ingress_maps_publisher_failure_to_retryable_delivery_error() -> None:
    ingress = PaymentWebhookIngress(
        _Provider(),
        _Publisher(error=RuntimeError("secret broker detail")),
        queue="payments.webhooks",
        account_id="merchant-a",
    )

    with pytest.raises(PaymentWebhookDeliveryError) as error:
        await ingress.accept(b"{}", "signature")
    assert "secret broker detail" not in str(error.value)


@pytest.mark.asyncio
async def test_ingress_rejects_oversized_body_before_provider_or_broker() -> None:
    provider = _Provider()
    publisher = _Publisher()
    ingress = PaymentWebhookIngress(
        provider, publisher, queue="payments.webhooks", account_id="merchant-a"
    )

    with pytest.raises(PaymentWebhookError, match="configured limit"):
        await ingress.accept(b"x" * 716_801, "signature")
    assert provider.received is None
    assert publisher.messages == []


@pytest.mark.asyncio
async def test_payment_worker_validates_envelope_and_delegates_to_app_handler() -> None:
    envelope = WebhookEnvelope(
        provider="stripe",
        account_id="merchant-a",
        event_id="evt_123",
        event_type="payment_intent.succeeded",
        raw_body=b'{"event":"payment_intent.succeeded"}',
    )
    identity = f"{envelope.provider}\0{envelope.account_id}\0{envelope.event_id}"
    message = WorkMessage(
        queue="payments.webhooks",
        message_id="payment-" + hashlib.sha256(identity.encode()).hexdigest(),
        payload=envelope.model_dump_json().encode(),
        headers={
            "provider": envelope.provider,
            "account": envelope.account_id,
            "event-type": envelope.event_type,
        },
    )
    delivery = _Delivery(message)
    queue = _WorkQueue(delivery)
    processed = asyncio.Event()
    seen: list[WebhookEnvelope] = []

    async def handle(event: WebhookEnvelope) -> None:
        seen.append(event)
        processed.set()

    worker = PaymentWebhookWorker(queue, handle, queue_name="payments.webhooks")
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(processed.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert delivery.acked is True
    assert seen == [envelope]
