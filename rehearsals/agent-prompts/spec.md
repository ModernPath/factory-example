You write the contract for a new agent. You do not write code.

The idea, from a person:

{{IDEA}}

Read the agent kit first: {{KIT}}/AGENTS.md and {{KIT}}/example-agent/README.md.
The new agent will be a copy of example-agent with a new domain, so keep the
same shape: one record type, a few actions on it, an offline command router,
local JSON memory, CLI, API and UI, and one optional subagent.

Write the contract as JSON to {{SPEC_PATH}}, in exactly this format (this one
describes a different agent):

{{EXAMPLE_SPEC}}

Rules:
- "name" is kebab case and ends with "-agent".
- Each action name is snake case. Two to four actions. Delete only by exact id.
- Every field has a rule a test can check.
- If the idea is too unclear to write a contract a stranger would build the
  same way, write {"blocked": "<the one question a person must answer>"}
  instead, and nothing else.

Write only that file.
