"""Start Safari Zone's first discovery as a silent baseline.

Revision ID: c7a68c5d23e4
Revises: b9f0466b7e12
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "c7a68c5d23e4"
down_revision = "b9f0466b7e12"
branch_labels = None
depends_on = None

URL = "https://safari-zone.com/collections/pokemon"


def upgrade():
    connection = op.get_bind()
    exists = connection.scalar(sa.text("SELECT id FROM discovery_sources WHERE url = :url"), {"url": URL})
    if exists is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        connection.execute(sa.text("""
            INSERT INTO discovery_sources
                (retailer, url, enabled, baseline_complete, next_scan_at, created_at)
            VALUES (:retailer, :url, :enabled, :baseline_complete, :now, :now)
        """), {"retailer": "Safari Zone Collectibles", "url": URL,
                "enabled": True, "baseline_complete": False, "now": now})


def downgrade():
    connection = op.get_bind()
    connection.execute(sa.text("""
        DELETE FROM discovery_sources
        WHERE url = :url AND baseline_complete = :baseline_complete
          AND NOT EXISTS (SELECT 1 FROM discovered_products
                          WHERE discovered_products.source_id = discovery_sources.id)
    """), {"url": URL, "baseline_complete": False})
