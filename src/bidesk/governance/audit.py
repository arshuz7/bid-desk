"""The audit log: spans go to the append-only `spans` table, and the spend cap reads them back."""

from decimal import Decimal

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from bidesk.tracing import SpanRecord, start_of_today

INSERT_SPAN = """
INSERT INTO spans (
    id, run_id, parent_span_id, agent, name, prompt_id, prompt_version, model, input,
    retrieved_chunk_ids, raw_output, parsed_output, tokens_in, tokens_out, cost_usd,
    latency_ms, status, error, started_at
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""


class PostgresSpanSink:
    """Writes each span the moment it ends. Errors propagate: a paid call must never go
    unlogged, so a failed write stops the caller instead of being swallowed."""

    def __init__(self, conn: AsyncConnection) -> None:
        # Its own autocommit connection: a span written inside the caller's transaction would
        # vanish if that transaction rolled back, though the call was already paid for.
        if not conn.autocommit:
            raise ValueError("PostgresSpanSink needs its own autocommit connection")
        self._conn = conn

    async def emit(self, record: SpanRecord) -> None:
        await self._conn.execute(
            INSERT_SPAN,
            (
                record.id,
                record.run_id,
                record.parent_span_id,
                record.agent,
                record.name,
                record.prompt_id,
                record.prompt_version,
                record.model,
                None if record.input is None else Jsonb(record.input),
                record.retrieved_chunk_ids,
                record.raw_output,
                None if record.parsed_output is None else Jsonb(record.parsed_output),
                record.tokens_in,
                record.tokens_out,
                record.cost_usd,
                record.latency_ms,
                record.status,
                record.error,
                record.started_at,
            ),
        )

    async def spent_today(self) -> Decimal:
        cur = await self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM spans WHERE started_at >= %s",
            (start_of_today(),),
        )
        row = await cur.fetchone()
        return Decimal(row[0]) if row else Decimal(0)
