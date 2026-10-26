from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def create_database_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


@lru_cache
def get_engine(database_url: str) -> Engine:
    return create_database_engine(database_url)


@lru_cache
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = get_engine(database_url)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def get_db_session() -> Generator[Session, None, None]:
    with get_session_factory(get_settings().database_url)() as session:
        yield session
