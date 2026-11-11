"""Structural safety test: no code path in browser_automation may click/submit."""
import re
from pathlib import Path

import careerpilot.browser_automation as ba
from careerpilot.browser_automation.safety import FORBIDDEN_CALLS

SRC = Path(ba.__file__).parent


def _code_lines(p: Path):
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if s.startswith("#") or p.name == "safety.py":   # safety.py only *lists* the forbidden calls
            continue
        yield n, line


def test_no_click_or_submit_calls_anywhere():
    bad = []
    for p in SRC.rglob("*.py"):
        for n, line in _code_lines(p):
            for tok in FORBIDDEN_CALLS:
                if tok in line:
                    bad.append(f"{p.name}:{n}: {tok}")
    assert not bad, bad


def test_no_click_on_submit_like_locator_regex():
    pat = re.compile(r"(get_by_role\(\s*[\"']button|button\[type|type=.?submit|text=.?(submit|apply))"
                     r"[^\n]*\.(click|press|dispatch_event)\(", re.I)
    for p in SRC.rglob("*.py"):
        assert not pat.search(p.read_text(encoding="utf-8")), p.name


def test_no_persistent_browser_state():
    for p in SRC.rglob("*.py"):
        if p.name == "safety.py":
            continue
        t = p.read_text(encoding="utf-8")
        assert "launch_persistent_context" not in t and "storage_state" not in t


def test_safety_forbidden_list_present():
    assert ".click(" in FORBIDDEN_CALLS and ".submit(" in FORBIDDEN_CALLS
