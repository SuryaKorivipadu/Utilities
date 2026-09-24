[CmdletBinding()]
param(
    [string]$OutputPath = "$env:TEMP\endpoint-readiness-audit.json",
    [int]$RecentErrorHours = 24
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-OsInventory {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem
    $computer = Get-CimInstance -ClassName Win32_ComputerSystem

    [pscustomobject]@{
        ComputerName = $env:COMPUTERNAME
        UserName = $env:USERNAME
        Manufacturer = $computer.Manufacturer
        Model = $computer.Model
        OperatingSystem = $os.Caption
        Version = $os.Version
        BuildNumber = $os.BuildNumber
        LastBootTime = $os.LastBootUpTime
        FreeMemoryGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    }
}

function Get-DiskHealth {
    $volumes = Get-Volume |
        Where-Object {
            $_.DriveLetter -and $_.FileSystem -eq "NTFS"
        } |
        Select-Object `
            DriveLetter,
            FileSystem,
            FileSystemLabel,
            HealthStatus,
            @{Name = "SizeGB"; Expression = {
                [math]::Round($_.Size / 1GB, 2)
            }},
            @{Name = "FreeGB"; Expression = {
                [math]::Round($_.SizeRemaining / 1GB, 2)
            }}

    foreach ($volume in $volumes) {
        $freePercentage = if ($volume.SizeGB -gt 0) {
            [math]::Round(($volume.FreeGB / $volume.SizeGB) * 100, 2)
        }
        else {
            0
        }

        [pscustomobject]@{
            Drive = "$($volume.DriveLetter):"
            Label = $volume.FileSystemLabel
            FileSystem = $volume.FileSystem
            HealthStatus = $volume.HealthStatus
            SizeGB = $volume.SizeGB
            FreeGB = $volume.FreeGB
            FreePercentage = $freePercentage
            Status = if ($freePercentage -lt 15) { "Warning" } else { "Healthy" }
        }
    }
}

function Get-ServiceHealth {
    $requiredServices = @(
        "EventLog",
        "Winmgmt",
        "LanmanWorkstation",
        "Schedule",
        "BITS"
    )

    foreach ($serviceName in $requiredServices) {
        $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

        [pscustomobject]@{
            Name = $serviceName
            Exists = $null -ne $service
            Status = if ($null -ne $service) {
                $service.Status.ToString()
            }
            else {
                "NotInstalled"
            }
            StartType = if ($null -ne $service) {
                $service.StartType.ToString()
            }
            else {
                "Unknown"
            }
            Compliance = if ($null -ne $service -and $service.Status -eq "Running") {
                "Healthy"
            }
            else {
                "Review"
            }
        }
    }
}

function Get-SecurityStatus {
    $defenderCommand = Get-Command `
        -Name Get-MpComputerStatus `
        -ErrorAction SilentlyContinue

    if ($null -eq $defenderCommand) {
        return [pscustomobject]@{
            Available = $false
            Status = "Defender command unavailable"
        }
    }

    try {
        $defender = Get-MpComputerStatus

        [pscustomobject]@{
            Available = $true
            AntivirusEnabled = $defender.AntivirusEnabled
            RealTimeProtectionEnabled = $defender.RealTimeProtectionEnabled
            AntivirusSignatureAge = $defender.AntivirusSignatureAge
            QuickScanAge = $defender.QuickScanAge
            Status = if (
                $defender.AntivirusEnabled -and
                $defender.RealTimeProtectionEnabled
            ) {
                "Healthy"
            }
            else {
                "Review"
            }
        }
    }
    catch {
        [pscustomobject]@{
            Available = $true
            Status = "Unable to query Defender"
            Error = $_.Exception.Message
        }
    }
}

function Get-PendingRebootStatus {
    $rebootLocations = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
    )

    $pendingLocations = @(
        $rebootLocations |
            Where-Object { Test-Path $_ }
    )

    [pscustomobject]@{
        PendingReboot = $pendingLocations.Count -gt 0
        DetectedBy = $pendingLocations
    }
}

function Get-RecentSystemErrors {
    param(
        [int]$Hours
    )

    $startTime = (Get-Date).AddHours(-$Hours)

    try {
        Get-WinEvent -FilterHashtable @{
            LogName = "System"
            Level = 2
            StartTime = $startTime
        } -MaxEvents 20 |
            Select-Object `
                TimeCreated,
                ProviderName,
                Id,
                LevelDisplayName,
                Message
    }
    catch {
        [pscustomobject]@{
            QueryFailed = $true
            Error = $_.Exception.Message
        }
    }
}

function Invoke-EndpointReadinessAudit {
    param(
        [string]$Destination,
        [int]$ErrorLookbackHours
    )

    $audit = [ordered]@{
        GeneratedAt = Get-Date
        Computer = Get-OsInventory
        Disks = @(Get-DiskHealth)
        Services = @(Get-ServiceHealth)
        Security = Get-SecurityStatus
        Reboot = Get-PendingRebootStatus
        RecentSystemErrors = @(
            Get-RecentSystemErrors -Hours $ErrorLookbackHours
        )
    }

    $audit |
        ConvertTo-Json -Depth 8 |
        Set-Content -Path $Destination -Encoding UTF8

    [pscustomobject]@{
        OutputPath = $Destination
        GeneratedAt = $audit.GeneratedAt
        DiskCount = $audit.Disks.Count
        ServiceCount = $audit.Services.Count
        ErrorCount = $audit.RecentSystemErrors.Count
    }
}

Invoke-EndpointReadinessAudit `
    -Destination $OutputPath `
    -ErrorLookbackHours $RecentErrorHours