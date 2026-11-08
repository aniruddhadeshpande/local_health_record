# Spec Delta

## Purpose

Accepts multiple health files, processes them asynchronously with a local model only, and lets the user track progress and review the extracted values before any analysis happens.

## ADDED Requirements

### Requirement: Multi-file upload with immediate response
An authenticated user SHALL be able to upload up to 10 files per request. The system SHALL respond immediately, before processing starts, with a batch id and one job id per accepted file.

#### Scenario: Upload three files
- **WHEN** the user uploads two PDFs and one Excel sheet
- **THEN** the response returns at once with a batch id and three job ids in state `queued`

### Requirement: Upload validation
The system SHALL accept only PDF, PNG, JPEG, XLSX and CSV files, identified by content signature. Each file SHALL be at most 10 MB, and each PDF at most 10 pages. Macro-enabled or decompression-bomb workbooks and oversized images SHALL be rejected. Each rejected file SHALL carry its own reason, and the other files in the request SHALL still be accepted.

#### Scenario: Oversized file in a batch
- **WHEN** a batch contains one 12 MB file and two valid files
- **THEN** the two valid files are queued and the large file is rejected with a size reason

#### Scenario: Renamed executable
- **WHEN** a file named `report.pdf` does not have a PDF signature
- **THEN** it is rejected as an unsupported type

#### Scenario: Macro-enabled workbook
- **WHEN** an `.xlsm` file, or an `.xlsx` containing a VBA project or macro-enabled content type, is uploaded
- **THEN** it is rejected

#### Scenario: Decompression bomb
- **WHEN** an XLSX whose uncompressed size, entry count or compression ratio exceeds the configured limits is uploaded
- **THEN** it is rejected without being fully decompressed

### Requirement: Background processing with status polling
Files SHALL be processed one at a time by a background worker. Each file job SHALL move through `queued`, `extracting`, `masking` and `done`, or end in `failed` with a user-readable reason. `waiting_for_unlock` SHALL be used when the data key is unavailable. The client SHALL be able to poll job and batch status.

#### Scenario: Poll until done
- **WHEN** the client polls a batch while the worker processes it
- **THEN** each job's state progresses through the defined states and ends in `done` or `failed`

#### Scenario: Key unavailable
- **WHEN** the user has logged out and queued jobs remain
- **THEN** those jobs show `waiting_for_unlock` and resume automatically after the next login

### Requirement: Restart recovery
After a restart, jobs that were not in a final state SHALL return to `queued` and be retried from their encrypted temporary file. A job SHALL be marked `failed` after more than 2 attempts.

#### Scenario: Crash mid-extraction
- **WHEN** the API process stops while a job is `extracting`, and the user then logs in again
- **THEN** that job is retried automatically

### Requirement: Local-only extraction
File contents SHALL be read and structured only by the local model or local parsers. Raw file contents SHALL never be sent to any remote service. Each file SHALL produce a structured record of test name, value, unit, reference range and date. Identifiers SHALL be captured in separate identifier fields.

#### Scenario: Text PDF blood report
- **WHEN** a digital blood-report PDF is processed
- **THEN** a structured record of its tests is stored encrypted, with no network call except to the local model endpoint

#### Scenario: BMI Excel sheet
- **WHEN** an Excel sheet of dated height, weight and BMI rows is processed
- **THEN** each row becomes a dated structured measurement

#### Scenario: Scanned image report
- **WHEN** a photo or scanned PDF is processed
- **THEN** it is read by the local model's vision capability and its values are marked as lower-confidence

### Requirement: Swappable local model endpoint
The local model SHALL be selected through configuration, so a different compatible endpoint can replace it without changes to calling code. A remote endpoint that does not use TLS SHALL be refused.

#### Scenario: Non-TLS remote endpoint configured
- **WHEN** the local model URL is set to a plain-HTTP non-localhost address
- **THEN** the system refuses to start the worker and reports the configuration error

### Requirement: Read-only review of extracted values
After a batch finishes, the user SHALL be able to view a read-only table of extracted values per file, showing real dates and units. Values that came from the vision path, fall outside the expected schema or are implausible SHALL be flagged "check this". Analysis SHALL start only when the user clicks **Analyse**.

#### Scenario: Review then analyse
- **WHEN** all jobs in a batch are `done` and the user opens the review screen
- **THEN** the extracted values are listed with flags, and no Claude call has happened until the user clicks Analyse

#### Scenario: Partial batch
- **WHEN** some jobs in a batch failed
- **THEN** the review shows only the successful files, gives a reason for each failure, and still allows Analyse

### Requirement: Mismatched patient warning
If the name extracted from a file does not match the profile name, the system SHALL warn the user that the report may belong to someone else.

#### Scenario: Someone else's report
- **WHEN** an uploaded report's patient name differs from the profile name
- **THEN** the review screen shows a "this may not be your report" warning for that file
