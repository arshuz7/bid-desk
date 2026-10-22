"""The only module that calls a model or embeddings API.

Every call is checked against the daily spend cap before it reaches the API, and logged as a
span with tokens, cost, latency and the raw output, whether it succeeds or fails.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import anthropic
import httpx2
from anthropic import AsyncAnthropic, transform_schema
from pydantic import BaseModel, ValidationError

from bidesk.tracing import SpanRecord, get_sink, span

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
VOYAGE_MODEL = "voyage-4"
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

MILLION = Decimal(1_000_000)
LONG_PROMPT_TOKENS = 100_000  # Haiku 5.5 charges a higher rate above this
CACHE_WRITE_MULTIPLIER = Decimal("1.25")
CACHE_READ_MULTIPLIER = Decimal("0.1")
CHARS_PER_TOKEN_ESTIMATE = 2  # deliberately low, so the cap check over-estimates
VOYAGE_PRICE_PER_M = Decimal("0.06")

Effort = Literal["low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True)
class ClaudePrice:
    """USD per million tokens, for prompts up to and above LONG_PROMPT_TOKENS."""

    input: Decimal
    output: Decimal
    long_input: Decimal
    long_output: Decimal


CLAUDE_PRICES = {
    HAIKU: ClaudePrice(Decimal("0.10"), Decimal("0.50"), Decimal("0.50"), Decimal("2.50")),
    SONNET: ClaudePrice(Decimal(2), Decimal(10), Decimal(2), Decimal(10)),
}


class LLMError(Exception):
    pass


class SpendCapExceeded(LLMError):
    pass


class LLMCallFailed(LLMError):
    pass


def claude_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> Decimal:
    price = CLAUDE_PRICES[model]
    prompt_tokens = input_tokens + cache_write_tokens + cache_read_tokens
    long = prompt_tokens > LONG_PROMPT_TOKENS
    in_rate = price.long_input if long else price.input
    out_rate = price.long_output if long else price.output
    billed_input = (
        input_tokens
        + cache_write_tokens * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * CACHE_READ_MULTIPLIER
    )
    return (billed_input * in_rate + output_tokens * out_rate) / MILLION


def estimate_tokens(*texts: str) -> int:
    return sum(len(t) for t in texts) // CHARS_PER_TOKEN_ESTIMATE + 1


def voyage_client(api_key: str) -> httpx2.AsyncClient:
    """An HTTP client for the Voyage API. The voyageai SDK is avoided because it pulls in
    LangChain, numpy, pillow and tokenizers for what is one POST request."""
    return httpx2.AsyncClient(headers={"Authorization": f"Bearer {api_key}"}, timeout=60.0)


class LLM:
    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        voyage_client: httpx2.AsyncClient,
        daily_cap_usd: Decimal = Decimal("2.00"),
    ) -> None:
        self._anthropic = anthropic_client
        self._voyage = voyage_client
        self.daily_cap_usd = daily_cap_usd

    async def _check_cap(self, record: SpanRecord, estimate: Decimal) -> None:
        spent = await get_sink().spent_today()
        if spent + estimate > self.daily_cap_usd:
            record.status = "cap_exceeded"
            raise SpendCapExceeded(
                f"spent ${spent:.4f} today; this call could cost up to ${estimate:.4f}, "
                f"over the ${self.daily_cap_usd} daily cap"
            )

    async def extract[T: BaseModel](
        self,
        *,
        prompt_id: str,
        prompt_version: int,
        model: str,
        system: str,
        user: str,
        output_model: type[T],
        max_tokens: int = 16_000,
        effort: Effort = "medium",
    ) -> T:
        """One Claude call whose answer must validate as `output_model`."""
        if model not in CLAUDE_PRICES:
            raise ValueError(f"unknown model {model!r}; add it to CLAUDE_PRICES")
        estimate = claude_cost(model, estimate_tokens(system, user), max_tokens)
        request_input: dict[str, object] = {
            "system": system,
            "user": user,
            "max_tokens": max_tokens,
            "effort": effort,
        }
        async with span(
            "claude",
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model=model,
            input=request_input,
        ) as record:
            await self._check_cap(record, estimate)
            try:
                response = await self._anthropic.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    output_config={
                        "format": {"type": "json_schema", "schema": transform_schema(output_model)},
                        "effort": effort,
                    },
                )
            except anthropic.APIError as e:
                raise LLMCallFailed(f"Claude API error: {e}") from e

            usage = response.usage
            cache_write = usage.cache_creation_input_tokens or 0
            cache_read = usage.cache_read_input_tokens or 0
            record.tokens_in = usage.input_tokens + cache_write + cache_read
            record.tokens_out = usage.output_tokens
            record.cost_usd = claude_cost(
                model, usage.input_tokens, usage.output_tokens, cache_write, cache_read
            )
            record.raw_output = "".join(b.text for b in response.content if b.type == "text")

            if response.stop_reason == "refusal":
                raise LLMCallFailed("the model refused the request")
            if response.stop_reason == "max_tokens":
                raise LLMCallFailed(f"output was cut off at max_tokens={max_tokens}")
            try:
                parsed = output_model.model_validate_json(record.raw_output)
            except ValidationError as e:
                raise LLMCallFailed(f"output failed validation: {e}") from e
            record.parsed_output = parsed.model_dump(mode="json")
            return parsed

    async def embed(
        self, texts: list[str], input_type: Literal["document", "query"]
    ) -> list[list[float]]:
        """Voyage embeddings, one vector per text, in order."""
        if not texts:
            return []
        estimate = estimate_tokens(*texts) * VOYAGE_PRICE_PER_M / MILLION
        async with span(
            "voyage",
            model=VOYAGE_MODEL,
            input={"input_type": input_type, "count": len(texts)},
        ) as record:
            await self._check_cap(record, estimate)
            try:
                response = await self._voyage.post(
                    VOYAGE_URL,
                    json={
                        "input": texts,
                        "model": VOYAGE_MODEL,
                        "input_type": input_type,
                        # an over-long chunk should fail loudly, not be cut silently
                        "truncation": False,
                    },
                )
                response.raise_for_status()
                body = response.json()
                total_tokens = int(body["usage"]["total_tokens"])
                data = sorted(body["data"], key=lambda item: item["index"])
                vectors = [[float(x) for x in item["embedding"]] for item in data]
            except httpx2.HTTPError as e:
                raise LLMCallFailed(f"Voyage API error: {e}") from e
            except (ValueError, KeyError, TypeError) as e:
                raise LLMCallFailed(f"Voyage returned an unexpected response: {e!r}") from e
            record.tokens_in = total_tokens
            record.cost_usd = total_tokens * VOYAGE_PRICE_PER_M / MILLION
            if len(vectors) != len(texts):
                raise LLMCallFailed(
                    f"Voyage returned {len(vectors)} vectors for {len(texts)} texts"
                )
            return vectors
