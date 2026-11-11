"""Shared helpers for Lane B routes (underscore module: not auto-mounted, no `router`)."""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ...documents.profile_service import ProfileError


def to_http(e: ProfileError) -> HTTPException:
    return HTTPException(e.status, e.detail)


def error_response(e: ProfileError) -> JSONResponse:
    body: dict = {"detail": e.detail}
    if e.code:
        body["code"] = e.code
    return JSONResponse(status_code=e.status, content=body)
