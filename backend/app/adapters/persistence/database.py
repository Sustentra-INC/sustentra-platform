from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def build_session_factory(database_url: str):
    """Create a SQLAlchemy session factory for future repository wiring."""

    engine = create_engine(database_url, future=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
