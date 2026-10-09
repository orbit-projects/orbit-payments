# Orbit Payments: architecture and boundaries

`orbit-payments` owns the shared payment models, errors, and `PaymentProvider` protocol. Provider
adapters own vendor SDKs, credentials, webhook verification, transport configuration, retries,
resource cleanup, and provider-specific behavior.

```text
Orbit application
└── orbit-payments: PaymentProvider contract
    ├── orbit-payments-stripe: Stripe PaymentIntent adapter
    └── orbit-payments-razorpay: Razorpay Orders adapter
```

The capability package has no Core dependency and no provider SDK. It exposes the framework-neutral
`PaymentWebhookIngress`, which depends on `orbit-workers`' generic `WorkPublisher` contract.
Applications can inject provider implementations directly or bind them through Orbit Core
composition. Provider adapters depend on this contract; this package never depends on adapters.

## Shared semantics

- Amounts are positive integer minor units and currencies are three uppercase letters.
- `reference` is a stable merchant-owned identifier used for reconciliation. Stripe maps it to an
  idempotency key and metadata; Razorpay maps it to its order receipt and notes. The capability
  cannot promise exactly-once behavior across providers.
- `client_token` carries the provider-specific value needed by a supported client flow (for
  example, a Stripe client secret or Razorpay order ID). `provider_resource` preserves resource
  differences rather than pretending the vendors return an identical checkout object.
- Webhook verification requires raw request bytes and a signature. The adapter returns normalized
  event identity; ingress publishes that identity and exact body before the HTTP route acknowledges
  the provider. The application owns event deduplication and payment/order state transactions.

## Scope limits

The capability covers payment creation, lookup, refunds, webhook verification, and publication
through a selected `WorkPublisher`. It does not
standardize subscriptions, payment methods, customer vaults, disputes, payouts, settlement,
reconciliation, or a multi-provider routing policy. Provider-specific extensions remain available
through the adapter's documented client surface when needed.
