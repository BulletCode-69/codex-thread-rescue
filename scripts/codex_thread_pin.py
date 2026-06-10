from __future__ import annotations

"""Persistently pin Codex Desktop threads from the command line.

Why this exists
---------------
A controlled before/after diff of `~/.codex` (app fully quit -> snapshot ->
pin one thread in the UI -> quit -> snapshot) shows that pinning a thread
changes exactly one key in one file:

    ~/.codex/.codex-global-state.json
        "pinned-thread-ids": ["<thread-id>", ...]

(The app also keeps `.codex-global-state.json.bak` in sync.) Nothing is
written to `state_5.sqlite`, `session_index.jsonl`, or any other local
store. Thread ids appended to that array programmatically — while Codex is
fully quit — are shown as pinned on next launch and survive further
restarts, even for threads that have no project assignment at all.

Note: pins are not special. Any edit to this file made while the app is
fully quit persists; edits made while it runs are clobbered by the app's
exit-time rewrite.

Pinning is a useful supplement, but it does not restore thread listing under
a project — it only adds the thread to the pinned section. To bring a thread
back under its project in the sidebar, use `codex_thread_recall.sh` to give
it one turn of activity (see docs/PERSISTENCE.md). Writing to
`thread-project-assignments` or `thread-workspace-root-hints` (what
`codex_thread_rebind.py` does) persists on disk but does NOT drive sidebar
listing — the sidebar uses a recency window, not local binding caches.

Safety model
------------
- Dry-run by default. Nothing is written without `--apply`.
- Refuses to run while Codex Desktop processes are detected.
- Timestamped safety copies of the state file (and `.bak`) are made before
  any write.
- The JSON is re-serialized in the app's own compact format; the script
  verifies a byte-exact round-trip of the unmodified document before
  touching anything, and aborts if the format does not round-trip.
- Only the `pinned-thread-ids` array is modified. Every other key is
  preserved verbatim.

Usage
-----
    # Preview pinning two specific threads
    python3 codex_thread_pin.py 019e... 019f...

    # Pin every non-archived user thread of one project root
    python3 codex_thread_pin.py --cwd /path/to/project --apply

    # List current pins
    python3 codex_thread_pin.py --list

    # Remove pins added earlier
    python3 codex_thread_pin.py --unpin 019e... --apply
"""

import argparse
import json
import sys
from pathlib import Path

from codex_thread_rescue_common import (
    connect_readonly,
    default_paths,
    detect_codex_processes,
    fetch_threads,
    now_stamp,
    safety_copy,
)

GLOBAL_STATE_BAK_SUFFIX = ".bak"
PIN_KEY = "pinned-thread-ids"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Persistently pin (or unpin) Codex Desktop threads. Dry-run by default."
    )
    parser.add_argument("thread_ids", nargs="*", help="Thread ids to pin.")
    parser.add_argument("--codex-home", type=Path, help="Codex state directory. Default: CODEX_HOME or ~/.codex.")
    parser.add_argument("--safety-dir", type=Path, help="Directory for safety copies.")
    parser.add_argument("--cwd", help="Pin all non-archived user threads whose project root equals this path.")
    parser.add_argument("--unpin", nargs="*", default=[], help="Thread ids to remove from the pin list.")
    parser.add_argument("--list", action="store_true", help="Show the current pin list and exit.")
    parser.add_argument("--allow-unknown", action="store_true",
                        help="Pin ids even when they are not found in state_5.sqlite.")
    parser.add_argument("--apply", action="store_true", help="Actually write. Without this flag nothing changes.")
    return parser.parse_args()


def load_raw_state(path: Path) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8")
    return raw, json.loads(raw)


def serialize_state(state: dict) -> str:
    return json.dumps(state, separators=(",", ":"), ensure_ascii=False)


def main() -> int:
    args = parse_args()
    paths = default_paths(args.codex_home, args.safety_dir)
    state_path = paths.global_state
    bak_path = state_path.with_name(state_path.name + GLOBAL_STATE_BAK_SUFFIX)

    if not state_path.exists():
        print(f"error: {state_path} not found", file=sys.stderr)
        return 2

    raw, state = load_raw_state(state_path)
    pins: list[str] = [p for p in state.get(PIN_KEY, []) if isinstance(p, str)]

    if args.list:
        print(f"{len(pins)} pinned thread id(s):")
        for p in pins:
            print(f"  {p}")
        return 0

    # Resolve the requested additions.
    to_pin: list[str] = list(dict.fromkeys(args.thread_ids))
    if args.cwd:
        threads = fetch_threads(paths, scope="cwd", prefix=None, cwd=args.cwd)
        for record in threads:
            if record.is_user_thread and record.is_active and record.id not in to_pin:
                to_pin.append(record.id)
        print(f"--cwd matched {len(to_pin) - len(args.thread_ids)} thread(s) in {args.cwd}")

    if not to_pin and not args.unpin:
        print("nothing to do: pass thread ids, --cwd, --unpin, or --list", file=sys.stderr)
        return 2

    # Validate ids against the local database (read-only).
    if to_pin and not args.allow_unknown:
        with connect_readonly(paths.state_db) as conn:
            known = {
                row[0]
                for row in conn.execute(
                    "SELECT id FROM threads WHERE id IN (%s)"
                    % ",".join("?" * len(to_pin)),
                    to_pin,
                )
            }
        unknown = [t for t in to_pin if t not in known]
        if unknown:
            print("error: not found in state_5.sqlite (use --allow-unknown to override):", file=sys.stderr)
            for t in unknown:
                print(f"  {t}", file=sys.stderr)
            return 2

    new_pins = [p for p in pins if p not in set(args.unpin)]
    added = [t for t in to_pin if t not in new_pins]
    new_pins.extend(added)
    removed = [p for p in pins if p not in new_pins]

    print(f"current pins: {len(pins)}  ->  new pins: {len(new_pins)} (+{len(added)} / -{len(removed)})")
    for t in added:
        print(f"  + {t}")
    for t in removed:
        print(f"  - {t}")

    if new_pins == pins:
        print("pin list already up to date; nothing to write.")
        return 0

    if not args.apply:
        print("\ndry-run: no files were modified. Re-run with --apply to write.")
        return 0

    # --- write path -------------------------------------------------------
    running = detect_codex_processes()
    blocking = [p for p in running if p.get("pid")]
    if blocking:
        print("error: Codex Desktop appears to be running. Quit it fully first:", file=sys.stderr)
        for p in blocking[:10]:
            print(f"  pid {p['pid']}: {p['command']}", file=sys.stderr)
        return 3

    # The app rewrites this file with compact separators and raw UTF-8.
    # Refuse to write if we cannot reproduce the on-disk bytes exactly.
    if serialize_state(state) != raw:
        print(
            "error: round-trip mismatch — the on-disk JSON format is not the "
            "expected compact serialization. Aborting without changes.",
            file=sys.stderr,
        )
        return 4

    stamp = now_stamp()
    for target in (state_path, bak_path):
        copy = safety_copy(target, paths, stamp, "pin")
        if copy:
            print(f"safety copy: {copy}")

    state[PIN_KEY] = new_pins
    payload = serialize_state(state)

    for target in (state_path, bak_path):
        if not target.exists() and target is bak_path:
            continue
        if target is bak_path:
            # Keep .bak consistent with the main file, as the app does.
            bak_raw, bak_state = load_raw_state(target)
            if serialize_state(bak_state) != bak_raw:
                print(f"warning: {target.name} did not round-trip; leaving it untouched.")
                continue
            bak_state[PIN_KEY] = new_pins
            out = serialize_state(bak_state)
        else:
            out = payload
        tmp = target.with_name(target.name + f".tmp_{stamp}")
        tmp.write_text(out, encoding="utf-8")
        tmp.replace(target)
        print(f"wrote {target}")

    print("\ndone. Launch Codex Desktop and check the pinned section of the sidebar.")
    print("Verify persistence: quit the app fully and relaunch once.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
