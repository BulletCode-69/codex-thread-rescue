#!/bin/bash
# codex_thread_touch.sh — re-register hidden threads in the Codex Desktop sidebar
# by "touching" each one via `codex exec resume` (non-interactive, one trivial turn).
#
# Why this works: the sidebar/search show a bounded window of recently
# active threads. New activity through the app/CLI puts a thread back into
# the window, persistently. Editing local state files does NOT do this.
#
# ZERO-SUM CAVEAT: the window is bounded. Touching a long list works, but
# earlier touches get pushed out of view by later ones — expect only the
# tail of the list to remain visible. For day-to-day use, prefer
# codex_thread_recall.sh on the specific thread you need.
# See docs/PERSISTENCE.md.
#
# Usage:
#   bash scripts/codex_thread_touch.sh ids.txt
#     ids.txt: one thread id per line.
#   Progress is checkpointed in ids.txt.done — Ctrl+C anytime and rerun to resume.
#   Failures are listed in ids.txt.failed (rerun retries them only if you
#   delete them from .done / keep them out of it — failed ids are not marked done).
#
# Env:
#   CODEX_BIN     path to the codex CLI (default: auto-detect inside Codex.app)
#   TOUCH_WAIT    seconds to sleep between touches (default 2)
#   TOUCH_PROMPT  override the prompt sent to the model (default: Japanese "OK" prompt)

set -u
IDS="${1:?usage: codex_thread_touch.sh ids.txt}"
BIN="${CODEX_BIN:-$(find /Applications/Codex.app -type f -name 'codex*' -perm -u+x 2>/dev/null | head -1)}"
[ -n "$BIN" ] && [ -x "$BIN" ] || { echo "error: codex CLI not found; set CODEX_BIN" >&2; exit 1; }
DONE="$IDS.done"; FAIL="$IDS.failed"
touch "$DONE"
PROMPT="${TOUCH_PROMPT:-これはサイドバー再登録のためのタッチです。何も作業せず「OK」とだけ返答してください。}"
TO=$(command -v gtimeout || true)
total=$(grep -c . "$IDS"); n=0; ok=0; ng=0
while IFS= read -r id; do
  id="${id//$'\r'/}"; [ -z "$id" ] && continue
  n=$((n+1))
  if grep -q "^$id$" "$DONE"; then echo "[$n/$total] skip (done)  $id"; continue; fi
  printf '[%d/%d] touch %s ... ' "$n" "$total" "$id"
  if ${TO:+$TO 180} "$BIN" exec resume "$id" --skip-git-repo-check "$PROMPT" >/dev/null 2>&1; then
    echo "$id" >> "$DONE"; ok=$((ok+1)); echo "ok"
  else
    echo "$id" >> "$FAIL"; ng=$((ng+1)); echo "FAILED"
  fi
  sleep "${TOUCH_WAIT:-2}"
done < "$IDS"
echo
echo "finished: ok=$ok failed=$ng (already done earlier: $(($(grep -c . "$DONE") - ok)))"
[ "$ng" -gt 0 ] && echo "failed ids are in $FAIL — rerun the script to retry them."
