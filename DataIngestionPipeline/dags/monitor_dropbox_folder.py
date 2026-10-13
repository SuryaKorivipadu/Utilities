import hashlib
import logging
import os
from contextlib import closing
from typing import Any

import dropbox
from airflow import DAG
from airflow.operators.python import PythonOperator
from pendulum import datetime

from ingestion_queue import (
    connect,
    enqueue_change,
    ensure_tables,
    get_cursor,
    save_cursor,
)

LOGGER = logging.getLogger(__name__)
DAG_ID = "monitor_dropbox_folder"


def _change_event(entry: Any) -> dict[str, Any] | None:
    path = getattr(entry, "path_display", None) or getattr(
        entry, "path_lower", None
    )
    if not path or not path.lower().endswith(".pdf"):
        return None

    document_id = getattr(entry, "id", None) or path.lower()
    revision = getattr(entry, "rev", None)
    action = (
        "delete"
        if isinstance(entry, dropbox.files.DeletedMetadata)
        else "upsert"
    )
    identity = f"{document_id}:{revision or ''}:{action}"
    event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    return {
        "event_id": event_id,
        "document_id": document_id,
        "file_path": path,
        "revision": revision,
        "action": action,
    }


def discover_dropbox_changes() -> None:
    app_key = os.environ.get("DROPBOX_APP_KEY")
    app_secret = os.environ.get("DROPBOX_APP_SECRET")
    refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")
    folder_path = os.environ.get("DROPBOX_FOLDER_PATH", "")
    if not all((app_key, app_secret, refresh_token)):
        raise RuntimeError(
            "DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and "
            "DROPBOX_REFRESH_TOKEN must be configured"
        )

    client = dropbox.Dropbox(
        oauth2_refresh_token=refresh_token,
        app_key=app_key,
        app_secret=app_secret,
    )
    with closing(connect()) as connection:
        with connection:
            ensure_tables(connection)
            cursor = get_cursor(connection)

    page = (
        client.files_list_folder_continue(cursor)
        if cursor
        else client.files_list_folder(folder_path, recursive=True)
    )

    while True:
        with closing(connect()) as connection:
            with connection:
                ensure_tables(connection)
                for entry in page.entries:
                    event = _change_event(entry)
                    if event:
                        enqueue_change(connection, event)
                        LOGGER.info(
                            "Queued Dropbox %s event for %s",
                            event["action"],
                            event["file_path"],
                        )
                # Checkpoint only after all changes on this page are durable.
                save_cursor(connection, page.cursor)

        if not page.has_more:
            break
        page = client.files_list_folder_continue(page.cursor)


with DAG(
    dag_id=DAG_ID,
    description="Discover Dropbox PDF changes and enqueue them for processing",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["dropbox", "ingestion"],
) as dag:
    discover_changes = PythonOperator(
        task_id="discover_dropbox_changes",
        python_callable=discover_dropbox_changes,
    )
