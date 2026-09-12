"""The single reader/writer for the JSON payload embedded in a Markdown artifact.

Every artifact in this pipeline is a Markdown container holding EXACTLY ONE
fenced ```json block, which is the contract (see common/CONTRACTS.md). Plain
.json files are accepted too, so the same helpers work on a schema or a profile.

This module is the ONLY place that knows how to find that block. It used to be
implemented three times — here, in validate_plan.py and in the Reviewer's
_common.py — with three different regexes: one anchored to the start of a line,
two not. The same file could then pass one tool and be rejected by the next,
which is the worst kind of disagreement in a pipeline that hands artifacts from
agent to agent. The anchored form is the strict one, so it is the one that
survived: a fence must start at the beginning of a line, exactly as every agent
is told to write it.

Standard library only.
"""

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
