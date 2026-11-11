# Lane E notes (applications + supervised autofill)

Deviations / additions to API_CONTRACT (all additive):
- `POST /applications/{id}/grant-submit {approval_id, granted?}`: stop-gap human decision on a submit approval
  until Lane D's approvals route is the canonical decision point. Granting re-checks the snapshot.
- `PATCH /applications/{id} {notes, follow_up_at, confirmation_ref}`, `GET /applications/follow-ups` (due reminders),
  `GET /automation/sessions/{id}/screenshot`.
- `Approved` is also unreachable via the generic transition endpoint (only `approve-resume`), like `Submitted`.
- `PUT /applications/{id}/answers` body: `{answers:[{id?, question?, answer}]}`; editing clears evidence_ids and
  user_confirmed (user-authored text is no longer fact-backed); any edit expires pending/granted submit approvals.
- Answers are drafted from CONFIRMED `contact`/`experience`/`education` facts only; unmatched or sensitive
  questions get answer=null, needs_user=true. Sensitive answers are never auto-filled, even if the user confirmed one.
- Automation sessions are in-memory (one Chromium per session, ephemeral context, daemon worker thread); they do not
  survive a restart. Hard blockers (CAPTCHA, login/MFA, access-control, off-allowlist redirect, unsupported/ambiguous
  form) move the application to `Blocked`. NOTE: `Blocked` has no outgoing transitions in core/enums.py, so a blocked
  application cannot resume (integrator: consider `Blocked -> Approved`). Sensitive fields and read-back mismatches do
  not block: they are left for the user and listed in `blockers` with `hard:false`.
- Playwright pinned to 1.63.0 in the venv (matches preinstalled chromium-1243 in /opt/pw-browsers).
- Redirects: Playwright does not re-route redirect hops, so navigation requests are fetched with
  `max_redirects=0` and the Location header is vetted before the response is passed to the page.
- Setting keys: `automation.allowlist` (list of hostnames), `automation.headed` (bool, default false; env
  CAREERPILOT_AUTOMATION_HEADED). No migrations were added.
