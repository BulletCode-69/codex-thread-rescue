# Method: How to survive the disappearing-threads bug

This document explains what we tried, what held up, and why. The short version: **only pinning persists; everything else is temporary.** Treat this as a survival guide, not a repair manual.

## First, confirm nothing is lost

Before doing anything, verify the data is intact. In every affected install we checked:

- `state_5.sqlite` passed `PRAGMA integrity_check` with `ok`.
- All threads remained reachable through `codex resume` and Codex search.

So the sidebar going blank is a **display** problem, not data loss. The read-only doctor script reports the healthy database and the real thread count so you can see this for yourself:

```bash
python3 scripts/codex_thread_doctor.py --scope all
```

## What persists vs. what does not

We tested several recovery approaches on a live affected install. Only one survived a restart.

### Persists

- **Pinning a thread.** A pinned thread stays in the sidebar across restarts. This is the durable workaround.

### Does not persist (temporary display only)

All of these can make threads reappear in the current session, then lose them again on the next restart:

- **Asking Codex, from inside the affected project, to "restore this project's threads to the sidebar."** Codex can rebind thread ids to the project's workspace root and assignment cache, and the sidebar repopulates — but only until the next restart. We originally believed this was the best fix; further testing showed it does not hold.
- **Fork-based bulk restore** of many threads at once.
- **Editing `.codex-global-state.json` directly** to rewrite the display cache.
- **Running a metadata backfill/audit that reports a clean result** (for example "207/207 OK"). The audit passing does not mean Desktop will keep displaying the threads.

The common trap: any of these makes the threads visible *right now*, which feels like success. It is not durable. If you see threads return after one of these actions, expect them gone again after a restart.

## The realistic workflow

Because only pinning holds, run the sidebar as a small working tray:

1. Run the read-only doctor to confirm the database is healthy and see the full thread count.
2. Pin the few threads you are actively working on.
3. Reach everything else with `codex resume` and search.
4. Rotate pins as your active set changes.
5. Keep a **resume index** so step 3 never depends on memory: one `project-thread-index.md` per project mapping each thread to its `codex resume <thread_id>` command. Build it read-only with `codex_thread_index.py`, or with the Codex prompt — both are documented in [docs/INDEX.md](docs/INDEX.md). Pin the index thread and you have a durable entry point even when the sidebar is empty.

## Why the temporary approaches fail

Codex Desktop does not rely only on the SQLite thread table. The sidebar also needs display metadata that binds a thread id to a workspace root and a project assignment. The relevant cache surfaces include:

- `session_index.jsonl`
- `electron-saved-workspace-roots`
- `project-order`
- `electron-workspace-root-labels`
- `sidebar-collapsed-groups`
- `thread-workspace-root-hints`
- `thread-project-assignments`

Rebinding these surfaces — whether by asking Codex, by editing the cache, or by running a backfill — can repopulate the sidebar for the session. But on restart Codex rebuilds or revalidates this display state and the binding is lost again. That is the upstream bug: the durable association between a thread and its project sidebar entry is not being preserved. Until Codex fixes that, no local cache edit reliably sticks. Pinning works because it is stored and honored through a different, persistent path.

## About the experimental write helpers

Two metadata-rewriting helpers live under [`../experimental`](../experimental), **outside the
supported v0.1 toolset**. `codex_thread_rebuild_index.py` can rewrite `session_index.jsonl`
from active thread rows in `state_5.sqlite`; `codex_thread_rebind_metadata.py` can update
Desktop sidebar metadata in `.codex-global-state.json` and add missing `[projects]` entries
to `config.toml`.

They are kept only for inspection. They are deliberately conservative — dry-run by default,
refuse to run while Codex is open, write a safety copy before any change, and never touch
thread message content. But per the testing above, their effect on the sidebar is **not**
expected to survive a restart, which is exactly why they are isolated rather than recommended.
Pinning remains the durable option, and the read-only `codex_thread_index.py` plus
`codex_thread_resume.py` are the supported way to keep working.

This is not deleted-data recovery. If thread rows and rollout files were truly gone, nothing
here would recreate their contents — but as noted above, in the disappearing-sidebar case the
data is intact and the problem is display-only.
