import asyncio
import time
from typing import Any

import httpx


class CoinalyzeRateLimiter:
    def __init__(self, max_requests_per_minute: int, reserve_requests: int = 0) -> None:
        self.max_requests = max_requests_per_minute
        self.reserve_requests = max(reserve_requests, 0)
        self.effective_max_requests = max(1, max_requests_per_minute - self.reserve_requests)
        self.window_seconds = 60.0
        self.window_started_at = time.monotonic()
        self.request_count = 0
        self._lock = asyncio.Lock()

    async def wait(self, cost: int = 1) -> None:
        cost = max(cost, 1)
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.window_started_at
            if elapsed >= self.window_seconds:
                self.window_started_at = now
                self.request_count = 0
                elapsed = 0

            if self.request_count + cost > self.effective_max_requests:
                sleep_seconds = max(self.window_seconds - elapsed, 0)
                print(
                    f"CoinalyzeRateLimiter {self.request_count}/{self.effective_max_requests} "
                    f"cost={cost} reserve={self.reserve_requests} max={self.max_requests}, "
                    f"sleeping {sleep_seconds:.1f} sec"
                )
                await asyncio.sleep(sleep_seconds)
                self.window_started_at = time.monotonic()
                self.request_count = 0

            self.request_count += cost


class CoinalyzeClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.coinalyze.net/v1",
        max_requests_per_minute: int = 35,
        timeout: float = 15.0,
        max_retries: int = 3,
        reserve_requests: int = 0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.rate_limiter = CoinalyzeRateLimiter(max_requests_per_minute, reserve_requests)
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, headers=self._headers())

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "CoinalyzeClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def get_markets(self) -> list[dict[str, Any]]:
        data = await self._get("/future-markets")
        return data if isinstance(data, list) else []

    async def get_open_interest(
        self,
        coinalyze_symbol: str,
        interval: str,
        start_ts: int,
        end_ts: int,
    ) -> list[dict[str, Any]]:
        data = await self.get_open_interest_many([coinalyze_symbol], interval, start_ts, end_ts)
        return data.get(coinalyze_symbol, [])

    async def get_open_interest_many(
        self,
        coinalyze_symbols: list[str],
        interval: str,
        start_ts: int,
        end_ts: int,
    ) -> dict[str, list[dict[str, Any]]]:
        symbols = [symbol for symbol in coinalyze_symbols if symbol]
        if not symbols:
            return {}
        data = await self._get(
            "/open-interest-history",
            params={
                "symbols": ",".join(symbols),
                "interval": coinalyze_interval(interval),
                "from": start_ts,
                "to": end_ts,
            },
            rate_limit_cost=len(symbols),
        )
        if not isinstance(data, list):
            return {}
        result: dict[str, list[dict[str, Any]]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "")
            history = item.get("history")
            if symbol and isinstance(history, list):
                result[symbol] = history
        return result

    async def _get(self, path: str, params: dict[str, Any] | None = None, *, rate_limit_cost: int = 1) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self.rate_limiter.wait(rate_limit_cost)
            response = await self._http.get(path, params=params)
            if response.status_code == 429 and attempt < self.max_retries:
                retry_after = float(response.headers.get("Retry-After", "1"))
                print(f"Coinalyze 429 retry_after={retry_after}")
                await asyncio.sleep(retry_after)
                continue
            try:
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                response_text = response.text[:500] if hasattr(response, "text") else ""
                last_error = RuntimeError(f"{exc} response={response_text}")
                if attempt < self.max_retries:
                    await asyncio.sleep(1)
                    continue
                break
        raise RuntimeError(f"Coinalyze request failed path={path}: {last_error}")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["api_key"] = self.api_key
        return headers


def coinalyze_interval(interval: str) -> str:
    mapping = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1hour",
        "2h": "2hour",
        "4h": "4hour",
        "6h": "6hour",
        "12h": "12hour",
        "1d": "daily",
    }
    return mapping.get(interval.strip().lower(), interval)
