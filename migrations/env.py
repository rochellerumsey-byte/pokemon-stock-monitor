from alembic import context
from monitor_app.db import Base, make_engine

target_metadata = Base.metadata


def run_migrations_online():
    engine = make_engine()
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
