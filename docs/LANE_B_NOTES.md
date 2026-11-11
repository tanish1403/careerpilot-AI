# Lane B notes (profile / documents / resume engine)

Deviations and decisions relative to `API_CONTRACT.md`:

- Extra fact categories `contact` and `summary` (confirming them updates the profile row). Typed
  rows are materialised on confirm; user-entered items via `/experiences` etc. create a confirmed
  fact + row immediately (the user typed them). Extracted facts are always `proposed`.
- `PATCH /facts/{id}` on a confirmed fact without `confirm:true` demotes it to `proposed`.
- Upload: `unsupported_type|corrupt_file|empty_file` -> 422 and nothing is stored; `too_large` -> 413;
  a valid scanned file with no OCR available is stored and its ParseRun fails with `[ocr_unavailable]`.
- Extra endpoints: `GET /facts/{id}`, `POST /facts/confirm-bulk {ids}`, `POST /profiles/import?mode=merge|replace`.
- `PUT /resumes/{id}/source` is scanned for forbidden TeX (`\write`, `\input`, `\catcode`, unknown
  packages...) -> 422 `code:"unsafe_latex"`. Claim markers `% cp:claim=<id>` in the source map lines
  to ResumeClaims; edited/unknown lines become `needs_confirmation`.
- Hooks for Lane D (all optional, default off): `documents.ingest.LLM_CALLABLE(prompt)->str|list`,
  `resume_engine.service.REWORD_FN(bullet, wrapped_jd)->str|None`. Integrator must check
  `allow_external_llm` consent before setting them.
- No migrations added. Cover letters are not persisted (no table).
