# Round 1 – Solution Architect position

> Target path (to be written once plan mode is lifted): `docs/design-team/round1-sa.md`
> Guiding rule: **simplest thing that keeps PII on the laptop.** One process, one DB, no broker, no agent framework.

## 1. HLD

**Components (one Python process + one static client)**

| # | Component | Responsibility | Where |
|---|-----------|----------------|-------|
| C1 | Thin client (HTML/CSS/jQuery) | Register/login, upload, poll job status, show analysis, chat, disclaimer, **re-hydrate placeholders** with the token map returned by the local API | Browser (local) |
| C2 | FastAPI API | Auth (passphrase → KDF → session-held DB key), upload, jobs, analysis, chat endpoints | Local |
| C3 | Job runner | FastAPI `BackgroundTasks` + `jobs` table; single worker, sequential | Local |
| C4 | Agent 1 – Extractor + Masker | Route file → parse → MedGemma structuring (JSON schema) → mask → store; delete original | Local |
| C5 | `LocalLLMClient` | Interface `generate(prompt, images=None, schema=None) -> dict`; `OllamaClient` impl now, `VllmClient` in Phase 2 | Local |
| C6 | PII Guard | Last gate before *any* Claude call: deny-list of known profile values + token-map originals + regex patterns; block or mask; writes audit row | Local |
| C7 | Agent 2 – Analyst + Memory | Plain Anthropic SDK call: memory + masked report(s) + age/gender → analysis + updated memory | Calls Claude |
| C8 | Chat bot | Memory (cached) + latest masked report + last N turns → reply | Calls Claude |
| C9 | Encrypted store | SQLite with field-level AES-GCM encryption (key from passphrase KDF) or SQLCipher – Security to pick | Local |
| C10 | Audit log | Table of exactly what was sent to Claude (masked payload, hash, timestamp, guard verdict) | Local, encrypted |

**Trust boundary:** everything except the Claude API sits inside the laptop. The *only* way out is through `ClaudeGateway.send()`, which always calls the PII Guard first and the audit log second. No other module imports `anthropic`.

```
                       ┌──────────────────────── LOCAL (laptop, trust boundary) ────────────────────────┐
 User ──► jQuery UI ──►│ FastAPI ──► jobs table ──► Job runner ──► Agent 1                               │
   ▲   (re-hydrate     │   │                                       │  ├─ Router: xlsx/text-PDF → parser   │
   │    tokens here)   │   │                                       │  ├─ scanned PDF/image → MedGemma VLM │
   │                   │   │                                       │  ├─ LocalLLMClient (Ollama medgemma) │
   │                   │   │                                       │  ├─ Masker (rules + model + deny-list)│
   │                   │   │                                       │  └─ delete original file             │
   │                   │   ▼                                       ▼                                      │
   │                   │  Encrypted SQLite: profile, extracted (raw), masked report, token map,          │
   │                   │                    memory, chat history, audit                                  │
   │                   │   │                                                                             │
   │                   │   ▼                                                                             │
   │                   │  Agent 2 / Chat ──► PII Guard ──(pass)──► Audit log ──► ClaudeGateway ──────────┼──┐
   │                   └─────────────────────────────────────────────────────────────────────────────────┘  │
   │                                                                                                         ▼
   │                                  SENT TO CLAUDE: masked report JSON, age, gender, memory summary       ┌──────────┐
   └──── reply with [LAB_1], [DATE_3] tokens ◄──────────────────────────────────────────────────────────────│ Claude   │
                                                                                                            └──────────┘
 NEVER SENT: name, passphrase, raw files, raw extracted text, token map, IDs, DOB, contacts, lab/hospital names
```

## 2. Recommendations

### Q1 – Workflow framework → **Plain Python functions + Anthropic SDK**

| | LangGraph | LangChain Deep Agents | Plain Python + SDK |
|---|---|---|---|
| Simplicity | Graph/state/checkpointer concepts for a 3-step linear pipeline | Planner, sub-agents, virtual FS – built for open-ended autonomous tasks | Two functions: `process_file()`, `analyse()`; one `chat()` |
| Local-model support | Via `langchain-ollama` | Same, plus heavier tool-calling assumptions a 4B model handles poorly | Direct HTTP to Ollama `/api/chat` with `format=<JSON schema>` |
| Debuggability | Needs LangSmith or tracing to see what crossed the boundary | Hardest – agent decides its own steps and tool calls | Stack traces + our own audit log; every outbound byte goes through one function |
| POC fit / security | Extra dependency surface between data and the network | Autonomy is a *liability* when the main requirement is "never leak" | Deterministic, auditable, easy to review |

Our flows are fixed pipelines, not open-ended agents. The "agents" are prompts. If Phase 2 needs branching or retries, LangGraph can wrap these same functions later.

### Q5 – Background jobs → **(a) FastAPI BackgroundTasks + `jobs` table**
- Single user and a single laptop. MedGemma on CPU can only run **one job at a time** anyway (4 cores), so a queue broker adds no throughput.
- `jobs(id, file_id, status[queued|running|done|failed], error, created_at, updated_at)`; UI polls `GET /jobs/{id}`.
- Run jobs one at a time with a single in-process `asyncio.Queue`/lock. On startup, mark stale `running` jobs as `failed` (the original file may already be gone, so the user re-uploads).
- Sessions: a short-lived random token held in server memory and mapped to the derived key. If the server restarts, the user logs in again. That is acceptable, and arguably a security feature.
- Redis/RQ/Celery means another service to install, secure and configure, and Redis is not installed here. RabbitMQ is **not justified**.

### Q4 – Long-term memory → **one bounded, structured, encrypted JSON document per user**
- Schema (Claude must return it via tool use or a JSON schema): `{conditions_flags[], key_markers{name:[{value,unit,period_token}] last 5}, trends[], lifestyle_notes[], open_questions[], chat_insights[], updated_at}`.
- **Update:** after each analysis, Claude receives `old_memory + new masked report` and returns the *full replacement* memory, not a diff. We store the previous version too (one-level rollback).
- **Bounded:** hard caps enforced in code: ≤ ~1,500 tokens total, ≤ 5 data points per marker, ≤ 10 items per list. If the cap is exceeded, call Claude once with "compress to fit". Deterministic truncation is the fallback.
- **Chat folding:** keep the last 6 turns verbatim. Every 10 turns, run a summary call that merges chat insights into memory, and older turns drop out of the context (they stay in local encrypted history).
- **Caching:** the memory block plus system prompt sits in a `cache_control` breakpoint. Minimum cacheable prefix is ~1,024 tokens on Sonnet-class models and higher (~4,096) on some others. Check with the TA; if the block is smaller, caching silently does nothing. That is harmless, but don't promise savings.
- Memory holds only masked content (tokens, not real names), so it can be sent safely.

## 3. Q3 – Masking (architecture view)
- **Where:** masking happens in Agent 1, **before** anything reaches the store's "sendable" tables. The masked report is a separate record from the raw extraction. Agent 2 and Chat can only read masked tables (enforced in the repository layer).
- **How (both):** (1) a **deterministic layer**: regex for IDs/MRN/phone/email/dates/PIN codes, plus a deny-list from the profile (name variants, initials), plus a lab/hospital gazetteer. (2) **MedGemma** tags remaining identifiers in the structured JSON (header fields such as `patient_name`, `lab_name` and `referring_doctor` are schema fields, so they are dropped *by construction*). Structuring first means masking mostly removes fields instead of scrubbing free text.
- **Tokenised placeholders:** `[PERSON_1]`, `[LAB_1]`, `[DATE_3]`. Mapping `token → original` lives in the encrypted `token_map` table, per user and stable across reports, so trends still line up.
- **Dates:** convert to relative periods (`T0`, `T0+92d`) or month/year. Trends need intervals, not calendar dates. This reduces re-identification.
- **Re-hydration:** the API returns the reply plus the needed token→value pairs to the local client, which substitutes in the DOM. Real values never reach Claude, and replies are stored with tokens.
- **Verify:** the PII Guard re-scans every outbound payload against the deny-list, all `token_map` originals and the regexes, and blocks if anything matches. The audit log stores the exact masked payload for QA leak review.

## 4. Input routing (CPU-only)

| Input | Route | Notes |
|---|---|---|
| Excel/CSV (BMI) | `openpyxl`/`pandas` → rows → MedGemma *text* call to map columns to schema (or a pure column-mapping heuristic) | Most accurate and fastest. The LLM only labels columns and does not re-type numbers |
| Text PDF | `pypdf`/`pdfplumber` text + tables → MedGemma text structuring with JSON schema | Good accuracy; seconds to ~1 min per page on CPU |
| Scanned PDF / image | Render page to an image (`pypdfium2`) → MedGemma vision (image + schema) | Slowest (likely 1–3+ min/page on 4 cores) and highest error rate on numbers/units. Optional Tesseract OCR text can be passed alongside to cross-check values |
| Detection | PDF with < ~50 chars of extractable text per page = scanned | |

Trade-offs: a 4B model on CPU risks transposed digits and wrong units. Mitigations: deterministic text whenever possible, `temperature=0`, Ollama `format` JSON schema, a post-check that every extracted number appears in the source text (text routes), and showing extracted values to the user to confirm. TA owns the measured accuracy and timings (Q2).

## 5. Phase-2 seam (vLLM)
- Swap `OllamaClient` → `VllmClient` (OpenAI-compatible `/v1/chat/completions`, `response_format`/guided JSON, images as base64 parts) by changing config: `LOCAL_LLM_PROVIDER`, `BASE_URL`, auth.
- What changes: raw files and unmasked text now travel over the network to the vLLM server, so that server is **inside the trust boundary**. That adds TLS/mTLS, an API key, VPN/private network, no prompt logging, disk encryption and deletion on the server (Security's list). Also timeouts/retries, and possibly parallel jobs (a broker becomes debatable only then).
- What does not change: masking, PII Guard, ClaudeGateway, store, UI.

## 6. Expected challenges
1. **TA:** "BackgroundTasks lose jobs on restart." Answer: acceptable for a single-user POC; mark failed on boot and let the user re-upload.
2. **Security:** "Where does the derived key live, and is an in-memory session key safe?" Also: field-level AES vs SQLCipher, and whether re-hydration mapping sent to the browser is a risk (it is localhost only, but still needs CORS lockdown and binding to 127.0.0.1).
3. **Security/BA:** "Rare values and age+gender+dates can re-identify." Relative dates, no lab names and rounding of extreme rare values: is that enough?
4. **TA:** "Can MedGemma 4B on 4 CPU cores meet acceptable latency/accuracy for scans?" Possibly not. We may need to label scans as "best effort" or add Tesseract.
5. **BA:** "Users must confirm extracted values?" Adds a UI step but greatly improves trust. Is it in scope for Phase 1?
