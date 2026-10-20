# Dropbox ingestion pipeline

This local setup uses:

- **FastAPI + ngrok** to receive Dropbox webhook notifications.
- **Airflow 2 in Docker Compose** to detect Dropbox changes and process queued PDFs.
- **PostgreSQL** for the ingestion queue and Dropbox cursor.

The monitor queues PDF changes. Processing currently extracts Markdown and images; chunking, embeddings, vector storage, and deletion cleanup are not implemented yet.

## One-time setup

1. Install Docker Desktop, Python, and ngrok. Configure your ngrok authtoken.
2. Create `.env` in this folder with your Dropbox app credentials:
`DROPBOX_FOLDER_PATH` is the folder to monitor.
3. Start Airflow and create the ingestion database:
   ```powershell
   docker compose up airflow-init
   docker compose exec postgres psql -U airflow -d postgres -c "CREATE DATABASE ingestion;"
   docker compose up -d
   ```
   Create the database only once. Open [http://localhost:8080](http://localhost:8080) and sign in with the configured Airflow credentials (the quick-start defaults are `airflow` / `airflow`).
4. In your project Python environment, install webhook dependencies:

   ```powershell
   python -m pip install fastapi uvicorn httpx python-dotenv dropbox
   ```

## Start after a restart
Run these in separate PowerShell windows from this project folder.

**Airflow**

```powershell
docker compose up -d
docker compose ps
```

**Webhook**

```powershell
python -m uvicorn DropboxWebhook:app --host 0.0.0.0 --port 8000
```

**ngrok**

```powershell
ngrok http 8000
```

Set the Dropbox app webhook URL to the ngrok HTTPS address with `/dropbox/webhook` appended. Update it whenever ngrok gives you a new address.

## Verify

1. In Airflow at [http://localhost:8080](http://localhost:8080), trigger `monitor_dropbox_folder` once. The first run queues existing PDFs and saves the Dropbox cursor.
2. Add, edit, or delete a file in the monitored Dropbox folder. The webhook checks Dropbox's cursor and triggers the monitor DAG only when it finds file changes. Duplicate notifications with no new changes do not create extra runs.
3. Check the DAG task logs in Airflow. `process_dropbox_queue` checks for work every minute and handles up to 10 changes per run.
4. Extracted Markdown and images are written to `data/`. The custom logger writes to `logs/ingestion_logs.log`.

The webhook keeps its own cursor in the ignored `dropbox_webhook_state.sqlite3` file. On its first startup, it saves a baseline and does not trigger a run for files already present. The monitor DAG has a separate cursor. The monitor currently queues PDF changes; other file types can trigger the DAG but are not processed by the PDF pipeline. Until the remaining processing stages are implemented, processed records are left as `awaiting_implementation`.

## Stop
Stop ngrok and Uvicorn with `Ctrl+C`, then stop Airflow:

```powershell
docker compose down
```

Do not add `--volumes` unless you intend to delete Airflow state, including the queue and cursor.

## Troubleshooting
- **DAG missing or import error:** run `docker compose logs airflow-scheduler`; check the `dags/` mount and Airflow dependencies.
- **Dropbox credentials missing:** check the Dropbox values in `.env` and the Compose environment mappings, then run `docker compose up -d`.
- **Webhook cannot trigger Airflow:** verify `AIRFLOW_API_URL`, credentials, and the DAG ID `monitor_dropbox_folder`.
- **Database connection error:** from this project folder, check whether the `ingestion` database exists:

  ```powershell
  docker compose exec postgres psql -U airflow -d postgres -c "SELECT datname FROM pg_database WHERE datname = 'ingestion'"
  ```

  If it does not exist, create it:

  ```powershell
  docker compose exec postgres psql -U airflow -d postgres -c "CREATE DATABASE ingestion"
  ```

  Also verify `INGESTION_DATABASE_URL` uses the Compose hostname `postgres`.
- **No queued files:** check the monitor task logs, `DROPBOX_FOLDER_PATH`, and whether the initial monitor run succeeded.
