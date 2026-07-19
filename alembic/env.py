import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core import model_registry  # noqa: F401 populates Base.metadata
from app.core.config import settings
from app.core.database import Base

config = context.config
# Pull DATABASE_URL from the app's own settings (env vars) instead of
# duplicating it in alembic.ini — one source of truth for the connection string.
# NOTE: ConfigParser (which backs alembic's Config) treats "%" as the start
# of interpolation syntax (e.g. "%(foo)s"). A password containing a
# URL-encoded character such as "%40" (for "@") breaks set_main_option
# unless every literal "%" is escaped as "%%" first.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())