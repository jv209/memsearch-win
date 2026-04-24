"""LanceDB vector storage layer — Windows-native drop-in for MilvusStore."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


def _escape_sql_str(value: str) -> str:
    """Escape a value for interpolation into a SQL single-quoted string literal.

    DataFusion (LanceDB's SQL engine) treats backslashes as literal characters,
    so only single quotes need escaping.
    """
    return value.replace("'", "''")


def _translate_filter(expr: str) -> str:
    """Translate Milvus filter syntax to LanceDB SQL WHERE syntax."""
    if not expr:
        return expr
    # Milvus == → SQL =
    expr = expr.replace(" == ", " = ")
    # Convert Milvus double-quoted string literals to single-quoted SQL strings.
    # Also un-escape Milvus-style escapes: \\ → \ and \" → "
    def _rewrite_string(m: re.Match) -> str:
        inner = m.group(1)
        inner = inner.replace('\\"', '"')    # un-escape Milvus \" → "
        inner = inner.replace("\\\\", "\\") # un-escape Milvus \\ → \ (DataFusion is literal)
        inner = inner.replace("'", "''")    # SQL single-quote escape
        return f"'{inner}'"

    return re.sub(r'"((?:[^"\\]|\\.)*)"', _rewrite_string, expr)


class LanceStore:
    """LanceDB-backed chunk store, drop-in replacement for MilvusStore.

    Hybrid search uses dense vector + tantivy FTS with RRF reranking,
    matching Milvus's dense + BM25 + RRF pipeline.
    """

    DEFAULT_COLLECTION = "memsearch_chunks"

    def __init__(
        self,
        uri: str = "~/.memsearch/lance.db",
        *,
        token: str | None = None,
        collection: str = DEFAULT_COLLECTION,
        dimension: int | None = 1536,
        description: str = "",
    ) -> None:
        import lancedb

        resolved = str(Path(uri).expanduser())
        Path(resolved).mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(resolved)
        self._collection = collection
        self._dimension = dimension
        self._table = None
        self._ensure_table()

    def _schema(self):
        import pyarrow as pa

        return pa.schema([
            pa.field("chunk_hash", pa.string()),
            pa.field("embedding", pa.list_(pa.float32(), self._dimension)),
            pa.field("content", pa.string()),
            pa.field("source", pa.string()),
            pa.field("heading", pa.string()),
            pa.field("heading_level", pa.int64()),
            pa.field("start_line", pa.int64()),
            pa.field("end_line", pa.int64()),
        ])

    def _ensure_table(self) -> None:
        import lancedb

        if self._collection in self._db.table_names():
            self._table = self._db.open_table(self._collection)
            if self._dimension is not None:
                existing_dim = self._table.schema.field("embedding").type.list_size
                if existing_dim != self._dimension:
                    raise ValueError(
                        f"Embedding dimension mismatch: table '{self._collection}' "
                        f"has dim={existing_dim} but current provider outputs "
                        f"dim={self._dimension}. Run 'memsearch reset --yes' to re-index."
                    )
        elif self._dimension is not None:
            self._table = self._db.create_table(self._collection, schema=self._schema())

    @property
    def _tbl(self):
        if self._table is None:
            raise RuntimeError(f"Table '{self._collection}' does not exist.")
        return self._table

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        import pyarrow as pa

        if not chunks:
            return 0

        tbl = self._tbl
        schema = self._schema()

        data = {
            "chunk_hash": pa.array([c["chunk_hash"] for c in chunks], type=pa.string()),
            "embedding": pa.array(
                [c["embedding"] for c in chunks],
                type=pa.list_(pa.float32(), self._dimension),
            ),
            "content": pa.array([c["content"] for c in chunks], type=pa.string()),
            "source": pa.array([c["source"] for c in chunks], type=pa.string()),
            "heading": pa.array([c.get("heading", "") for c in chunks], type=pa.string()),
            "heading_level": pa.array([int(c.get("heading_level", 0)) for c in chunks], type=pa.int64()),
            "start_line": pa.array([int(c.get("start_line", 0)) for c in chunks], type=pa.int64()),
            "end_line": pa.array([int(c.get("end_line", 0)) for c in chunks], type=pa.int64()),
        }
        batch = pa.table(data, schema=schema)

        (
            tbl.merge_insert("chunk_hash")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(batch)
        )
        tbl.create_fts_index("content", replace=True)
        return len(chunks)

    def search(
        self,
        query_embedding: list[float],
        *,
        query_text: str = "",
        top_k: int = 10,
        filter_expr: str = "",
    ) -> list[dict[str, Any]]:
        """Hybrid search: dense vector + FTS with RRF reranking."""
        from lancedb.rerankers import RRFReranker

        tbl = self._tbl
        if tbl.count_rows() == 0:
            return []

        sql_filter = _translate_filter(filter_expr)

        if query_text:
            q = (
                tbl.search(query_type="hybrid")
                .vector(query_embedding)
                .text(query_text)
                .rerank(RRFReranker())
                .limit(top_k)
            )
        else:
            q = tbl.search(query_embedding).limit(top_k)

        if sql_filter:
            q = q.where(sql_filter, prefilter=True)

        rows = q.to_list()
        result = []
        for row in rows:
            score = row.get("_relevance_score", row.get("_distance", 0.0))
            entry = {k: row[k] for k in self._QUERY_FIELDS if k in row}
            entry["score"] = float(score) if score is not None else 0.0
            result.append(entry)
        return result

    _QUERY_FIELDS: ClassVar[list[str]] = [
        "content",
        "source",
        "heading",
        "chunk_hash",
        "heading_level",
        "start_line",
        "end_line",
    ]

    def query(self, *, filter_expr: str = "") -> list[dict[str, Any]]:
        """Retrieve chunks by scalar filter (no vector needed)."""
        tbl = self._tbl
        sql = _translate_filter(filter_expr) if filter_expr else "chunk_hash != ''"
        rows = tbl.search().where(sql).select(self._QUERY_FIELDS).to_list()
        return [{k: row[k] for k in self._QUERY_FIELDS if k in row} for row in rows]

    def hashes_by_source(self, source: str) -> set[str]:
        tbl = self._tbl
        rows = tbl.search().where(f"source = '{_escape_sql_str(source)}'").select(["chunk_hash"]).to_list()
        return {r["chunk_hash"] for r in rows}

    def indexed_sources(self) -> set[str]:
        tbl = self._tbl
        if tbl.count_rows() == 0:
            return set()
        rows = tbl.search().where("chunk_hash != ''").select(["source"]).to_list()
        return {r["source"] for r in rows}

    def delete_by_source(self, source: str) -> None:
        self._tbl.delete(f"source = '{_escape_sql_str(source)}'")

    def delete_by_hashes(self, hashes: list[str]) -> None:
        if not hashes:
            return
        if len(hashes) == 1:
            self._tbl.delete(f"chunk_hash = '{_escape_sql_str(hashes[0])}'")
        else:
            values = ", ".join(f"'{_escape_sql_str(h)}'" for h in hashes)
            self._tbl.delete(f"chunk_hash IN ({values})")

    def count(self) -> int:
        return self._tbl.count_rows()

    def drop(self) -> None:
        if self._collection in self._db.table_names():
            self._db.drop_table(self._collection)
            self._table = None

    def close(self) -> None:
        pass  # LanceDB has no explicit close; connections are reference-counted

    def __enter__(self) -> LanceStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
