import json
from datetime import date
from typing import Any


async def ensure_fear_greed_table(connection) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("SHOW TABLES LIKE 'fear_greed_index'")
        if await cursor.fetchone():
            return

        await cursor.execute(
            """
            CREATE TABLE fear_greed_index (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                index_date DATE NOT NULL,
                value TINYINT UNSIGNED NOT NULL,
                value_classification VARCHAR(32) NOT NULL,
                source VARCHAR(64) NOT NULL DEFAULT 'alternative.me',
                source_timestamp BIGINT UNSIGNED NULL,
                time_until_update_seconds INT UNSIGNED NULL,
                raw_response JSON NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uq_fear_greed_index_date_source (index_date, source),
                KEY idx_fear_greed_index_date (index_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )


async def has_index_for_date(connection, index_date: date, *, source: str = "alternative.me") -> bool:
    await ensure_fear_greed_table(connection)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            SELECT 1
            FROM fear_greed_index
            WHERE index_date=%s AND source=%s
            LIMIT 1
            """,
            (index_date, source),
        )
        return await cursor.fetchone() is not None


async def save_index(
    connection,
    *,
    index_date: date,
    value: int,
    value_classification: str,
    source_timestamp: int | None,
    time_until_update_seconds: int | None,
    raw_response: dict[str, Any],
    source: str = "alternative.me",
) -> None:
    await ensure_fear_greed_table(connection)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            INSERT INTO fear_greed_index (
                index_date,
                value,
                value_classification,
                source,
                source_timestamp,
                time_until_update_seconds,
                raw_response
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                value=%s,
                value_classification=%s,
                source_timestamp=%s,
                time_until_update_seconds=%s,
                raw_response=%s,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                index_date,
                value,
                value_classification,
                source,
                source_timestamp,
                time_until_update_seconds,
                json.dumps(raw_response, ensure_ascii=False),
                value,
                value_classification,
                source_timestamp,
                time_until_update_seconds,
                json.dumps(raw_response, ensure_ascii=False),
            ),
        )
