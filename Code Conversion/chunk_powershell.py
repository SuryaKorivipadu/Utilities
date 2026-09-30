from __future__ import annotations

import json
from pathlib import Path

from transformers import AutoTokenizer
from checkPowershellComponents import get_powershell_components

tokenizer = AutoTokenizer.from_pretrained(
    "Qwen/Qwen2.5-Coder-7B-Instruct"
)

def token_count(text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))

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

    for ast_unit in get_powershell_components(source):
        unit_name = ast_unit["Name"]
        components = ast_unit["Statements"]
        body_source = "\n\n".join(component["Text"] for component in components)
        unit_source = (
            f"function {unit_name} {{\n{body_source}\n}}"
            if unit_name != "script"
            else body_source
        )

        if token_count(unit_source) > chunk_size:
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
    input_path = Path(r"C:\Sury(A)\Code\Utilities\Data\Code Conversion\EndpointReadinessAuditing.ps1")
    output_path = Path("powershell_chunks.json")

    source = input_path.read_text(encoding="utf-8")

    chunks = chunk_powershell(
        source=source,
        source_path=str(input_path),
        chunk_size=500,
        chunk_overlap=50,
    )

    output_path.write_text(
        json.dumps(chunks, indent=2),
        encoding="utf-8",
    )

    print(f"Created {len(chunks)} chunks in {output_path}")


if __name__ == "__main__":
    main()