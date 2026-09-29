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
    $warningThreshold = 15
    $criticalThreshold = 5

    $volumes = Get-Volume |
        Where-Object {
            $_.DriveLetter -and $_.FileSystem -eq "NTFS"
        } |
        Select-Object `
            DriveLetter,
            DriveType,
            FileSystem,
            FileSystemLabel,
            HealthStatus,
            OperationalStatus,
            Path,
            UniqueId,
            @{Name = "SizeGB"; Expression = {
                [math]::Round($_.Size / 1GB, 2)
            }},
            @{Name = "FreeGB"; Expression = {
                [math]::Round($_.SizeRemaining / 1GB, 2)
            }}

    foreach ($volume in $volumes) {
        $usedGB = [math]::Round($volume.SizeGB - $volume.FreeGB, 2)

        $freePercentage = if ($volume.SizeGB -gt 0) {
            [math]::Round(($volume.FreeGB / $volume.SizeGB) * 100, 2)
        }
        else {
            0
        }

        $freeGBToCriticalThreshold = [math]::Max(
            0,
            [math]::Round(($volume.SizeGB * $criticalThreshold / 100) - $volume.FreeGB, 2)
        )

        $status = if ($volume.HealthStatus -ne "Healthy") {
            "Review"
        }
        elseif ($freePercentage -lt $criticalThreshold) {
            "Critical"
        }
        elseif ($freePercentage -lt $warningThreshold) {
            "Warning"
        }
        else {
            "Healthy"
        }

        $recommendedAction = switch ($status) {
            "Critical" {
                "Free disk space immediately; the volume is below the critical threshold."
            }
            "Warning" {
                "Review disk usage and plan cleanup before free space falls below the critical threshold."
            }
            "Review" {
                "Investigate the volume health reported by Windows before relying on this disk."
            }
            default {
                "No action required. Continue routine capacity monitoring."
            }
        }

        [pscustomobject]@{
            Drive = "$($volume.DriveLetter):"
            IsSystemDrive = $volume.DriveLetter -eq $env:SystemDrive.Substring(0, 1)
            DriveType = $volume.DriveType
            Label = $volume.FileSystemLabel
            FileSystem = $volume.FileSystem
            HealthStatus = $volume.HealthStatus
            OperationalStatus = $volume.OperationalStatus
            VolumePath = $volume.Path
            VolumeId = $volume.UniqueId
            SizeGB = $volume.SizeGB
            FreeGB = $volume.FreeGB
            UsedGB = $usedGB
            FreePercentage = $freePercentage
            FreeGBToCriticalThreshold = $freeGBToCriticalThreshold
            UsedPercentage = [math]::Round(100 - $freePercentage, 2)
            WarningThresholdPercentage = $warningThreshold
            CriticalThresholdPercentage = $criticalThreshold
            Status = $status
            RecommendedAction = $recommendedAction
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