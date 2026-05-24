#!/usr/bin/env bash
# setup.sh — One-time Lightsail Ubuntu setup for Antrenör
# Run once as ubuntu user: bash setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing system packages ==="
sudo apt-get update -q
sudo apt-get install -y python3 python3-venv python3-pip nginx

echo "=== Creating Python virtualenv ==="
python3 -m venv "$REPO_DIR/.venv"
source "$REPO_DIR/.venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$REPO_DIR/requirements.txt" -q

echo "=== Creating DB directory ==="
mkdir -p "$REPO_DIR/db"

echo "=== Configuring nginx reverse proxy ==="
sudo tee /etc/nginx/sites-available/antrenor > /dev/null << 'NGINX'
server {
    listen 80 default_server;
    server_name _;

    client_max_body_size 5M;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
NGINX

sudo ln -sf /etc/nginx/sites-available/antrenor /etc/nginx/sites-enabled/antrenor
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

echo "=== Installing systemd service ==="
sudo tee /etc/systemd/system/antrenor.service > /dev/null << UNIT
[Unit]
Description=Antrenör Trainer App
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$REPO_DIR
EnvironmentFile=$REPO_DIR/.env
ExecStart=$REPO_DIR/.venv/bin/uvicorn server.api_server:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable antrenor
sudo systemctl restart antrenor

echo ""
echo "=== Setup complete ==="
echo "Check status:  sudo systemctl status antrenor"
echo "View logs:     sudo journalctl -u antrenor -f"
echo ""
echo "Don't forget to copy .env.example to .env and fill in your keys!"
