# Changelog

All notable user-facing changes are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## 0.1.7 — 2026-07-30

### Changed

- YubiKey registration now explains the HTTPS requirement and password-login
  alternative instead of exposing a browser's technical insecure-operation
  error in LAN mode.

## 0.1.6 — 2026-07-30

### Changed

- Settings now shows an available application update as a red attention notice
  instead of a green success message.

## 0.1.5 — 2026-07-30

### Changed

- The initial password-login button activates as soon as the required values
  are valid and match. The YubiKey registration control now uses the compact,
  subtle button treatment used elsewhere in the interface.

## 0.1.4 — 2026-07-30

### Fixed

- Database backups no longer contain passkeys, password hashes, session secrets
  or encrypted Bitvavo credentials. Restoring keeps the credentials configured
  on the current installation, including when restoring an older backup.

## 0.1.3 — 2026-07-30

First stable release of PortfolioManager.

## 0.1.0-beta.3 — 2026-07-30

### Fixed

- The Docker image now includes the version marker used by Settings and the
  update check, preventing a missing-file error after first-time setup.

## 0.1.0-beta.2 — 2026-07-30

### Changed

- The trusted-LAN HTTP warning can be dismissed locally in the browser.

## 0.1.0-beta.1 — 2026-07-30

Initial public beta release.

### Highlights

- Dashboard for stocks, crypto and savings, including configurable history
  series and time ranges.
- DeGiro `Account.csv` import, read-only Bitvavo synchronization and savings
  interest tracking.
- Password login with rate limiting, plus WebAuthn/FIDO2 passkey support.
- Docker, trusted-LAN HTTP, self-signed TLS and native LXC/systemd deployment
  options.
- Database backup and restore, configurable automatic refreshes, local logo
  caching and light/dark liquid-glass themes.
