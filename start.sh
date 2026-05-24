#!/usr/bin/env bash
# start.sh — Launch the Antrenör server on Lightsail (run as ubuntu user)
set -euo pipefail

cd "$(dirname "$0")"

# Activate virtualenv if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Port 80 requires root or CAP_NET_BIND_SERVICE — use 8000 behind nginx, or run with sudo
exec uvicorn server.api_server:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --log-level info
