from __future__ import annotations

import json, re
from pathlib import Path

from transformers import AutoTokenizer
from checkPowershellComponents import get_powershell_components

tokenizer = AutoTokenizer.from_pretrained(
    "Qwen/Qwen2.5-Coder-7B-Instruct"
)

def token_count(text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))

# The raw-string regex uses a zero-width lookahead, so a split starts at the
# declaration instead of consuming it. With MULTILINE, ^ means each line start;
# [ \t]* allows indentation, `function` is case-insensitive, and [ \t]+ requires
# whitespace before a name made of letters, digits, underscores, or hyphens.
# Indented nested functions match too; this pattern does not track brace depth.
# For example, it matches "function Get-OsInventory" and
# "    function Get_Nested2".
FUNCTION_PATTERN = re.compile(
    r"(?=^[ \t]*function[ \t]+[A-Za-z0-9_-]+)",
    re.MULTILINE | re.IGNORECASE,
)


def extract_powershell_units(source: str) -> list[tuple[str, str]]:
    """Split a PowerShell script into named top-level function units."""
    matches = list(FUNCTION_PATTERN.finditer(source))

    if not matches:
        return [("script", source.strip())]

    units: list[tuple[str, str]] = []

    preamble = source[: matches[0].start()].strip()
    if preamble:
        units.append(("preamble", preamble))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        unit = source[start:end].strip()

        function_match = re.search(
            r"function[ \t]+([A-Za-z0-9_-]+)",
            unit,
            re.IGNORECASE,
        )

        name = function_match.group(1) if function_match else f"unit_{index + 1}"
        units.append((name, unit))

    return units


def build_context(function_name: str, source_path: str) -> str:
    return f"""You are converting PowerShell to Python.

Source file: {source_path}
Current PowerShell unit: {function_name}

Requirements:
- Preserve behavior and validation.
- Preserve error handling.
- Replace PowerShell pipelines with clear Python equivalents.
- Use only Python standard-library functionality unless explicitly requested.
- Return valid, runnable Python.
- Explain assumptions briefly after the code.
"""


def chunk_powershell(
    source: str,
    source_path: str,
    chunk_size: int = 500,
    chunk_overlap: int = 250,
) -> list[dict[str, object]]:
    """
    Produce semantic PowerShell chunks, then split large units based on powershell ast parser.
    """
    chunks: list[dict[str, object]] = []

    for unit_name, unit_source in extract_powershell_units(source):
        if token_count(unit_source) > chunk_size:
            ast_units = get_powershell_components(unit_source)
            ast_unit = next(
                (unit for unit in ast_units if unit["Name"] == unit_name),
                ast_units[0],
            )
            components = ast_unit["Statements"]
            pieces: list[list[dict[str, str]]] = []
            pending: list[dict[str, str]] = []

            for component in components:
                candidate_components = pending + [component]
                candidate_text = "\n\n".join(
                    item["Text"] for item in candidate_components
                )

                if token_count(candidate_text) <= chunk_size:
                    pending = candidate_components
                    continue

                if pending:
                    pieces.append(pending)
                pending = [component]

                if token_count(component["Text"]) > chunk_size:
                    pieces.append(pending)
                    pending = []

            if pending:
                pieces.append(pending)

            print(
                f"Unit '{unit_name}' exceeds {chunk_size} tokens; "
                f"split into {len(pieces)} AST-based chunks."
            )

            for piece_index, piece_components in enumerate(pieces):
                piece = "\n\n".join(
                    component["Text"] for component in piece_components
                )
                piece_token_count = token_count(piece)
                chunks.append(
                    {
                        "chunk_id": f"{unit_name}:{piece_index + 1}",
                        "source_file": source_path,
                        "unit": unit_name,
                        "part": piece_index + 1,
                        "total_parts": len(pieces),
                        "context": build_context(unit_name, source_path),
                        "powershell": piece,
                        "character_count": len(piece),
                        "token_count": piece_token_count,
                        "over_token_limit": piece_token_count > chunk_size,
                    }
                )
        else:
            chunks.append(
                {
                    "chunk_id": unit_name,
                    "source_file": source_path,
                    "unit": unit_name,
                    "part": 1,
                    "total_parts": 1,
                    "context": build_context(unit_name, source_path),
                    "powershell": unit_source,
                    "character_count": len(unit_source),
                }
            )

    return chunks


def main() -> None:
    input_path = Path("Invoke-EndpointReadinessAudit.ps1")
    output_path = Path("powershell_chunks.json")

    source = input_path.read_text(encoding="utf-8")

    chunks = chunk_powershell(
        source=source,
        source_path=str(input_path),
        chunk_size=3500,
        chunk_overlap=250,
    )

    output_path.write_text(
        json.dumps(chunks, indent=2),
        encoding="utf-8",
    )

    print(f"Created {len(chunks)} chunks in {output_path}")


if __name__ == "__main__":
    main()