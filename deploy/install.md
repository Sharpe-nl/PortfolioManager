# PortfolioManager — Installation Guide (LXC on Proxmox)

## Requirements

- Debian 12 LXC (1 vCPU, 1 GB RAM, 8 GB disk)
- Outbound internet access for `pip install` and initial price fetches
- Python 3.11 (available via `apt`)

---

## Step 1 — Provision the LXC

Create a Debian 12 LXC in Proxmox.  Suggested settings:

```
Cores:    1
Memory:   1024 MB
Swap:     512 MB
Disk:     8 GB
Network:  static IP, e.g. 192.168.1.100
Hostname: portfoliomanager
```

---

## Step 2 — Install system dependencies

```bash
apt update && apt upgrade -y
apt install -y python3.11 python3.11-venv python3.11-dev git
```

---

## Step 3 — Create a dedicated user

```bash
useradd --system --create-home --shell /bin/false service_portfolio_manager
```

---

## Step 4 — Clone the repository

```bash
cd /opt
git clone https://your-repo-url portfoliomanager
chown -R service_portfolio_manager:service_portfolio_manager /opt/portfoliomanager
```

---

## Step 5 — Python virtual environment & dependencies

```bash
cd /opt/portfoliomanager
sudo -u service_portfolio_manager python3.11 -m venv .venv
sudo -u service_portfolio_manager .venv/bin/pip install --upgrade pip
sudo -u service_portfolio_manager .venv/bin/pip install -r requirements.txt
```

---

## Step 6 — Configure the reverse proxy (Nginx Proxy Manager)

Chart.js and Pico.css are committed in `app/static/vendor`, so no frontend asset download is required after cloning.

TLS is terminated at the proxy; uvicorn runs plain HTTP on port 8443 and
is never exposed directly to the internet.

In **Nginx Proxy Manager**, create a new Proxy Host:

| Field | Value |
|-------|-------|
| Domain name | e.g. `portfolio.lan` or the IP/hostname you use |
| Scheme | `http` |
| Forward Hostname / IP | LXC IP, e.g. `192.168.1.100` |
| Forward Port | `8443` |
| SSL | your signed certificate (Let's Encrypt or uploaded) |
| Force SSL | ✓ enabled |

Add these custom Nginx directives under **Advanced** so uvicorn receives
the correct forwarded headers:

```nginx
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header Host              $host;
proxy_read_timeout 120;
proxy_send_timeout 120;
```

Uvicorn is already started with `--forwarded-allow-ips="*"` in the
service file, so it will trust these headers and present `https` as the
request scheme to the application.  This is required for the session
cookie (`Secure` flag) and for WebAuthn to construct the correct origin.

The hostname in the browser must remain stable after registering a WebAuthn
credential. The application derives the RP ID from the forwarded `Host` header.

### Alternative: nginx with an existing certificate

If nginx itself owns your certificate, proxy HTTPS to the local application:

```nginx
server {
    listen 443 ssl;
    server_name portfolio.example.lan;
    ssl_certificate     /etc/letsencrypt/live/portfolio.example.lan/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/portfolio.example.lan/privkey.pem;
    location / {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

---

## Step 7 — Install and start the systemd service

```bash
cp /opt/portfoliomanager/deploy/portfoliomanager.service \
   /etc/systemd/system/portfoliomanager.service
systemctl daemon-reload
systemctl enable portfoliomanager
systemctl start portfoliomanager
systemctl status portfoliomanager
```

---

## Step 8 — First login (YubiKey registration)

1. Open the URL configured in your proxy manager (e.g. `https://portfolio.lan`).
2. The app redirects to the **YubiKey registration** page (only shown when
   no credentials exist yet).
3. Insert your YubiKey and click the registration button.
4. Touch the YubiKey when the browser prompts.
5. You are redirected to the login page.  Insert your YubiKey and log in.

> If you access the app from a second device / browser, you may need to
> re-register the same YubiKey (or add a second credential) via the
> Settings page once logged in.

---

## Backup

### Manual backup

```bash
sqlite3 /opt/portfoliomanager/data/portfolio.db \
    ".backup /opt/portfoliomanager/data/portfolio-$(date +%Y%m%d).db"
```

### Automated nightly backup (keep 30 days)

```bash
cat > /etc/cron.daily/portfoliomanager-backup << 'EOF'
#!/bin/bash
BACKUP_DIR=/opt/portfoliomanager/data/backups
mkdir -p "$BACKUP_DIR"
sqlite3 /opt/portfoliomanager/data/portfolio.db \
    ".backup ${BACKUP_DIR}/portfolio-$(date +%Y%m%d).db"
find "$BACKUP_DIR" -name "portfolio-*.db" -mtime +30 -delete
EOF
chmod +x /etc/cron.daily/portfoliomanager-backup
```

**Proxmox-backed mount:** mount a Proxmox shared directory (e.g. NFS from
the Proxmox host) at `/opt/portfoliomanager/data/backups` so backups
survive LXC deletion.

---

## Update procedure

### Automatic (recommended) — deploy from your workstation

```bash
# Set the server address once (or add it to your shell profile)
export PM_SERVER=root@192.168.1.100

# Copy code and restart the service
bash scripts/deploy_to_server.sh
```

The script uses `rsync`, excludes `data/` and `.venv/`, and runs `deploy/update.sh` on the server.

### Manual — on the server

```bash
sudo bash /opt/portfoliomanager/deploy/update.sh
```

This script updates Python dependencies, corrects permissions, and restarts the service.

---

## Alternative: direct TLS without a proxy

If you prefer to skip the reverse proxy and have uvicorn serve HTTPS
directly, generate a self-signed certificate:

```bash
openssl req -x509 -newkey rsa:4096 \
    -keyout /opt/portfoliomanager/data/server.key \
    -out    /opt/portfoliomanager/data/server.crt \
    -days 3650 -nodes -subj "/CN=portfoliomanager"
chmod 600 /opt/portfoliomanager/data/server.key
```

Then change `ExecStart` in the service file to add:

```
    --ssl-keyfile /opt/portfoliomanager/data/server.key \
    --ssl-certfile /opt/portfoliomanager/data/server.crt \
```

And remove `--forwarded-allow-ips` (not needed without a proxy).
Browsers will show a certificate warning; add a permanent exception.

Use a stable hostname that matches the certificate common name when registering WebAuthn credentials.

---

## Logs

```bash
journalctl -u portfoliomanager -f
```
