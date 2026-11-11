"""Safety policy for browser automation.

The automation code has NO code path that submits a form. This module lists what is forbidden and
detects hard-stop conditions (CAPTCHA, login/MFA walls, access-control pages)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Words that identify a final submit/apply control. Used ONLY to exclude such controls from field
# extraction and by the structural test; nothing in this package ever interacts with them.
FORBIDDEN_SUBMIT_WORDS = ("submit", "apply", "send application", "finish", "complete application")
# Source-level constructs that must never appear in this package (enforced by a structural test).
FORBIDDEN_CALLS = (".click(", ".dblclick(", ".tap(", ".press(", ".dispatch_event(", "requestSubmit",
                   ".submit(", "form.submit", "keyboard.", ".type(", "storage_state",
                   "launch_persistent_context", "user_data_dir")

CAPTCHA_FRAME = re.compile(
    r"(recaptcha|hcaptcha|turnstile|challenges\.cloudflare|arkoselabs|funcaptcha|geetest|"
    r"captcha-delivery|datadome)", re.I)
CAPTCHA_SELECTOR = (".g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey], [id*='captcha' i], "
                    "[class*='captcha' i], iframe[src*='captcha' i]")
CAPTCHA_TEXT = re.compile(r"(verify you are (a )?human|i'?m not a robot|are you a robot|"
                          r"complete the (captcha|security check))", re.I)
LOGIN_URL = re.compile(r"/(log-?in|sign-?in|sso|auth|authenticate|session/new)(/|$|\?)", re.I)
LOGIN_TEXT = re.compile(r"(sign in to (continue|apply)|log ?in to (continue|apply)|"
                        r"you must (be )?(logged|signed) in|create an account to apply|"
                        r"verification code|two-factor|2-step verification|multi-factor|one-time (code|password))",
                        re.I)
ACCESS_TEXT = re.compile(r"(access denied|unusual traffic|automated (queries|access)|"
                         r"blocked.{0,30}(bot|automat)|forbidden)", re.I)


@dataclass
class Blocker:
    kind: str       # captcha|login_required|mfa|access_control|unsupported_form|ambiguous_form|
    detail: str     # domain_not_allowed|navigation_failed
    hard: bool = True

    def as_dict(self) -> dict:
        return {"kind": self.kind, "detail": self.detail, "hard": self.hard}


_PROBE_JS = """() => {
  const vis = e => { const r = e.getClientRects(); const s = getComputedStyle(e);
                     return r.length > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const text = (document.body && document.body.innerText || '').slice(0, 6000);
  return {
    text,
    password: Array.from(document.querySelectorAll('input[type=password]')).some(vis),
    otp: Array.from(document.querySelectorAll(
      'input[autocomplete=one-time-code], input[name*=otp i], input[name*=mfa i]')).some(vis),
    captchaEl: document.querySelectorAll(%s).length,
    frames: Array.from(document.querySelectorAll('iframe')).map(f => f.src || f.getAttribute('src') || ''),
    forms: document.forms.length,
    fields: document.querySelectorAll('input:not([type=hidden]), select, textarea').length,
  };
}""" % json.dumps(CAPTCHA_SELECTOR)


def detect_blockers(page, violations: list[str] | None = None) -> list[Blocker]:  # noqa: ANN001
    """Inspect the live page (all frames) for hard-stop conditions. Read-only."""
    out: list[Blocker] = []
    for v in violations or []:
        out.append(Blocker("domain_not_allowed", v))
    url = page.url or ""
    try:
        info = page.evaluate(_PROBE_JS)
    except Exception as e:  # noqa: BLE001
        out.append(Blocker("navigation_failed", type(e).__name__))
        return out
    frame_urls = [f.url for f in page.frames if f != page.main_frame] + list(info["frames"])
    if (info["captchaEl"] or any(CAPTCHA_FRAME.search(u or "") for u in frame_urls)
            or CAPTCHA_TEXT.search(info["text"])):
        out.append(Blocker("captcha", "CAPTCHA or challenge detected; the user must handle it"))
    mfa_text = re.search(r"(verification code|two-factor|multi-factor|one-time)", info["text"], re.I)
    if info["otp"] or (mfa_text and info["fields"] <= 6):
        out.append(Blocker("mfa", "Multi-factor / verification code step detected"))
    path = urlparse(url).path
    if info["password"] or LOGIN_URL.search(path) or (
            LOGIN_TEXT.search(info["text"]) and info["fields"] <= 6):
        out.append(Blocker("login_required", "Login or account wall detected"))
    if ACCESS_TEXT.search(info["text"][:800]) and info["fields"] <= 3:
        out.append(Blocker("access_control", "Access-control / anti-bot page detected"))
    seen: set[str] = set()
    uniq = []
    for b in out:
        if b.kind not in seen:
            seen.add(b.kind)
            uniq.append(b)
    return uniq
