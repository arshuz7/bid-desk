import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path

import anthropic
import httpx2
import pytest
from conftest import FakeAnthropic, FakeVoyage, claude_response, voyage_result
from pydantic import BaseModel

from bidesk import tracing
from bidesk.llm import (
    HAIKU,
    LLM,
    SONNET,
    LLMCallFailed,
    SpendCapExceeded,
    claude_cost,
)
from bidesk.schemas.fields import WorkerField
from bidesk.tracing import MemorySink, SpanRecord


class Title(BaseModel):
    title: str


def extract(llm: LLM, output_model: type[BaseModel] = Title, **overrides: object) -> BaseModel:
    kwargs: dict[str, object] = {
        "prompt_id": "baseline",
        "prompt_version": 1,
        "model": HAIKU,
        "system": "Extract the title.",
        "user": "TENDER TEXT",
        "output_model": output_model,
        "max_tokens": 1_000,
        "effort": "low",
    }
    kwargs.update(overrides)
    return asyncio.run(llm.extract(**kwargs))  # type: ignore[arg-type]


# Cost


def test_haiku_cost() -> None:
    # 100k in at $0.10/M + 100k out at $0.50/M (100k is still the normal rate)
    assert claude_cost(HAIKU, 100_000, 100_000) == Decimal("0.06")


def test_haiku_long_prompt_rate_above_100k_tokens() -> None:
    assert claude_cost(HAIKU, 100_000, 0) == Decimal("0.01")
    assert claude_cost(HAIKU, 100_001, 0) == Decimal("0.0500005")


def test_sonnet_cost() -> None:
    assert claude_cost(SONNET, 1_000, 1_000) == Decimal("0.012")


def test_cache_tokens_are_priced_and_count_toward_the_long_prompt_rate() -> None:
    # 1,000 written at 1.25x, 10,000 read at 0.1x, 0 uncached: 1,250 + 1,000 = 2,250 billed
    assert claude_cost(SONNET, 0, 0, cache_write_tokens=1_000, cache_read_tokens=10_000) == Decimal(
        "0.0045"
    )
    # 50k uncached + 60k cache read is a 110k prompt, so the long rate applies
    assert claude_cost(HAIKU, 50_000, 0, cache_read_tokens=60_000) > claude_cost(
        HAIKU, 50_000, 0
    ) * Decimal("5")


# extract: success


def test_extract_returns_the_parsed_model_and_logs_a_span(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    fake_anthropic.queue.append(
        claude_response('{"title": "Bridge"}', input_tokens=2_000, output_tokens=300)
    )
    assert extract(llm) == Title(title="Bridge")

    (record,) = sink.records
    assert record.name == "claude"
    assert (record.prompt_id, record.prompt_version, record.model) == ("baseline", 1, HAIKU)
    assert (record.tokens_in, record.tokens_out) == (2_000, 300)
    assert record.cost_usd == claude_cost(HAIKU, 2_000, 300)
    assert record.raw_output == '{"title": "Bridge"}'
    assert record.parsed_output == {"title": "Bridge"}
    assert record.status == "ok"


def test_extract_sends_the_schema_and_effort(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    fake_anthropic.queue.append(claude_response('{"title": "Bridge"}'))
    extract(llm, effort="high")

    (call,) = fake_anthropic.calls
    assert call["model"] == HAIKU
    assert call["system"] == "Extract the title."
    assert call["messages"] == [{"role": "user", "content": "TENDER TEXT"}]
    assert call["output_config"]["effort"] == "high"
    schema = call["output_config"]["format"]["schema"]
    assert schema["properties"]["title"]["type"] == "string"


def test_extract_works_with_the_worker_schema(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    answer = {
        "status": "found",
        "value": "Bridge",
        "evidence": [{"file": "itt.pdf", "page": 1, "quote": "Bridge"}],
    }
    fake_anthropic.queue.append(claude_response(json.dumps(answer)))
    result = extract(llm, WorkerField[str])
    assert result.value == "Bridge"  # type: ignore[attr-defined]


# extract: the spend cap


def test_over_the_cap_raises_before_the_api_is_called(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    sink.records.append(SpanRecord(name="earlier", cost_usd=Decimal("1.9999")))
    with pytest.raises(SpendCapExceeded):
        extract(llm)
    assert fake_anthropic.calls == []
    refused = sink.records[-1]
    assert refused.status == "cap_exceeded"
    assert refused.cost_usd == 0


def test_the_cap_counts_the_worst_case_output(
    fake_anthropic: FakeAnthropic, fake_voyage: FakeVoyage, sink: MemorySink
) -> None:
    # 100k output tokens on Sonnet can cost $1, so a $0.50 cap refuses it up front
    capped = LLM(fake_anthropic, fake_voyage.client, daily_cap_usd=Decimal("0.50"))  # type: ignore[arg-type]
    with pytest.raises(SpendCapExceeded):
        extract(capped, model=SONNET, max_tokens=100_000)
    assert fake_anthropic.calls == []


def test_under_the_cap_the_call_goes_through(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    sink.records.append(SpanRecord(name="earlier", cost_usd=Decimal("1.50")))
    fake_anthropic.queue.append(claude_response('{"title": "Bridge"}'))
    extract(llm)
    assert len(fake_anthropic.calls) == 1


def test_unknown_model_raises_before_any_call(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    with pytest.raises(ValueError, match="unknown model"):
        extract(llm, model="claude-imaginary")
    assert fake_anthropic.calls == []


def test_no_sink_means_no_call(llm: LLM, fake_anthropic: FakeAnthropic) -> None:
    tracing.set_sink(None)
    with pytest.raises(tracing.NoSinkError):
        extract(llm)
    assert fake_anthropic.calls == []


# extract: failures are logged with their cost and raw output


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (claude_response("", stop_reason="refusal"), "refused"),
        (claude_response('{"title": "Bri', stop_reason="max_tokens"), "cut off"),
        (claude_response("not json"), "failed validation"),
        (claude_response('{"name": "Bridge"}'), "failed validation"),
    ],
)
def test_bad_responses_raise_llm_call_failed(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink, response: object, message: str
) -> None:
    fake_anthropic.queue.append(response)
    with pytest.raises(LLMCallFailed, match=message):
        extract(llm)
    (record,) = sink.records
    assert record.status == "error"
    assert message in (record.error or "")
    assert record.cost_usd > 0  # we paid for it, so it counts toward the cap
    assert record.parsed_output is None


def test_our_validators_apply_to_model_output(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    # Valid JSON, but FOUND without evidence breaks the schema's rules
    fake_anthropic.queue.append(claude_response('{"status": "found", "value": "Bridge"}'))
    with pytest.raises(LLMCallFailed, match="at least one evidence"):
        extract(llm, WorkerField[str])
    assert sink.records[0].raw_output == '{"status": "found", "value": "Bridge"}'


def test_worker_output_cannot_set_confidence(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    answer = '{"status": "not_stated", "confidence": 0.99}'
    fake_anthropic.queue.append(claude_response(answer))
    with pytest.raises(LLMCallFailed, match="Extra inputs"):
        extract(llm, WorkerField[str])


def test_api_errors_raise_llm_call_failed(
    llm: LLM, fake_anthropic: FakeAnthropic, sink: MemorySink
) -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_anthropic.queue.append(anthropic.APIConnectionError(request=request))
    with pytest.raises(LLMCallFailed, match="Claude API error"):
        extract(llm)
    (record,) = sink.records
    assert record.status == "error"
    assert record.cost_usd == 0


# embed


def test_embed_returns_vectors_and_logs_cost(
    llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink
) -> None:
    fake_voyage.queue.append(voyage_result([[0.1, 0.2], [0.3, 0.4]], total_tokens=1_000_000))
    vectors = asyncio.run(llm.embed(["a", "b"], "document"))
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]

    (call,) = fake_voyage.calls
    assert call == {
        "url": "https://api.voyageai.com/v1/embeddings",
        "body": {
            "input": ["a", "b"],
            "model": "voyage-4",
            "input_type": "document",
            "truncation": False,
        },
    }
    (record,) = sink.records
    assert (record.name, record.tokens_in, record.cost_usd) == (
        "voyage",
        1_000_000,
        Decimal("0.06"),
    )
    assert record.input == {"input_type": "document", "count": 2}


def test_embed_keeps_input_order_even_if_the_api_reorders(
    llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink
) -> None:
    body = {
        "data": [{"index": 1, "embedding": [2.0]}, {"index": 0, "embedding": [1.0]}],
        "usage": {"total_tokens": 4},
    }
    fake_voyage.queue.append(httpx2.Response(200, json=body))
    assert asyncio.run(llm.embed(["first", "second"], "document")) == [[1.0], [2.0]]


def test_embed_nothing_makes_no_call(llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink) -> None:
    assert asyncio.run(llm.embed([], "query")) == []
    assert fake_voyage.calls == []
    assert sink.records == []


def test_embed_vector_count_mismatch_fails(
    llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink
) -> None:
    fake_voyage.queue.append(voyage_result([[0.1]]))
    with pytest.raises(LLMCallFailed, match="1 vectors for 2 texts"):
        asyncio.run(llm.embed(["a", "b"], "document"))


@pytest.mark.parametrize(
    "failure",
    [
        httpx2.Response(503, json={"detail": "down"}),
        httpx2.Response(429, json={"detail": "slow down"}),
        httpx2.ConnectError("no route"),
    ],
)
def test_embed_http_errors_raise_llm_call_failed(
    llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink, failure: object
) -> None:
    fake_voyage.queue.append(failure)  # type: ignore[arg-type]
    with pytest.raises(LLMCallFailed, match="Voyage API error"):
        asyncio.run(llm.embed(["a"], "query"))
    assert sink.records[0].status == "error"


@pytest.mark.parametrize("body", [{"data": []}, {"usage": {"total_tokens": 1}}, "not json"])
def test_embed_malformed_response_fails(
    llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink, body: object
) -> None:
    response = (
        httpx2.Response(200, text=body)
        if isinstance(body, str)
        else httpx2.Response(200, json=body)
    )
    fake_voyage.queue.append(response)
    with pytest.raises(LLMCallFailed, match="unexpected response"):
        asyncio.run(llm.embed(["a"], "query"))


def test_embed_over_the_cap_makes_no_call(
    llm: LLM, fake_voyage: FakeVoyage, sink: MemorySink
) -> None:
    sink.records.append(SpanRecord(name="earlier", cost_usd=Decimal("2.00")))
    with pytest.raises(SpendCapExceeded):
        asyncio.run(llm.embed(["a"], "query"))
    assert fake_voyage.calls == []


def test_only_llm_py_talks_to_model_apis() -> None:
    src = Path(__file__).resolve().parent.parent / "src" / "bidesk"
    pattern = re.compile(r"^\s*(import|from)\s+(anthropic|voyageai)\b|api\.voyageai\.com", re.M)
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if path.name != "llm.py" and pattern.search(path.read_text())
    ]
    assert offenders == [], "only src/bidesk/llm.py may call Claude or Voyage"
