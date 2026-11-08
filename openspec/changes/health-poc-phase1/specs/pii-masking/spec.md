# Spec Delta

## Purpose

Produces a de-identified version of every report and chat message on the device, linked back to the profile only through an encrypted local mapping, so health data can be analysed remotely without exposing identity.

## ADDED Requirements

### Requirement: Identifier classes removed or tokenised
Each processed file SHALL produce a masked version. All of these SHALL be removed or replaced with placeholder tokens: patient name and other person names (including doctors), patient, sample and accession IDs, date of birth, phone numbers, email addresses, postal addresses, and lab, hospital and clinic names.

#### Scenario: Blood report with full header
- **WHEN** a report with a patient name, MRN, DOB, phone number, lab name and referring doctor is processed
- **THEN** its masked version contains none of those values, only placeholders such as `[LAB_1]` or no field at all

### Requirement: Placeholder tokens and encrypted mapping
Placeholders SHALL be random tokens scoped to the profile, not derived from the real value, and stable for the same value within the profile. The token-to-value mapping SHALL be stored encrypted and linked to the profile.

#### Scenario: Same lab in two reports
- **WHEN** two reports from the same lab are processed
- **THEN** both masked versions use the same lab placeholder, and the placeholder reveals nothing about the lab name

### Requirement: Relative dates
Dates in masked data SHALL be expressed only as whole-day offsets from a fixed per-profile anchor date, for example `T0+94d`. Negative offsets SHALL be allowed for older reports. The anchor date itself SHALL never appear in masked data.

#### Scenario: Older report uploaded later
- **WHEN** a report dated before the first uploaded report is processed
- **THEN** its masked date is a negative offset, and the review screen still shows the real date

### Requirement: Age band at extremes
Masked data and outgoing payloads SHALL carry the user's exact age, except that ages above 89 SHALL be sent as `90+`.

#### Scenario: Elderly user
- **WHEN** the profile age is 93
- **THEN** outgoing payloads carry `90+` as the age

### Requirement: Known-value and pattern scan
Every field eligible to leave the device SHALL be scanned before it is stored as masked data. The scan SHALL cover exact and fuzzy matches of known profile and mapping values, plus identifier patterns (phone, email, ID-like numbers, calendar dates, addresses). Any hit SHALL be tokenised or the field dropped.

#### Scenario: Name variant in a field
- **WHEN** a field contains a misspelt or differently formatted version of the user's name
- **THEN** the fuzzy match catches it and replaces it with the name placeholder

### Requirement: Constrained sendable field formats
Sendable fields SHALL have strict formats:
- test names: normalised against a local test-name list, otherwise checked for proper nouns;
- values and reference ranges: numeric or range patterns only;
- units: from an allowlist;
- flags: from a fixed set.

A field that fails its format SHALL be dropped from the masked record and flagged for review.

#### Scenario: Lab name inside a reference range
- **WHEN** a reference range reads "13-17 (Apollo method)"
- **THEN** only the numeric range is kept and the lab name is absent from the masked record

#### Scenario: Unknown test name with a proper noun
- **WHEN** an extracted test name contains a proper noun that is not in the test-name list
- **THEN** the test name is tokenised or dropped, and the value is flagged "check this"

### Requirement: Structured-only masked output
Masked reports SHALL contain only structured fields: test name, value, unit, reference range, relative date and flag. Free-text narrative, such as a doctor's impressions, SHALL stay local and SHALL NOT be part of the masked report.

#### Scenario: Report with a narrative comment
- **WHEN** a report contains a free-text interpretation paragraph
- **THEN** that paragraph is absent from the masked report

### Requirement: Server-side swap-back
Placeholders in Claude output and stored data SHALL be replaced with real values on the server before display. The Privacy log, the "Sent to Claude" view and any payload built for Claude SHALL use masked data, never swapped-back data. The mapping SHALL never be sent to the client.

#### Scenario: Reply mentions a placeholder
- **WHEN** a Claude reply contains `[LAB_1]`
- **THEN** the user sees the real lab name, and no API response contains the mapping table

#### Scenario: Privacy log stays masked
- **WHEN** the user opens the Privacy log
- **THEN** payloads are shown with placeholders, not with real values

### Requirement: Canary leak test
The project SHALL include a leak-probe script. It runs synthetic reports through the full pipeline, with canary identifiers planted in headers, test names, reference ranges and file names. It checks masked reports, audit payloads, application logs, temp directories and the raw database files for those canaries, and SHALL report zero hits before a demo.

#### Scenario: Run leak probe
- **WHEN** the leak-probe script runs against synthetic canary reports
- **THEN** it reports the number of canary hits in masked data and audit payloads, and the expected result is zero
