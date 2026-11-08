# Round 2 – Security Engineer critique

> Target: `docs/design-team/round2-security.md` (plan mode blocked it; copy this file verbatim).

## 1. Disagreements

| # | Point | Who | Argument | Resolution | Sev |
|---|---|---|---|---|---|
| D1 | PIN, or a passphrase of 8 chars or more | BA US-1 | The wrapped DEK sits in a file anyone can copy. An attacker can brute-force a PIN offline in hours | Passphrase of at least 10 characters. No PIN | High |
| D2 | Memory written by Claude is sent back | SA, TA | Claude can write quasi-identifiers into memory, such as "works at a hospital in Pune" or a doctor's name taken from chat. TA's free-form `summary_md` makes this worse | Use SA's structured JSON schema and leave out location, employer and person fields. Run the guard over memory output **before it is stored** as well as on every send | High |
| D3 | Haiku fold and memory-update calls | TA, SA | They are Claude calls too, so they are egress | All Claude traffic goes through `ClaudeClient` and is guarded and audited with purpose `fold` or `memory`. Inbound memory and fold output is re-scanned | Med |
| D4 | `[DATE_3]` tokens | SA | Opaque date tokens remove the time intervals that trend analysis needs. The temptation then is to send real dates | Send relative day offsets only (`T0+92d`). T0 is never sent. Drop month/year | Med |
| D5 | Token map sent to the browser for DOM re-hydration | SA | This puts real values into JS memory and API responses that don't need them | Re-hydrate on the server (TA's `result_md` unmasked locally). The client never sees the mapping | Med |
| D6 | Separate origin (`http.server :5500`) with CORS | TA | This adds an origin to secure, and DNS rebinding is possible | Same-origin `StaticFiles` is preferred. If TA keeps :5500, use exact-origin CORS + `TrustedHostMiddleware` + a bearer token in `sessionStorage` | Low |
| D7 | Plaintext metadata columns | SA, TA | `pii_mapping.token` and `kind` reveal how many people and labs exist. `jobs.mime` and timestamps leak usage patterns | Accept timestamps, status and mime. Keep `kind` encrypted or in an HMAC column. Set `secure_delete=ON` and VACUUM after delete | Low |
| D8 | Separate `pw_verifier` Argon2 hash | TA | It is a second offline brute-force target and serves no purpose | Verify by successful GCM unwrap only (TA already leans this way) | Low |
| D9 | Mask-by-default in chat | BA | **Agree** (see concessions) | Detected hits are auto-masked and the UI shows "we hid X". Block only if the re-check after masking still finds a hit, or the guard throws an error | Low |
| D10 | Re-identification from a rare value + age + gender | all | Low once names, facilities and dates are gone. Rare genetic or rare-disease panels are still a fingerprint | Age band if the user is over 89. Drop or flag rare-panel tests. Record as residual risk | Low |
| D11 | Someone else's report (BA Q8) | BA | That person's name is not in the deny-list, so the guard depends on regex and the model | The schema field `patient_name` is dropped by construction. Warn if it doesn't match the profile name | Med |
| D12 | Rendering model output | all | Using jQuery `.html()` on Claude or audit text is an XSS risk on a page that holds PHI | Render as text or escaped markdown only | Med |

**Good, and kept as is:** BA's "What was sent to Claude" screen (US-9/US-19) gives real audit transparency. SA's rule that the repository layer gives Agent 2 and Chat read access to masked tables only. TA's single choke point in `ClaudeClient`.

## 2. Concessions (POC proportionality)
- Idle timeout: I accept **TA's 30 min** (8 h absolute). The API is localhost-only and jobs pause while locked.
- Argon2id `p=2` (TA) is fine. Store the parameters with the salt.
- Upload limit of 10 MB per file (BA/TA) instead of 20.
- Chat masks by default (BA) instead of blocking.
- Encrypted temp files are kept until the job finishes (success, or failure after at most 2 attempts), as TA proposes. Restarting after a crash resumes the job. Startup sweeps orphan temp files.
- Bearer token in `sessionStorage` instead of an HttpOnly cookie.
- Exact age is sent (the brief allows it).
- Python can't reliably zero the DEK in memory. Accepted risk.

## 3. Verification
- **OWASP Argon2id**: minimum m=19 MiB (19456 KiB), t=2, p=1. Equivalent trade-offs are listed. Our m=64 MiB, t=3 is above this. *Verified* (OWASP Password Storage Cheat Sheet).
- **Anthropic API retention**: by default, inputs and outputs are deleted from the backend within 30 days. Exceptions: ZDR by agreement, Usage-Policy-flagged content (up to 2 years), feedback (5 years), legal holds. No training on API data by default. *Verified* (privacy.claude.com article 7996866). The DPA governs.

## 4. Security requirements that MUST appear in the specs
1. Only `ClaudeClient` imports `anthropic`. Every call (analysis, chat, memory, fold) runs guard, then audit, then send.
2. The guard scans the final serialised payload and fails closed on a hit, an error or a missing mapping.
3. Only structured extraction and masked fields go to Claude. Free text is excluded unless masked and re-checked.
4. Dates go out as relative day offsets only. No real dates, facility, doctor or patient names, IDs or DOB.
5. Memory follows a fixed JSON schema with no location, employer or person fields, and is guard-scanned before it is stored.
6. KEK = Argon2id(passphrase, salt) with at least m=64 MiB and t=3, and the parameters are stored. A random DEK is wrapped with AES-256-GCM.
7. Passphrase of at least 10 characters. Registration warns that the data can't be recovered.
8. Health and personal fields use AES-256-GCM per field with a fresh nonce and AAD = table|column|row_id.
9. A plaintext upload never reaches disk. Temp files are encrypted, 0600 and randomly named, and are deleted when the job finishes.
10. The DEK is held only in process memory, dropped on logout, after 30 min idle or 8 h absolute, or when the process exits. Jobs pause while locked.
11. Bind to 127.0.0.1 only. Same origin, or exact CORS. `TrustedHostMiddleware`. A 256-bit session token.
12. Uploads: magic-byte allowlist, 10 MB per file, 10 files per request, zip-bomb cap, no `.xlsm`.
13. Never log bodies, prompts, outputs or extracted values. Debug off. Ollama bound to 127.0.0.1.
14. The audit row holds the purpose, decision, rule IDs (never matched values), SHA-256, the encrypted masked payload and `prev_hash`.
15. A "What was sent to Claude" screen, viewable only after authentication.
16. Model and audit output is rendered as escaped text. No `.html()`.
17. Re-hydration happens on the server. The token map never leaves the API.
18. 5 failed logins trigger exponential back-off. Errors are generic.
19. The API key lives in `.env` with 0600 and is listed in gitignore. It is never stored in the DB, logs or client.
20. A synthetic canary leak test (`qa_leak_probe.sh`) must find zero canaries before demo.
21. The README recommends full-disk encryption and records the residual risks: swap, malware, 30-day retention at Anthropic.
22. Phase-2 `LocalLLMClient` rejects any non-TLS remote URL (localhost exempt).
