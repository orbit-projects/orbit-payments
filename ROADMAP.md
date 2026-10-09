# Orbit Payments roadmap

This roadmap tracks the provider-neutral contract. Provider-specific integrations live in separate
adapter repositories.

## Current scope

- Typed async payment and refund contracts.
- Integer minor-unit amounts and immutable bounded metadata.
- Normalized lifecycle states and verified webhook metadata.
- Stripe and Razorpay adapters are separate packages and remain pre-alpha.
- Provider-verified webhook ingress publishes a bounded envelope through `WorkPublisher`.

## Next work

- Validate contract ergonomics against additional provider adapters before stabilizing 1.0 APIs.
- Validate RabbitMQ ingress and worker behavior against a live broker and provider test accounts.
- Keep application-owned event deduplication, transactional order updates, and fulfillment outbox
  patterns explicit; the capability package does not impose application tables.
- Add provider conformance tests and sandbox integration tests as credentials and CI environments
  become available.

Roadmap items are proposals, not shipped features.
