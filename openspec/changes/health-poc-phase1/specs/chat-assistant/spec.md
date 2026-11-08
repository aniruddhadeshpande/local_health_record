# Spec Delta

## Purpose

Lets the user ask questions about their reports in a chat backed by Claude, while a local guard stops personal details they type from leaving the machine.

## ADDED Requirements

### Requirement: Chat availability
Chat SHALL be available once at least one analysis has completed. Each reply SHALL draw on the user's memory and latest masked report, and the chat screen SHALL show the "not medical advice" disclaimer.

#### Scenario: Chat before any analysis
- **WHEN** the user opens chat with no completed analysis
- **THEN** the client explains that chat unlocks after the first analysis

#### Scenario: Ask about a result
- **WHEN** the user asks "why is my HbA1c flagged?"
- **THEN** the reply refers to the user's own masked results and memory

### Requirement: Bounded chat context
Each chat request SHALL contain only the system instructions, the memory, the latest masked report, the most recent turns (at most 6) and the new masked message. The stable leading block of system instructions and memory SHALL be marked for prompt caching.

#### Scenario: Long conversation
- **WHEN** the conversation has 20 turns
- **THEN** only the last 6 turns are sent verbatim, and the audit payload shows no older turns

### Requirement: Chat PII guard: auto-mask known values
Before sending, known profile and mapping values found in the user's message (exact or fuzzy) SHALL be replaced with placeholders automatically. The user SHALL be told what was hidden.

#### Scenario: User types their name
- **WHEN** the user writes "Hi, I'm <their name>, is my LDL ok?"
- **THEN** the name is replaced with a placeholder before sending, and the UI shows "we hid your name"

### Requirement: Chat PII guard: confirm before masking unknown identifiers
When a message matches an identifier pattern that is not a known value (a phone number, an email, an ID-like number, a date or an address), the message SHALL NOT be sent. The response SHALL list the matching spans, and the message SHALL stay editable in the input box. The user MAY choose "Mask and send", which tokenises those spans and re-scans the message.

#### Scenario: User types a phone number
- **WHEN** the message contains a phone number
- **THEN** nothing is sent, the number is highlighted, and the draft remains in the input box

#### Scenario: Mask and send
- **WHEN** the user chooses "Mask and send"
- **THEN** the spans are tokenised, the message is re-scanned, and it is sent only if clean

#### Scenario: Guard failure
- **WHEN** the guard errors on a chat message
- **THEN** nothing is sent and the user is told so

### Requirement: Placeholder swap-back in replies
Replies SHALL have their placeholders replaced with real values on the server before display. A "Sent to Claude" view SHALL show each user message exactly as it was sent.

#### Scenario: Reply references a placeholder
- **WHEN** Claude's reply mentions `[LAB_1]`
- **THEN** the user sees the real lab name, and the "Sent to Claude" view still shows the placeholder

### Requirement: Encrypted chat history
Chat history SHALL be stored locally, encrypted, in masked form only, and SHALL be shown with real values restored.

#### Scenario: Reload chat
- **WHEN** the user logs in again and opens chat
- **THEN** previous turns are shown with real values restored, while the stored rows contain only masked ciphertext

### Requirement: Fold older turns into memory
When the conversation holds more than 12 turns that have not yet been folded into memory, the system SHALL fold the oldest 6 into the long-term memory. The fold call SHALL pass the same egress guard and audit as any other call, and the updated memory SHALL be guard-scanned before it is stored.

#### Scenario: Thirteenth unfolded turn
- **WHEN** a thirteenth unfolded turn is added
- **THEN** the oldest 6 unfolded turns are folded into memory, the fold call appears in the Privacy log, and the memory stays within its size cap
