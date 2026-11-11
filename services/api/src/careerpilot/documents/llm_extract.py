"""Optional LLM-assisted extraction through an INJECTED callable (the provider gateway comes
from Lane D). No provider vendors are imported here. Document text is wrapped as untrusted
data and every proposed fact is verified against the source text; results are always
'proposed' with capped confidence."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Protocol

from ..core.untrusted import injection_flags, wrap_untrusted
from .extractor import ExtractionResult, ProposedFact, extract
from .factschema import CATEGORIES, FIELDS, normalize_value
from .parsers import ParsedDocument

LLMCallable = Callable[[str], "str | list | dict"]
LLM_CONFIDENCE_CAP = 0.7
_IDENT_FIELDS = ("company", "title", "institution", "name", "degree", "issuer", "venue")

PROMPT = (
    "Extract career facts from the document below. Return ONLY JSON: a list of objects "
    '{"category": one of %s, "value": {...}, "source_quote": "verbatim text from the '
    'document"}. Field names per category: %s. Never invent data; omit anything not '
    "present verbatim in the document.\n\n%s"
)


class Extractor(Protocol):
    """Anything that turns a parsed document into PROPOSED facts."""
    name: str

    def extract(self, doc: ParsedDocument) -> ExtractionResult: ...


class RuleBasedExtractor:
    name = "rules"

    def extract(self, doc: ParsedDocument) -> ExtractionResult:
        return extract(doc)


def _squash(s: str) -> str:
    return re.sub(r"\W+", "", s.lower())


def _parse_json(raw: "str | list | dict") -> list:
    if isinstance(raw, (list, dict)):
        data = raw
    else:
        m = re.search(r"(\[.*\]|\{.*\})", raw, re.S)
        if not m:
            raise ValueError("no JSON in model output")
        data = json.loads(m.group(1))
    if isinstance(data, dict):
        data = data.get("facts", [])
    if not isinstance(data, list):
        raise ValueError("expected a list")
    return data


class LLMAssistedExtractor:
    """Rule-based extraction first, then LLM facts that are verifiably grounded in the text."""
    name = "rules+llm"

    def __init__(self, call: LLMCallable, max_chars: int = 24000) -> None:
        self._call = call
        self._max = max_chars

    def extract(self, doc: ParsedDocument) -> ExtractionResult:
        res = extract(doc)
        text = doc.text[:self._max]
        flags = injection_flags(text)
        if flags:
            res.warnings.append("Document contains instruction-like text (" + ", ".join(flags)
                                + "); it was treated as data only.")
        prompt = PROMPT % (", ".join(CATEGORIES), json.dumps({k: list(v) for k, v in
                                                              FIELDS.items()}),
                           wrap_untrusted(text, "uploaded_document"))
        try:
            items = _parse_json(self._call(prompt))
        except Exception as e:  # noqa: BLE001
            res.warnings.append(f"LLM extraction skipped ({type(e).__name__}); rules only.")
            return res
        haystack = _squash(doc.text)
        have = {(f.category, _squash(f.key)) for f in res.facts}
        dropped = 0
        for it in items:
            try:
                cat, val = it["category"], normalize_value(it["category"], it["value"])
            except Exception:  # noqa: BLE001
                dropped += 1
                continue
            if cat not in CATEGORIES or cat in ("other",):
                dropped += 1
                continue
            idents = [str(val[f]) for f in _IDENT_FIELDS if val.get(f)]
            nums = re.findall(r"\d[\d.,]*%?", " ".join(str(b) for b in val.get("bullets", [])))
            grounded = bool(idents) and all(_squash(i) in haystack for i in idents)
            grounded = grounded and all(_squash(n) in haystack for n in nums)
            if not grounded:
                dropped += 1
                continue
            f = ProposedFact(cat, val, min(LLM_CONFIDENCE_CAP, 0.55),
                             str(it.get("source_loc") or "llm-assisted"))
            if (f.category, _squash(f.key)) in have:
                continue
            have.add((f.category, _squash(f.key)))
            res.facts.append(f)
        if dropped:
            res.warnings.append(f"{dropped} LLM-proposed facts were discarded because they "
                                "could not be verified in the document text.")
        return res
