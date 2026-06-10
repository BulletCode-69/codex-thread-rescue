# Automation: keep the index fresh, resume fast

The goal of automation here is narrow and honest: **always have a current, resume-ready index**, and **reopen any thread quickly** when the sidebar hides it. That is durable and safe.

What this does **not** automate, on purpose: continuously pushing threads back into the sidebar in the background. The sidebar shows a recency window — only the threads you actually use (or touch on demand) stay visible. Automating bulk re-touches is zero-sum and fights the window forever. So the durable design is *index + on-demand recall*, not *auto-revive*.

```
state_5.sqlite  ──(read-only)──>  index (auto-updated)  ──>  codex resume <id>  ──>  pin the few you keep
```

## 1. Auto-update the index

Regenerate the index on a schedule so it never goes stale. The generator is read-only on Codex state and idempotent, so running it often is harmless.

On-demand or in a script:

```bash
python3 scripts/codex_thread_index.py --scope all --apply
```

macOS launchd (runs every hour). Save as `~/Library/LaunchAgents/com.local.codex-thread-index.plist`, then `launchctl load` it. Adjust the absolute paths:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.local.codex-thread-index</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/ABSOLUTE/PATH/scripts/codex_thread_index.py</string>
    <string>--scope</string><string>all</string>
    <string>--apply</string>
    <string>--master-index</string>
    <string>/ABSOLUTE/PATH/thread-rescue-index/project-thread-master-index.md</string>
  </array>
  <key>StartInterval</key><integer>3600</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
```

cron equivalent (hourly):

```cron
0 * * * * /usr/bin/python3 /ABSOLUTE/PATH/scripts/codex_thread_index.py --scope all --apply --master-index /ABSOLUTE/PATH/thread-rescue-index/project-thread-master-index.md
```

git pre-commit hook (refresh the index whenever you commit in a project):

```bash
#!/bin/sh
python3 /ABSOLUTE/PATH/scripts/codex_thread_index.py --scope cwd --cwd "$(pwd)" --apply >/dev/null 2>&1 || true
```

Reads are safe while Codex is running. The generated files contain real thread ids and paths, so keep them local — `.gitignore` already ignores `project*thread*index*` and `thread-health/`.

## 2. Resume fast from the index ("revive")

When the sidebar hides a thread, "reviving" it means reopening it with `codex resume`. The launcher lists your user threads and resumes the one you pick. It is read-only and, by default, only prints the command:

```bash
# List user threads (newest first)
python3 scripts/codex_thread_resume.py --list

# Filter, then pick a number; prints `codex resume <id>`
python3 scripts/codex_thread_resume.py --query "auth"

# Same, but actually launch codex resume for the chosen thread
python3 scripts/codex_thread_resume.py --query "auth" --exec
```

The touch that `codex resume` performs re-enters the thread into the recency window and persists across restarts (until it ages out). If you want a thread guaranteed visible without aging out, also pin it with `scripts/codex_thread_pin.py`.

## 3. Detect a disappearance (notify, don't auto-fix)

The doctor can flag when the sidebar is likely showing missing chats. With `--verify-ui-readiness` it exits non-zero when checks suggest the UI is not in a clean state, which is enough to drive a notification.

```bash
python3 scripts/codex_thread_doctor.py --scope all --verify-ui-readiness >/dev/null 2>&1 \
  || osascript -e 'display notification "Codex sidebar may be hiding threads — open your index" with title "Codex Thread Rescue"'
```

Run that on the same schedule as the index. The point is to *tell you* to fall back to the index and `codex resume`, not to silently re-inject threads into a cache that will drop them again.

## Why this is the safe shape

Every step above is read-only on Codex state (the notification step only runs the doctor read-only), never edits thread content or the Desktop cache surfaces, and never quits or restarts Codex. The only writes are plain Markdown index files you own. That keeps the automation aligned with the verified model: your data is always safe and resume-reachable via `codex resume`; the sidebar is a recency window, not an archive, and on-demand recall is the right tool rather than continuous force-repair.
