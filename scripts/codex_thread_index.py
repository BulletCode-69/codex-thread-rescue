from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from codex_thread_rescue_common import (
    ThreadRecord,
    default_paths,
    fetch_threads,
)


# This tool is an ORGANIZER, not a repair tool.
#
# It only READS the local Codex state database to learn which threads exist,
# and then WRITES plain-Markdown index files (project-thread-index.md) so that
# every thread stays reachable with `codex resume <thread_id>` even when the
# Codex Desktop sidebar shows nothing.
#
# It never edits state_5.sqlite, session_index.jsonl, .codex-global-state.json,
# config.toml, or any rollout file. It never changes thread rows. It does not
# attempt to repair the sidebar. See docs/INDEX.md for the full method.


INDEX_FILENAME = "project-thread-index.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only: build per-project resume indexes (project-thread-index.md) from Codex state."
    )
    parser.add_argument("--codex-home", type=Path, help="Codex state directory. Default: CODEX_HOME or ~/.codex.")
    parser.add_argument("--scope", choices=("all", "prefix", "cwd"), default="all")
    parser.add_argument("--prefix", help="Only index project roots under this prefix when --scope prefix is used.")
    parser.add_argument("--cwd", help="Only index this exact project root when --scope cwd is used.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / ".codex-thread-rescue" / "index",
        help="Central, private directory for the generated index files. "
        "Default: ~/.codex-thread-rescue/index. This keeps files (which contain real "
        "thread ids and paths) out of your project repositories by default.",
    )
    parser.add_argument(
        "--master-index",
        type=Path,
        help="Where to write the master index table. Default: <out-dir>/project-thread-master-index.md.",
    )
    parser.add_argument(
        "--in-project-roots",
        action="store_true",
        help="Opt in to ALSO writing project-thread-index.md into each project's own root "
        "directory (scatters files with real ids/paths into your repos — off by default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the index files. Default is dry-run (report only, no files written).",
    )
    return parser.parse_args()


def expand_root(cwd: str, home: Path) -> Path | None:
    if not cwd:
        return None
    if cwd == "~":
        return home
    if cwd.startswith("~/"):
        return home / cwd[2:]
    return Path(cwd)


def sanitize(cwd: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", cwd).strip("-")
    return slug or "unknown-project"


def thread_title(thread: ThreadRecord) -> str:
    title = (thread.title or "").strip()
    return title or "(untitled)"


def sort_threads(threads: list[ThreadRecord]) -> list[ThreadRecord]:
    # updated_at descending, then thread id ascending for a stable, repeatable order.
    return sorted(threads, key=lambda t: (-(t.updated_at_ms or 0), t.id))


def render_project_index(cwd: str, threads: list[ThreadRecord], generated: str) -> str:
    display_cwd = cwd or "(no cwd)"
    lines = [
        "# Project Thread Index",
        "",
        f"最終更新: {generated}",
        f"cwd: {display_cwd}",
        f"スレッド数: {len(threads)}",
        "",
        "## スレッド一覧",
        "",
    ]
    for thread in sort_threads(threads):
        lines.extend(
            [
                f"### {thread_title(thread)}",
                "",
                f"thread_id: {thread.id}",
                f"resume: codex resume {thread.id}",
                f"updated_at: {thread.updated_iso or '(unknown)'}",
                f"cwd: {display_cwd}",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_master_index(rows: list[dict[str, Any]], generated: str) -> str:
    lines = [
        "# Codex Project Master Index",
        "",
        f"最終更新: {generated}",
        "",
        "| Project | Thread Count | Index Path |",
        "| --- | ---: | --- |",
    ]
    for row in rows:
        lines.append(f"| `{row['project']}` | {row['thread_count']} | `{row['index_path']}` |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    paths = default_paths(args.codex_home, None)
    home = paths.codex_home.parent if paths.codex_home.name == ".codex" else Path.home()
    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")

    threads = fetch_threads(paths, args.scope, args.prefix, args.cwd)

    archived_excluded = sum(1 for t in threads if not t.is_active)
    helper_excluded = sum(1 for t in threads if t.is_active and t.is_system_helper)
    no_user_event_excluded = sum(
        1 for t in threads if t.is_active and not t.is_system_helper and t.has_user_event != 1
    )

    # Enumerate projects from the THREAD ROWS' distinct cwd, not from saved-roots.
    # A project whose sidebar binding was lost may no longer be a saved root, but its
    # threads still exist here, so this is the only way to avoid missing them.
    visible = [t for t in threads if t.is_visible_candidate]
    by_cwd: dict[str, list[ThreadRecord]] = defaultdict(list)
    for thread in visible:
        by_cwd[thread.cwd].append(thread)

    # De-duplicate thread ids within each project (defensive; ids are primary keys).
    duplicate_ids = 0
    for cwd, items in by_cwd.items():
        seen: set[str] = set()
        deduped: list[ThreadRecord] = []
        for thread in items:
            if thread.id in seen:
                duplicate_ids += 1
                continue
            seen.add(thread.id)
            deduped.append(thread)
        by_cwd[cwd] = deduped

    out_dir = args.out_dir
    master_index = args.master_index or out_dir / "project-thread-master-index.md"

    master_rows: list[dict[str, Any]] = []
    planned_writes: list[dict[str, Any]] = []
    errors = 0

    for cwd in sorted(by_cwd):
        items = by_cwd[cwd]
        content = render_project_index(cwd, items, generated)
        # Primary copy always lives in the central private directory, so files that
        # contain real thread ids and paths stay out of your project repositories.
        central_path = out_dir / f"{sanitize(cwd or 'no-cwd')}.{INDEX_FILENAME}"
        planned_writes.append(
            {"cwd": cwd or "(no cwd)", "path": central_path, "content": content, "location": "central"}
        )
        # Optionally ALSO drop a copy into the project's own root.
        if args.in_project_roots:
            root = expand_root(cwd, home)
            if root is not None and root.is_dir():
                planned_writes.append(
                    {
                        "cwd": cwd or "(no cwd)",
                        "path": root / INDEX_FILENAME,
                        "content": content,
                        "location": "project-root",
                    }
                )
        master_rows.append(
            {
                "project": cwd or "(no cwd)",
                "thread_count": len(items),
                "index_path": str(central_path),
            }
        )

    created = 0
    if args.apply:
        for write in planned_writes:
            try:
                write["path"].parent.mkdir(parents=True, exist_ok=True)
                write["path"].write_text(write["content"], encoding="utf-8")
                created += 1
            except OSError as exc:
                errors += 1
                print(f"index write failed for {write['cwd']}: {exc}", file=sys.stderr)
        try:
            master_index.parent.mkdir(parents=True, exist_ok=True)
            master_index.write_text(render_master_index(master_rows, generated), encoding="utf-8")
        except OSError as exc:
            errors += 1
            print(f"master index write failed: {exc}", file=sys.stderr)

    report = {
        "dry_run": not args.apply,
        "projects_targeted": len(by_cwd),
        "indexes_planned": len(planned_writes),
        "indexes_created": created if args.apply else 0,
        "total_threads_indexed": sum(len(items) for items in by_cwd.values()),
        "archived_excluded": archived_excluded,
        "helper_excluded": helper_excluded,
        "missing_user_event_excluded": no_user_event_excluded,
        "duplicate_thread_ids_dropped": duplicate_ids,
        "index_errors": errors,
        "master_index": str(master_index),
    }

    print("# Codex Thread Index — Run Report")
    print("")
    print("| Metric | Value |")
    print("| --- | ---: |")
    print(f"| dry_run | {report['dry_run']} |")
    print(f"| projects_targeted | {report['projects_targeted']} |")
    print(f"| indexes_planned | {report['indexes_planned']} |")
    print(f"| indexes_created | {report['indexes_created']} |")
    print(f"| total_threads_indexed | {report['total_threads_indexed']} |")
    print(f"| archived_excluded | {report['archived_excluded']} |")
    print(f"| helper_excluded | {report['helper_excluded']} |")
    print(f"| missing_user_event_excluded | {report['missing_user_event_excluded']} |")
    print(f"| duplicate_thread_ids_dropped | {report['duplicate_thread_ids_dropped']} |")
    print(f"| index_errors | {report['index_errors']} |")
    print("")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"codex_thread_index failed: {exc}", file=sys.stderr)
        raise
