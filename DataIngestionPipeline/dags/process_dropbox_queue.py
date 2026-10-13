import logging
import os
from pathlib import Path
from typing import Any

import dropbox
import pymupdf4llm
from airflow.decorators import dag, task
from pendulum import datetime

from ingestion_queue import get_pending_work, set_work_status

LOGGER = logging.getLogger(__name__)
BATCH_SIZE = 10


def get_text(file_path: str, image_output_dir: str) -> str:
    """Extract PDF text as Markdown using the project's existing approach."""
    LOGGER.debug("Getting text from file: %s", file_path)
    file_type = file_path.split(".")[-1].lower()
    if file_type == "pdf":
        LOGGER.debug("Processing PDF file: %s", file_path)
        return pymupdf4llm.to_markdown(
            file_path,
            write_images=True,
            image_path=image_output_dir,
        )
    LOGGER.warning("Unsupported file type: %s", file_type)
    return ""


@dag(
    dag_id="process_dropbox_queue",
    description="Process queued Dropbox PDF changes through the RAG stages",
    start_date=datetime(2024, 1, 1),
    schedule="*/1 * * * *",
    catchup=False,
    max_active_runs=1,
    tags=["dropbox", "ingestion", "rag"],
)
def process_dropbox_queue():
    @task
    def load_pending_batch() -> list[dict[str, Any]]:
        return get_pending_work(BATCH_SIZE)

    @task
    def read_pdf(event: dict[str, Any]) -> dict[str, Any]:
        if event["action"] == "delete":
            return {**event, "markdown_path": None}

        app_key = os.environ.get("DROPBOX_APP_KEY")
        app_secret = os.environ.get("DROPBOX_APP_SECRET")
        refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")
        if not all((app_key, app_secret, refresh_token)):
            raise RuntimeError(
                "DROPBOX_APP_KEY, DROPBOX_APP_SECRET, and "
                "DROPBOX_REFRESH_TOKEN must be configured"
            )

        artifact_root = Path(
            os.environ.get("INGESTION_ARTIFACT_DIR", "/opt/airflow/data")
        )
        event_dir = artifact_root / event["event_id"]
        image_dir = event_dir / "images"
        event_dir.mkdir(parents=True, exist_ok=True)
        image_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = event_dir / "source.pdf"
        client = dropbox.Dropbox(
            oauth2_refresh_token=refresh_token,
            app_key=app_key,
            app_secret=app_secret,
        )
        client.files_download_to_file(
            str(pdf_path),
            event["file_path"],
            rev=event.get("revision") or None,
        )
        markdown = get_text(str(pdf_path), str(image_dir))
        markdown_path = event_dir / "document.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        return {**event, "markdown_path": str(markdown_path)}

    @task
    def chunk_text(document: dict[str, Any]) -> dict[str, Any]:
        if document["action"] == "delete":
            return document
        LOGGER.warning(
            "Chunking is not implemented; event %s is not ready for indexing",
            document["event_id"],
        )
        return document

    @task
    def embed_chunks(document: dict[str, Any]) -> dict[str, Any]:
        if document["action"] == "delete":
            return document
        LOGGER.warning(
            "Embedding is not implemented; event %s is not ready for indexing",
            document["event_id"],
        )
        return document

    @task
    def store_vectors(document: dict[str, Any]) -> None:
        if document["action"] == "delete":
            LOGGER.warning(
                "Vector deletion is not implemented for event %s",
                document["event_id"],
            )
        else:
            LOGGER.warning(
                "Vector storage is not implemented for event %s",
                document["event_id"],
            )
        set_work_status(
            document["event_id"],
            "awaiting_implementation",
        )

    pending = load_pending_batch()
    pdfs = read_pdf.expand(event=pending)
    chunks = chunk_text.expand(document=pdfs)
    embeddings = embed_chunks.expand(document=chunks)
    store_vectors.expand(document=embeddings)


process_dropbox_queue()
