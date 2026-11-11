"""Errors raised by the document pipeline. `code` values are part of the API contract."""
from __future__ import annotations

# Codes that make the upload fail with 422 and store nothing.
REJECT_CODES = {"unsupported_type", "corrupt_file", "empty_file"}


class DocumentError(Exception):
    """A document could not be parsed. `code` is machine readable, `message` is user facing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def rejects_upload(self) -> bool:
        return self.code in REJECT_CODES
