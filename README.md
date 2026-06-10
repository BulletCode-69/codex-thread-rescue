# Codex Thread Rescue

> **Codex Desktop sidebar suddenly empty, showing `No chats`, or missing your threads after an update or restart? Your conversations are NOT lost.** This repository is a survival guide plus small, read-only tools to find every Codex thread again and keep working while the sidebar hides them.

This is **not** a tool that fixes the sidebar bug — that bug is upstream in Codex itself and can only be fixed by Codex. What this gives you is a calm, safe way to (1) confirm your data is intact, (2) find and reopen any hidden thread with `codex resume`, and (3) keep working without losing anything.

The first rule of this repository is privacy: do not commit local Codex state, project names, real paths, local auth material, or generated reports from your machine.

## Is my data gone? No.

If the Codex Desktop (Codex app) sidebar shows `No chats`, an empty project, or far fewer threads than you had, your threads still exist on disk in `state_5.sqlite` and are reachable with `codex resume <thread_id>` and Codex search. The failure is a **display** bug in the sidebar, not data loss. Do not reset, reinstall, or delete anything.

In every case we checked, the local database was healthy:

- `state_5.sqlite` is intact, with `PRAGMA integrity_check = ok`.
- Every thread is still reachable through `codex resume` and through Codex search.

So the failure is a *display* failure in Codex Desktop, not data loss. If the sidebar is empty, do not panic and do not start deleting or "repairing" anything. Your work is safe and accessible by other means.

## Quick answers (FAQ)

**My Codex threads disappeared from the sidebar after updating. Did I lose them?**
No. The data is intact in `state_5.sqlite`; only the sidebar display is affected. Reach any thread with `codex resume <thread_id>`. The sidebar and in-app search show a bounded window of *recently active* threads — old threads age out of the window but are never deleted.

**A Codex project shows `No chats`, but I know I had conversations there.**
Threads that have not had recent activity have aged out of the recency window. They still exist and `codex resume <thread_id>` always works. Use the resume index in this repo to list them and bring any specific one back.

**They reappeared when I asked Codex to restore them, then vanished again after a restart. Why?**
"Ask Codex to restore" only appeared to work: a Codex agent session runs inside the app, so its writes to local state are clobbered when the app exits. What *does* work persistently is giving a thread one actual turn of activity — `bash scripts/codex_thread_recall.sh <thread-id>` does this in one command. See [docs/PERSISTENCE.md](docs/PERSISTENCE.md) for the full verified model.

**Does in-app search always find every thread?**
No — search is also windowed the same way the sidebar is. Threads outside the recency window do not appear in search results. `codex resume <thread_id>` and the resume index are the always-working fallbacks.

**How do I get a list of all my Codex threads with their resume commands?**
Run the read-only `codex_thread_index.py` (see [docs/INDEX.md](docs/INDEX.md)). It builds a `project-thread-index.md` that maps every thread to `codex resume <thread_id>`.

**Will reinstalling Codex or clearing state fix it?**
No — and it risks making things worse. The data is fine; the bug is upstream. Keep working via the index, `codex resume`, and touch/recall until Codex ships a fix.

## Symptoms

- A project still appears in Codex Desktop, but its chat list is empty or short.
- Threads exist in local Codex state, but they are not shown in the project sidebar.
- The project works if you create a *new* chat, while older chats stay hidden.
- The threads briefly reappear after some action, then vanish again after a restart.

## What actually works, and what does not

This is the heart of this repository. These conclusions come from direct testing on an affected install, not from theory.

### Works (verified)

- **Touching a thread with one turn of activity.** The sidebar and in-app search show a bounded window of recently active threads. `codex exec resume <id> --skip-git-repo-check "..."` puts a thread back into that window, persistently across restarts, until it ages out again. Use `scripts/codex_thread_recall.sh` for one thread, `scripts/codex_thread_touch.sh` for a list (zero-sum caveat: only the most recently touched ~window-size threads stay visible).
- **`codex resume <thread-id>`.** Your threads are always reachable this way, sidebar or not.
- **Pinning** (the pinned section renders from local `pinned-thread-ids`; programmatic editing while the app is fully quit persists — `scripts/codex_thread_pin.py`).

### Does **not** restore sidebar visibility (tempting traps)

- **Editing local display caches** — `thread-project-assignments`, `thread-workspace-root-hints` in `.codex-global-state.json`, or `has_user_event` in `state_5.sqlite`. Edits made while the app is fully quit do persist on disk, but the sidebar does not consult these stores for listing (verified negative).
- **Any edit made while the app is running** — including everything a Codex agent session does to local files. The app rewrites `.codex-global-state.json` from memory on exit, erasing such edits.
- **Fork-based bulk restore.** Creates recently-active *copies*; the originals stay hidden and your projects fill with duplicates.
- **Metadata "backfill" / audits reporting "207/207 OK".** A clean local audit is consistent with an empty-looking sidebar.

## The realistic workflow

1. Confirm your data is safe (the diagnostics below will show the healthy database and the full thread count).
2. Build the resume index (`scripts/codex_thread_index.py`) — your durable map to every thread, independent of what the sidebar shows.
3. When you need an old thread in the UI, recall it: `bash scripts/codex_thread_recall.sh <keyword>` to find it, then `... <thread-id>` to touch it. It reappears in its project and in search.
4. Accept that the sidebar is a recent-activity view, not an archive. Recall is cheap and repeatable; the index is the archive.

To make step 3 reliable, keep a **resume index**: one `project-thread-index.md` per project listing each thread's id and its `codex resume <thread_id>` command, plus a master table across all projects. This is organization, not repair — it never touches Codex state — and it means that even with a blank sidebar you always have a durable map to every thread. You can build it with the read-only `codex_thread_index.py` script, or by asking Codex with the prompt in [docs/INDEX.md](docs/INDEX.md).

```bash
# Preview (dry-run, writes nothing)
python3 scripts/codex_thread_index.py --scope all

# Write the index into a central private directory (~/.codex-thread-rescue/index by default)
python3 scripts/codex_thread_index.py --scope all --apply
```

By default the index files are written to a central private directory, not into your
project repositories, because they contain real thread ids and paths. Pass
`--in-project-roots` if you also want a copy inside each project root.

## Read-only diagnostics

These commands never modify Codex state — they open the database read-only and never touch
`session_index.jsonl`, `.codex-global-state.json`, `config.toml`, or any rollout file. The
only files they ever write are the report and index Markdown files you ask for, in locations
you choose. They never upload or push anything. Run everything with `python3`; no install required.

Read-only diagnosis of the local Codex state:

```bash
python3 scripts/codex_thread_doctor.py --scope all
```

Write a local Markdown report (home paths redacted by default — still review before sharing):

```bash
python3 scripts/codex_thread_doctor.py --scope all --markdown thread-rescue-audit/doctor.md
```

Build a resume index across all projects (dry-run by default — see [docs/INDEX.md](docs/INDEX.md)):

```bash
python3 scripts/codex_thread_index.py --scope all
```

Resume a hidden thread from the read-only launcher (prints `codex resume <id>`; `--exec` to launch):

```bash
python3 scripts/codex_thread_resume.py --query "auth"
```

Run the synthetic fixture test (no access to your real state):

```bash
python3 scripts/codex_thread_visibility_selftest.py
```

For keeping the index fresh on a schedule and resuming fast, see [docs/AUTOMATION.md](docs/AUTOMATION.md).

## Experimental (not part of v0.1)

Two metadata-rewriting helpers live under [`experimental/`](experimental/). They try to
rebind threads to the sidebar by editing local binding caches, but in testing this does **not**
restore sidebar listing — the sidebar uses the recency window, not local binding caches. They
are kept only for inspection and are not part of the supported workflow. See
[experimental/README.md](experimental/README.md) before touching them.

## Safety policy

- The supported tools (`doctor`, `index`, `resume`) open the Codex database **read-only** and never modify any Codex state file (`state_5.sqlite`, `session_index.jsonl`, `.codex-global-state.json`, `config.toml`) or any rollout file.
- The only files these tools write are the report and index Markdown files you request. By default the index goes to a central private directory, not into your repositories.
- They never edit thread message content, and never publish, upload, or push anything.
- The `experimental/` helpers can write Desktop metadata, but only with an explicit `--apply`, are dry-run by default, refuse to run while Codex appears open, and write a safety copy first. Their writes do not restore sidebar listing (the sidebar uses the recency window — see [docs/PERSISTENCE.md](docs/PERSISTENCE.md)). Treat them as documentation-only.
- Generated reports and indexes can contain local project names, paths, and thread ids. Keep them out of version control (the bundled `.gitignore` already does this) and review before sharing.

More detail on the method and the cache surfaces involved: [docs/METHOD.md](docs/METHOD.md). Safety notes: [docs/SAFETY.md](docs/SAFETY.md).

## Related upstream issues

This is an upstream Codex bug. These reports track the disappearing-threads / sidebar-state behavior:

- [openai/codex issue #20833](https://github.com/openai/codex/issues/20833)
- [openai/codex issue #21128](https://github.com/openai/codex/issues/21128)
- [openai/codex issue #22796](https://github.com/openai/codex/issues/22796)
- [openai/codex issue #23609](https://github.com/openai/codex/issues/23609)
- [openai/codex issue #23942](https://github.com/openai/codex/issues/23942)
- [openai/codex issue #26157](https://github.com/openai/codex/issues/26157)

Because the root cause is upstream, the durable fix has to come from Codex. Until then, this repository is a way to stay calm, confirm your data is intact, and keep working.

## Publishing

This repository is prepared for a local first commit only. To publish it later:

```bash
git remote add origin <new-public-repository-url>
git push -u origin main
```

Before publishing, run your own privacy scan again and inspect every tracked file:

```bash
git ls-files
git diff --stat HEAD
```
