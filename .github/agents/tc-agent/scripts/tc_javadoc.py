"""Read and rewrite the per-test metadata that Model B keeps in the code.

In Model B the committed test suite IS the pipeline's database. Every test the
agent writes carries a Javadoc with machine tags (see tc-test-conventions.md §A1):

    /**
     * AI-generated test. Characterizes current behaviour of OrderService (a freeze, not a spec).
     *
     * @aiGenerated
     * @mode legacy
     * @characterizes OrderService@29aeef6a
     */
    @Test
    void shouldCreateOrderWhenCustomerActive() { ... }

This module finds test methods in a Java source file, attaches the Javadoc that
belongs to each one and parses its tags. It is a small character scanner, not a
regex over raw text: string literals such as `@DisplayName("a (b)")` and comments
would otherwise break the annotation and brace matching.

It never guesses silently. A tag it cannot read, a tag on the class, a
placeholder without its `@Disabled` — each becomes a `defect` that derive-state
reports instead of dropping the test from the picture.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

AI_TAGS = ("aiGenerated", "mode", "interactive", "characterizes", "deferred", "note")
MODES = ("legacy", "spec-driven")
TEST_ANNOTATIONS = {"Test", "ParameterizedTest", "RepeatedTest", "TestFactory", "TestTemplate"}
PLACEHOLDER_PREFIX = "AI deferred:"
CHARACTERIZES = re.compile(r"^([A-Za-z_$][\w$]*)@([0-9a-fA-F]{7,40})$")

ANN = r"@[A-Za-z_][\w.]*(?:\s*\((?:[^()]|\([^()]*\))*\))?"
METHOD = re.compile(
    rf"((?:{ANN}\s*)+)"
    r"((?:(?:public|protected|private|static|final|synchronized|abstract|default)\s+)*)"
    r"(?:<[^>]*>\s*)?"
    r"([\w.$<>\[\],? ]+?)\s+"
    r"([A-Za-z_$][\w$]*)\s*\("
)
ANN_NAME = re.compile(r"@([A-Za-z_][\w.]*)")
CLASS_DECL = re.compile(r"\b(class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")
DISABLED = re.compile(r'@(?:[\w.]*\.)?Disabled\s*(?:\(\s*(?:value\s*=\s*)?"((?:[^"\\]|\\.)*)"\s*\))?')


# ------------------------------------------------------------------ model ---


@dataclass
class Meta:
    """The tags of one Javadoc. `ai` is False for a test written by a human."""

    ai: bool = False
    mode: str | None = None
    interactive: bool = False
    characterizes_class: str | None = None
    characterizes_sha: str | None = None
    deferred: str | None = None
    notes: list = field(default_factory=list)
    has_ai_tags: bool = False
    defects: list = field(default_factory=list)


@dataclass
class TestMethod:
    file: str
    class_name: str
    name: str
    line: int
    annotations: list
    disabled: bool
    disabled_reason: str | None
    body_empty: bool
    prose: str
    meta: Meta
    javadoc_span: tuple | None = None

    @property
    def key(self) -> str:
        return f"{self.class_name}#{self.name}"

    @property
    def is_placeholder(self) -> bool:
        return self.meta.ai and self.meta.deferred is not None

    def as_dict(self) -> dict:
        out = {
            "method": self.key,
            "file": self.file,
            "line": self.line,
            "ai": self.meta.ai,
        }
        if self.meta.ai:
            out["mode"] = self.meta.mode
            if self.meta.interactive:
                out["interactive"] = True
            if self.meta.characterizes_class:
                out["characterizes"] = f"{self.meta.characterizes_class}@{self.meta.characterizes_sha}"
            if self.meta.deferred is not None:
                out["deferred"] = self.meta.deferred
            if self.meta.notes:
                out["notes"] = list(self.meta.notes)
        if self.disabled:
            out["disabled"] = True
        return out


# ------------------------------------------------------------------- scan ---


def mask(text: str) -> tuple[str, list]:
    """Blank out comments and literal contents, keeping offsets and newlines.

    Returns the masked text and the (start, end) spans of every Javadoc comment
    in the original. Quotes survive, so `@Disabled("x")` stays `@Disabled(" ")`.
    """
    out = list(text)
    javadocs = []
    i, n = 0, len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] not in "\r\n":
                out[k] = " "

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            end = text.find("\n", i)
            end = n if end == -1 else end
            blank(i, end)
            i = end
        elif ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            if text.startswith("/**", i) and not text.startswith("/**/", i):
                javadocs.append((i, end))
            blank(i, end)
            i = end
        elif text.startswith('"""', i):
            end = text.find('"""', i + 3)
            end = n if end == -1 else end
            blank(i + 3, end)
            i = end + 3
        elif ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            blank(i + 1, min(j, n))
            i = j + 1
        else:
            i += 1
    return "".join(out), javadocs


def _match_brace(masked: str, open_at: int, pair: str = "{}") -> int:
    depth = 0
    for k in range(open_at, len(masked)):
        if masked[k] == pair[0]:
            depth += 1
        elif masked[k] == pair[1]:
            depth -= 1
            if depth == 0:
                return k
    return len(masked) - 1


def _class_spans(masked: str) -> list:
    spans = []
    for m in CLASS_DECL.finditer(masked):
        brace = masked.find("{", m.end())
        if brace == -1:
            continue
        spans.append((brace, _match_brace(masked, brace), m.group(2)))
    return spans


def _enclosing(spans: list, pos: int) -> str:
    chain = [name for start, end, name in spans if start < pos < end]
    return "$".join(chain) if chain else ""


def parse_javadoc(raw: str) -> tuple[str, list]:
    """(first prose line, [[tag, value], ...]); continuation lines join the previous tag."""
    body = raw[3:-2] if raw.endswith("*/") else raw[3:]
    prose, tags = [], []
    for line in body.splitlines():
        s = re.sub(r"^\s*\*?\s?", "", line).strip()
        if not s:
            continue
        m = re.match(r"^@(\w+)\b\s*(.*)$", s)
        if m:
            tags.append([m.group(1), m.group(2).strip()])
        elif tags:
            tags[-1][1] = (tags[-1][1] + " " + s).strip()
        else:
            prose.append(s)
    return (prose[0] if prose else ""), tags


def build_meta(tags: list) -> Meta:
    meta = Meta()
    seen = [t for t, _ in tags if t in AI_TAGS]
    meta.has_ai_tags = bool(seen)
    if not seen:
        return meta
    for name, value in tags:
        if name in ("aiGenerated", "interactive") and value:
            meta.defects.append(f"@{name} is followed by '{value}' - write one tag per line")
        if name == "aiGenerated":
            meta.ai = True
        elif name == "mode":
            if value in MODES:
                meta.mode = value
            else:
                meta.defects.append(f"@mode '{value}' is not one of {', '.join(MODES)}")
        elif name == "interactive":
            meta.interactive = True
        elif name == "characterizes":
            m = CHARACTERIZES.match(value)
            if m:
                meta.characterizes_class, meta.characterizes_sha = m.group(1), m.group(2).lower()
            else:
                meta.defects.append(f"@characterizes '{value}' is not <Class>@<sha>")
        elif name == "deferred":
            meta.deferred = value
            if not value:
                meta.defects.append("@deferred has no reason")
        elif name == "note":
            if value:
                meta.notes.append(value)
    if not meta.ai:
        meta.defects.append("AI tags without @aiGenerated")
        return meta
    if meta.mode is None and not any("@mode" in d for d in meta.defects):
        meta.defects.append("@aiGenerated without @mode")
    if meta.mode == "legacy" and meta.characterizes_class is None \
            and not any("@characterizes" in d for d in meta.defects):
        meta.defects.append("@mode legacy without @characterizes")
    if meta.mode == "spec-driven" and meta.characterizes_class is not None:
        meta.defects.append("@mode spec-driven must not carry @characterizes")
    return meta


def parse_text(text: str, file: str = "") -> tuple[list, list]:
    """Return (test methods, file-level defects) for one Java source."""
    masked, javadocs = mask(text)
    classes = _class_spans(masked)
    used = set()
    methods = []
    for m in METHOD.finditer(masked):
        names = [a.split(".")[-1] for a in ANN_NAME.findall(m.group(1))]
        if not TEST_ANNOTATIONS.intersection(names):
            continue
        block_start, name_pos = m.start(1), m.start(4)
        boundary = max(masked.rfind(c, 0, block_start) for c in "{};")
        doc = None
        for idx, (start, end) in enumerate(javadocs):
            if start > boundary and end <= name_pos:
                doc = idx
        prose, tags = ("", [])
        span = None
        if doc is not None:
            used.add(doc)
            span = javadocs[doc]
            prose, tags = parse_javadoc(text[span[0]:span[1]])
        meta = build_meta(tags)

        raw_block = text[block_start:m.end(1)]
        dis = DISABLED.search(raw_block)
        disabled = dis is not None
        reason = (dis.group(1) if dis and dis.group(1) is not None else ("" if dis else None))

        paren = masked.find("(", m.end(4) - 1)
        close = _match_brace(masked, paren, "()")
        brace = masked.find("{", close)
        semi = masked.find(";", close)
        body_empty = False
        if brace != -1 and (semi == -1 or brace < semi):
            end = _match_brace(masked, brace)
            body_empty = masked[brace + 1:end].strip() == ""

        placeholder_marked = bool(reason and reason.startswith(PLACEHOLDER_PREFIX))
        if meta.ai and meta.deferred is not None:
            if not disabled:
                meta.defects.append("@deferred placeholder without @Disabled")
            elif not placeholder_marked:
                meta.defects.append(f'placeholder @Disabled reason must start with "{PLACEHOLDER_PREFIX}"')
            if not body_empty:
                meta.defects.append("@deferred placeholder must have an empty body")
        elif placeholder_marked:
            meta.defects.append(f'@Disabled("{PLACEHOLDER_PREFIX} ...") without @deferred in the Javadoc')

        methods.append(TestMethod(
            file=file,
            class_name=_enclosing(classes, name_pos) or Path(file).stem,
            name=m.group(4),
            line=text.count("\n", 0, name_pos) + 1,
            annotations=names,
            disabled=disabled,
            disabled_reason=reason,
            body_empty=body_empty,
            prose=prose,
            meta=meta,
            javadoc_span=span,
        ))

    defects = []
    for idx, (start, end) in enumerate(javadocs):
        if idx in used:
            continue
        _, tags = parse_javadoc(text[start:end])
        if any(t in AI_TAGS for t, _ in tags):
            line = text.count("\n", 0, start) + 1
            defects.append(f"{file}:{line}: AI tags outside a test method's Javadoc "
                           f"(tags belong on test METHODS only, never on the class)")
    return methods, defects


def parse_file(path: Path, display: str | None = None) -> tuple[list, list]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_text(text, display or Path(path).as_posix())


# ----------------------------------------------------------------- reseal ---


def reseal(path: Path, method_key: str, target_class: str, new_sha: str) -> tuple[bool, str]:
    """Move one test's freeze point to `new_sha`, touching only that Javadoc line.

    Returns (changed, detail). Line endings of the file are preserved.
    """
    path = Path(path)
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    methods, _ = parse_text(text, path.as_posix())
    hit = next((m for m in methods if m.key == method_key), None)
    if hit is None:
        return False, f"{method_key} not found in {path}"
    if hit.javadoc_span is None:
        return False, f"{method_key} has no Javadoc"
    start, end = hit.javadoc_span
    doc = text[start:end]
    pattern = re.compile(rf"(@characterizes[ \t]+{re.escape(target_class)}@)([0-9a-fA-F]{{7,40}})")
    found = pattern.search(doc)
    if not found:
        return False, f"{method_key} does not characterize {target_class}"
    old = found.group(2)
    if old.lower() == new_sha.lower():
        return False, f"{method_key} already at {new_sha}"
    new_doc = doc[:found.start(2)] + new_sha + doc[found.end(2):]
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text[:start] + new_doc + text[end:])
    return True, f"{method_key}: {target_class}@{old} -> @{new_sha}"
