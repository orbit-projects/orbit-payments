# Operations

Configure provider clients during application startup and close them during shutdown. Keep network
timeouts finite, cap concurrent provider operations, and monitor sanitized failure categories and
latency without recording payment credentials or cardholder data.

Provider adapters are SDK clients and signature verifiers, not Core middleware or webhook
controllers. `PaymentWebhookIngress` connects signature verification to Orbit's neutral
`WorkPublisher`; install a durable adapter such as `orbit-workers-rabbitmq` for broker acceptance.
The application owns its route, database schema, worker handler, business retries, and side effects.
See [durable webhook processing](webhook-processing.md) before accepting production events.

Reconcile ambiguous network outcomes against the provider before retrying a create or refund
operation. Adapter documentation describes where provider-native idempotency is supported.

Sandbox checks are required before release. This repository has no production credentials and does
not claim live provider acceptance.
