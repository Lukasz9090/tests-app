"""Shared helpers for the pipeline scripts (Model B).

Nothing here reads a plan or a generation report. The target, its Maven module
and the test classes that exercise it are derived from the slug and the file
system, so the same checks run before a plan exists (derive-state) and inside a
run (the Reviewer). Every file a script writes lands in the RUN directory,
`.test-agent/runs/<slug>/<run-id>/`, never in a shared location.

Standard library only. Exit-code convention used by every check script:
  0 - check ran, gate satisfied
  1 - check ran, gate NOT satisfied (quality defect -> repair loop)
  2 - check could not run (environment/tooling problem -> BLOCKED)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tc_md_payload import load_payload as _load_payload  # noqa: E402

PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)

DEFAULT_GATES = {
    "branch_coverage_target_scope": 0.80,
    "mutation_score_target_scope": 0.70,
}
# Both tools must be able to READ the class files the project was compiled with.
# JaCoCo 0.8.15 is the first release with official Java 26 (class file major 70)
# support; older ones fail the report goal outright. Override per repo under
# `tooling` in tc-project-profile.md when the build targets an older JDK.
DEFAULT_VERSIONS = {"jacoco": "0.8.15", "pit": "1.25.9"}


class CheckError(Exception):
    """Environment/tooling failure. Callers map this to exit code 2."""


# --------------------------------------------------------------------- io ---


def payload(path: Path) -> dict:
    """The artifact's contract, read by the shared fence reader.

    Only the error type is local: every caller here maps a bad artifact to exit
    code 2 through CheckError.
    """
    if not path.exists():
        raise CheckError(f"missing artifact: {path}")
    try:
        return _load_payload(path)[0]
    except ValueError as exc:
        raise CheckError(f"INVALID_ARTIFACT {exc}") from exc


SKIP_DIRS = {"target", "build", "out", ".git", ".idea", ".test-agent", "node_modules"}
TEST_ANNOTATION = re.compile(r"@(?:[\w.]*\.)?(?:Test|ParameterizedTest|RepeatedTest|TestFactory|TestTemplate)\b")


# --------------------------------------------------------------- run dirs ---


def runs_root(repo: Path, slug: str) -> Path:
    return repo / ".test-agent" / "runs" / slug


def run_dir(repo: Path, slug: str, run: str) -> Path:
    """The directory of one run. `latest` resolves to the newest existing run."""
    root = runs_root(repo, slug)
    if run == "latest":
        runs = sorted(p for p in root.glob("*") if (p / "run.json").is_file()) if root.is_dir() else []
        if not runs:
            raise CheckError(f"no run found under {root} - start one with tc_orchestrate.py start")
        return runs[-1]
    path = root / run
    if not (path / "run.json").is_file():
        raise CheckError(f"run {run} not found: {path}/run.json is missing")
    return path


def load_run(directory: Path) -> dict:
    return json.loads((directory / "run.json").read_text(encoding="utf-8"))


def save_run(directory: Path, data: dict) -> None:
    (directory / "run.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                        encoding="utf-8")


def checks_dir(directory: Path) -> Path:
    path = directory / "checks"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ----------------------------------------------------------------- target ---


class Target:
    """What a slug names: class, optional method, source file, FQCN, module."""

    def __init__(self, repo: Path, slug: str, cls: str, method: str | None,
                 file: Path, fqcn: str, module: str | None):
        self.repo, self.slug, self.cls, self.method = repo, slug, cls, method
        self.file, self.fqcn, self.module = file, fqcn, module

    @property
    def rel_file(self) -> str:
        return self.file.resolve().relative_to(self.repo.resolve()).as_posix()

    @property
    def scope(self) -> str:
        return f"{self.fqcn}.{self.method}" if self.method else self.fqcn

    def as_dict(self) -> dict:
        out = {"slug": self.slug, "class": self.cls, "fqcn": self.fqcn,
               "file": self.rel_file, "module": self.module}
        if self.method:
            out["method"] = self.method
        return out


class TargetError(CheckError):
    """A slug that names no class, or more than one. `code` is machine-readable."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def find_roots(repo: Path) -> tuple[list, list]:
    """Maven source and test roots of every module (Maven only)."""
    src, test = [], []
    poms = (p for p in repo.rglob("pom.xml") if not SKIP_DIRS.intersection(p.relative_to(repo).parts))
    for pom_dir in sorted({p.parent for p in poms}):
        m, t = pom_dir / "src/main/java", pom_dir / "src/test/java"
        if m.is_dir():
            src.append(m)
        if t.is_dir():
            test.append(t)
    return src, test


def java_files(roots) -> list:
    out = []
    for root in roots:
        for f in root.rglob("*.java"):
            if not SKIP_DIRS.intersection(f.relative_to(root).parts):
                out.append(f)
    return out


def resolve_target(repo: Path, slug: str) -> Target:
    """Slug (`Class`, `Class.method` or a path to a .java file) -> Target.

    Never guesses: no match is TARGET_NOT_FOUND, several are TARGET_AMBIGUOUS.
    """
    repo = Path(repo).resolve()
    if not any(p for p in repo.rglob("pom.xml") if not SKIP_DIRS.intersection(p.relative_to(repo).parts)):
        raise TargetError("UNSUPPORTED_REPOSITORY", "no pom.xml found - this pipeline is Maven-only")
    src_roots, _ = find_roots(repo)
    method = None
    if slug.endswith(".java") and (repo / slug).is_file():
        file = (repo / slug).resolve()
        cls = file.stem
    else:
        parts = slug.split(".")
        cls = parts[0]
        method = parts[1] if len(parts) > 1 else None
        hits = [f for f in java_files(src_roots) if f.stem == cls]
        if not hits:
            raise TargetError("TARGET_NOT_FOUND", f"no {cls}.java under the source roots")
        if len(hits) > 1:
            listing = ", ".join(h.relative_to(repo).as_posix() for h in hits)
            raise TargetError("TARGET_AMBIGUOUS", f"{cls}.java exists in several places: {listing}")
        file = hits[0].resolve()
    return Target(repo, slug, cls, method, file, fqcn_of_file(file), module_for_target(repo, file))


def mentions(text: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


def discover_test_classes(repo: Path, target: Target) -> list:
    """Test classes that exercise the target: human and AI tests alike.

    A file under a test root counts when its name contains the target's class
    name or its source uses that name as a whole word, AND it declares at least
    one test method (so builders and fixtures that merely mention the class are
    not handed to surefire). Returns [(fqcn, path), ...] sorted by path.
    """
    _, test_roots = find_roots(Path(repo).resolve())
    found = []
    for f in java_files(test_roots):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not TEST_ANNOTATION.search(text):
            continue
        if target.cls in f.stem or mentions(text, target.cls):
            found.append((fqcn_of_file(f), f))
    return sorted(found, key=lambda pair: str(pair[1]))


def write_container(path: Path, title: str, summary: list, data: dict) -> None:
    """Markdown container: title + human summary + exactly one json fence (D19)."""
    lines = [f"# {title}", ""]
    lines += [f"- {item}" for item in summary]
    lines += ["", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_xml(path: Path):
    """Parse a report XML defensively.

    JaCoCo emits a DOCTYPE pointing at report.dtd; some parsers refuse to
    continue without the DTD, so it is stripped. An empty or truncated file is
    reported as an environment failure with its first bytes, never as a crash.
    """
    raw = path.read_bytes()
    if not raw.strip():
        raise CheckError(f"{path} is empty - the maven goal produced no report")
    text = raw.decode("utf-8-sig", errors="replace").lstrip()
    text = re.sub(r"<!DOCTYPE[^>\[]*(\[[^\]]*\])?[^>]*>", "", text, count=1)
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        head = " ".join(text[:200].split())
        raise CheckError(f"cannot parse {path}: {exc} | starts with: {head}") from exc


# ------------------------------------------------------------------ maven ---


def write_log(directory: Path, name: str, command: list, output: str) -> Path:
    """Keep the full maven output next to the check result.

    Terminals truncate, error messages are summaries, and re-running a failed
    maven goal to see what it said costs minutes. The log is the ground truth.
    """
    path = checks_dir(directory) / f"maven-{name}.log"
    path.write_text(
        "$ " + " ".join(str(part) for part in command) + "\n\n" + output,
        encoding="utf-8",
        errors="replace",
    )
    return path


def mvn_executable() -> str:
    return "mvn.cmd" if os.name == "nt" else "mvn"


def run(cmd: list, cwd: Path) -> tuple:
    """Run a command, returning (returncode, combined output)."""
    try:
        if os.name == "nt":
            proc = subprocess.run(
                subprocess.list2cmdline(cmd),
                cwd=str(cwd),
                shell=True,
                capture_output=True,
                text=True,
                errors="replace",
            )
        else:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                errors="replace",
            )
    except FileNotFoundError as exc:
        raise CheckError(f"cannot execute {cmd[0]}: {exc}") from exc
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


JDK_HINTS = (
    (
        "unsupported class file major version",
        "the plugin is older than the JDK that compiled these classes - pin a newer version "
        "under tooling in tc-project-profile.md (or build with an older --release)",
    ),
    (
        "incompatible version",
        "the exec file was written by a different JaCoCo version than the report goal - pin one "
        "version under tooling in tc-project-profile.md and delete target/jacoco.exec",
    ),
    (
        "invalid execution data",
        "the exec file is corrupt - delete target/jacoco.exec and re-run tc_run_tests.py",
    ),
    (
        "missing execution data",
        "no exec file - the tests ran without the agent; re-run tc_run_tests.py and read its diagnosis",
    ),
)


STOP_MARKERS = (
    "For more information about the errors",
    "To see the full stack trace",
    "Re-run Maven using the -X switch",
    "Re-run Maven with the -e switch",
    "[Help 1] http",
)


def maven_error(output: str, limit: int = 12) -> str:
    """Pull the real failure out of maven's output.

    A blind tail is useless: maven ends every failed build with generic [Help 1]
    boilerplate and the JVM appends its own warnings after that, so the actual
    MojoExecutionException scrolls out of view. Note the message itself ends with
    "-> [Help 1]", so that suffix is stripped rather than treated as a stop mark.
    """
    lines = [line.rstrip() for line in output.splitlines()]
    start = next((i for i, line in enumerate(lines) if "Failed to execute goal" in line), None)
    if start is None:
        picked = [
            line
            for line in lines
            if line.startswith("[ERROR]") and not any(m in line for m in STOP_MARKERS)
        ][:limit] or lines[-limit:]
    else:
        picked = []
        for line in lines[start:]:
            if any(marker in line for marker in STOP_MARKERS) or line.strip() == "[ERROR]":
                break
            picked.append(line)
            if len(picked) >= limit:
                break
    text = "\n".join(line.strip() for line in picked if line.strip())
    text = text.replace(" -> [Help 1]", "")
    lowered = text.lower()
    for marker, hint in JDK_HINTS:
        if marker in lowered:
            text += f"\nHINT: {hint}"
            break
    return text or output[-800:]


def module_args(module: str | None, also_make: bool = False) -> list:
    if not module:
        return []
    args = ["-pl", module]
    if also_make:
        args.append("-am")
    return args


def module_dir(repo: Path, module: str | None) -> Path:
    return repo / module if module else repo


def hardcoded_arg_line(repo: Path, module: str | None) -> Path | None:
    """Find a pom that pins surefire's <argLine> without preserving @{argLine}.

    That single line silently disables JaCoCo: prepare-agent only sets the
    argLine PROPERTY, and an explicit <argLine> in the pom wins over it, so the
    tests run without the agent and the exec file stays empty.
    """
    candidates = [module_dir(repo, module) / "pom.xml", repo / "pom.xml"]
    for pom in candidates:
        if not pom.exists():
            continue
        text = pom.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"<argLine>(.*?)</argLine>", text, re.S):
            if "@{argLine}" not in match.group(1) and "${argLine}" not in match.group(1):
                return pom
    return None


def is_module(repo: Path, candidate: str) -> bool:
    """A real maven module is a subdirectory of the repo that owns a pom.xml."""
    if not candidate or candidate in (".", "./"):
        return False
    path = repo / candidate
    return path.is_dir() and (path / "pom.xml").exists()


def pom_binds_jacoco_agent(repo: Path, module: str | None) -> Path | None:
    """Return the pom that already binds jacoco's prepare-agent to the build.

    Adding a fully-qualified prepare-agent goal on top of such a pom puts TWO
    -javaagent switches on the forked JVM; the second premain then dies with
    "duplicate class definition for java.lang.$JaCoCo" and surefire reports
    "The forked VM terminated without properly saying goodbye" before running a
    single test. The runnable contract means: inject the agent only when the pom
    does not already do it.
    """
    for pom in (module_dir(repo, module) / "pom.xml", repo / "pom.xml"):
        if not pom.exists():
            continue
        text = re.sub(r"\s+", " ", pom.read_text(encoding="utf-8", errors="replace"))
        if "jacoco-maven-plugin" in text and "prepare-agent" in text:
            return pom
    return None


def module_for_target(repo: Path, target_file: Path) -> str | None:
    """Derive the Maven module from the target's own location.

    The nearest ancestor directory that owns a pom.xml IS the module. Reports
    live under <module>/target, and looking for them at the repo root finds
    nothing while maven exits 0. None = the target lives in the root project.
    """
    try:
        current = target_file.resolve().parent
        repo = repo.resolve()
    except OSError:
        return None
    while current != repo and repo in current.parents:
        if (current / "pom.xml").exists():
            return current.relative_to(repo).as_posix()
        current = current.parent
    return None


# ---------------------------------------------------------------- profile ---


PROFILE_PATHS = (
    Path(".github") / "agents" / "tc-agent" / "tc-project-profile.md",  # committed config
)


_PROFILE_CACHE = {}


def profile(repo: Path) -> dict:
    """Quality gates and tool versions, first match wins.

    `.test-agent/` is gitignored, so a profile kept only there never reaches the
    team and every run silently falls back to DEFAULT_GATES.

    A malformed profile still falls back, but says so on stderr: a gate that
    quietly reverts to the default is the kind of degradation nobody notices
    until a weak test suite has been accepted. Cached per repo, because every
    gate and version lookup calls this.
    """
    key = str(repo)
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]

    found = {}
    for relative in PROFILE_PATHS:
        path = repo / relative
        if not path.exists():
            continue
        try:
            found = payload(path)
        except CheckError as exc:
            print(f"WARNING: ignoring {path}: {exc}. Falling back to the built-in "
                  f"gates {DEFAULT_GATES} and tool versions {DEFAULT_VERSIONS}.",
                  file=sys.stderr)
            found = {}
        break

    _PROFILE_CACHE[key] = found
    return found


def gate_value(repo: Path, key: str, override=None) -> float:
    if override is not None:
        return float(override)
    gates = profile(repo).get("quality_gates", {})
    return float(gates.get(key, DEFAULT_GATES[key]))


DEFAULT_FRESHNESS_DAYS = 7


def freshness_days(repo: Path) -> float:
    """Legacy mode refuses to freeze code younger than this (tc-project-profile.md)."""
    value = profile(repo).get("freshness_days", DEFAULT_FRESHNESS_DAYS)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(DEFAULT_FRESHNESS_DAYS)


def instruction_paths(repo: Path) -> list:
    """Extra repo instruction files named in the profile (may live outside .github)."""
    return [str(p) for p in profile(repo).get("instruction_paths", []) or []]


PROTECTED_LINE = re.compile(r"^\s*[-*]?\s*`?tc-agent-protected-branches:\s*(.*?)`?\s*$", re.M)
DEFAULT_PROTECTED = ["master"]


def protected_branches(repo: Path) -> tuple[list, str]:
    """Branches the agent never commits to, and where that list came from.

    Read from ONE line in the repo's AGENTS.md:
        tc-agent-protected-branches: master, main, release/*
    No file, no line, or an empty list -> only `master`. `master` cannot be
    un-protected by accident: an empty value falls back to the default.
    """
    agents = Path(repo) / "AGENTS.md"
    if agents.is_file():
        found = PROTECTED_LINE.search(agents.read_text(encoding="utf-8", errors="replace"))
        if found:
            names = [n.strip() for n in found.group(1).split(",") if n.strip()]
            if names:
                return names, "AGENTS.md"
    return list(DEFAULT_PROTECTED), "default"


PLUGIN_ARTIFACT = {"jacoco": "jacoco-maven-plugin", "pit": "pitest-maven"}


def pom_plugin_version(repo: Path, module: str | None, artifact_id: str) -> str | None:
    """Version declared for a plugin in the module pom or the root pom, if any."""
    pattern = re.compile(
        r"<artifactId>\s*%s\s*</artifactId>\s*<version>\s*([^<\s]+)\s*</version>" % re.escape(artifact_id)
    )
    for pom in (module_dir(repo, module) / "pom.xml", repo / "pom.xml"):
        if not pom.exists():
            continue
        text = re.sub(r"\s+", " ", pom.read_text(encoding="utf-8", errors="replace"))
        match = pattern.search(text)
        if match and not match.group(1).startswith("${"):
            return match.group(1)
    return None


def tool_version(repo: Path, tool: str, override=None, module: str | None = None) -> str:
    """CLI flag > tc-project-profile.md > version declared in the pom > agent default.

    The pom wins over the default on purpose: prepare-agent and report must run
    the same JaCoCo version, otherwise the report goal rejects the exec file.
    """
    if override:
        return str(override)
    tooling = profile(repo).get("tooling", {})
    if f"{tool}_version" in tooling:
        return str(tooling[f"{tool}_version"])
    return pom_plugin_version(repo, module, PLUGIN_ARTIFACT[tool]) or DEFAULT_VERSIONS[tool]


def recent_files(root: Path, pattern: str, since: float) -> list:
    """Files matching a glob that were written by the run we just made.

    Never trust a fixed path for maven output: multi-module layouts, custom
    reportsDirectory and aggregator roots all move it. Search, then filter by
    modification time so stale artefacts from earlier runs cannot be mistaken
    for fresh ones.
    """
    found = []
    for path in root.rglob(pattern):
        try:
            if path.stat().st_mtime >= since:
                found.append(path)
        except OSError:
            continue
    return sorted(found)


# ------------------------------------------------------------------- java ---


def fqcn_of_file(path: Path) -> str:
    match = PACKAGE.search(path.read_text(encoding="utf-8", errors="replace"))
    return f"{match.group(1)}.{path.stem}" if match else path.stem


# ------------------------------------------------------------------- cli ----


def add_common_args(parser) -> None:
    parser.add_argument("slug", help="target slug, e.g. OrderService or OrderService.createOrder")
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--run", default="latest", help="run id, or `latest` (default)")
    parser.add_argument("--module", default=None, help="override the maven module owning the target")
    parser.add_argument("--label", default="entry",
                        help="names this check's outputs: `entry` for derive-state, v<N>-r<M> for a review")


def open_run(args) -> tuple[Path, Path, "Target"]:
    """(repo, run directory, target) for a check script's arguments."""
    repo = Path(args.repo).resolve()
    directory = run_dir(repo, args.slug, args.run)
    target = resolve_target(repo, args.slug)
    if args.module:
        if not is_module(repo, args.module):
            raise CheckError(f"--module {args.module}: no {args.module}/pom.xml under {repo}")
        target.module = args.module.strip().rstrip("/")
    return repo, directory, target


def finish(directory: Path, name: str, title: str, summary: list, data: dict, code: int) -> int:
    out = checks_dir(directory) / name
    write_container(out, title, summary, data)
    print(f"{title}: {data.get('status')} -> {out}")
    for item in summary:
        print(f"  {item}")
    return code


def fail(message: str) -> int:
    print(f"CHECK_UNAVAILABLE: {message}", file=sys.stderr)
    return 2
