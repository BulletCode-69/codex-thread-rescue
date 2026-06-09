from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from codex_thread_rescue_common import (
    ThreadRecord,
    default_paths,
    fetch_threads,
)


# Read-only resume launcher.
#
# When the Codex Desktop sidebar hides a project's threads, the conversations are
# still in state_5.sqlite and can be reopened with `codex resume <thread_id>`.
# This tool reads the thread list read-only and helps you pick one to resume.
#
# It NEVER edits state_5.sqlite, session_index.jsonl, .codex-global-state.json,
# config.toml, or any rollout file. It does not try to repair the sidebar. By
# default it only PRINTS the resume command; pass --exec to actually launch it.
#
# "Reviving" a thread here means reopening it with codex resume — the durable
# path. It does not push threads back into the sidebar (that does not persist;
# only pinning does). Resume the ones you need, and pin the few you want to keep
# visible.


def title_of(thread: ThreadRecord) -> str:
    return (thread.title or "").strip() or "(untitled)"


def select_threads(
    threads: list[ThreadRecord], query: str | None, scope_label: str
) -> list[ThreadRecord]:
    visible = [t for t in threads if t.is_visible_candidate]
    if query:
        q = query.lower()
        visible = [
            t for t in visible if q in title_of(t).lower() or q in t.id.lower() or q in (t.cwd or "").lower()
        ]
    return sorted(visible, key=lambda t: (-(t.updated_at_ms or 0), t.id))


def print_table(threads: list[ThreadRecord]) -> None:
    if not threads:
        print("No matching user threads found.")
        return
    width = len(str(len(threads)))
    for i, thread in enumerate(threads, 1):
        print(f"{str(i).rjust(width)}. {title_of(thread)}")
        print(f"{' ' * (width + 2)}id: {thread.id}   updated: {thread.updated_iso or '(unknown)'}")
        print(f"{' ' * (width + 2)}cwd: {thread.cwd or '(no cwd)'}")
        print(f"{' ' * (width + 2)}resume: codex resume {thread.id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only: list user threads and resume one with `codex resume <thread_id>`."
    )
    parser.add_argument("--codex-home", type=Path, help="Codex state directory. Default: CODEX_HOME or ~/.codex.")
    parser.add_argument("--scope", choices=("all", "prefix", "cwd"), default="all")
    parser.add_argument("--prefix", help="Only consider project roots under this prefix when --scope prefix is used.")
    parser.add_argument("--cwd", help="Only consider this exact project root when --scope cwd is used.")
    parser.add_argument("--query", help="Filter by substring of title, thread id, or cwd.")
    parser.add_argument("--limit", type=int, default=0, help="Show at most N threads (0 = no limit).")
    parser.add_argument("--list", action="store_true", help="Just print the table and exit (no prompt).")
    parser.add_argument(
        "--exec",
        action="store_true",
        help="Run `codex resume <id>` for the chosen thread instead of only printing it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = default_paths(args.codex_home, None)
    threads = fetch_threads(paths, args.scope, args.prefix, args.cwd)
    selected = select_threads(threads, args.query, args.scope)
    if args.limit and args.limit > 0:
        selected = selected[: args.limit]

    print_table(selected)
    if args.list or not selected:
        return 0

    print("")
    try:
        raw = input(f"Resume which? [1-{len(selected)}, or blank to cancel]: ").strip()
    except EOFError:
        return 0
    if not raw:
        return 0
    try:
        choice = int(raw)
        if not 1 <= choice <= len(selected):
            raise ValueError
    except ValueError:
        print(f"Not a valid choice: {raw}", file=sys.stderr)
        return 1

    thread = selected[choice - 1]
    command = ["codex", "resume", thread.id]
    if args.exec:
        print(f"Running: {' '.join(command)}")
        try:
            return subprocess.run(command, check=False).returncode
        except FileNotFoundError:
            print("`codex` CLI not found on PATH. Run the command below manually:", file=sys.stderr)
            print(f"  {' '.join(command)}")
            return 127
    print("")
    print(f"  {' '.join(command)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"codex_thread_resume failed: {exc}", file=sys.stderr)
        raise
