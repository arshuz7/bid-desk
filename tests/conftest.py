import asyncio
import json
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest

from bidesk import tracing
from bidesk.llm import LLM

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def example_label() -> dict[str, Any]:
    """The full example label in docs/evals.md, read from the doc so the two can't drift."""
    text = (ROOT / "docs" / "evals.md").read_text()
    block = re.search(r"```json\n(.*?)```", text, re.DOTALL)
    assert block, "docs/evals.md has no ```json example"
    return json.loads(block[1])


# Fake model clients. Tests never call real APIs; these stand in for AsyncAnthropic and
# voyageai.AsyncClient, record every call, and replay queued responses or exceptions.


def claude_response(
    text: str,
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 1_000,
    output_tokens: int = 200,
    cache_write: int | None = None,
    cache_read: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
        ),
    )


class FakeAnthropic:
    def __init__(self) -> None:
        self.queue: list[object] = []
        self.calls: list[dict[str, Any]] = []
        self.gate: asyncio.Event | None = None  # if set, calls wait here until it opens

    @property
    def messages(self) -> "FakeAnthropic":
        return self

    async def create(self, **kwargs: Any) -> object:  # noqa: ANN401
        self.calls.append(kwargs)
        await asyncio.sleep(0)  # like the network: lets calls started together overlap
        if self.gate is not None:
            await self.gate.wait()
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeVoyage:
    """A real httpx2 client whose transport replays queued responses instead of the network."""

    def __init__(self) -> None:
        self.queue: list[httpx2.Response | Exception] = []
        self.calls: list[dict[str, Any]] = []
        self.client = httpx2.AsyncClient(transport=httpx2.MockTransport(self._handle))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append({"url": str(request.url), "body": json.loads(request.content)})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def voyage_result(vectors: list[list[float]], total_tokens: int = 100) -> httpx2.Response:
    data = [{"index": i, "embedding": v} for i, v in enumerate(vectors)]
    return httpx2.Response(200, json={"data": data, "usage": {"total_tokens": total_tokens}})


@pytest.fixture
def sink() -> Iterator[tracing.MemorySink]:
    memory = tracing.MemorySink()
    tracing.set_sink(memory)
    yield memory
    tracing.set_sink(None)


@pytest.fixture
def fake_anthropic() -> FakeAnthropic:
    return FakeAnthropic()


@pytest.fixture
def fake_voyage() -> FakeVoyage:
    return FakeVoyage()


@pytest.fixture
def llm(fake_anthropic: FakeAnthropic, fake_voyage: FakeVoyage) -> LLM:
    return LLM(fake_anthropic, fake_voyage.client, Decimal("2.00"))  # type: ignore[arg-type]
