from decimal import Decimal
from typing import Any

from app import config


async def ensure_market_data_tables(connection) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS market_candles (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                symbol VARCHAR(64) NOT NULL,
                exchange VARCHAR(32) NOT NULL,
                timeframe VARCHAR(16) NOT NULL,
                ts DATETIME NOT NULL,
                open DECIMAL(30, 12) NOT NULL,
                high DECIMAL(30, 12) NOT NULL,
                low DECIMAL(30, 12) NOT NULL,
                close DECIMAL(30, 12) NOT NULL,
                volume DECIMAL(30, 12) NULL,
                source VARCHAR(32) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_candle (symbol, exchange, timeframe, ts),
                INDEX idx_symbol_timeframe_ts (symbol, timeframe, ts)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        await cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS market_open_interest (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                symbol VARCHAR(64) NOT NULL,
                exchange VARCHAR(32) NOT NULL,
                timeframe VARCHAR(16) NOT NULL,
                ts DATETIME NOT NULL,
                open_interest DECIMAL(30, 12) NOT NULL,
                source VARCHAR(32) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_oi (symbol, exchange, timeframe, ts),
                INDEX idx_symbol_timeframe_ts (symbol, timeframe, ts)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        await cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS symbol_mappings (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                normalized_symbol VARCHAR(64) NOT NULL,
                bingx_symbol VARCHAR(64) NULL,
                coinalyze_symbol VARCHAR(128) NULL,
                base_asset VARCHAR(32) NULL,
                quote_asset VARCHAR(32) NULL,
                market_type VARCHAR(32) NULL,
                is_active BOOLEAN DEFAULT TRUE,
                is_crypto BOOLEAN DEFAULT TRUE,
                raw_bingx_json JSON NULL,
                raw_coinalyze_json JSON NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_normalized_symbol (normalized_symbol),
                INDEX idx_bingx_symbol (bingx_symbol),
                INDEX idx_coinalyze_symbol (coinalyze_symbol)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )


async def upsert_symbol_mappings(connection, mappings: list[dict[str, Any]]) -> None:
    if not mappings:
        return
    async with connection.cursor() as cursor:
        for item in mappings:
            await cursor.execute(
                """
                INSERT INTO symbol_mappings (
                    normalized_symbol, bingx_symbol, coinalyze_symbol, base_asset, quote_asset,
                    market_type, is_active, is_crypto, raw_bingx_json, raw_coinalyze_json
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    bingx_symbol=VALUES(bingx_symbol),
                    coinalyze_symbol=VALUES(coinalyze_symbol),
                    base_asset=VALUES(base_asset),
                    quote_asset=VALUES(quote_asset),
                    market_type=VALUES(market_type),
                    is_active=VALUES(is_active),
                    is_crypto=VALUES(is_crypto),
                    raw_bingx_json=VALUES(raw_bingx_json),
                    raw_coinalyze_json=VALUES(raw_coinalyze_json)
                """,
                (
                    item["normalized_symbol"],
                    item["bingx_symbol"],
                    item["coinalyze_symbol"],
                    item["base_asset"],
                    item["quote_asset"],
                    item["market_type"],
                    item["is_active"],
                    item["is_crypto"],
                    item["raw_bingx_json"],
                    item["raw_coinalyze_json"],
                ),
            )


async def active_symbol_mappings(connection, limit: int = 0) -> list[dict[str, Any]]:
    sql = """
        SELECT *
        FROM symbol_mappings
        WHERE is_active=TRUE AND is_crypto=TRUE AND bingx_symbol IS NOT NULL AND coinalyze_symbol IS NOT NULL
        ORDER BY normalized_symbol
    """
    params = ()
    if limit > 0:
        sql += " LIMIT %s"
        params = (limit,)
    async with connection.cursor() as cursor:
        await cursor.execute(sql, params)
        columns = [column[0] for column in cursor.description]
        rows = await cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


async def upsert_candles(connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with connection.cursor() as cursor:
        for row in rows:
            await cursor.execute(
                """
                INSERT INTO market_candles (symbol, exchange, timeframe, ts, open, high, low, close, volume, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    open=VALUES(open), high=VALUES(high), low=VALUES(low), close=VALUES(close),
                    volume=VALUES(volume), source=VALUES(source)
                """,
                (
                    row["symbol"],
                    row["exchange"],
                    row["timeframe"],
                    row["ts"],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row.get("volume"),
                    row["source"],
                ),
            )


async def upsert_open_interest(connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with connection.cursor() as cursor:
        for row in rows:
            await cursor.execute(
                """
                INSERT INTO market_open_interest (symbol, exchange, timeframe, ts, open_interest, source)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE open_interest=VALUES(open_interest), source=VALUES(source)
                """,
                (
                    row["symbol"],
                    row["exchange"],
                    row["timeframe"],
                    row["ts"],
                    row["open_interest"],
                    row["source"],
                ),
            )


async def own_data_quality_counts(connection) -> dict[str, int]:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT COUNT(*) FROM symbol_mappings WHERE bingx_symbol IS NOT NULL")
        total_bingx_symbols = int((await cursor.fetchone())[0] or 0)
        await cursor.execute("SELECT COUNT(*) FROM symbol_mappings WHERE coinalyze_symbol IS NOT NULL")
        total_coinalyze_markets = int((await cursor.fetchone())[0] or 0)
        await cursor.execute(
            """
            SELECT COUNT(*) FROM symbol_mappings
            WHERE bingx_symbol IS NOT NULL AND coinalyze_symbol IS NOT NULL AND is_active=TRUE AND is_crypto=TRUE
            """
        )
        matched_symbols = int((await cursor.fetchone())[0] or 0)
        await cursor.execute("SELECT COUNT(*) FROM symbol_mappings WHERE coinalyze_symbol IS NULL")
        missing_coinalyze_mapping = int((await cursor.fetchone())[0] or 0)
        await cursor.execute(
            """
            SELECT COUNT(DISTINCT symbol)
            FROM market_open_interest
            WHERE ts >= UTC_TIMESTAMP() - INTERVAL 30 MINUTE
            """
        )
        symbols_with_fresh_oi = int((await cursor.fetchone())[0] or 0)
        await cursor.execute(
            """
            SELECT COUNT(DISTINCT symbol)
            FROM market_open_interest
            WHERE ts < UTC_TIMESTAMP() - INTERVAL 30 MINUTE
            """
        )
        symbols_with_stale_oi = int((await cursor.fetchone())[0] or 0)
    return {
        "total_bingx_symbols": total_bingx_symbols,
        "total_coinalyze_markets": total_coinalyze_markets,
        "matched_symbols": matched_symbols,
        "missing_coinalyze_mapping": missing_coinalyze_mapping,
        "symbols_with_fresh_oi": symbols_with_fresh_oi,
        "symbols_with_stale_oi": symbols_with_stale_oi,
        "symbols_missing_oi": max(matched_symbols - symbols_with_fresh_oi - symbols_with_stale_oi, 0),
        "blacklisted_symbols": len(config.OWN_SYMBOL_BLACKLIST),
    }


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))
