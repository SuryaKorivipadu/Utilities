# webhook.py
import hashlib
import hmac
import os
import uuid

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

load_dotenv()
app = FastAPI()

DROPBOX_APP_SECRET = os.environ["DROPBOX_APP_SECRET"]
AIRFLOW_API_URL = os.environ["AIRFLOW_API_URL"].rstrip("/")
AIRFLOW_API_USER = os.environ["AIRFLOW_API_USER"]
AIRFLOW_API_PASSWORD = os.environ["AIRFLOW_API_PASSWORD"]
DAG_ID = "monitor_dropbox_folder"


@app.get("/dropbox/webhook")
async def verify_webhook(request: Request):
    # Dropbox's initial URL-verification request.
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

    # A notification means the account changed; the DAG checks the folder cursor.
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            result = await client.post(
                f"{AIRFLOW_API_URL}/api/v1/dags/{DAG_ID}/dagRuns",
                auth=(AIRFLOW_API_USER, AIRFLOW_API_PASSWORD),
                json={
                    "dag_run_id": f"dropbox-{uuid.uuid4().hex}",
                    "conf": {},
                },
            )
            result.raise_for_status()
    except httpx.HTTPError as exc:
        # A failure response allows Dropbox to retry the notification.
        raise HTTPException(
            status_code=503,
            detail="Could not trigger Airflow",
        ) from exc

    return Response(status_code=200)