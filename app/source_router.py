import asyncio
from collections.abc import Awaitable, Callable

from app import config
from app.own_strategy.scanner import run_own_strategy_scanner
from app.position_monitor import run_position_monitor
from app.telegram.listener import run_listener


Starter = Callable[[], Awaitable[None]]


async def run_source_router(
    *,
    source_mode: str | None = None,
    dry_run: bool = False,
    telegram_starter: Starter | None = None,
    own_starter: Starter | None = None,
    monitor_starter: Starter | None = None,
) -> None:
    mode = (source_mode or config.SIGNAL_SOURCE_MODE).strip().lower()
    if mode not in {"telegram", "own", "both"}:
        raise ValueError("Invalid SIGNAL_SOURCE_MODE")

    telegram = telegram_starter or run_listener
    own = own_starter or (lambda: run_own_strategy_scanner(dry_run=dry_run))
    monitor = monitor_starter or run_position_monitor

    if mode == "telegram":
        await telegram()
    elif mode == "own":
        if dry_run:
            await own()
        else:
            await asyncio.gather(own(), monitor())
    else:
        await asyncio.gather(telegram(), own())
