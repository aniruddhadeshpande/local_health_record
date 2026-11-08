# Spec Delta

## Purpose

Lets a single local user create a profile, unlock it with a passphrase, keep a bounded session, and delete everything, without any recoverable secret being stored.

## ADDED Requirements

### Requirement: Single-profile registration
The system SHALL allow exactly one profile per install. The profile holds name, age and gender, and is protected by a passphrase of at least 10 characters. PINs SHALL NOT be accepted. Only name, age and gender are stored as profile data, and they are encrypted.

#### Scenario: Successful registration
- **WHEN** no profile exists and the user submits name, age, gender, a passphrase of 10 or more characters and the "no recovery" acknowledgement
- **THEN** the system creates the profile, stores no plaintext passphrase or key, and returns a session token

#### Scenario: Passphrase too short
- **WHEN** the submitted passphrase is shorter than 10 characters
- **THEN** the system rejects the request with a validation error and creates nothing

#### Scenario: Profile already exists
- **WHEN** a profile already exists and registration is attempted
- **THEN** the system responds with a conflict error and the existing profile is unchanged

#### Scenario: Missing no-recovery acknowledgement
- **WHEN** the user has not ticked the acknowledgement that a forgotten passphrase means permanent data loss
- **THEN** registration is rejected

### Requirement: Passphrase login
The system SHALL authenticate by trying to unlock the profile's data key with the submitted passphrase. On success it SHALL return a random session token of at least 256 bits. Error messages SHALL be generic.

#### Scenario: Correct passphrase
- **WHEN** the user submits the correct passphrase
- **THEN** the system returns a session token and the profile's data becomes readable for that session

#### Scenario: Wrong passphrase
- **WHEN** the user submits an incorrect passphrase
- **THEN** the system returns a generic authentication error and reveals no profile data

### Requirement: Login back-off
After 5 consecutive failed passphrase checks (login or delete confirmation), the system SHALL apply an exponentially increasing delay before it accepts another attempt. The counter SHALL be persisted, so it survives a restart. Key derivation SHALL run one attempt at a time.

#### Scenario: Repeated failures
- **WHEN** 5 consecutive login attempts fail
- **THEN** the next attempt is refused until the back-off delay has passed, and the delay grows with each further failure

#### Scenario: Restart does not reset back-off
- **WHEN** the API restarts after 5 failed attempts
- **THEN** the back-off delay still applies to the next attempt

### Requirement: Session lifetime
A session token SHALL expire after 15 minutes without user requests or 8 hours after login, whichever comes first. Status polling SHALL NOT reset the idle timer. Logout SHALL invalidate the token immediately.

#### Scenario: Idle expiry
- **WHEN** 15 minutes pass with no user-initiated request
- **THEN** the token is rejected and the client shows the login screen

#### Scenario: Polling does not extend session
- **WHEN** the client only polls job status for 15 minutes
- **THEN** the session still expires

#### Scenario: Logout
- **WHEN** the user logs out
- **THEN** the token is invalid at once and the data key is removed from memory

### Requirement: Worker lease
When a session expires, the system SHALL keep the data key in process memory only for jobs that were unfinished at that moment. The lease ends when the last of those jobs ends, at 8 hours after login, or on logout, whichever comes first. New uploads SHALL NOT extend it. The lease SHALL never authenticate an API request or issue a token.

#### Scenario: Batch outlives idle timeout
- **WHEN** the session expires from idleness while files are still processing
- **THEN** processing continues to completion without the user logging in again

#### Scenario: Lease cannot be used for access
- **WHEN** the session has expired while a worker lease is active, and a client calls any data endpoint with the old token
- **THEN** the request is rejected as unauthenticated

#### Scenario: Logout during processing
- **WHEN** the user logs out while jobs are unfinished
- **THEN** the data key is dropped and the remaining jobs move to `waiting_for_unlock` until the next login

### Requirement: Delete profile and data
The system SHALL let an authenticated user permanently delete the profile and all associated data: extracted data, masked reports, mapping, memory, chat, audit log and temporary files. It SHALL ask for the passphrase again to confirm.

#### Scenario: Confirmed deletion
- **WHEN** the user confirms deletion with the correct passphrase
- **THEN** the worker stops, all sessions and leases end, the database and its WAL, SHM and journal files and all temporary files are removed, an empty database is created, and registration is available again

#### Scenario: Retention notice
- **WHEN** deletion completes
- **THEN** the user is told that masked data already sent to Claude may be kept by Anthropic for up to 30 days

#### Scenario: Wrong confirmation passphrase
- **WHEN** the confirmation passphrase is wrong
- **THEN** nothing is deleted
