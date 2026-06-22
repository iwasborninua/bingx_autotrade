import json
from typing import Any

from app.own_strategy.rs_pullback_v1 import RSPullbackSignal


async def ensure_own_strategy_tables(connection) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS own_strategy_signals (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                strategy_name VARCHAR(128) NOT NULL,
                signal_source VARCHAR(32) NOT NULL DEFAULT 'own',
                symbol VARCHAR(64) NOT NULL,
                bingx_symbol VARCHAR(64) NULL,
                direction VARCHAR(16) NOT NULL,
                setup_type VARCHAR(128) NOT NULL,
                timeframe VARCHAR(16) NOT NULL,
                signal_ts DATETIME NOT NULL,
                signal_close DECIMAL(30, 12) NOT NULL,
                entry_model VARCHAR(64) NOT NULL,
                entry_price DECIMAL(30, 12) NOT NULL,
                stop_model VARCHAR(64) NOT NULL,
                stop_price DECIMAL(30, 12) NOT NULL,
                risk_price DECIMAL(30, 12) NOT NULL,
                risk_pct DECIMAL(18, 8) NOT NULL,
                tp1_price DECIMAL(30, 12) NOT NULL,
                tp2_price DECIMAL(30, 12) NOT NULL,
                tp3_price DECIMAL(30, 12) NOT NULL,
                atr_period INT NOT NULL,
                atr_value DECIMAL(30, 12) NOT NULL,
                relative_strength_1h DECIMAL(18, 8) NULL,
                price_change_1h DECIMAL(18, 8) NULL,
                volume_ratio_15m DECIMAL(18, 8) NULL,
                oi_change_15m DECIMAL(18, 8) NULL,
                btc_change_1h DECIMAL(18, 8) NULL,
                score DECIMAL(18, 8) NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'NEW',
                skip_reason VARCHAR(255) NULL,
                features_json JSON NULL,
                reason_json JSON NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_own_signal (strategy_name, symbol, timeframe, signal_ts)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )


async def save_own_signal(connection, signal: RSPullbackSignal, *, status: str = "NEW", skip_reason: str | None = None) -> int | None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            INSERT IGNORE INTO own_strategy_signals (
                strategy_name, signal_source, symbol, bingx_symbol, direction, setup_type, timeframe,
                signal_ts, signal_close, entry_model, entry_price, stop_model, stop_price, risk_price,
                risk_pct, tp1_price, tp2_price, tp3_price, atr_period, atr_value,
                relative_strength_1h, price_change_1h, volume_ratio_15m, oi_change_15m, btc_change_1h,
                status, skip_reason, features_json, reason_json
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                signal.strategy_name,
                signal.signal_source,
                signal.symbol,
                signal.bingx_symbol,
                signal.direction,
                signal.setup_type,
                signal.timeframe,
                signal.signal_ts,
                signal.signal_close,
                signal.entry_model,
                signal.entry_price,
                signal.stop_model,
                signal.stop_price,
                signal.risk_price,
                signal.risk_pct,
                signal.tp1_price,
                signal.tp2_price,
                signal.tp3_price,
                signal.atr_period,
                signal.atr_value,
                signal.relative_strength_1h,
                signal.price_change_1h,
                signal.volume_ratio_15m,
                signal.oi_change_15m,
                signal.btc_change_1h,
                status,
                skip_reason,
                json.dumps(signal.features_json, ensure_ascii=False),
                json.dumps(signal.reason_json, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid) if cursor.rowcount else None


async def update_own_signal_status(connection, *, signal_id: int, status: str, skip_reason: str | None = None) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE own_strategy_signals
            SET status=%s, skip_reason=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (status, skip_reason, signal_id),
        )


async def own_signal_exists(connection, *, strategy_name: str, symbol: str, timeframe: str, signal_ts: Any) -> bool:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            SELECT id FROM own_strategy_signals
            WHERE strategy_name=%s AND symbol=%s AND timeframe=%s AND signal_ts=%s
            LIMIT 1
            """,
            (strategy_name, symbol, timeframe, signal_ts),
        )
        return await cursor.fetchone() is not None
