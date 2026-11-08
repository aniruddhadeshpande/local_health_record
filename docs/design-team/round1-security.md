# Plan: Security Engineer Round 1 position

Target file (to create once plan mode is lifted): `/home/aniruddha/Projects/local_health_record/docs/design-team/round1-security.md`
Action: `mkdir -p docs/design-team` and write the content below verbatim. Nothing else.

---

# Round 1 – Security Engineer Position

Scope: Phase 1 POC on a single laptop. Controls are proportionate: strong where data leaves the machine or sits on disk, light elsewhere.

## 1. Threat model (STRIDE-lite)

**Assets (by sensitivity)**
| Asset | Where | Sensitivity |
|---|---|---|
| Raw upload (PDF/XLSX/image) | transient temp only | Critical – full PII + PHI |
| Extracted (unmasked) data | encrypted DB | Critical |
| PII mapping (token -> real value) | encrypted DB | Critical – the re-identification key |
| Profile (name, age, gender) | encrypted DB | High |
| Masked reports, memory summary, chat history | encrypted DB | High (PHI, possibly re-identifiable) |
| Audit log (masked payloads) | encrypted DB | Medium–High |
| Passphrase / derived keys | process memory only | Critical |
| Anthropic API key | `.env` (0600) | Medium (cost/abuse, not PHI) |

**Actors**
- *Curious other OS user*: handled by file permissions (0700 data dir, 0600 files) plus encryption at rest. In scope.
- *Malware running as the user*: can read process memory, keylog the passphrase and read `.env`. **Out of scope to fully defend.** We limit how long data is exposed (key only in memory, temp files deleted quickly) but say plainly that this is residual risk.
- *Network observer*: Claude traffic uses TLS 1.2+ (SDK default, cert verification on). Localhost traffic stays off the wire because nothing binds to 0.0.0.0.
- *Anthropic as data processor*: only receives masked data plus age/gender. Rely on the commercial API terms (no training on API data, limited retention). Even so, treat anything sent as potentially kept.
- *The user*: will type PII into chat or upload a file of the wrong type. This is the most likely way data leaks, so the guard must fail closed.
- *Local web content / other browser tabs*: can attack localhost through CSRF or DNS rebinding. In scope (see section 6).

**Trust boundary**: everything on the laptop (FastAPI, SQLite, Ollama, browser) is inside. The Claude API is outside. **One egress choke point** – a single `ClaudeGateway` module – is the only code that imports the Anthropic SDK, and every call goes through `PIIGuard.check()` first.

**STRIDE highlights**
- S: localhost API without a session token -> any local process or web page can call it. Mitigation: session token + Origin check.
- T: tampering with DB rows -> AES-GCM / SQLCipher HMAC detects it.
- R: audit log of every egress decision.
- I: masking misses data; leftover temp files; logs; swap. Mitigations in sections 3–5.
- D: huge uploads or zip bombs (XLSX is a zip) -> size limits.
- E: path traversal through upload filenames -> never use the client's filename on disk.

## 2. Key handling

- **KDF**: Argon2id (`argon2-cffi`). Params: `m=64 MiB, t=3, p=1` (above the OWASP minimum of m=19 MiB/t=2/p=1, in line with RFC 9106's 64 MiB profile). Target about 0.5–1 s on the laptop. Store the params with the salt so they can be raised later.
- **Salt**: 16 random bytes (`secrets.token_bytes`), stored in plaintext in `keyfile.json` next to the DB. A salt is not secret.
- **DEK/KEK**:
  - `KEK = Argon2id(passphrase, salt)` (32 bytes).
  - `DEK` = 32 random bytes, generated once at registration.
  - `wrapped_DEK = AES-256-GCM(KEK, nonce, DEK, aad="lhr-dek-v1|user_id")`, stored in `keyfile.json`.
  - Changing the passphrase means re-deriving the KEK and re-wrapping the DEK. Data is not re-encrypted.
- **Verification without storing the key**: a successful GCM unwrap of `wrapped_DEK` *is* the verifier. A wrong passphrase gives an auth-tag failure, so no separate hash is stored. Return a generic "invalid passphrase" message. Rate-limit locally (exponential back-off after 5 failures). Argon2 cost already slows brute force.
- **PIN warning**: a 4–6 digit PIN has ≤10^6 possibilities. An offline attacker with the keyfile can brute-force that in hours, even with Argon2id. Require a **passphrase of at least 10 characters** (or a 6+ word diceware phrase). If BA insists on a PIN, record the accepted risk in decisions.md.
- **In-memory lifetime**: the DEK lives only in the FastAPI process after login. It is dropped on logout, after a 15-minute idle timeout, or on process exit. Keep it in a `bytearray` and zero it on logout (best effort, since Python cannot guarantee wiping). Never log, serialise, pass to a subprocess, or put it in a job payload. Background jobs use the in-process key, so **jobs cannot run while locked**. Jobs in progress at lock-time fail with status `locked` and resume after login.
- **Forgotten passphrase**: **the data cannot be recovered. There is no backdoor and no recovery key.** The UI must say this at registration. An optional printed recovery code (a second KEK wrap) is Phase 2.
- **Multi-user**: one keyfile/DEK per profile.

## 3. Encryption at rest

**Recommendation: app-level AES-256-GCM on plain SQLite** (`cryptography` lib), not SQLCipher.
- Why: SQLCipher in Python needs `sqlcipher3`/`pysqlcipher3` wheels plus a native lib. That breaks easily across Linux/macOS/Windows and Python 3.12, and it is the most likely way to waste POC time. App-level encryption is pure-pip and portable.
- Cost: plaintext metadata. Keep it to a minimum:
  - **Plaintext allowed**: row IDs, user_id (random UUID), timestamps of record creation, job status, file type, sizes, Argon2 params/salt, schema version.
  - **Encrypted (single blob column per row)**: name, age, gender, extracted data, masked report, mapping table, memory, chat messages, audit payloads, original filename.
  - No searching inside encrypted fields. Load and filter in memory, which is fine at POC scale.
- Each encrypted field: `nonce(12) || ciphertext || tag`, with AAD = `table|column|row_id` so blobs cannot be swapped between rows. Use a fresh random nonce for every write.
- Turn on `PRAGMA secure_delete=ON` and run `VACUUM` after deleting a profile, so freed pages don't keep old plaintext metadata.
- If TA prefers SQLCipher and shows it installs cleanly on the target OSes, I accept it. It encrypts metadata as well. **Do not use both.**

**Uploads and temp files**
- Stream the upload straight into **AES-GCM-encrypted temp storage** (`data/tmp/<uuid>.enc`, 0600). Never write the plaintext file to disk. Use a random server-side name and ignore the client filename.
- For MedGemma, decrypt into memory (bytes -> Ollama base64 image / text) or into `/dev/shm` (tmpfs) when a library insists on a path. Delete in a `finally:`.
- After processing (success *or* final failure): overwrite once, then unlink the encrypted temp. Because it was ciphertext, deleting the DEK-encrypted file is enough. **SSD caveat**: overwrite-in-place does not reliably erase data on SSDs (wear levelling, TRIM) or on CoW/journaling filesystems. That is exactly why plaintext must never reach disk. Recommend full-disk encryption (LUKS/FileVault/BitLocker) in the README as a baseline.
- Rendered page images (PDF -> PNG for the vision model) stay in memory only.
- Also: turn off Ollama/uvicorn request logging of bodies, and note in the README that swap/hibernation can hold plaintext (accepted POC risk; FDE mitigates).

## 4. Masking (Q3): rules + model hybrid

No single layer is reliable enough. MedGemma 4B misses entities; regex misses names. Use **layered, union-of-detections**:
1. **Known-value pass (deterministic)**: exact and fuzzy match on profile name (all tokens, case/diacritic-folded, initials like "A. Dey"), plus every value already in the mapping table.
2. **Regex/rules pass**: phone (incl. +91 formats), email, Aadhaar/PAN/SSN-like IDs, MRN/UHID/patient ID/accession/sample/barcode patterns (label-anchored: `(MRN|UHID|Patient ID|Lab No|Accession|Sample ID|Reg No)\s*[:#]?\s*\S+`), long digit runs (≥6), PIN/ZIP codes, URLs, dates.
3. **Model pass (MedGemma)**: during extraction, ask for a JSON list of PII spans (person, doctor, facility, address).
4. **Structured-output rule (strongest control)**: send Claude **only the structured extraction** (test name, value, unit, reference range, relative date), *not* free text from the report. Free-text fields (comments, impressions) go through all passes and are left out if in doubt.

**Identifier classes -> treatment**
| Class | Treatment |
|---|---|
| Patient name, relatives | `[PERSON_1]` token |
| Doctor / pathologist names | `[DOCTOR_n]` |
| Lab / hospital / clinic names, addresses | `[FACILITY_n]` / removed |
| MRN, UHID, accession, sample IDs, barcodes | removed (no analytic value) |
| DOB | removed; age is already sent |
| Phone, email, URL | removed |
| Report/collection dates | **relative offset** from the user's first report (`day +0, +94, +310`), or month/year only. Never exact dates |
| Age | send age band (e.g. 40–44) if age > 89 or if age is unusual; otherwise exact age (allowed by brief) |

**Tokenisation**: per-profile random tokens (`[PERSON_1]`), mapping stored encrypted. Tokens are not derived from the value (no hash of the name, which would let anyone confirm a guessed name). Tokens are the same within one profile so Claude can follow trends. Swap back on the device only.

**Re-identification risks**
- Exact dates + lab name + age + gender: combined, these could identify a person. Hence relative dates and no facility names.
- Rare values / rare tests (genetic markers, rare-disease panels): flag and coarsen if possible. Accept as residual risk in the POC.
- Small-cell combos (age 97 + rare condition): use age bands at the extremes.
- Free text ("patient of Dr X at Y hospital, Kolkata"): left out by the structured-output rule.
- Units/reference ranges can fingerprint a specific lab. Low risk, accepted.

**Verifying nothing leaks**
- **Pre-send PII guard** runs on the *final serialised payload* (system + memory + messages), not on fields one by one:
  - exact + fuzzy (Levenshtein ≤1 for tokens ≥4 chars, `rapidfuzz`) match against profile name tokens and **all real values in the mapping table**;
  - the regex set above;
  - allowlist: age, gender, token placeholders, medical vocabulary.
- **Fail closed**: any hit, guard exception, or missing mapping table -> **do not send**. The job status becomes `blocked_pii`, and the masked text is shown to the user with the hit highlighted. Never retry automatically without masking.
- **Leak-test corpus**: `samples/synthetic/` with synthetic reports containing planted canary PII (fake names, MRNs, phones, Indian-format dates, lab names). QA runs a curl script and greps the audit log / an intercepting stub for every canary. Pass = zero canaries found. Never build it from `samples/raw/`.

## 5. Chat PII guard

- **Policy: mask known values, block unknown pattern hits.**
  - Text that matches a known profile/mapping value -> **auto-mask** with the existing token, then send. The user's own name is expected in chat, and blocking it would be annoying.
  - Regex hit with no known mapping (a new phone number, ID, email, unknown person name) -> **block**. Show the user "Your message contains what looks like a phone number/ID. Remove it or click 'mask and send'". "Mask and send" adds a new token and sends again.
  - Guard error -> block (fail closed).
- **Feedback**: the UI shows the exact text that went out (masked) as a collapsible "Sent to Claude" view. This builds trust and helps QA.
- **Replies**: swap tokens back locally before showing. Store chat in two forms: masked (for context) and display (encrypted).
- **Audit log** (one row per egress attempt): timestamp, call type (analysis/chat/memory), decision (`sent|masked_sent|blocked`), rule IDs that fired (not the matched values), SHA-256 of the exact masked payload, the masked payload itself (encrypted with the DEK), model id, request id from Anthropic response.
- **Audit protection**: encrypted like other PHI. Rows are append-only in code, and each row includes `prev_hash` (a simple hash chain) so tampering is visible. Never write the matched raw value into the log, because that turns the audit log into a PII store.

## 6. Localhost API hardening

- Uvicorn `--host 127.0.0.1` only. Serve the thin client from the **same origin** (FastAPI `StaticFiles`) so no CORS is needed. If served separately, CORS allowlist = exact `http://127.0.0.1:<port>`, never `*`, no credentials wildcard.
- **Host header check** (`TrustedHostMiddleware`: `127.0.0.1`, `localhost`) to defeat DNS rebinding.
- **Session**: random 256-bit token issued at login, kept in server memory (dict), with a 15-minute idle and 8-hour absolute expiry. Prefer an **HttpOnly, SameSite=Strict cookie**. With SameSite=Strict, a same-origin client and an `Origin` header check on state-changing requests, CSRF is covered. If bearer header is chosen instead, CSRF goes away but the token sits in JS memory (not localStorage).
- **Uploads**: max 20 MB/file, 10 files/request. Extension + magic-byte allowlist (PDF `%PDF`, XLSX/zip `PK`, PNG/JPEG). XLSX zip-bomb guard (uncompressed size cap). `openpyxl` in read-only mode with formulas not evaluated. No macros (`.xlsm` rejected).
- **Errors**: generic messages, no stack traces (debug off).
- **Logging**: never log request bodies, prompts, model outputs or extracted values. Log IDs and statuses only. Review Ollama: set `OLLAMA_HOST=127.0.0.1:11434` (the default; verify it is not 0.0.0.0), and do not enable debug.
- **Anthropic API key**: `.env` (0600), loaded via env var, `.env` in `.gitignore`, never in DB, logs or client. Provide `.env.example`.
- **Claude retention**: commercial API terms – no training on API inputs by default. Inputs/outputs are kept for a limited period for trust & safety (check the current number of days in Anthropic's terms before demo). Zero-data-retention is available only by agreement. **Prompt caching** stores the masked memory block server-side for its TTL (5 min default). That is fine because it is already masked. Record this in decisions.md.

## 7. Jobs: job table vs Redis

**Preference: (a) FastAPI background tasks + job table in the local encrypted DB.**
- Security reason: the DEK lives in the API process. Redis/RQ workers are separate processes and would need the key passed across (IPC, env, or Redis itself), which makes the key-handling problem bigger. Redis is also another listening service to harden, and its RDB/AOF files are unencrypted on disk.
- If Redis is chosen anyway: `bind 127.0.0.1`, `protected-mode yes`, `requirepass` (or ACL user) from `.env`, persistence off (`save ""`, `appendonly no`), messages carry **only job_id/file_id**, session TTL ≤15 min idle, and the worker gets the key by an explicit, documented mechanism (not via Redis).

## 8. Phase-2 vLLM server requirements (inside trust boundary)

1. TLS 1.2+ (prefer 1.3) with certificate verification. No plaintext HTTP even on internal networks.
2. Client auth: **mTLS preferred**. Otherwise a per-client API key sent over TLS, rotated, stored in the client's OS keychain/.env.
3. Reachable only over a **private network / VPN** (WireGuard, corporate VPN). An IP allowlist alone is not enough (spoofing/NAT/shared egress). No public endpoint.
4. **No prompt/response logging** (vLLM `--disable-log-requests`, proxy access logs without bodies). Metrics only.
5. Full-disk encryption on the server. Files handled only in memory or encrypted temp, **deleted right after processing**. No caching of inputs.
6. **No shared/multi-tenant cloud GPU** without a signed DPA, data residency confirmation, and tenant isolation. Prefer company-owned hardware.
7. Access control + audit of who administers the box. Patch cadence. Model weights integrity (pin a hash).
8. `LocalLLMClient` config must refuse a non-TLS remote URL (only `http://127.0.0.1` exempt).

## 9. Expected challenges to SA / TA / BA

1. **BA – "PIN" in registration**: a short PIN cannot protect an offline keyfile. I will push for a minimum 10-char passphrase, or a recorded risk acceptance.
2. **SA/TA – sending free text to Claude**: I will challenge any design that sends masked *narrative* text. Default is structured extraction only. Free-text comments need justification.
3. **TA – SQLCipher vs app-level crypto**: I recommend app-level for portability. If TA chooses SQLCipher, they own showing that the wheel installs on every target OS. No dual approach.
4. **SA – Redis/separate workers**: this creates key-sharing problems across processes. I will push back unless the job-table option is shown not to work.
5. **SA/TA – exact dates for trends**: trend analysis needs time intervals, not calendar dates. Relative day offsets give Claude the same signal. I will challenge sending real dates or lab names "for context".
6. **All – fail-closed UX**: blocked analysis must show a clear message the user can act on. A silent fallback that sends anyway is not acceptable.
