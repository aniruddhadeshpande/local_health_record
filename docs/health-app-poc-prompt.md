# Project: Personal Health Report App (POC, Phase 1)

## Context
I am the Tech Manager at a smart health report company. This is a POC to show that
health reports can be analysed with AI while personal data never leaves the user's machine.
Keep it simple. Do not over-engineer.

## Working model (harness)
Use a small team of subagents that talk to each other, not a heavy process:
- Business Analyst (BA)
- Solution Architect (SA)
- Tech Architect (TA)
- Security Engineer
- Developer(s)
- QA
- Security Tester
- Code Reviewer

Rules:
- BA, SA, TA and Security Engineer collaborate during design and challenge each other's
  decisions. Record key discussion points and decisions in a short `decisions.md`.
- Use OpenSpec (https://openspec.dev/) for spec-driven development. Run `openspec --help`
  first and follow the installed version's workflow:
  explore -> propose -> [my approval] -> apply -> verify -> archive.
  Put the HLD and LLD in design.md and the developer tickets in tasks.md.
  I will interact with you while the specs are written. Explain each step briefly as we go
  so I can learn the tool.
- No TDD, no pytest and no other test frameworks, and no complex tooling. QA does practical
  functional tests after development, using a manual test checklist and simple scripted
  API calls (for example curl), and records the results.

## Product goal
A simple personal health app where a user uploads health records and gets a smart analysis
and a chat assistant, with all personal data staying local.

## Functional requirements
1. **Registration:** collect name, age, gender and a passphrase or PIN. Create a local user
   profile. Only name, age and gender are stored as profile data. The passphrase is used to
   log in and to derive the database encryption key. Security Engineer defines key handling, and the key
   is never stored in plain text.
2. **Upload:** the user can upload multiple files (blood reports, BMI Excel sheets).
   Uploads return immediately. Processing runs as a background job and the UI polls for status.
3. **Local extraction and masking (local models only):**
   - MedGemma (local) reads each file and extracts the health information.
   - Each file produces a masked version, with names, IDs, dates of birth, contact details,
     lab and hospital names and similar identifiers removed or tokenised.
   - Masked info is securely linked to the user's profile through a local mapping.
   - The mapping, original data and profile are stored encrypted in the local database.
   - Delete the original uploaded file after processing. There is no option to keep it.
     Only the extracted data and the masked version remain, stored encrypted.
4. **Smart analysis (Claude API):**
   - Only masked, de-identified data is sent to the Claude API. The user's age and gender
     are allowed to be sent with it, so Claude can give smarter, context-aware analysis.
     No name, other identifier or raw file ever leaves the machine.
   - Claude analyses one or many masked reports and produces a long-term memory summary
     of the user's health profile. Store this memory locally, encrypted, and linked to
     the profile.
   - On the next upload, use the stored memory plus the new masked report to give a
     smarter, trend-aware analysis.
5. **Chat:** after the analysis, the user can chat with a bot about their reports.
   - The chatbot uses the Claude API with the stored long-term memory as context.
   - Every outgoing chat message goes through the local PII guard first. Block or mask
     anything that matches the user's name, another identifier pattern or other personal
     detail (age and gender are allowed). Users may type
     personal details into chat, so this is a key leak risk.
   - Context sent to Claude = memory summary + latest masked report + only the last few
     chat turns. Older turns are summarised and folded into the memory periodically.
     Use prompt caching for the stable memory block.
   - Chat history is stored locally and encrypted. Placeholder tokens are swapped back to
     real values on the device before replies are shown.
   - Show a clear "not medical advice" disclaimer in the UI.

## Agents inside the app
- Agent 1 (local, MedGemma): reads blood reports and BMI Excel files, then extracts and masks.
- Agent 2 (Claude): smart report analysis and long-term memory update.
- Chat bot (Claude, masked context only, as described above).

## Non-negotiable constraints
- Claude API must never receive personal information. The only profile fields allowed to
  go out are age and gender. Add a pre-send check that blocks any payload containing the
  user's name, other known profile values or identifier patterns, and log what was sent
  (masked) for audit.
- Encryption at rest for the database, and for stored files, memory and chat history.
- Headless architecture: a Python API (backend) with the UI as a separate thin client.
- Apply SOLID principles only where they genuinely help.
- Python for the API, and plain HTML, CSS and jQuery for the frontend (Phase 1).

## Local model setup
- Phase 1: MedGemma 4B running on the user's laptop via Ollama or llama.cpp.
  CPU works (about 5 GB RAM, slower), and a GPU is optional (a 4-bit build needs about
  2.3 GB VRAM). Weights come from Hugging Face (gated model: accept the terms, use a read
  token) or from Ollama.
- Record the exact model ID, version and license terms in decisions.md.
  MedGemma is a research and development model, so its output is not a diagnosis.
- Hide the model behind a swappable `LocalLLMClient` interface.
- Phase 2 (optional, not built now): the same interface can point to a company-owned vLLM
  server. Because MedGemma reads unmasked files, that server sits inside the trust boundary.
  Security Engineer must specify the requirements: TLS, API key or mTLS, private network or
  VPN (an IP allowlist alone is not enough), no prompt logging, disk encryption, file
  deletion after processing, and no shared cloud GPU without a data processing agreement.

## Background jobs and sessions
Architects to recommend one option, with justification:
- (a) FastAPI background tasks with a job table in the local DB, or
- (b) Redis only, as queue broker (RQ or Celery) and session store.
RabbitMQ is only allowed if justified in writing, since Redis already covers queue and
sessions. If Redis is used: bind to localhost with a password, put only file IDs in
queue messages (never health or personal data), and keep session tokens short-lived.

## Questions for the SA and TA to answer (with a recommendation)
1. Should we use LangGraph, LangChain Deep Agents, or plain Python functions and the
   Anthropic SDK for the workflow? Compare on simplicity, local-model support,
   debuggability and fit for a POC. Pick the simplest option that works.
2. How do we run MedGemma locally, and what are the accuracy trade-offs for PDF, image
   and Excel inputs? Test on sample blood-report PDFs and BMI Excel files and report the
   measured accuracy and minimum hardware.
3. What masking approach is reliable enough (model-based, rules-based, or both), and how
   do we verify nothing leaks? Include re-identification risks such as lab names, dates
   and rare values.
4. How is long-term memory stored and updated so it stays useful without growing forever?
5. Background jobs: option (a) or (b) above?

## Process and approval gates
1. BA, SA, TA and Security Engineer discuss and produce: HLD, LLD, a data flow diagram
   showing what stays local vs what goes to Claude, and the OpenSpec specs.
2. Security Engineer reviews the architecture and records findings and fixes.
3. **Stop and share all artifacts with me for approval** (HLD, LLD, specs, security review,
   answers to the questions above). Do not start development before I approve.
4. After approval, I will tell the TA to break the work into tickets and assign them
   to developer agents.
5. Development, then Code Reviewer, then QA, then Security Tester, with a short report
   from each.
6. Prepare the code documentation and sequence diagrams (see below), then share them with me.

## Documentation
Prepare code documentation and sequence diagrams as Claude HTML artifacts: self-contained
HTML pages I can open in a browser with no server (diagrams as inline SVG or bundled
Mermaid, not loaded from the internet).
- Code documentation: modules, API endpoints, data model, configuration, and how the local
  model and Claude API are called.
- Sequence diagrams, at minimum for: registration and login, file upload through extraction,
  masking and local storage, masked analysis and memory update with Claude, and chat with
  the PII guard. Mark clearly what stays local and what goes to Claude.

## Deliverables for Phase 1
- Working local POC (API + simple UI) covering the requirements above
- Architecture docs, OpenSpec specs, decisions.md
- Code documentation and sequence diagrams as HTML artifacts
- Short README with setup steps and how to download and run the local model
- QA test checklist and results, and the security test summary
