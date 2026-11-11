"""Gateway errors. Messages are always scrubbed of secrets before they are raised."""
from __future__ import annotations

from ..core.redaction import redact_text


def scrub(text: str, secret: str | None = None) -> str:
    """Remove the exact API key (any format) plus pattern-based secrets from text."""
    text = str(text)
    if secret:
        text = text.replace(secret, "[REDACTED_KEY]")
    return redact_text(text)


class GatewayError(Exception):
    def __init__(self, message: str, attempts: list[dict] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


class ProviderError(GatewayError):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class StructuredOutputError(ProviderError):
    """Model output did not parse/validate against the requested JSON schema."""


class CapabilityError(ProviderError):
    """Provider protocol does not support the requested operation."""


class NoRouteError(GatewayError):
    """No enabled model satisfies the policy."""


class ConsentRequired(GatewayError):
    """Sensitive document + non-local provider without explicit consent."""


class BudgetExceeded(GatewayError):
    pass
