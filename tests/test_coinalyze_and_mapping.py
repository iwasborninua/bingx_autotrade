import unittest

from app.market_data.coinalyze_client import CoinalyzeClient, coinalyze_interval
from app.market_data.symbol_mapping import build_symbol_mappings


class FakeResponse:
    def __init__(self, status_code, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else []
        self.is_error = status_code >= 400

    def raise_for_status(self):
        if self.is_error:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, payload=None, throttle_first=True):
        self.calls = 0
        self.payload = payload if payload is not None else [{"symbol": "BTCUSDT_PERP.A"}]
        self.params = []
        self.throttle_first = throttle_first

    async def get(self, path, params=None):
        self.calls += 1
        self.params.append(params)
        if self.throttle_first and self.calls == 1:
            return FakeResponse(429, {"Retry-After": "0.001"})
        return FakeResponse(200, payload=self.payload)


class CoinalyzeClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_is_parsed_as_float(self) -> None:
        client = CoinalyzeClient(api_key="", max_requests_per_minute=1000)
        client._http = FakeHttp()

        data = await client.get_markets()

        self.assertEqual(data, [{"symbol": "BTCUSDT_PERP.A"}])
        self.assertEqual(client._http.calls, 2)

    async def test_bingx_timeframe_is_mapped_to_coinalyze_interval(self) -> None:
        self.assertEqual(coinalyze_interval("15m"), "15min")
        self.assertEqual(coinalyze_interval("1h"), "1hour")

    async def test_open_interest_many_sends_comma_symbol_list(self) -> None:
        client = CoinalyzeClient(api_key="", max_requests_per_minute=1000)
        client._http = FakeHttp(
            payload=[
                {"symbol": "ETHUSDT_PERP.3", "history": [{"t": 1, "o": 100}]},
                {"symbol": "BTCUSDT_PERP.A", "history": [{"t": 1, "o": 200}]},
            ],
            throttle_first=False,
        )

        data = await client.get_open_interest_many(
            ["ETHUSDT_PERP.3", "BTCUSDT_PERP.A"],
            "15m",
            1,
            2,
        )

        params = client._http.params[-1]
        self.assertEqual(params["symbols"], "ETHUSDT_PERP.3,BTCUSDT_PERP.A")
        self.assertEqual(params["interval"], "15min")
        self.assertEqual(data["ETHUSDT_PERP.3"], [{"t": 1, "o": 100}])
        self.assertEqual(client.rate_limiter.request_count, 2)

    async def test_rate_limiter_keeps_configured_reserve(self) -> None:
        client = CoinalyzeClient(api_key="", max_requests_per_minute=35, reserve_requests=7)

        self.assertEqual(client.rate_limiter.effective_max_requests, 28)


class SymbolMappingTest(unittest.TestCase):
    def test_mapping_matches_bingx_and_coinalyze_and_respects_blacklist(self) -> None:
        mappings = build_symbol_mappings(
            [
                {"symbol": "BTC-USDT", "displayName": "BTC-USDT"},
                {"symbol": "PAXG-USDT", "displayName": "PAXG-USDT"},
            ],
            [{"symbol": "BTCUSDT_PERP.A"}, {"symbol": "PAXGUSDT_PERP.A"}],
            blacklist={"PAXGUSDT"},
        )

        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0]["normalized_symbol"], "BTCUSDT")
        self.assertEqual(mappings[0]["coinalyze_symbol"], "BTCUSDT_PERP.A")


if __name__ == "__main__":
    unittest.main()
