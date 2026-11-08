# Security Review: health-poc-phase1

Reviewer: Security Engineer. Inputs: proposal, design, tasks, specs/*, `/decisions.md`, brief, `round2-security.md` §4. TM overrides applied: 15 min idle with worker lease, same-origin static client, hash chain out (#14 `prev_hash` dropped).

## 1. Verdict
**Approve with fixes.** The architecture is sound. F1 and F2 (High) must be folded in before implementation starts. The Med findings can be fixed as text edits to the tickets.

## 2. Coverage (§4 requirements)

| # | Requirement | Covered |
|---|---|---|
| 1 | Single `anthropic` import, guard→audit→send | egress "Single egress path"; task 6.2 |
| 2 | Final-payload scan, fail closed | egress "Fail-closed guard"; 6.1 |
| 3 | Structured/masked only | pii "Structured-only"; 5.1 (**F1**) |
| 4 | Relative dates, no IDs/names | pii "Relative dates", "Identifier classes"; 5.2 |
| 5 | Memory schema + guard before store | analysis "Structured memory"; 7.3 (**F9**) |
| 6 | Argon2id ≥64 MiB/t=3, wrapped DEK | data-prot "Passphrase-derived key"; 2.1 |
| 7 | ≥10 chars, no-recovery warning | user-profile "Registration"; 2.3 |
| 8 | AES-GCM, fresh nonce, AAD | data-prot "Encryption at rest"; 2.1 (AAD = table\|row_id, one blob per row: accepted) |
| 9 | No plaintext upload on disk | data-prot; 3.1 (**F2**) |
| 10 | DEK in memory only, timeouts | data-prot "Data key"; user-profile "Session", "Worker lease"; 2.4 (**F6**) |
| 11 | 127.0.0.1, same origin, TrustedHost, 256-bit token | data-prot "Local-only"; 1.3, 2.4 |
| 12 | Magic bytes, limits, zip-bomb, no xlsm | ingestion "Upload validation"; 3.1. **GAP: zip-bomb cap** (**F8**) |
| 13 | No body logging, Ollama local | data-prot "No sensitive logging"; 1.3 (**F5**) |
| 14 | Audit fields, no matched values | egress "Audit log"; 6.2 (`prev_hash` out by TM) (**F4**) |
| 15 | Authenticated Privacy log | egress "Privacy log screen"; 6.3, 9.5 |
| 16 | Escaped rendering | data-prot "Safe rendering"; 9.1, 9.5 (**F10**) |
| 17 | Server-side swap-back | pii "Server-side swap-back"; 5.4 (**F3**) |
| 18 | Back-off, generic errors | user-profile "Login back-off"; 2.3 (**F11**) |
| 19 | API key in `.env` 0600, gitignored | data-prot "No sensitive logging"; 1.1. Permission check not verified (**F5**) |
| 20 | Canary leak probe = 0 | pii "Canary leak test"; 6.4 (**F13**) |
| 21 | README FDE and residual risks | 10.1 |
| 22 | Phase-2 client rejects non-TLS remote | ingestion "Swappable endpoint"; 1.2, 4.1 (**F12**) |

## 3. Findings

| ID | Sev | Location | Issue | Required fix |
|---|---|---|---|---|
| F1 | High | pii-masking "Structured-only masked output"; task 5.3 | `test_name`, `unit`, `reference_range` and `flag` are free strings copied from the document. If MedGemma misplaces a lab or doctor name ("Ref: Apollo Labs", "Dr X panel") and it is not in the mapping, the known-value scan and the regexes miss it. | Add: "Sendable string fields SHALL match strict grammars: `reference_range` matches `^[<>≤≥]?\s*\d+(\.\d+)?(\s*[-–]\s*\d+(\.\d+)?)?$` or it is dropped; `unit` is checked against an allowlist; `flag` is an enum (`H`/`L`/`N`/`crit`); `test_name` is ≤60 chars, has no digits beyond those in known analyte names, and is normalised against a local analyte list. A name not on the list is flagged 'check this' and sent only after a proper-noun/capitalised-token check passes." Task 5.3 verifies this with a canary in a test name and in a reference range. |
| F2 | High | design pipeline step 1; task 3.1 | Raising the spool threshold to "above 10 MB" still spools an oversized file (the 12 MB scenario), or any file once the multipart total passes the threshold, to OS temp as plaintext *before* the size check. The `/dev/shm` fallback can swap. | Specify: "Reject on `Content-Length` > 105 MB and stream-count the body in middleware, aborting over the cap. Set `MultiPartParser.spool_max_size` (or a custom parser) above the request cap so no part ever spools." Task 3.1 verifies with a 12 MB file and a 10×9.9 MB batch while watching `/tmp` (`inotifywait`). |
| F3 | Med | task 5.4 vs chat "Swap-back", egress "Privacy log" | Ticket 5.4 says swap-back applies to "every read endpoint". Applied to `/api/audit`, `sent_masked` or the "Sent to Claude" view, it shows real values as if they had been sent, which hides leaks. Internal callers could also send swapped-back memory. | Change 5.4 to: "...used by user-facing read endpoints EXCEPT `/api/audit`, `sent_masked` and the 'Sent to Claude' view, which return the stored masked text verbatim. Context builders read masked rows directly and never call swap-back." |
| F4 | Med | egress "Audit log", "Privacy log screen" | A blocked attempt stores "the payload that would have been sent". By definition it contains the real value, which breaks #14. | Add: "For `blocked`, the stored payload SHALL have each hit span replaced by `[REDACTED:<rule_id>]`. The SHA-256 is taken over the original payload. Recovery highlighting is computed live from `masked_reports`, never from the audit row." |
| F5 | Med | data-prot "No sensitive logging"; 1.3 | Leak paths not covered: `ANTHROPIC_LOG=debug` and httpx debug log full prompts; pydantic `ValidationError` strings embed `input_value`; FastAPI's default 422 echoes request bodies (passphrase); job error text could carry values; `OLLAMA_DEBUG` logs prompts. | Add: "At startup, force the `anthropic`, `httpx` and `httpcore` loggers to WARNING and refuse to start if `ANTHROPIC_LOG` is set. Use a custom validation handler that returns field names only. `jobs.error_code` is an enum, and logged exceptions record only type and module. Never set `metadata.user_id`. Refuse to start if `.env` is not 0600. README warns against `OLLAMA_DEBUG`." |
| F6 | Med | user-profile "Worker lease"; design "Worker lease" | The design's "until it is idle" is ambiguous. The lease could be kept alive by queuing more jobs, or reused to authorise requests. | Specify: "The lease covers only the job IDs that are non-terminal when the token expires. New jobs do not extend it. It is released when the last of those jobs reaches a terminal state, at 8 h, or on logout. The lease never authenticates API requests and cannot mint a token. Logout zeroes the shared `bytearray` in place." Task 2.4 verifies release. |
| F7 | Med | user-profile "Delete"; task 2.5 | Deleting rows and running VACUUM leaves `-wal`, `-shm` and `-journal` files, and an in-flight worker job could write after the delete. The passphrase check is an unthrottled oracle. | Specify: "Stop the worker and abort the current job; wipe sessions and leases; close all connections; unlink `app.db`, `app.db-wal`, `app.db-shm`, `app.db-journal` and `data/tmp/*`; recreate an empty DB. The delete passphrase check shares login back-off. The UI notes the 30-day Anthropic retention." Task 2.5 verifies with `ls data/`. |
| F8 | Med | ingestion "Upload validation"; 3.1 | **GAP #12:** no zip-bomb cap. `.xlsm` is rejected by extension only, and a renamed `.xlsm` has the XLSX signature. No image or XML bomb limits. | Add: "XLSX: ≤50 MB uncompressed, ≤1000 entries, ratio ≤100. Reject if `vbaProject.bin` exists or `[Content_Types].xml` contains `macroEnabled`. Add `defusedxml`. Keep Pillow `MAX_IMAGE_PIXELS`; cap the PDF render at 1600 px." |
| F9 | Med | analysis "Structured memory"; 7.3 | The free-text "chat-derived notes" field can hold a city or person name, which the known-value and regex guard cannot detect. Task 7.3's verification has no mechanism behind it. | Specify: "Notes: ≤10 items of ≤120 chars each. Store-time check rejects capitalised non-analyte tokens not on the allowlist (simple proper-noun heuristic) plus the guard. On rejection the previous memory is kept and the event is audited as `blocked`." |
| F10 | Low | 9.1 only; no spec | CSP exists only as a `<meta>` tag in a ticket. A meta tag cannot set `frame-ancestors`. PHI responses can land in the browser cache. | Add to data-prot: response headers `Content-Security-Policy: default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`, plus `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` on `/api/*`. |
| F11 | Low | user-profile "Login back-off" | The counter lives in memory, so a restart resets it. Parallel logins each allocate 64 MiB for Argon2. | Persist `fail_count` and `next_allowed_at` in a plaintext `auth_state` row. Keep a single global counter. Serialise KDF calls behind a lock. |
| F12 | Low | design; README | D11's Phase-2 vLLM requirements are not carried into design or README. The "localhost exempt" parsing is undefined. | Add a design section that copies D11. Exempt only a parsed hostname in {`127.0.0.1`, `::1`, `localhost`}. Never disable TLS verification. |
| F13 | Low | task 6.4 | The probe greps only masked reports and the audit. | Plant canaries in test names, reference ranges and file names as well. Also grep app logs, `/tmp`, `data/tmp`, the raw `app.db*` bytes and the Ollama log. |
| F14 | Low | egress "Allowed outbound content" | File names and internal IDs are not explicitly excluded. | Add "file names, job, batch and row IDs" to the never-included list. |
| F15 | Low | design `ClaudeGateway`; 7.4 | The audit row says `sent` even if transmission fails. Client-supplied `mask_spans` could be arbitrary. | Update the audit row's outcome after `create()` (`sent`/`send_failed`). Accept only spans that match the server-recorded hits. |

## 4. Residual risks accepted for the POC
- The DEK cannot be zeroised in Python; swap and hibernation files. Mitigation: README recommends full-disk encryption.
- Malware running as the same OS user, or a local process calling the API while a token is valid.
- The DEK stays in memory during the worker lease (≤8 h) on an unattended machine.
- Re-identification from rare values plus age and gender (`90+` band, rare panels flagged).
- Masking misses a novel identifier that MedGemma misplaces and that passes the F1 grammars. Mitigated by the Privacy log and the canary probe.
- Anthropic's 30-day retention; prompt-cache prefixes held for minutes at Anthropic (masked data only).
- Plaintext metadata (timestamps, counts, MIME, `pii_mapping.token` revealing the kind and count of identifiers).
- SSDs cannot guarantee secure deletion; no tamper-evident audit (TM decision).
- Offline brute force of the wrapped DEK, which Argon2id and the ≥10-character passphrase mitigate.

## Fix status (2026-11-08)
All findings F1–F15 have been applied to the specs (user-profile, data-protection, report-ingestion, pii-masking, claude-egress, health-analysis), to design.md (upload path, Phase-2 seam) and to tasks.md, where each change is tagged `SEC Fn`. `openspec validate --strict` passes. Security Tester task 11.3 re-verifies them after implementation.
