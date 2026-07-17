# PortfolioManager

PortfolioManager is a private, self-hosted investment tracker. It imports DeGiro exports, tracks holdings and cash, fetches market prices, compares benchmarks, and supports WebAuthn/FIDO2 security keys.

It is designed for a small home server: one Python process, one SQLite database, no external database service, and no frontend build step.

## Interface

<table>
  <tr>
    <td align="center"><strong>Dark theme</strong></td>
    <td align="center"><strong>Light theme</strong></td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/dashboard-dark.png" alt="PortfolioManager dashboard in dark theme" width="600"></td>
    <td><img src="docs/screenshots/dashboard-light.png" alt="PortfolioManager dashboard in light theme" width="600"></td>
  </tr>
</table>

The screenshots use an isolated demo portfolio with fictitious data.

## Features

- DeGiro `Account.csv` imports with safe re-imports
- Manual accounts and generic CSV imports
- Portfolio dashboard, value history, realised/unrealised P&L, dividends and benchmark comparison
- Allocation by sector, continent and asset type, including manual ETF country weights
- Company and ETF logos through an optional Logo.dev publishable key
- WebAuthn/FIDO2 authentication (YubiKey-compatible)
- SQLite backup download from the settings page
- Responsive liquid-glass interface for desktop and mobile

## Requirements

- A modern browser
- HTTPS and a stable hostname for WebAuthn in production
- Outbound internet access if you want price updates or Logo.dev images
- One of the deployment options below

The app stores all persistent state in `data/portfolio.db`. Do not commit or share this file: it contains portfolio data, the generated session secret, WebAuthn credentials, and any saved Logo.dev key.

## Deployment options

| Option | Best for | Notes |
|---|---|---|
| Docker Compose | Most home servers | Easiest upgrades and a persistent named volume |
| Docker CLI | Existing Docker setup | Use your own reverse proxy and bind mount |
| Native systemd in an LXC | Proxmox users | Small footprint and straightforward backups |
| Direct Python | Development or a trusted LAN | Not recommended for public exposure |

In production, place the application behind a reverse proxy such as Caddy, Nginx Proxy Manager, Traefik, or nginx. Terminate TLS there and forward requests to the application. Do not expose the internal HTTP port directly to the internet.

### Choose a TLS setup

| Setup | Best choice when | Trade-off |
|---|---|---|
| Reverse proxy with a trusted certificate | You use a domain, or access the app from several devices | Recommended: browsers trust it automatically and WebAuthn works smoothly |
| nginx with your existing certificate | Your home server already runs nginx | One small proxy configuration is required |
| Self-signed certificate | A private LAN, one or a few devices, and no proxy | Fast to start, but every device must trust or accept the certificate |

For most home servers, use your existing Nginx Proxy Manager/nginx setup. A self-signed certificate is simpler on the server, but the browser warning and device trust step make it less convenient in daily use.

## Option 1: Docker Compose

```bash
git clone https://github.com/YOUR-USER/portfoliomanager.git
cd portfoliomanager
docker compose up -d --build
```

The included [compose.yml](compose.yml) binds the application to `127.0.0.1:8000` and stores data in the `portfoliomanager-data` Docker volume. Point your reverse proxy at `http://HOST:8000`.

Useful commands:

```bash
docker compose logs -f
docker compose pull
docker compose up -d --build
docker compose down                 # keeps the data volume
```

To back up the database from the volume, use the backup button in Settings or copy it from a temporary container:

```bash
docker run --rm -v portfoliomanager-data:/data -v "$PWD":/backup alpine \
  cp /data/portfolio.db /backup/portfolio-backup.db
```

## Option 2: Docker CLI

```bash
git clone https://github.com/YOUR-USER/portfoliomanager.git
cd portfoliomanager
docker build -t portfoliomanager:latest .
mkdir -p /srv/portfoliomanager/data
docker run -d \
  --name portfoliomanager \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v /srv/portfoliomanager/data:/app/data \
  -e PM_HTTPS_ONLY=true \
  portfoliomanager:latest
```

Chart.js and Pico.css are versioned in `app/static/vendor`, so the image build and application startup do not download frontend assets. The container runs as an unprivileged user and only needs write access to `/app/data`.

## Option 3: Native LXC / systemd (Proxmox)

This is a good fit for a Debian LXC container on Proxmox. A small starting point is 1 vCPU, 1 GB RAM and 8 GB disk.

```bash
apt update
apt install -y python3 python3-venv python3-dev git sqlite3

useradd --system --create-home --shell /usr/sbin/nologin service_portfolio_manager
git clone https://github.com/YOUR-USER/portfoliomanager.git /opt/portfoliomanager
chown -R service_portfolio_manager:service_portfolio_manager /opt/portfoliomanager

sudo -u service_portfolio_manager python3 -m venv /opt/portfoliomanager/.venv
sudo -u service_portfolio_manager /opt/portfoliomanager/.venv/bin/pip install -r /opt/portfoliomanager/requirements.txt

cp /opt/portfoliomanager/deploy/portfoliomanager.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now portfoliomanager
```

The service listens on port `8443`. Configure the reverse proxy to reach the LXC IP on that port and forward `Host` and `X-Forwarded-Proto` headers. See [deploy/install.md](deploy/install.md) for a more detailed LXC and proxy guide.

## Option 4: Direct Python for development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# WebAuthn permits HTTP on localhost only.
PM_HTTPS_ONLY=false uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Do not use this mode as an internet-facing production server.

## Reverse proxy and WebAuthn

WebAuthn needs a secure browser context. Use HTTPS in production and always access the application by the same hostname used when registering your security key.

Your proxy must forward at least:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

Keep `PM_HTTPS_ONLY=true` behind HTTPS. Set it to `false` only for local HTTP development.

## Self-signed TLS without a reverse proxy

This option is useful on a trusted LAN. Pick a hostname you will keep using (for example `portfolio.home`) and create a certificate on the Docker host:

```bash
mkdir -p /srv/portfoliomanager/data/tls
openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
  -keyout /srv/portfoliomanager/data/tls/server.key \
  -out /srv/portfoliomanager/data/tls/server.crt \
  -subj "/CN=portfolio.home" \
  -addext "subjectAltName=DNS:portfolio.home"
chmod 600 /srv/portfoliomanager/data/tls/server.key
```

Then run the included self-signed Compose configuration:

```bash
docker compose -f compose.selfsigned.yml up -d --build
```

Open `https://portfolio.home:8443`. Add a local DNS entry for that hostname if necessary, then trust the certificate on each device before registering a security key. The certificate and database live in `/srv/portfoliomanager/data`; keep that directory private and back it up.

## First run and settings

1. Open the site and register a FIDO2/WebAuthn authenticator.
2. Create or import an account from the Import page.
3. Add a Logo.dev **publishable** key in **Settings → Company logo API keys** if you want official logos. It is optional; the app falls back to initials.
4. Download a backup from Settings after the first successful import.

## Backups and updates

Back up `data/portfolio.db` while the app is stopped, or use SQLite's backup command:

```bash
sqlite3 data/portfolio.db ".backup 'portfolio-backup.db'"
```

For a native installation, update with:

```bash
cd /opt/portfoliomanager
git pull
sudo -u service_portfolio_manager .venv/bin/pip install -r requirements.txt
systemctl restart portfoliomanager
```

For Docker, rebuild and recreate the container with `docker compose up -d --build`. Database migrations run automatically at application startup.

## Tests and development

```bash
python -m pytest
python -m py_compile app/main.py app/routers/portfolio.py
git diff --check
```

`AGENTS.md` documents the repository conventions for contributors and coding agents.

## Project layout

```text
app/          FastAPI application, templates, static assets and services
migrations/   Ordered SQLite migrations, applied automatically at startup
tests/        Unit tests and CSV fixtures
deploy/       systemd unit and detailed LXC deployment guide
scripts/      Vendor download and maintenance utilities
data/         Local SQLite database (ignored by Git)
```

## License

Copyright © 2026 Sharpe-nl. All rights reserved.

PortfolioManager is available for personal, non-commercial use under the
[PortfolioManager Personal Use License](LICENSE). Ownership and all
intellectual-property rights remain with Sharpe-nl; redistribution, resale,
sublicensing, and commercial use require prior written permission.
