# Resume Index: keep every thread reachable

When the Codex Desktop sidebar drops a project's threads, the threads are not lost — they are still in `state_5.sqlite` and reachable with `codex resume <thread_id>`. The weak point is *finding* the right id when the sidebar won't show it.

The fix for that is a plain-text index you maintain yourself: one `project-thread-index.md` per project, plus a master table. This is **organization, not repair**. It never edits Codex state and never tries to fix the sidebar. If the UI breaks, you open the index and resume from it.

This pairs with pinning: pin the index thread (or the project), keep the index file current, and you have a durable entry point into everything.

## Option A — the script (deterministic)

`codex_thread_index.py` reads the local state database read-only and writes the index files. It is dry-run by default.

```bash
# Preview what would be written (no files created)
python3 scripts/codex_thread_index.py --scope all

# Write the index into a central private directory (~/.codex-thread-rescue/index by default)
python3 scripts/codex_thread_index.py --scope all --apply

# Optionally ALSO drop a copy inside each project's own root
python3 scripts/codex_thread_index.py --scope all --apply --in-project-roots
```

What it does, and why it is safe:

- Opens the database **read-only** (`file:...?mode=ro`); never writes `state_5.sqlite`, `session_index.jsonl`, `.codex-global-state.json`, `config.toml`, or any rollout file.
- Reads the schema defensively: it introspects which columns exist and degrades gracefully, so a future Codex schema change does not crash it.
- Writes the index to a **central private directory by default** (`~/.codex-thread-rescue/index`), not into your project repositories — generated files contain real thread ids and paths. Use `--in-project-roots` to also place a copy in each project root, and `--out-dir` to change the central location.
- Enumerates projects from the **distinct `cwd` of the thread rows**, not from the saved-roots list. This matters: a project whose sidebar binding was lost may no longer be a saved root, but its threads still exist — enumerating by thread `cwd` is the only way to avoid missing exactly the broken projects.
- Excludes archived threads, system helpers (guardian / worker / explorer / auto-review / subagent / approval-review), and threads with no user event. Only normal user threads are indexed.
- Orders threads by `updated_at` descending, with the thread id as a stable tiebreak, and drops duplicate ids. The thread list is identical on every run (only the `最終更新` timestamp line changes).

Generated index files contain real thread ids and real paths, so keep them local. The repository `.gitignore` already ignores `project*thread*index*` and `thread-health/`.

## Option B — ask Codex (brushed-up prompt)

If you would rather have Codex assemble the index from inside the affected project, use the prompt below. It is written to be strictly read-only and to avoid every state surface that must not be touched.

```text
目的: 各プロジェクトに project-thread-index.md を整備し、Codex Desktop の
サイドバー表示不具合に備える。UI 復旧ではなく「resume 可能な索引の維持」が目的。
これは整理作業であり、スレッド復旧でも DB 修復でもない。

絶対禁止（読み取り専用を厳守）:
- ~/.codex/state_5.sqlite を書き換えない
- ~/.codex/session_index.jsonl を書き換えない
- ~/.codex/.codex-global-state.json を書き換えない
- ~/.codex/config.toml を書き換えない
- rollout JSONL を書き換えない
- task_complete 等を追記しない / source・thread_source を変更しない
- Codex の終了・再起動・force kill をしない
- safe_restore 系・サイドバー復旧系を実行しない

収集方針:
- state_5.sqlite を read-only で読む。
- 対象プロジェクトは「スレッド行の distinct cwd」を起点に列挙する
  （saved-roots ではない。保存対象から外れた壊れたプロジェクトを取りこぼさないため）。
- archived を除外。
- helper / guardian / approval-review / subagent 系を除外。
- has_user_event が無いスレッドを除外。通常ユーザースレッドのみ。

出力:
- 各プロジェクトルートに project-thread-index.md を作成または再生成する。
  プロジェクトのディレクトリが存在しない場合は、まとめ用ディレクトリに退避して書く（消さない）。
- 1 つのマスター索引を作成する。

各 project-thread-index.md のフォーマット:
  # Project Thread Index

  最終更新: YYYY-MM-DD HH:mm
  cwd: <cwd>
  スレッド数: <n>

  ## スレッド一覧

  ### <title>
  thread_id: <thread_id>
  resume: codex resume <thread_id>
  updated_at: <timestamp>
  cwd: <cwd>

  ---

出力ルール:
- title が無ければ "(untitled)"
- updated_at 降順、同値は thread_id 昇順で安定化
- thread_id 重複禁止
- 既存ファイルは安全に再生成
- 最終更新行を除き、何度実行しても同じ内容になること

マスター索引のフォーマット:
  # Codex Project Master Index

  | Project | Thread Count | Index Path |
  | --- | ---: | --- |
  （全プロジェクトを一覧化）

最後に次を表で報告して停止:
- 対象プロジェクト数 / 作成した index 数 / 総スレッド数
- archived 除外数 / helper 系除外数 / has_user_event 欠落除外数
- thread_id 重複数 / index 生成エラー数

勝ち条件:
Codex Desktop の UI が壊れても、project-thread-index.md を見れば
すべてのスレッドへ codex resume <thread_id> で到達できる状態にすること。
```

Either option produces the same outcome: a local, durable, resume-ready map of your threads that does not depend on the Desktop sidebar.
