"""Shared helper: read/write a JSON payload embedded in a Markdown container.

The plan artifact is a .md file (org policy blocks .json/.yaml) containing
EXACTLY ONE fenced ```json block, which is the single source of truth.
Plain .json files are also supported transparently.
"""

import json
import re
from pathlib import Path

FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def load_payload(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        matches = FENCE.findall(text)
        if len(matches) == 0:
            raise ValueError(f"No ```json fence found in {path}")
        if len(matches) > 1:
            raise ValueError(
                f"Expected exactly one ```json fence in {path}, found {len(matches)}"
            )
        return json.loads(matches[0]), text
    return json.loads(text), text


def save_payload(path: Path, payload: dict, original_text: str):
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    if path.suffix == ".md":
        new_text = FENCE.sub(lambda m: "```json\n" + rendered + "\n```",
                             original_text, count=1)
        path.write_text(new_text, encoding="utf-8")
    else:
        path.write_text(rendered + "\n", encoding="utf-8")
