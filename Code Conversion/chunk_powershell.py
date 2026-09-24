from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter


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
    chunk_size: int = 3500,
    chunk_overlap: int = 250,
) -> list[dict[str, object]]:
    """
    Produce semantic PowerShell chunks, then recursively split large units.

    chunk_size is measured in characters, not tokens. For local SLMs,
    3,500 characters is a conservative starting point.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\nfunction ",
            "\nparam(",
            "\ntry",
            "\ncatch",
            "\nif ",
            "\nforeach ",
            "\nwhile ",
            "\n\n",
            "\n",
            " ",
            "",
        ],
        keep_separator=True,
        strip_whitespace=True,
    )

    chunks: list[dict[str, object]] = []

    for unit_name, unit_source in extract_powershell_units(source):
        pieces = splitter.split_text(unit_source)

        for piece_index, piece in enumerate(pieces):
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