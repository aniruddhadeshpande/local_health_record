# Proposal

## Why

The company needs evidence that health reports can be analysed with AI while personal data never leaves the user's machine. This POC runs extraction and masking on a local model (MedGemma 4B). Only de-identified data, plus age and gender, goes to Claude, which provides analysis, long-term memory and chat. A fail-closed guard and an audit trail the user can see enforce that boundary.

## What Changes

- New local Python API (FastAPI, bound to 127.0.0.1). It serves a thin HTML/CSS/jQuery client from `frontend/` on the same origin.
- **Registration:** one local profile (name, age, gender), protected by a passphrase of at least 10 characters. The passphrase derives the key that unlocks an encryption key for all data. Nothing can be recovered if it is forgotten.
- **Upload:** several blood-report PDFs, images or BMI Excel sheets at once. The upload returns immediately; a single background worker processes the files, and the UI polls for status.
- **Local extraction and masking:** MedGemma 4B via Ollama, accessed through a swappable `LocalLLMClient`. Identifiers become per-profile placeholder tokens, and dates become day offsets. Original files are deleted after processing. Extracted data, masked reports and the token mapping are stored encrypted.
- **Review step:** the user checks a read-only table of extracted values with "check this" flags, then clicks **Analyse**.
- **Analysis:** Claude (`claude-sonnet-5-5`) analyses the masked reports with age and gender. It produces and maintains a bounded, schema-fixed long-term memory, which is stored encrypted locally and used for trend-aware analysis of later uploads.
- **Chat:**
  - The chat assistant uses memory, the latest masked report and the last few turns as context, with prompt caching on the stable block.
  - Every outgoing message passes a local PII guard: known values are masked automatically, and unknown pattern hits need the user to confirm "Mask and send".
  - Older turns are folded into memory with `claude-haiku-5-5`.
  - Placeholders are swapped back to real values on the server before display.
- **Privacy:**
  - A single egress gateway to Claude with a fail-closed pre-send guard and an encrypted, append-only audit log.
  - A **Privacy log** screen shows exactly what was sent.
  - **Delete my profile and data** is available.
- A "not medical advice" disclaimer appears throughout the UI.
- Deliverables beyond code: README (setup and model download), QA checklist and curl scripts, a canary leak-probe script.

## Out of Scope (Phase 1)

- Phase-2 company vLLM server: only the `LocalLLMClient` seam and its security requirements are recorded.
- Multiple profiles per install, multi-device sync, cloud backup, mobile apps.
- Passphrase recovery or reset. Passphrase change is not built, although the key design allows it later.
- Editing extracted values. The review step is read-only.
- Sending free-text report narrative to Claude; only structured fields go.
- Non-English, handwritten or non-blood/BMI report types; macro-enabled Excel (`.xlsm`).
- Streaming chat responses, notifications, hash-chained audit log, automated test frameworks.
- Clinical validation. MedGemma and Claude output is not a diagnosis.

## Capabilities

### New Capabilities
- `user-profile`: registration, passphrase login and lockout back-off, session lifetime (idle timeout and worker lease), profile and data deletion.
- `data-protection`: key derivation and wrapping, field-level encryption at rest, encrypted temp files, deletion of originals, localhost-only hardening, no logging of sensitive bodies.
- `report-ingestion`: multi-file upload with limits and type checks, background job queue and states, restart recovery, status polling, local extraction through `LocalLLMClient`, read-only review of extracted values.
- `pii-masking`: identifier classes, placeholder tokenisation and encrypted mapping, relative-date conversion, server-side placeholder swap-back, canary leak test.
- `claude-egress`: single gateway to Claude, fail-closed pre-send guard, allowed fields (masked data, age and gender), audit log and Privacy log screen.
- `health-analysis`: user-triggered batch analysis, structured long-term memory (schema, size cap, update and guard-before-store), trend-aware re-analysis, disclaimer.
- `chat-assistant`: chat context assembly, prompt caching, chat PII guard flow (auto-mask, confirm-mask, block), fold of old turns into memory, encrypted chat history.

### Modified Capabilities
- None (greenfield project).

## Impact

- New code: `backend/` (FastAPI app, worker, services), `frontend/` (static HTML/CSS/jQuery), `scripts/` (curl QA scripts, leak probe), `README.md`.
- Dependencies:
  - Python packages: fastapi, uvicorn, python-multipart, anthropic, httpx, pypdfium2, Pillow, openpyxl, cryptography, argon2-cffi, rapidfuzz.
  - External services: Ollama with `medgemma:4b`, and an Anthropic API key in `.env`.
- Local data: `data/app.db` (SQLite with encrypted blobs) and `data/tmp/` (encrypted temp files).
- External: Claude API, which receives masked data only. Anthropic's default API retention is 30 days, recorded as a residual risk.
- Rationale for every choice is in `/decisions.md`.
