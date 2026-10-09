# Security

- Load API keys and webhook secrets from a secret manager or deployment secret injection. The
  library has no default credentials and does not persist secrets.
- Verify signatures using the exact raw webhook body before parsing it or applying business state.
- Never treat browser redirects or client-supplied payment status as authoritative.
- Do not log raw webhook payloads, provider responses, client tokens, API credentials, or payment
  details. Store only the minimum business data required by the application.
- `PaymentWebhookIngress` places the exact verified body in the work message. Protect RabbitMQ
  storage, credentials, backups, dead-letter queues, retention, and operator replay access as
  sensitive payment data; never place secrets or card data in the envelope.
- Keep payment creation and refund operations behind application authorization and audit controls.
- Use provider-hosted or tokenized payment collection. Orbit does not handle raw card numbers and
  does not establish PCI compliance for an application.

Report security issues using the instructions in the repository [security policy](../../SECURITY.md).
