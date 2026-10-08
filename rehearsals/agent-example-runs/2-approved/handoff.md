# reading-list-agent: ready for a person

Built by the agent factory in `../agent-example/reading-list-agent`, from the contract in `spec.json`.
Nothing is committed: the folder is untracked in the agent kit.

## What the factory checked

- The tests were written first, failed before the build (`red.txt`) and were
  not changed afterwards.
- Offline test suite passes without a provider key, against a temporary data dir.
- The reference's structure is kept, with no `example_`/note names, `.env`
  files or data files left in the folder.
- `reading_list_agent.py --help`, the offline CLI, one `--help` per tool
  (add_item, search_items, mark_read, delete_item), the API health check and the UI home page start and answer.
- An independent, read-only review approved it on build attempt 1.

Review notes:

- none

## What a person still does (agent kit AGENTS.md, steps 6 and 7)

1. Read `README.md`: is this the contract you meant?
2. Run the browser tests: `pip install playwright && playwright install chromium`,
   then `python -m pytest tests/test_browser.py`.
3. Use the UI and chat in a real browser, with and without a provider key.
4. Commit the folder in the agent kit and add it to the "Registered agents"
   table in `AGENTS.md`. Or delete it.

Agent cost for this run: $13.41.
