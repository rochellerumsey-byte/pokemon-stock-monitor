#!/bin/sh
set -eu
python -m alembic upgrade head
python -m monitor_app.worker &
exec gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 4 --access-logfile - monitor_app.web:app
