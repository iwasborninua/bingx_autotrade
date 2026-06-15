from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


FEAR_GREED_API_URL = "https://api.alternative.me/fng/"
FEAR_GREED_SOURCE = "alternative.me"


@dataclass(frozen=True)
class FearGreedIndex:
    index_date: datetime
    value: int
    value_classification: str
    source_timestamp: int | None
    time_until_update_seconds: int | None
    raw_response: dict[str, Any]


class FearGreedClient:
    def __init__(self, *, timeout: float = 10.0) -> None:
        self._http = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "FearGreedClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def latest(self) -> FearGreedIndex:
        rows, payload = await self._fetch(limit=1)
        row = rows[0]
        return parse_index_row(row, payload)

    async def all_history(self) -> list[FearGreedIndex]:
        rows, payload = await self._fetch(limit=0)
        return [parse_index_row(row, payload) for row in rows]

    async def _fetch(self, *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        response = await self._http.get(FEAR_GREED_API_URL, params={"limit": limit, "format": "json"})
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError("Fear & Greed API returned no data")
        return rows, payload


def parse_index_row(row: dict[str, Any], raw_response: dict[str, Any]) -> FearGreedIndex:
    timestamp = int(row["timestamp"]) if row.get("timestamp") else None
    index_datetime = datetime.fromtimestamp(timestamp, tz=UTC) if timestamp else datetime.now(UTC)
    return FearGreedIndex(
        index_date=index_datetime,
        value=int(row["value"]),
        value_classification=str(row["value_classification"]),
        source_timestamp=timestamp,
        time_until_update_seconds=to_optional_int(row.get("time_until_update")),
        raw_response=raw_response,
    )


def to_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
