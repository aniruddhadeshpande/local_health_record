# Round 2 – Tech Architect critique (implementability)

> Intended path: /home/aniruddha/Projects/local_health_record/docs/design-team/round2-ta.md (plan mode blocked it; copy verbatim)

## Library facts (checked on PyPI and the Ollama site, 2026-11-08)
- **sqlcipher3-binary 0.6.0**: wheels only for `manylinux2014_x86_64` (CPython 3.8 to 3.14). No macOS, Windows or ARM wheels, and no sdist. **Confirmed: use app-level AES-GCM.**
- **Ollama `format`** accepts a full JSON schema object (structured outputs, Dec 2024), including with vision models. Confirmed. Minimum version: unverified. Pin a version in the README.
- **pypdfium2** has wheels for Win, macOS 13+ and Linux (glibc/musl, x86/ARM), and does both text extraction and `page.render()`. **Correction to my R1:** `bitmap.to_pil()` needs **Pillow**, and we need it to get PNG bytes for Ollama. Add Pillow.

## Disagreements

| # | Point / who | Argument | Resolution |
|---|---|---|---|
| 1 | Upload limits. BA 10 files ≤10 MB; Sec 20 MB | CPU time is the real limit, not bytes. A 20 MB scanned PDF can be 40 pages, about 1–2 h on 4 cores | **10 files/request, 10 MB/file, 10 pages/PDF**, magic-byte check (Sec) |
| 2 | BA has `analysing` as a per-file state | Analysis runs over a batch and memory, not over one file. A per-file state would run N Claude calls and N memory rewrites | The file job ends at `stored`. One **batch analysis job** is enqueued automatically when every file in the batch is terminal. The UI shows batch progress |
| 3 | SA: BackgroundTasks; restarted jobs marked failed | BackgroundTasks run concurrently in the threadpool and have no recovery. With an encrypted temp file still on disk, resuming costs nothing | Keep the **single daemon worker thread** (~40 LOC). Restart → non-terminal jobs go back to `queued` |
| 4 | Sec: stream-encrypt the upload, tmpfs | `AESGCM` is one-shot, not streaming. The real leak is Starlette's `UploadFile`, which **spools to the OS temp dir in plaintext above 1 MB** | Read the file (≤10 MB) into memory and encrypt it one-shot to `data/tmp/<uuid>.enc`. Raise the multipart spool threshold above 10 MB (Starlette attr name to verify), or set `TMPDIR=/dev/shm` on Linux. pypdfium2/openpyxl/Ollama all take bytes or BytesIO, so tmpfs paths aren't needed |
| 5 | Sec: hash-chained audit | Cheap: a `prev_hash` column. But chat writes from request threads and the worker writes analysis rows, so concurrent writers would fork the chain | **Accept**, using one `audit_lock` around read-last-hash + insert. Add `GET /api/audit/verify` for QA |
| 6 | Sec: chat "mask and send" | It needs to be stateless to stay simple | `POST /api/chat` → `422 {guard:{status:"needs_confirm", hits:[{kind,start,end}]}}`. The client re-posts `{message, confirm_mask:true}`, which creates new tokens. Known values are auto-masked → `200` with `guard.status:"masked"`. Guard error → `503`, blocked |
| 7 | Cookie vs bearer. Sec prefers an HttpOnly SameSite=Strict cookie | The brief requires a *separate* thin client. `127.0.0.1:5500` → `:8000` is cross-origin but same-site, so the cookie works only with `credentials:'include'`, `allow_credentials` and an exact origin. Mixing `localhost` and `127.0.0.1` makes the request cross-site, and the cookie silently drops. That is fragile to debug | **Bearer header**, which also avoids CSRF. Token in JS memory, plus `sessionStorage` so it survives a reload (Sec to confirm). XSS control: render Claude output with `.text()` or a whitelisted markdown subset, plus a CSP meta tag. CORS = exact origin, `TrustedHostMiddleware` |
| 8 | Key in memory for jobs. Sec: jobs fail `locked` after 15 min idle; mine paused | A 10-file scanned batch runs longer than 15 min. If the user steps away, every job stalls | **Worker lease**: the API token expires on idle (15 min, Sec), but the DEK is kept in-process while that user has non-terminal jobs, up to the 8 h absolute cap. Explicit logout wipes it right away → jobs go to `waiting_for_unlock`. Unprocessed encrypted temps are deleted after 24 h → `failed`. **Sec sign-off needed** |
| 9 | SA: send the token map to the browser for re-hydration | This puts the re-identification key in browser JS memory | **Unmask server-side**. The API returns display text. The client never holds the mapping |

## Concessions
- **BA single profile:** drop `GET /api/users`. Login is `{passphrase}`. Register returns `409` if a profile exists. Keyfile JSON as Sec specifies.
- Sec: passphrase ≥10 chars, 15-min idle, `rapidfuzz` fuzzy guard, relative-day dates, structured-only payload to Claude, age bands at extremes, `secure_delete`.
- SA: memory is a schema-bound JSON doc, fully replaced on each update, with caps enforced in code and one-level rollback.

## Final job state machine
```
file job:  queued -> extracting -> masking -> stored -> done      (temp deleted at stored)
           any running state -> waiting_for_unlock -> queued      (on login)
           any -> failed (attempts>2, unsupported, 24h unlock timeout; temp deleted)
analysis:  queued -> analysing -> done | blocked_pii | failed
           (blocked_pii = guard hit; payload shown, never auto-retried)
```

## Endpoint deltas vs R1
- Removed: `GET /api/users`. Changed: `POST /api/login {passphrase}`.
- Added: `GET /api/batches/{id}` (file jobs plus the auto analysis job), `GET /api/reports/{id}/masked` (US-9), `POST /api/analysis/{job_id}/retry` (after blocked_pii), `GET /api/audit/verify`, `DELETE /api/profile` (stretch).
- Changed: chat `422 needs_confirm` + `confirm_mask` flag. `GET /api/jobs` also returns `waiting_for_unlock`.
