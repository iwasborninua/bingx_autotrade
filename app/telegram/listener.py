import asyncio
import os
import sqlite3
import warnings
from pathlib import Path
from types import TracebackType

from telethon import TelegramClient, events

from app import config
from app.db import connect
from app.bingx.client import BingXClient, BingXCredentials
from app.parser.signal_parser import parse_signal
from app.repositories.signal_repository import save_signal, update_signal_status
from app.services.bingx_trader import handle_new_signal, monitor_open_trades
from app.services.fear_greed_service import sync_daily_fear_greed_index


warnings.filterwarnings(
    "ignore",
    message="Using async sessions support is an experimental feature",
    category=UserWarning,
    module="telethon.utils",
)


class SessionAlreadyInUseError(RuntimeError):
    """Raised when another process is using the configured Telethon session."""


class SingleInstanceLock:
    """Cross-platform advisory lock for the Telethon session file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self._remove_stale_lock():
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            else:
                raise self._in_use_error()

        os.write(self._fd, str(os.getpid()).encode("ascii"))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._fd is None:
            return

        try:
            os.close(self._fd)
        finally:
            self._fd = None
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def _remove_stale_lock(self) -> bool:
        try:
            pid = int(self.path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, OSError, ValueError):
            pid = 0

        try:
            if pid > 0:
                os.kill(pid, 0)
                return False
        except OSError:
            pass

        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def _in_use_error(self) -> SessionAlreadyInUseError:
        try:
            pid = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            pid = ""
        owner = f" by process {pid}" if pid else ""
        return SessionAlreadyInUseError(
            f"Telegram session is already in use{owner}. "
            "Stop the other bot process or set TELEGRAM_SESSION_NAME to a different value."
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

    session_path = config.BASE_DIR / config.TELEGRAM_SESSION_NAME
    client = None
    connection = None
    monitor_connection = None
    bingx_client = None
    monitor_task = None

    try:
        with SingleInstanceLock(session_path.with_suffix(".lock")):
            client = TelegramClient(
                str(session_path),
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
                        await sync_daily_fear_greed_index(connection)
                    except Exception as exc:
                        print(f"FEAR_GREED WARNING: {exc}")

                    if not config.TOPIC_TRADE_ENABLED.get(topic_id, False):
                        reason = f"Autotrade is disabled for topic {topic_id}"
                        await update_signal_status(
                            connection,
                            signal_id=signal_id,
                            status="SKIPPED",
                            skip_reason=reason,
                        )
                        print(f"TRADE SKIP signal_id={signal_id} topic={topic_id}: {reason}")
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

            await client.start(phone=config.TELEGRAM_PHONE)
            monitor_task = asyncio.create_task(monitor_open_trades(monitor_connection, bingx_client))
            print(
                f"Listening group={config.GROUP_ID}, topics={sorted(config.TOPIC_IDS)}, "
                f"trade_topics={[topic for topic, enabled in config.TOPIC_TRADE_ENABLED.items() if enabled]}, "
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
        if connection:
            connection.close()
        if monitor_connection:
            monitor_connection.close()
        if bingx_client:
            await bingx_client.close()
        if client:
            try:
                await client.disconnect()
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
