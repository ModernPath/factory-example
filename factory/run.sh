#!/usr/bin/env bash
# A small software factory: one issue file in, one reviewed draft pull request out.
#
#   bash factory/run.sh factory/issues/001-title-max-length.md
#
# Stages run headless agents with narrow permissions. Between stages this
# script runs the gates, which no model can talk its way past:
#
#   spec -> [spec gate] -> test -> [test gate] -> [RED gate] -> implement
#        -> [scope gate] -> [GREEN gate] -> review -> [verdict gate] -> PR
#
# Settings (environment):
#   FACTORY_BACKEND        claude (default) | codex | fake (tests only)
#   FACTORY_RUN_ID         run id; default the issue id. A new id starts a fresh run.
#   FACTORY_MAX_TURNS      agent turns per stage (claude), default 25
#   FACTORY_STAGE_TIMEOUT  seconds per stage, default 600
#   FACTORY_MAX_COST_USD   budget for the whole run (claude), default 3.00
#   FACTORY_PR             file (default): write pr.md | gh: open a draft PR
#   FACTORY_TEST_CMD       default: python3 -m pytest -q app/tests
#   FACTORY_BASE           branch to start from and diff against, default main
#
# Everything a run produces is in factory/runs/<run id>/: the log, the state
# file, each stage's agent output (<stage>.out.json), spec.md, gate outputs, review.json, pr.md or
# the PR url, and stop.md when the run stopped for a person.

set -uo pipefail

main() {
  ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "run.sh: not inside a git repository" >&2; exit 2; }
  cd "$ROOT" || exit 2

  ISSUE=${1:-}
  [ -n "$ISSUE" ] && [ -f "$ISSUE" ] || { echo "usage: bash factory/run.sh factory/issues/<nnn>-<slug>.md" >&2; exit 2; }
  ISSUE_ID=$(basename "$ISSUE" .md)
  RUN_ID=${FACTORY_RUN_ID:-$ISSUE_ID}
  RUN="factory/runs/$RUN_ID"
  BRANCH="factory/$RUN_ID"
  STATE="$RUN/state"
  BACKEND=${FACTORY_BACKEND:-claude}
  MAX_TURNS=${FACTORY_MAX_TURNS:-25}
  STAGE_TIMEOUT=${FACTORY_STAGE_TIMEOUT:-600}
  MAX_COST=${FACTORY_MAX_COST_USD:-3.00}
  PR_MODE=${FACTORY_PR:-file}
  TEST_CMD=${FACTORY_TEST_CMD:-python3 -m pytest -q app/tests}
  BASE=${FACTORY_BASE:-main}
  CURRENT_STAGE=start

  mkdir -p "$RUN"
  ORIG=$(git rev-parse --abbrev-ref HEAD)

  if [ -n "$(git status --porcelain)" ]; then
    echo "run.sh: the working tree has uncommitted changes; commit or stash them first." >&2
    exit 2
  fi

  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git switch -q "$BRANCH" || exit 2
    log "resume run=$RUN_ID branch=$BRANCH backend=$BACKEND"
  else
    git switch -q -c "$BRANCH" "$BASE" || exit 2
    log "start run=$RUN_ID issue=$ISSUE branch=$BRANCH backend=$BACKEND"
  fi
  trap 'on_interrupt' INT TERM

  stage_spec
  stage_test
  gate_red
  stage_implement
  stage_review
  stage_pr

  log "DONE run=$RUN_ID total_cost_usd=$(total_cost)"
  git switch -q "$ORIG"
}

# --------------------------------------------------------------------------- #
# Bookkeeping
# --------------------------------------------------------------------------- #

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$RUN/log"; }

is_done() { grep -q "^$1 " "$STATE" 2>/dev/null; }

mark_done() { echo "$1 $(git rev-parse --short HEAD) $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATE"; }

skip_if_done() {
  if is_done "$1"; then log "skip $1 (done in an earlier run)"; return 0; fi
  CURRENT_STAGE=$1
  return 1
}

total_cost() { awk '{s += $1} END {printf "%.4f", s + 0}' "$RUN/costs" 2>/dev/null || echo 0; }

# Uncommitted agent work from a stage that did not pass is kept as a patch in
# the run directory and removed from the branch, so a rerun starts that stage
# clean and nothing half-done can follow anyone back to their own branch.
set_aside_uncommitted() {
  if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git diff --cached > "$RUN/rejected-$CURRENT_STAGE.patch"
    git reset -q --hard HEAD
    log "set aside uncommitted changes from $CURRENT_STAGE in $RUN/rejected-$CURRENT_STAGE.patch"
  fi
}

stop() {  # $1 stage, $2 reason, $3 decision a person must make
  log "STOP $1: $2"
  set_aside_uncommitted
  {
    echo "# STOP $(date -u +%Y-%m-%dT%H:%M:%SZ) run=$RUN_ID stage=$1"
    echo
    echo "**Reason:** $2"
    echo
    echo "**Completed stages:**"
    if [ -s "$STATE" ]; then sed 's/^\([^ ]*\) \([^ ]*\) \(.*\)$/- \1 at commit \2 (\3)/' "$STATE"; else echo "- none"; fi
    echo
    echo "**Decision needed:** $3"
    echo
    echo "Branch \`$BRANCH\`, log \`$RUN/log\`, cost so far \$$(total_cost)."
  } > "$RUN/stop.md"
  git switch -q "$ORIG" 2>/dev/null
  exit 1
}

on_interrupt() {
  log "interrupted during $CURRENT_STAGE"
  set_aside_uncommitted
  git switch -q "$ORIG" 2>/dev/null
  log "rerun the same command to continue from $CURRENT_STAGE"
  exit 130
}

with_timeout() {  # portable: GNU timeout, Homebrew gtimeout, or perl's alarm
  if command -v timeout >/dev/null 2>&1; then timeout "$STAGE_TIMEOUT" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$STAGE_TIMEOUT" "$@"
  else perl -e 'alarm shift; exec @ARGV' "$STAGE_TIMEOUT" "$@"
  fi
}

json_field() {  # $1 file, $2 field: print a top-level field of a JSON object
  python3 -c 'import json,sys
try: v = json.load(open(sys.argv[1])).get(sys.argv[2], "")
except Exception: v = ""
print("" if v is None else v)' "$1" "$2"
}

# --------------------------------------------------------------------------- #
# Running one headless agent
# --------------------------------------------------------------------------- #

run_stage() {  # $1 stage, $2 allowed tools (claude), $3 read|write (codex sandbox)
  local stage=$1 tools=$2 access=$3 out="$RUN/$1.out.json" rc start remaining prompt
  remaining=$(awk -v max="$MAX_COST" -v used="$(total_cost)" 'BEGIN {printf "%.4f", max - used}')
  if awk -v r="$remaining" 'BEGIN {exit !(r <= 0)}'; then
    stop "$stage" "run budget of \$$MAX_COST is used up" "Raise FACTORY_MAX_COST_USD for this run, or split the issue."
  fi
  prompt="$(cat "factory/prompts/$stage.md")

Issue file: $ISSUE
Run directory: $RUN"
  start=$(date +%s)

  case "$BACKEND" in
    claude)
      # --setting-sources project and --strict-mcp-config keep personal hooks,
      # settings and MCP servers out of the run: only this repo's settings apply.
      with_timeout claude -p "$prompt" \
        --allowedTools "$tools" \
        --output-format json \
        --max-turns "$MAX_TURNS" \
        --max-budget-usd "$remaining" \
        --setting-sources project \
        --strict-mcp-config \
        > "$out" 2> "$RUN/$stage.err"
      rc=$?
      ;;
    codex)
      # Codex has no per-tool allowlist; the sandbox is its permission boundary.
      local sandbox=workspace-write
      [ "$access" = read ] && sandbox=read-only
      with_timeout codex exec --sandbox "$sandbox" --ephemeral -o "$RUN/$stage.txt" "$prompt" \
        > "$RUN/$stage.jsonl" 2> "$RUN/$stage.err"
      rc=$?
      python3 -c 'import json,sys,pathlib
p = pathlib.Path(sys.argv[1]); rc = int(sys.argv[2])
text = p.read_text() if p.exists() else ""
json.dump({"subtype": "success" if rc == 0 else "error", "is_error": rc != 0, "result": text,
           "num_turns": None, "total_cost_usd": None}, open(sys.argv[3], "w"))' "$RUN/$stage.txt" "$rc" "$out"
      ;;
    fake)
      FACTORY_STAGE=$stage FACTORY_RUN=$RUN with_timeout python3 "$FACTORY_FAKE_AGENT" "$prompt" > "$out" 2> "$RUN/$stage.err"
      rc=$?
      ;;
    *)
      stop "$stage" "unknown FACTORY_BACKEND=$BACKEND" "Use claude or codex."
      ;;
  esac

  local secs=$(( $(date +%s) - start ))
  if [ "$rc" -eq 124 ] || [ "$rc" -eq 142 ]; then
    stop "$stage" "agent timed out after ${STAGE_TIMEOUT}s" "Look at $out and $RUN/$stage.err; raise FACTORY_STAGE_TIMEOUT or simplify the issue."
  fi
  local subtype turns cost is_error
  subtype=$(json_field "$out" subtype)
  turns=$(json_field "$out" num_turns)
  cost=$(json_field "$out" total_cost_usd)
  is_error=$(json_field "$out" is_error)
  [ -n "$cost" ] && echo "$cost" >> "$RUN/costs"
  log "stage=$stage exit=$rc subtype=${subtype:-?} turns=${turns:-n/a} cost_usd=${cost:-n/a} seconds=$secs"
  if [ "$rc" -ne 0 ] || [ "$is_error" = "True" ] || [ "$subtype" != "success" ]; then
    stop "$stage" "agent ended with ${subtype:-exit $rc}" "Read $out and $RUN/$stage.err, then rerun to retry this stage."
  fi
}

changed_files() { git status --porcelain --untracked-files=all | sed 's/^...//'; }

run_tests() { bash -c "$TEST_CMD" > "$1" 2>&1; }

# --------------------------------------------------------------------------- #
# Stages and gates
# --------------------------------------------------------------------------- #

stage_spec() {
  skip_if_done spec && return
  run_stage spec "Read,Grep,Glob,Write" write
  local spec="$RUN/spec.md"
  [ -s "$spec" ] || stop spec "spec.md is missing" "Read $RUN/spec.out.json: did the agent misread the prompt or the issue?"
  if grep -q '^BLOCKED:' "$spec"; then
    stop spec "the spec stage could not proceed: $(grep '^BLOCKED:' "$spec" | head -1)" "Answer the question in the issue file and rerun on a new run id."
  fi
  grep -qE '^1\. ' "$spec" || stop spec "spec.md has no numbered acceptance criteria" "Sharpen the issue's acceptance check."
  TEST_NAME=$(sed -n 's/^Test: app\/tests\/test_tasks\.py::\(test_[A-Za-z0-9_]*\).*/\1/p' "$spec" | head -1)
  [ -n "$TEST_NAME" ] || stop spec "spec.md names no test as 'Test: app/tests/test_tasks.py::<name>'" "Check prompts/spec.md and rerun."
  [ -z "$(changed_files)" ] || stop spec "the spec stage changed repository files: $(changed_files | tr '\n' ' ')" "Tighten the spec stage's permissions or prompt."
  mark_done spec
}

test_name() { sed -n 's/^Test: app\/tests\/test_tasks\.py::\(test_[A-Za-z0-9_]*\).*/\1/p' "$RUN/spec.md" | head -1; }

stage_test() {
  skip_if_done test && return
  local name; name=$(test_name)
  run_stage test "Read,Grep,Glob,Edit,Write" write
  local files outside added removed
  files=$(changed_files)
  [ -n "$files" ] || stop test "the test stage changed nothing" "Read $RUN/test.out.json."
  outside=$(printf '%s\n' "$files" | grep -v '^app/tests/' || true)
  [ -z "$outside" ] || stop test "the test stage changed files outside app/tests/: $(echo $outside)" "Tighten prompts/test.md; nothing outside the tests may change here."
  git add -A app/tests
  added=$(git diff --cached -U0 -- app/tests | grep -cE '^\+def test_' || true)
  removed=$(git diff --cached -U0 -- app/tests | grep -E '^-' | grep -vcE '^--- ' || true)
  [ "$added" -eq 1 ] || stop test "expected exactly one new test, found $added" "Check prompts/test.md and the spec's Test line."
  [ "$removed" -eq 0 ] || stop test "the test stage changed or deleted existing test lines" "Existing tests are not the test stage's to edit."
  git diff --cached -U0 -- app/tests | grep -qE "^\+def $name\(" || stop test "the new test is not named $name as the spec requires" "Rerun; the name links the test to its spec."
  git commit -q -m "factory($RUN_ID): test $name" || stop test "commit failed" "Check git status on $BRANCH."
  mark_done test
}

gate_red() {
  skip_if_done red && return
  local name; name=$(test_name)
  if run_tests "$RUN/red.txt"; then
    stop red-gate "the new test $name passed before implementation" \
      "Close the issue if the behaviour already exists, or sharpen its acceptance check so the test can fail."
  fi
  grep -q "$name" "$RUN/red.txt" || stop red-gate "the suite fails, but not because of $name" \
    "Fix the existing failure on $BASE first; see $RUN/red.txt."
  log "RED gate: $name fails as expected"
  mark_done red
}

stage_implement() {
  skip_if_done implement && return
  run_stage implement "Read,Grep,Glob,Edit,Write,Bash(python3 -m pytest:*)" write
  local files forbidden
  files=$(changed_files)
  [ -n "$files" ] || stop implement "the implement stage changed nothing" "Read $RUN/implement.out.json."
  # Allowed: files under app/ except app/tests/. Everything else is out of bounds.
  forbidden=$( { printf '%s\n' "$files" | grep -vE '^app/'; printf '%s\n' "$files" | grep -E '^app/tests/'; } | sed '/^$/d' )
  [ -z "$forbidden" ] || stop implement "the implementer touched files it may not change: $(echo $forbidden)" \
    "Tests and factory/ are off limits to the implement stage. Rerun; if it repeats, tighten prompts/implement.md."
  if ! run_tests "$RUN/green.txt"; then
    stop green-gate "the suite fails after implementation" "See $RUN/green.txt. Rerun to retry the implement stage."
  fi
  log "GREEN gate: suite passes"
  git add -A app
  git commit -q -m "factory($RUN_ID): implement $(test_name)" || stop implement "commit failed" "Check git status on $BRANCH."
  mark_done implement
}

stage_review() {
  skip_if_done review && return
  git diff "$BASE"...HEAD > "$RUN/diff.patch"
  run_stage review "Read,Grep,Glob" read
  # The reviewer stays read-only: it answers with JSON, and this script checks and saves it.
  if ! python3 -c 'import json,re,sys
result = json.load(open(sys.argv[1])).get("result") or ""
open(sys.argv[2], "w").write(result)
match = re.search(r"\{.*\}", result, re.S)
try: data = json.loads(match.group(0)) if match else None
except json.JSONDecodeError: data = None
ok = isinstance(data, dict) and data.get("verdict") in ("approve", "changes") and isinstance(data.get("findings"), list)
if not ok: sys.exit(1)
json.dump({"verdict": data["verdict"], "findings": data["findings"]}, open(sys.argv[3], "w"), indent=2)' \
    "$RUN/review.out.json" "$RUN/review.txt" "$RUN/review.json"; then
    stop review "the reviewer returned no valid verdict" "Read $RUN/review.txt. Rerun to retry the review."
  fi
  if [ "$(json_field "$RUN/review.json" verdict)" != "approve" ]; then
    stop verdict-gate "the reviewer asked for changes: $(python3 -c 'import json,sys; print("; ".join(json.load(open(sys.argv[1]))["findings"]))' "$RUN/review.json")" \
      "Decide whether the findings are right. If so, fix them on $BRANCH by hand or rerun from implement on a new run id."
  fi
  log "verdict gate: approve"
  mark_done review
}

stage_pr() {
  skip_if_done pr && return
  local title body="$RUN/pr.md"
  title=$(head -1 "$ISSUE" | sed 's/^# *//')
  {
    echo "Factory run \`$RUN_ID\` for \`$ISSUE\`. **Draft: a person decides whether to merge.**"
    echo
    echo "## Acceptance criteria"
    sed -n '/^1\. /,/^$/p' "$RUN/spec.md"
    echo
    echo "## Evidence"
    echo "- RED: \`$(test_name)\` failed before implementation ($RUN/red.txt)"
    echo "- GREEN: \`$TEST_CMD\` → $(tail -1 "$RUN/green.txt")"
    echo "- Review: approve$(python3 -c 'import json,sys; f=json.load(open(sys.argv[1]))["findings"]; print(", findings: " + "; ".join(f) if f else ", no findings")' "$RUN/review.json")"
    echo "- Cost: \$$(total_cost) across all stages"
    echo
    echo "Log and stage outputs: \`$RUN/\`."
  } > "$body"

  if [ "$PR_MODE" = gh ]; then
    local url
    git push -q -u origin "$BRANCH" || stop pr "git push failed" "Check the remote and your credentials."
    url=$(gh pr list --head "$BRANCH" --state open --json url -q '.[0].url' 2>/dev/null)
    if [ -n "$url" ]; then
      log "PR already open for $BRANCH: $url"
    else
      url=$(gh pr create --draft --base "$BASE" --head "$BRANCH" --title "$title" --body-file "$body") \
        || stop pr "gh pr create failed" "Open the PR by hand from $body."
      log "draft PR opened: $url"
    fi
    echo "$url" > "$RUN/pr_url"
  else
    log "wrote $body (FACTORY_PR=gh opens a draft PR instead)"
  fi
  mark_done pr
}

main "$@"
