"""Read and rewrite the per-test metadata the pipeline keeps in the code.

The committed test suite IS the pipeline's database. Every test the
agent writes carries a one-line Javadoc (conventions §A1), optionally followed by notes:

    /**
     * AI-generated test. Mode: characterization, interactive: false
     * Note: reported as defect: fee 0 is accepted
     */
    @Test
    void shouldCreateOrderWhenCustomerActive() { ... }

That first line is the marker: a method that has one was written by the agent; a
placeholder says `AI-generated placeholder.` and carries its reason in
`@Disabled("AI deferred: <reason>")`. Plain text, not Javadoc `@tags`, so no IDE or
doclint flags it. A test's freeze point is the newest commit of its own lines (git
blame), not a line in the code.

This module finds test methods in a Java source file, attaches the Javadoc that
belongs to each one and parses its tags. It is a small character scanner, not a
regex over raw text: string literals such as `@DisplayName("a (b)")` and comments
would otherwise break the annotation and brace matching.

It never guesses silently. A first line it cannot read, metadata on the class, a
placeholder without its `@Disabled` / `@Ignore` — each becomes a `defect` that derive-state
reports instead of dropping the test from the picture.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

MODES = ("characterization", "spec-driven")
HEADER = re.compile(r"^AI-generated (test|placeholder)\.\s*Mode:\s*(characterization|spec-driven)\s*,"
                    r"\s*interactive:\s*(true|false)\s*$")
AI_PREFIX = re.compile(r"^AI-generated (?:test|placeholder)\b")
NOTE = re.compile(r"^Note:\s*(.*)$")
HEADER_FORMAT = "AI-generated test|placeholder. Mode: <characterization|spec-driven>, interactive: <true|false>"
TEST_ANNOTATIONS = {"Test", "ParameterizedTest", "RepeatedTest", "TestFactory", "TestTemplate"}
PLACEHOLDER_PREFIX = "AI deferred:"

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
# JUnit 5 disables with @Disabled, JUnit 4 with @Ignore. Both carry the reason
# as their single string value, so one pattern reads either.
DISABLED = re.compile(r'@(?:[\w.]*\.)?(?:Disabled|Ignore)\b\s*(?:\(\s*(?:value\s*=\s*)?"((?:[^"\\]|\\.)*)"\s*\))?')
DISABLE_ANNOTATION = "@Disabled / @Ignore"


# ------------------------------------------------------------------ model ---


@dataclass
class Meta:
    """The tags of one Javadoc. `ai` is False for a test written by a human."""

    ai: bool = False
    kind: str | None = None        # "test" | "placeholder"
    mode: str | None = None
    interactive: bool = False
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
    first_line: int = 0            # Javadoc (or first annotation) .. closing brace: the lines git blame reads
    last_line: int = 0
    freeze: str | None = None      # newest commit of those lines, set by derive-state

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
            if self.freeze:
                out["frozen_at"] = self.freeze
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


def parse_javadoc(raw: str) -> tuple[str, list, list]:
    """(first line, [[tag, value], ...], problems) - tags `header` and `note`.

    A Javadoc whose first line does not start with "AI-generated test|placeholder" is
    a human's: no tags, no problems. A line after a `Note:` continues it.
    """
    body = raw[3:-2] if raw.endswith("*/") else raw[3:]
    lines = [s for s in (re.sub(r"^\s*\*?\s?", "", line).strip() for line in body.splitlines()) if s]
    first = lines[0] if lines else ""
    if not AI_PREFIX.match(first):
        return first, [], []
    tags, problems = [], []
    m = HEADER.match(first)
    if m:
        tags.append(["header", m.groups()])
    else:
        problems.append(f"first line '{first}' is not '{HEADER_FORMAT}'")
    for s in lines[1:]:
        note = NOTE.match(s)
        if note:
            tags.append(["note", note.group(1).strip()])
        elif s.startswith("@"):                      # a Javadoc block tag (@see ...)
            continue
        elif tags and tags[-1][0] == "note":
            tags[-1][1] = (tags[-1][1] + " " + s).strip()
        else:
            problems.append(f"unexpected line '{s}' in an AI Javadoc (only 'Note: ...' may follow the first line)")
    return first, tags, problems


def build_meta(tags: list, problems: list | None = None) -> Meta:
    meta = Meta()
    meta.has_ai_tags = bool(tags) or bool(problems)
    if not meta.has_ai_tags:
        return meta
    meta.ai = True
    meta.defects.extend(problems or [])
    for name, value in tags:
        if name == "header":
            meta.kind, meta.mode, meta.interactive = value[0], value[1], value[2] == "true"
        elif name == "note" and value:
            meta.notes.append(value)
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
        prose, tags, problems = ("", [], [])
        span = None
        if doc is not None:
            used.add(doc)
            span = javadocs[doc]
            prose, tags, problems = parse_javadoc(text[span[0]:span[1]])
        meta = build_meta(tags, problems)

        raw_block = text[block_start:m.end(1)]
        dis = DISABLED.search(raw_block)
        disabled = dis is not None
        reason = (dis.group(1) if dis and dis.group(1) is not None else ("" if dis else None))

        paren = masked.find("(", m.end(4) - 1)
        close = _match_brace(masked, paren, "()")
        brace = masked.find("{", close)
        semi = masked.find(";", close)
        body_empty = False
        end = close
        if brace != -1 and (semi == -1 or brace < semi):
            end = _match_brace(masked, brace)
            body_empty = masked[brace + 1:end].strip() == ""

        placeholder_marked = bool(reason and reason.startswith(PLACEHOLDER_PREFIX))
        if meta.kind == "placeholder":
            meta.deferred = reason[len(PLACEHOLDER_PREFIX):].strip() if placeholder_marked else ""
            if not disabled:
                meta.defects.append(f"AI-generated placeholder without {DISABLE_ANNOTATION}")
            elif not placeholder_marked:
                meta.defects.append(f'placeholder {DISABLE_ANNOTATION} reason must start with "{PLACEHOLDER_PREFIX}"')
            elif not meta.deferred:
                meta.defects.append(f'placeholder {DISABLE_ANNOTATION}("{PLACEHOLDER_PREFIX} ...") has no reason')
            if not body_empty:
                meta.defects.append("AI-generated placeholder must have an empty body")
        elif placeholder_marked:
            meta.defects.append(f'{DISABLE_ANNOTATION} ("{PLACEHOLDER_PREFIX} ...") on a method whose Javadoc '
                                f'is not "AI-generated placeholder. Mode: ..."')

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
            first_line=text.count("\n", 0, span[0] if span else block_start) + 1,
            last_line=text.count("\n", 0, max(end, name_pos)) + 1,
        ))

    defects = []
    for idx, (start, end) in enumerate(javadocs):
        if idx in used:
            continue
        _, tags, problems = parse_javadoc(text[start:end])
        if problems or tags:
            line = text.count("\n", 0, start) + 1
            defects.append(f"{file}:{line}: an AI-generated Javadoc outside a test method "
                           f"(it belongs on test METHODS only, never on the class)")
    return methods, defects


def parse_file(path: Path, display: str | None = None) -> tuple[list, list]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_text(text, display or Path(path).as_posix())
