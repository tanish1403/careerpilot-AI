"""Lane D test helpers."""
from __future__ import annotations

import json

import httpx

from careerpilot.core.secrets import set_secret
from careerpilot.db.models import Model, Provider, Setting

KEY = "sk-SUPERSECRETKEY123456"


def mk_provider(db, protocol="openai_compatible", url="https://api.example.com/v1", key=None,
                retries=2, name="P", local=None):
    p = Provider(display_name=name, protocol=protocol, base_url=url, max_retries=retries,
                 extra={"local": local} if local is not None else {})
    db.add(p)
    db.flush()
    if key:
        p.secret_ref = f"provider:{p.id}"
        set_secret(db, p.secret_ref, key)
    db.flush()
    return p


def mk_model(db, p, model_id="m1", **caps):
    m = Model(provider_id=p.id, model_id=model_id, capabilities={"chat": True, **caps},
              verified=bool(caps.get("verified")))
    db.add(m)
    db.flush()
    return m


def setting(db, key, value):
    row = db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    db.flush()


def oai_reply(text, pt=10, ct=5):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                     "usage": {"prompt_tokens": pt, "completion_tokens": ct}})


def transport(handler):
    return httpx.MockTransport(handler)


async def no_sleep(_s):  # noqa: D401
    return None


class Sleeps:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"]}
GOOD = json.dumps({"answer": "ok"})
