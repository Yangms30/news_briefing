from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# SQLite ignores FOREIGN KEY constraints unless PRAGMA foreign_keys is ON per
# connection. Without this, bulk `.delete()` calls leave orphan child rows that
# can get reattached when SQLite reuses a freed PK id. We hit exactly that bug
# — 3 articles from a deleted Report resurfaced under a new Report that
# reused the same id. Turning the PRAGMA on makes SQLite enforce cascades
# defined in the ORM relationships (cascade="all, delete-orphan") at the DB
# layer too, so stray bulk deletes can't leave dangling children.
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(Engine, "connect")
    def _sqlite_fk_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
