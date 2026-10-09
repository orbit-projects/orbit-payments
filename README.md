# Orbit Payments

`orbit-payments` defines provider-neutral asynchronous contracts for payment creation, status
lookup, refunds, and verified webhook metadata. Provider SDKs, credentials, and network transports
belong in `orbit-payments-stripe` and `orbit-payments-razorpay`.

```bash
python -m pip install orbit-payments
```

```python
from orbit_payments import PaymentProvider, PaymentRequest


async def start_payment(provider: PaymentProvider, order_id: str) -> str:
    session = await provider.create_payment(
        PaymentRequest(
            amount_minor=1999,
            currency="USD",
            reference=order_id,
            metadata={"cart": "cart-42"},
        )
    )
    # Pass the provider-issued token to that provider's supported client integration.
    return session.client_token or session.provider_id
```

Amounts use integer minor units; floating point values are rejected. The capability deliberately
does not claim identical checkout UI, settlement, capture, dispute, subscription, or idempotency
behavior across providers. `PaymentSession.provider_resource` records whether the provider returned
a PaymentIntent, Order, or another resource. Verify provider webhooks and reconcile server-side
state; browser redirects are not proof of payment.

Provider adapters must never log API keys, webhook secrets, client tokens, raw webhook bodies, or
full provider responses. Do not store or transmit raw card data through Orbit. Use each provider's
hosted or tokenized payment flow and assess PCI obligations for the deployment. This package does
not itself provide a payment processor, durable webhook queue, reconciliation job, or accounting
ledger.

The Stripe and Razorpay packages are provider SDK adapters. `PaymentWebhookIngress` verifies the
original bytes through the selected adapter and publishes a bounded `WebhookEnvelope` through
Orbit's provider-neutral `WorkPublisher`. `PaymentWebhookWorker` validates the envelope and delegates
to an application handler in a separately run worker process. The application owns the HTTP route,
payment/order schema, transaction, deduplication, and business effects. Return `2xx` only after the
publisher confirms durable acceptance. See the [webhook processing guide](docs/operations/webhook-processing.md)
for the request/consumer boundary and failure semantics.

## Documentation

- [Architecture and contract](docs/architecture/overview.md)
- [Operations](docs/operations/README.md)
- [Security](docs/security/overview.md)
- [Development](docs/development/README.md)
- [Project documentation index](docs/README.md)

## Development

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
mypy
```

This package is pre-alpha, its API is not stable, and it supports Python 3.11 through 3.14.
Licensed under Apache-2.0.
