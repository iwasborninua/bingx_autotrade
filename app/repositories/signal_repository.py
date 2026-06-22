from decimal import Decimal

from app import config


async def ensure_signal_context_columns(connection) -> None:
    async with connection.cursor() as cursor:
        try:
            await cursor.execute("ALTER TABLE signals ADD COLUMN btc_change_1h DECIMAL(20, 8) NULL")
        except Exception as exc:
            if "Duplicate column" not in str(exc) and "1060" not in str(exc):
                raise


def signal_status_and_reason(signal_score: Decimal | None) -> tuple[str, str | None]:
    """Return DB status and skip reason for a parsed signal score."""
    if signal_score is None:
        return "SKIPPED", "Signal score is missing"

    if signal_score < config.MIN_SIGNAL_SCORE:
        return "SKIPPED", f"Signal score {signal_score} is below minimum {config.MIN_SIGNAL_SCORE}"

    return "NEW", None


async def save_signal(
    connection,
    *,
    topic_id: int | None,
    message_id: int,
    message_date,
    raw_text: str,
    fields: dict[str, object],
) -> int | None:
    """Insert a parsed Telegram signal into MySQL, ignoring duplicates."""
    await ensure_signal_context_columns(connection)
    symbol = fields["symbol"]
    direction = fields["direction"]
    if not symbol or not direction:
        print(f"SKIP message_id={message_id}: cannot parse required symbol/direction")
        return None

    status, skip_reason = signal_status_and_reason(fields["signal_score"])
    external_id = f"{config.GROUP_ID}:{message_id}"

    async with connection.cursor() as cursor:
        affected = await cursor.execute(
            """
            INSERT IGNORE INTO signals (
                topic_id,
                external_id,
                symbol,
                direction,
                price,
                change_24h,
                rsi_14,
                market_sentiment,
                macd,
                open_interest_value,
                open_interest_raw,
                funding_rate,
                signal_score,
                sl_price,
                sl_percent,
                tp1_price,
                tp2_price,
                tp3_price,
                raw_text,
                status,
                skip_reason,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, CURRENT_TIMESTAMP
            )
            """,
            (
                topic_id,
                external_id,
                symbol,
                direction,
                fields["price"],
                fields["change_24h"],
                fields["rsi_14"],
                fields["market_sentiment"],
                fields["macd"],
                fields["open_interest_value"],
                fields["open_interest_raw"],
                fields["funding_rate"],
                fields["signal_score"],
                fields["sl_price"],
                fields["sl_percent"],
                fields["tp1_price"],
                fields["tp2_price"],
                fields["tp3_price"],
                raw_text,
                status,
                skip_reason,
                message_date.replace(tzinfo=None),
            ),
        )

    if affected == 1:
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT id FROM signals WHERE external_id=%s", (external_id,))
            row = await cursor.fetchone()
        print(f"SAVED message_id={message_id} symbol={symbol} status={status}")
        return int(row[0]) if row else None

    print(f"DUPLICATE message_id={message_id}")
    return None


async def update_signal_status(connection, *, signal_id: int, status: str, skip_reason: str | None = None) -> None:
    if skip_reason:
        skip_reason = skip_reason[:255]

    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE signals
            SET status=%s,
                skip_reason=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (status, skip_reason, signal_id),
        )


async def update_signal_market_context(
    connection,
    *,
    signal_id: int,
    btc_change_1h: Decimal | None,
) -> None:
    await ensure_signal_context_columns(connection)
    async with connection.cursor() as cursor:
        await cursor.execute(
            """
            UPDATE signals
            SET btc_change_1h=%s,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
            """,
            (btc_change_1h, signal_id),
        )
