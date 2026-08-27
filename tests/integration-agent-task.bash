#!/usr/bin/env bash
set -euo pipefail
ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT
BIN="$ROOT/bin"; mkdir "$BIN"; STATE="$ROOT/systemd"; mkdir "$STATE"
export STATE
cat >"$BIN/systemd-run" <<'EOF'
#!/usr/bin/env bash
set -e
for x in "$@"; do [[ "$x" == --unit=* ]] && unit="${x#--unit=}"; done
runner="${!#}"; "$runner" & echo $! >"$STATE/$unit.pid"; echo active >"$STATE/$unit.state"
EOF
cat >"$BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
set -e
unit="${@: -1}"; unit="${unit%.service}"
case "${@: -2:1}" in
  is-active) [[ -s "$STATE/$unit.state" ]] && cat "$STATE/$unit.state" || echo inactive ;;
  show) cat "$STATE/$unit.pid" 2>/dev/null || echo 0 ;;
  stop) echo inactive >"$STATE/$unit.state"; kill "$(cat "$STATE/$unit.pid")" 2>/dev/null || true ;;
  kill-service) kill "$(cat "$STATE/$unit.pid")" 2>/dev/null || true ; echo inactive >"$STATE/$unit.state" ;;
  *) exit 0;;
esac
EOF
chmod +x "$BIN"/*
export PATH="$BIN:$PATH" AGENT_WORKSTATION_ROOT="$ROOT/ws"
REPO="$ROOT/repo"; git init -q "$REPO"; git -C "$REPO" config user.email test@example.com; git -C "$REPO" config user.name test; echo base >"$REPO/file"; git -C "$REPO" add file; git -C "$REPO" commit -qm base
PROMPT="$ROOT/prompt"; echo test >"$PROMPT"
run="$ROOT/agent-task"; cp "$(dirname "$0")/../bin/agent-task" "$run"; chmod +x "$run"
WT1="$ROOT/wt1"; WT2="$ROOT/wt2"; WT3="$ROOT/wt3"; WT4="$ROOT/wt4"; WT5="$ROOT/wt5"; WT6="$ROOT/wt6"; WT7="$ROOT/wt7"; WT8="$ROOT/wt8"; git -C "$REPO" worktree add -qb one "$WT1"; git -C "$REPO" worktree add -qb two "$WT2"; git -C "$REPO" worktree add -qb three "$WT3"; git -C "$REPO" worktree add -qb four "$WT4"; git -C "$REPO" worktree add -qb five "$WT5"; git -C "$REPO" worktree add -qb six "$WT6"; git -C "$REPO" worktree add -qb seven "$WT7"; git -C "$REPO" worktree add -qb eight "$WT8"
"$run" attach --project p --issue FLOW-ATTACH --worktree "$WT1" --repo "$REPO" >/dev/null
head_before=$(git -C "$WT1" rev-parse HEAD); branch_before=$(git -C "$WT1" branch --show-current); echo diff >>"$WT1/file"
"$run" attach --project p --issue FLOW-ATTACH --worktree "$WT1" --repo "$REPO" >/dev/null
[[ "$head_before" == "$(git -C "$WT1" rev-parse HEAD)" && "$branch_before" == "$(git -C "$WT1" branch --show-current)" && -n "$(git -C "$WT1" diff)" ]]
! "$run" attach --project p --issue FLOW-OTHER --worktree "$WT1" --repo "$REPO" 2>/dev/null
git -C "$WT1" checkout -q -- file
missing_origin_err=$("$run" attach --project p --issue FLOW-NO-ORIGIN --worktree "$WT4" 2>&1 >/dev/null || true)
[[ "$missing_origin_err" == *'no origin URL'* ]]
"$run" attach --project p --issue FLOW-DONE --worktree "$WT4" --repo "$REPO" >/dev/null
"$run" start --issue FLOW-DONE --prompt-file "$PROMPT" --agent smoke >/dev/null
json=$("$run" wait --issue FLOW-DONE --timeout-seconds 10 --json); python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["state"]=="COMPLETED"; assert set(("state","issue","agent","service","wrapper_pid","wrapper_alive","child_pid","child_alive","started_at","max_minutes","run_dir","exit_code","heartbeat","worktree","branch","head","dirty")) <= d.keys()' "$json"
run_dir=$(python3 -c 'import json,sys;print(json.load(sys.stdin)["run_dir"])' <<<"$json"); python3 -m json.tool "$run_dir/result.json" >/dev/null
[[ -f "$run_dir/result.json" ]]
natural_run_dir=$(find "$ROOT/ws/artifacts/FLOW-DONE/runs" -mindepth 1 -maxdepth 1 -type d | head -1)
python3 - "$natural_run_dir/result.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1])); assert d['state']=='COMPLETED'; assert d['service']=='inactive'; assert d['wrapper_alive'] is False; assert d['child_alive'] is False
assert isinstance(d['max_minutes'], int) and isinstance(d['dirty'], bool) and isinstance(d['wrapper_pid'], int)
PY
grep -q 'HEARTBEAT_INTERVAL=.*:-15' "$natural_run_dir/runner.sh"
"$run" attach --project p --issue FLOW-CODEX --worktree "$WT2" --repo "$REPO" >/dev/null
cat >"$BIN/codex" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$CODEX_ARGS"; exit 0
EOF
chmod +x "$BIN/codex"; export CODEX_ARGS="$ROOT/codex.args"
"$run" start --issue FLOW-CODEX --prompt-file "$PROMPT" --agent codex >/dev/null; "$run" wait --issue FLOW-CODEX --timeout-seconds 10 >/dev/null
grep -q -- '--model gpt-5.6-luna' "$CODEX_ARGS"
"$run" attach --project p --issue FLOW-CODEX-OVERRIDE --worktree "$WT5" --repo "$REPO" >/dev/null; "$run" start --issue FLOW-CODEX-OVERRIDE --prompt-file "$PROMPT" --agent codex --model test-model >/dev/null; "$run" wait --issue FLOW-CODEX-OVERRIDE --timeout-seconds 10 >/dev/null; grep -q -- '--model test-model' "$CODEX_ARGS"
"$run" attach --project p --issue FLOW-LOST --worktree "$WT6" --repo "$REPO" >/dev/null; "$run" start --issue FLOW-LOST --prompt-file "$PROMPT" --agent smoke >/dev/null; "$BIN/systemctl" --user kill-service agent-task-flow-lost.service; sleep .1; lost=$("$run" status --issue FLOW-LOST --json 2>/dev/null||true); [[ "$lost" == *'"state":"LOST"'* ]]
"$run" attach --project p --issue FLOW-STOP --worktree "$WT3" --repo "$REPO" >/dev/null; "$run" start --issue FLOW-STOP --prompt-file "$PROMPT" --agent smoke >/dev/null
( ! "$run" start --issue FLOW-STOP --prompt-file "$PROMPT" --agent smoke >/dev/null 2>&1 )
(sleep .1; "$run" stop --issue FLOW-STOP >/dev/null) & stopper=$!
for _ in {1..20}; do out=$("$run" status --issue FLOW-STOP --json 2>/dev/null||true); [[ -z "$out" ]]||{ [[ "$(python3 -c 'import json,sys;print(json.load(sys.stdin)["state"])' <<<"$out")" != LOST ]]||exit 1; }; sleep .02; done; wait "$stopper"; [[ "$("$run" status --issue FLOW-STOP --json 2>/dev/null||true)" == *STOPPED* ]]
stop_run_dir=$(find "$ROOT/ws/artifacts/FLOW-STOP/runs" -mindepth 1 -maxdepth 1 -type d | head -1)
python3 - "$stop_run_dir/result.json" <<'PY'
import json, sys
d=json.load(open(sys.argv[1])); assert d['state']=='STOPPED'; assert d['service']=='inactive'; assert d['wrapper_alive'] is False; assert d['child_alive'] is False
PY

"$run" attach --project p --issue FLOW-FAIL --worktree "$WT7" --repo "$REPO" >/dev/null
cat >"$BIN/claude" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
chmod +x "$BIN/claude"
"$run" start --issue FLOW-FAIL --prompt-file "$PROMPT" --agent claude >/dev/null || true
set +e
failed_json=$("$run" wait --issue FLOW-FAIL --timeout-seconds 10 --json); failed_rc=$?
set -e
[[ "$failed_rc" -ne 0 ]]
python3 - "$failed_json" <<'PY'
import json, sys
d=json.loads(sys.argv[1]); assert d['state']=='FAILED'; assert isinstance(d['exit_code'], int)
PY

"$run" attach --project p --issue FLOW-TIMEOUT --worktree "$WT8" --repo "$REPO" >/dev/null
cat >"$BIN/claude" <<'EOF'
#!/usr/bin/env bash
exit 124
EOF
chmod +x "$BIN/claude"
AGENT_TASK_HEARTBEAT_INTERVAL=1 "$run" start --issue FLOW-TIMEOUT --prompt-file "$PROMPT" --agent claude --max-minutes 1 >/dev/null || true
set +e
timeout_json=$(AGENT_TASK_HEARTBEAT_INTERVAL=1 "$run" wait --issue FLOW-TIMEOUT --timeout-seconds 70 --json); timeout_rc=$?
set -e
[[ "$timeout_rc" -ne 0 ]]
python3 - "$timeout_json" <<'PY'
import json, sys
d=json.loads(sys.argv[1]); assert d['state']=='TIMED_OUT'; assert d['service']=='inactive'; assert d['wrapper_alive'] is False
PY

missing_old_err=$("$run" attach --project p --issue FLOW-DONE --worktree "$ROOT/does-not-exist" --repo "$REPO" 2>&1 >/dev/null || true)
[[ "$missing_old_err" == *'does not exist'* ]]
echo 'integration-agent-task: PASS'
