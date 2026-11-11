# Security and privacy

Local single-user app; API binds to 127.0.0.1 by default; CORS limited to configured origins, no credentials.

## Controls (as implemented)
- Auth: PBKDF2-SHA256 (200k) password hash, HMAC-signed expiring bearer token; `/auth/setup` works once; all routes except health, ready, features, auth require a token.
- Secrets: provider keys Fernet-encrypted; key file in the data dir; API exposes `has_secret` only; export excludes secrets; audit details auto-redacted.
- Consent: documents flagged sensitive are not sent to non-local providers unless `allow_external_llm` is true; refusals audited.
- Untrusted text (jobs, documents, web pages) is wrapped and scanned; tool grants are fixed policy, not derived from content.
- Submit gate: generic transition cannot reach `Approved`/`Submitted`; only `confirm-submitted` after a granted, fingerprint-matched approval; edits expire approvals.
- Automation: explicit user start, domain allowlist, redirect hops vetted, hard stop at CAPTCHA/login/MFA, sensitive fields never auto-filled.
- LaTeX: source scanned for forbidden commands/packages before compile; timeout.
- Uploads: type/size/corruption checks; nothing stored on rejection.
- Data: backup, restore, export, delete-all.

## STRIDE
| Threat | Example | Mitigation | Gap |
|---|---|---|---|
| Spoofing | Other local process calls API | Bearer token, PBKDF2 | Token is bearer, not bound to device; no rate limit on login |
| Tampering | Injected job text steers agent | Wrapping, flags, frozen grants, tests | Model behaviour itself is not verified |
| Tampering | Malicious LaTeX | Forbidden-command scan, timeout | Compiled with no shell, `-no-shell-escape`, temp dir, timeout, rlimits; not a full OS sandbox |
| Repudiation | Dispute what was submitted | Audit events, approval snapshot fingerprint | Audit table is not tamper-evident |
| Info disclosure | Key in response/log | Write-only, encrypted, redaction, walked by tests | Key file sits beside the DB on disk (no OS keystore) |
| Info disclosure | Resume sent to cloud LLM | Consent gate | After consent, content leaves the machine |
| Denial of service | Huge upload, hostile page | Size limits, timeouts, rate limits per source | In-process execution; no quotas |
| Elevation | Agent submits for user | No submit tool, approval gate | Autofill sessions fill real forms once allowlisted |

Known weaknesses are listed in `docs/KNOWN_ISSUES.md`. No independent review has been done.
