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
"""Provider-neutral, sanitized payment errors."""


class PaymentError(Exception):
    """Base class for safe payment capability errors."""


class PaymentConfigurationError(PaymentError, ValueError):
    """Adapter configuration or provider-bound request settings are invalid."""


class PaymentOperationError(PaymentError):
    """A provider operation failed; the public message must not contain secret data."""


class PaymentWebhookError(PaymentError, ValueError):
    """Webhook signature or payload validation failed."""


class PaymentWebhookDeliveryError(PaymentError):
    """A verified webhook could not be durably published for processing."""


__all__ = [
    "PaymentConfigurationError",
    "PaymentError",
    "PaymentOperationError",
    "PaymentWebhookError",
]
