import pytest

from bidesk.text import normalize_text


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Example Creek  Trail\nBridge", "example creek trail bridge"),  # case and whitespace
        ("Parks Canada Agency.", "parks canada agency"),  # punctuation
        ("asbestos abate-\nment", "asbestos abatement"),  # a word broken across lines
        ("Contractor’s “COR”", "contractor s cor"),  # curly quotes
        ("Phase 1 — Demolition", "phase 1 demolition"),  # dashes
        ("ﬁre stopping", "fire stopping"),  # a ligature
        ("$1,000", "1000"),  # thousands separators go
        ("$1,000,000.50", "1000000.50"),
        ("10%", "10 %"),
        ("RFT-2021-551", "rft 2021 551"),
    ],
)
def test_these_normalize_the_same(a: str, b: str) -> None:
    assert normalize_text(a) == normalize_text(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("1.5%", "15%"),  # a decimal point is never dropped
        ("1,5 %", "15 %"),  # nor a decimal comma (French)
        ("sections 1,2 and 3", "sections 12 and 3"),
        ("$1,000.50", "$100050"),
        ("Section 2.1", "Section 21"),
        ("bid bond", "bid-bond deposit"),
    ],
)
def test_these_stay_different(a: str, b: str) -> None:
    assert normalize_text(a) != normalize_text(b)


def test_a_sentence_ending_in_a_number_keeps_the_number() -> None:
    assert normalize_text("The bond is 10. The fee is 2.5.") == "the bond is 10 the fee is 2.5"
    assert normalize_text("") == ""
