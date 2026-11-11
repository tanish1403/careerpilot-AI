"""Connector registry: kind -> connector class."""
from __future__ import annotations

from .ashby import AshbyConnector
from .base import BaseConnector
from .career_page import CareerPageConnector
from .errors import ConfigError
from .greenhouse import GreenhouseConnector
from .jobspy_adapter import JobSpyConnector
from .lever import LeverConnector
from .url_import import UrlListConnector

CONNECTORS: dict[str, type[BaseConnector]] = {c.kind: c for c in (
    GreenhouseConnector, AshbyConnector, LeverConnector, CareerPageConnector, UrlListConnector,
    JobSpyConnector)}


def build_connector(kind: str, **kw) -> BaseConnector:
    cls = CONNECTORS.get(kind)
    if cls is None:
        raise ConfigError(f"Unknown source kind '{kind}'. Known: {', '.join(sorted(CONNECTORS))}")
    return cls(**kw)


def kinds_info() -> list[dict]:
    return [{"kind": k, "label": c.label, "permitted_usage": c.permitted_usage,
             "config_schema": c.config_schema, "enabled_by_default": k != "jobspy"}
            for k, c in CONNECTORS.items()]
