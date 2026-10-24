#!/bin/sh
# One container: Temporal dev server + Later worker + web app.
set -e
DATA="${DATA_DIR:-/var/data}"
mkdir -p "$DATA"

temporal server start-dev --db-filename "$DATA/temporal.db" --ip 127.0.0.1 --headless --log-level warn &

# Wait for Temporal to accept connections before starting the worker and app.
i=0
until temporal operator cluster health >/dev/null 2>&1; do
  i=$((i + 1)); [ "$i" -gt 60 ] && echo "Temporal did not start" && exit 1
  sleep 1
done
echo "Temporal is up"

# Keep the worker alive: if it crashes, restart it (reminders depend on it).
(while true; do python -m later.worker; echo "worker exited, restarting in 2s"; sleep 2; done) &

exec uvicorn later.app:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers --forwarded-allow-ips '*'
