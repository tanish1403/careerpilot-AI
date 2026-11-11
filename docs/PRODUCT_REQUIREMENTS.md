# Product requirements

Scope as built. The original aspirational specification is in `docs/blueprint/` and is not a statement of status.

## Users and goals
A single job seeker running the app locally who wants a verified evidence library, tailored resumes that make
only supportable claims, ranked jobs from permitted sources, tracked applications, and interview/learning prep.

## Requirements and where they stand
| ID | Requirement | Status |
|---|---|---|
| R1 | Candidate owns data: export, backup, restore, delete | implemented (`/system/*`) |
| R2 | Extracted facts are `proposed` until user confirms; resumes cite confirmed evidence | implemented; unconfirmed/edited claims flagged `needs_confirmation` |
| R3 | Never submit applications automatically; submission requires a granted, fingerprint-checked approval and a manual confirm | implemented; enforced by tests |
| R4 | No secret ever returned or logged | implemented; walked by `h_safety_test.py` |
| R5 | Provider-neutral model routing by declared capabilities, with consent gate for external LLMs | implemented |
| R6 | Jobs record source, URL, first-seen, last-verified; expired jobs marked not deleted | implemented (mock-tested connectors) |
| R7 | Respect robots.txt; refuse login-walled platforms | implemented in `job_connectors/policy.py` |
| R8 | Scores explainable; unknown is never treated as satisfied | implemented |
| R9 | Windows without WSL | scripts provided; untested on Windows |
| R10 | Supervised autofill on allowlisted domains, stops at CAPTCHA/login/MFA | experimental (fixtures only) |
| R11 | Agent workflows with checkpoints and approval nodes | experimental (linear) |

## Non-goals
Multi-user hosting, mass-apply, CAPTCHA/login bypass, scraping LinkedIn/Indeed/Glassdoor, guaranteeing outcomes.
