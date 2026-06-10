# How Codex Desktop decides what the sidebar shows — and how to bring threads back

This document records the final, experimentally-verified model of the
"missing threads / No chats" behavior, after a full day of controlled
experiments on an affected install. It corrects several earlier beliefs,
including ones published in earlier versions of this repository.

## The final model

**Sidebar project lists and in-app search show a bounded window of
recently-active threads.** The registry behind that window is not any file
in `~/.codex`, not Electron storage in `~/Library/Application Support`, and
not directly editable. Threads that have had no activity recently fall out
of the window — they look deleted ("No chats"), but they are not: the
conversation data in `state_5.sqlite` and the rollout files stays intact
and `codex resume <thread-id>` always works.

**Any thread can be brought back on demand** by giving it one trivial turn
of activity through the app or CLI:

```bash
codex exec resume <thread-id> --skip-git-repo-check "「OK」とだけ返答してください。"
```

After this "touch", the thread reappears in its project in the sidebar and
becomes findable in search, and this survives app restarts — until it ages
out of the window again as other threads see activity.

**The window is bounded, so mass-restoration is zero-sum.** Touching
hundreds of threads in a row works mechanically (each touch succeeds), but
only the most recently touched ones remain visible; the earlier ones get
pushed out by the later ones. There is no way to make *all* historical
threads visible simultaneously. The sustainable workflow is on-demand
recall: keep a resume index (see [INDEX.md](INDEX.md)), and touch the
specific thread you need (`scripts/codex_thread_recall.sh`).

## What does NOT control sidebar visibility (verified negatives)

Each of these was tested directly; none of them affects what the sidebar
lists, even though some were previously believed to:

- `thread-project-assignments` / `thread-workspace-root-hints` in
  `~/.codex/.codex-global-state.json`. Entries written there while the app
  is fully quit are loaded, preserved, and written back by the app — they
  persist — but the sidebar does not consult them for listing.
- `has_user_event` (and other flags) in `state_5.sqlite`.
- `session_index.jsonl` membership.
- Electron storage under `~/Library/Application Support/Codex`
  (no thread data exists there at all).
- Network state: the behavior is identical offline (served from cache),
  so you cannot tell from one offline launch whether the registry is
  remote; the write path, however, clearly goes through app/CLI activity,
  which is account-backed.

Two local stores ARE honored by the UI, but only for their own features:
`pinned-thread-ids` (the pinned section) — edits made while the app is
fully quit persist and render — and `sidebar-collapsed-groups`.

## Why everything earlier looked contradictory

- *"Only pinning survives a restart"* — pins live in a local file the UI
  does read; thread-list "repairs" made in-session lived in app memory and
  were clobbered by the exit-time rewrite of `.codex-global-state.json`.
  Both observations were real; the inferred rule was wrong.
- *"Asking Codex to restore threads works, then breaks after restart"* —
  in-session repairs to local files are clobbered at exit (a Codex agent
  session runs inside the app). What *does* work is activity: a resumed
  thread re-enters the recency window persistently. Fork-based restores
  "worked" by creating new (recently-active) copies.
- *"Threads vanished after an update"* — a migration (observed forensically
  via timestamped backups: the legacy binding store inside
  `electron-persisted-atom-state` collapsed from ~80 KB to ~1 KB, and new
  binding keys plus a backfill appeared) switched listing to the
  recency-window system. Threads without recent activity dropped out of
  view at that moment. Routine updates without migrations change nothing.

## Key safety facts that still stand

- The app reads `.codex-global-state.json` at launch, holds it in memory,
  and rewrites it from memory on exit. Never edit files in `~/.codex`
  while any Codex process is running if you want the edit to last.
- All conversation data lives locally and survives everything described
  here. `PRAGMA integrity_check` stayed `ok` throughout; no rollout files
  were lost.

## Tools in this repository

- `scripts/codex_thread_recall.sh <id|keyword>` — find and touch a single
  thread to bring it back into the sidebar/search window. The daily driver.
- `scripts/codex_thread_touch.sh ids.txt` — bulk-touch a list of thread
  ids (checkpointed, resumable). Useful after a migration event, with the
  zero-sum caveat above: expect only the tail of the list to stay visible.
- `scripts/codex_thread_index.py` — build the read-only resume index, the
  durable map to every thread regardless of what the sidebar shows.
- `scripts/codex_thread_pin.py` / `scripts/codex_thread_rebind.py` —
  persistent editors for the local pin list and binding caches. The pin
  list renders in the UI; the binding caches do not drive the sidebar (see
  above) and these are kept mainly as documentation of the local format.

Each touch costs one trivial model turn and appends a short
"touch" exchange to the thread — harmless, and a handy marker of restored
threads.
