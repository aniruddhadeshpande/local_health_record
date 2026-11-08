# Round 2 – Solution Architect critique

> Intended path: `docs/design-team/round2-sa.md` (plan mode blocked it; copy verbatim).
> Lens: architecture and simplicity. One process, one DB, one egress choke point.

## 1. Pushback (complexity beyond POC needs)

| # | Point | Who | Argument | Resolution |
|---|---|---|---|---|
| P1 | Hash-chained audit log | Sec | There is one user, and that user owns the DB. Tamper-evidence against yourself proves nothing. AES-GCM with row AAD already detects edited rows. Row deletion only matters for malware, which Sec has put out of scope. | Drop `prev_hash`. Keep append-only inserts. |
| P2 | `/dev/shm` tmpfs fallback | Sec | pypdfium2, openpyxl (`BytesIO`) and Ollama (base64) all take bytes, so no library needs a path. tmpfs also isn't portable to macOS or Windows. | Decrypt into memory only. A library that needs a path gets replaced. |
| P3 | Per-column `enc` | TA | Separate encrypted name/age/gender/report_date columns multiply the AAD and helper code. | Use Sec's model: one `enc_blob` (JSON) per row, with only plaintext metadata as columns. |
| P4 | Masking as 3–4 layers, including a separate MedGemma span pass | Sec, TA | Sec's own structured-output rule is the strongest control. A second MedGemma call per file doubles CPU latency (1–3 min/page). | Layers: (1) the single extraction call puts identifiers in schema fields (`patient_name`, `lab`, `doctor`), which are never sendable. (2) Deterministic known-value + regex pass. (3) Guard on the final payload. Free-text fields are excluded from Phase 1, so no model scrub is needed. |
| P5 | `keyfile.json` vs `users.wrapped_dek` | Sec, TA | Two places to store key material. | Store `wrapped_dek`, salt and params in the `users` row. Keep DEK/KEK: about 10 lines, and it avoids re-encryption later. No separate argon2 verifier: a successful unwrap is the check (TA and Sec agree). |
| P6 | Two chat stores (masked + display) | Sec | Doubles the stored PHI. | Store masked only and re-hydrate on read. |
| P7 | Multi-profile user picker, `GET /users` | TA | BA recommends a single profile. The picker adds an endpoint and UX for no demo value. | One profile per install. |
| P8 | Frontend on `http.server :5500` + CORS | TA | A second server plus a CORS surface. | Serve via FastAPI `StaticFiles` from the same origin (Sec's suggestion). Bearer token in `sessionStorage`, plus `TrustedHostMiddleware`. |

## 2. Consistency fixes

- **Job states** (BA, TA and Sec each listed different sets). Ingest: `queued → extracting → masking → done | failed`, plus `waiting_for_login`. Analysis: `queued → analysing → done | failed | blocked_pii`. Drop `stored` (internal) and `locked` (same as `waiting_for_login`).
- **Restart:** I concede to TA. Non-terminal jobs go back to `queued` (attempts+1, >2 → `failed`) and resume from the encrypted temp file. Use one worker thread from lifespan, not `BackgroundTasks`.
- **Timeouts (15 vs 30 min):** 15 min idle and 8 h absolute. Job polling does **not** reset the idle timer. A job already running keeps the DEK until it finishes, then the session locks. Queued jobs wait for login.
- **Memory size:** hard cap of 1,500 tokens, full-replacement rewrite. Folding follows TA: when unfolded turns > 12, fold the oldest 6 and keep the last 6 verbatim.
- **Models:** `claude-sonnet-5-5` for analysis and chat, `claude-haiku-5-5` for folding. IDs live in config.
- **Prompt cache (verified):** current docs list a **512-token minimum for Sonnet 5.5 and Haiku 5.5**, down from 1,024 on Sonnet 4.5/4.6/5 and 4,096 on Haiku 4.5. The static system prompt plus memory will likely clear 512, so caching should actually hit. Keep the blocks byte-stable. Below the minimum, caching silently no-ops; check `cache_read_input_tokens`.
- **Chat policy:** adopt Sec's rule, which already covers BA's mask-by-default. Known values are auto-masked. An unknown pattern is blocked, with a "mask and send" button and a visible "Sent to Claude" view.
- **Dates:** a single rule, day offsets from the first report (`T0+94d`), negative allowed for older uploads. No month/year variant.
- **Upload limit:** 10 MB per file (BA), 10 files per request.
- **Re-hydration:** I concede to TA. Swap tokens back on the server and never ship the token map to JS.

## 3. Accepted (cheap and essential)

Argon2id with m=64 MiB/t=3, a passphrase of at least 10 characters (no PIN), and no recovery, with a warning at registration. Fail-closed guard. Fuzzy match via `rapidfuzz`. Age bands above 89. Magic-byte checks and a zip-bomb cap. `secure_delete=ON`. Never log bodies. A synthetic canary leak corpus plus `qa_leak_probe.sh`. BA's "What was sent to Claude" screen (`GET /api/audit`, US-9/19). Structured-only egress.

## 4. Concessions from my Round 1

- A single worker thread replaces `BackgroundTasks`.
- Jobs resume after a restart instead of being marked `failed`.
- Re-hydration happens on the server, not the client.
- The "~1,024/4,096 tokens" caching note is corrected to 512.
- The user-confirms-extracted-values step moves to a stretch goal.

Sources: [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Sonnet 5.5 migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide), [Haiku 5.5 overview](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
