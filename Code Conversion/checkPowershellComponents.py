import argparse
import json
import subprocess
from pathlib import Path

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

$functionType = [System.Management.Automation.Language.FunctionDefinitionAst]
$components = [System.Collections.Generic.List[object]]::new()

foreach ($usingStatement in $ast.UsingStatements) {
    $components.Add([pscustomobject]@{
        Name = "script"
        Type = $usingStatement.GetType().Name
        StartOffset = $usingStatement.Extent.StartOffset
        StartLine = $usingStatement.Extent.StartLineNumber
        EndLine = $usingStatement.Extent.EndLineNumber
        Text = $usingStatement.Extent.Text
        Statements = @([pscustomobject]@{
            Type = $usingStatement.GetType().Name
            StartLine = $usingStatement.Extent.StartLineNumber
            EndLine = $usingStatement.Extent.EndLineNumber
            Text = $usingStatement.Extent.Text
        })
    })
}

if ($null -ne $ast.ParamBlock) {
    $attributes = @($ast.ParamBlock.Attributes)
    foreach ($attribute in $attributes) {
        $components.Add([pscustomobject]@{
            Name = "script"
            Type = $attribute.GetType().Name
            StartOffset = $attribute.Extent.StartOffset
            StartLine = $attribute.Extent.StartLineNumber
            EndLine = $attribute.Extent.EndLineNumber
            Text = $attribute.Extent.Text
            Statements = @([pscustomobject]@{
                Type = $attribute.GetType().Name
                StartLine = $attribute.Extent.StartLineNumber
                EndLine = $attribute.Extent.EndLineNumber
                Text = $attribute.Extent.Text
            })
        })
    }

    $paramStart = if ($attributes.Count -gt 0) {
        ($attributes | ForEach-Object { $_.Extent.EndOffset } | Measure-Object -Maximum).Maximum
    }
    else {
        $ast.ParamBlock.Extent.StartOffset
    }
    $paramEnd = $ast.ParamBlock.Extent.EndOffset

    if ($paramEnd -gt $paramStart) {
        $paramText = $source.Substring($paramStart, $paramEnd - $paramStart).Trim()
        if ($paramText) {
            $startLine = $source.Substring(0, $paramStart).Split("`n").Length
            $components.Add([pscustomobject]@{
                Name = "script"
                Type = "ParamBlockAst"
                StartOffset = $paramStart
                StartLine = $startLine
                EndLine = $ast.ParamBlock.Extent.EndLineNumber
                Text = $paramText
                Statements = @([pscustomobject]@{
                    Type = "ParamBlockAst"
                    StartLine = $startLine
                    EndLine = $ast.ParamBlock.Extent.EndLineNumber
                    Text = $paramText
                })
            })
        }
    }
}

foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -is $functionType) {
        $functionStatements = [System.Collections.Generic.List[object]]::new()
        if ($null -ne $statement.Body.ParamBlock) {
            $functionStatements.Add($statement.Body.ParamBlock)
        }
        foreach ($bodyStatement in $statement.Body.EndBlock.Statements) {
            $functionStatements.Add($bodyStatement)
        }

        $statements = @(
            $functionStatements | ForEach-Object {
                [pscustomobject]@{
                    Type = $_.GetType().Name
                    StartLine = $_.Extent.StartLineNumber
                    EndLine = $_.Extent.EndLineNumber
                    Text = $_.Extent.Text
                }
            }
        )
        $components.Add([pscustomobject]@{
            Name = $statement.Name
            Type = $statement.GetType().Name
            StartOffset = $statement.Extent.StartOffset
            StartLine = $statement.Extent.StartLineNumber
            EndLine = $statement.Extent.EndLineNumber
            Text = $statement.Extent.Text
            Statements = $statements
        })
    }
    else {
        $components.Add([pscustomobject]@{
            Name = "script"
            Type = $statement.GetType().Name
            StartOffset = $statement.Extent.StartOffset
            StartLine = $statement.Extent.StartLineNumber
            EndLine = $statement.Extent.EndLineNumber
            Text = $statement.Extent.Text
            Statements = @([pscustomobject]@{
                Type = $statement.GetType().Name
                StartLine = $statement.Extent.StartLineNumber
                EndLine = $statement.Extent.EndLineNumber
                Text = $statement.Extent.Text
            })
        })
    }
}

$result = [System.Collections.Generic.List[object]]::new()
$order = 0
foreach ($component in ($components | Sort-Object StartOffset)) {
    $order++
    $result.Add([pscustomobject]@{
        Order = $order
        Name = $component.Name
        Type = $component.Type
        StartLine = $component.StartLine
        EndLine = $component.EndLine
        Text = $component.Text
        Statements = $component.Statements
    })
}

ConvertTo-Json -InputObject @($result) -Depth 6 -Compress
"""

def get_powershell_components(source: str) -> list[dict[str, object]]:
    """Return top-level script and function units with their AST statements."""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PARSER_SCRIPT],
        input=source,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List PowerShell AST components.")
    parser.add_argument("script", type=Path, help="PowerShell script to inspect")
    args = parser.parse_args()
    print(
        json.dumps(
            get_powershell_components(args.script.read_text(encoding="utf-8")),
            indent=2,
        )
    )