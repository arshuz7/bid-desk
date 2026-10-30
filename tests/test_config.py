from decimal import Decimal

import pytest

from bidesk.config import ConfigError, daily_cap_usd, database_url


def test_database_url_must_be_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "  ")
    with pytest.raises(ConfigError, match="DATABASE_URL is not set"):
        database_url()
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    assert database_url() == "postgresql://u:p@localhost/db"


def test_daily_cap_defaults_to_two_dollars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIDESK_DAILY_SPEND_CAP_USD", raising=False)
    assert daily_cap_usd() == Decimal("2.00")
    monkeypatch.setenv("BIDESK_DAILY_SPEND_CAP_USD", "")
    assert daily_cap_usd() == Decimal("2.00")


def test_daily_cap_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIDESK_DAILY_SPEND_CAP_USD", "0.50")
    assert daily_cap_usd() == Decimal("0.50")


@pytest.mark.parametrize("raw", ["two", "0", "-1", "NaN", "Infinity"])
def test_daily_cap_rejects_nonsense(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("BIDESK_DAILY_SPEND_CAP_USD", raw)
    with pytest.raises(ConfigError):
        daily_cap_usd()
