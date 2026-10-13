import os
from contextlib import closing
from typing import Any

import psycopg2


CURSOR_KEY = "dropbox_folder_cursor"


def connect():
    return psycopg2.connect(os.environ["INGESTION_DATABASE_URL"])


def ensure_tables(connection: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_work (
                event_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                revision TEXT,
                action TEXT NOT NULL CHECK (action IN ('upsert', 'delete')),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending',
                        'awaiting_implementation',
                        'completed'
                    )),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS ingestion_work_pending_idx
            ON ingestion_work (created_at)
            WHERE status = 'pending'
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def get_cursor(connection: Any) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT state_value FROM ingestion_state WHERE state_key = %s",
            (CURSOR_KEY,),
        )
        row = cursor.fetchone()
    return row[0] if row else None


def save_cursor(connection: Any, value: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_state (state_key, state_value)
            VALUES (%s, %s)
            ON CONFLICT (state_key)
            DO UPDATE SET
                state_value = EXCLUDED.state_value,
                updated_at = NOW()
            """,
            (CURSOR_KEY, value),
        )


def enqueue_change(connection: Any, event: dict[str, Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_work (
                event_id, document_id, file_path, revision, action
            )
            VALUES (%(event_id)s, %(document_id)s, %(file_path)s,
                    %(revision)s, %(action)s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            event,
        )


def get_pending_work(limit: int) -> list[dict[str, Any]]:
    with closing(connect()) as connection:
        with connection:
            ensure_tables(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_id, document_id, file_path, revision, action
                    FROM ingestion_work
                    WHERE status = 'pending'
                    ORDER BY created_at, event_id
                    LIMIT %s
                    """,
                    (limit,),
                )
                columns = [description[0] for description in cursor.description]
                return [
                    dict(zip(columns, row))
                    for row in cursor.fetchall()
                ]


def set_work_status(event_id: str, status: str) -> None:
    with closing(connect()) as connection:
        with connection:
            ensure_tables(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ingestion_work
                    SET status = %s, updated_at = NOW()
                    WHERE event_id = %s
                    """,
                    (status, event_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"Ingestion work item was not found: {event_id}"
                    )
