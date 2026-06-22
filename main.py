import argparse
import asyncio
import os


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BingX autotrade bot.")
    parser.add_argument("--source-mode", choices=("telegram", "own", "both"), help="Override SIGNAL_SOURCE_MODE.")
    parser.add_argument("--paper", action="store_true", help="Force PAPER_TRADING=true for this run.")
    parser.add_argument("--dry-run", action="store_true", help="Run one own-strategy scan and exit.")
    parser.add_argument("--mode", choices=("own-data-quality",), help="Run utility mode.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.source_mode:
        os.environ["SIGNAL_SOURCE_MODE"] = args.source_mode
    if args.paper:
        os.environ["PAPER_TRADING"] = "true"

    if args.mode == "own-data-quality":
        from app.own_strategy.data_quality import run_own_data_quality

        await run_own_data_quality()
        return

    from app import config
    from app.source_router import run_source_router
    from app.startup_checks import run_startup_checks

    await run_startup_checks(args.source_mode or config.SIGNAL_SOURCE_MODE)
    await run_source_router(source_mode=args.source_mode, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
