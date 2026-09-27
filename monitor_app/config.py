"""Validate required settings before migrations or service startup."""
import os
import sys
from sqlalchemy.engine import make_url


def validate_startup(environ=None):
    env = environ if environ is not None else os.environ
    errors = []
    raw_url = env.get("DATABASE_URL", "")
    if not raw_url:
        errors.append("DATABASE_URL is missing; set it to the Railway PostgreSQL service URL.")
    else:
        try:
            url = make_url(raw_url)
            if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg") or not url.database:
                errors.append("DATABASE_URL must be a PostgreSQL URL with a database name.")
        except Exception:
            errors.append("DATABASE_URL is invalid; use the Railway PostgreSQL DATABASE_URL reference.")
    secret = env.get("SECRET_KEY", "")
    if len(secret) < 32 or "replace-with" in secret:
        errors.append("SECRET_KEY must be a unique random value of at least 32 characters.")
    password = env.get("ADMIN_PASSWORD", "")
    if len(password) < 16 or "replace-with" in password:
        errors.append("ADMIN_PASSWORD must be a unique password of at least 16 characters.")
    port = env.get("PORT", "8000")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        errors.append("PORT must be a number between 1 and 65535; Railway normally sets it.")
    return errors


if __name__ == "__main__":
    problems = validate_startup()
    if problems:
        for problem in problems:
            print("Configuration error: " + problem, file=sys.stderr)
        raise SystemExit(1)
