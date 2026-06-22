import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"


load_dotenv(ENV_PATH, override=True)


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env variable: {name}")
    return value


def optional_decimal(name: str, default: str) -> Decimal:
    value = os.getenv(name, default)
    return Decimal(value)


def optional_int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


def optional_bool(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value in {"1", "true", "yes", "on", "demo"}


def optional_csv_set(name: str, default: str = "") -> set[str]:
    value = os.getenv(name, default)
    return {item.strip().upper() for item in value.split(",") if item.strip()}


def optional_csv_list(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


TELEGRAM_API_ID = int(require_env("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = require_env("TELEGRAM_API_HASH")
TELEGRAM_PHONE = require_env("TELEGRAM_PHONE")
TELEGRAM_SESSION_NAME = require_env("TELEGRAM_SESSION_NAME")
GROUP_ID = int(require_env("GROUP_ID"))
TOPIC_BOT_1 = int(require_env("TOPIC_BOT_1"))
TOPIC_BOT_2 = int(require_env("TOPIC_BOT_2"))
TOPIC_IDS = {TOPIC_BOT_1, TOPIC_BOT_2}
TOPIC_BOT_1_TRADE = optional_bool("TOPIC_BOT_1_TRADE", "true")
TOPIC_BOT_2_TRADE = optional_bool("TOPIC_BOT_2_TRADE", "true")
TOPIC_TRADE_ENABLED = {
    TOPIC_BOT_1: TOPIC_BOT_1_TRADE,
    TOPIC_BOT_2: TOPIC_BOT_2_TRADE,
}

MIN_SIGNAL_SCORE = optional_decimal("MIN_SIGNAL_SCORE", "0")
BINGX_MODE = os.getenv("BINGX_MODE", "live").strip().lower()
BINGX_DEMO = BINGX_MODE in {"demo", "testnet", "paper", "sandbox"}
BINGX_BASE_URL = os.getenv("BINGX_BASE_URL", "").strip() or (
    "https://open-api-vst.bingx.com" if BINGX_DEMO else "https://open-api.bingx.com"
)
BINGX_API = require_env("BINGX_API")
BINGX_SECRET = require_env("BINGX_SECRET")
BINGX_EXCLUDED_CONTRACT_PREFIXES = optional_csv_set("BINGX_EXCLUDED_CONTRACT_PREFIXES", "NCSK,NCFX,NCCO")
BINGX_EXCLUDED_DISPLAY_ASSETS = optional_csv_set(
    "BINGX_EXCLUDED_DISPLAY_ASSETS",
    "TSLA,MSFT,GOOGL,AMZN,AAPL,NVDA,META,EURUSD,EURJPY,USDJPY,EURCAD,GBPJPY,GBPUSD,AUDUSD,"
    "EURGBP,EURCHF,AUDJPY,GBPCHF,GBPSGD,EURSGD,CADJPY,NZDJPY,GOLD,SILVER,XAU,XAG,XAUAUD,XAUEUR,XAUJPY",
)
BINGX_LIMIT_OPENED_POSITIONS = optional_int("BINGX_LIMIT_OPENED_POSITIONS", "1")
BINGX_MAX_PROTECTIVE_ORDERS = optional_int("BINGX_MAX_PROTECTIVE_ORDERS", "160")
BINGX_MARGIN = optional_decimal("BINGX_MARGIN", "0")
BINGX_LEVERAGE = optional_int("BINGX_LEVERAGE", "1")
BINGX_MARGIN_TYPE = os.getenv("BINGX_MARGIN_TYPE", "ISOLATED").strip().upper()
if BINGX_MARGIN_TYPE == "CROSS":
    BINGX_MARGIN_TYPE = "CROSSED"
BINGX_POSITION_CHECK_INTERVAL_SECONDS = optional_int("BINGX_POSITION_CHECK_INTERVAL_SECONDS", "180")
BINGX_LOG_STATS_EACH_CHECK = optional_bool("BINGX_LOG_STATS_EACH_CHECK", "true")

ENABLE_SIGNAL_FILTERS = optional_bool("ENABLE_SIGNAL_FILTERS", "true")
ALLOWED_SIGNAL_SIDE = os.getenv("ALLOWED_SIGNAL_SIDE", "LONG").strip().upper()
ENABLE_RR_TP3_FILTER = optional_bool("ENABLE_RR_TP3_FILTER", "true")
RR_TP3_MIN = optional_decimal("RR_TP3_MIN", "0.8")
RR_TP3_MAX = optional_decimal("RR_TP3_MAX", "1.5")
ENABLE_SESSION_FILTER = optional_bool("ENABLE_SESSION_FILTER", "true")
ALLOWED_SESSIONS = optional_csv_list("ALLOWED_SESSIONS", "Asia")
ENABLE_BTC_CHANGE_1H_FILTER = optional_bool("ENABLE_BTC_CHANGE_1H_FILTER", "true")
BTC_CHANGE_1H_MIN = optional_decimal("BTC_CHANGE_1H_MIN", "-1")
BTC_CHANGE_1H_MAX = optional_decimal("BTC_CHANGE_1H_MAX", "0")
SESSION_BTC_FILTER_MODE = os.getenv("SESSION_BTC_FILTER_MODE", "OR").strip().upper()
RR_FILTER_IS_REQUIRED = optional_bool("RR_FILTER_IS_REQUIRED", "true")

TP1_CLOSE_PERCENT = optional_decimal("TP1_CLOSE_PERCENT", "0")
TP2_CLOSE_PERCENT = optional_decimal("TP2_CLOSE_PERCENT", "0")
TP3_CLOSE_PERCENT = optional_decimal("TP3_CLOSE_PERCENT", "100")
STOP_MOVE_MODE = os.getenv("STOP_MOVE_MODE", "move_sl_to_be_after_tp1").strip()
MOVE_SL_TO_BE_ON_TP1_TOUCH = optional_bool("MOVE_SL_TO_BE_ON_TP1_TOUCH", "true")


def validate_strategy_config() -> None:
    if ALLOWED_SIGNAL_SIDE not in {"LONG", "SHORT", "BOTH"}:
        raise RuntimeError("ALLOWED_SIGNAL_SIDE must be LONG, SHORT, or BOTH")
    if SESSION_BTC_FILTER_MODE not in {"OR", "AND"}:
        raise RuntimeError("SESSION_BTC_FILTER_MODE must be OR or AND")
    if STOP_MOVE_MODE not in {
        "none",
        "move_sl_to_be_after_tp1",
        "move_sl_to_be_after_tp1_and_to_tp1_after_tp2",
    }:
        raise RuntimeError(
            "STOP_MOVE_MODE must be none, move_sl_to_be_after_tp1, "
            "or move_sl_to_be_after_tp1_and_to_tp1_after_tp2"
        )
    percentages = (TP1_CLOSE_PERCENT, TP2_CLOSE_PERCENT, TP3_CLOSE_PERCENT)
    if any(value < 0 for value in percentages):
        raise RuntimeError("TP close percentages cannot be negative")
    if sum(percentages) != Decimal("100"):
        raise RuntimeError("TP1_CLOSE_PERCENT + TP2_CLOSE_PERCENT + TP3_CLOSE_PERCENT must equal 100")


validate_strategy_config()

DB_HOST = require_env("DB_HOST")
DB_PORT = int(require_env("DB_PORT"))
DB_DATABASE = require_env("DB_DATABASE")
DB_USERNAME = require_env("DB_USERNAME")
DB_PASSWORD = require_env("DB_PASSWORD")
