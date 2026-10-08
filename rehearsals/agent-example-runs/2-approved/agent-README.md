# Reading List Agent

Keep a list of articles and books to read, find them by topic, and mark them
read — so you can answer "what should I read next about X?" from your own
list, not from a model's imagination.

## Contract

### Purpose
Save things to read, retrieve them by keyword, tag, or unread status, and
mark them read when done.

### Inputs
- **Chat / CLI messages** — natural-language commands like
  `add Attention is all you need https://arxiv.org/abs/1706.03762 #ml`,
  `find ml`, `unread`, `read <item_id>`, `delete <item_id>`, `summarize`.
- **Tool CLIs** (`tools/*.py`) — one action each, structured flags.
- **HTTP API** (`api/main.py`) — JSON payloads to `/items`, `/items/{id}/read`,
  `/items/{id}`, `/overview`, `/summary`, `/chat`.
- **Web UI** (`ui/app.py`) — forms for add / mark read / delete / summarize,
  plus a chat page.

### Outputs
- **Items** carry `id` (`item_` + 10 hex), `title` (one line, ≤200 chars),
  `url` (optional, must start with `http://` or `https://`), `tags` (lowercase
  slugs), `status` (`unread` → `read`), and `added_at` (ISO 8601 UTC set by
  the store).
- **Tool CLIs** print one JSON envelope on stdout — `{"status":"success", "data":…}`
  on success, `{"status":"error", "error":…}` and exit 1 on failure.
- **Chat replies** are short plain text; the UI/API also return
  `tools_used`, `used_llm`, and the updated history.
- **Summaries** come from the `reading_summarizer` subagent and include
  `summary`, `item_count`, `tag`, `used_llm`.

### Actions (contract pin)
| Action | Does | Changes data |
|---|---|---|
| `add_item` | Save a new title/URL. A URL already on the list returns the existing item. | yes |
| `search_items` | Find items by words in the title or by a tag; optional unread-only. | no |
| `mark_read` | Flip one item's status to `read`, by exact id. | yes |
| `delete_item` | Remove one item, by exact id. | yes |

### Permissions
- Local only. The API and UI bind to `127.0.0.1`; neither has authentication.
  Do not expose on a network without adding an access design.
- No model-callable action outside the four tools above.
- No access to the network beyond the Gemini call when chat/summary runs in
  LLM mode.

### Side effects
- Writes to one JSON file at `memory/data/items.json` (or wherever
  `READING_LIST_AGENT_DATA_DIR` points).
- Spawns one subprocess per `summarize` call: `subagents/reading_summarizer.py`.
- Reads `.env` / `.env.local` from this folder upwards; never commits them.

### Offline behavior
Everything works without a Gemini API key:
- With no key, `READING_LIST_AGENT_OFFLINE=1`, or `--offline`, chat routes
  through a small regex-based command router that calls the same service
  functions.
- The summarizer falls back to a deterministic textual summary when no key
  is set.
- The core module (`reading_list_core.py`) has no I/O and no network.

### Memory / retention
- One JSON array file in the agent's data directory. One record per item.
- Items are retained until the user deletes them. **Read items are kept**;
  marking read only flips a status field.
- Tests use a disposable `tmp_path` directory; no real items are written
  during the test run.

### Surfaces
- `cli` — `python reading_list_agent.py …`
- `api` — FastAPI at `http://127.0.0.1:8013`
- `ui` — Flask at `http://127.0.0.1:5013`

## Anatomy

```
reading-list-agent/
├── reading_list_agent.py    # CLI: --chat, single query, --offline
├── reading_list_core.py     # Pure domain logic: Item model, tags, search, offline summary
├── reading_list_service.py  # Use cases shared by every surface + subagent delegation
├── reading_list_chat.py     # Chat: Gemini function calling, or an offline command router
├── agent_env.py             # Loads .env / .env.local from this folder upwards
├── agent_llm.py             # Gemini client, API key lookup, offline switch
├── agent_cli.py             # JSON envelope used by every tool/subagent/memory CLI
├── .env.example             # Commented, non-secret environment options
├── memory/
│   ├── memory.py            # ItemStore (JSON file, atomic writes) + inspection CLI
│   ├── item_schema.json     # Data schema
│   └── data/                # items.json lives here (gitignored)
├── tools/                   # One CLI per contract action
│   ├── add_item.py
│   ├── search_items.py
│   ├── mark_read.py
│   └── delete_item.py
├── subagents/
│   └── reading_summarizer.py  # Independent process, run by the service layer
├── skills/                  # Markdown loaded into the system prompt
├── api/main.py              # FastAPI REST API   (port 8013)
├── ui/app.py                # Flask web UI       (port 5013)
└── tests/                   # pytest: core, memory, service, chat, API, UI, CLIs, browser
```

### How the layers connect

```
 CLI ─┐
 API ─┼──► reading_list_chat ──► reading_list_service ──► reading_list_core   (pure logic)
 UI  ─┤          │                       │
tools ┘    Gemini tools              memory.ItemStore                         (persistence)
                                         │
                              subagents/reading_summarizer.py                 (separate process)
```

## Run

```bash
python -m pip install -r requirements.txt

# CLI
python reading_list_agent.py --chat
python reading_list_agent.py "add Attention is all you need https://arxiv.org/abs/1706.03762 #ml"
python reading_list_agent.py --offline "unread"

# Tools, subagent, memory (each prints one JSON object)
python tools/add_item.py --title "Attention is all you need" --url "https://arxiv.org/abs/1706.03762" --tags "ml"
python tools/search_items.py --query attention
python tools/mark_read.py --id item_ab12cd34ef
python tools/delete_item.py --id item_ab12cd34ef
python subagents/reading_summarizer.py --tag ml
python memory/memory.py stats

# API → http://127.0.0.1:8013/docs
python api/main.py

# UI → http://127.0.0.1:5013/ (chat at /chat)
python ui/app.py
```

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` / `GOOGLE_AI_STUDIO_KEY` | Enables LLM mode (otherwise offline) |
| `READING_LIST_AGENT_OFFLINE=1` | Force offline mode even when a key is set |
| `READING_LIST_AGENT_MODEL` | Override the model (default `gemini-3.8-flash`) |
| `READING_LIST_AGENT_DATA_DIR` | Store items somewhere other than `memory/data/` |
| `PORT` / `API_PORT` | UI / API port |
| `FLASK_SECRET` | Set a private session secret before using the UI beyond disposable local development |

Copy `.env.example` to `.env.local` for optional settings. Both files are
gitignored.

## Test

```bash
python -m playwright install chromium                       # once (optional, for browser tests)
python -m pytest -q --ignore=tests/test_browser.py          # offline, temp data
```

## Gotchas

- **No `from __future__ import annotations` in `reading_list_chat.py`.**
  google-genai validates tool arguments with `isinstance(value, annotation)`;
  string annotations break every tool call. `tests/test_chat.py` guards this.
- **Keep a reference to `genai.Client` while using it.** The SDK closes its
  HTTP connection when the client is garbage-collected, so chaining
  `get_client().chats.create(...).send_message(...)` can fail with
  "client has been closed".
