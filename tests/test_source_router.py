import unittest

from app.source_router import run_source_router


class SourceRouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_telegram_mode_starts_only_telegram(self) -> None:
        calls = []

        async def telegram():
            calls.append("telegram")

        async def own():
            calls.append("own")

        async def monitor():
            calls.append("monitor")

        await run_source_router(
            source_mode="telegram",
            telegram_starter=telegram,
            own_starter=own,
            monitor_starter=monitor,
        )
        self.assertEqual(calls, ["telegram"])

    async def test_own_dry_run_starts_only_own(self) -> None:
        calls = []

        async def telegram():
            calls.append("telegram")

        async def own():
            calls.append("own")

        async def monitor():
            calls.append("monitor")

        await run_source_router(
            source_mode="own",
            dry_run=True,
            telegram_starter=telegram,
            own_starter=own,
            monitor_starter=monitor,
        )
        self.assertEqual(calls, ["own"])

    async def test_own_mode_starts_own_and_monitor(self) -> None:
        calls = []

        async def telegram():
            calls.append("telegram")

        async def own():
            calls.append("own")

        async def monitor():
            calls.append("monitor")

        await run_source_router(
            source_mode="own",
            telegram_starter=telegram,
            own_starter=own,
            monitor_starter=monitor,
        )
        self.assertEqual(set(calls), {"own", "monitor"})

    async def test_both_mode_starts_both(self) -> None:
        calls = []

        async def telegram():
            calls.append("telegram")

        async def own():
            calls.append("own")

        async def monitor():
            calls.append("monitor")

        await run_source_router(
            source_mode="both",
            telegram_starter=telegram,
            own_starter=own,
            monitor_starter=monitor,
        )
        self.assertEqual(set(calls), {"telegram", "own"})


if __name__ == "__main__":
    unittest.main()
