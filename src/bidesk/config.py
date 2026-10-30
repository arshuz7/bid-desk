"""Settings from the environment. The Makefile loads `.env`; copy `.env.example` to create it."""

import os
from decimal import Decimal, InvalidOperation


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set; copy .env.example to .env and run via make")
    return value


def database_url() -> str:
    return _required("DATABASE_URL")


def anthropic_api_key() -> str:
    return _required("ANTHROPIC_API_KEY")


def voyage_api_key() -> str:
    return _required("VOYAGE_API_KEY")


def daily_cap_usd() -> Decimal:
    """The daily spend cap for model calls; `$2.00` unless BIDESK_DAILY_SPEND_CAP_USD says so."""
    raw = os.environ.get("BIDESK_DAILY_SPEND_CAP_USD", "").strip() or "2.00"
    try:
        cap = Decimal(raw)
    except InvalidOperation as e:
        raise ConfigError(f"BIDESK_DAILY_SPEND_CAP_USD is not a number: {raw!r}") from e
    if not cap.is_finite() or cap <= 0:
        raise ConfigError(f"BIDESK_DAILY_SPEND_CAP_USD must be a positive amount, not {raw!r}")
    return cap
