"""Retry the seeded Safari Zone baseline after the rolling-deploy handoff.

Revision ID: e5a1c0d84b2f
Revises: c7a68c5d23e4
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "e5a1c0d84b2f"
down_revision = "c7a68c5d23e4"
branch_labels = None
depends_on = None

URL = "https://safari-zone.com/collections/pokemon"


def upgrade():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.get_bind().execute(sa.text("""
        UPDATE discovery_sources
        SET next_scan_at = :now, last_error = NULL
        WHERE url = :url AND baseline_complete = :pending
    """), {"now": now, "url": URL, "pending": False})


def downgrade():
    pass
