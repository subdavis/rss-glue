"""Database setup and session management."""
from sqlmodel import SQLModel, Session, create_engine

DATABASE_URL = "sqlite:///rss_glue.db"

engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency for FastAPI to get a database session."""
    with Session(engine) as session:
        yield session
