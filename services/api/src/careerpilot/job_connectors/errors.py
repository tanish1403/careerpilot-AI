"""Connector error types."""
from __future__ import annotations


class ConnectorError(Exception):
    """Base class; message is safe to show to the user."""


class ConfigError(ConnectorError, ValueError):
    pass


class ConnectorHTTPError(ConnectorError):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class BlockedError(ConnectorError):
    """Login wall, CAPTCHA, robots.txt refusal or access control. We never try to bypass these."""

    def __init__(self, message: str, url: str | None = None, code: str = "blocked") -> None:
        super().__init__(message)
        self.url = url
        self.code = code


class RefusedSourceError(BlockedError):
    def __init__(self, message: str, url: str | None = None) -> None:
        super().__init__(message, url, code="refused_domain")


class ConnectorDisabled(ConnectorError):
    pass
