import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from bidesk import tracing
from bidesk.tracing import EDMONTON, MemorySink, SpanRecord, span


def test_gathered_spans_nest_under_their_parent(sink: MemorySink) -> None:
    async def child(n: int) -> None:
        async with span(f"child-{n}"):
            await asyncio.sleep(0)

    async def main() -> None:
        async with span("parent"):
            await asyncio.gather(child(1), child(2), child(3))

    asyncio.run(main())
    parent = next(r for r in sink.records if r.name == "parent")
    children = [r for r in sink.records if r.name.startswith("child")]
    assert len(children) == 3
    assert all(c.parent_span_id == parent.id for c in children)
    assert parent.parent_span_id is None


def test_spans_carry_the_run_id(sink: MemorySink) -> None:
    run_id = uuid4()

    async def main() -> None:
        with tracing.run(run_id):
            async with span("inside"):
                pass
        async with span("outside"):
            pass

    asyncio.run(main())
    inside, outside = sink.records
    assert inside.run_id == run_id
    assert outside.run_id is None


def test_a_failing_span_records_the_error_and_reraises(sink: MemorySink) -> None:
    async def main() -> None:
        async with span("boom"):
            raise KeyError("missing")

    with pytest.raises(KeyError):
        asyncio.run(main())
    (record,) = sink.records
    assert record.status == "error"
    assert record.error == "KeyError: 'missing'"


def test_sibling_spans_are_not_nested(sink: MemorySink) -> None:
    async def main() -> None:
        async with span("first"):
            pass
        async with span("second"):
            pass

    asyncio.run(main())
    assert all(r.parent_span_id is None for r in sink.records)


def test_no_sink_means_no_span() -> None:
    tracing.set_sink(None)

    async def main() -> None:
        async with span("unlogged"):
            pass

    with pytest.raises(tracing.NoSinkError):
        asyncio.run(main())


def test_spent_today_counts_only_today_in_edmonton() -> None:
    memory = MemorySink()
    now = datetime.now(EDMONTON)
    memory.records = [
        SpanRecord(name="today", cost_usd=Decimal("0.25"), started_at=now),
        SpanRecord(name="also today", cost_usd=Decimal("0.50"), started_at=now),
        SpanRecord(name="yesterday", cost_usd=Decimal(9), started_at=now - timedelta(days=1)),
    ]
    assert asyncio.run(memory.spent_today()) == Decimal("0.75")
