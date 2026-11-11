"""Protocol adapters: openai_compatible, ollama, anthropic. httpx with injectable transport."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
import jsonschema

from .errors import CapabilityError, ProviderError, StructuredOutputError, scrub
from .interface import EmbedRequest, EmbedResult, GenerateRequest, GenerateResult, HealthResult

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_json_output(text: str, schema: dict | None) -> Any:
    """Parse model text as JSON (tolerating code fences / surrounding prose) and validate."""
    raw = _FENCE.sub("", text.strip())
    try:
        val = json.loads(raw)
    except ValueError:
        m = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
        if not m:
            raise StructuredOutputError("output is not valid JSON") from None
        try:
            val = json.loads(m.group(1))
        except ValueError:
            raise StructuredOutputError("output is not valid JSON") from None
    if schema:
        try:
            jsonschema.validate(val, schema)
        except jsonschema.ValidationError as e:
            raise StructuredOutputError(f"output violates schema: {e.message[:200]}") from None
    return val


def schema_instruction(schema: dict) -> str:
    return ("Respond with a single JSON value only (no prose, no code fences) that validates "
            "against this JSON schema:\n" + json.dumps(schema, separators=(",", ":")))


def _with_schema(messages: list[dict], schema: dict | None) -> list[dict]:
    if not schema:
        return list(messages)
    return [{"role": "system", "content": schema_instruction(schema)}, *messages]


class BaseAdapter:
    protocol = ""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    def _headers(self, api_key: str | None) -> dict:
        return {}

    async def _request(self, method: str, url: str, api_key: str | None, timeout_s: float,
                       json_body: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=timeout_s) as c:
                r = await c.request(method, url, headers=self._headers(api_key), json=json_body)
        except httpx.TimeoutException as e:
            raise ProviderError(f"timeout: {type(e).__name__}", None, True) from None
        except httpx.HTTPError as e:
            raise ProviderError(scrub(f"connection error: {type(e).__name__}: {e}", api_key),
                                None, True) from None
        if r.status_code >= 400:
            body = scrub(r.text[:400], api_key)
            raise ProviderError(f"HTTP {r.status_code}: {body}", r.status_code,
                                r.status_code >= 500 or r.status_code in (408, 429))
        try:
            return r.json()
        except ValueError:
            raise ProviderError("provider returned non-JSON body", r.status_code, False) from None

    @staticmethod
    def _base(base_url: str) -> str:
        return base_url.rstrip("/")

    async def health(self, base_url: str, api_key: str | None, timeout_s: int) -> HealthResult:
        t = time.perf_counter()
        try:
            await self.list_models(base_url, api_key, {}, timeout_s=timeout_s)
        except ProviderError as e:
            return HealthResult(ok=False, detail=str(e), latency_ms=(time.perf_counter() - t) * 1000)
        return HealthResult(ok=True, latency_ms=(time.perf_counter() - t) * 1000, detail="reachable")

    async def embed(self, base_url, api_key, model_id, req, timeout_s) -> EmbedResult:
        raise CapabilityError(f"{self.protocol} adapter does not support embeddings")


class OpenAICompatAdapter(BaseAdapter):
    protocol = "openai_compatible"

    def _headers(self, api_key):
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def list_models(self, base_url, api_key, extra, timeout_s: float = 30) -> list[dict]:
        d = await self._request("GET", f"{self._base(base_url)}/models", api_key, timeout_s)
        out = []
        for m in d.get("data", d.get("models", [])) if isinstance(d, dict) else d:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            caps: dict = {}
            sp = m.get("supported_parameters")
            if isinstance(sp, list):  # only declared metadata, never inferred from the name
                caps["tool_calling"] = "tools" in sp
                caps["structured_output"] = "response_format" in sp or "structured_outputs" in sp
            if isinstance(m.get("context_length"), int):
                caps["context_length"] = m["context_length"]
            out.append({"model_id": m["id"], "capabilities": caps})
        return out

    async def generate(self, base_url, api_key, model_id, req: GenerateRequest, timeout_s,
                       json_schema) -> GenerateResult:
        body: dict = {"model": model_id, "messages": _with_schema(req.messages, json_schema),
                      "temperature": req.temperature, "stream": False}
        if req.max_tokens:
            body["max_tokens"] = req.max_tokens
        d = await self._request("POST", f"{self._base(base_url)}/chat/completions", api_key,
                                timeout_s, body)
        try:
            text = d["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError("malformed chat completion response", None, False) from None
        u = d.get("usage") or {}
        usage = {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}
        return GenerateResult(text=text, provider_id="", model_id=model_id, usage=usage)

    async def embed(self, base_url, api_key, model_id, req: EmbedRequest, timeout_s) -> EmbedResult:
        d = await self._request("POST", f"{self._base(base_url)}/embeddings", api_key, timeout_s,
                                {"model": model_id, "input": req.inputs})
        try:
            vecs = [x["embedding"] for x in sorted(d["data"], key=lambda x: x.get("index", 0))]
        except (KeyError, TypeError):
            raise ProviderError("malformed embeddings response", None, False) from None
        return EmbedResult(vectors=vecs, provider_id="", model_id=model_id)


class OllamaAdapter(BaseAdapter):
    protocol = "ollama"

    async def list_models(self, base_url, api_key, extra, timeout_s: float = 30) -> list[dict]:
        d = await self._request("GET", f"{self._base(base_url)}/api/tags", api_key, timeout_s)
        return [{"model_id": m.get("name") or m.get("model"), "capabilities": {}}
                for m in d.get("models", []) if m.get("name") or m.get("model")]

    async def generate(self, base_url, api_key, model_id, req, timeout_s, json_schema):
        body: dict = {"model": model_id, "messages": _with_schema(req.messages, json_schema),
                      "stream": False, "options": {"temperature": req.temperature}}
        if req.max_tokens:
            body["options"]["num_predict"] = req.max_tokens
        if json_schema:
            body["format"] = json_schema
        d = await self._request("POST", f"{self._base(base_url)}/api/chat", api_key, timeout_s, body)
        try:
            text = d["message"]["content"]
        except (KeyError, TypeError):
            raise ProviderError("malformed ollama chat response", None, False) from None
        usage = {"prompt_tokens": d.get("prompt_eval_count"), "completion_tokens": d.get("eval_count")}
        return GenerateResult(text=text, provider_id="", model_id=model_id, usage=usage)

    async def embed(self, base_url, api_key, model_id, req, timeout_s):
        d = await self._request("POST", f"{self._base(base_url)}/api/embed", api_key, timeout_s,
                                {"model": model_id, "input": req.inputs})
        vecs = d.get("embeddings")
        if not isinstance(vecs, list):
            raise ProviderError("malformed ollama embed response", None, False)
        return EmbedResult(vectors=vecs, provider_id="", model_id=model_id)


class AnthropicAdapter(BaseAdapter):
    protocol = "anthropic"
    VERSION = "2023-06-01"

    def _headers(self, api_key):
        h = {"anthropic-version": self.VERSION}
        if api_key:
            h["x-api-key"] = api_key
        return h

    def _root(self, base_url: str) -> str:
        b = self._base(base_url)
        return b[:-3] if b.endswith("/v1") else b

    async def list_models(self, base_url, api_key, extra, timeout_s: float = 30) -> list[dict]:
        d = await self._request("GET", f"{self._root(base_url)}/v1/models", api_key, timeout_s)
        return [{"model_id": m["id"], "capabilities": {}} for m in d.get("data", []) if m.get("id")]

    async def generate(self, base_url, api_key, model_id, req, timeout_s, json_schema):
        msgs = _with_schema(req.messages, json_schema)
        system = "\n\n".join(str(m["content"]) for m in msgs if m.get("role") == "system")
        chat = [{"role": m["role"], "content": m["content"]} for m in msgs
                if m.get("role") in ("user", "assistant")]
        body: dict = {"model": model_id, "messages": chat, "max_tokens": req.max_tokens or 1024,
                      "temperature": req.temperature}
        if system:
            body["system"] = system
        d = await self._request("POST", f"{self._root(base_url)}/v1/messages", api_key, timeout_s, body)
        try:
            text = "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")
        except (KeyError, TypeError):
            raise ProviderError("malformed anthropic response", None, False) from None
        u = d.get("usage") or {}
        usage = {"prompt_tokens": u.get("input_tokens"), "completion_tokens": u.get("output_tokens")}
        return GenerateResult(text=text, provider_id="", model_id=model_id, usage=usage)


def build_adapters(transport=None) -> dict[str, BaseAdapter]:
    return {a.protocol: a for a in (OpenAICompatAdapter(transport), OllamaAdapter(transport),
                                    AnthropicAdapter(transport))}
