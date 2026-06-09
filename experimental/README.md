# Experimental — not part of v0.1

The two helpers in this directory can **write** Codex Desktop metadata to try to rebind
threads to the project sidebar. They are kept here for inspection and study only.

**They do not reliably work.** Based on direct testing on an affected install, any
improvement they make to the sidebar does **not** survive a restart. They fall in the
"does not persist" category described in the main [docs/METHOD.md](../docs/METHOD.md):
re-binding the display cache repopulates the sidebar for the current session, and Codex
drops the binding again on the next launch. The only action that persists is **pinning**.

So nothing here is a fix. Do not rely on it. The supported, durable workflow is the
read-only tooling in [`../scripts`](../scripts) plus pinning:

- `codex_thread_doctor.py` — read-only diagnosis.
- `codex_thread_index.py` — read-only resume index (keep every thread reachable).
- `codex_thread_resume.py` — read-only resume launcher.

## If you still want to experiment

These scripts are conservative by construction: dry-run by default, they refuse to run
while Codex appears to be open, they write a safety copy outside the repository before
any change, and they never edit thread message content. But understand that applying
them is, at best, a temporary display nudge — and usually not even that past a restart.

```bash
# Dry-run only (writes nothing)
python3 experimental/codex_thread_rebuild_index.py --scope all
python3 experimental/codex_thread_rebind_metadata.py --scope all --update-config
```

`--apply` exists but is intentionally undocumented here as a recommended step. Quit Codex
Desktop first if you choose to try it, and expect the effect not to last.
