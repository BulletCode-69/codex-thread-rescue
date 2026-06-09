from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from codex_thread_rescue_common import (
    CodexPaths,
    build_inspection,
    canonical_index_lines,
    fetch_threads,
)


SCHEMA = """
create table threads (
    id text primary key,
    rollout_path text not null,
    created_at integer not null,
    updated_at integer not null,
    source text not null,
    model_provider text not null,
    cwd text not null,
    title text not null,
    sandbox_policy text not null,
    approval_mode text not null,
    has_user_event integer not null default 0,
    archived integer not null default 0,
    archived_at integer,
    first_user_message text not null default '',
    agent_nickname text,
    agent_role text,
    agent_path text,
    created_at_ms integer,
    updated_at_ms integer,
    thread_source text,
    preview text not null default ''
)
"""


def insert_thread(
    conn: sqlite3.Connection,
    thread_id: str,
    cwd: str,
    *,
    archived: int = 0,
    has_user_event: int = 1,
    source: str = "vscode",
    thread_source: str = "user",
    updated_at_ms: int = 1000,
) -> None:
    conn.execute(
        """
        insert into threads (
            id, rollout_path, created_at, updated_at, source, model_provider, cwd,
            title, sandbox_policy, approval_mode, has_user_event, archived,
            first_user_message, created_at_ms, updated_at_ms, thread_source, preview
        )
        values (?, '', 1, 1, ?, 'openai', ?, ?, 'workspace-write', 'on-request', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            thread_id,
            source,
            cwd,
            f"title {thread_id}",
            has_user_event,
            archived,
            f"first {thread_id}",
            updated_at_ms,
            updated_at_ms,
            thread_source,
            f"preview {thread_id}",
        ),
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        codex_home = root / "codex-home"
        codex_home.mkdir()
        paths = CodexPaths(
            codex_home=codex_home,
            state_db=codex_home / "state_5.sqlite",
            session_index=codex_home / "session_index.jsonl",
            global_state=codex_home / ".codex-global-state.json",
            config_toml=codex_home / "config.toml",
            safety_dir=codex_home / "thread-rescue-safety",
        )

        conn = sqlite3.connect(paths.state_db)
        conn.execute(SCHEMA)
        insert_thread(conn, "demo-alpha", "~/projects/demo-alpha", updated_at_ms=1000)
        insert_thread(
            conn,
            "demo-helper",
            "~/projects/demo-alpha",
            source='{"subagent": "worker"}',
            thread_source="subagent",
            updated_at_ms=2000,
        )
        insert_thread(conn, "demo-beta", "~/projects/demo-beta", has_user_event=0, updated_at_ms=3000)
        insert_thread(conn, "demo-old", "~/projects/demo-old", archived=1, updated_at_ms=4000)
        conn.commit()
        conn.close()

        paths.session_index.write_text(
            "\n".join(
                [
                    json.dumps({"id": "demo-alpha", "thread_name": "alpha", "updated_at": "x"}),
                    json.dumps({"id": "demo-alpha", "thread_name": "alpha duplicate", "updated_at": "x"}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        paths.global_state.write_text(
            json.dumps(
                {
                    "electron-saved-workspace-roots": ["~/projects/demo-alpha"],
                    "project-order": ["~/projects/demo-alpha"],
                    "electron-workspace-root-labels": {"~/projects/demo-alpha": "Demo Alpha"},
                    "electron-persisted-atom-state": {
                        "sidebar-collapsed-groups": {"~/projects/demo-alpha": True}
                    },
                    "thread-workspace-root-hints": {},
                    "thread-project-assignments": {},
                }
            ),
            encoding="utf-8",
        )
        paths.config_toml.write_text(
            '[projects."~/projects/demo-alpha"]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )

        inspection = build_inspection(paths, scope="all", prefix=None, cwd=None, redact=True)
        assert inspection["db_integrity"] == "ok"
        assert inspection["totals"]["threads"] == 4
        assert inspection["totals"]["system_helpers"] == 1
        assert inspection["critical_counts"]["missing_user_event"] == 1
        assert inspection["critical_counts"]["duplicate_visible_index_ids"] == 1
        assert inspection["critical_counts"]["collapsed_visible_roots"] == 1
        assert inspection["critical_counts"]["missing_thread_workspace_root_hints"] == 1
        assert inspection["critical_counts"]["missing_thread_project_assignments"] == 1
        assert inspection["ui_ready"] is False

        threads = fetch_threads(paths, scope="all", prefix=None, cwd=None)
        visible = [thread for thread in threads if thread.is_visible_candidate]
        assert len(canonical_index_lines(visible)) == 1

    print("codex_thread_visibility_selftest: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
