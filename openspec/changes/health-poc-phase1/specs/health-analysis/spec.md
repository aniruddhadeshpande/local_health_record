# Spec Delta

## Purpose

Turns the user's masked reports into a plain-language, trend-aware analysis using Claude, and maintains a bounded long-term health memory that makes each later analysis smarter.

## ADDED Requirements

### Requirement: User-triggered batch analysis
When the user clicks Analyse on a reviewed batch, the system SHALL run one analysis job covering every successful file in that batch, along with the stored memory and the user's age and gender. Analysis job states SHALL be `queued`, `analysing`, `done`, `blocked_pii` and `failed`.

#### Scenario: Analyse a batch of three reports
- **WHEN** the user clicks Analyse on a batch with three successful files
- **THEN** exactly one analysis job runs and produces one analysis covering all three

### Requirement: Analysis content
Each analysis SHALL include:
- a summary in plain language;
- values outside their reference range;
- trends against earlier results, when memory holds them;
- suggested questions to ask a doctor;
- a "not medical advice" disclaimer.

It SHALL NOT present a diagnosis.

#### Scenario: First analysis
- **WHEN** a user with no memory gets their first analysis
- **THEN** it contains a summary, out-of-range values, suggested doctor questions and the disclaimer, and says that no trend history exists yet

#### Scenario: Trend-aware follow-up
- **WHEN** a later batch contains a test that also appears in memory
- **THEN** the analysis states the direction and size of change and the interval in days

### Requirement: Structured long-term memory
The system SHALL keep one memory document per profile, stored encrypted locally. It SHALL follow a fixed schema: key results with relative dates, trends, conditions noted, and chat-derived notes. It SHALL contain no fields for location, employer or other people, and SHALL be capped at about 1,500 tokens. Free-text notes SHALL be limited to 10 entries of at most 120 characters each.

#### Scenario: Memory stays bounded
- **WHEN** many batches have been analysed over time
- **THEN** the memory document never exceeds the size cap, and older detail is summarised rather than appended

### Requirement: Memory update after analysis
After each analysis, the system SHALL replace the memory with an updated version produced by Claude, keeping the previous version for a one-step rollback. It SHALL scan the new memory with the guard and a proper-noun check before storing it. A rejected update SHALL be audited as blocked. The user SHALL be told when memory is updated.

#### Scenario: Memory contains a quasi-identifier
- **WHEN** Claude's proposed memory contains a location, a person's name or another identifier
- **THEN** the update is rejected or masked before storage, and the previous memory stays in place

#### Scenario: Successful update
- **WHEN** an analysis completes cleanly
- **THEN** the new memory is stored encrypted, the old version is kept as the rollback copy, and the UI shows "Memory updated"

### Requirement: View memory and analyses
An authenticated user SHALL be able to view their current memory and past analyses, with placeholders replaced by real values on the server.

#### Scenario: Open memory view
- **WHEN** the user opens the memory view
- **THEN** the current memory is displayed with real dates and names restored, and the disclaimer is shown

### Requirement: Disclaimer visibility
Every screen that shows analysis, memory or chat SHALL display a clear "not medical advice" disclaimer.

#### Scenario: Analysis screen
- **WHEN** the user views any analysis
- **THEN** the disclaimer is visible without scrolling
