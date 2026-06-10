#!/bin/bash
# codex_thread_recall.sh — bring a hidden thread back into the Codex Desktop
# sidebar (and search) by giving it one trivial turn of activity.
#
# Background: sidebar and in-app search show a bounded window of recently
# active threads. Old threads fall out of the window; they are not deleted.
# One touch via `codex exec resume` puts a thread back in the window.
# See docs/PERSISTENCE.md.
#
# Usage:
#   codex_thread_recall.sh <thread-id>     touch this thread now
#   codex_thread_recall.sh <keyword>       search local thread titles, list
#                                          matching ids, then rerun with an id
# Env:
#   CODEX_HOME    Codex state dir (default ~/.codex)
#   CODEX_BIN     path to the codex CLI (default: auto-detect inside Codex.app)
#   TOUCH_PROMPT  override the prompt sent to the model (default: Japanese "OK" prompt)

set -u
Q="${1:?usage: codex_thread_recall.sh <thread-id | keyword>}"
DB="${CODEX_HOME:-$HOME/.codex}/state_5.sqlite"
BIN="${CODEX_BIN:-$(find /Applications/Codex.app -type f -name 'codex*' -perm -u+x 2>/dev/null | head -1)}"
[ -n "$BIN" ] && [ -x "$BIN" ] || { echo "error: codex CLI not found; set CODEX_BIN" >&2; exit 1; }
PROMPT="${TOUCH_PROMPT:-サイドバー呼び戻しのためのタッチです。何も作業せず「OK」とだけ返答してください。}"

if [[ "$Q" =~ ^[0-9a-f]{8}-[0-9a-f]{4}- ]]; then
  exec "$BIN" exec resume "$Q" --skip-git-repo-check "$PROMPT"
fi

QS="${Q//\'/\'\'}"
echo "title search: $Q"
sqlite3 -readonly "$DB" \
  "SELECT id || '  ' || substr(replace(coalesce(title,''),char(10),' '),1,60) || '  [' || cwd || ']'
   FROM threads
   WHERE archived=0 AND title LIKE '%$QS%'
   ORDER BY updated_at DESC LIMIT 20"
echo
echo "recall a thread with: bash scripts/codex_thread_recall.sh <id>"
