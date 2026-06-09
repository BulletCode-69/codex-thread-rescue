from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# This helper lives in experimental/; the shared module is in ../scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from codex_thread_rescue_common import (
    atomic_write_text,
    canonical_index_lines,
    default_paths,
    detect_codex_processes,
    fetch_threads,
    now_stamp,
    read_session_index_records,
    safety_copy,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely rebuild Codex session_index.jsonl from the SQLite thread table."
    )
    parser.add_argument("--codex-home", type=Path, help="Codex state directory. Default: CODEX_HOME or ~/.codex.")
    parser.add_argument("--safety-dir", type=Path, help="Directory for safety copies and optional audits.")
    parser.add_argument("--scope", choices=("all", "prefix", "cwd"), default="all")
    parser.add_argument("--prefix", help="Only rebuild records under this prefix when --scope prefix is used.")
    parser.add_argument("--cwd", help="Only rebuild records for this exact project root when --scope cwd is used.")
    parser.add_argument("--apply", action="store_true", help="Rewrite session_index.jsonl. Default is dry-run.")
    parser.add_argument(
        "--allow-while-running",
        action="store_true",
        help="Allow apply while Codex appears to be running. This can be overwritten by Desktop state.",
    )
    parser.add_argument("--audit", action="store_true", help="Write an audit JSON into the safety directory.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = default_paths(args.codex_home, args.safety_dir)
    stamp = now_stamp()
    threads = fetch_threads(paths, args.scope, args.prefix, args.cwd)
    visible_threads = [thread for thread in threads if thread.is_visible_candidate]
    canonical_lines = canonical_index_lines(visible_threads)
    records = read_session_index_records(paths)

    if args.scope == "all":
        kept_lines: list[str] = []
        removed_records = len(records)
    else:
        target_ids = {thread.id for thread in threads}
        kept_lines = [
            record["line"]
            for record in records
            if record["id"] is None or record["id"] not in target_ids
        ]
        removed_records = len(records) - len(kept_lines)

    final_lines = kept_lines + canonical_lines
    apply_block = None
    safety_path = None
    if args.apply:
        processes = detect_codex_processes()
        if processes and not args.allow_while_running:
            apply_block = {
                "reason": "Codex appears to be running. Quit Codex Desktop first, then rerun with --apply.",
                "matched_process_count": len(processes),
            }
        else:
            safety_path = safety_copy(paths.session_index, paths, stamp, "session-index")
            atomic_write_text(paths.session_index, "\n".join(final_lines) + "\n", stamp)

    payload = {
        "dry_run": not args.apply or apply_block is not None,
        "applied": bool(args.apply and apply_block is None),
        "blocked": apply_block,
        "scope": args.scope,
        "prefix": args.prefix,
        "cwd": args.cwd,
        "session_index": str(paths.session_index),
        "safety_copy": safety_path,
        "stats": {
            "original_records": len(records),
            "kept_records": len(kept_lines),
            "removed_target_records": removed_records,
            "canonical_records": len(canonical_lines),
            "final_records": len(final_lines),
            "visible_threads": len(visible_threads),
        },
    }
    if args.audit:
        audit_path = paths.safety_dir / f"rebuild-index-{stamp}.json"
        write_json(audit_path, payload)
        payload["audit"] = str(audit_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if apply_block else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"codex_thread_rebuild_index failed: {exc}", file=sys.stderr)
        raise
