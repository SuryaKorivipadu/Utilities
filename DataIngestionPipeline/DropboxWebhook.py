import asyncio
import hashlib
import hmac
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import dropbox
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from ingestion_logging import get_logger

load_dotenv()
app = FastAPI()

DROPBOX_APP_KEY = os.environ["DROPBOX_APP_KEY"]
DROPBOX_APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
DROPBOX_REFRESH_TOKEN = os.environ["DROPBOX_REFRESH_TOKEN"]
DROPBOX_FOLDER_PATH = os.environ.get("DROPBOX_FOLDER_PATH", "")
AIRFLOW_API_URL = os.environ["AIRFLOW_API_URL"].rstrip("/")
AIRFLOW_API_USER = os.environ["AIRFLOW_API_USER"]
AIRFLOW_API_PASSWORD = os.environ["AIRFLOW_API_PASSWORD"]
DAG_ID = "monitor_dropbox_folder"
STATE_DB = Path(__file__).with_name("dropbox_webhook_state.sqlite3")
LOGGER = get_logger("dropbox_webhook")
WEBHOOK_LOCK = asyncio.Lock()


def _dropbox_client() -> dropbox.Dropbox:
    return dropbox.Dropbox(
        oauth2_refresh_token=DROPBOX_REFRESH_TOKEN,
        app_key=DROPBOX_APP_KEY,
        app_secret=DROPBOX_APP_SECRET,
    )


def _connect_state() -> sqlite3.Connection:
    connection = sqlite3.connect(STATE_DB)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS webhook_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            folder_path TEXT NOT NULL,
            cursor TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS known_folders (
            path_lower TEXT PRIMARY KEY
        );
    """)
    return connection


def _save_state(cursor: str, folder_path: str, folders: set[str]) -> None:
    with closing(_connect_state()) as connection, connection:
        connection.execute(
            "INSERT INTO webhook_state VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "folder_path = excluded.folder_path, cursor = excluded.cursor",
            (folder_path, cursor),
        )
        connection.execute("DELETE FROM known_folders")
        connection.executemany(
            "INSERT INTO known_folders (path_lower) VALUES (?)",
            ((path,) for path in folders),
        )


def _load_state() -> tuple[str | None, set[str]]:
    with closing(_connect_state()) as connection, connection:
        state = connection.execute(
            "SELECT folder_path, cursor FROM webhook_state WHERE id = 1"
        ).fetchone()
        if state is None or state[0] != DROPBOX_FOLDER_PATH:
            return None, set()
        folders = {
            row[0]
            for row in connection.execute("SELECT path_lower FROM known_folders")
        }
        return state[1], folders


def _pages(client: dropbox.Dropbox, first_page):
    page = first_page
    while True:
        yield page
        if not page.has_more:
            break
        page = client.files_list_folder_continue(page.cursor)


def _bootstrap_cursor() -> None:
    cursor, _ = _load_state()
    if cursor:
        LOGGER.info("Loaded saved Dropbox webhook cursor")
        return

    client = _dropbox_client()
    page = client.files_list_folder(
        DROPBOX_FOLDER_PATH,
        recursive=True,
    )
    folders: set[str] = set()
    for page in _pages(client, page):
        folders.update(
            entry.path_lower
            for entry in page.entries
            if isinstance(entry, dropbox.files.FolderMetadata)
        )
    cursor = page.cursor

    _save_state(cursor, DROPBOX_FOLDER_PATH, folders)
    LOGGER.info(
        "Initialized Dropbox webhook cursor for folder %s",
        DROPBOX_FOLDER_PATH or "/",
    )


def _scan_changes() -> tuple[str, set[str], list[tuple[str, str]]]:
    cursor, folders = _load_state()
    if cursor is None:
        raise RuntimeError("Dropbox webhook cursor has not been initialized")

    client = _dropbox_client()
    page = client.files_list_folder_continue(cursor)
    changes: list[tuple[str, str]] = []
    deleted_paths: list[str] = []

    for page in _pages(client, page):
        for entry in page.entries:
            path = getattr(entry, "path_lower", None)
            if not path:
                continue
            if isinstance(entry, dropbox.files.FolderMetadata):
                folders.add(path)
            elif isinstance(entry, dropbox.files.DeletedMetadata):
                deleted_paths.append(path)
            elif isinstance(entry, dropbox.files.FileMetadata):
                changes.append(("upsert", path))

    cursor = page.cursor

    deleted_folders = set(deleted_paths).intersection(folders)
    for path in deleted_paths:
        if any(
            path == folder or path.startswith(f"{folder}/")
            for folder in deleted_folders
        ):
            continue
        changes.append(("delete", path))

    folders = _remove_deleted_folders(folders, deleted_folders)
    return cursor, folders, changes


def _remove_deleted_folders(
    folders: set[str],
    deleted_folders: set[str],
) -> set[str]:
    return {
        path
        for path in folders
        if not any(
            path == deleted or path.startswith(f"{deleted}/")
            for deleted in deleted_folders
        )
    }


@app.on_event("startup")
async def initialize_webhook_cursor() -> None:
    try:
        await asyncio.to_thread(_bootstrap_cursor)
    except (dropbox.exceptions.DropboxException, sqlite3.Error, OSError):
        LOGGER.exception("Could not initialize the Dropbox webhook cursor")
        raise


@app.get("/dropbox/webhook")
async def verify_webhook(request: Request):
    challenge = request.query_params.get("challenge")
    if challenge is None:
        raise HTTPException(status_code=400, detail="Missing challenge")

    response = PlainTextResponse(challenge)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.post("/dropbox/webhook")
async def receive_notification(request: Request):
    raw_body = await request.body()
    supplied_signature = request.headers.get("X-Dropbox-Signature", "")
    expected_signature = hmac.new(
        DROPBOX_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise HTTPException(status_code=403, detail="Invalid Dropbox signature")

    async with WEBHOOK_LOCK:
        try:
            cursor, folders, changes = await asyncio.to_thread(_scan_changes)
        except (
            dropbox.exceptions.DropboxException,
            sqlite3.Error,
            OSError,
            RuntimeError,
        ) as exc:
            LOGGER.exception("Could not check Dropbox changes")
            raise HTTPException(
                status_code=503,
                detail="Could not check Dropbox changes",
            ) from exc

        if not changes:
            await asyncio.to_thread(
                _save_state,
                cursor,
                DROPBOX_FOLDER_PATH,
                folders,
            )
            LOGGER.info("Dropbox notification contained no file changes")
            return Response(status_code=200)

        run_id = f"dropbox-{hashlib.sha256(cursor.encode()).hexdigest()[:32]}"
        try:
            async with httpx.AsyncClient(timeout=4) as client:
                result = await client.post(
                    f"{AIRFLOW_API_URL}/api/v1/dags/{DAG_ID}/dagRuns",
                    auth=(AIRFLOW_API_USER, AIRFLOW_API_PASSWORD),
                    json={"dag_run_id": run_id, "conf": {}},
                )
                if result.status_code != 409:
                    result.raise_for_status()
        except httpx.HTTPError as exc:
            LOGGER.exception("Could not trigger the Airflow monitor DAG")
            raise HTTPException(
                status_code=503,
                detail="Could not trigger Airflow",
            ) from exc

        await asyncio.to_thread(
            _save_state,
            cursor,
            DROPBOX_FOLDER_PATH,
            folders,
        )
        LOGGER.info(
            "Triggered %s for %d file change(s): %s",
            DAG_ID,
            len(changes),
            ", ".join(f"{action} {path}" for action, path in changes),
        )

    return Response(status_code=200)
