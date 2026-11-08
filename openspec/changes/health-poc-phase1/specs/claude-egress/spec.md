# Spec Delta

## Purpose

Guarantees that every request to the Claude API passes one guarded, audited exit point that allows only masked data plus age and gender, and lets the user see exactly what left the machine.

## ADDED Requirements

### Requirement: Single egress path
Every call to the Claude API SHALL go through one gateway, whatever its purpose (analysis, memory update, chat or fold). No other component SHALL be able to reach the Claude API.

#### Scenario: Any outbound Claude call
- **WHEN** analysis, memory update, chat or fold sends a request
- **THEN** the request passes the pre-send guard and creates an audit entry before it is transmitted

### Requirement: Allowed outbound content
Outgoing payloads SHALL contain only masked structured report data, relative dates, the long-term memory, masked chat text, placeholders, and the user's age and gender. Names, other profile values, raw files, file names, internal job, batch and row identifiers, and the mapping SHALL never be included.

#### Scenario: Analysis payload inspection
- **WHEN** an analysis payload is captured from the audit log
- **THEN** it contains age, gender and masked data only

### Requirement: Fail-closed pre-send guard
Immediately before sending, the guard SHALL scan the final serialised payload for the user's name, other known profile values, mapping values (exact and fuzzy) and identifier patterns. On any hit, scanner error or missing mapping, the request SHALL NOT be sent.

#### Scenario: Name slipped into payload
- **WHEN** the final payload contains the user's name
- **THEN** the request is not sent, the operation returns a blocked result, and the block is audited

#### Scenario: Guard error
- **WHEN** the guard throws an unexpected error
- **THEN** the request is not sent and the user sees a "could not verify privacy, nothing was sent" message

#### Scenario: Clean payload
- **WHEN** the payload has no hits
- **THEN** the request is sent and audited as `sent`

### Requirement: Audit log
Each egress attempt SHALL record time, purpose, decision (`sent`, `send_failed`, `blocked`), fired guard rule IDs (never matched values), model, payload SHA-256 and the encrypted masked payload. For blocked attempts each hit SHALL be stored as `[REDACTED:<rule>]`. The `sent` or `send_failed` result SHALL be recorded after the send. The log is append-only via the app.

#### Scenario: Blocked attempt is audited
- **WHEN** a request is blocked
- **THEN** an audit entry records purpose, `blocked` and the rule IDs, and the stored payload shows `[REDACTED:<rule>]` in place of each matched value

#### Scenario: Send failure
- **WHEN** the Claude API returns an error
- **THEN** the audit entry is recorded as `send_failed`

### Requirement: Privacy log screen
An authenticated user SHALL be able to view a Privacy log listing each egress attempt with time, purpose and decision. Each entry SHALL expand to show the exact masked payload that was, or would have been, sent.

#### Scenario: Review what was sent
- **WHEN** the user opens the Privacy log after running an analysis
- **THEN** the analysis call is listed and its expanded payload shows only masked data, age and gender

### Requirement: Blocked analysis is recoverable
When the guard blocks an analysis, the user SHALL see the masked payload with the offending spans highlighted. The user SHALL be able to mask those spans and retry. A retry SHALL accept only spans that match hits recorded by the server. The system SHALL NOT offer any option to send unmasked content.

#### Scenario: Mask and retry
- **WHEN** an analysis is `blocked_pii` and the user chooses "Mask this and retry"
- **THEN** the highlighted spans are tokenised, the payload is re-scanned, and it is sent only if the scan is clean
