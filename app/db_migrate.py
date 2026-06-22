import argparse
import asyncio
import hashlib
from pathlib import Path

from app import config
from app.db import connect


MIGRATIONS_DIR = config.BASE_DIR / "migrations"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Apply SQL migrations.")
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Mark existing migrations as applied without executing them.",
    )
    args = parser.parse_args()

    connection = await connect()
    try:
        await ensure_schema_migrations(connection)
        migrations = migration_files()
        applied = await applied_migrations(connection)

        for migration in migrations:
            checksum = file_checksum(migration)
            if migration.name in applied:
                if applied[migration.name] != checksum:
                    raise RuntimeError(f"Checksum mismatch for applied migration: {migration.name}")
                print(f"SKIP {migration.name}")
                continue

            if args.baseline:
                await record_migration(connection, migration.name, checksum)
                print(f"BASELINE {migration.name}")
                continue

            sql = migration.read_text(encoding="utf-8")
            statements = split_sql(sql)
            async with connection.cursor() as cursor:
                for statement in statements:
                    try:
                        await cursor.execute(statement)
                    except Exception as exc:
                        if is_duplicate_column_error(exc):
                            print(f"SKIP duplicate column in {migration.name}")
                            continue
                        raise
            await record_migration(connection, migration.name, checksum)
            print(f"APPLIED {migration.name}")
    finally:
        connection.close()


async def ensure_schema_migrations(connection) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("SHOW TABLES LIKE 'schema_migrations'")
        if await cursor.fetchone():
            return

        await cursor.execute(
            """
            CREATE TABLE schema_migrations (
                version VARCHAR(255) NOT NULL PRIMARY KEY,
                checksum CHAR(64) NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )


def migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(path for path in MIGRATIONS_DIR.glob("*.sql") if path.is_file())


async def applied_migrations(connection) -> dict[str, str]:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT version, checksum FROM schema_migrations")
        rows = await cursor.fetchall()
    return {str(version): str(checksum) for version, checksum in rows}


async def record_migration(connection, version: str, checksum: str) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            INSERT INTO schema_migrations (version, checksum)
            VALUES (%s, %s)
            """,
            (version, checksum),
        )


def file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_sql(sql: str) -> list[str]:
    statements = []
    current = []
    quote = None
    i = 0

    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ""

        if quote:
            current.append(char)
            if char == quote and next_char != quote:
                quote = None
            elif char == quote and next_char == quote:
                current.append(next_char)
                i += 1
        elif char in {"'", '"', "`"}:
            quote = char
            current.append(char)
        elif char == "-" and next_char == "-":
            i += 2
            while i < len(sql) and sql[i] not in "\r\n":
                i += 1
            continue
        elif char == "#":
            i += 1
            while i < len(sql) and sql[i] not in "\r\n":
                i += 1
            continue
        elif char == "/" and next_char == "*":
            i += 2
            while i + 1 < len(sql) and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 1
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)

        i += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def is_duplicate_column_error(exc: Exception) -> bool:
    message = str(exc)
    return "Duplicate column" in message or "1060" in message


if __name__ == "__main__":
    asyncio.run(main())
