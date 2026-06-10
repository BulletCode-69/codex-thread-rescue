# Method: How to survive the disappearing-threads bug

This document explains what we tried, what held up, and why. The short version: **touching a thread with one turn of activity brings it back persistently; pinning is a durable supplement for threads you keep open.** Treat this as a survival guide, not a repair manual.

## First, confirm nothing is lost

Before doing anything, verify the data is intact. In every affected install we checked:

- `state_5.sqlite` passed `PRAGMA integrity_check` with `ok`.
- All threads remained reachable through `codex resume` and Codex search.

So the sidebar going blank is a **display** problem, not data loss. The read-only doctor script reports the healthy database and the real thread count so you can see this for yourself:

```bash
python3 scripts/codex_thread_doctor.py --scope all
```

## The recommended method: touch/recall

The sidebar (and in-app search) show a **bounded window of recently active threads**. Old threads fall out of the window — they look gone, but the data is intact. The way to bring a thread back is to give it one trivial turn of activity:

```bash
# Find a thread by keyword, then touch it by id
bash scripts/codex_thread_recall.sh <keyword>
bash scripts/codex_thread_recall.sh <thread-id>
```

`codex_thread_recall.sh` searches thread titles when you pass a keyword, and touches (re-activates) the thread when you pass an id. After the touch, the thread reappears in its project in the sidebar and in search, and this survives restarts — until it ages out of the window again as other threads see activity.

If you need to touch a longer list (for example after a migration event), use `codex_thread_touch.sh` — but read its zero-sum caveat first: the window is bounded, so only the most recently touched threads stay visible simultaneously.

The complete model is in [docs/PERSISTENCE.md](PERSISTENCE.md).

## What persists vs. what does not

We tested several approaches on a live affected install.

### Persists (verified)

- **Touching a thread with one turn of activity** (`codex exec resume <id> --skip-git-repo-check "..."` — what `codex_thread_recall.sh` does). The thread re-enters the recency window and stays there across restarts until it ages out.
- **Pinning a thread.** Pins live in local `pinned-thread-ids` which the UI reads; edits made while the app is fully quit render on next launch. Useful as a supplement for a small working set.

### Does not restore sidebar listing (verified negatives)

All of these can make threads appear to reappear in the current session, then lose them again on the next restart:

- **Asking Codex, from inside the affected project, to "restore this project's threads to the sidebar."** (Deprecated — see below.) Codex can rebind thread ids to the local assignment cache, and the sidebar repopulates for the session — but this is clobbered on exit. Further, the in-session repair sometimes creates new fork copies; the originals stay hidden and projects fill with duplicates.
- **Fork-based bulk restore** of many threads at once.
- **Editing `.codex-global-state.json` directly** to rewrite `thread-project-assignments` or `thread-workspace-root-hints`. These edits persist on disk when made while the app is fully quit, but the sidebar does not consult these stores for its listing (verified negative). Editing while the app runs is also clobbered on exit.
- **Running a metadata backfill/audit that reports a clean result** (for example "207/207 OK"). A clean local audit is consistent with an empty-looking sidebar.

The common trap: any of these makes threads visible *right now*, which feels like success. Only the touch/recall approach is persistent.

## The realistic workflow

1. Run the read-only doctor to confirm the database is healthy and see the full thread count.
2. Build the resume index (`scripts/codex_thread_index.py`) — your durable map to every thread, independent of what the sidebar shows.
3. When you need a specific thread in the UI, recall it: `bash scripts/codex_thread_recall.sh <keyword>` to find it, then `bash scripts/codex_thread_recall.sh <thread-id>` to touch it. It reappears in its project and in search.
4. Optionally pin the threads you keep coming back to.
5. Accept that the sidebar is a recent-activity view, not an archive. Recall is cheap and repeatable; the index is the archive.

## Why the "ask Codex to restore" method only appeared to work (historical note)

Earlier versions of this document listed "ask Codex to restore this project's threads" as the recommended method. Here is why it appeared to work but does not:

A Codex agent session runs **inside the app**. Any writes it makes to `.codex-global-state.json` are in-memory only — the app holds the file in memory and rewrites it from memory on exit, clobbering whatever the agent wrote. So the sidebar reflects the in-memory (repopulated) state for the current session, then goes blank again after a restart.

In some cases the agent creates new fork copies of threads (recently active, so they enter the window), while the originals stay hidden. This produces duplicate threads in the project and pollutes your history.

The only writes to `.codex-global-state.json` that persist are ones made **while the app is fully quit**. And even those do not drive sidebar listing — only the recency window does (see [docs/PERSISTENCE.md](PERSISTENCE.md)).

## About the experimental write helpers

Two metadata-rewriting helpers live under [`../experimental`](../experimental), **outside the
supported v0.1 toolset**. `codex_thread_rebuild_index.py` can rewrite `session_index.jsonl`
from active thread rows in `state_5.sqlite`; `codex_thread_rebind_metadata.py` can update
Desktop sidebar metadata in `.codex-global-state.json` and add missing `[projects]` entries
to `config.toml`.

They are kept only for inspection. They are deliberately conservative — dry-run by default,
refuse to run while Codex is open, write a safety copy before any change, and never touch
thread message content. But per the testing above, their effect on the sidebar is **not**
expected to restore listing (the sidebar uses the recency window, not local binding caches),
which is exactly why they are isolated rather than recommended. Touch/recall is the durable
option, and the read-only `codex_thread_index.py` plus `codex_thread_resume.py` are the
supported way to keep working without depending on the sidebar.

This is not deleted-data recovery. If thread rows and rollout files were truly gone, nothing
here would recreate their contents — but as noted above, in the disappearing-sidebar case the
data is intact and the problem is display-only.
