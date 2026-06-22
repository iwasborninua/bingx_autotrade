from datetime import datetime, timezone

from app.services.market_context_service import next_minute


def test_next_minute_after_signal_with_seconds():
    assert next_minute(datetime(2026, 6, 17, 12, 34, 20, tzinfo=timezone.utc)) == datetime(
        2026, 6, 17, 12, 35, tzinfo=timezone.utc
    )


def test_next_minute_keeps_exact_minute():
    assert next_minute(datetime(2026, 6, 17, 12, 34, 0, tzinfo=timezone.utc)) == datetime(
        2026, 6, 17, 12, 34, tzinfo=timezone.utc
    )
