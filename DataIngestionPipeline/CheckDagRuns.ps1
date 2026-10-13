$pair = "airflow:airflow"
$encoded = [Convert]::ToBase64String(
    [Text.Encoding]::ASCII.GetBytes($pair)
)
$headers = @{ Authorization = "Basic $encoded" }

$result = Invoke-RestMethod `
    -Uri "http://localhost:8080/api/v1/dags/monitor_dropbox_folder/dagRuns?limit=10&order_by=-execution_date" `
    -Headers $headers

foreach ($run in $result.dag_runs) {
    Write-Host "`nDAG run: $($run.dag_run_id) | State: $($run.state) | Started: $($run.start_date)"

    $encodedRunId = [uri]::EscapeDataString($run.dag_run_id)
    $tasks = Invoke-RestMethod `
        -Uri "http://localhost:8080/api/v1/dags/monitor_dropbox_folder/dagRuns/$encodedRunId/taskInstances?limit=100" `
        -Headers $headers

    if ($tasks.task_instances.Count -eq 0) {
        Write-Host "  No task instances have been created for this run yet."
        continue
    }

    $tasks.task_instances |
        Select-Object task_id, state, start_date, end_date |
        Format-Table -AutoSize
}