# memsearch-win

**Windows-native fork of [memsearch](https://github.com/zilliztech/memsearch) — replaces Milvus with LanceDB.**

The upstream project uses milvus-lite as its local vector store, which has no Windows wheels. This fork swaps it for [LanceDB](https://lancedb.github.io/lancedb/), which is fully Windows-native. Everything else — the Claude Code plugin, hybrid search, ONNX embeddings, the Python API — works the same way.

> **Upstream:** https://github.com/zilliztech/memsearch  
> **What diverges from upstream:** `store_lance.py` (new), `core.py` (1-line import swap), `pyproject.toml` (dependency swap)

---

## What it does

memsearch gives Claude Code persistent memory across sessions. After each conversation, a hook summarizes the turn and appends it to a daily markdown file. At the start of the next session, those notes are indexed and made searchable via the `memory-recall` skill.

```
Session ends → Stop hook → LLM summarizes turn → appends to memory/YYYY-MM-DD.md
                                                         ↓
Session starts → SessionStart hook → index memory/ → inject recent context
                                                         ↓
You ask something → /memory-recall → search → expand → transcript
```

---

## Install

This package is not on PyPI. Install from source:

```bash
git clone https://github.com/jv209/memsearch-win.git
cd memsearch-win
uv sync --all-extras
```

Or install directly with pip into an existing environment:

```bash
pip install "git+https://github.com/jv209/memsearch-win.git[onnx]"
```

The `[onnx]` extra enables the default local embedding model (bge-m3, CPU, no API key). On first use it downloads ~558 MB from HuggingFace Hub.

---

## Claude Code Plugin

### Install the plugin

```bash
# Copy plugin to Claude Code's plugin cache
cp -r plugins/claude-code ~/.claude/plugins/cache/memsearch-plugins/memsearch-win/0.4.0

# Register it (run from repo root)
python register_plugin.py
```

Or use the manual method: add the plugin to `~/.claude/plugins/installed_plugins.json` and enable it in `~/.claude/settings.json`, then run `/reload-plugins` in a Claude Code session.

### Verify it's working

After a few sessions, check for daily memory files:

```bash
ls .memsearch/memory/
cat .memsearch/memory/$(date +%Y-%m-%d).md
```

### Recall memories

```
/memory-recall what did we discuss about Redis?
```

Or just ask naturally — Claude invokes the skill automatically when it senses a question needs historical context:

```
We discussed that auth issue before, what was the fix?
```

---

## Configuration

### Embedding provider

Defaults to ONNX bge-m3 (local, free, no API key):

```bash
memsearch config set embedding.provider onnx     # default
memsearch config set embedding.provider openai   # requires OPENAI_API_KEY
memsearch config set embedding.provider ollama   # local, any model
```

### Vector store

This fork uses LanceDB. The database is a local directory:

```bash
memsearch config get milvus.uri   # → ~/.memsearch/lance.db
```

No server, no Docker, no API key — just a folder on disk. The `milvus.uri` config key is retained for compatibility with upstream config files.

---

## CLI

```bash
memsearch index ./memory/                          # index markdown files
memsearch search "Redis caching"                   # hybrid search (FTS + vector + RRF)
memsearch expand <chunk_hash>                      # show full section around a chunk
memsearch watch ./memory/                          # live file watcher
memsearch stats                                    # show indexed chunk count
memsearch reset --yes                              # drop index and rebuild
```

---

## Python API

```python
from memsearch import MemSearch

mem = MemSearch(paths=["./memory"])

await mem.index()
results = await mem.search("Redis config", top_k=3)
print(results[0]["content"], results[0]["score"])
```

---

## LanceDB backend notes

The store is in `src/memsearch/store_lance.py`. Key behaviors that differ from Milvus:

- **SQL filter syntax:** DataFusion (LanceDB's engine) treats backslashes as literal characters. `C:\path` in a filter matches a stored `C:\path` directly — no doubling needed.
- **Hybrid search API:** `.search(query_type="hybrid").vector(emb).text(text).rerank(RRFReranker()).limit(n)` — the vector and text args must be chained, not passed positionally.
- **FTS index:** Rebuilt after every upsert (`create_fts_index("content", replace=True)`).
- **Stale references:** After a mutation, re-open the table with a fresh `lancedb.connect().open_table()` if checking row count from outside the store.

---

## Keeping in sync with upstream

Only three files diverge from upstream:

| File | Change |
|------|--------|
| `src/memsearch/store_lance.py` | New file — LanceDB backend |
| `src/memsearch/core.py` | One import: `from .store_lance import LanceStore as MilvusStore` |
| `pyproject.toml` | `lancedb + tantivy + pyarrow` instead of `pymilvus + milvus-lite` |

To merge upstream changes: pull upstream, apply those three files, run the Phase 3 tests.

---

## License

[MIT](LICENSE) — same as upstream.
