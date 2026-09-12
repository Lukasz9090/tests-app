"""Shared helpers for the tc-reviewer check scripts.

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
VERSION_SUFFIX = re.compile(r"-v(\d+)(?:-r(\d+))?\.md$")

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


def _version_key(path: Path) -> tuple:
    match = VERSION_SUFFIX.search(path.name)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2) or 1))


def latest(paths) -> Path | None:
    paths = list(paths)
    return max(paths, key=_version_key) if paths else None


def plans_dir(repo: Path, slug: str) -> Path:
    return repo / ".test-agent" / "plans" / slug


def checks_dir(repo: Path, slug: str) -> Path:
    path = repo / ".test-agent" / "checks" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_plan(repo: Path, slug: str) -> tuple[Path, dict]:
    path = latest(plans_dir(repo, slug).glob("plan-v*.md"))
    if path is None:
        raise CheckError(f"no plan found in {plans_dir(repo, slug)}")
    return path, payload(path)


def load_report(repo: Path, slug: str, plan_version: int) -> tuple[Path, dict]:
    """Newest report for THIS plan version.

    A glob on `-v{n}*` also matches v10, v11 ... and `_version_key` then ranks
    those highest, so plan v1 would be reviewed against the report of plan v10.
    Filter on the parsed version instead.
    """
    candidates = [
        path
        for path in plans_dir(repo, slug).glob("generation-report-v*.md")
        if _version_key(path)[0] == plan_version
    ]
    path = latest(candidates)
    if path is None:
        raise CheckError(f"no generation report for plan v{plan_version} in {plans_dir(repo, slug)}")
    return path, payload(path)


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


def write_log(repo: Path, slug: str, name: str, command: list, output: str) -> Path:
    """Keep the full maven output next to the check result.

    Terminals truncate, error messages are summaries, and re-running a failed
    maven goal to see what it said costs minutes. The log is the ground truth.
    """
    path = checks_dir(repo, slug) / f"maven-{name}.log"
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

    The nearest ancestor directory that owns a pom.xml IS the module, whatever
    the plan says. This is the fallback that makes multi-module repos work even
    when the Planner recorded no module: reports live under <module>/target, and
    looking for them at the repo root finds nothing while maven exits 0.
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


def resolve_module(repo: Path, plan: dict, override: str | None,
                   target_file: Path | None = None) -> str | None:
    """--module wins; otherwise read context.notes, but only accept a REAL module.

    The notes are prose written by the Planner, so a phrase like "single module
    Maven project" used to yield `-pl Maven` and maven answered "Could not find
    the selected project in the reactor". Every candidate is now checked against
    the filesystem; anything that is not a directory with a pom.xml is ignored.
    """
    if override:
        if not is_module(repo, override):
            raise CheckError(f"--module {override}: no {override}/pom.xml under {repo}")
        return override.strip().rstrip("/")
    context = plan.get("context", {})
    explicit = context.get("module")
    if explicit and is_module(repo, str(explicit)):
        return str(explicit).strip().rstrip("/")
    for note in context.get("notes", []) or []:
        for match in re.finditer(r"module[\s:=]+([\w\-./]+)", str(note), re.I):
            candidate = match.group(1).strip().rstrip("/")
            if is_module(repo, candidate):
                return candidate
    if target_file is not None:
        return module_for_target(repo, target_file)
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


def java_files(repo: Path, simple_name: str) -> list:
    return [
        path
        for path in repo.rglob(f"{simple_name}.java")
        if "target" not in path.parts and ".test-agent" not in path.parts
    ]


def fqcn_of_file(path: Path) -> str:
    match = PACKAGE.search(path.read_text(encoding="utf-8", errors="replace"))
    return f"{match.group(1)}.{path.stem}" if match else path.stem


def target_fqcn(repo: Path, plan: dict) -> tuple:
    simple = plan["target"]["class"]
    candidates = java_files(repo, simple)
    if not candidates:
        raise CheckError(f"cannot locate source file for target class {simple}")
    production = [p for p in candidates if "test" not in str(p).lower()] or candidates
    chosen = production[0]
    return fqcn_of_file(chosen), chosen


def test_fqcns(repo: Path, plan: dict, report: dict, with_existing: bool = True) -> list:
    """Generated test classes plus (optionally) the existing tests the plan cites."""
    names = []
    for rel in report.get("test_files", []) or []:
        path = repo / rel
        names.append(fqcn_of_file(path) if path.exists() else Path(rel).stem)
    if with_existing:
        for entry in plan.get("context", {}).get("existing_tests", []) or []:
            simple = str(entry).split("#")[0].split(".")[-1].strip()
            found = java_files(repo, simple)
            if found:
                names.append(fqcn_of_file(found[0]))
    return sorted(set(n for n in names if n))


def target_scope(plan: dict) -> tuple:
    target = plan.get("target", {})
    return target.get("class"), target.get("method")


# ------------------------------------------------------------------- cli ----


def add_common_args(parser) -> None:
    parser.add_argument("slug", help="target slug, e.g. OrderService or OrderService.createOrder")
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--module", default=None, help="maven module owning the target")
    parser.add_argument("--iteration", type=int, default=1, help="review iteration, used in output name")


def finish(repo: Path, slug: str, name: str, title: str, summary: list, data: dict, code: int) -> int:
    out = checks_dir(repo, slug) / name
    write_container(out, title, summary, data)
    print(f"{title}: {data.get('status')} -> {out}")
    for item in summary:
        print(f"  {item}")
    return code


def fail(message: str) -> int:
    print(f"CHECK_UNAVAILABLE: {message}", file=sys.stderr)
    return 2