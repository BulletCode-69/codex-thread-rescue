from __future__ import annotations

"""Write thread-to-project binding entries in Codex Desktop local state.

IMPORTANT — does NOT restore sidebar listing (see docs/PERSISTENCE.md)
-----------------------------------------------------------------------
Controlled experiments confirmed that writing `thread-project-assignments`
and `thread-workspace-root-hints` to `.codex-global-state.json` — even
while the app is fully quit so the writes persist on disk — does NOT cause
the Codex Desktop sidebar to list those threads. The sidebar uses a
recency window (threads age in via app/CLI activity), not local binding
caches. These stores are read by the app for other purposes but do not
drive the thread listing.

The write path (for reference):
Codex Desktop reads `~/.codex/.codex-global-state.json` at launch, keeps
the whole document in memory while running, and rewrites it from memory on
exit. Writes made while the app is **fully quit** do persist on disk and
are loaded on next launch. Writes made while the app is **running**
(including by a Codex agent session) are silently clobbered on exit.

This script is kept as documentation of the local format and for
experimental use. It is NOT the recommended way to bring threads back.
To restore a thread under its project in the sidebar, give it one turn of
activity with `scripts/codex_thread_recall.sh` instead.

Safety model
------------
- Dry-run by default; nothing is written without `--apply`.
- Refuses to run while Codex Desktop processes are detected.
- Timestamped safety copies of the state file (and `.bak`) before writing.
- Verifies a byte-exact round-trip of the unmodified JSON before touching
  anything; aborts on mismatch.
- Only adds missing entries (or overwrites with `--force`); never deletes.

Usage
-----
    # Preview: every non-archived user thread of a project root that has
    # no binding
    python3 codex_thread_rebind.py --cwd /path/to/project

    # Apply it
    python3 codex_thread_rebind.py --cwd /path/to/project --apply

    # Specific threads only (binding target inferred from each thread's cwd)
    python3 codex_thread_rebind.py 019e... 019f... --apply

    # Include subagent/helper threads too (skipped by default)
    python3 codex_thread_rebind.py --cwd /path/to/project --include-helpers
"""

import argparse
import json
import sys
from pathlib import Path

from codex_thread_rescue_common import (
    default_paths,
    detect_codex_processes,
    fetch_threads,
    now_stamp,
    safety_copy,
)

ASSIGN_KEY = "thread-project-assignments"
HINT_KEY = "thread-workspace-root-hints"
GLOBAL_STATE_BAK_SUFFIX = ".bak"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persistently restore thread-to-project sidebar bindings. Dry-run by default."
    )
    parser.add_argument("thread_ids", nargs="*", help="Thread ids to rebind (target inferred from cwd).")
    parser.add_argument("--codex-home", type=Path, help="Codex state directory. Default: CODEX_HOME or ~/.codex.")
    parser.add_argument("--safety-dir", type=Path, help="Directory for safety copies.")
    parser.add_argument("--cwd", help="Rebind all matching threads whose project root equals this path.")
    parser.add_argument("--include-helpers", action="store_true",
                        help="Also rebind subagent/system helper threads (skipped by default).")
    parser.add_argument("--include-archived", action="store_true", help="Also rebind archived threads.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing bindings, not only add missing ones.")
    parser.add_argument("--apply", action="store_true", help="Actually write. Without this flag nothing changes.")
    return parser.parse_args()


def binding_for(cwd: str) -> dict:
    return {
        "projectKind": "local",
        "projectId": cwd,
        "path": cwd,
        "cwd": cwd,
        "pendingCoreUpdate": False,
    }


def serialize(state: dict) -> str:
    return json.dumps(state, separators=(",", ":"), ensure_ascii=False)


def main() -> int:
    args = parse_args()
    if not args.thread_ids and not args.cwd:
        print("nothing to do: pass thread ids or --cwd", file=sys.stderr)
        return 2

    paths = default_paths(args.codex_home, args.safety_dir)
    state_path = paths.global_state
    bak_path = state_path.with_name(state_path.name + GLOBAL_STATE_BAK_SUFFIX)
    if not state_path.exists():
        print(f"error: {state_path} not found", file=sys.stderr)
        return 2

    raw = state_path.read_text(encoding="utf-8")
    state = json.loads(raw)
    assignments = state.setdefault(ASSIGN_KEY, {})
    hints = state.setdefault(HINT_KEY, {})

    # Collect candidate threads.
    if args.cwd:
        records = fetch_threads(paths, scope="cwd", prefix=None, cwd=args.cwd)
    else:
        records = fetch_threads(paths, scope="all", prefix=None, cwd=None)
        wanted = set(args.thread_ids)
        records = [r for r in records if r.id in wanted]
        missing_ids = wanted - {r.id for r in records}
        if missing_ids:
            print("error: not found in state_5.sqlite:", file=sys.stderr)
            for t in sorted(missing_ids):
                print(f"  {t}", file=sys.stderr)
            return 2

    skipped_helper = skipped_archived = skipped_bound = 0
    plan: list[tuple[str, str, str]] = []  # (thread_id, cwd, title)
    for r in records:
        if not args.include_archived and not r.is_active:
            skipped_archived += 1
            continue
        if not args.include_helpers and not r.is_user_thread:
            skipped_helper += 1
            continue
        if not args.force and r.id in assignments:
            skipped_bound += 1
            continue
        if not r.cwd:
            continue
        plan.append((r.id, r.cwd, (r.title or "").replace("\n", " ")[:60]))

    print(f"candidates: {len(plan)} to rebind "
          f"(skipped: {skipped_bound} already bound, {skipped_helper} helper, {skipped_archived} archived)")
    for tid, cwd, title in plan:
        print(f"  + {tid}  ->  {cwd}  | {title}")

    if not plan:
        print("nothing to write.")
        return 0
    if not args.apply:
        print("\ndry-run: no files were modified. Re-run with --apply to write.")
        return 0

    # --- write path -------------------------------------------------------
    blocking = [p for p in detect_codex_processes() if p.get("pid")]
    if blocking:
        print("error: Codex Desktop appears to be running. Quit it fully first — "
              "edits made while it runs are clobbered on exit:", file=sys.stderr)
        for p in blocking[:10]:
            print(f"  pid {p['pid']}: {p['command']}", file=sys.stderr)
        return 3

    if serialize(state) != raw:
        print("error: round-trip mismatch — unexpected on-disk JSON format. Aborting.", file=sys.stderr)
        return 4

    stamp = now_stamp()
    for target in (state_path, bak_path):
        copy = safety_copy(target, paths, stamp, "rebind")
        if copy:
            print(f"safety copy: {copy}")

    for tid, cwd, _ in plan:
        assignments[tid] = binding_for(cwd)
        hints[tid] = cwd

    for target in (state_path, bak_path):
        if not target.exists():
            continue
        if target is bak_path:
            bak_raw = target.read_text(encoding="utf-8")
            bak_state = json.loads(bak_raw)
            if serialize(bak_state) != bak_raw:
                print(f"warning: {target.name} did not round-trip; leaving it untouched.")
                continue
            bak_assign = bak_state.setdefault(ASSIGN_KEY, {})
            bak_hints = bak_state.setdefault(HINT_KEY, {})
            for tid, cwd, _ in plan:
                bak_assign[tid] = binding_for(cwd)
                bak_hints[tid] = cwd
            out = serialize(bak_state)
        else:
            out = serialize(state)
        tmp = target.with_name(target.name + f".tmp_{stamp}")
        tmp.write_text(out, encoding="utf-8")
        tmp.replace(target)
        print(f"wrote {target}")

    print(f"\ndone: {len(plan)} binding(s) restored. Launch Codex Desktop and check the project's thread list.")
    print("Verify persistence: quit fully and relaunch once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
