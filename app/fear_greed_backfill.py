import argparse
import asyncio
from datetime import UTC, date, datetime

import aiomysql

from app.db import connect
from app.fear_greed.client import FEAR_GREED_SOURCE, FearGreedClient
from app.repositories import fear_greed_repository


async def earliest_trade_date(connection) -> date | None:
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(
            """
            SELECT MIN(DATE(COALESCE(opened_at, created_at))) AS earliest_date
            FROM trades
            """
        )
        row = await cursor.fetchone()
    return row["earliest_date"] if row else None


async def backfill(start_date: date, end_date: date) -> int:
    connection = await connect()
    try:
        await fear_greed_repository.ensure_fear_greed_table(connection)
        async with FearGreedClient() as client:
            history = await client.all_history()

        saved = 0
        for index in history:
            index_date = index.index_date.date()
            if index_date < start_date or index_date > end_date:
                continue

            await fear_greed_repository.save_index(
                connection,
                index_date=index_date,
                value=index.value,
                value_classification=index.value_classification,
                source_timestamp=index.source_timestamp,
                time_until_update_seconds=index.time_until_update_seconds,
                raw_response=index.raw_response,
                source=FEAR_GREED_SOURCE,
            )
            saved += 1
        return saved
    finally:
        connection.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Fear & Greed Index from the first bot trade date.")
    parser.add_argument("--start-date", help="Override start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Override end date, YYYY-MM-DD. Defaults to today UTC.")
    args = parser.parse_args()

    connection = await connect()
    try:
        first_trade_date = await earliest_trade_date(connection)
    finally:
        connection.close()

    start_date = parse_date(args.start_date) if args.start_date else first_trade_date
    if start_date is None:
        print("No trades found; nothing to backfill.")
        return

    end_date = parse_date(args.end_date) if args.end_date else datetime.now(UTC).date()
    saved = await backfill(start_date, end_date)
    print(f"Fear & Greed backfill saved {saved} rows from {start_date.isoformat()} to {end_date.isoformat()}.")


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


if __name__ == "__main__":
    asyncio.run(main())
