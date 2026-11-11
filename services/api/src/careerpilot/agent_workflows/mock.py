"""Deterministic mock model for tests: valid instances generated from the requested schema."""
from __future__ import annotations

import json
from typing import Any

from ..provider_gateway.interface import GenerateRequest, GenerateResult, TaskPolicy


def example_from_schema(s: Any, root: dict, depth: int = 0) -> Any:
    if not isinstance(s, dict):
        return None
    if "$ref" in s:
        node: Any = root
        for part in s["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return example_from_schema(node, root, depth)
    if "default" in s and not isinstance(s["default"], (list, dict)):
        return s["default"]
    if "enum" in s:
        return s["enum"][0]
    for k in ("anyOf", "oneOf"):
        if k in s:
            opts = [o for o in s[k] if o.get("type") != "null"] or s[k]
            return example_from_schema(opts[0], root, depth)
    t = s.get("type")
    if t == "object" or "properties" in s:
        if depth > 6:
            return {}
        return {k: example_from_schema(v, root, depth + 1)
                for k, v in s.get("properties", {}).items() if k in s.get("required", [])}
    if t == "array":
        return []
    if t == "string":
        return "mock"
    if t == "integer":
        return 1
    if t == "number":
        return 0.5
    if t == "boolean":
        return False
    return None


class MockGateway:
    """Implements the generate/embed subset agents use. `responses` maps task_type -> dict|callable."""

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[GenerateRequest, TaskPolicy]] = []

    async def generate(self, req: GenerateRequest, policy: TaskPolicy) -> GenerateResult:
        self.calls.append((req, policy))
        r = self.responses.get(policy.task_type)
        if callable(r):
            r = r(req, policy)
        if r is None:
            r = example_from_schema(policy.json_schema or {}, policy.json_schema or {})
        text = json.dumps(r)
        return GenerateResult(text=text, parsed=r if policy.json_schema else None,
                              provider_id="mock", model_id="mock-model",
                              usage={"prompt_tokens": 10, "completion_tokens": 5, "cost_usd": None})

    async def embed(self, req, policy):  # pragma: no cover
        raise NotImplementedError
