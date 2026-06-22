from app import config
from app.bingx.client import BingXClient, BingXCredentials
from app.market_data.coinalyze_client import CoinalyzeClient


async def run_startup_checks(source_mode: str) -> None:
    mode = source_mode.strip().lower()
    print("STARTUP CHECKS")
    bingx_ok = await check_bingx()
    coinalyze_ok = True
    if mode in {"own", "both"}:
        coinalyze_ok = await check_coinalyze()

    if not bingx_ok:
        raise RuntimeError("Startup check failed: BingX is unavailable")
    if mode in {"own", "both"} and not coinalyze_ok:
        raise RuntimeError("Startup check failed: Coinalyze is unavailable for own strategy")


async def check_bingx() -> bool:
    client = BingXClient(
        BingXCredentials(config.BINGX_API, config.BINGX_SECRET),
        base_url=config.BINGX_BASE_URL,
        demo=config.BINGX_DEMO,
        public_max_requests_per_minute=config.BINGX_MARKET_MAX_REQUESTS_PER_MINUTE,
    )
    try:
        server_time = await client.server_time()
        contracts = await client.contracts("BTCUSDT")
        balance = await client.account_balance("USDT")
        print(
            "BingX: OK "
            f"mode={config.BINGX_MODE} base_url={config.BINGX_BASE_URL} "
            f"server_time={server_time} btc_contracts={len(contracts)} "
            f"private_access={'yes' if balance is not None else 'unknown'}"
        )
        return True
    except Exception as exc:
        print(f"BingX: FAIL {exc}")
        return False
    finally:
        await client.close()


async def check_coinalyze() -> bool:
    if not config.COINALYZE_API_KEY:
        print("Coinalyze: FAIL missing COINALYZE_API or COINALYZE_API_KEY")
        return False

    client = CoinalyzeClient(
        api_key=config.COINALYZE_API_KEY,
        base_url=config.COINALYZE_BASE_URL,
        max_requests_per_minute=config.COINALYZE_MAX_REQUESTS_PER_MINUTE,
        reserve_requests=config.COINALYZE_REQUEST_RESERVE,
    )
    try:
        markets = await client.get_markets()
        print(f"Coinalyze: OK base_url={config.COINALYZE_BASE_URL} markets={len(markets)}")
        return True
    except Exception as exc:
        print(f"Coinalyze: FAIL {exc}")
        return False
    finally:
        await client.close()
