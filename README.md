# memsearch-win

**Windows-native fork of [memsearch](https://github.com/zilliztech/memsearch) — replaces Milvus with LanceDB.**

The upstream project uses milvus-lite as its local vector store, which has no Windows wheels. This fork swaps it for [LanceDB](https://lancedb.github.io/lancedb/), which is fully Windows-native. The result is a Claude Code memory plugin that works on Windows without WSL.

> **Upstream:** https://github.com/zilliztech/memsearch  
> **What diverges from upstream:** `store_lance.py` (new), `core.py` (1-line import swap), `pyproject.toml` (dependency swap)

---

## What it does

Gives Claude Code persistent memory across sessions. After each conversation turn, a hook summarizes the exchange and appends it to a daily markdown file. At the start of the next session, those notes are indexed and made searchable via the `memory-recall` skill.

```
Session ends   → Stop hook → LLM summarizes turn → appends to .memsearch/memory/YYYY-MM-DD.md
Session starts → SessionStart hook → index memory dir → inject recent context into Claude
You ask        → /memory-recall → search → expand → original transcript
```

Memory files are plain markdown — readable, editable, version-controllable. LanceDB is a rebuildable index derived from them.

---

## Requirements

- Windows 10/11
- Python 3.10+
- Claude Code
- `uv` (recommended) or `pip`

---

## Install

```bash
git clone https://github.com/jv209/memsearch-win.git
cd memsearch-win
uv sync --all-extras
```

The `[onnx]` extra (included in `--all-extras`) enables the default local embedding model (bge-m3, CPU, no API key). On first use it downloads ~558 MB from HuggingFace Hub.

---

## Claude Code Plugin Setup

### 1. Register the plugin

```bash
python register_plugin.py
```

Then run `/reload-plugins` in a Claude Code session (or restart Claude Code).

### 2. Verify it's working

After a session ends, check for a daily memory file:

```bash
ls .memsearch/memory/
```

### 3. Recall memories

```
/memory-recall what did we discuss about Redis?
```

Or ask naturally — Claude invokes the skill automatically when it senses a question needs historical context:

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

LanceDB stores data in a local directory — no server, no Docker, no API key:

```bash
memsearch config get milvus.uri   # → ~/.memsearch/lance.db
```

---

## CLI

```bash
memsearch index ./memory/          # index markdown files
memsearch search "Redis caching"   # hybrid search (FTS + vector + RRF)
memsearch expand <chunk_hash>      # show full section around a chunk
memsearch stats                    # show indexed chunk count
memsearch reset --yes              # drop index and rebuild
```

---

## Keeping in sync with upstream

Only three files diverge:

| File | Change |
|------|--------|
| `src/memsearch/store_lance.py` | New — LanceDB backend |
| `src/memsearch/core.py` | One import: `from .store_lance import LanceStore as MilvusStore` |
| `pyproject.toml` | `lancedb + tantivy + pyarrow` instead of `pymilvus + milvus-lite` |

To pull upstream changes: fetch upstream, apply those three files, run tests.

---

## License

[MIT](LICENSE) — same as upstream.
