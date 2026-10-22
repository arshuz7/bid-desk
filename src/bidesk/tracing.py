"""Spans: one record per step, nested through ContextVars, sent to whatever sink is registered.

`llm.py` reports every model call here. The composition root registers a sink at startup
(the Postgres sink comes with governance); `MemorySink` serves tests and local runs. With no
sink registered, opening a span raises, so nothing can run unlogged.
"""

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

EDMONTON = ZoneInfo("America/Edmonton")

SpanStatus = Literal["ok", "error", "cap_exceeded"]


@dataclass
class SpanRecord:
    """One row of the `spans` table."""

    name: str
    id: UUID = field(default_factory=uuid4)
    run_id: UUID | None = None
    parent_span_id: UUID | None = None
    agent: str | None = None
    prompt_id: str | None = None
    prompt_version: int | None = None
    model: str | None = None
    input: dict[str, object] | None = None
    retrieved_chunk_ids: list[int] = field(default_factory=list)
    raw_output: str | None = None
    parsed_output: dict[str, object] | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0
    status: SpanStatus = "ok"
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(EDMONTON))


class SpanSink(Protocol):
    async def emit(self, record: SpanRecord) -> None: ...

    async def spent_today(self) -> Decimal:
        """Total `cost_usd` of spans started today, America/Edmonton."""
        ...


class NoSinkError(RuntimeError):
    pass


class MemorySink:
    """Keeps spans in a list. For tests and local runs before the database exists."""

    def __init__(self) -> None:
        self.records: list[SpanRecord] = []

    async def emit(self, record: SpanRecord) -> None:
        self.records.append(record)

    async def spent_today(self) -> Decimal:
        today = datetime.now(EDMONTON).date()
        return sum(
            (r.cost_usd for r in self.records if r.started_at.astimezone(EDMONTON).date() == today),
            Decimal(0),
        )


_sink: SpanSink | None = None
_run_id: ContextVar[UUID | None] = ContextVar("run_id", default=None)
_span_id: ContextVar[UUID | None] = ContextVar("span_id", default=None)


def set_sink(sink: SpanSink | None) -> None:
    global _sink
    _sink = sink


def get_sink() -> SpanSink:
    if _sink is None:
        raise NoSinkError("no span sink registered; call tracing.set_sink() at startup")
    return _sink


@contextmanager
def run(run_id: UUID) -> Iterator[None]:
    """Attach every span opened inside this block to `run_id`."""
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)


@asynccontextmanager
async def span(name: str, **fields: object) -> AsyncIterator[SpanRecord]:
    """Time a step and emit its record on exit, nested under the current span.

    `asyncio.gather` copies the context into each task, so spans opened in gathered tasks
    nest under the span that was current when the tasks were created.
    """
    sink = get_sink()
    record = SpanRecord(name=name, run_id=_run_id.get(), parent_span_id=_span_id.get(), **fields)  # type: ignore[arg-type]
    token = _span_id.set(record.id)
    start = time.perf_counter()
    try:
        yield record
    except BaseException as e:
        if record.status == "ok":
            record.status = "error"
        if record.error is None:
            record.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        _span_id.reset(token)
        record.latency_ms = round((time.perf_counter() - start) * 1000)
        await sink.emit(record)
