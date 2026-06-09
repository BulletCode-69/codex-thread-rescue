from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

# This helper lives in experimental/; the shared module is in ../scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from codex_thread_rescue_common import (
    atomic_write_text,
    canonical_thread_project_assignment,
    default_paths,
    detect_codex_processes,
    fetch_threads,
    now_stamp,
    project_label,
    project_order_from_state,
    read_global_state,
    safety_copy,
    saved_roots_from_state,
    sidebar_collapsed_groups_from_state,
    thread_project_assignment_matches_thread,
    thread_project_assignments_from_state,
    thread_workspace_root_hints_from_state,
    toml_escape_basic_string,
    config_project_roots,
    persisted_atom_state_from_state,
    redacted_path,
    workspace_root_labels_from_state,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair Codex Desktop project-sidebar display metadata without editing thread rows."
    )
    parser.add_argument("--codex-home", type=Path, help="Codex state directory. Default: CODEX_HOME or ~/.codex.")
    parser.add_argument("--safety-dir", type=Path, help="Directory for safety copies and optional audits.")
    parser.add_argument("--scope", choices=("all", "prefix", "cwd"), default="all")
    parser.add_argument("--prefix", help="Only repair project roots under this prefix when --scope prefix is used.")
    parser.add_argument("--cwd", help="Only repair this exact project root when --scope cwd is used.")
    parser.add_argument("--apply", action="store_true", help="Edit local Codex metadata. Default is dry-run.")
    parser.add_argument("--update-config", action="store_true", help="Add missing [projects] entries to config.toml.")
    parser.add_argument(
        "--reset-backfill-flag",
        action="store_true",
        help="Set remote-project-connection-backfill-completed to false when that key already exists.",
    )
    parser.add_argument(
        "--allow-while-running",
        action="store_true",
        help="Allow apply while Codex appears to be running. This can be overwritten by Desktop state.",
    )
    parser.add_argument("--no-redact", action="store_true", help="Show full local paths in command output.")
    parser.add_argument("--audit", action="store_true", help="Write an audit JSON into the safety directory.")
    return parser.parse_args()


def visible_project_state(paths, scope: str, prefix: str | None, cwd: str | None):
    threads = fetch_threads(paths, scope, prefix, cwd)
    visible_threads = [thread for thread in threads if thread.is_visible_candidate and thread.cwd]
    cwd_latest: dict[str, int] = {}
    for thread in visible_threads:
        cwd_latest[thread.cwd] = max(cwd_latest.get(thread.cwd, 0), thread.updated_at_ms or 0)
    ordered_cwds = sorted(cwd_latest, key=lambda item: (-cwd_latest[item], item))
    return threads, visible_threads, ordered_cwds


def redact_change(value: Any, redact: bool) -> Any:
    if not redact:
        return value
    if isinstance(value, str):
        return redacted_path(value)
    if isinstance(value, list):
        return [redact_change(item, redact=True) for item in value]
    if isinstance(value, dict):
        return {key: redact_change(item, redact=True) for key, item in value.items()}
    return value


def append_config_projects(current: str, added_projects: list[str]) -> str:
    if current and not current.endswith("\n"):
        current += "\n"
    blocks = []
    for cwd in added_projects:
        escaped = toml_escape_basic_string(cwd)
        blocks.append(f'\n[projects."{escaped}"]\ntrust_level = "trusted"\n')
    return current + "".join(blocks)


def plan_global_state_changes(
    state: dict[str, Any],
    visible_threads,
    ordered_cwds: list[str],
    *,
    reset_backfill_flag: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    next_state = copy.deepcopy(state)
    saved = saved_roots_from_state(next_state)
    ordered = project_order_from_state(next_state)
    labels = workspace_root_labels_from_state(next_state)
    collapsed = sidebar_collapsed_groups_from_state(next_state)
    hints = thread_workspace_root_hints_from_state(next_state)
    assignments = thread_project_assignments_from_state(next_state)

    added_saved = [cwd for cwd in ordered_cwds if cwd not in set(saved)]
    added_order = [cwd for cwd in ordered_cwds if cwd not in set(ordered)]
    added_labels = [
        {"cwd": cwd, "label": project_label(cwd)}
        for cwd in ordered_cwds
        if not labels.get(cwd, "").strip()
    ]
    uncollapsed = [cwd for cwd in ordered_cwds if collapsed.get(cwd) is True]
    repaired_hints = [
        {"id": thread.id, "cwd": thread.cwd, "previous": hints.get(thread.id)}
        for thread in visible_threads
        if hints.get(thread.id) != thread.cwd
    ]
    repaired_assignments = [
        {
            "id": thread.id,
            "cwd": thread.cwd,
            "previous": assignments.get(thread.id),
            "expected": canonical_thread_project_assignment(thread),
        }
        for thread in visible_threads
        if not thread_project_assignment_matches_thread(thread, assignments.get(thread.id))
    ]

    if added_saved:
        next_state["electron-saved-workspace-roots"] = saved + added_saved
    if added_order:
        next_state["project-order"] = ordered + added_order
    if added_labels:
        raw_labels = next_state.get("electron-workspace-root-labels")
        if not isinstance(raw_labels, dict):
            raw_labels = {}
        for item in added_labels:
            raw_labels[item["cwd"]] = item["label"]
        next_state["electron-workspace-root-labels"] = raw_labels
    if uncollapsed:
        persisted = persisted_atom_state_from_state(next_state)
        collapsed_state = persisted.get("sidebar-collapsed-groups")
        if not isinstance(collapsed_state, dict):
            collapsed_state = {}
        for cwd in uncollapsed:
            collapsed_state.pop(cwd, None)
        persisted["sidebar-collapsed-groups"] = collapsed_state
        next_state["electron-persisted-atom-state"] = persisted
    if repaired_hints:
        raw_hints = next_state.get("thread-workspace-root-hints")
        if not isinstance(raw_hints, dict):
            raw_hints = {}
        for item in repaired_hints:
            raw_hints[item["id"]] = item["cwd"]
        next_state["thread-workspace-root-hints"] = raw_hints
    if repaired_assignments:
        raw_assignments = next_state.get("thread-project-assignments")
        if not isinstance(raw_assignments, dict):
            raw_assignments = {}
        for item in repaired_assignments:
            raw_assignments[item["id"]] = item["expected"]
        next_state["thread-project-assignments"] = raw_assignments

    backfill_change = None
    key = "remote-project-connection-backfill-completed"
    if reset_backfill_flag and key in next_state:
        before = next_state.get(key)
        next_state[key] = False
        backfill_change = {"key": key, "before": before, "after": False}

    changes = {
        "added_saved_roots": added_saved,
        "added_project_order": added_order,
        "added_workspace_labels": added_labels,
        "uncollapsed_roots": uncollapsed,
        "repaired_thread_workspace_root_hints": repaired_hints,
        "repaired_thread_project_assignments": repaired_assignments,
        "backfill_flag": backfill_change,
    }
    return next_state, changes


def has_global_state_change(changes: dict[str, Any]) -> bool:
    return any(bool(value) for value in changes.values())


def main() -> int:
    args = parse_args()
    paths = default_paths(args.codex_home, args.safety_dir)
    stamp = now_stamp()
    _, visible_threads, ordered_cwds = visible_project_state(paths, args.scope, args.prefix, args.cwd)
    state = read_global_state(paths)
    next_state, global_changes = plan_global_state_changes(
        state,
        visible_threads,
        ordered_cwds,
        reset_backfill_flag=args.reset_backfill_flag,
    )

    existing_config = config_project_roots(paths)
    added_config_projects = [cwd for cwd in ordered_cwds if cwd not in set(existing_config)]
    should_update_config = bool(args.update_config and added_config_projects)
    apply_block = None
    global_safety = None
    config_safety = None

    if args.apply:
        processes = detect_codex_processes()
        if processes and not args.allow_while_running:
            apply_block = {
                "reason": "Codex appears to be running. Quit Codex Desktop first, then rerun with --apply.",
                "matched_process_count": len(processes),
            }
        elif not paths.global_state.exists():
            apply_block = {"reason": "Missing .codex-global-state.json; refusing to create it automatically."}
        else:
            if has_global_state_change(global_changes):
                global_safety = safety_copy(paths.global_state, paths, stamp, "global-state")
                atomic_write_text(
                    paths.global_state,
                    json.dumps(next_state, ensure_ascii=False, indent=2) + "\n",
                    stamp,
                )
            if should_update_config:
                config_safety = safety_copy(paths.config_toml, paths, stamp, "config")
                current = (
                    paths.config_toml.read_text(encoding="utf-8", errors="replace")
                    if paths.config_toml.exists()
                    else ""
                )
                atomic_write_text(paths.config_toml, append_config_projects(current, added_config_projects), stamp)

    payload = {
        "dry_run": not args.apply or apply_block is not None,
        "applied": bool(args.apply and apply_block is None),
        "blocked": apply_block,
        "scope": args.scope,
        "prefix": args.prefix,
        "cwd": args.cwd,
        "visible_threads": len(visible_threads),
        "target_cwds": redact_change(ordered_cwds, redact=not args.no_redact),
        "global_state": str(paths.global_state),
        "config_toml": str(paths.config_toml),
        "safety_copies": {
            "global_state": global_safety,
            "config_toml": config_safety,
        },
        "planned_global_state_changes": redact_change(global_changes, redact=not args.no_redact),
        "planned_config_changes": {
            "enabled": args.update_config,
            "added_projects": redact_change(added_config_projects if args.update_config else [], redact=not args.no_redact),
        },
    }
    if args.audit:
        audit_path = paths.safety_dir / f"rebind-metadata-{stamp}.json"
        write_json(audit_path, payload)
        payload["audit"] = str(audit_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if apply_block else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"codex_thread_rebind_metadata failed: {exc}", file=sys.stderr)
        raise
