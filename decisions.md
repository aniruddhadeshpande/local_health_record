# Decisions — Personal Health Report App POC (Phase 1)

Design team: BA, SA, TA, Security Engineer (2 rounds). Full positions and critiques: `docs/design-team/round{1,2}-*.md`.
Status legend: **Agreed** · **Pending TM** (needs Tech Manager decision) · **Residual risk**.

## D1. Local model — Agreed
- `medgemma:4b` (official Ollama tag), digest `9fe4e9a6c9bd`, gemma3 arch, 4.3B params, Q4_K_M, 3.3 GB, text + vision, 128K context.
- License: Health AI Developer Foundations Terms of Use (last modified 2024-11-15). Research/development model: output is **not a diagnosis**; UI shows a "not medical advice" disclaimer.
- Accessed only via the `LocalLLMClient` interface (Ollama implementation, structured output via the `format` JSON schema). Phase 2: an OpenAI-compatible vLLM implementation; it must reject non-TLS remote URLs.
- Measured accuracy / hardware: see D12 (spike).

## D2. Q1 Workflow framework — Agreed: plain Python + Anthropic SDK
The flows are fixed pipelines (extract → mask → store; analyse → update memory; chat turn). LangGraph and Deep Agents add an abstraction layer, extra dependencies and harder debugging, and an agent that chooses its own steps is harder to prove leak-free. Plain functions give one readable call path and one egress point. All four roles agreed.

## D3. Q5 Background jobs — Agreed: option (a), job table + single worker thread
- One daemon worker thread started in the FastAPI lifespan, polling a `jobs` table in SQLite. MedGemma on a 4-core CPU can only process one file at a time anyway.
- Redis was rejected: not installed, adds a process, and puts session/key state outside the API process. RabbitMQ is not justified.
- On restart, non-terminal jobs go back to `queued` and resume from their encrypted temp file (at most 2 retries, then `failed`).
- File job states: `queued → extracting → masking → stored → done`; `waiting_for_unlock` when the key is unavailable; `failed`.
- Analysis is one job per batch, enqueued when the user clicks **Analyse** after reviewing the extracted values (D13): `queued → analysing → done | blocked_pii | failed`.

## D4. Q3 Masking — Agreed: schema-first + rules + fail-closed guard
1. The single MedGemma extraction call returns a JSON schema in which identifiers go into dedicated fields (`patient_name`, `ids`, `lab`, `doctor`, `dob`, `contact`). These fields are never sendable.
2. A deterministic pass over every sendable field: exact and fuzzy (`rapidfuzz`) match against known profile and mapping values, plus regex patterns (phone, email, IDs, dates, addresses).
3. A pre-send PII guard scans the final serialised payload. It fails closed on any hit, any error or a missing mapping, and every call is audited.
- Placeholders are random per-profile tokens (`[LAB_1]`), never hashes of the real value. The mapping is stored encrypted, and placeholders are swapped back **on the server**; the browser never sees the map.
- Only structured fields go to Claude; free-text impressions stay local in Phase 1. A second MedGemma scrub pass was rejected because it doubles CPU time.
- Verification: a synthetic canary corpus and `qa_leak_probe.sh` must report zero leaks before the demo.
- **Residual risk:** re-identification from rare values plus age and gender. Mitigations: age band above 89; rare-panel tests are flagged.

## D5. Dates — Agreed
Dates go out only as day offsets from a fixed per-profile anchor (`T0+94d`); negative offsets are allowed for older reports, and T0 is never sent. The UI always shows real dates.

## D6. Q4 Long-term memory — Agreed
- One JSON document per profile with a fixed schema (conditions/trends, latest key values with offsets, notes). It contains no location, employer or person fields. It is capped at about 1,500 tokens, enforced in code.
- Claude returns a full replacement on each analysis; the previous version is kept for one-level rollback. The memory output is guard-scanned **before it is stored**.
- Chat folding: when there are more than 12 unfolded turns, the oldest 6 are folded into memory by `claude-haiku-5-5`, also through the guard. The last 6 turns are kept verbatim.

## D7. Claude usage — Agreed
- Models: `claude-sonnet-5-5` for analysis and chat, `claude-haiku-5-5` for folding; IDs set in config.
- Prompt caching applies to the static system prompt plus the memory block (minimum cacheable prompt is 512 tokens on Sonnet/Haiku 5.5, verified in the docs). Check `cache_read_input_tokens` to confirm caching is happening.
- Chat context = memory + latest masked report + last 6 turns.
- Only `ClaudeClient` imports `anthropic`. Every call (analysis, chat, memory, fold) runs through the guard, then the audit log, then the send.
- Anthropic API default retention is 30 days, with no training on API data (verified). Recorded as a residual risk in the README.

## D8. Keys and encryption at rest — Agreed
- **Key derivation:** Argon2id (m=64 MiB, t=3, p=2; parameters stored with the salt) turns the passphrase into a key-encryption key (KEK), which wraps a random data-encryption key (DEK) with AES-256-GCM. A successful unwrap is the passphrase check; there is no stored hash.
- **Passphrase:** at least 10 characters, no PIN. A forgotten passphrase means the data cannot be recovered, and registration says so (mandatory checkbox).
- **Encryption:** app-level AES-256-GCM on plain SQLite. Each row's sensitive data is one `enc_blob`, with a fresh nonce and AAD = table|row_id. Plaintext columns are limited to IDs, timestamps, status and MIME type. SQLCipher was rejected because `sqlcipher3-binary` has Linux x86_64 wheels only (verified).
- **Uploads:** read into memory (≤10 MB) and encrypted one-shot to `data/tmp/<uuid>.enc` with mode 0600; plaintext never reaches disk. Starlette's spool-to-disk threshold must be raised, or its temp directory moved to tmpfs. The encrypted temp file is deleted when the job finishes. The original file is never kept.
- `secure_delete=ON`. The README recommends full-disk encryption (SSDs can't securely delete; swap is a residual risk).

## D9. Profiles, sessions and API — Agreed except where marked
- **Profiles:** one profile per install. Login is `{passphrase}`, and register returns 409 if a profile already exists.
- **Network:** the API binds to 127.0.0.1 with `TrustedHostMiddleware`. Auth uses a 256-bit bearer token kept in `sessionStorage`, so no cookie and no CSRF exposure.
- **Logging and login:** request bodies, prompts and outputs are never logged. Five failed logins trigger exponential back-off.
- **Uploads:** 10 files per request, 10 MB per file, 10 pages per PDF; magic-byte allowlist; no `.xlsm`.
- **Rendering:** Claude and audit output is rendered as escaped text or safe markdown, never with `.html()`, plus a CSP.
- **Session (TM decision 2026-11-08):** the API token expires after 15 min idle. A **worker lease** keeps the DEK in process memory while the user has unfinished jobs, up to the 8 h absolute cap. Explicit logout wipes the DEK immediately and jobs move to `waiting_for_unlock`; encrypted temp files still unprocessed after 24 h are deleted and the job is marked `failed`.
- **Client serving (TM decision 2026-11-08):** the thin client lives in `frontend/` (plain HTML/CSS/jQuery, REST calls only) and FastAPI serves it with `StaticFiles` on the same origin. The app stays headless, with no CORS to secure.

## D10. Chat PII guard — Agreed
- Known profile and mapping values are masked automatically, and the UI says "we hid X".
- Unknown pattern hits return `422 needs_confirm` with highlighted spans. The message stays in the input box, and the user can click "Mask and send".
- A guard error returns 503 and nothing is sent.

## D11. Phase-2 vLLM server (not built) — Agreed requirements
TLS; API key or mTLS; private network or VPN (an IP allowlist alone is not enough); no prompt logging; disk encryption; files deleted after processing; no shared cloud GPU without a data processing agreement. The server sits inside the trust boundary because it sees unmasked files.

## D12. Q2 MedGemma accuracy and hardware — Measured (synthetic samples, 2026-11-08)
Full details are in `spikes/REPORT.md`.

| Route | Values | Units | Ref ranges | Time per page (4-core CPU) |
|---|---|---|---|---|
| Text PDF (2 files) | 24/24 | 24/24 | 24/24 | about 225 s |
| Scan, JPG or image-only PDF (2 files) | 24/24 | 20/24 | **0/24** | about 270 s |
| BMI Excel (1 file) | 6/6 rows | — | — | 104 s |

- **Memory:** the model uses about 4.8 GB RSS. Minimum is a 4-core CPU with 8 GB RAM (16 GB recommended); a GPU is optional, at about 2.3–3 GB VRAM.
- **Leaks:** 0 fake-identifier hits in the masked output.
- **Decisions taken from the spike, all refining existing tickets with no spec change:**
  - H/L flags are always computed locally; the model's flags are ignored because it made them up on scans.
  - Scans take units and reference ranges from a local reference table and are flagged "check this".
  - The test-name list needs aliases (one test was dropped wrongly).
  - Known identifiers are seeded from the profile plus a sweep of labelled header fields, because MedGemma often leaves `patient_name` and `doctor_name` empty.
  - MedGemma's output is kept short to save CPU time.
- **Caveat:** synthetic layouts only. Re-run on real de-identified samples before the demo.

## D13. Phase 1 scope extras — TM decision 2026-11-08
- **In scope:**
  - Privacy log screen ("What was sent to Claude").
  - Read-only review of extracted values with "check this" flags, then a manual **Analyse** button, so analysis starts when the user chooses rather than automatically.
  - "Delete my profile and data".
- **Out of scope:** hash-chained audit log. The SA's argument is accepted: a single user who owns the DB gains nothing from it, and append-only rows plus AES-GCM AAD are enough. This overrides Security requirement #14's `prev_hash`.
