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
No. The data is intact in `state_5.sqlite`; only the sidebar display is broken. Reach any thread with `codex resume <thread_id>` or Codex search.

**A Codex project shows `No chats`, but I know I had conversations there.**
The thread-to-project binding in the Desktop display cache was lost. The threads still exist. Use the resume index in this repo to list them and reopen them.

**They reappeared when I asked Codex to restore them, then vanished again after a restart. Why?**
That is expected. Re-binding the sidebar is temporary — only **pinning** survives a restart. Pin the few threads you need and reach the rest with `codex resume`.

**How do I get a list of all my Codex threads with their resume commands?**
Run the read-only `codex_thread_index.py` (see [docs/INDEX.md](docs/INDEX.md)). It builds a `project-thread-index.md` that maps every thread to `codex resume <thread_id>`.

**Will reinstalling Codex or clearing state fix it?**
No — and it risks making things worse. The data is fine; the bug is upstream. Keep working via the index, `codex resume`, and pinning until Codex ships a fix.

## Symptoms

- A project still appears in Codex Desktop, but its chat list is empty or short.
- Threads exist in local Codex state, but they are not shown in the project sidebar.
- The project works if you create a *new* chat, while older chats stay hidden.
- The threads briefly reappear after some action, then vanish again after a restart.

## What actually works, and what does not

This is the heart of this repository. These conclusions come from direct testing on an affected install, not from theory.

### Works (the only thing that persists)

- **Pinning.** A pinned thread stays visible in the sidebar across restarts. This is the only action we found that reliably survives a restart.
- **`codex resume` and search.** Your threads are always reachable this way, sidebar or not.

### Does **not** persist (tempting traps)

Each of these can make threads reappear *for the current session*, which is exactly why they are misleading. After a restart, the threads disappear again:

- **Asking Codex to "restore this project's threads to the sidebar."** It can rebind them temporarily, but the binding is lost on the next restart.
- **Fork-based bulk restore** of many threads at once.
- **Hand-editing `.codex-global-state.json`** (the Desktop display cache).
- **Running a metadata "backfill" / audit that reports e.g. "207/207 OK".** A clean audit does not mean the UI will keep showing the threads.

If you try one of these and the threads come back, that is *expected* and *temporary*. Do not take it as a permanent fix.

## The realistic workflow

Because only pinning persists, the practical approach is to treat the sidebar as a small **working tray** rather than a complete archive:

1. Confirm your data is safe (the diagnostics below will show the healthy database and the full thread count).
2. Pin the handful of threads you are actively working on. They will stay visible across restarts.
3. For everything else, rely on `codex resume` and search to reach older threads on demand.
4. When you finish with a pinned thread, unpin it and pin the next one you need.

This keeps you working through the bug instead of fighting a display cache that will not hold.

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
rebind threads to the sidebar, but in testing the effect does **not** survive a restart —
they are the "does not persist" trap, kept only for inspection. They are not part of the
supported v0.1 workflow. See [experimental/README.md](experimental/README.md) before touching them.

## Safety policy

- The supported tools (`doctor`, `index`, `resume`) open the Codex database **read-only** and never modify any Codex state file (`state_5.sqlite`, `session_index.jsonl`, `.codex-global-state.json`, `config.toml`) or any rollout file.
- The only files these tools write are the report and index Markdown files you request. By default the index goes to a central private directory, not into your repositories.
- They never edit thread message content, and never publish, upload, or push anything.
- The `experimental/` helpers can write Desktop metadata, but only with an explicit `--apply`, are dry-run by default, refuse to run while Codex appears open, and write a safety copy first. Treat their output as temporary at best.
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
