from app import config
from app.bingx.client import BingXClient
from app.db import connect
from app.market_data.coinalyze_client import CoinalyzeClient
from app.market_data.symbol_mapping import build_symbol_mappings
from app.repositories import market_data_repository


async def run_own_data_quality() -> None:
    connection = await connect()
    bingx_client = BingXClient(
        base_url=config.BINGX_MARKET_BASE_URL,
        public_max_requests_per_minute=config.BINGX_MARKET_MAX_REQUESTS_PER_MINUTE,
    )
    coinalyze_client = CoinalyzeClient(
        api_key=config.COINALYZE_API_KEY,
        base_url=config.COINALYZE_BASE_URL,
        max_requests_per_minute=config.COINALYZE_MAX_REQUESTS_PER_MINUTE,
        reserve_requests=config.COINALYZE_REQUEST_RESERVE,
    )
    try:
        await market_data_repository.ensure_market_data_tables(connection)
        contracts = await bingx_client.contracts()
        markets = await coinalyze_client.get_markets()
        mappings = build_symbol_mappings(contracts, markets)
        await market_data_repository.upsert_symbol_mappings(connection, mappings)
        counts = await market_data_repository.own_data_quality_counts(connection)
        counts["total_bingx_symbols"] = len(contracts)
        counts["total_coinalyze_markets"] = len(markets)
        counts["matched_symbols"] = len(mappings)
        for key, value in counts.items():
            print(f"{key}: {value}")
    finally:
        connection.close()
        await bingx_client.close()
        await coinalyze_client.close()
