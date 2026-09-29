"""Store available release and image metadata on monitored products.

Revision ID: b9f0466b7e12
Revises: d1b86c024442
"""
from alembic import op
import sqlalchemy as sa

revision = "b9f0466b7e12"
down_revision = "d1b86c024442"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("products", sa.Column("release_date", sa.String(length=40), nullable=True))
    op.add_column("products", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("products", "image_url")
    op.drop_column("products", "release_date")
