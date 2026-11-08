# Round 2 – Business Analyst critique

> Target path: `docs/design-team/round2-ba.md` (written here because plan mode blocks other writes; copy verbatim).

## 1. Disagreements and gaps

**D1. Idle timeout vs long jobs.** *Challenge: Security (15 min idle; in-flight jobs fail `locked`) and TA (30 min; jobs pause `queued`).*
On CPU a scan takes 1–3 min per page, so a batch of 10 can run for 30+ min. Priya uploads, makes tea, and her batch dies halfway. "Failed" is the wrong word for something that will resume.
**Resolution:** 15-min idle (Security), but the idle clock **does not run while the user's own jobs are running**. The 8 h absolute cap still applies. When the session locks, jobs move to `waiting_for_login` (TA's status, not `locked`/`failed`). The UI says "Paused – log in to continue processing 3 files", and jobs resume on their own after login.

**D2. Restart and failure behaviour.** *Challenge: SA (mark stale jobs failed and the user re-uploads).*
TA's design keeps the encrypted temp file and retries up to 2 times. That is better for the user and costs nothing extra in security. **Resolution:** adopt TA's design. After the final failure, show: "We couldn't read *report.pdf*. For your privacy the file has been deleted. Try a clearer scan or a text PDF."

**D3. Chat: block vs mask-and-send.** *Partial concession to Security.* Known values get masked automatically. Unknown pattern hits get blocked, with a one-click "Mask and send". I accept this on three conditions:
(a) a blocked message **stays in the input box**, never cleared;
(b) the risky spans are highlighted, so TA's `422` must return local span offsets plus kind;
(c) every sent message has a collapsible "Sent to Claude" view.

**D4. Blocked analysis is a dead end.** *Challenge: Security (`blocked_pii`, show masked text).* The user can see the problem but has no way to fix it. **Resolution:** reuse the chat pattern: highlight the hit, offer "Mask this and retry", which adds a token. There is no "send anyway".

**D5. Dates.** *Concede relative offsets.* Gap: Security anchors offsets to the *first report*. Users will upload old reports after newer ones. **Resolution:** use a fixed per-profile anchor and allow negative offsets. Use day offsets, not month/year, because BMI rows can be weeks apart. The **UI always shows real dates**, re-hydrated locally. Only Claude sees offsets.

**D6. "What was sent to Claude" must be a screen, not just an API.** TA's `GET /api/audit` and Security's audit row are both necessary but not enough. **Resolution:** a Phase-1 "Privacy log" page that lists each egress (time, purpose, sent/masked/blocked) with the masked payload expandable. This is the Tech Manager's proof point.

**D7. Confirming extracted values.** *Support SA's suggestion, scoped down.* A 4B model will misread digits on scans. **Resolution:** after a batch finishes, show a read-only table of extracted values with "check this" badges on vision-route or out-of-schema values. Analysis then starts from an **"Analyse"** button, which matches TA's `POST /api/analysis`. Editing values is a stretch goal.

**D8. Login picker "Profile 1".** *Challenge: TA.* An unlabelled picker is confusing. **Resolution:** single profile for the POC, so there is no picker at all. If multi-profile is chosen, allow a user-chosen plaintext nickname, with a warning that it is not encrypted.

**D9. Upload limits.** BA and TA say 10 MB; Security says 20 MB. Phone photos and scanned PDFs often exceed 10 MB. **Resolution:** 20 MB per file and 10 files per batch, with the rejection reason shown for each file.

**D10. Memory changes are invisible.** Folding happens silently. **Resolution:** show a "Memory updated" notice linked to `GET /api/memory`.

## 2. Concessions
- Passphrase of **at least 10 characters**, no PIN. I ask for a strength hint, a diceware suggestion, and a mandatory "I understand there is no recovery" checkbox.
- No password recovery in Phase 1.
- Structured-only payloads to Claude. Free-text impressions are left out for blood/BMI reports and shown locally only.
- Plain Python + SDK, job table plus a single worker, app-level AES-GCM.
- Synchronous chat with a typing indicator. SSE later.
- Age bands at extremes (>89).

## 3. Questions for the Tech Manager
1. **Single or multiple local profiles?** Default: single.
2. **Idle timeout:** 15 min, paused while jobs run, 8 h absolute? Default: yes.
3. **Extracted-values review before analysis** (read-only, manual "Analyse")? Default: yes. Editing is a stretch goal.
4. **Privacy log screen in Phase 1 scope?** Default: yes.
5. **"Delete my profile and data" in Phase 1?** Default: yes. It is cheap (secure_delete + VACUUM), and it is a strong demo of user control.
