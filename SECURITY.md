# Security policy

CareerPilot AI is a local-first, single-user application. It has not had an independent security review.

## Reporting a vulnerability

Please report privately: use GitHub "Report a vulnerability" (private security advisory) on the repository.
Do not open a public issue with exploit details. Include version/commit, steps to reproduce, and impact.
No response-time SLA is promised; this is a volunteer project.

## Scope

In scope: authentication/session handling, secret storage and redaction, the submit-approval gate, the
browser-automation allowlist and blocker handling, prompt-injection isolation, file upload/parse handling,
LaTeX compile sandboxing (forbidden-command scan), backup/export.
Out of scope: vulnerabilities in third-party services you configure, or in an instance deliberately exposed
to the public internet (the app is designed to bind to `127.0.0.1`).

## Design summary

See `docs/SECURITY_AND_PRIVACY.md` (threat model, STRIDE table, known gaps).
Never commit `.env`, `data/`, `secret.key`, provider keys or real resumes; CI runs `scripts/scan_secrets.py`.
