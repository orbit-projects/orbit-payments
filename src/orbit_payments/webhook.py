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
"""Provider-neutral webhook verification and durable queue handoff."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Awaitable, Callable

from orbit_workers import (
    QueueWorker,
    RetryPolicy,
    WorkFailureHandler,
    WorkMessage,
    WorkPublisher,
    WorkQueue,
)

from orbit_payments.contracts import PaymentProvider, VerifiedWebhook, WebhookEnvelope
from orbit_payments.errors import PaymentWebhookDeliveryError, PaymentWebhookError

_MAX_RAW_BODY_BYTES = 716_800  # Base64 JSON encoding stays below WorkMessage's 1 MiB limit.
PaymentWebhookHandler = Callable[[WebhookEnvelope], Awaitable[None]]


def _message_id(envelope: WebhookEnvelope) -> str:
    """Derive a stable, non-sensitive broker ID from provider/account/event identity."""
    identity = f"{envelope.provider}\0{envelope.account_id}\0{envelope.event_id}"
    return "payment-" + hashlib.sha256(identity.encode()).hexdigest()


class PaymentWebhookIngress:
    """Verify exact provider bytes and publish a durable work message before returning.

    The application owns the HTTP route and supplies an account scope from trusted configuration,
    not from a client-controlled header. ``publisher.publish`` must return only after the backend
    confirms durable acceptance. Duplicate deliveries are expected and must be idempotent in the
    consumer.
    """

    def __init__(
        self,
        provider: PaymentProvider,
        publisher: WorkPublisher,
        *,
        queue: str,
        account_id: str,
    ) -> None:
        """Bind one provider/account route to a caller-owned durable work publisher."""
        if not isinstance(provider, PaymentProvider):
            raise TypeError("provider must implement the Orbit PaymentProvider contract.")
        if not isinstance(publisher, WorkPublisher):
            raise TypeError("publisher must implement the Orbit WorkPublisher contract.")
        if not isinstance(queue, str) or not queue:
            raise ValueError("queue must be a nonempty queue name.")
        if not isinstance(account_id, str) or not account_id:
            raise ValueError("account_id must be a nonempty trusted account scope.")
        self._provider = provider
        self._publisher = publisher
        self._queue = queue
        self._account_id = account_id

    async def accept(self, raw_body: bytes, signature: str) -> VerifiedWebhook:
        """Verify a bounded raw body, await durable publication, and return verified metadata.

        Raises ``PaymentWebhookError`` for untrusted/invalid provider input and
        ``PaymentWebhookDeliveryError`` if the durable handoff fails. HTTP handlers should map the
        former to a client error and the latter to a retryable server error; never return 2xx for a
        failed or ambiguous publication.
        """
        if not isinstance(raw_body, bytes) or not raw_body or len(raw_body) > _MAX_RAW_BODY_BYTES:
            raise PaymentWebhookError("Webhook body is invalid or exceeds the configured limit.")
        if not isinstance(signature, str) or not signature:
            raise PaymentWebhookError("Webhook signature is missing or invalid.")
        try:
            verified = self._provider.verify_webhook(raw_body, signature)
        except asyncio.CancelledError:
            raise
        if not isinstance(verified, VerifiedWebhook):
            raise PaymentWebhookError("Payment provider returned invalid verified event metadata.")
        if verified.event_id is None:
            raise PaymentWebhookError("Verified webhook has no stable event identity.")
        envelope = WebhookEnvelope(
            provider=verified.provider,
            account_id=self._account_id,
            event_id=verified.event_id,
            event_type=verified.event_type,
            payment_id=verified.payment_id,
            occurred_at=verified.occurred_at,
            raw_body=raw_body,
        )
        payload = envelope.model_dump_json().encode("utf-8")
        message = WorkMessage(
            queue=self._queue,
            message_id=_message_id(envelope),
            payload=payload,
            headers={
                "provider": envelope.provider,
                "account": envelope.account_id,
                "event-type": envelope.event_type,
            },
        )
        try:
            await self._publisher.publish(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise PaymentWebhookDeliveryError(
                "Verified webhook could not be durably accepted for processing."
            ) from None
        return verified


class PaymentWebhookWorker:
    """Decode verified payment envelopes and run app-owned handlers with bounded retries.

    Run this worker in a separate process/deployment from the HTTP application when workload
    isolation is required. The callback owns database transactions, event deduplication, payment
    state transitions, and any outbox writes.
    """

    def __init__(
        self,
        queue: WorkQueue,
        handler: PaymentWebhookHandler,
        *,
        queue_name: str,
        workers: int = 4,
        retry_policy: RetryPolicy | None = None,
        on_failure: WorkFailureHandler | None = None,
    ) -> None:
        """Bind an application handler to one payment-webhook queue."""
        if not isinstance(queue, WorkQueue):
            raise TypeError("queue must implement the Orbit WorkQueue contract.")
        if not callable(handler) or not (
            inspect.iscoroutinefunction(handler)
            or inspect.iscoroutinefunction(type(handler).__call__)
        ):
            raise TypeError("handler must be an async payment webhook callback.")
        if not isinstance(queue_name, str) or not queue_name:
            raise ValueError("queue_name must be a nonempty queue name.")
        self._queue_name = queue_name
        self._handler = handler
        self._runner = QueueWorker(
            queue,
            self._handle_message,
            workers=workers,
            retry_policy=retry_policy,
            on_failure=on_failure,
        )

    async def run(self) -> None:
        """Run until cancellation or a queue/settlement failure stops the worker group."""
        await self._runner.run()

    async def _handle_message(self, message: WorkMessage) -> None:
        """Validate internal envelope identity before invoking application business logic."""
        try:
            envelope = WebhookEnvelope.model_validate_json(message.payload)
        except Exception:
            raise ValueError("Invalid verified payment webhook envelope.") from None
        if (
            message.queue != self._queue_name
            or message.message_id != _message_id(envelope)
            or message.headers.get("provider") != envelope.provider
            or message.headers.get("account") != envelope.account_id
            or message.headers.get("event-type") != envelope.event_type
        ):
            raise ValueError("Payment webhook message identity does not match its envelope.")
        await self._handler(envelope)


__all__ = ["PaymentWebhookHandler", "PaymentWebhookIngress", "PaymentWebhookWorker"]
