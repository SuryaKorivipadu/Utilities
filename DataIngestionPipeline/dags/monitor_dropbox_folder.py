import json
import os
from datetime import datetime, timezone

import dropbox
from dotenv import load_dotenv
from dropbox.files import DeletedMetadata, FileMetadata

from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonOperator

load_dotenv()

STATE_KEY = "dropbox_reports_state"
FOLDER_PATH = os.environ["DROPBOX_FOLDER_PATH"]  # Example: /Reports


def monitor_folder():
    dbx = dropbox.Dropbox(
        oauth2_refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
        app_key=os.environ["DROPBOX_APP_KEY"],
        app_secret=os.environ["DROPBOX_APP_SECRET"],
    )

    state = Variable.get(STATE_KEY, default_var=None, deserialize_json=True)
    if state is None:
        state = {"cursor": None, "inventory": {}, "initialized": False}

    inventory = state["inventory"]
    cursor = state["cursor"]
    is_baseline = not state["initialized"]

    if cursor:
        page = dbx.files_list_folder_continue(cursor)
    else:
        page = dbx.files_list_folder(
            FOLDER_PATH,
            recursive=True,
            include_deleted=True,
        )

    while True:
        for entry in page.entries:
            path = getattr(entry, "path_lower", None)
            if not path:
                continue

            if isinstance(entry, DeletedMetadata):
                previous = inventory.pop(path, None)
                if previous is not None and not is_baseline:
                    print(f"DELETED {previous['path']}")
                continue

            if not isinstance(entry, FileMetadata):
                continue

            current = {
                "path": entry.path_display,
                "rev": entry.rev,
                "size": entry.size,
                "modified": entry.server_modified.isoformat(),
            }
            previous = inventory.get(path)

            if is_baseline:
                print(f"BASELINE {entry.path_display}")
            elif previous is None:
                print(
                    f"NEW FILE ARRIVED: {entry.name} (path: {entry.path_display})",
                    flush=True,
                )
            elif previous != current:
                print(f"CHANGED {entry.path_display}")

            inventory[path] = current

        cursor = page.cursor
        has_more = page.has_more

        # Save state after each page so a retry can continue from that cursor.
        Variable.set(
            STATE_KEY,
            json.dumps({
                "cursor": cursor,
                "inventory": inventory,
                "initialized": state["initialized"] or not has_more,
            }),
        )

        if not has_more:
            break

        page = dbx.files_list_folder_continue(cursor)


with DAG(
    dag_id="monitor_dropbox_folder",
    start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
    schedule=None,  # The webhook starts this DAG.
    catchup=False,
    max_active_runs=1,
) as dag:
    PythonOperator(
        task_id="check_dropbox_folder",
        python_callable=monitor_folder,
    )