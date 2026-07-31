"""SQLite persistence for runs, approvals, and the audit event stream."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    idempotency_key: str
    source: str
    business_path: str
    task_path: str
    status: str
    created_at: str
    updated_at: str
    client_id: str | None = None
    workspace_path: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunNotFoundError(KeyError):
    """Raised when a requested service run does not exist."""


class RunStateError(ValueError):
    """Raised when a requested state transition is invalid."""


class RunStore:
    """Small, durable queue suitable for a single Hostinger VPS pilot."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    business_path TEXT NOT NULL,
                    task_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    client_id TEXT,
                    workspace_path TEXT,
                    result_json TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    approval_kind TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, approval_kind),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS runs_status_created_idx
                    ON runs(status, created_at);
                CREATE INDEX IF NOT EXISTS events_run_idx
                    ON events(run_id, event_id);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "client_id" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN client_id TEXT")
            if "workspace_path" not in columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN workspace_path TEXT"
                )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS runs_client_created_idx
                    ON runs(client_id, created_at)
                """
            )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        result_json = row["result_json"]
        return RunRecord(
            run_id=row["run_id"],
            idempotency_key=row["idempotency_key"],
            source=row["source"],
            business_path=row["business_path"],
            task_path=row["task_path"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            client_id=row["client_id"],
            workspace_path=row["workspace_path"],
            result=json.loads(result_json) if result_json else None,
            error=row["error"],
        )

    def create_run(
        self,
        *,
        idempotency_key: str,
        source: str,
        business_path: str,
        task_path: str,
        client_id: str | None = None,
        workspace_path: str | None = None,
    ) -> tuple[RunRecord, bool]:
        now = utc_now()
        run_id = f"run_{uuid4().hex}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                expected = (
                    source,
                    business_path,
                    task_path,
                    client_id,
                    workspace_path,
                )
                actual = (
                    existing["source"],
                    existing["business_path"],
                    existing["task_path"],
                    existing["client_id"],
                    existing["workspace_path"],
                )
                if actual != expected:
                    connection.rollback()
                    raise RunStateError(
                        "Idempotency-Key is already bound to a different request"
                    )
                connection.commit()
                return self._row_to_run(existing), False
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, idempotency_key, source, business_path, task_path,
                    status, created_at, updated_at, client_id, workspace_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    idempotency_key,
                    source,
                    business_path,
                    task_path,
                    "awaiting-blueprint-approval",
                    now,
                    now,
                    client_id,
                    workspace_path,
                ),
            )
            self._append_event(
                connection,
                run_id,
                "run.created",
                {"source": source, "client_id": client_id},
                now,
            )
            connection.commit()
        return self.get_run(run_id), True

    def list_runs(
        self,
        *,
        client_id: str | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        query = "SELECT * FROM runs"
        parameters: tuple[Any, ...] = ()
        if client_id is not None:
            query += " WHERE client_id = ?"
            parameters = (client_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters += (limit,)
        with self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_run(row) for row in rows]

    def get_run(self, run_id: str) -> RunRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise RunNotFoundError(run_id)
        return self._row_to_run(row)

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, payload_json, created_at
                FROM events WHERE run_id = ? ORDER BY event_id
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_approval(
        self,
        *,
        run_id: str,
        approval_kind: str,
        decision: str,
        actor: str,
        details: dict[str, Any],
    ) -> RunRecord:
        if approval_kind not in {"blueprint", "test", "action"}:
            raise RunStateError("Unsupported approval kind")
        if decision not in {"approved", "rejected"}:
            raise RunStateError("Decision must be approved or rejected")
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RunNotFoundError(run_id)

            existing = connection.execute(
                """
                SELECT decision, actor, details_json
                FROM approvals
                WHERE run_id = ? AND approval_kind = ?
                """,
                (run_id, approval_kind),
            ).fetchone()
            canonical_details = json.dumps(
                details,
                sort_keys=True,
                separators=(",", ":"),
            )
            if existing is not None:
                if (
                    existing["decision"] != decision
                    or existing["actor"] != actor
                    or existing["details_json"] != canonical_details
                ):
                    connection.rollback()
                    raise RunStateError(
                        "Approval already exists with different data"
                    )
                connection.commit()
                return self._row_to_run(row)

            status = row["status"]
            next_status = status
            if approval_kind == "blueprint":
                if status != "awaiting-blueprint-approval":
                    connection.rollback()
                    raise RunStateError(
                        "Blueprint approval is not valid in the current state"
                    )
                next_status = "queued" if decision == "approved" else "rejected"
            elif approval_kind == "action":
                connection.rollback()
                raise RunStateError(
                    "Action approvals are recorded only after a future "
                    "state-changing adapter shows the exact target and effect"
                )

            connection.execute(
                """
                INSERT INTO approvals (
                    approval_id, run_id, approval_kind, decision, actor,
                    details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"approval_{uuid4().hex}",
                    run_id,
                    approval_kind,
                    decision,
                    actor,
                    canonical_details,
                    now,
                ),
            )
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
                (next_status, now, run_id),
            )
            self._append_event(
                connection,
                run_id,
                f"approval.{decision}",
                {"kind": approval_kind, "actor": actor, "details": details},
                now,
            )
            connection.commit()
        return self.get_run(run_id)

    def claim_next_run(self) -> RunRecord | None:
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM runs
                WHERE status = 'queued'
                ORDER BY created_at
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE runs
                SET status = 'running', updated_at = ?
                WHERE run_id = ? AND status = 'queued'
                """,
                (now, row["run_id"]),
            )
            self._append_event(
                connection,
                row["run_id"],
                "run.started",
                {},
                now,
            )
            connection.commit()
        return self.get_run(row["run_id"])

    def requeue_stale_runs(self, *, older_than_minutes: int) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        ).isoformat()
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT run_id FROM runs
                WHERE status = 'running' AND updated_at < ?
                ORDER BY updated_at
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE runs
                    SET status = 'queued', updated_at = ?
                    WHERE run_id = ? AND status = 'running'
                    """,
                    (now, row["run_id"]),
                )
                self._append_event(
                    connection,
                    row["run_id"],
                    "run.requeued-after-stale-lease",
                    {"older_than_minutes": older_than_minutes},
                    now,
                )
            connection.commit()
        return len(rows)

    def complete_run(
        self,
        run_id: str,
        *,
        result: dict[str, Any],
        succeeded: bool,
    ) -> RunRecord:
        now = utc_now()
        status = "completed" if succeeded else "failed"
        error = None if succeeded else result.get("error", "Browser run failed")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RunNotFoundError(run_id)
            if row["status"] != "running":
                connection.rollback()
                raise RunStateError("Only a running job may be completed")
            connection.execute(
                """
                UPDATE runs
                SET status = ?, updated_at = ?, result_json = ?, error = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    now,
                    json.dumps(result, ensure_ascii=False),
                    error,
                    run_id,
                ),
            )
            self._append_event(
                connection,
                run_id,
                f"run.{status}",
                {"runtime_status": result.get("status")},
                now,
            )
            connection.commit()
        return self.get_run(run_id)

    def fail_run(self, run_id: str, error: str) -> RunRecord:
        return self.complete_run(
            run_id,
            result={"status": "failed", "error": error},
            succeeded=False,
        )

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        now = utc_now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if exists is None:
                connection.rollback()
                raise RunNotFoundError(run_id)
            self._append_event(
                connection,
                run_id,
                event_type,
                payload,
                now,
            )
            connection.commit()

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO events (run_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                event_type,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )
