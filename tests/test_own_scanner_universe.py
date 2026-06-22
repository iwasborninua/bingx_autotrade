import unittest
from unittest.mock import AsyncMock, patch

from app.own_strategy.scanner import load_universe


class OwnScannerUniverseTest(unittest.IsolatedAsyncioTestCase):
    async def test_load_universe_refreshes_from_api_instead_of_using_stale_db_limit(self) -> None:
        bingx = AsyncMock()
        bingx.contracts.return_value = [
            {"symbol": "AAA-USDT", "displayName": "AAA-USDT"},
            {"symbol": "BBB-USDT", "displayName": "BBB-USDT"},
            {"symbol": "CCC-USDT", "displayName": "CCC-USDT"},
        ]
        coinalyze = AsyncMock()
        coinalyze.get_markets.return_value = [
            {"symbol": "AAAUSDT_PERP.A"},
            {"symbol": "BBBUSDT_PERP.A"},
            {"symbol": "CCCUSDT_PERP.A"},
        ]

        with (
            patch("app.config.OWN_MAX_SYMBOLS", 0),
            patch("app.repositories.market_data_repository.upsert_symbol_mappings", new=AsyncMock()),
            patch("app.repositories.market_data_repository.active_symbol_mappings", new=AsyncMock(return_value=[{"normalized_symbol": "AAAUSDT"}])),
        ):
            mappings = await load_universe(object(), bingx, coinalyze)

        self.assertEqual([item["normalized_symbol"] for item in mappings], ["AAAUSDT", "BBBUSDT", "CCCUSDT"])


if __name__ == "__main__":
    unittest.main()
