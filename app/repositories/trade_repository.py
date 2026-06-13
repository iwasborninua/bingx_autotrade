import json
from decimal import Decimal, ROUND_DOWN
from typing import Any


OPEN_TRADE_STATUSES = ("OPENING", "OPEN")
OPEN_TRADE_STATUS_SQL = "('OPENING', 'OPEN')"
VALID_OPEN_TRADE_SQL = (
    f"status IN {OPEN_TRADE_STATUS_SQL} "
    "AND contract_symbol IS NOT NULL "
    "AND direction IN ('BUY', 'SELL') "
    "AND entry_price IS NOT NULL "
    "AND current_sl_price IS NOT NULL "
    "AND tp1_price IS NOT NULL "
    "AND tp2_price IS NOT NULL "
    "AND tp3_price IS NOT NULL "
    "AND margin IS NOT NULL "
    "AND volume IS NOT NULL"
)
VALID_ACTIVE_TRADE_SQL = VALID_OPEN_TRADE_SQL.replace(f"status IN {OPEN_TRADE_STATUS_SQL}", "status = 'OPEN'")


TRADE_COLUMNS = {
    "signal_id": "BIGINT NULL",
    "external_id": "VARCHAR(64) NULL",
    "bingx_order_id": "VARCHAR(64) NULL",
    "bingx_position_id": "VARCHAR(64) NULL",
    "stop_plan_order_id": "VARCHAR(64) NULL",
    "symbol": "VARCHAR(32) NULL",
    "contract_symbol": "VARCHAR(32) NULL",
    "direction": "VARCHAR(8) NULL",
    "status": "VARCHAR(32) NULL",
    "close_reason": "VARCHAR(255) NULL",
    "entry_price": "DECIMAL(30, 12) NULL",
    "avg_entry_price": "DECIMAL(30, 12) NULL",
    "margin_usdt": "DECIMAL(30, 12) NULL",
    "original_sl_price": "DECIMAL(30, 12) NULL",
    "initial_sl_price": "DECIMAL(30, 12) NULL",
    "current_sl_price": "DECIMAL(30, 12) NULL",
    "tp1_price": "DECIMAL(30, 12) NULL",
    "tp2_price": "DECIMAL(30, 12) NULL",
    "tp3_price": "DECIMAL(30, 12) NULL",
    "margin": "DECIMAL(30, 12) NULL",
    "leverage": "INT NULL",
    "volume": "DECIMAL(30, 12) NULL",
    "contract_size": "DECIMAL(30, 12) NULL",
    "fee_rate": "DECIMAL(20, 12) NOT NULL DEFAULT 0",
    "last_price": "DECIMAL(30, 12) NULL",
    "last_roi": "DECIMAL(20, 8) NULL",
    "last_pnl": "DECIMAL(30, 12) NULL",
    "close_price": "DECIMAL(30, 12) NULL",
    "realized_roi": "DECIMAL(20, 8) NULL",
    "realized_pnl": "DECIMAL(30, 12) NULL",
    "break_even_price": "DECIMAL(30, 12) NULL",
    "error_message": "TEXT NULL",
    "break_even_moved_at": "DATETIME NULL",
    "tp1_reached_at": "DATETIME NULL",
    "tp2_reached_at": "DATETIME NULL",
    "opened_at": "DATETIME NULL",
    "closed_at": "DATETIME NULL",
    "raw_open_response": "JSON NULL",
    "raw_close_response": "JSON NULL",
    "created_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "updated_at": "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
}


TRADE_COLUMN_TYPES = {
    "external_id": "VARCHAR(64) NOT NULL",
    "symbol": "VARCHAR(32) NOT NULL",
    "contract_symbol": "VARCHAR(32) NOT NULL",
    "direction": "VARCHAR(8) NOT NULL",
    "status": "VARCHAR(32) NOT NULL",
    "close_reason": "VARCHAR(255) NULL",
    "entry_price": "DECIMAL(30, 12) NOT NULL",
    "avg_entry_price": "DECIMAL(30, 12) NULL",
    "margin_usdt": "DECIMAL(30, 12) NULL",
    "original_sl_price": "DECIMAL(30, 12) NOT NULL",
    "initial_sl_price": "DECIMAL(30, 12) NULL",
    "current_sl_price": "DECIMAL(30, 12) NOT NULL",
    "tp1_price": "DECIMAL(30, 12) NOT NULL",
    "tp2_price": "DECIMAL(30, 12) NOT NULL",
    "tp3_price": "DECIMAL(30, 12) NOT NULL",
    "margin": "DECIMAL(30, 12) NOT NULL",
    "leverage": "INT NOT NULL",
    "volume": "DECIMAL(30, 12) NOT NULL",
    "contract_size": "DECIMAL(30, 12) NULL",
    "fee_rate": "DECIMAL(20, 12) NOT NULL DEFAULT 0",
    "last_price": "DECIMAL(30, 12) NULL",
    "last_roi": "DECIMAL(20, 8) NULL",
    "last_pnl": "DECIMAL(30, 12) NULL",
    "close_price": "DECIMAL(30, 12) NULL",
    "realized_roi": "DECIMAL(20, 8) NULL",
    "realized_pnl": "DECIMAL(30, 12) NULL",
    "break_even_price": "DECIMAL(30, 12) NULL",
    "error_message": "TEXT NULL",
    "raw_open_response": "JSON NULL",
    "raw_close_response": "JSON NULL",
}


async def ensure_trades_table(connection) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute("SHOW TABLES LIKE 'trades'")
        table_exists = await cursor.fetchone()
        if not table_exists:
            await cursor.execute(
                """
                CREATE TABLE trades (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    signal_id BIGINT NULL,
                    external_id VARCHAR(64) NOT NULL,
                    bingx_order_id VARCHAR(64) NULL,
                    bingx_position_id VARCHAR(64) NULL,
                    stop_plan_order_id VARCHAR(64) NULL,
                    symbol VARCHAR(32) NOT NULL,
                    contract_symbol VARCHAR(32) NOT NULL,
                    direction VARCHAR(8) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    close_reason VARCHAR(255) NULL,
                    entry_price DECIMAL(30, 12) NOT NULL,
                    original_sl_price DECIMAL(30, 12) NOT NULL,
                    current_sl_price DECIMAL(30, 12) NOT NULL,
                    tp1_price DECIMAL(30, 12) NOT NULL,
                    tp2_price DECIMAL(30, 12) NOT NULL,
                    tp3_price DECIMAL(30, 12) NOT NULL,
                    margin DECIMAL(30, 12) NOT NULL,
                    leverage INT NOT NULL,
                    volume DECIMAL(30, 12) NOT NULL,
                    contract_size DECIMAL(30, 12) NULL,
                    fee_rate DECIMAL(20, 12) NOT NULL DEFAULT 0,
                    last_price DECIMAL(30, 12) NULL,
                    last_roi DECIMAL(20, 8) NULL,
                    last_pnl DECIMAL(30, 12) NULL,
                    close_price DECIMAL(30, 12) NULL,
                    realized_roi DECIMAL(20, 8) NULL,
                    realized_pnl DECIMAL(30, 12) NULL,
                    break_even_moved_at DATETIME NULL,
                    tp1_reached_at DATETIME NULL,
                    tp2_reached_at DATETIME NULL,
                    opened_at DATETIME NULL,
                    closed_at DATETIME NULL,
                    raw_open_response JSON NULL,
                    raw_close_response JSON NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_trades_external_id (external_id),
                    KEY idx_trades_status (status),
                    KEY idx_trades_signal_id (signal_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )

        for column, definition in TRADE_COLUMNS.items():
            try:
                await cursor.execute(f"ALTER TABLE trades ADD COLUMN {column} {definition}")
            except Exception as exc:
                if "Duplicate column" not in str(exc) and "1060" not in str(exc):
                    raise

        for column, definition in TRADE_COLUMN_TYPES.items():
            await cursor.execute(f"ALTER TABLE trades MODIFY COLUMN {column} {definition}")


async def count_open_trades(connection) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute(
            f"SELECT COUNT(*) FROM trades WHERE {VALID_OPEN_TRADE_SQL}",
        )
        row = await cursor.fetchone()
    return int(row[0] or 0)


async def active_trade_for_symbol(connection, contract_symbol: str) -> dict[str, Any] | None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            f"""
            SELECT *
            FROM trades
            WHERE {VALID_OPEN_TRADE_SQL}
              AND contract_symbol=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            (contract_symbol,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [column[0] for column in cursor.description]
    return dict(zip(columns, row))


async def insert_open_trade(connection, trade: dict[str, Any]) -> int:
    columns = list(trade)
    placeholders = ", ".join(["%s"] * len(columns))
    values = [to_db_value(trade[column]) for column in columns]

    async with connection.cursor() as cursor:
        await cursor.execute(
            f"""
            INSERT INTO trades ({", ".join(columns)})
            VALUES ({placeholders})
            """,
            values,
        )
        return int(cursor.lastrowid)


async def active_trades(connection) -> list[dict[str, Any]]:
    async with connection.cursor() as cursor:
        await cursor.execute(f"SELECT * FROM trades WHERE {VALID_ACTIVE_TRADE_SQL}")
        columns = [column[0] for column in cursor.description]
        rows = await cursor.fetchall()
    return [dict(zip(columns, row)) for row in rows]


async def mark_trade_open(
    connection,
    *,
    trade_id: int,
    bingx_order_id: str | None,
    bingx_position_id: str | None,
    stop_plan_order_id: str | None,
    raw_open_response: Any,
) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE trades
            SET status='OPEN',
                bingx_order_id=%s,
                bingx_position_id=%s,
                stop_plan_order_id=%s,
                raw_open_response=%s,
                opened_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (
                bingx_order_id,
                bingx_position_id,
                stop_plan_order_id,
                to_json(raw_open_response),
                trade_id,
            ),
        )


async def mark_trade_open_failed(connection, *, trade_id: int, reason: str, raw_response: Any = None) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE trades
            SET status='OPEN_FAILED',
                close_reason=%s,
                raw_open_response=%s,
                closed_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (reason[:255], to_json(raw_response), trade_id),
        )


async def update_trade_stop(
    connection,
    *,
    trade_id: int,
    stop_price: Decimal,
    reached_column: str,
    roi: Decimal | None,
    pnl: Decimal | None = None,
    price: Decimal | None = None,
) -> None:
    if reached_column not in {"break_even_moved_at", "tp1_reached_at", "tp2_reached_at"}:
        raise ValueError(f"Unsupported reached column: {reached_column}")

    async with connection.cursor() as cursor:
        await cursor.execute(
            f"""
            UPDATE trades
            SET current_sl_price=%s,
                last_price=%s,
                last_roi=%s,
                last_pnl=%s,
                {reached_column}=COALESCE({reached_column}, CURRENT_TIMESTAMP),
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (stop_price, price, roi, pnl, trade_id),
        )


async def update_trade_market(
    connection,
    *,
    trade_id: int,
    price: Decimal | None,
    roi: Decimal | None,
    pnl: Decimal | None,
) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE trades
            SET last_price=%s,
                last_roi=%s,
                last_pnl=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (price, roi, pnl, trade_id),
        )


async def close_trade(
    connection,
    *,
    trade_id: int,
    reason: str,
    raw_close_response: Any = None,
    close_price: Decimal | None = None,
    realized_roi: Decimal | None = None,
    realized_pnl: Decimal | None = None,
) -> None:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE trades
            SET status='CLOSED',
                close_reason=%s,
                close_price=%s,
                realized_roi=%s,
                realized_pnl=%s,
                last_price=COALESCE(%s, last_price),
                last_roi=COALESCE(%s, last_roi),
                last_pnl=COALESCE(%s, last_pnl),
                raw_close_response=%s,
                closed_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (
                reason[:255],
                close_price,
                realized_roi,
                realized_pnl,
                close_price,
                realized_roi,
                realized_pnl,
                to_json(raw_close_response),
                trade_id,
            ),
        )


async def trade_stats(connection) -> dict[str, Any]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            SELECT
                COUNT(*) AS total_trades,
                SUM(status IN ('OPENING', 'OPEN')) AS active_trades,
                SUM(status = 'CLOSED') AS closed_trades,
                SUM(status = 'CLOSED' AND close_reason LIKE 'TP%%') AS tp_trades,
                SUM(status = 'CLOSED' AND close_reason LIKE '%%STOP%%' AND close_reason NOT LIKE 'TP%%') AS sl_trades,
                COALESCE(SUM(CASE WHEN status IN ('OPENING', 'OPEN') THEN last_pnl ELSE 0 END), 0) AS active_pnl,
                COALESCE(SUM(CASE WHEN status IN ('OPENING', 'OPEN') THEN margin ELSE 0 END), 0) AS active_margin,
                COALESCE(SUM(CASE WHEN status = 'CLOSED' THEN realized_pnl ELSE 0 END), 0) AS closed_pnl,
                COALESCE(SUM(CASE WHEN status = 'CLOSED' THEN margin ELSE 0 END), 0) AS closed_margin,
                COALESCE(SUM(CASE WHEN status IN ('OPENING', 'OPEN') THEN last_pnl ELSE realized_pnl END), 0) AS total_pnl,
                COALESCE(SUM(margin), 0) AS total_margin
            FROM trades
            """
        )
        columns = [column[0] for column in cursor.description]
        row = await cursor.fetchone()
    return dict(zip(columns, row)) if row else {}


def to_db_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return to_json(value)
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.000000000001"), rounding=ROUND_DOWN)
    return value


def to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)
