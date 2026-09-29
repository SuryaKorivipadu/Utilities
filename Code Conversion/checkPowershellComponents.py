import json
import subprocess

PARSER_SCRIPT = r"""
$source = [Console]::In.ReadToEnd()
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput(
    $source,
    [ref]$tokens,
    [ref]$errors
)

if ($errors.Count -gt 0) {
    [Console]::Error.WriteLine(($errors | ForEach-Object Message) -join "`n")
    exit 2
}

$functions = $ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true)

$result = foreach ($function in $functions) {
    [pscustomobject]@{
        Name = $function.Name
        Statements = @(
            $function.Body.EndBlock.Statements | ForEach-Object {
                [pscustomobject]@{
                    Type = $_.GetType().Name
                    Text = $_.Extent.Text
                }
            }
        )
    }
}

ConvertTo-Json -InputObject @($result) -Depth 6 -Compress
"""

def get_function_statements(source: str) -> list[dict]:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PARSER_SCRIPT],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


source = r"""function Get-DiskHealth {
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
}"""

print(json.dumps(get_function_statements(source), indent=2))