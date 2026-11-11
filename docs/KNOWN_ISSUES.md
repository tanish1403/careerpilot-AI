# Known issues and gaps

Found during final integration (Lane H) or carried from lane notes. Not fixed unless stated.

1. **Audit log over-redaction.** `core.audit` redaction rewrites backup filenames (digit runs) as
   `[REDACTED_PHONE]`, so audit entries for backups lose the filename. Low impact, cosmetic.
2. **`Blocked` is terminal.** `core/enums.py` gives `Blocked` no outgoing transitions, so an application blocked
   by CAPTCHA/login/allowlist cannot resume; the user must create a new application path. Suggested: `Blocked -> Approved`.
3. **Ruff default rules.** `ruff check services/api` with current ruff reports ~600 style findings (mostly B008
   FastAPI `Depends` defaults, unsorted imports). CI blocks only on syntax/undefined-name rules.
4. **PyMuPDF is AGPL-3.0**, a required dependency (see `THIRD_PARTY_NOTICES.md`).
5. **Windows untested.** `scripts/windows/*.cmd` and the CI Windows job have never run on real Windows.
6. **Workflows are linear and in-process.** No branching, no external queue; a crash mid-step leaves the run `running`.
7. **Automation sessions are in-memory** and do not survive a restart.
8. **Cover letters are not persisted** (no table).
9. **No lane notes exist for lanes A, F, G**; behaviour there is documented only from code and tests.
10. **No live job-board, real-ATS or real-LLM-provider run has been performed.**
