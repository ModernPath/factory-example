You write the tests for a new agent before it exists. You do not write the agent.

The contract:

{{SPEC}}

The agent folder {{AGENT_DIR}} is an unchanged copy of the notes reference
(example-agent). Its tests/ folder still tests notes. Replace those tests with
tests for the contract above. Read the agent kit's rules at the end of this
prompt and the copied tests first, and keep their structure: conftest.py, test_core.py, test_memory_and_service.py,
test_cli.py, test_api.py, test_ui.py, test_chat.py, test_startup.py and
test_browser.py.

The agent will be built with these names, so import them exactly:
- modules {{BASE}}_core, {{BASE}}_service, {{BASE}}_chat, {{BASE}}_agent (the CLI)
- environment variables {{PREFIX}}_OFFLINE, {{PREFIX}}_DATA_DIR, {{PREFIX}}_MODEL
- one tool CLI per action: {{TOOLS}}

Rules:
- Change files only inside {{AGENT_DIR}}/tests/. Delete the notes tests you
  replace.
- conftest.py must force offline mode with {{PREFIX}}_OFFLINE=1 and a temporary
  {{PREFIX}}_DATA_DIR for every test, as the copied one does. No test may call a
  real model.
- Every action name must appear in the tests, and every field rule in the
  contract needs at least one assertion.
- These tests must fail now, because the agent does not exist yet. Check with:
  {{TEST_CMD}}
  A failure because a module is missing is expected. A syntax error in a test
  is not.

Say in one line what you tested.

---

The agent kit's rules ({{KIT}}/AGENTS.md):

{{KIT_RULES}}
