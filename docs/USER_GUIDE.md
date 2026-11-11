# User guide

Open the UI (http://localhost:5173) and create the local account. Check **System** for tool availability
(LaTeX, Tesseract, Playwright) and **Overview** for feature status.

1. **Profile**: upload a resume (Documents) or enter data. Extracted items are `proposed`; confirm, edit or reject each.
   Only confirmed facts feed resumes and application answers.
2. **Models** (optional): add a provider (key is write-only, stored encrypted). Documents are never sent to a
   non-local provider unless you enable `allow_external_llm`. Without a provider, rule-based paths are used.
3. **Jobs / Integrations**: add a source (experimental) or import a job by URL or pasted text. Refused sites tell you to apply at the source.
4. **Matching**: score jobs; open a match to see eligibility, factor contributions and gaps. Tune weights in the matching config.
5. **Resume**: generate a tailored version per job, review flagged claims, edit LaTeX, compile, diff against the original.
6. **Applications**: create from a job, prepare (resume + drafted answers from confirmed facts), approve the resume,
   optionally start a supervised autofill session (experimental; allowlisted domains only; stops at CAPTCHA/login/MFA;
   sensitive questions are left to you). Then `request-submit`, grant the approval, submit **yourself** on the employer
   site, and click confirm-submitted. There is no way to submit from CareerPilot.
7. **Learning / Interviews / Research / Planner**: study plans and revisions; mock interviews and company briefs (experimental); scheduled tasks and digest.
8. **System**: backups, restore, export (secrets excluded), delete all data (type `DELETE`).
