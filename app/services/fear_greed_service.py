from datetime import UTC, datetime

from app.fear_greed.client import FEAR_GREED_SOURCE, FearGreedClient
from app.repositories import fear_greed_repository


async def sync_daily_fear_greed_index(connection) -> None:
    """Save latest Fear & Greed Index once per UTC day."""
    today = datetime.now(UTC).date()
    if await fear_greed_repository.has_index_for_date(connection, today, source=FEAR_GREED_SOURCE):
        return

    async with FearGreedClient() as client:
        index = await client.latest()

    index_date = index.index_date.date()
    if await fear_greed_repository.has_index_for_date(connection, index_date, source=FEAR_GREED_SOURCE):
        return

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
    print(
        "FEAR_GREED SAVED "
        f"date={index_date.isoformat()} value={index.value} classification={index.value_classification}"
    )
