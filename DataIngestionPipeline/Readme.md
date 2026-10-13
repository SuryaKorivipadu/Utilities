# Dropbox file monitor: local setup and restart guide

This project monitors a Dropbox folder using:

1. A FastAPI webhook (`DropboxWebhook.py`) that receives Dropbox notifications.
2. An ngrok HTTPS tunnel that makes the local webhook reachable by Dropbox.
3. Airflow 2 running in Docker Compose. Its DAG (`dags/monitor_dropbox_folder.py`) reads the Dropbox folder cursor and reports file changes.

The Dropbox notification only says that the linked account changed. Airflow queries Dropbox to find the actual folder changes. Keep the FastAPI process, ngrok tunnel, and Airflow services running while testing. After a laptop restart, start them again using the steps below.

> **Airflow version:** `DropboxWebhook.py` calls Airflow's `/api/v1` REST endpoint. These instructions use Airflow 2. Do not use the Airflow 3 Compose file without updating the webhook's API URL and authentication.
>
> The official Airflow Docker Compose quick-start is for learning and local testing, not production. Do not expose its Airflow UI or API publicly.

## One-time setup

### 1. Requirements

- Windows x64 with Docker Desktop installed and running (WSL 2 backend).
- Python installed for running the FastAPI webhook.
- ngrok installed, with an ngrok account authtoken configured once.
- A Dropbox app configured for **Full Dropbox** access if the monitored folder is outside the app folder, with `files.metadata.read` enabled.
- A Dropbox refresh token authorized for that app and account.

### 2. Configure local environment values

Create or update `.env` in this directory. Do not commit it or share its contents. Keep the values already generated for your Dropbox app and token. Ensure it contains these names:

```dotenv
DROPBOX_APP_KEY=your_app_key
DROPBOX_APP_SECRET=your_app_secret
DROPBOX_REFRESH_TOKEN=your_refresh_token
DROPBOX_FOLDER_PATH=/Reports

# Used by DropboxWebhook.py running on Windows to reach Airflow.
AIRFLOW_API_URL=http://localhost:8080
AIRFLOW_API_USER=airflow
AIRFLOW_API_PASSWORD=airflow

# Needed by the official Airflow 2 Docker Compose quick-start on Windows.
AIRFLOW_UID=50000

# Installs these packages in the local Airflow containers for development.
_PIP_ADDITIONAL_REQUIREMENTS=dropbox python-dotenv
```

Replace placeholder values with your own. `DROPBOX_FOLDER_PATH` must be the Dropbox path of the folder to monitor. Change the Airflow API credentials if you configure different credentials in Compose.

The webhook loads `.env` from its current working directory. Run it from this directory as shown below. Docker Compose also reads `.env` for variable substitution, but it does **not** automatically pass every value into containers.

### 3. Get the Airflow 2 Docker Compose file

In PowerShell:

```powershell
Set-Location "C:\Sury(A)\Code\Utilities\DataIngestionPipeline"
Invoke-WebRequest `
  -Uri "https://airflow.apache.org/docs/apache-airflow/2.10.5/docker-compose.yaml" `
  -OutFile "docker-compose.yaml"
```

Open `docker-compose.yaml` and find the shared `x-airflow-common` section's `environment:` mapping. Add these entries inside that mapping so the scheduler and task worker receive the Dropbox settings:

```yaml
      DROPBOX_APP_KEY: ${DROPBOX_APP_KEY}
      DROPBOX_APP_SECRET: ${DROPBOX_APP_SECRET}
      DROPBOX_REFRESH_TOKEN: ${DROPBOX_REFRESH_TOKEN}
      DROPBOX_FOLDER_PATH: ${DROPBOX_FOLDER_PATH}
```

Preserve the indentation and existing entries. The quick-start Compose file installs packages named by `_PIP_ADDITIONAL_REQUIREMENTS` when the Airflow containers start. This is convenient for local testing; for a durable deployment, build a custom Airflow image with those packages installed.

Initialize and start Airflow:

```powershell
docker compose up airflow-init
docker compose up -d
docker compose ps
```

Wait until the services are healthy, then open [http://localhost:8080](http://localhost:8080) and sign in. The default quick-start credentials are `airflow` / `airflow`. In the DAG list, find `monitor_dropbox_folder` and trigger it once. The first run creates a baseline from existing Dropbox files; it does not report those existing files as new arrivals. Subsequent runs report new, changed, and deleted files in the task logs.

If the DAG is not listed, check that the Compose file mounts this project's `./dags` directory to `/opt/airflow/dags`, then inspect scheduler logs:

```powershell
docker compose logs airflow-scheduler
```

### 4. Install webhook packages in your Python environment

Activate the virtual environment you use for this project, then run:

```powershell
python -m pip install fastapi uvicorn httpx python-dotenv
```

Airflow's `dropbox` and `python-dotenv` packages are installed in its containers via `_PIP_ADDITIONAL_REQUIREMENTS`; installing them only in this Windows virtual environment is not enough for the DAG.

## Start everything after a laptop restart

Open Docker Desktop and wait until it is running. Then use three PowerShell windows.

### Window 1: start Airflow

```powershell
Set-Location "C:\Sury(A)\Code\Utilities\DataIngestionPipeline"
docker compose up -d
docker compose ps
```

Airflow UI: [http://localhost:8080](http://localhost:8080).

### Window 2: start the FastAPI webhook

```powershell
Set-Location "C:\Sury(A)\Code\Utilities\DataIngestionPipeline"
python -m uvicorn DropboxWebhook:app --host 0.0.0.0 --port 8000
```

Keep this window open. The app must be able to read `DROPBOX_APP_SECRET` and the Airflow API settings from `.env`.

### Window 3: start ngrok

```powershell
ngrok http 8000
```

Keep this window open too. Copy the HTTPS forwarding URL shown by ngrok and append `/dropbox/webhook`, for example:

```text
https://example.ngrok-free.dev/dropbox/webhook
```

If ngrok assigned a different URL after restart, update the webhook URL in the Dropbox App Console. Dropbox verifies it with a GET request containing a `challenge`; the FastAPI endpoint echoes that challenge. Keep the endpoint path `/dropbox/webhook`.

## Verify and use the monitor

1. Confirm `docker compose ps` shows Airflow services running.
2. Confirm the FastAPI/Uvicorn terminal has no startup error.
3. Confirm ngrok is forwarding to local port `8000`.
4. In the Airflow UI, manually trigger `monitor_dropbox_folder` once to create the baseline (first-time setup only).
5. Add or modify a file inside the monitored Dropbox folder.
6. Dropbox sends a notification to ngrok, which forwards it to FastAPI. FastAPI validates `X-Dropbox-Signature` and requests an Airflow DAG run.
7. Check the DAG run's `check_dropbox_folder` task logs in Airflow. New files print `NEW FILE ARRIVED` and the name/path.

The DAG has `schedule=None`, so it runs when manually triggered or when the webhook requests a DAG run. Dropbox notifications can be repeated; the DAG uses its saved cursor to reconcile the actual changes.

## Stop services

Stop ngrok and Uvicorn with `Ctrl+C` in their windows. Stop Airflow containers while preserving their data and cursor state with:

```powershell
Set-Location "C:\Sury(A)\Code\Utilities\DataIngestionPipeline"
docker compose down
```

Do not use `docker compose down --volumes` unless you intentionally want to delete Airflow's local database/state. The Airflow Variable `dropbox_reports_state` stores the Dropbox cursor and inventory needed to detect changes across runs.

## Troubleshooting

- **`ngrok` is not recognized:** close and reopen PowerShell after installation; try `Get-Command ngrok`. Confirm the ngrok authtoken was configured once with `ngrok config add-authtoken ...`.
- **DAG missing or import error:** inspect `docker compose logs airflow-scheduler`; verify `dags/monitor_dropbox_folder.py` is mounted and the Dropbox packages were installed in Airflow.
- **DAG fails due to missing Dropbox environment values:** confirm the four `DROPBOX_*` mappings were added to the shared Compose `environment:` section and the corresponding variables exist in `.env`; recreate containers with `docker compose up -d`.
- **Webhook cannot trigger Airflow:** when FastAPI runs on Windows and Airflow is published on port 8080, use `AIRFLOW_API_URL=http://localhost:8080`. Check the configured Airflow API credentials and that the DAG ID is exactly `monitor_dropbox_folder`.
- **No file appears in logs:** the webhook does not include file details; it only triggers the DAG. Check the Airflow task logs, verify the Dropbox folder path, and ensure the baseline run succeeded.
- **Secrets:** never paste Dropbox tokens, app secrets, or Airflow credentials into chat, commit them, or include them in logs.