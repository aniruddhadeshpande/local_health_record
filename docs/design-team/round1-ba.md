# Round 1 – Business Analyst position

> Target path once plan mode is lifted: `docs/design-team/round1-ba.md` (copy verbatim).

## 1. Personas & journeys
- **Priya (primary)**: health-conscious adult, non-technical, uploads quarterly blood PDFs and a BMI Excel sheet; wants plain-language trends; fears data leaks.
- **Tech Manager (demo viewer)**: needs visible proof that PII never leaves the laptop (audit log).

Journeys:
1. **Register** name/age/gender/passphrase -> profile created -> logged in.
2. **Login** with passphrase -> DB unlocked -> session token.
3. **Upload** 1..N files -> immediate "accepted" with job IDs -> UI polls -> per-file status `queued -> extracting -> masking -> analysing -> done | failed`.
4. **View analysis** (latest + memory summary) with disclaimer.
5. **Next upload** -> analysis shows "compared with previous" trends.
6. **Chat** about reports; user sees when a message was masked/blocked.

## 2. User stories & acceptance criteria

### user-profile
- US-1 Register. WHEN valid name, age (1–120), gender, passphrase (>= 8 chars, or 6-digit PIN — TBD) THEN profile is created; only name/age/gender persisted (encrypted); passphrase never stored in plain text. WHEN a profile already exists THEN registration is refused (single-user assumption, see Q2).
- US-2 Login. WHEN correct passphrase THEN session token (short-lived) issued and DB unlocked. WHEN wrong THEN generic error, no hint; after 5 failures a delay applies.
- US-3 Logout. WHEN logout THEN token invalidated and key dropped from memory.

### report-ingestion
- US-4 Multi-upload. WHEN user uploads 1..10 files of supported type (PDF, PNG/JPG, XLSX/CSV) <= 10 MB each THEN API responds <1 s with one job ID per file. WHEN type/size unsupported THEN that file is rejected with reason; others still accepted.
- US-5 Status polling. WHEN UI polls job ID THEN returns status + step + error message (no health data). WHEN job fails THEN status `failed` with a user-readable reason and original file still deleted.
- US-6 Original deletion. WHEN processing ends (success or failure) THEN original file no longer exists on disk; only encrypted extracted + masked data remain.

### pii-masking
- US-7 Extraction. WHEN file processed THEN MedGemma (local) extracts test name, value, unit, reference range, test date (relative/shifted).
- US-8 Masking. WHEN extracted THEN names, IDs, DOB, contact details, lab/hospital/doctor names, addresses are replaced by tokens (e.g. `[PERSON_1]`); token<->value mapping stored encrypted, linked to profile.
- US-9 Review masked view. WHEN user opens a report THEN they can see the masked version that would be sent to Claude.

### health-analysis
- US-10 First analysis. WHEN at least one masked report exists and no memory THEN Claude receives masked data + age + gender, returns analysis; memory summary created and stored encrypted.
- US-11 Trend analysis. WHEN memory exists and new report processed THEN analysis references prior values (e.g. "HbA1c up from X to Y") and memory is updated, not appended unbounded.
- US-12 Output contents (proposal): summary, out-of-range markers with values, trends vs previous, lifestyle suggestions, "discuss with a doctor" flags, disclaimer.

### chat-assistant
- US-13 Chat. WHEN user sends message THEN PII guard runs locally first; context = memory + latest masked report + last N turns.
- US-14 Guard outcome visible. WHEN message contains PII THEN it is masked (default) and the UI shows "we hid X before sending"; WHEN it cannot be safely masked THEN blocked with an explanation and the message is not sent.
- US-15 Token restore. WHEN reply contains tokens THEN real values are swapped back locally before display.
- US-16 History. Chat history stored encrypted; survives logout/login.
- US-17 Disclaimer always visible in chat and analysis views.

### security-audit
- US-18 Pre-send guard. WHEN any payload to Claude contains name/known profile values (except age, gender)/identifier patterns THEN the call is blocked and logged.
- US-19 Audit log. WHEN a payload is sent THEN its masked form, timestamp, and purpose (analysis/chat) are logged locally (encrypted) and viewable by the user.
- US-20 Encryption at rest. Inspecting DB files without passphrase reveals no readable health or profile data.

## 3. Out of scope (Phase 1)
- Multi-device sync, cloud backup, multi-user sharing, clinician access.
- Phase-2 vLLM server (interface only).
- Mobile/native apps; accessibility beyond basic semantic HTML.
- **Password recovery** (judgement call: with key derived from passphrase, recovery = data loss; we state it clearly at registration).
- Profile editing / passphrase change (judgement call — possibly a stretch goal since it requires re-keying).
- Export/delete-my-data (judgement call — "delete profile" is cheap and good for demo; propose as stretch).
- Medical diagnosis, prescriptions, emergency alerts.
- Non-English reports, handwritten scans, DICOM/imaging.
- Keeping original uploaded files (brief explicitly forbids).

## 4. Open questions
1. **Forgotten passphrase**: confirm "no recovery, data unrecoverable" is acceptable for POC; add a warning + confirmation checkbox at registration? (Tech Manager)
2. **One laptop = one user?** Or multiple local profiles each with own key/DB? Affects registration and login UX. BA recommends single profile for POC. (Tech Manager)
3. **PIN vs passphrase**: a 6-digit PIN is weak for key derivation; Security to set a minimum. 
4. **Smart analysis contents**: confirm US-12 list; structured (JSON sections) or free text?
5. **Supported files/sizes**: PDF (text + scanned?), images, XLSX/CSV; max size/count per batch?
6. **Dates**: are test dates allowed out (needed for trends)? Propose relative offsets or month/year only.
7. **Failed extraction**: if MedGemma output is low-confidence, do we show a "please check" state or drop the file (original already deleted)?
8. **Report of someone else** (e.g. a parent's report uploaded): detect name mismatch and warn, or ignore?
9. **Chat summarisation cadence**: every N turns? Is user told memory changed?
10. **Session timeout** value and whether background jobs continue after logout (key needed to write encrypted data).

## 5. Challenges I expect to raise
1. **Block vs mask in chat**: blocking frustrates users; I'll push for mask-by-default with visible feedback, block only on unresolvable matches. The user must never be left guessing why a message vanished.
2. **Deleting originals on failure**: if extraction fails, the user loses the file in the app with nothing to show. Need a clear message ("re-upload original") — or Security must justify not keeping an encrypted temp copy until success.
3. **Over-masking kills value**: stripping all dates/lab names may break trend analysis. Masking must preserve clinically useful fields (values, units, ranges, relative dates).
4. **Background jobs vs encryption key**: if the key lives only in session memory, jobs die on logout/timeout. Architects must define behaviour the user can understand.
5. **Audit visibility**: an audit log only devs can read doesn't prove the POC's point; I want a simple "What was sent to Claude" screen.
