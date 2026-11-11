"""Adapter interface + generic form adapter.

Fields are located by accessible label / ARIA role / form semantics FIRST; css (id/name) is only a
last-resort fallback and is always verified to be the very element that was extracted.
There is deliberately no function in this package that clicks a submit/apply control.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("careerpilot.automation")

SKIP_TYPES = {"hidden", "submit", "button", "image", "reset"}
TRUTHY = {"yes", "true", "1", "y", "on", "checked"}


class UnsupportedFormError(Exception):
    kind = "unsupported_form"


class AmbiguousFormError(UnsupportedFormError):
    kind = "ambiguous_form"


def norm(s: Any) -> str:
    return " ".join(str(s if s is not None else "").split())


def clean_label(s: str) -> str:
    return norm(re.sub(r"\(\s*required\s*\)|\*|✱", " ", s or "", flags=re.I)).strip(" :")


@dataclass
class FormField:
    idx: int
    label: str                  # cleaned display label
    raw_label: str              # accessible text as found (may include '*')
    kind: str                   # text|textarea|select|checkbox|radio|file|combobox|unsupported
    tag: str = "input"
    type: str = "text"
    name: str = ""
    id: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)
    option_idxs: list[int] = field(default_factory=list)   # radio groups
    supported: bool = True
    reason: str | None = None

    def public(self) -> dict:
        return {"label": self.label, "kind": self.kind, "required": self.required,
                "options": self.options, "supported": self.supported, "reason": self.reason}


@dataclass
class FieldMapping:
    field: FormField
    value: str | bool | None
    status: str                 # only "ok" is ever filled
    source: str = ""


@dataclass
class FillResult:
    label: str
    status: str                 # filled|mismatch|error|skipped
    validated: bool = False
    value: str | None = None    # read-back value (returned to the user, never logged)
    via: str | None = None      # label|role|css
    detail: str | None = None


_EXTRACT_JS = """(root) => {
  const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
  const labelText = lab => { const c = lab.cloneNode(true);
    c.querySelectorAll('input,select,textarea,button').forEach(n => n.remove()); return clean(c.textContent); };
  const vis = e => { const r = e.getClientRects(); if (!r.length) return false;
    const s = getComputedStyle(e); if (s.visibility === 'hidden' || s.display === 'none') return false;
    const b = e.getBoundingClientRect(); return !(b.right < -500 || b.bottom < -500); };
  const out = []; let i = 0;
  root.querySelectorAll('input, select, textarea').forEach(el => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : tag)).toLowerCase();
    if (['hidden','submit','button','image','reset'].includes(type) || el.disabled) return;
    if (type !== 'file' && !vis(el)) return;
    if (el.getAttribute('aria-hidden') === 'true') return;
    let raw = '';
    const al = el.getAttribute('aria-label'), lb = el.getAttribute('aria-labelledby');
    if (al) raw = clean(al);
    else if (lb) raw = clean(lb.split(/\\s+/).map(id => { const n = document.getElementById(id);
      return n ? clean(n.textContent) : ''; }).join(' '));
    else if (el.labels && el.labels.length) raw = Array.from(el.labels).map(labelText).join(' ');
    let legend = '';
    const fs = el.closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg) legend = clean(lg.textContent); }
    const grp = el.closest('[role=radiogroup],[role=group]');
    if (!legend && grp) { legend = clean(grp.getAttribute('aria-label') || '');
      const gl = grp.getAttribute('aria-labelledby');
      if (!legend && gl) { const n = document.getElementById(gl); if (n) legend = clean(n.textContent); } }
    el.setAttribute('data-cp-idx', String(i));
    out.push({idx: i, tag, type, name: el.getAttribute('name') || '', id: el.id || '', label: raw,
      legend, placeholder: clean(el.getAttribute('placeholder') || ''),
      required: !!el.required || el.getAttribute('aria-required') === 'true',
      multiple: !!el.multiple, role: el.getAttribute('role') || '',
      popup: el.getAttribute('aria-haspopup') || '', auto: el.getAttribute('aria-autocomplete') || '',
      options: tag === 'select' ? Array.from(el.options).map(o => clean(o.textContent)).filter(Boolean) : []});
    i++;
  });
  return out;
}"""

_CONTROLS = "input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea"


class SiteAdapter(ABC):
    name = "base"
    hosts: tuple[str, ...] = ()
    description = ""

    @abstractmethod
    def detect(self, url: str) -> bool: ...

    @abstractmethod
    def extract_fields(self, page) -> list[FormField]: ...  # noqa: ANN001

    @abstractmethod
    def fill(self, page, mapping: list[FieldMapping]) -> list[FillResult]: ...  # noqa: ANN001


class GenericFormAdapter(SiteAdapter):
    name = "generic"
    description = "Any single, plain HTML application form (labels/roles first)."
    form_selectors: tuple[str, ...] = ()
    name_hints: dict[str, str] = {}

    def detect(self, url: str) -> bool:
        return True

    # ---- scope -----------------------------------------------------------------------------
    def _scope(self, page):  # noqa: ANN001, ANN202
        for sel in self.form_selectors:
            loc = page.locator(sel)
            if loc.count() >= 1:
                return loc.first
        forms = page.locator("form")
        cands = []
        for i in range(forms.count()):
            f = forms.nth(i)
            if f.is_visible() and f.locator(_CONTROLS).count() >= 2:
                cands.append(f)
        if len(cands) == 1:
            return cands[0]
        if not cands:
            raise UnsupportedFormError("no application form found on this page")
        raise AmbiguousFormError(f"{len(cands)} candidate forms found; refusing to guess")

    def _hint(self, name: str) -> str:
        for k, v in self.name_hints.items():
            if name == k or name.endswith(f"[{k}]") or name.endswith("." + k):
                return v
        return ""

    # ---- extraction ------------------------------------------------------------------------
    def extract_fields(self, page) -> list[FormField]:  # noqa: ANN001
        scope = self._scope(page)
        raw = scope.evaluate(_EXTRACT_JS)
        fields: list[FormField] = []
        radios: dict[str, FormField] = {}
        for r in raw:
            t, tag = r["type"], r["tag"]
            label_raw = r["label"] or ""
            if tag == "select":
                kind = "select"
            elif tag == "textarea":
                kind = "textarea"
            elif t == "checkbox":
                kind = "checkbox"
            elif t == "radio":
                kind = "radio"
            elif t == "file":
                kind = "file"
            elif t == "password":
                kind = "unsupported"
            else:
                kind = "text"
            if r["role"] == "combobox" or r["popup"] in ("listbox", "true") or r["auto"]:
                kind = "combobox"
            if kind == "radio":
                key = r["name"] or f"idx{r['idx']}"
                grp = radios.get(key)
                opt = clean_label(label_raw) or r["placeholder"]
                if grp is None:
                    title = r["legend"] or self._hint(r["name"]) or ""
                    grp = FormField(r["idx"], clean_label(title), title, "radio", "input", "radio",
                                    r["name"], r["id"], r["required"])
                    if not title:
                        grp.supported, grp.reason = False, "no accessible group label"
                    radios[key] = grp
                    fields.append(grp)
                grp.options.append(opt)
                grp.option_idxs.append(r["idx"])
                grp.required = grp.required or r["required"]
                continue
            title = label_raw or r["legend"] or r["placeholder"] or self._hint(r["name"])
            f = FormField(r["idx"], clean_label(title), title, kind, tag, t, r["name"], r["id"],
                          r["required"] or "*" in label_raw, r["options"])
            if not f.label:
                f.supported, f.reason = False, "no accessible label"
            elif kind == "combobox":
                f.supported, f.reason = False, "custom combobox widgets are not auto-filled"
            elif kind == "unsupported":
                f.supported, f.reason = False, f"unsupported input type {t}"
            elif r["multiple"]:
                f.supported, f.reason = False, "multi-select is not auto-filled"
            fields.append(f)
        # ambiguity: two fields sharing a label cannot be located reliably
        counts: dict[str, int] = {}
        for f in fields:
            counts[f.label.lower()] = counts.get(f.label.lower(), 0) + 1
        for f in fields:
            if f.label and counts[f.label.lower()] > 1 and f.supported:
                f.supported, f.reason = False, "ambiguous: duplicate label"
        if not fields:
            raise UnsupportedFormError("form has no fillable fields")
        return fields

    # ---- locating --------------------------------------------------------------------------
    @staticmethod
    def _role(f: FormField) -> str:
        return {"checkbox": "checkbox", "radio": "radio", "select": "combobox"}.get(
            f.kind, "spinbutton" if f.type == "number" else "textbox")

    def _locate(self, root, f: FormField, idx: int, label: str, role: str):  # noqa: ANN001, ANN202
        want = str(idx)
        tries = []
        if label:
            tries.append(("label", lambda: root.get_by_label(label, exact=True)))
            cl = clean_label(label)
            if cl != label:
                tries.append(("label", lambda: root.get_by_label(cl, exact=True)))
            tries.append(("role", lambda: root.get_by_role(role, name=clean_label(label), exact=True)))
        for via, mk in tries:
            try:
                loc = mk()
                if loc.count() == 1 and loc.get_attribute("data-cp-idx") == want:
                    return loc, via
            except Exception:  # noqa: BLE001
                continue
        for sel in ([f'[id="{f.id}"]'] if f.id else []) + ([f'[name="{f.name}"]'] if f.name else []):
            loc = root.locator(sel)
            if loc.count() >= 1:
                m = root.locator(f'{sel}[data-cp-idx="{want}"]')
                if m.count() == 1:
                    return m, "css"
        return None, None

    # ---- filling ---------------------------------------------------------------------------
    def fill(self, page, mapping: list[FieldMapping]) -> list[FillResult]:  # noqa: ANN001
        scope = self._scope(page)
        results: list[FillResult] = []
        for m in mapping:
            f = m.field
            if m.status != "ok" or not f.supported:
                results.append(FillResult(f.label, "skipped", detail=f"status={m.status}"))
                continue
            try:
                results.append(self._fill_one(scope, f, m.value))
            except Exception as e:  # noqa: BLE001 - never include the value in messages
                log.warning("autofill error on field %r: %s", f.label, type(e).__name__)
                results.append(FillResult(f.label, "error", detail=type(e).__name__))
        return results

    def _fill_one(self, root, f: FormField, value) -> FillResult:  # noqa: ANN001
        if f.kind == "radio":
            want = norm(value).lower()
            for opt, oidx in zip(f.options, f.option_idxs):
                if norm(opt).lower() == want:
                    loc, via = self._locate(root, f, oidx, opt, "radio")
                    if loc is None:
                        return FillResult(f.label, "error", detail="option not locatable")
                    loc.check(timeout=5000)
                    ok = loc.is_checked()
                    return FillResult(f.label, "filled" if ok else "mismatch", ok,
                                      opt if ok else None, via)
            return FillResult(f.label, "error", detail="no such option")
        loc, via = self._locate(root, f, f.idx, f.raw_label or f.label, self._role(f))
        if loc is None:
            return FillResult(f.label, "error", detail="field not locatable by label/role")
        if f.kind in ("text", "textarea"):
            loc.fill(str(value), timeout=5000)
            back = loc.input_value()
            ok = norm(back) == norm(value)
            return FillResult(f.label, "filled" if ok else "mismatch", ok, back, via,
                              None if ok else "field did not retain the value")
        if f.kind == "select":
            try:
                loc.select_option(label=str(value), timeout=5000)
            except Exception:  # noqa: BLE001
                loc.select_option(value=str(value), timeout=5000)
            back = loc.evaluate("e => e.selectedOptions[0] ? e.selectedOptions[0].textContent : ''")
            bval = loc.input_value()
            ok = norm(back).lower() == norm(value).lower() or norm(bval) == norm(value)
            return FillResult(f.label, "filled" if ok else "mismatch", ok, norm(back), via)
        if f.kind == "checkbox":
            want = value is True or norm(value).lower() in TRUTHY
            loc.set_checked(want, timeout=5000)
            ok = loc.is_checked() == want
            return FillResult(f.label, "filled" if ok else "mismatch", ok, str(want).lower(), via)
        if f.kind == "file":
            p = Path(str(value))
            if not p.is_file():
                return FillResult(f.label, "error", detail="file missing")
            loc.set_input_files(str(p), timeout=5000)
            names = loc.evaluate("e => Array.from(e.files).map(f => f.name)")
            ok = names == [p.name]
            return FillResult(f.label, "filled" if ok else "mismatch", ok, p.name if ok else None, via)
        return FillResult(f.label, "skipped", detail="unsupported kind")
