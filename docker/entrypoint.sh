#!/usr/bin/env bash
set -euo pipefail

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.production}"
export PYTHONPATH=/app/backend

cd /app

echo "[OpenMobility OS] Applying database migrations..."
python manage.py migrate --noinput

echo "[OpenMobility OS] Collecting static files..."
python manage.py collectstatic --noinput

if [ "${AUTO_SEED_DEMO:-1}" = "1" ]; then
  echo "[OpenMobility OS] Seeding demo workspaces (idempotent)..."
  python manage.py seed_demo || echo "[OpenMobility OS] Seed skipped or failed; continuing."
fi

echo "[OpenMobility OS] Starting app: $*"
exec "$@"
