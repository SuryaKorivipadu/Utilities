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
$functions = @($ast.EndBlock.Statements | Where-Object { $_ -is $functionType })
$scriptStatements = [System.Collections.Generic.List[object]]::new()

foreach ($usingStatement in $ast.UsingStatements) {
    $scriptStatements.Add($usingStatement)
}

if ($null -ne $ast.ParamBlock) {
    $scriptStatements.Add($ast.ParamBlock)
}

foreach ($statement in $ast.EndBlock.Statements) {
    if ($statement -isnot $functionType) {
        $scriptStatements.Add($statement)
    }
}

$result = [System.Collections.Generic.List[object]]::new()
if ($scriptStatements.Count -gt 0) {
    $result.Add([pscustomobject]@{
        Name = "script"
        Statements = @($scriptStatements | ForEach-Object {
            [pscustomobject]@{
                Type = $_.GetType().Name
                Text = $_.Extent.Text
            }
        })
    })
}

foreach ($function in $functions) {
    $functionStatements = [System.Collections.Generic.List[object]]::new()
    if ($null -ne $function.Body.ParamBlock) {
        $functionStatements.Add($function.Body.ParamBlock)
    }
    foreach ($statement in $function.Body.EndBlock.Statements) {
        $functionStatements.Add($statement)
    }

    $result.Add([pscustomobject]@{
        Name = $function.Name
        Statements = @(
            $functionStatements | ForEach-Object {
                [pscustomobject]@{
                    Type = $_.GetType().Name
                    Text = $_.Extent.Text
                }
            }
        )
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