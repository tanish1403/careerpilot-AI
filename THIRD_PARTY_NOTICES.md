# Third-party notices

Licenses below were read from installed package metadata (`pip` / `importlib.metadata`) and from
`node_modules/*/package.json` in the build environment on 2026-11-11. This is a convenience list, not a
legal review: re-verify before redistributing. Transitive dependencies are not enumerated.

## Needs attention before distribution

- **PyMuPDF (`pymupdf`)**: dual-licensed AGPL-3.0 or Artifex commercial. It is a required dependency
  (PDF text extraction) and AGPL is stronger than this project's Apache-2.0. Running locally for yourself
  is fine; **redistributing a bundle or offering it as a network service has AGPL obligations**. Replacing it
  (for example with a permissively licensed parser) is an open item (see ADR 0006).
- **LaTeX / Tesseract / Chromium**: external programs invoked as tools (`xelatex`, `tesseract`,
  Playwright's Chromium). They are not bundled; their licenses are not reviewed here (unverified).
- **Playwright browser downloads** are fetched by `playwright install` and carry their own licenses (unverified).

## Python (services/api)

| Package | Version seen | License (from metadata) |
|---|---|---|
| fastapi | 0.162.2 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| sqlalchemy | 2.1.8 | MIT |
| alembic | 1.20.1 | MIT |
| pydantic | 2.14.3 | MIT |
| pydantic-settings | 2.16.2 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| python-multipart | 0.0.33 | Apache-2.0 |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| apscheduler | 3.11.3 | MIT |
| pymupdf | 2.1 | AGPL-3.0 or commercial (see above) |
| python-docx | 1.2.0 | MIT |
| striprtf | 0.0.35 | BSD-3-Clause |
| beautifulsoup4 | 4.15.0 | MIT |
| pytest (dev) | 9.2.0 | MIT |
| pytest-asyncio (dev) | 1.4.1.post1 | Apache-2.0 |
| playwright (optional `browser`) | 1.63.0 | Apache-2.0 |
| langgraph (installed in dev venv; not used by the workflow engine) | 1.2.20 | MIT |
| ruff, mypy (dev) | not installed here | unverified |
| pytesseract, pillow (optional `ocr`) | not installed here | unverified |
| litellm (optional `agents`; not used) | not installed here | unverified |

## JavaScript (apps/web)

All verified from installed `package.json` files.

| Package | Version | License |
|---|---|---|
| @fontsource-variable/bricolage-grotesque, hanken-grotesk, jetbrains-mono | 5.3.0 | OFL-1.1 (font files) |
| @radix-ui/react-dialog / -switch / -tabs | 1.3.1 / 1.4.1 / 1.2.1 | MIT |
| @tanstack/react-query | 5.107.1 | MIT |
| class-variance-authority | 0.7.1 | Apache-2.0 |
| clsx, react, react-dom, react-router-dom, tailwind-merge, zustand | see package.json | MIT |
| lucide-react | 1.70.0 | ISC |
| typescript | 6.0.3 | Apache-2.0 |
| vite, vitest, eslint, @eslint/js, typescript-eslint, eslint-plugin-react-hooks, globals, jsdom, postcss, autoprefixer, tailwindcss, openapi-typescript, @vitejs/plugin-react, @testing-library/*, @types/* | see package.json | MIT |

## Job-source terms

Connectors talk to public job-board endpoints (Greenhouse, Lever, Ashby) and user-supplied career pages.
Their terms of service are the user's responsibility; see `docs/JOB_SOURCES_AND_COMPLIANCE.md`.
