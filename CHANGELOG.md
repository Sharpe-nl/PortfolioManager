# Changelog

All notable user-facing changes are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## 0.4.1 — 2026-07-31

### Fixed

- LAN-warning duration buttons now use explicit high-contrast liquid-glass
  styling in both light and dark themes.

## 0.4.0 — 2026-07-31

### Changed

- The LAN-mode warning is now anchored below the screen content. Hiding it
  opens a duration picker for one day, one month, three months or one year.

## 0.3.1 — 2026-07-31

### Changed

- First-time setup now directs users only to the automatic one-time code in
  the server log; the optional `PM_SETUP_TOKEN` remains documented for admins.

## 0.3.0 — 2026-07-31

### Added

- Language and light/dark theme controls are now available before login and
  during first-time setup.

### Changed

- First-time setup now separates YubiKey and password registration into clearer
  choice panels with more visual spacing.

## 0.2.2 — 2026-07-31

### Fixed

- The LAN-mode warning is now fixed at the top of the screen on every page,
  while navigation and content remain correctly positioned beneath it.

## 0.2.1 — 2026-07-31

### Fixed

- The first-time setup screen now uses the same YubiKey and password-login
  choice as the regular login screen.

## 0.2.0 — 2026-07-31

### Added

- The login screen now starts with YubiKey sign-in and lets users switch to a
  username-and-password form or back again without leaving the page.

## 0.1.8 — 2026-07-30

### Changed

- Portable database downloads and restores now exclude all Bitvavo-derived
  crypto data. Reconnect Bitvavo after a restore to synchronize it again.

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
