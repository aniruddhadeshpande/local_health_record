# Spec Delta

## Purpose

Keeps all personal and health data encrypted at rest under a key derived from the user's passphrase, minimises plaintext exposure during processing, and confines the API to the local machine.

## ADDED Requirements

### Requirement: Passphrase-derived key protection
The data encryption key SHALL be random. It SHALL be stored only in wrapped form, encrypted under a key derived from the passphrase with a memory-hard KDF (Argon2id, at least 64 MiB memory and 3 iterations). The KDF parameters and salt SHALL be stored with the wrapped key. Neither the passphrase, nor the derived key, nor a passphrase hash SHALL be stored.

#### Scenario: Inspect stored key material
- **WHEN** the database and data folder are inspected after registration
- **THEN** they contain only the salt, the KDF parameters and the wrapped key, with no passphrase, no plaintext key and no passphrase hash

### Requirement: Encryption at rest
Profile fields, extracted data, masked reports, the token mapping, memory, chat history and audit payloads SHALL be stored with authenticated encryption (AES-256-GCM). Each value SHALL use a fresh nonce and be bound to its table and row. Only identifiers, timestamps, job status and file type MAY be stored in plaintext.

#### Scenario: Raw database inspection
- **WHEN** the database file is opened with a generic SQLite tool
- **THEN** no name, health value, mapping value, memory text or chat text is readable

#### Scenario: Tampered or moved ciphertext
- **WHEN** an encrypted value is modified or copied into another row
- **THEN** decryption fails and the system reports an integrity error instead of returning data

### Requirement: Plaintext uploads never written to disk
Uploaded files SHALL be held in memory and written to disk only in encrypted form, in owner-only temporary files with random names. Requests whose declared or streamed size exceeds the batch limit SHALL be rejected before any part of the body is spooled to disk. Decrypted content SHALL exist only in process memory.

#### Scenario: Upload a 9 MB PDF
- **WHEN** a 9 MB file is uploaded
- **THEN** no plaintext copy appears in the OS temp directory or the data folder at any point

#### Scenario: Oversized request body
- **WHEN** a request larger than the total upload limit is sent
- **THEN** it is rejected and nothing is written to the OS temp directory

### Requirement: Original files deleted after processing
The encrypted temporary copy of each upload SHALL be deleted when its job reaches a final state (done or failed). There SHALL be no option to keep originals. Leftover temporary files SHALL be swept at startup, and any unprocessed for more than 24 hours SHALL be deleted.

#### Scenario: Successful processing
- **WHEN** a file job completes
- **THEN** its temporary file no longer exists, and only encrypted extracted and masked data remain

#### Scenario: Failed processing
- **WHEN** a file job fails permanently
- **THEN** its temporary file is deleted and the user is told the original was removed for privacy

### Requirement: Data key held only in memory
While a session or worker lease is active, the data key SHALL exist only in process memory. It SHALL be discarded on logout, on session and lease expiry, and when the process exits.

#### Scenario: Process restart
- **WHEN** the API process restarts
- **THEN** no data can be decrypted until the user logs in again

### Requirement: Local-only API surface
The API SHALL listen only on 127.0.0.1 and reject requests whose Host header is not a local host name. The web client SHALL be served from the same origin. The local model endpoint SHALL also be local-only.

#### Scenario: Remote access attempt
- **WHEN** another machine on the network tries to connect to the API port
- **THEN** the connection is not accepted

#### Scenario: Foreign Host header
- **WHEN** a request arrives with a Host header that is not localhost or 127.0.0.1
- **THEN** the request is rejected

### Requirement: No sensitive logging
The system SHALL NOT log or echo bodies, prompts, model outputs, extracted values or passphrases, including in SDK or HTTP-client debug logs, validation error responses and job error messages. Job errors SHALL be fixed codes. The Anthropic API key SHALL come from an owner-only, git-ignored env file and never be stored in the DB or sent to the client.

#### Scenario: Validation error does not echo input
- **WHEN** a request fails validation, for example registration with an invalid age
- **THEN** the error response names the invalid field but does not contain the submitted values

#### Scenario: SDK debug logging requested
- **WHEN** the API is started with Anthropic SDK debug logging enabled in the environment
- **THEN** it refuses to start and reports why

#### Scenario: Log review after a full workflow
- **WHEN** application logs are reviewed after registration, upload, analysis and chat
- **THEN** they contain no names, health values, prompts or keys

### Requirement: Safe rendering of model output
The client SHALL render model-generated and audit text as escaped text or a sanitised markdown subset. Raw HTML from those sources SHALL never be inserted into the page.

#### Scenario: Model returns HTML
- **WHEN** a Claude reply contains `<script>` or other HTML markup
- **THEN** it is displayed as literal text and is not executed

### Requirement: Security response headers
All responses SHALL include a Content-Security-Policy header that allows only same-origin scripts, sets `frame-ancestors 'none'` and permits no inline script. They SHALL also include `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. API responses SHALL include `Cache-Control: no-store`.

#### Scenario: Header check
- **WHEN** the index page and any `/api/*` response are fetched
- **THEN** the CSP, nosniff and referrer headers are present, and API responses are marked no-store
