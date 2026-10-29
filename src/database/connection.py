
from __future__ import annotations

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine

from src.config.settings import Settings, get_settings


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Create a MySQL connection engine without modifying database data."""
    current = settings or get_settings()
    password = current.db_password.get_secret_value()

    if not password or password == "replace_locally":
        raise RuntimeError(
            "Set a valid DB_PASSWORD in your local .env file."
        )

    url = URL.create(
        drivername="mysql+pymysql",
        username=current.db_user,
        password=password,
        host=current.db_host,
        port=current.db_port,
        database=current.db_name,
        query={"charset": "utf8mb4"},
    )

    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": current.db_connect_timeout},
        echo=False,
    )
