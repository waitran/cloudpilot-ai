from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from cloudpilot.core.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine = create_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=3,
            pool_recycle=1800,
            hide_parameters=True,
            connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"},
        )
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            yield session

    def reachable(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return connection.scalar(text("SELECT 1")) == 1
        except Exception:
            # Never serialize or log the exception: it may include the connection URL.
            return False

    def close(self) -> None:
        self.engine.dispose()
