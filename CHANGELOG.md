# Changelog

## 2026-06-10

### Verified visibility model

Controlled experiments on an affected install confirmed the final model: the Codex Desktop
sidebar and in-app search show a **bounded window of recently active threads**. Threads age
out of the window when they receive no activity; they are not deleted. The registry behind
the window is not any locally editable file in `~/.codex` or Electron storage. See
`docs/PERSISTENCE.md` for the full experimentally-verified account.

Key findings documented:

- `thread-project-assignments` and `thread-workspace-root-hints` persist on disk when written
  while the app is quit, but the sidebar does not consult them for listing (verified negative).
- Any Codex agent session edit to `.codex-global-state.json` is clobbered on app exit.
- A one-time migration event (identified forensically) switched listing to the recency-window
  system and dropped threads without recent activity from view.

### New scripts: touch/recall

- `scripts/codex_thread_recall.sh` — find a thread by keyword or id and touch it with one
  trivial turn of activity to bring it back into the sidebar/search window. The daily driver.
- `scripts/codex_thread_touch.sh` — bulk-touch a list of thread ids (checkpointed,
  resumable). Includes zero-sum caveat: only the most recently touched threads stay visible.
- Both scripts support a `TOUCH_PROMPT` environment variable to override the default prompt.

### Deprecated: "ask Codex to restore the sidebar"

The previously documented method of asking a Codex agent session to restore threads is now
known to be ineffective: in-session writes are clobbered on app exit, and fork-based restores
create duplicate copies while originals stay hidden. `docs/METHOD.md` has been rewritten to
reflect this; the old method is preserved as a historical note.

### Documentation rewritten

- `docs/PERSISTENCE.md` — new document; single source of truth for the verified model.
- `docs/METHOD.md` — rewritten; touch/recall is now the recommended method.
- `docs/SAFETY.md` — updated to reflect touch/recall as a durable option alongside pinning.
- `docs/AUTOMATION.md` — updated; removed "only pinning does" claim.
- `README.md` — full consistency pass; FAQ, symptoms, and all sections updated.
- `experimental/README.md` — corrected; experimental helpers do not restore listing.
- `scripts/codex_thread_pin.py` — docstring updated; no longer points to rebind as the
  restore path.
- `scripts/codex_thread_rebind.py` — docstring corrected; write persists locally but does
  NOT drive sidebar listing.
