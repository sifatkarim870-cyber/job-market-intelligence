#!/usr/bin/env bash
# Behavioural tests for the "Alert on sustained Indeed blocks" step in
# .github/workflows/scrape.yml.
#
# Why a shell harness for a shell step: the logic that decides whether CI goes
# red lives entirely in this bash, so unit-testing the Python that surrounds it
# would test nothing. The step's script is *extracted from the workflow* rather
# than copied here, so this cannot drift from what CI actually runs.
#
# This exists because writing it found three real bugs: the step read the
# counter with a bare `python3` (unverified on this runner, and a failure there
# silently resets the count to 0 every run, permanently disarming the
# alerting), it exited before persisting the incremented count (so the reported
# streak froze), and it conflated a run that collected jobs before being
# challenged with a run that collected nothing.
#
# Run directly (needs bash and an interpreter with PyYAML), or via
# tests/workflow/test_indeed_block_alerting.py, which skips without bash.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PY:-python}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

cd "$REPO_ROOT" || exit 1

"$PY" - "$WORK/step.sh" "$PY" <<'PYEOF'
import sys, yaml
d = yaml.safe_load(open('.github/workflows/scrape.yml', encoding='utf-8'))
for step in d['jobs']['indeed']['steps']:
    if step.get('name') == 'Alert on sustained Indeed blocks':
        script = step['run']
        # The step hardcodes .venv/bin/python relative to the checkout; this
        # harness runs it from a temp dir, so point it at the nominated
        # interpreter.
        #
        # Forward slashes only: on Windows the caller may hand us a path like
        # C:\...\python.exe, and bash would eat those backslashes as escapes,
        # leaving a command that does not exist.
        script = script.replace('.venv/bin/python', sys.argv[2].replace('\\', '/'))
        open(sys.argv[1], 'w', encoding='utf-8').write(script)
        sys.exit(0)
sys.exit('alert step not found in scrape.yml')
PYEOF

# GitHub expands ${{ github.run_number }} before bash sees it.
sed -i 's/${{ github.run_number }}/7/g' "$WORK/step.sh"

pass=0; fail=0

# run_case <label> <previous_count|absent> <outcome|absent> <want_count> <want_exit>
run_case() {
  label="$1"; prev="$2"; outcome="$3"; want_count="$4"; want_exit="$5"
  dir="$WORK/case"; rm -rf "$dir"; mkdir -p "$dir"

  [ "$prev" = "absent" ] || printf '{"consecutive_blocks": %s}\n' "$prev" > "$dir/indeed_block_state.json"
  [ "$outcome" = "absent" ] || printf '{"outcome": "%s"}\n' "$outcome" > "$dir/indeed_run_summary.json"

  out=$(cd "$dir" && RUNNER_TEMP="$dir" BLOCK_THRESHOLD=3 bash "$WORK/step.sh" 2>&1)
  got_exit=$?

  if [ -f "$dir/indeed_block_state.json" ]; then
    got_count=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['consecutive_blocks'])" "$dir/indeed_block_state.json" 2>/dev/null || echo ERR)
  else
    got_count=NOSTATE
  fi

  if [ "$got_count" = "$want_count" ] && [ "$got_exit" = "$want_exit" ]; then
    pass=$((pass + 1)); printf '  ok   %-46s count=%s exit=%s\n' "$label" "$got_count" "$got_exit"
  else
    fail=$((fail + 1))
    printf '  FAIL %-46s count=%s exit=%s (wanted %s / %s)\n' "$label" "$got_count" "$got_exit" "$want_count" "$want_exit"
    printf '%s\n' "$out" | sed 's/^/         | /'
  fi
}

# run_annotation_case <outcome> <expected_annotation_substring|absent>
run_annotation_case() {
  outcome="$1"; want="$2"
  dir="$WORK/ann"; rm -rf "$dir"; mkdir -p "$dir"
  printf '{"consecutive_blocks": 0}\n' > "$dir/indeed_block_state.json"
  printf '{"outcome": "%s"}\n' "$outcome" > "$dir/indeed_run_summary.json"
  msg=$(cd "$dir" && RUNNER_TEMP="$dir" BLOCK_THRESHOLD=3 bash "$WORK/step.sh" 2>&1)

  if [ "$want" = "absent" ]; then
    if printf '%s' "$msg" | grep -q '::warning\|::error'; then
      fail=$((fail + 1)); printf '  FAIL %-46s emitted an annotation, wanted none\n' "$outcome"
    else
      pass=$((pass + 1)); printf '  ok   %-46s no annotation\n' "$outcome"
    fi
  elif printf '%s' "$msg" | grep -qF "$want"; then
    pass=$((pass + 1)); printf '  ok   %-46s %s\n' "$outcome" "$want"
  else
    fail=$((fail + 1)); printf '  FAIL %-46s wanted %s\n' "$outcome" "$want"
  fi
}

# run_unreadable_case: a state file that exists but is not valid JSON must warn
# rather than silently behaving like a fresh counter.
run_unreadable_case() {
  dir="$WORK/bad"; rm -rf "$dir"; mkdir -p "$dir"
  printf 'not json at all\n' > "$dir/indeed_block_state.json"
  printf '{"outcome": "blocked"}\n' > "$dir/indeed_run_summary.json"
  msg=$(cd "$dir" && RUNNER_TEMP="$dir" BLOCK_THRESHOLD=3 bash "$WORK/step.sh" 2>&1)
  if printf '%s' "$msg" | grep -qF '::warning title=Indeed block counter unreadable::'; then
    pass=$((pass + 1)); printf '  ok   %-46s warned\n' "corrupt state file is reported"
  else
    fail=$((fail + 1)); printf '  FAIL %-46s corrupt state file was absorbed silently\n' "corrupt state file"
    printf '%s\n' "$msg" | sed 's/^/         | /'
  fi
}

echo "counter transitions (threshold=3):"
run_case "first block, nothing before"          absent  blocked  1 0
run_case "second block, streak=1"               1       blocked  2 0
run_case "third block -> job fails"             2       blocked  3 1
run_case "fourth block, streak keeps growing"   3       blocked  4 1
run_case "ok resets the streak"                 2       ok       0 0
run_case "partial resets the streak"            2       partial  0 0
run_case "empty leaves the streak alone"        2       empty    2 0
run_case "unknown leaves the streak alone"      2       unknown  2 0
run_case "missing summary leaves it alone"      2       absent   2 0
run_case "absent state + ok"                    absent  ok       0 0
run_case "absent state + blocked"               absent  blocked  1 0
run_case "streak survives an intervening empty" 1       empty    1 0

echo
echo "annotations per outcome:"
run_annotation_case blocked "::warning title=Indeed blocked::"
run_annotation_case partial "::warning title=Indeed partial::"
run_annotation_case unknown "::warning title=Indeed outcome unknown::"
run_annotation_case ok       absent
run_annotation_case empty    absent

echo
echo "robustness:"
run_unreadable_case

echo
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
