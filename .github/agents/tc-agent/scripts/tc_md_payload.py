"""Reads and writes the one ```json fence of a Markdown artifact (plain .json files too)."""

import json
import re
from pathlib import Path

FENCE = re.compile(r"^```json\s*\n(.*?)\n```", re.S | re.M)


def _extract(path: Path, text: str) -> str:
    blocks = FENCE.findall(text)
    if len(blocks) != 1:
        raise ValueError(
            f"expected exactly one ```json fence at the start of a line in {path}, "
            f"found {len(blocks)}"
        )
    return blocks[0]


def load_payload(path: Path):
    """Return (payload, original_text). Raises ValueError on a malformed file."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"file not found: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    raw = text if path.suffix.lower() == ".json" else _extract(path, text)
    try:
        return json.loads(raw), text
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def payload(path: Path) -> dict:
    """Just the payload, for callers that do not rewrite the file."""
    return load_payload(path)[0]


def save_payload(path: Path, payload: dict, original_text: str) -> None:
    """Write the payload back, leaving the prose around the fence untouched."""
    path = Path(path)
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    if path.suffix.lower() == ".json":
        path.write_text(rendered + "\n", encoding="utf-8")
        return
    new_text = FENCE.sub(lambda m: "```json\n" + rendered + "\n```", original_text, count=1)
    path.write_text(new_text, encoding="utf-8")
