"""Database configuration and session management for local SQLite catalogue."""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

DEFAULT_DB_URL = "sqlite:///./data/catalogue.db"


def get_engine(db_url: str = DEFAULT_DB_URL):
    """Creates a SQLAlchemy engine configured for SQLite with WAL journal mode."""
    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    return create_engine(db_url, connect_args=connect_args)


def get_db_session(db_url: str = DEFAULT_DB_URL):
    """Session factory for database access."""
    engine = get_engine(db_url)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_factory()


def init_db(db_url: str = DEFAULT_DB_URL):
    """Initializes tables in database schema."""
    engine = get_engine(db_url)
    Base.metadata.create_all(bind=engine)
    return engine
