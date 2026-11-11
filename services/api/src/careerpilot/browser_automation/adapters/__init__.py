from __future__ import annotations

from .base import (AmbiguousFormError, FieldMapping, FillResult, FormField, GenericFormAdapter,
                   SiteAdapter, UnsupportedFormError)
from .sites import AshbyAdapter, GreenhouseAdapter, LeverAdapter

ADAPTERS: list[SiteAdapter] = [GreenhouseAdapter(), LeverAdapter(), AshbyAdapter()]
GENERIC = GenericFormAdapter()


def get_adapter(url: str) -> SiteAdapter:
    for a in ADAPTERS:
        if a.detect(url):
            return a
    return GENERIC


def list_adapters() -> list[dict]:
    rows = [{"name": a.name, "hosts": list(a.hosts), "description": a.description} for a in ADAPTERS]
    rows.append({"name": GENERIC.name, "hosts": [], "description": GENERIC.description})
    return rows


__all__ = ["ADAPTERS", "GENERIC", "get_adapter", "list_adapters", "SiteAdapter", "GenericFormAdapter",
           "FormField", "FieldMapping", "FillResult", "UnsupportedFormError", "AmbiguousFormError"]
