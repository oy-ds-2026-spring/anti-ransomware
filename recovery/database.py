import sqlite3
import time
from typing import Optional, Dict, Any, List


class SnapshotDB:
    """
    Store distributed snapshot metadata:
      - command_id (one snapshot round)
      - client_id (finance1..4)
      - restic_snapshot_id (restic snapshot id returned by node)
      - status (DONE / FAILED)
    """

    def __init__(self, db_path: str = "snapshots.db"):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # WAL improves concurrent reads/writes; safe for single-process use.
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshot_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_id TEXT NOT NULL,
                    client_id TEXT NOT NULL,
                    restic_snapshot_id TEXT,
                    status TEXT NOT NULL,                 -- DONE / FAILED
                    error TEXT,
                    created_ts INTEGER NOT NULL,

                    UNIQUE(command_id, client_id)
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd ON snapshot_results(command_id);")

    def upsert_result(
        self,
        command_id: str,
        client_id: str,
        status: str,
        restic_snapshot_id: Optional[str] = None,
        error: Optional[str] = None,
        created_ts: Optional[int] = None,
    ) -> None:
        if created_ts is None:
            created_ts = int(time.time())

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO snapshot_results (command_id, client_id, restic_snapshot_id, status, error, created_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(command_id, client_id) DO UPDATE SET
                    restic_snapshot_id = excluded.restic_snapshot_id,
                    status = excluded.status,
                    error = excluded.error,
                    created_ts = excluded.created_ts;
                """,
                (command_id, client_id, restic_snapshot_id, status, error, created_ts),
            )

    def get_results_for_command(self, command_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Returns:
          {
            "finance1": {"status":"DONE","restic_snapshot_id":"...","error":None,"created_ts":...},
            ...
          }
        """
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT client_id, status, restic_snapshot_id, error, created_ts
                FROM snapshot_results
                WHERE command_id = ?
                """,
                (command_id,),
            )
            out: Dict[str, Dict[str, Any]] = {}
            for client_id, status, snap_id, err, ts in cur.fetchall():
                out[client_id] = {
                    "status": status,
                    "restic_snapshot_id": snap_id,
                    "error": err,
                    "created_ts": ts,
                }
            return out

    def count_done(self, command_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT COUNT(*)
                FROM snapshot_results
                WHERE command_id = ? AND status = 'DONE'
                """,
                (command_id,),
            )
            return int(cur.fetchone()[0])

    def all_done(self, command_id: str, required_clients: Optional[set] = None) -> bool:
        """
        If required_clients is provided, requires DONE for all those clients.
        Otherwise checks whether all rows for that command are DONE (not recommended if variable set).
        """
        results = self.get_results_for_command(command_id)
        if required_clients:
            return all(results.get(c, {}).get("status") == "DONE" for c in required_clients)
        return len(results) > 0 and all(v["status"] == "DONE" for v in results.values())

    def list_commands(self, limit: int = 50) -> List[str]:
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT DISTINCT command_id
                FROM snapshot_results
                ORDER BY MAX(created_ts) DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [row[0] for row in cur.fetchall()]

    def delete_command(self, command_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM snapshot_results WHERE command_id = ?", (command_id,))