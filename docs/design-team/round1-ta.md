# Round 1 – Tech Architect position (LLD)

> Intended path: /home/aniruddha/Projects/local_health_record/docs/design-team/round1-ta.md
> (written here because plan mode blocks edits elsewhere; copy verbatim once approved)

Guiding rule: one process, one SQLite file, plain functions plus a handful of small interfaces. Anything we would only need "later" stays out.

## 1. Repo layout

```
backend/
  pyproject.toml            # uv-managed
  app/
    main.py                 # FastAPI app, CORS for the frontend origin, router includes, startup job recovery
    config.py               # env settings (OLLAMA_URL, MODEL ids, DATA_DIR, CHAT_TURNS=6, ...)
    db.py                   # sqlite3 connection, schema DDL, tiny helpers (no ORM)
    crypto.py               # Argon2id KDF, AES-GCM encrypt/decrypt, key wrapping
    sessions.py             # in-memory token -> (user_id, DEK, expiry)
    api/
      auth.py  uploads.py  jobs.py  analysis.py  memory.py  chat.py
    llm/
      local.py              # LocalLLMClient protocol + OllamaClient (+ OpenAICompatClient stub for Phase 2)
      claude.py             # ClaudeClient wrapper (only path to Anthropic)
    pipeline/
      ingest.py             # file -> text/images (pdf, image, xlsx)
      extract.py            # MedGemma extraction prompt -> structured JSON
      mask.py               # Masker (rules + model-assisted), token mapping
      worker.py             # single job worker thread + job state machine
    guard.py                # PIIGuard (pre-send check, audit write)
    memory.py               # MemoryService (build/update/fold)
    prompts/                # .txt prompt templates (extract, mask, analyse, chat, fold)
frontend/
  index.html  app.js  style.css  vendor/jquery-3.7.1.min.js   # served via `python -m http.server 5500`
scripts/
  qa_register_login.sh  qa_upload_poll.sh  qa_analysis.sh  qa_chat_guard.sh  qa_leak_probe.sh
docs/  openspec/  samples/ (samples/raw is never read by tooling or agents)
data/   # runtime: health.db, tmp uploads (gitignored)
```

## 2. Python dependencies

| Package | Why |
|---|---|
| fastapi, uvicorn[standard] | API + server |
| python-multipart | required by FastAPI for `UploadFile` |
| anthropic | Claude SDK (brings httpx, which we also use for Ollama – no `ollama` package needed) |
| pypdfium2 | PDF text extraction **and** page→PNG rendering for scanned PDFs; prebuilt wheels on Linux/mac/Windows, no system deps |
| openpyxl | read BMI .xlsx sheets |
| cryptography | AES-256-GCM column encryption |
| argon2-cffi | Argon2id key derivation and passphrase verification |

Not included: pdfplumber (slower, pdfminer-only, no rendering), pypdf (no rendering), Pillow (Ollama accepts PNG/JPEG bytes as-is; only add if we must downscale), SQLAlchemy, LangChain.

**Encrypted SQLite recommendation: plain SQLite + app-level AES-GCM on sensitive columns.**
- `sqlcipher3-binary` ships wheels for Linux x86_64 only; macOS and Windows need SQLCipher + OpenSSL built from source. That is a demo-killer on a reviewer's laptop.
- App-level encryption uses stdlib `sqlite3` + `cryptography` (wheels everywhere).
- Trade-off we accept: metadata (row counts, timestamps, status, file sizes) is visible in the DB file. Every column with health or personal content is ciphertext. Security may push back; see §10.
- Each encrypted value = `nonce(12) || ciphertext||tag`, AAD = `table:column:row_id` so blobs cannot be swapped between rows.

## 3. Data model (`enc` = AES-GCM BLOB under the user's DEK)

- **users**: id PK, name `enc`, age `enc`, gender `enc`, kdf_salt, kdf_params (json), pw_verifier (argon2 encoded hash), wrapped_dek (DEK encrypted with KEK), created_at. Login lookup: users listed by id; the UI sends `user_id` from a local picker, or we try-unwrap per user (POC has 1–3 users). No plaintext name index.
- **jobs**: id (uuid), user_id, file_name `enc`, mime, status, step, error (sanitised, no content), attempts, created_at, updated_at. Temp file path = `data/tmp/{job_id}.bin`, itself AES-GCM encrypted on write.
- **extracted_records**: id, job_id, user_id, report_date `enc`, data_json `enc` (original values, incl. identifiers found), created_at.
- **masked_reports**: id, job_id, user_id, masked_json `enc` (what may go to Claude), created_at.
- **pii_mapping**: id, user_id, token (e.g. `[PERSON_1]`, `[LAB_1]`, `[DATE_3]`), kind, real_value `enc`. Unique(user_id, token). Tokens are per-user, stable across reports so trends survive masking.
- **analyses**: id, user_id, report_ids (json), result_md `enc`, model, created_at.
- **memory**: user_id PK, summary_md `enc`, version, updated_at (single row per user, overwritten; previous version kept in `memory_history` only if cheap – optional).
- **chat_messages**: id, user_id, role, content_masked `enc`, folded (bool), created_at. Stored masked; unmasked on read for display.
- **audit_log**: id, user_id, ts, direction (`to_claude`), purpose (`analysis|chat|fold`), model, payload_masked `enc`, payload_sha256, guard_result (`pass|blocked`), blocked_reasons (json, no values).

Sessions are not a table (see §8).

## 4. REST API (JSON; `Authorization: Bearer <token>` except register/login)

- `POST /api/register` `{name, age, gender, passphrase}` → `201 {user_id}`
- `POST /api/login` `{user_id, passphrase}` → `{token, expires_at, profile:{name, age, gender}}`
- `POST /api/logout` → `204` (drops DEK from memory)
- `GET  /api/users` → `[{user_id, created_at}]` (no names; UI labels "Profile 1…")  *— BA may prefer names; would require decrypting, so no.*
- `POST /api/uploads` multipart `files[]` → `202 {jobs:[{job_id, file_name, status:"queued"}]}` (pdf/png/jpg/xlsx, ≤10 MB each)
- `GET  /api/jobs?ids=a,b` → `{jobs:[{job_id, status, step, error}]}`  (UI polls every 3 s)
- `POST /api/analysis` `{report_ids?: [...]}` (default: all un-analysed masked reports) → `202 {job_id}` (same job table, type=analysis)
- `GET  /api/analysis/latest` → `{analysis_id, created_at, result_md (unmasked locally), disclaimer}`
- `GET  /api/memory` → `{summary_md, version, updated_at}`
- `POST /api/chat` `{message}` → `200 {reply, guard:{status:"pass"|"masked", replaced:[kind…]}}` or `422 {guard:{status:"blocked", reasons:[...]}}`
- `GET  /api/chat/history?limit=50` → `{messages:[{role, content, created_at}]}`
- `GET  /api/audit?limit=20` → masked payloads (demo transparency).

Chat is synchronous (Claude latency is a few seconds; no local model in the chat path except optional mask, see §5).

## 5. Interfaces (only these)

```python
class LocalLLMClient(Protocol):
    def generate(self, prompt: str, images: list[bytes] = [], json_schema: dict | None = None) -> str: ...
# OllamaClient: POST {OLLAMA_URL}/api/chat, model="medgemma:4b", format=json_schema, options={temperature:0, num_ctx:8192}
# OpenAICompatClient (Phase 2, stub): /v1/chat/completions, TLS + bearer/mTLS per Security spec

class ClaudeClient:
    def __init__(self, guard: PIIGuard, sdk: anthropic.Anthropic): ...
    def complete(self, user_id, purpose, system_blocks, messages, model) -> str
    # ALWAYS: guard.check(full payload) -> audit -> sdk.messages.create. No other module imports anthropic.

class PIIGuard:
    def check(self, user_id, payload_text) -> GuardResult  # pass | blocked + reasons
    # denylist = decrypted name parts, pii_mapping real values (len>=3), + regexes (email, phone, IDs, DOB-like dates, MRN/UHID, addresses, pincodes)
    def sanitize_chat(self, user_id, text) -> (masked_text, replaced)  # swap known values for existing tokens

class Masker:
    def mask(self, user_id, extracted: dict) -> dict  # rules first (known fields: patient_name, lab, dates→relative/YYYY-MM), then MedGemma pass to flag residual identifiers, then PIIGuard.check as final gate

class MemoryService:
    def get(user_id) -> str; def update_from_analysis(user_id, analysis); def fold_turns(user_id, turns)
```
Dependency inversion is used exactly twice: LocalLLMClient (Phase-2 swap) and ClaudeClient wrapping the SDK (single choke point for the guard). Everything else is module-level functions.

## 6. Background jobs – recommend option (a)

**One daemon worker thread + `jobs` table in SQLite**, started in FastAPI lifespan. Not `BackgroundTasks` per request (it runs N jobs concurrently in the threadpool, which would load MedGemma N times worth of compute) and not Redis+RQ (extra service, extra secret, RQ has no native Windows worker, and queue/session data would sit outside our encryption).

State machine: `queued → extracting → masking → stored → done`, any step → `failed`. Analysis jobs: `queued → analysing → done|failed`.

- Concurrency = 1 (MedGemma 4B on 4 CPUs ≈ 1–3 min per page; Ollama serialises anyway). `OLLAMA_NUM_PARALLEL=1`.
- Worker needs the DEK: the job is enqueued with the session's DEK reference held in memory (`dict[job_id → user_id]`, DEK looked up from the live session). If the user logs out or the session expires, pending jobs pause in `queued` until next login.
- Crash/restart: on startup, any job in a non-terminal state is reset to `queued` (attempts+1; >2 → `failed`). The encrypted temp file is still on disk, so it can resume after the user logs in. Temp files of `done`/`failed` jobs are deleted (failed: deleted after max attempts — no retention option). A startup sweep deletes orphan temp files.
- Original-file deletion happens immediately after `stored` commits, inside the same step.

## 7. Claude usage

- **Analysis + memory update:** `claude-sonnet-5-5` (good reasoning, moderate cost). Opus-5-5 is overkill for a POC.
- **Chat:** `claude-sonnet-5-5` default; `claude-haiku-5-5` configurable for cost.
- **Turn folding:** `claude-haiku-5-5`.
- Prompt structure (system blocks, in order):
  1. Static instructions (role, "not a diagnosis", output format, "placeholders like [LAB_1] are opaque; do not ask for real values") — `cache_control: ephemeral`.
  2. Patient context: `age, gender` + memory summary — `cache_control: ephemeral`.
  3. Latest masked report (JSON).
  Messages: last N=6 turns (masked) + new user message.
- **Caching caveat:** caching only applies above a minimum prefix size (≈1024 tokens on Sonnet/Opus-class, larger on Haiku-class historically; confirm exact Claude 5 values via the claude-api docs before implementation). A fresh user's memory is small, so blocks 1–2 may not reach the minimum; that's fine — caching just no-ops. Keep blocks byte-stable (no timestamps) so cache hits happen.
- **Folding:** when unfolded turns > 12, send the oldest 6 (masked) + current memory to Haiku with "merge durable facts into memory, max ~800 words, drop chit-chat", mark them `folded`. Memory hard cap ~1,500 tokens; the analysis prompt also rewrites memory (not appends) to keep it bounded.

## 8. Session handling

- Register: random 256-bit DEK; KEK = Argon2id(passphrase, salt, t=3, m=64 MiB, p=2) → `wrapped_dek = AESGCM(KEK).encrypt(DEK)`. Separate argon2 hash for verification (or verify implicitly by GCM unwrap success — simpler; I prefer just unwrap).
- Login: derive KEK, unwrap DEK, create `token = secrets.token_urlsafe(32)`, store `sessions[sha256(token)] = (user_id, DEK as bytearray, expires)` in a process dict.
- Lifetime: 30 min sliding idle, 8 h absolute. Logout/expiry overwrites the bytearray and deletes the entry. Server restart = everyone logs in again (by design).
- Token kept in `sessionStorage` on the frontend (not localStorage). Bind uvicorn to 127.0.0.1; CORS only for `http://127.0.0.1:5500`.
- Passphrase change = re-wrap DEK only (no data re-encryption) — one reason for DEK/KEK split.

## 9. Q1 – Workflow framework

**Plain Python + Anthropic SDK.** The flow is a fixed, linear pipeline (ingest → extract → mask → guard → Claude → memory) with no branching agent decisions or tool loops. LangGraph adds a state-graph abstraction, checkpointer and a dependency tree we'd need to audit for data egress (LangSmith tracing defaults are a leak risk to explicitly disable). Deep Agents adds planning/filesystem/sub-agent machinery we don't need, and its local-model support goes through LangChain wrappers. Plain functions: stack traces point at our code, the guard choke point is obvious in review, and QA can reason about it. Revisit LangGraph only if Phase 2 adds multi-step tool-using agents.

## 10. Expected challenges

1. **Security:** app-level column encryption leaks metadata and leaves SQLite temp/WAL with plaintext of non-encrypted columns; they may demand SQLCipher. My answer: no PII/health in plaintext columns; offer SQLCipher as an optional Linux-only build flag.
2. **Security:** DEK in Python memory can't be reliably zeroised (immutable bytes copies in `cryptography`). Accepted POC risk; localhost-only binding mitigates.
3. **SA:** jobs pausing until login (DEK needed) may look like "stuck" uploads; alternative is encrypting temp files with a per-job key, but that key would also need protecting — I'd keep pause-until-login and show `waiting_for_login` status.
4. **BA:** login by user picker without showing names; and synchronous chat with no streaming may feel slow. Could add SSE later.
5. **Security/BA:** masking reliability with a 4B CPU model — rules-first, model-second, guard-last; plus a `qa_leak_probe.sh` that greps the audit log for every known profile/mapping value.
