from app import config
from app.bingx.client import BingXClient, BingXCredentials
from app.db import connect
from app.services.bingx_trader import monitor_open_trades


async def run_position_monitor() -> None:
    connection = await connect()
    client = BingXClient(
        BingXCredentials(config.BINGX_API, config.BINGX_SECRET),
        base_url=config.BINGX_BASE_URL,
        demo=config.BINGX_DEMO,
    )
    try:
        await monitor_open_trades(connection, client)
    finally:
        connection.close()
        await client.close()
