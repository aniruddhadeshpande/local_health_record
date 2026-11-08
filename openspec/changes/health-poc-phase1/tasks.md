# Tasks

> Developer tickets (draft for TA refinement and assignment after approval). Each ticket names its verification: a curl script in `scripts/`, a manual check, or a command. No test frameworks. Ticket IDs = `X.Y`.

## 1. Scaffolding

- [ ] 1.1 Create `backend/` (uv project, deps per design.md), `frontend/`, `scripts/`, `data/` (gitignored), `.env.example` (ANTHROPIC_API_KEY, OLLAMA_URL, model IDs); verify `uv run uvicorn app.main:app --host 127.0.0.1` starts and `GET /api/health` returns 200
- [ ] 1.2 `config.py` with limits (10 files, 10 MB, 10 pages), timeouts (15 min idle / 8 h), model IDs, `LocalLLMClient` URL validation (reject non-TLS remote); verify startup fails with a clear error when `OLLAMA_URL=http://10.0.0.5:11434`
- [ ] 1.3 `main.py`: bind 127.0.0.1, TrustedHostMiddleware (localhost/127.0.0.1), serve `frontend/` via StaticFiles, no body logging, debug off; send CSP as a header (`default-src 'self'; frame-ancestors 'none'`, no inline script), `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on `/api/*`; force `anthropic`/`httpx`/`uvicorn.access` loggers to WARNING and refuse to start if `ANTHROPIC_LOG` is set; custom validation handler that returns field names only; refuse to start if `.env` is not 0600 (SEC F5, F10); verify `curl -H 'Host: evil.com'` is rejected, `/` serves `index.html`, `curl -I` shows the headers, and a 422 response does not echo the submitted value

## 2. Crypto, DB and profile (user-profile, data-protection)

- [ ] 2.1 `crypto.py`: Argon2id KEK (m=64 MiB, t=3, p=2), DEK wrap/unwrap, `enc/dec` with AES-256-GCM and AAD `table|row_id`; verify with a `scripts/check_crypto.py` that round-trips, and fails on tampered blob and on swapped AAD
- [ ] 2.2 `db.py`: DDL for all tables in design.md, `secure_delete=ON`; verify `sqlite3 data/app.db .schema` matches design, plaintext columns limited to IDs/timestamps/status/mime
- [ ] 2.3 `POST /api/register` (≥10-char passphrase, ack required, 409 if exists) and `POST /api/login` / `logout` (generic errors, back-off after 5 fails); keep the back-off counter in an `auth_state` row and run key derivation behind a lock (SEC F11); verify via `scripts/qa_auth.sh` (success, short passphrase, missing ack, 409, wrong passphrase, back-off, back-off still applies after restart)
- [ ] 2.4 `sessions.py`: 256-bit bearer token, 15 min idle (polling excluded), 8 h absolute, logout wipes DEK, worker lease covering only the jobs unfinished at expiry, never authenticating a request, zeroing the bytearray on logout (SEC F6); verify the old token is rejected while the lease is active, and `scripts/qa_session.sh` with `IDLE_TIMEOUT=60s` override shows expiry, and polling-only does not extend
- [ ] 2.5 `DELETE /api/profile` with passphrase re-confirm (subject to back-off): stop the worker, wipe sessions and leases, close connections, delete `app.db`, `-wal`, `-shm`, `-journal` and `data/tmp/*`, recreate an empty DB, show the 30-day Anthropic retention notice (SEC F7); verify `scripts/qa_delete.sh`: wrong passphrase deletes nothing; after a correct one, `ls data/` shows only a fresh DB, and registration is available again
- [ ] 2.6 Manual check documented in `docs/qa/checklist.md` §Profile: open `data/app.db` in `sqlite3` and confirm no readable name/age/gender

## 3. Upload and job worker (report-ingestion, data-protection)

- [ ] 3.1 `POST /api/uploads`: reject when `Content-Length` exceeds 105 MB and count streamed body bytes in middleware; set `MultiPartParser.spool_max_size` above the request cap (SEC F2); magic-byte allowlist (PDF/PNG/JPEG/XLSX/CSV); reject `.xlsm`, and XLSX files containing `vbaProject.bin` or a macro content type, or exceeding the uncompressed-size, entry-count or ratio caps (use defusedxml); keep Pillow's `MAX_IMAGE_PIXELS` cap (SEC F8); 10 MB / 10 files / 10 PDF pages, per-file rejection reasons, read to memory, encrypt to `data/tmp/<uuid>.enc` (0600), raise Starlette spool threshold; returns 202 immediately; verify `scripts/qa_upload.sh` (mixed valid/invalid batch, renamed exe, timing < 1 s) `ls /tmp` shows no plaintext spool during a 9 MB upload or an oversized 120 MB request, and a zip-bomb XLSX and an XLSX renamed from `.xlsm` are both rejected
- [ ] 3.2 `worker.py`: single daemon thread, job state machine (design.md), `waiting_for_unlock`, fixed `error_code` values only, never exception text (SEC F5); restart recovery (attempts>2 → failed), startup temp sweep, 24 h unlock timeout; verify `scripts/qa_jobs.sh` (poll states; kill API mid-`extracting`, restart, log in, job resumes)
- [ ] 3.3 `GET /api/batches/{id}`, `GET /api/jobs?ids=` (no idle reset); verify via `qa_jobs.sh` polling output

## 4. Local extraction — Agent 1 (report-ingestion)

- [ ] 4.1 `llm/local.py`: `LocalLLMClient` protocol, `OllamaClient` (`/api/chat`, `format`=JSON schema, temperature 0), `OpenAICompatClient` stub (TLS-only); verify `scripts/check_ollama.py` returns schema-valid JSON from `medgemma:4b`
- [ ] 4.2 `pipeline/ingest.py`: text PDF (pypdfium2 text), scanned PDF/image → PNG ≤1600 px, XLSX/CSV rows; verify on synthetic samples from 6.4 that each route produces non-empty input
- [ ] 4.3 `pipeline/extract.py` + `prompts/extract.txt`: extraction schema (identifier fields + `tests[]`/`measurements[]`), H/L flags computed locally from value vs range (model flags ignored), vision-route units/ref ranges from a local reference table + "check this", compact output (omit null identifiers) (spike D12); plausibility + vision-route "check this" flags, patient-name mismatch flag; verify on synthetic samples: values match the generator's ground truth file (record accuracy in `docs/qa/results.md`)
- [ ] 4.4 Delete temp file at `done`/final `failed`; verify `data/tmp/` empty after `qa_upload.sh` + `qa_jobs.sh`

## 5. Masking (pii-masking)

- [ ] 5.1 `pipeline/mask.py`: tokenise identifier fields into `pii_mapping` (random per-profile, stable per value), drop narrative, structured-only masked record; verify synthetic report's masked JSON contains only tokens/structured fields
- [ ] 5.2 Relative dates `T0±Nd` with per-profile anchor (negative allowed); age `90+` band; verify older-report upload yields negative offset and review still shows real date
- [ ] 5.3 Known-value (exact + rapidfuzz) + regex scan (phone, email, ID-like, dates, address, PIN code) over sendable fields. Strict field formats (SEC F1): test names normalised against a local `test_names.txt` list with aliases, e.g. "Vitamin D (25-OH)" (spike D12); known-value list seeded from the profile plus a regex sweep of labelled header fields ("Patient Name:", "Referred by:") in the raw text, otherwise a proper-noun check; reference ranges and values numeric or range patterns only; units from an allowlist; flags an enum; a field that fails its format is dropped and flagged. Verify a synthetic report with a misspelt name, a stray phone number, a canary in a test name and a lab name in a reference range is fully tokenised or dropped
- [ ] 5.4 Server-side swap-back helper used by display endpoints only. It is excluded from `/api/audit`, `sent_masked` and "Sent to Claude", and payload builders read masked rows directly (SEC F3). Verify no API response contains a mapping table, and the Privacy log shows placeholders (`grep` over `qa_*.sh` outputs)

## 6. Claude egress, guard and audit (claude-egress)

- [ ] 6.1 `guard.py`: scan final serialised payload (known values exact+fuzzy, mapping values, regex), fail closed on hit/error/missing mapping, return rule IDs and spans (never values); a blocked payload is stored with each hit replaced by `[REDACTED:<rule>]` (SEC F4); verify `scripts/check_guard.py` with planted name/phone/email → blocked, clean → pass, forced exception → blocked
- [ ] 6.2 `llm/claude.py` `ClaudeGateway`: only module importing `anthropic`; serialise → guard → audit (encrypted masked payload, sha256, purpose, decision, rule IDs) → send → record `sent` or `send_failed` (SEC F15); never set `metadata.user_id`; payloads never contain file names or internal IDs (SEC F14); verify `grep -r "import anthropic" backend/` returns only this file
- [ ] 6.3 `GET /api/audit` (Privacy log data); verify `scripts/qa_audit.sh` lists sent and blocked entries with masked payloads and no raw values
- [ ] 6.4 `scripts/make_canary_samples.py` (synthetic blood PDFs, text and scanned, and a BMI XLSX, with canaries planted in the header (name, MRN, DOB, phone, lab, doctor), a test name, a reference range and the file name, plus a ground-truth file) and `scripts/qa_leak_probe.sh`. The probe runs the full pipeline and searches masked reports, all audit payloads, app logs, `/tmp`, `data/tmp`, raw `app.db*` bytes and the Ollama log for the canaries (SEC F13). Verify the probe reports 0 hits

## 7. Analysis and memory — Agent 2 (health-analysis)

- [ ] 7.1 `GET /api/batches/{id}/review` (read-only values, real dates, flags, mismatch warning) and `POST /api/batches/{id}/analyse`; verify `scripts/qa_analysis.sh` shows no audit entry before Analyse, one after
- [ ] 7.2 Analysis job + `prompts/analyse.txt`: masked reports + memory + age/gender → `claude-sonnet-5-5` with cached system+memory prefix; output = analysis (summary, out-of-range, trends with day intervals, doctor questions, disclaimer, no diagnosis) + proposed memory; verify `qa_analysis.sh` response has all sections and audit payload has only masked data/age/gender
- [ ] 7.3 `memory.py`: fixed schema (no location/employer/person fields), ~1,500-token cap, full rewrite, rollback copy, notes limited to 10 entries of at most 120 characters, guard scan plus proper-noun check before storing, rejection audited as blocked (SEC F9), "memory updated" flag; verify `scripts/check_memory.py` rejects a memory containing a city or person name, keeps the previous version, and an audit row exists
- [ ] 7.4 `blocked_pii` path + `POST /api/analyses/{job_id}/retry {mask_spans}`, accepting only spans the server recorded (SEC F15); verify a forged span is rejected, and by planting a canary in a masked record: job → `blocked_pii`, retry with spans → sent clean
- [ ] 7.5 Trend check: upload a second synthetic batch with the same tests; verify analysis states direction, magnitude and day interval (`qa_analysis.sh --second`)

## 8. Chat (chat-assistant)

- [ ] 8.1 `POST /api/chat`: auto-mask known values (`hidden[]`), `422 needs_confirm` with spans for unknown patterns, `confirm_mask` re-scan, `503` on guard error; verify `scripts/qa_chat_guard.sh` (name → masked 200; phone → 422; confirm → 200 with token; forced error → 503) and audit shows no raw values
- [ ] 8.2 Context assembly (system+memory cached, latest masked report, last 6 turns), swap-back of reply, masked encrypted storage, `GET /api/chat/history` with "Sent to Claude" text; verify after 20 turns the latest audit payload holds ≤6 prior turns and `cache_read_input_tokens > 0` on the second call
- [ ] 8.3 Fold: >12 unfolded turns → oldest 6 + memory → `claude-haiku-5-5` via Gateway, guard-before-store; verify Privacy log shows a `fold` entry and memory stays ≤ cap

## 9. Thin client (all capabilities)

- [ ] 9.1 `index.html`/`app.js`/`style.css` (jQuery, no inline script so it works under the CSP header, text-only rendering — no `.html()` on model/audit data): register (strength hint, no-recovery checkbox), login, logout; verify manually per checklist §UI-Auth
- [ ] 9.2 Upload screen with per-file status polling (3 s), rejection reasons, "Paused – log in to continue"; verify manually
- [ ] 9.3 Review table with "check this" badges, mismatch warning, Analyse button; analysis and memory views with "Memory updated" notice; disclaimer visible without scrolling; verify manually
- [ ] 9.4 Chat screen: "we hid X" notes, highlighted spans with draft kept in input, "Mask and send", collapsible "Sent to Claude"; verify manually
- [ ] 9.5 Privacy log screen and Delete-my-data flow; verify manually; verify a Claude reply containing `<script>` renders as text

## 10. Docs and handover

- [ ] 10.1 `README.md`: setup with uv, install Ollama, `ollama pull medgemma:4b` (or HF gated weights + token), `.env`, run; hardware notes from spike; warn never to set `OLLAMA_DEBUG`, and keep Ollama on 127.0.0.1; Phase-2 vLLM requirements (SEC F12); residual risks (swap, malware, 30-day Anthropic retention, full-disk encryption recommended); verify a fresh clone follows README to a running app
- [ ] 10.2 Update `decisions.md` D12 with spike measurements (accuracy per input type, latency, peak RAM, min hardware); verify section has numbers

## 11. Integration checks (QA, Code Review, Security Test)

- [ ] 11.1 Code Reviewer: review full diff against specs and design (single egress, no body logging, no `.html()`, SOLID only where useful); record findings in `docs/qa/code-review.md`
- [ ] 11.2 QA: run every `scripts/qa_*.sh` and the manual checklist `docs/qa/checklist.md` end-to-end (register → upload mixed batch → review → analyse → second batch trend → chat → privacy log → delete); record pass/fail in `docs/qa/results.md`
- [ ] 11.3 Security Tester: leak probe (0 hits), DB/log/tmp inspection for plaintext, remote-bind and Host-header checks, back-off, XSS payload in chat reply, guard fail-closed; record in `docs/qa/security-test.md`

## Workflow follow-up

- After implementation: `/opsx:verify` (if enabled) or manual verification against specs, then produce HTML artifacts (code documentation + sequence diagrams: registration/login, upload→extraction→masking→storage, analysis+memory, chat with PII guard; local vs Claude marked).
- Archive the change with `/opsx:archive` after Tech Manager sign-off, which merges delta specs into `openspec/specs/`.
