import logging
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext

from app.core.settings import settings
from app.models_db import *  # noqa: F403

logger = logging.getLogger(__name__)

# ================================================
# Database engine initialization
# ================================================

# TODO: Add echo=False in production
engine = create_engine(settings.DATABASE_URL, echo=settings.ENVIRONMENT == "local")

# ================================================
# Database functions
# ================================================
def get_db():
    with Session(engine) as session:
        yield session


def init_db():
    """Initialize the database by creating all tables.

    DEPRECATED: Use Alembic migrations instead.
    This function is kept for backwards compatibility only.

    For new deployments, use:
        alembic upgrade head
    """
    logger.warning(
        "init_db() is deprecated. Please use Alembic migrations: 'alembic upgrade head'"
    )
    SQLModel.metadata.create_all(engine)


def get_alembic_config() -> Config:
    """Get Alembic configuration.

    Returns:
        Config: Alembic configuration object.
    """
    # Path to alembic.ini relative to backend directory
    backend_dir = Path(__file__).parent.parent.parent
    alembic_ini_path = backend_dir / "alembic.ini"

    if not alembic_ini_path.exists():
        raise FileNotFoundError(
            f"Alembic configuration not found at {alembic_ini_path}. "
            "Please ensure Alembic is properly initialized."
        )

    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return alembic_cfg


def get_current_revision() -> str | None:
    """Get the current database migration revision.

    Returns:
        str | None: Current revision ID, or None if no migrations applied.
    """
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_rev = context.get_current_revision()
        return current_rev


def get_head_revision() -> str:
    """Get the latest available migration revision.

    Returns:
        str: Head revision ID.
    """
    alembic_cfg = get_alembic_config()
    script = ScriptDirectory.from_config(alembic_cfg)
    head_rev = script.get_current_head()
    return head_rev


def check_migration_status() -> dict[str, str | bool]:
    """Check if database migrations are up to date.

    Returns:
        dict: Status information with keys:
            - current: Current database revision
            - head: Latest available revision
            - up_to_date: Whether database is up to date
    """
    try:
        current = get_current_revision()
        head = get_head_revision()
        up_to_date = current == head

        return {
            "current": current or "No migrations applied",
            "head": head,
            "up_to_date": up_to_date,
        }
    except Exception as e:
        logger.error(f"Failed to check migration status: {e}")
        return {
            "current": "Unknown",
            "head": "Unknown",
            "up_to_date": False,
        }


def get_session():
    """Get a database session from the engine.

    This is a generator function that yields a SQLModel Session object.
    It is designed to be used as a dependency in FastAPI endpoints.
    The session is automatically closed when the context exits.

    Yields:
        Session: A SQLModel database session.

    Example:
        >>> from fastapi import Depends
        >>> def my_endpoint(session: Session = Depends(get_session)):
        ...     # Use session here
        ...     pass
    """
    with Session(engine) as session:
        yield session
