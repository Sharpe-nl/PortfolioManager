# Security policy

## Supported versions

Security fixes are provided for the latest version on the `main` branch. If
you run an older release, update to the latest available version before
reporting an issue where possible.

## Reporting a vulnerability

Please do **not** open a public GitHub issue for a suspected security
vulnerability.

Instead, use [GitHub's private security advisory reporting](https://github.com/Sharpe-nl/PortfolioManager/security/advisories/new) for this repository. Include:

- a clear description of the issue and its potential impact;
- the affected version or commit;
- steps to reproduce it safely;
- any suggested mitigation or fix, if available.

You will receive an acknowledgement as soon as practical. Once the issue is
confirmed, a fix will be prepared privately and coordinated disclosure will be
used before publishing details.

## Security model and deployment guidance

PortfolioManager is designed to be self-hosted. The operator is responsible
for the host, network, backups and access to the application.

- Prefer HTTPS through a reverse proxy or the included self-signed TLS setup.
  HTTPS is required for WebAuthn/passkeys and protects password logins and
  session cookies in transit.
- The optional `compose.lan.yml` mode deliberately uses HTTP for a trusted
  home network only. Never expose port `8080` to the internet, add a router
  port-forward, or use it on an untrusted network.
- Keep `data/portfolio.db`, `data/.credential_key`, backups, certificates and
  environment files private. They can contain portfolio data, session secrets
  or encrypted service credentials.
- Use a long, unique password for local password login. Add a second sign-in
  method where possible to prevent lockout.
- Give Bitvavo API keys read-only permissions. Do not enable trading or
  withdrawals.
- Keep the application and its container or system packages up to date.

## Scope

The project welcomes reports about vulnerabilities in the application source,
the official Docker configuration and documented deployment scripts. Issues in
third-party services, a compromised host, an exposed database backup or an
intentionally insecure LAN deployment are normally outside the application's
direct control, but useful hardening suggestions are still welcome.
