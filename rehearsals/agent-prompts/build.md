You build a new agent so that its tests pass. Attempt {{ATTEMPT}} of {{MAX_ATTEMPTS}}.

The contract:

{{SPEC}}

The agent folder {{AGENT_DIR}} started as a copy of the notes reference
(example-agent). Its tests/ folder already describes the new agent and is
frozen: if you change any file under tests/, the factory stops and throws the
run away. Read the agent kit's rules at the end of this prompt, then the
tests, then the copied code.

Turn the copy into the agent the contract and tests describe, keeping the
reference's architecture:
- rename example_core.py, example_service.py, example_chat.py and
  example_agent.py to {{BASE}}_core.py, {{BASE}}_service.py, {{BASE}}_chat.py
  and {{BASE}}_agent.py, and EXAMPLE_AGENT_* settings to {{PREFIX}}_*;
- replace the note model, store, schema, tools, skills, subagent, API routes,
  UI pages and offline router with the contract's record and actions;
  one tool CLI per action: {{TOOLS}}, each printing the agent_cli.py JSON envelope;
- rewrite README.md as the agent's contract: purpose, inputs, outputs,
  permissions, side effects, offline behaviour, memory retention, surfaces;
- keep .env.example with commented names only. No secrets, no data files.

Change files only inside {{AGENT_DIR}}, and not under tests/. Use mv to rename
files. You cannot delete files: to remove one (an old reference file with no
new counterpart, say), write its path relative to the agent folder on its own
line in {{AGENT_DIR}}/.factory-remove, and the factory deletes it after you
finish. Do not empty a file instead: a reference file left behind fails the
checks whatever it contains. Run the tests with:
  {{TEST_CMD}}

{{FAILURES}}

Say in one line what you built.

---

The agent kit's rules ({{KIT}}/AGENTS.md):

{{KIT_RULES}}
