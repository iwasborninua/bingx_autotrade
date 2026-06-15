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
from app.repositories.signal_repository import save_signal
from app.services.bingx_trader import handle_new_signal, monitor_open_trades


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
        self._file = None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                self._lock_windows()
            else:
                self._lock_posix()
        except Exception:
            self._file.close()
            self._file = None
            raise

        self._file.seek(0)
        self._file.truncate()
        self._file.write(str(os.getpid()))
        self._file.flush()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._file:
            return

        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def _lock_windows(self) -> None:
        import msvcrt

        assert self._file is not None
        self._file.seek(0)
        try:
            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise self._in_use_error() from exc

    def _lock_posix(self) -> None:
        import fcntl

        assert self._file is not None
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise self._in_use_error() from exc

    def _in_use_error(self) -> SessionAlreadyInUseError:
        assert self._file is not None
        self._file.seek(0)
        pid = self._file.read().strip()
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
