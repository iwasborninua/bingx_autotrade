import asyncio
import warnings

from telethon import TelegramClient, events

from app import config
from app.db import connect
from app.bingx.client import BingXClient, BingXCredentials
from app.parser.signal_parser import parse_signal
from app.repositories.signal_repository import save_signal
from app.services.bingx_trader import handle_new_signal, monitor_open_trades


warnings.filterwarnings(
    "ignore",
    message="Using async sessions support is an experimental feature",
    category=UserWarning,
    module="telethon.utils",
)


def message_topic_id(message) -> int | None:
    """Extract Telegram forum topic id from a Telethon message."""
    reply_to = getattr(message, "reply_to", None)
    if not reply_to:
        return None
    return getattr(reply_to, "reply_to_top_id", None) or getattr(reply_to, "reply_to_msg_id", None)


async def run_listener() -> None:
    """Listen to configured Telegram topics and persist incoming trading signals."""
    if not config.TOPIC_IDS:
        raise RuntimeError("Missing TOPIC_BOT_1/TOPIC_BOT_2 env variables")

    client = TelegramClient(
        str(config.BASE_DIR / config.TELEGRAM_SESSION_NAME),
        config.TELEGRAM_API_ID,
        config.TELEGRAM_API_HASH,
    )
    connection = await connect()
    monitor_connection = await connect()
    bingx_client = BingXClient(
        BingXCredentials(config.BINGX_API, config.BINGX_SECRET),
        base_url=config.BINGX_BASE_URL,
        demo=config.BINGX_DEMO,
    )
    monitor_task = None
    db_lock = asyncio.Lock()

    @client.on(events.NewMessage(chats=config.GROUP_ID))
    async def handler(event: events.NewMessage.Event) -> None:
        message = event.message
        raw_text = message.message or ""
        if not raw_text:
            return

        topic_id = message_topic_id(message)
        if topic_id not in config.TOPIC_IDS:
            return

        async with db_lock:
            fields = parse_signal(raw_text)
            signal_id = await save_signal(
                connection,
                topic_id=topic_id,
                message_id=message.id,
                message_date=message.date,
                raw_text=raw_text,
                fields=fields,
            )
            if signal_id is None:
                return

            try:
                await handle_new_signal(
                    connection,
                    bingx_client,
                    signal_id=signal_id,
                    external_id=f"{config.GROUP_ID}:{message.id}",
                    fields=fields,
                )
            except Exception as exc:
                print(f"TRADE HANDLER ERROR signal_id={signal_id}: {exc}")

    try:
        await client.start(phone=config.TELEGRAM_PHONE)
        monitor_task = asyncio.create_task(monitor_open_trades(monitor_connection, bingx_client))
        print(
            f"Listening group={config.GROUP_ID}, topics={sorted(config.TOPIC_IDS)}, "
            f"min_signal_score={config.MIN_SIGNAL_SCORE}, "
            f"bingx_mode={config.BINGX_MODE}, bingx_base_url={config.BINGX_BASE_URL}"
        )
        await client.run_until_disconnected()
    finally:
        if monitor_task:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        connection.close()
        monitor_connection.close()
        await bingx_client.close()
        await client.disconnect()
