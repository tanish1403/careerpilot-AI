import pytest
from careerpilot.browser_automation.allowlist import DEFAULT_ALLOWLIST, is_allowed, normalize_entry


def test_defaults():
    assert set(DEFAULT_ALLOWLIST) == {"boards.greenhouse.io", "job-boards.greenhouse.io",
                                      "jobs.lever.co", "jobs.ashbyhq.com"}


@pytest.mark.parametrize("url,ok", [
    ("https://boards.greenhouse.io/acme/jobs/1", True),
    ("https://jobs.lever.co/x/y/apply", True),
    ("https://evil.com/boards.greenhouse.io", False),
    ("https://boards.greenhouse.io.evil.com/x", False),
    ("https://user@evil.com@boards.greenhouse.io/", True),   # host is boards.greenhouse.io
    ("https://evil.com@boards.greenhouse.io/", True),
    ("https://boards.greenhouse.io@evil.com/", False),
    ("http://boards.greenhouse.io/x", False),                # cleartext refused off loopback
    ("javascript:alert(1)", False), ("file:///etc/passwd", False), ("", False),
    ("https://sub.boards.greenhouse.io/", False),            # exact host match only
])
def test_is_allowed(url, ok):
    assert is_allowed(url, DEFAULT_ALLOWLIST) is ok


def test_loopback_http_only_when_listed():
    assert not is_allowed("http://127.0.0.1:1/x", DEFAULT_ALLOWLIST)
    assert is_allowed("http://127.0.0.1:1/x", ["127.0.0.1"])


def test_entry_validation():
    assert normalize_entry(" Jobs.Lever.co. ") == "jobs.lever.co"
    for bad in ("*.lever.co", "https://x.com", "a/b", ""):
        with pytest.raises(ValueError):
            normalize_entry(bad)
