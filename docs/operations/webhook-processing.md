# Payment webhook processing

Orbit's payment flow separates provider verification, durable acceptance, and application-owned
business processing:

```text
Provider → NGINX Gateway Fabric → Orbit Core app route
        → PaymentWebhookIngress → provider signature verification
        → confirmed RabbitMQ quorum queue → 2xx response
        → separate orbit-workers process → application database transaction
```

The payment capability and provider SDK adapters do not register HTTP routes or define application
payment tables. `PaymentWebhookIngress` performs bounded signature verification and publication.
The host application owns routes and maps errors to HTTP statuses. `orbit-workers-rabbitmq` provides
the confirmed publisher and queue adapter; `orbit-workers` provides bounded at-least-once handler
execution.

## Request process

1. Route the endpoint over HTTPS. Enforce a small request-body limit at the edge and preserve the
   exact raw body. Do not parse and reserialize before verification.
2. Select the provider adapter and account scope from trusted application configuration. Do not
   trust an account identifier supplied by an untrusted header or body field.
3. Pass raw bytes and the provider signature header to `PaymentWebhookIngress.accept()`.
4. Return a success status only after `accept()` returns. With the RabbitMQ adapter, this waits for
   mandatory routing and a publisher confirm for a persistent message in a durable quorum queue. A
   publication failure or ambiguous timeout must produce a retryable non-2xx response.
5. Map signature/payload errors to a client error without exposing internal exception text. Map
   `PaymentWebhookDeliveryError` to a retryable server failure. Never acknowledge first and enqueue
   in an untracked in-process background task.

The ingress contract caps raw bodies at 700 KiB so the base64 JSON envelope remains below the
worker message limit. Configure the NGINX request-body limit and application route policy to match.
Requests above the cap are rejected before SDK verification.

Create one queue adapter per process from operator-managed configuration. In the HTTP process, add
its optional Core lifecycle plugin so startup checks broker access and shutdown closes the connection.
The ingress can then publish through the same adapter:

```python
import os

from orbit_payments import PaymentWebhookIngress
from orbit_workers_rabbitmq import RabbitMQWorkQueue, RabbitMQWorkQueueConfig
from orbit_workers_rabbitmq.plugin import RabbitMQWorkQueuePlugin

queue = RabbitMQWorkQueue(
    RabbitMQWorkQueueConfig(
        url=os.environ["ORBIT_RABBITMQ_URL"],
        queue="payments.webhooks",
        dead_letter_exchange="payments.webhooks.dead",
        quorum_initial_group_size=3,
    )
)
app.register_plugin(RabbitMQWorkQueuePlugin(queue))
ingress = PaymentWebhookIngress(
    configured_payment_provider,
    queue,
    queue="payments.webhooks",
    account_id="configured-merchant-account",
)
```

Use a distinct, least-privilege RabbitMQ credential for the HTTP and consumer deployments where
the broker permissions allow it. Do not place credentials in source or ordinary application
configuration files.

`PaymentWebhookIngress` is framework-neutral. Register a small Orbit Core handler for each enabled
provider route; it should read `request.body` and exactly one expected signature header, call the
ingress, and return an empty 202 response after durable publication. Core's general body ceiling is
not the payment-specific limit, so the handler/edge must use the narrower ingress limit.

```python
from orbit.asgi import Request, Response
from orbit_payments import PaymentWebhookDeliveryError, PaymentWebhookError


def make_stripe_webhook_handler(ingress):
    async def handle(request: Request) -> Response:
        signatures = request.headers.getall("stripe-signature")
        if len(signatures) != 1:
            return Response(status=400)
        try:
            await ingress.accept(request.body, signatures[0])
        except PaymentWebhookError:
            return Response(status=400)
        except PaymentWebhookDeliveryError:
            return Response(status=503)
        return Response(status=202)

    return handle
```

Register the returned handler with the application's `Router` at the configured webhook path. The
Razorpay route uses its own `x-razorpay-signature` header and a separately configured adapter.

## Worker process

Run a separately deployed worker process with `PaymentWebhookWorker` and the same queue name. The
worker validates the envelope identity before calling the application handler. Treat `raw_body` as
sensitive and do not log it. A confirmed publication proves broker acceptance, not business
completion.

```python
from orbit_payments import PaymentWebhookWorker, WebhookEnvelope
from orbit_workers import RetryPolicy


async def process_payment_event(event: WebhookEnvelope) -> None:
    # In one SQL transaction: insert (provider, account_id, event_id) under a unique constraint,
    # then apply the order/payment state transition. Put external effects in a transactional outbox.
    ...


worker = PaymentWebhookWorker(
    rabbitmq_queue,
    process_payment_event,
    queue_name="payments.webhooks",
    workers=8,
    retry_policy=RetryPolicy(max_attempts=8, initial_delay=0.5, max_delay=30),
)

async with rabbitmq_queue:
    await worker.run()
```

The application handler must commit event identity and order/payment state in one database
transaction, with a unique constraint on `(provider, account_id, event_id)`. Duplicate deliveries
should become no-ops. Handle out-of-order events against authoritative provider state and the
application's payment state machine. Write an outbox record in the same transaction for effects
such as fulfillment or email, then deliver those effects idempotently.

`QueueWorker` retries handler exceptions with bounded backoff. Retry publication is confirmed before
the old RabbitMQ delivery is acknowledged. Process crashes or lost acknowledgements can cause
duplicates, so processing remains at least once. After the configured attempt limit, rejects route to
the adapter's durable `<queue>.dead` quorum queue. Alert on its depth, preserve evidence safely, and
document an operator-controlled replay process.

## Broker and database requirements

Use a RabbitMQ cluster configured for quorum queues with persistent storage. The adapter declares
quorum queues and enables at-least-once dead-lettering. Three queue members across separate nodes is
the practical minimum for tolerating one node failure; set `quorum_initial_group_size` to match the
actual cluster. A single-node value is suitable only for local development and does not provide node
fault tolerance. Publisher confirms protect the request-to-broker handoff; they do not make the
database transaction and broker one atomic transaction.

Use a supported SQL adapter for application payment/order state and idempotency constraints. Orbit
does not impose provider-specific schema. Broker publication happens before the business database
transaction, which is safe because the queue retains the verified event until a worker completes or
dead-letters it. Events that cannot be durably published are not acknowledged to the provider.

## Validation before live payments

Exercise provider test-mode signatures and delivery retries. Run integration tests against the
intended RabbitMQ cluster and database for broker restart, lost publisher confirmation, process
termination before and after consumer commit, duplicate and out-of-order delivery, database outage,
full dead-letter queue, poison messages, and replay. Validate TLS, broker quorum membership, disk
alarms, queue depth alerts, credential rotation, and backup/recovery. Unit tests and YAML shape
checks do not establish those deployment guarantees.
