"""Settings from the environment. The Makefile loads `.env`; copy `.env.example` to create it."""

import os
from decimal import Decimal, InvalidOperation


class ConfigError(RuntimeError):
    pass


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ConfigError("DATABASE_URL is not set; copy .env.example to .env and run via make")
    return url


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
