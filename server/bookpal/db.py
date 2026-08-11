"""Database-engine en sessies.

SQLite in WAL-modus: dat laat de scanner schrijven terwijl de API leest, wat op
een NAS met één proces precies genoeg is en geen extra container kost.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from bookpal.config import settings
from bookpal.models import Base, User

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _configure_sqlite(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings.ensure_dirs()
        _engine = create_engine(
            settings.database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )
        event.listen(_engine, "connect", _configure_sqlite)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Generator[Session, None, None]:
    """FastAPI-dependency."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


DEFAULT_USER = "daniel"


def init_db() -> None:
    """Maak het schema aan en zorg dat er een gebruiker is.

    Alembic is leidend voor migraties; dit pad is voor een verse database en
    voor de tests.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    with session_scope() as session:
        if session.query(User).count() == 0:
            session.add(User(name=DEFAULT_USER))


def current_user(session: Session) -> User:
    user = session.query(User).order_by(User.id).first()
    if user is None:
        user = User(name=DEFAULT_USER)
        session.add(user)
        session.flush()
    return user


def reset_engine() -> None:
    """Gooi de gecachte engine weg — alleen voor tests, die per test een eigen
    tijdelijke database gebruiken."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
