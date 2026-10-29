
from __future__ import annotations

import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.config.settings import get_settings
from src.database.connection import create_db_engine


def main() -> int:
    engine = None

    try:
        settings = get_settings()
        engine = create_db_engine(settings)

        with engine.connect() as connection:
            details = connection.execute(
                text(
                    """
                    SELECT
                        DATABASE() AS database_name,
                        CURRENT_USER() AS authenticated_account,
                        VERSION() AS server_version
                    """
                )
            ).mappings().one()

            if details["database_name"] != settings.db_name:
                raise RuntimeError(
                    "Connected database does not match DB_NAME."
                )

            visible_tables = connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = :database_name
                      AND table_type = 'BASE TABLE'
                    """
                ),
                {"database_name": settings.db_name},
            ).scalar_one()

        print("MySQL connection: OK")
        print(f"Database: {details['database_name']}")
        print(f"Account: {details['authenticated_account']}")
        print(f"MySQL version: {details['server_version']}")
        print(f"Visible base tables: {visible_tables}")

        return 0

    except (SQLAlchemyError, RuntimeError, ValueError) as exc:
        print(f"Connection check failed: {type(exc).__name__}")
        print(str(exc))
        return 1

    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
