#!/bin/bash
set -Eeuo pipefail
python -m monitor_app.config
python -m alembic upgrade head

worker_pid=
web_pid=
stop_children() {
    if [[ -n "$worker_pid" ]]; then kill "$worker_pid" 2>/dev/null || true; fi
    if [[ -n "$web_pid" ]]; then kill "$web_pid" 2>/dev/null || true; fi
    if [[ -n "$worker_pid" ]]; then wait "$worker_pid" 2>/dev/null || true; fi
    if [[ -n "$web_pid" ]]; then wait "$web_pid" 2>/dev/null || true; fi
}
on_term() {
    trap - TERM INT
    stop_children
    exit 0
}
trap on_term TERM INT

python -m monitor_app.worker &
worker_pid=$!
gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 4 --access-logfile - monitor_app.web:app &
web_pid=$!

set +e
wait -n "$worker_pid" "$web_pid"
status=$?
set -e
echo "Web server or monitoring worker exited; stopping service for restart." >&2
stop_children
if [[ "$status" -eq 0 ]]; then exit 1; fi
exit "$status"
