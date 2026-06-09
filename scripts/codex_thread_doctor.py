from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codex_thread_rescue_common import (
    build_inspection,
    default_paths,
    detect_codex_processes,
    format_inspection_markdown,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Codex Desktop thread visibility doctor.")
    parser.add_argument("--codex-home", type=Path, help="Codex state directory. Default: CODEX_HOME or ~/.codex.")
    parser.add_argument("--safety-dir", type=Path, help="Directory for safety copies created by other tools.")
    parser.add_argument("--scope", choices=("all", "prefix", "cwd"), default="all")
    parser.add_argument("--prefix", help="Only inspect project roots under this prefix when --scope prefix is used.")
    parser.add_argument("--cwd", help="Only inspect this exact project root when --scope cwd is used.")
    parser.add_argument("--json", type=Path, help="Write the full read-only inspection JSON.")
    parser.add_argument("--markdown", type=Path, help="Write a Markdown report.")
    parser.add_argument("--no-redact", action="store_true", help="Show full local paths in generated reports.")
    parser.add_argument("--include-processes", action="store_true", help="Include Codex-related process matches.")
    parser.add_argument(
        "--verify-ui-readiness",
        action="store_true",
        help="Exit non-zero when checks suggest the Desktop sidebar may still show missing chats.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = default_paths(args.codex_home, args.safety_dir)
    inspection = build_inspection(
        paths,
        scope=args.scope,
        prefix=args.prefix,
        cwd=args.cwd,
        redact=not args.no_redact,
    )
    if args.include_processes:
        inspection["codex_processes"] = detect_codex_processes()

    if args.json:
        write_json(args.json, inspection)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(format_inspection_markdown(inspection), encoding="utf-8")

    summary = {
        "ui_ready": inspection["ui_ready"],
        "db_integrity": inspection["db_integrity"],
        "totals": inspection["totals"],
        "critical_counts": inspection["critical_counts"],
        "generated": {
            "json": str(args.json) if args.json else None,
            "markdown": str(args.markdown) if args.markdown else None,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.verify_ui_readiness and not inspection["ui_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"codex_thread_doctor failed: {exc}", file=sys.stderr)
        raise
