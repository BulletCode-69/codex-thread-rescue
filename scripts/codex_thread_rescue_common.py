from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote


PROJECT_SECTION_RE = re.compile(r'^\[projects\."((?:\\.|[^"\\])*)"\]\s*$')
APPROVAL_REVIEW_PREFIX = (
    "The following is the Codex agent history whose request action you are assessing."
)


@dataclass(frozen=True)
class CodexPaths:
    codex_home: Path
    state_db: Path
    session_index: Path
    global_state: Path
    config_toml: Path
    safety_dir: Path


@dataclass(frozen=True)
class ThreadRecord:
    id: str
    title: str
    cwd: str
    archived: int
    has_user_event: int
    updated_at: int | None
    updated_at_ms: int | None
    source: str
    thread_source: str | None
    rollout_path: str
    first_user_message: str
    preview: str
    agent_nickname: str | None
    agent_role: str | None
    agent_path: str | None

    @property
    def is_active(self) -> bool:
        return self.archived == 0

    @property
    def is_system_helper(self) -> bool:
        return is_system_helper_values(
            title=self.title,
            source=self.source,
            thread_source=self.thread_source,
            first_user_message=self.first_user_message,
            preview=self.preview,
            agent_nickname=self.agent_nickname,
            agent_role=self.agent_role,
            agent_path=self.agent_path,
        )

    @property
    def is_user_thread(self) -> bool:
        return self.is_active and not self.is_system_helper

    @property
    def is_visible_candidate(self) -> bool:
        return self.is_user_thread and self.has_user_event == 1

    @property
    def updated_iso(self) -> str:
        return updated_iso(self.updated_at_ms)


def default_paths(codex_home: Path | None = None, safety_dir: Path | None = None) -> CodexPaths:
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return CodexPaths(
        codex_home=home,
        state_db=home / "state_5.sqlite",
        session_index=home / "session_index.jsonl",
        global_state=home / ".codex-global-state.json",
        config_toml=home / "config.toml",
        safety_dir=safety_dir or home / "thread-rescue-safety",
    )


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def generated_at() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def updated_iso(updated_at_ms: int | None) -> str:
    if not updated_at_ms:
        return ""
    return (
        dt.datetime.fromtimestamp(updated_at_ms / 1000, tz=dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def scope_filter(scope: str, prefix: str | None, cwd: str | None) -> tuple[str, tuple[str, ...]]:
    if scope == "all":
        return "1 = 1", ()
    if scope == "prefix":
        if not prefix:
            raise ValueError("--prefix is required with --scope prefix")
        return "cwd like ?", (f"{prefix}%",)
    if scope == "cwd":
        if not cwd:
            raise ValueError("--cwd is required with --scope cwd")
        return "cwd = ?", (cwd,)
    raise ValueError(f"unknown scope: {scope}")


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Open the SQLite database read-only so these tools can never write it.

    Uses a `file:...?mode=ro` URI. `mode=ro` (not `immutable`) is correct here
    because Codex may still be running and writing; we only guarantee that *we*
    cannot modify the database.
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing Codex state database: {path}")
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"pragma table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[1]) for row in rows}


# Columns we read, with a per-column default used when a future Codex schema
# drops or renames one. `id` and `cwd` are required; everything else degrades.
_THREAD_COLUMNS: tuple[str, ...] = (
    "id",
    "title",
    "cwd",
    "archived",
    "has_user_event",
    "updated_at",
    "updated_at_ms",
    "source",
    "thread_source",
    "rollout_path",
    "first_user_message",
    "preview",
    "agent_nickname",
    "agent_role",
    "agent_path",
)


def fetch_threads(paths: CodexPaths, scope: str, prefix: str | None, cwd: str | None) -> list[ThreadRecord]:
    clause, values = scope_filter(scope, prefix, cwd)
    conn = connect_readonly(paths.state_db)
    conn.row_factory = sqlite3.Row
    try:
        available = table_columns(conn, "threads")
        if not available:
            raise RuntimeError("Codex state database has no 'threads' table (schema changed?).")
        for required in ("id", "cwd"):
            if required not in available:
                raise RuntimeError(
                    f"Codex 'threads' table is missing the '{required}' column (schema changed?)."
                )
        select_cols = [col for col in _THREAD_COLUMNS if col in available]
        # Only order by sort keys that still exist, so a schema change cannot crash the query.
        order_terms = [
            f"{col} desc" for col in ("updated_at_ms", "updated_at") if col in available
        ]
        order_clause = f"order by {', '.join(order_terms)}" if order_terms else ""
        rows = conn.execute(
            f"select {', '.join(select_cols)} from threads where {clause} {order_clause}",
            values,
        ).fetchall()
    finally:
        conn.close()

    present = set(select_cols)

    def value(row: sqlite3.Row, col: str) -> Any:
        return row[col] if col in present else None

    return [
        ThreadRecord(
            id=value(row, "id"),
            title=value(row, "title") or "",
            cwd=value(row, "cwd") or "",
            archived=value(row, "archived") or 0,
            has_user_event=value(row, "has_user_event") or 0,
            updated_at=value(row, "updated_at"),
            updated_at_ms=value(row, "updated_at_ms"),
            source=value(row, "source") or "",
            thread_source=value(row, "thread_source"),
            rollout_path=value(row, "rollout_path") or "",
            first_user_message=value(row, "first_user_message") or "",
            preview=value(row, "preview") or "",
            agent_nickname=value(row, "agent_nickname"),
            agent_role=value(row, "agent_role"),
            agent_path=value(row, "agent_path"),
        )
        for row in rows
    ]


def read_session_index_records(paths: CodexPaths) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not paths.session_index.exists():
        return records
    lines = paths.session_index.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            records.append({"line_number": line_number, "line": line, "parsed": None, "id": None})
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            records.append({"line_number": line_number, "line": line, "parsed": None, "id": None})
            continue
        thread_id = parsed.get("id")
        records.append(
            {
                "line_number": line_number,
                "line": line,
                "parsed": parsed,
                "id": thread_id if isinstance(thread_id, str) else None,
            }
        )
    return records


def read_global_state(paths: CodexPaths) -> dict[str, Any]:
    if not paths.global_state.exists():
        return {}
    return json.loads(paths.global_state.read_text(encoding="utf-8", errors="replace"))


def saved_roots_from_state(state: dict[str, Any]) -> list[str]:
    roots = state.get("electron-saved-workspace-roots") or []
    return [str(root) for root in roots if isinstance(root, str)]


def project_order_from_state(state: dict[str, Any]) -> list[str]:
    roots = state.get("project-order") or []
    return [str(root) for root in roots if isinstance(root, str)]


def workspace_root_labels_from_state(state: dict[str, Any]) -> dict[str, str]:
    labels = state.get("electron-workspace-root-labels") or {}
    if not isinstance(labels, dict):
        return {}
    return {
        str(root): str(label)
        for root, label in labels.items()
        if isinstance(root, str) and isinstance(label, str)
    }


def persisted_atom_state_from_state(state: dict[str, Any]) -> dict[str, Any]:
    persisted = state.get("electron-persisted-atom-state") or {}
    return persisted if isinstance(persisted, dict) else {}


def sidebar_collapsed_groups_from_state(state: dict[str, Any]) -> dict[str, bool]:
    collapsed = persisted_atom_state_from_state(state).get("sidebar-collapsed-groups") or {}
    if not isinstance(collapsed, dict):
        return {}
    return {
        str(root): bool(value)
        for root, value in collapsed.items()
        if isinstance(root, str) and value is True
    }


def thread_workspace_root_hints_from_state(state: dict[str, Any]) -> dict[str, str]:
    hints = state.get("thread-workspace-root-hints") or {}
    if not isinstance(hints, dict):
        return {}
    return {
        str(thread_id): str(root)
        for thread_id, root in hints.items()
        if isinstance(thread_id, str) and isinstance(root, str)
    }


def thread_project_assignments_from_state(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assignments = state.get("thread-project-assignments") or {}
    if not isinstance(assignments, dict):
        return {}
    return {
        str(thread_id): assignment
        for thread_id, assignment in assignments.items()
        if isinstance(thread_id, str) and isinstance(assignment, dict)
    }


def canonical_thread_project_assignment(thread: ThreadRecord) -> dict[str, Any]:
    return {
        "projectKind": "local",
        "projectId": thread.cwd,
        "path": thread.cwd,
        "cwd": thread.cwd,
        "pendingCoreUpdate": False,
    }


def thread_project_assignment_matches_thread(
    thread: ThreadRecord, assignment: dict[str, Any] | None
) -> bool:
    if not assignment or not thread.cwd:
        return False
    if assignment.get("projectKind") != "local":
        return False
    if assignment.get("projectId") != thread.cwd:
        return False
    if assignment.get("path") not in (None, "", thread.cwd):
        return False
    if assignment.get("cwd") not in (None, "", thread.cwd):
        return False
    return assignment.get("pendingCoreUpdate") is not True


def _toml_unescape(value: str) -> str:
    return (
        value.replace(r"\\", "\\")
        .replace(r"\"", '"')
        .replace(r"\n", "\n")
        .replace(r"\t", "\t")
    )


def toml_escape_basic_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def config_project_roots(paths: CodexPaths) -> list[str]:
    if not paths.config_toml.exists():
        return []
    roots: list[str] = []
    lines = paths.config_toml.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines:
        match = PROJECT_SECTION_RE.match(line.strip())
        if match:
            roots.append(_toml_unescape(match.group(1)))
    return roots


def is_system_helper_values(
    *,
    title: str | None,
    source: str | None,
    thread_source: str | None,
    first_user_message: str | None,
    preview: str | None,
    agent_nickname: str | None = None,
    agent_role: str | None = None,
    agent_path: str | None = None,
) -> bool:
    text_fields = (title or "", first_user_message or "", preview or "")
    if any(text.startswith(APPROVAL_REVIEW_PREFIX) for text in text_fields):
        return True
    source_text = source or ""
    if thread_source == "subagent" or '"subagent"' in source_text:
        return True
    helper_markers = (agent_nickname or "", agent_role or "", agent_path or "")
    lowered = " ".join(helper_markers).lower()
    return any(marker in lowered for marker in ("guardian", "worker", "explorer", "auto-review"))


def check_sqlite_integrity(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        conn = connect_readonly(path)
        result = conn.execute("pragma integrity_check").fetchone()
    except sqlite3.Error as exc:
        return f"error: {exc}"
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass
    if not result:
        return "error: no integrity_check result"
    return str(result[0])


def detect_codex_processes() -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["ps", "ax", "-o", "pid=,comm=,args="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        return [{"pid": None, "command": f"process_detection_unavailable: {exc}"}]
    if completed.returncode != 0:
        return [{"pid": None, "command": f"process_detection_unavailable: ps exit {completed.returncode}"}]

    processes: list[dict[str, Any]] = []
    ignored = ("node_repl", "kernel.js --session-id", "--listen stdio://")
    needles = ("Codex.app/Contents/MacOS/Codex", "Codex Helper", "codex app-server", "codex desktop")
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_part, _, rest = stripped.partition(" ")
        try:
            pid = int(pid_part)
        except ValueError:
            continue
        lowered = rest.lower()
        if any(item.lower() in lowered for item in ignored):
            continue
        if any(item.lower() in lowered for item in needles):
            processes.append({"pid": pid, "command": rest})
    return processes


def canonical_session_index_record(thread: ThreadRecord) -> dict[str, str]:
    return {
        "id": thread.id,
        "thread_name": thread.title or "",
        "updated_at": thread.updated_iso,
    }


def canonical_index_lines(threads: Iterable[ThreadRecord]) -> list[str]:
    ordered = sorted(threads, key=lambda thread: ((thread.updated_at_ms or 0), thread.id))
    return [
        json.dumps(canonical_session_index_record(thread), ensure_ascii=False)
        for thread in ordered
    ]


def atomic_write_text(path: Path, text: str, stamp: str) -> None:
    temp = path.with_name(f"{path.name}.tmp_{stamp}")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


def safety_copy(path: Path, paths: CodexPaths, stamp: str, label: str) -> str | None:
    if not path.exists():
        return None
    paths.safety_dir.mkdir(parents=True, exist_ok=True)
    target = paths.safety_dir / f"{path.name}.{label}.{stamp}.copy"
    shutil.copy2(path, target)
    return str(target)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def redacted_path(value: str, home: Path | None = None) -> str:
    if not value:
        return value
    home_text = str(home or Path.home())
    if value == home_text:
        return "~"
    if value.startswith(home_text + os.sep):
        return "~" + value[len(home_text):]
    return value


def redacted_paths(values: Iterable[str], home: Path | None = None) -> list[str]:
    return [redacted_path(value, home=home) for value in values]


def project_label(cwd: str) -> str:
    if not cwd:
        return ""
    leaf = Path(cwd).name
    return leaf or cwd


def build_inspection(
    paths: CodexPaths,
    scope: str,
    prefix: str | None,
    cwd: str | None,
    *,
    redact: bool = True,
) -> dict[str, Any]:
    threads = fetch_threads(paths, scope, prefix, cwd)
    index_records = read_session_index_records(paths)
    state = read_global_state(paths)
    saved_roots = saved_roots_from_state(state)
    project_order = project_order_from_state(state)
    labels = workspace_root_labels_from_state(state)
    collapsed = sidebar_collapsed_groups_from_state(state)
    hints = thread_workspace_root_hints_from_state(state)
    assignments = thread_project_assignments_from_state(state)
    config_roots = config_project_roots(paths)
    index_ids = [record["id"] for record in index_records if record["id"]]
    index_counts = Counter(index_ids)

    active = [thread for thread in threads if thread.is_active]
    helpers = [thread for thread in active if thread.is_system_helper]
    user_threads = [thread for thread in active if not thread.is_system_helper]
    visible = [thread for thread in user_threads if thread.has_user_event == 1]
    missing_user_event = [thread for thread in user_threads if thread.has_user_event != 1]
    hidden = [
        thread
        for thread in user_threads
        if thread.source != "vscode" or thread.thread_source not in (None, "", "user")
    ]
    archived = [thread for thread in threads if not thread.is_active]
    missing_index = [thread for thread in visible if index_counts[thread.id] == 0]
    duplicate_visible_ids = {
        thread_id: count
        for thread_id, count in sorted(index_counts.items())
        if thread_id in {thread.id for thread in visible} and count > 1
    }

    cwd_latest: dict[str, int] = defaultdict(int)
    for thread in visible:
        if thread.cwd:
            cwd_latest[thread.cwd] = max(cwd_latest[thread.cwd], thread.updated_at_ms or 0)
    target_cwds = sorted(cwd_latest, key=lambda item: (-cwd_latest[item], item))
    missing_saved_roots = [item for item in target_cwds if item not in set(saved_roots)]
    missing_project_order = [item for item in target_cwds if item not in set(project_order)]
    missing_config_projects = [item for item in target_cwds if item not in set(config_roots)]
    missing_labels = [item for item in target_cwds if not labels.get(item, "").strip()]
    collapsed_visible_roots = [item for item in target_cwds if collapsed.get(item) is True]
    missing_hints = [thread for thread in visible if thread.cwd and hints.get(thread.id) is None]
    stale_hints = [
        {"id": thread.id, "expected": thread.cwd, "actual": hints.get(thread.id)}
        for thread in visible
        if thread.cwd and hints.get(thread.id) is not None and hints.get(thread.id) != thread.cwd
    ]
    missing_assignments = [
        thread for thread in visible if thread.cwd and assignments.get(thread.id) is None
    ]
    stale_assignments = [
        {"id": thread.id, "expected": canonical_thread_project_assignment(thread), "actual": assignments.get(thread.id)}
        for thread in visible
        if thread.cwd
        and assignments.get(thread.id) is not None
        and not thread_project_assignment_matches_thread(thread, assignments.get(thread.id))
    ]
    rollout_missing = [
        thread for thread in threads if thread.rollout_path and not Path(thread.rollout_path).exists()
    ]

    by_cwd: dict[str, list[ThreadRecord]] = defaultdict(list)
    for thread in threads:
        by_cwd[thread.cwd].append(thread)

    projects = []
    all_project_roots = sorted(set(target_cwds) | set(saved_roots) | set(config_roots))
    for project_root in all_project_roots:
        items = by_cwd.get(project_root, [])
        active_items = [thread for thread in items if thread.is_active]
        helper_items = [thread for thread in active_items if thread.is_system_helper]
        user_items = [thread for thread in active_items if not thread.is_system_helper]
        visible_items = [thread for thread in user_items if thread.has_user_event == 1]
        status = "OK_VISIBLE"
        if project_root in missing_saved_roots:
            status = "MISSING_SAVED_ROOT"
        if project_root in missing_project_order:
            status = "MISSING_PROJECT_ORDER"
        if project_root in missing_config_projects:
            status = "MISSING_CONFIG_PROJECT"
        if project_root in missing_labels:
            status = "MISSING_WORKSPACE_LABEL"
        if project_root in collapsed_visible_roots:
            status = "SIDEBAR_COLLAPSED"
        if any(thread.id in {item.id for item in missing_hints} for thread in visible_items):
            status = "MISSING_THREAD_WORKSPACE_HINT"
        if any(thread.id in {item.id for item in missing_assignments} for thread in visible_items):
            status = "MISSING_THREAD_PROJECT_ASSIGNMENT"
        if any(thread.id in {item.id for item in missing_index} for thread in visible_items):
            status = "INDEX_GAP"
        if any(thread.has_user_event != 1 for thread in user_items):
            status = "MISSING_USER_EVENT"
        if any(
            thread.source != "vscode" or thread.thread_source not in (None, "", "user")
            for thread in user_items
        ):
            status = "HIDDEN"
        if items and not visible_items and any(not thread.is_active for thread in items):
            status = "ONLY_ARCHIVED"
        if project_root in saved_roots and not items:
            status = "EMPTY_SAVED_PROJECT"
        projects.append(
            {
                "cwd": redacted_path(project_root) if redact else project_root,
                "saved_project": project_root in set(saved_roots),
                "project_ordered": project_root in set(project_order),
                "config_project": project_root in set(config_roots),
                "workspace_label": labels.get(project_root, ""),
                "sidebar_collapsed": collapsed.get(project_root) is True,
                "total": len(items),
                "active": len(active_items),
                "visible_candidates": len(visible_items),
                "system_helpers": len(helper_items),
                "archived": len([thread for thread in items if not thread.is_active]),
                "status": status,
            }
        )

    critical_counts = {
        "hidden_user_threads": len(hidden),
        "missing_user_event": len(missing_user_event),
        "missing_index": len(missing_index),
        "duplicate_visible_index_ids": len(duplicate_visible_ids),
        "missing_saved_roots": len(missing_saved_roots),
        "missing_project_order": len(missing_project_order),
        "missing_config_projects": len(missing_config_projects),
        "missing_workspace_labels": len(missing_labels),
        "collapsed_visible_roots": len(collapsed_visible_roots),
        "missing_thread_workspace_root_hints": len(missing_hints),
        "stale_thread_workspace_root_hints": len(stale_hints),
        "missing_thread_project_assignments": len(missing_assignments),
        "stale_thread_project_assignments": len(stale_assignments),
        "rollout_missing": len(rollout_missing),
    }
    db_integrity = check_sqlite_integrity(paths.state_db)
    ui_ready = db_integrity == "ok" and all(value == 0 for value in critical_counts.values())
    redact_value = redacted_path if redact else lambda item: item
    return {
        "generated_at": generated_at(),
        "scope": scope,
        "prefix": redact_value(prefix) if prefix else None,
        "cwd": redact_value(cwd) if cwd else None,
        "paths": {
            "codex_home": redacted_path(str(paths.codex_home)) if redact else str(paths.codex_home),
            "state_db": redacted_path(str(paths.state_db)) if redact else str(paths.state_db),
            "session_index": redacted_path(str(paths.session_index)) if redact else str(paths.session_index),
            "global_state": redacted_path(str(paths.global_state)) if redact else str(paths.global_state),
            "config_toml": redacted_path(str(paths.config_toml)) if redact else str(paths.config_toml),
            "safety_dir": redacted_path(str(paths.safety_dir)) if redact else str(paths.safety_dir),
        },
        "db_integrity": db_integrity,
        "ui_ready": ui_ready,
        "totals": {
            "threads": len(threads),
            "active": len(active),
            "visible_candidates": len(visible),
            "system_helpers": len(helpers),
            "archived": len(archived),
            "session_index_records": len(index_records),
            "session_index_unique_ids": len(index_counts),
            "session_index_invalid_records": len([item for item in index_records if item["parsed"] is None]),
            "target_cwds": len(target_cwds),
            "saved_roots": len(saved_roots),
            "project_order": len(project_order),
            "workspace_labels": len(labels),
            "thread_workspace_root_hints": len(hints),
            "thread_project_assignments": len(assignments),
            "config_projects": len(config_roots),
        },
        "critical_counts": critical_counts,
        "target_cwds": redacted_paths(target_cwds) if redact else target_cwds,
        "missing_saved_roots": redacted_paths(missing_saved_roots) if redact else missing_saved_roots,
        "missing_project_order": redacted_paths(missing_project_order) if redact else missing_project_order,
        "missing_config_projects": redacted_paths(missing_config_projects) if redact else missing_config_projects,
        "missing_workspace_labels": redacted_paths(missing_labels) if redact else missing_labels,
        "collapsed_visible_roots": redacted_paths(collapsed_visible_roots) if redact else collapsed_visible_roots,
        "missing_index_ids": [thread.id for thread in missing_index],
        "duplicate_visible_index_ids": duplicate_visible_ids,
        "missing_thread_workspace_root_hint_ids": [thread.id for thread in missing_hints],
        "stale_thread_workspace_root_hints": stale_hints,
        "missing_thread_project_assignment_ids": [thread.id for thread in missing_assignments],
        "stale_thread_project_assignments": stale_assignments,
        "projects": sorted(projects, key=lambda item: (item["status"], item["cwd"])),
    }


def format_inspection_markdown(inspection: dict[str, Any]) -> str:
    lines = [
        "# Codex Thread Rescue Doctor Report",
        "",
        f"Generated: `{inspection['generated_at']}`",
        f"Scope: `{inspection['scope']}`",
        f"DB integrity: `{inspection['db_integrity']}`",
        f"UI ready: `{inspection['ui_ready']}`",
        "",
        "## Totals",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
    ]
    for key, value in inspection["totals"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Critical Counts", "", "| Condition | Count |", "| --- | ---: |"])
    for key, value in inspection["critical_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(["", "## Projects", ""])
    lines.append("| Status | Visible | Helpers | Archived | Collapsed | Label | Project |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- | --- |")
    for project in inspection["projects"]:
        if project["status"] == "OK_VISIBLE":
            continue
        lines.append(
            "| `{status}` | {visible} | {helpers} | {archived} | {collapsed} | `{label}` | `{cwd}` |".format(
                status=project["status"],
                visible=project["visible_candidates"],
                helpers=project["system_helpers"],
                archived=project["archived"],
                collapsed="yes" if project["sidebar_collapsed"] else "no",
                label=project["workspace_label"],
                cwd=project["cwd"],
            )
        )
    if not any(project["status"] != "OK_VISIBLE" for project in inspection["projects"]):
        lines.append("| `OK_VISIBLE` | all | 0 | 0 | no | ok | all target projects |")
    return "\n".join(lines) + "\n"
