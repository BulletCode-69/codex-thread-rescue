# Safety Notes

This repository is meant to stay publishable. Treat local Codex state as private data.

## Your data is safe — start here

Before anything else: when the Codex Desktop sidebar goes blank, your conversations are **not** lost. In every affected install we checked, `state_5.sqlite` passed `PRAGMA integrity_check` with `ok`, and every thread stayed reachable through `codex resume` and Codex search. The failure is in the *display*, not the data. So there is never a reason to delete, reset, or aggressively "repair" your local state to get your work back — calmer options always exist.

## What is durable and what is not

This matters for safety because chasing a non-durable fix can lead you to edit state you should leave alone.

- **Durable:** pinning a thread keeps it in the sidebar across restarts. This is the recommended workaround.
- **Not durable:** asking Codex to restore the sidebar, fork-based bulk restore, hand-editing `.codex-global-state.json`, or running a backfill/audit that reports a clean result (e.g. "207/207 OK"). These can repopulate the sidebar for the current session and then lose it again on restart. A passing audit does **not** mean the UI will keep the threads.

Treat any temporary reappearance as exactly that — temporary — and prefer pinning plus `codex resume`/search over repeated cache surgery.

## Do Not Commit

- Local Codex state files.
- Generated reports from your machine.
- SQLite files or journal files.
- Safety copies.
- Real project names or real local paths.
- Local auth material, service account files, or environment files.

## Do Not Touch (the underlying data)

To keep your conversations safe, these tools never rewrite, and you should not manually rewrite:

- thread rows or conversation content in `state_5.sqlite`,
- rollout files,
- and more generally any source of the actual messages.

Only Desktop *display* metadata is ever a candidate for editing, and even that is optional and temporary (see below).

## The supported tools open the database read-only

`codex_thread_doctor.py`, `codex_thread_index.py`, and `codex_thread_resume.py` open
`state_5.sqlite` with a read-only URI (`file:...?mode=ro`), so they cannot modify it even by
accident. They never write `session_index.jsonl`, `.codex-global-state.json`, `config.toml`,
or any rollout file. The only files they write are the report and index Markdown files you ask
for. The index defaults to a central private directory (`~/.codex-thread-rescue/index`), not
your project repositories.

## Experimental write helpers (isolated)

The two metadata-rewriting helpers live under `experimental/` and are **not** part of the
supported v0.1 toolset. They default to dry-run; `--apply` is required for any write, and it
refuses to run while Codex appears to be running (writing while Desktop is open can be
overwritten by in-memory state when the app exits). Every apply path writes a safety copy
outside this repository first, and they never edit thread message content.

`codex_thread_rebuild_index.py` can rewrite `session_index.jsonl` from active user-visible
thread rows in `state_5.sqlite`. `codex_thread_rebind_metadata.py` can update Desktop sidebar
metadata in `.codex-global-state.json`, and can add missing `[projects]` entries to
`config.toml` when `--update-config` is passed.

**Honest expectation:** applying these does **not** reliably survive a restart — they fall in
the "not durable" category above, which is why they are isolated. Pinning remains the
dependable option.

Neither helper edits thread message content.
