"""Shared helpers for the pipeline scripts.

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
import shutil
import subprocess
import sys
import tempfile
import time
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
# `tooling` in the project profile.md when the build targets an older JDK.
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


_GIT_INDEX_CACHE: dict = {}


def git_index(start: Path) -> list | None:
    """Every file git knows about under `start`'s repository, as absolute paths.

    Reading git's index beats walking the tree: one process instead of a stat per
    file, which on Windows is most of the cost of finding a class in a big repo.
    `-c` adds untracked files (a test the generator just wrote is not committed
    yet) and `--exclude-standard` keeps .gitignore honoured - so anything git
    ignores, such as generated sources under target/, is NOT here and still needs
    a walk. Returns None when git cannot answer; every caller then walks.
    """
    start = Path(start).resolve()
    for known, files in _GIT_INDEX_CACHE.items():
        try:
            start.relative_to(known)
        except ValueError:
            continue
        return files
    code, out = run(["git", "-C", str(start), "rev-parse", "--show-toplevel"], start)
    if code != 0 or not out.strip():
        return None
    top = Path(out.strip().splitlines()[0]).resolve()
    code, listing = run(["git", "-C", str(top), "ls-files", "-co", "--exclude-standard"], top)
    if code != 0:
        return None
    files = [top / line for line in listing.splitlines() if line.strip()]
    _GIT_INDEX_CACHE[top] = files
    return files


def _under(root: Path, files: list, suffix: str) -> list:
    """Files of that suffix under `root`, by string prefix.

    `Path.relative_to` on every entry of a 50k-file index, once per module, was
    minutes of pure path arithmetic in a big repo. Comparing strings is the same
    answer for a fraction of the cost.
    """
    prefix = str(Path(root).resolve()) + os.sep
    cut = len(prefix)
    out = []
    for f in files:
        text = str(f)
        if not text.endswith(suffix) or not text.startswith(prefix):
            continue
        if SKIP_DIRS.intersection(text[cut:].split(os.sep)):
            continue
        out.append(f)
    return out


def pom_dirs(repo: Path) -> list:
    """Directories that own a pom.xml, from git's index when it can answer."""
    index = git_index(repo)
    if index is not None:
        poms = (p for p in _under(repo, index, ".xml") if p.name == "pom.xml")
    else:
        poms = (p for p in repo.rglob("pom.xml") if not SKIP_DIRS.intersection(p.relative_to(repo).parts))
    return sorted({p.parent for p in poms})


def find_roots(repo: Path) -> tuple[list, list]:
    """Maven source and test roots of every module (Maven only)."""
    src, test = [], []
    for pom_dir in pom_dirs(repo):
        m, t = pom_dir / "src/main/java", pom_dir / "src/test/java"
        if m.is_dir():
            src.append(m)
        if t.is_dir():
            test.append(t)
    return src, test


def java_files(roots, use_git: bool = True) -> list:
    """Every .java file under these roots, from git's index when it can answer.

    `use_git=False` for a root git ignores (generated sources under target/):
    there the walk is the only way to see anything.
    """
    out = []
    for root in roots:
        root = Path(root)
        index = git_index(root) if use_git else None
        if index is not None:
            out.extend(_under(root, index, ".java"))
            continue
        for f in root.rglob("*.java"):
            if not SKIP_DIRS.intersection(f.relative_to(root).parts):
                out.append(f)
    return out


def resolve_target(repo: Path, slug: str) -> Target:
    """Slug (`Class`, `Class.method` or a path to a .java file) -> Target.

    Never guesses: no match is TARGET_NOT_FOUND, several are TARGET_AMBIGUOUS.
    """
    repo = Path(repo).resolve()
    if not pom_dirs(repo):
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


def mentions(text: str, *names) -> bool:
    """Does the text use any of these simple names as a whole word?"""
    pattern = "|".join(re.escape(n) for n in names if n)
    return bool(pattern) and re.search(rf"\b(?:{pattern})\b", text) is not None


def grep_files(repo: Path, word, pathspec: str = "*.java") -> list | None:
    """Files that use any of these words, found by git. None when git cannot.

    Reading every test source in a big repo to ask "does it mention this class?"
    is what made the context pack slow. `git grep` scans the same content in one
    optimised process; `--untracked` keeps files the generator just wrote. Pass a
    list to ask about many names AT ONCE - one process, not one per name.
    """
    repo = Path(repo).resolve()
    words = [word] if isinstance(word, str) else [w for w in word if w]
    if not words:
        return []
    patterns = []
    for w in words:
        patterns += ["-e", w]
    code, out = run(["git", "-C", str(repo), "grep", "-l", "-I", "--untracked",
                     "--word-regexp", *patterns, "--", pathspec], repo)
    if code not in (0, 1):                        # 1 = no match, anything else = no answer
        return None
    return [repo / line.strip() for line in out.splitlines() if line.strip()]


MOCK_ANNOTATION = re.compile(r"@(Mock|MockBean|MockitoBean)\b")


def exercises(text: str, cls: str) -> bool:
    """Does this test source actually RUN `cls`, or does it only mock it?

    A class that appears solely as `@Mock TemplateUtil util` is never executed:
    the test exercises the collaborator's caller, not the collaborator. Running
    such a class costs the full build and adds exactly zero coverage, and
    treating it as "a test of the target" hides that the target is untested.

    A spy is real code, an @InjectMocks field is the class under test, and any
    other mention (a constructor call, a static call, a type in an assertion)
    counts as use.
    """
    word = re.compile(rf"\b{re.escape(cls)}\b")
    mock_call = re.compile(rf"\bmock\s*\(\s*{re.escape(cls)}\s*\.class")
    lines = text.splitlines()
    previous = ""
    for line in lines:
        stripped = line.strip()
        if not word.search(line):
            if stripped:
                previous = stripped
            continue
        if stripped.startswith("import ") or stripped.startswith("//") or stripped.startswith("*"):
            previous = stripped
            continue
        mocked = (MOCK_ANNOTATION.search(line)
                  or mock_call.search(line)
                  or MOCK_ANNOTATION.fullmatch(previous or "")
                  or bool(previous and MOCK_ANNOTATION.search(previous)
                          and not word.search(previous)))
        if not mocked:
            return True
        previous = stripped
    return False


def discover_test_classes(repo: Path, target: Target) -> tuple[list, list]:
    """Test classes that exercise the target: human and AI tests alike.

    A file under a test root counts when its name contains the target's class
    name or its source uses that name as a whole word, AND it declares at least
    one test method (so builders and fixtures that merely mention the class are
    not handed to surefire). Returns ([(fqcn, path), ...] sorted by path, [fqcn of
    test classes that only mock the target]).
    """
    repo = Path(repo).resolve()
    _, test_roots = find_roots(repo)
    candidates = java_files(test_roots)
    hits = grep_files(repo, target.cls)
    if hits is not None:
        wanted = {str(h.resolve()) for h in hits}
        candidates = [f for f in candidates
                      if target.cls in f.stem or str(f.resolve()) in wanted]
    found, mocked_only = [], []
    for f in candidates:
        text = f.read_text(encoding="utf-8", errors="replace")
        if not TEST_ANNOTATION.search(text):
            continue
        if not (target.cls in f.stem or mentions(text, target.cls)):
            continue
        if target.cls in f.stem or exercises(text, target.cls):
            found.append((fqcn_of_file(f), f))
        else:
            mocked_only.append(fqcn_of_file(f))
    return sorted(found, key=lambda pair: str(pair[1])), sorted(mocked_only)


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


def pid_alive(pid) -> bool:
    """Is that process still running? Used to tell a slow start from a dead one."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        code, out = run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], Path("."))
        return code == 0 and str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def mvn_executable() -> str:
    return "mvn.cmd" if os.name == "nt" else "mvn"


DEFAULT_MAVEN_TIMEOUT = 600        # 10 minutes: past that, fix the build, do not wait it out


def maven_timeout(repo: Path) -> float:
    """Seconds a single maven call may take (profile `maven_timeout_seconds`)."""
    try:
        value = float(profile(repo).get("maven_timeout_seconds", DEFAULT_MAVEN_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_MAVEN_TIMEOUT
    return value if value > 0 else DEFAULT_MAVEN_TIMEOUT


# Maven says this when a module\'s dependencies are not in the local repository.
UNRESOLVED_DEPENDENCY = (
    "could not resolve dependencies",
    "the following artifacts could not be resolved",
    "non-resolvable parent pom",
    "non-resolvable import pom",
)


def needs_also_make(output: str) -> bool:
    """Did maven fail because the module\'s own dependencies are not installed?"""
    low = (output or "").lower()
    return any(marker in low for marker in UNRESOLVED_DEPENDENCY)


def maven_also_make(repo: Path) -> str | bool:
    """When `-am` (also build the module\'s dependencies) is used. Default "auto".

    `-am` is what makes a test run in a big reactor take 16 minutes instead of
    two: it rebuilds every upstream module, every time. But in a small repo, or
    on a fresh clone, nothing is installed and without it maven cannot resolve
    anything. So the default is "auto": build only the target\'s module, and if
    maven says the dependencies are missing, do it again with `-am`.

    `true` always adds it (a repo whose modules change constantly), `false` never
    does (you install the dependencies yourself and own that decision).
    """
    value = profile(repo).get("maven_also_make", "auto")
    if isinstance(value, bool):
        return value
    return "auto"


def maven_skip_main_compile(repo: Path) -> str | bool:
    """When a check may skip compiling src/main. Default "auto".

    During a run the production code never changes - characterization mode requires it
    committed, and the agent only ever writes test files - so recompiling it
    before every check is pure cost, and in a module with annotation processors
    or generated sources it is a FULL rebuild every time (6500 files, minutes).

    "auto" decides from the clock, and asks about the TARGET's own class: newer
    source means this measurement would be taken on the wrong bytecode, so
    compile (and say it may take a while); otherwise run against target/classes
    with `-Dmaven.main.skip=true`. Another module member being stale is only
    reported, because in a repo that is pulled daily something always is - and
    rebuilding 6500 files because a file nobody in this run touches moved is how
    every check ended up costing minutes.

    "strict" is the old behavior: ANY stale source under src/main rebuilds.
    `true` always skips when classes exist, `false` never skips.
    """
    value = profile(repo).get("maven_skip_main_compile", "auto")
    if isinstance(value, bool):
        return value
    return "strict" if str(value) == "strict" else "auto"


def built_classes(repo: Path, module: str | None) -> Path | None:
    """`<module>/target/classes` when it holds compiled classes, else None."""
    classes = module_dir(repo, module) / "target" / "classes"
    if not classes.is_dir():
        return None
    return classes if any(classes.rglob("*.class")) else None


def stale_classes(repo: Path, module: str | None, classes: Path) -> tuple | None:
    """The first out-of-date source as `(path, reason)`, or None. Reasons:

    `"newer"`  - the source was edited after the class it produces was written.
    `"missing"`- there is no class of that name AND the source is younger than
                 the whole build, so the build cannot have seen it.

    Each source is compared with the class it produces (com/x/A.java ->
    com/x/A.class), not with the newest class in the module: that is two stats
    per file instead of walking every .class first, and it stops at the first
    file that is out of date.

    A missing class is NOT taken as proof of a stale build. Plenty of sources
    produce no class of their own name - a file holding a package-private type
    named differently, a source the compiler plugin excludes, a template the
    build copies elsewhere - and in a 6000-file module one of them would force
    a full rebuild on every check forever. So when the class is absent the
    source is compared with the newest build output instead: older means the
    last build already saw the file and chose not to emit it.
    """
    sources = module_dir(repo, module) / "src" / "main" / "java"
    if not sources.is_dir():
        return None
    newest_build = None            # computed at most once, and only if needed
    for f in sources.rglob("*.java"):
        if f.name == "package-info.java":
            continue
        produced = classes / f.relative_to(sources).with_suffix(".class")
        try:
            source_mtime = f.stat().st_mtime
        except OSError:            # vanished mid-walk - not our problem
            continue
        try:
            if source_mtime > produced.stat().st_mtime:
                return f.relative_to(repo).as_posix(), "newer"
        except FileNotFoundError:
            if newest_build is None:
                newest_build = max(
                    (p.stat().st_mtime for p in classes.rglob("*.class")), default=0.0)
            if source_mtime > newest_build:
                return f.relative_to(repo).as_posix(), "missing"
    return None


def maven_goals_only(repo: Path) -> bool:
    """Run the plugin goals directly instead of the `test` lifecycle phase.

    DEFAULT: yes. `-Dmaven.main.skip=true` stops the COMPILER, not the
    lifecycle, so the `test` phase still runs every plugin bound before it - an
    OpenAPI generator writing a frontend client, a node build, resource
    filtering, stampers - none of which a unit test needs, all of which cost
    minutes and pull plugins from the remote repository on the way.

    The goals do what an IDE does: copy the test resources, compile the test
    sources, run the tests. The production classes and the generated sources
    they need are already in target/, because this only applies when src/main
    is not being compiled anyway (`maven_skip_main_compile`), which in turn
    means the target is in step with the code. If the goals fail or run nothing,
    the check pays for the full phase once and says so, so a repo that needs the
    lifecycle still works - it just finds out the slow way, once per round.

    `maven_goals_only: false` for a repo that must always run the phase.
    """
    value = profile(repo).get("maven_goals_only", True)
    return bool(value)


# testResources is in the list because it is what the phase would do for the
# tests and costs milliseconds: without it, a test reading application.yml from
# the classpath would fail for a reason that has nothing to do with the test.
LEAN_GOALS = ["resources:testResources", "compiler:testCompile", "surefire:test"]


def maven_lifecycle(repo: Path, skip_main: bool) -> list:
    """What the test check asks maven to do: the lean goals or the `test` phase.

    The goals cannot build the module, so they are only safe when src/main is
    already compiled (`skip_main`); otherwise the phase does the work.
    """
    return list(LEAN_GOALS) if (skip_main and maven_goals_only(repo)) else ["test"]


def flaky_repeat(repo: Path) -> int:
    """How many times a check runs the suite when nothing failed. Default 1.

    Running a GREEN suite twice buys little: a flake that happens to pass twice
    is still accepted, and the second build costs as much as the first. What
    does pay is repeating a suite that FAILED - that is the run which tells a
    real failure from a flake - and the check does that by itself. Raise this
    for a module whose tests touch time, order or shared state, where catching
    an intermittent green is worth the second build.
    """
    try:
        value = int(profile(repo).get("flaky_repeat", 1))
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def maven_args(repo: Path) -> list:
    """Extra flags for every maven call (profile `maven_args`), e.g. -o, -T1C."""
    return [str(a) for a in profile(repo).get("maven_args", []) or []]


NO_SNAPSHOT_UPDATES = ("-nsu", "--no-snapshot-updates")


def maven_snapshot_updates(repo: Path) -> bool:
    """May a check re-resolve SNAPSHOT dependencies from the remote repo?

    Default NO, for two reasons. A run measures the code in THIS working tree,
    so pulling a colleague's newer snapshot halfway through changes what is
    being measured - and it can land between two checks of the same run, so the
    coverage and the mutation numbers would come from different dependencies.
    And it is pure wall-clock: maven re-checks every snapshot's metadata once a
    day, which in a reactor full of sibling SNAPSHOTs is a round trip to
    Artifactory per module on the first run of the morning.

    Set `maven_snapshot_updates: true` to restore maven's normal behavior.
    """
    return bool(profile(repo).get("maven_snapshot_updates", False))


def mvn_base(repo: Path) -> list:
    """`mvn` plus the flags EVERY check shares, profile args included."""
    args = maven_args(repo)
    flags = ["-B"]
    if not maven_snapshot_updates(repo) and not any(a in NO_SNAPSHOT_UPDATES for a in args):
        flags.append("-nsu")
    return [mvn_executable(), *flags, *args]


def _resolve(program: str) -> str:
    """Absolute path of an executable, so Windows needs no shell to find mvn.cmd."""
    found = shutil.which(program)
    return found or program


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
    else:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:            # pragma: no cover - the OS is stuck
        pass


HEARTBEAT_SECONDS = 60


def _wait_with_heartbeat(proc: subprocess.Popen, timeout: float | None, loud: bool) -> int:
    """Wait for the process, saying it is still alive once a minute.

    Maven's own output goes to a file, so a ten-minute build would otherwise
    print nothing at all between "this can take minutes" and the result.
    """
    if not loud:
        return proc.wait(timeout=timeout)
    started = time.monotonic()
    while True:
        waited = time.monotonic() - started
        left = None if timeout is None else max(0.0, timeout - waited)
        slice_ = HEARTBEAT_SECONDS if left is None else min(HEARTBEAT_SECONDS, left)
        try:
            return proc.wait(timeout=slice_)
        except subprocess.TimeoutExpired:
            waited = time.monotonic() - started
            if timeout is not None and waited >= timeout:
                raise
            minutes, seconds = divmod(int(waited), 60)
            elapsed = f"{minutes} min" if minutes else f"{seconds} s"
            print(f"[tc-agent] still running ({elapsed})", file=sys.stderr, flush=True)


def run(cmd: list, cwd: Path, timeout: float | None = None, log_path: Path | None = None,
        append: bool = False) -> tuple:
    """Run a command, returning (returncode, combined output).

    Output goes to a FILE, not to a pipe. Maven leaves grandchildren behind (a
    surefire fork, a JVM that has not exited yet) and on Windows they inherit the
    pipe: the build prints BUILD SUCCESS, maven exits, and the read still blocks
    on a pipe nobody will close - which looked exactly like a build that never
    ends. Waiting on the PROCESS, with the output on disk, ends when maven ends.

    `timeout` is a real limit on that wait; it kills the whole process tree.
    """
    cmd = [str(part) for part in cmd]
    loud = bool(cmd) and Path(cmd[0]).stem == "mvn"
    if loud:
        cmd = [_resolve(cmd[0]), *cmd[1:]]
        print(f"$ {' '.join(cmd)}", file=sys.stderr, flush=True)
    # With log_path the output is written straight into the run's log, so it
    # survives a timeout or a killed process - which is exactly when someone
    # needs to read it. Without it a temporary file is enough.
    if log_path is not None:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handle = open(log_path, "a+" if append else "w+", encoding="utf-8", errors="replace", newline="")
        handle.write("$ " + " ".join(cmd) + "\n\n")
        handle.flush()
    else:
        handle = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    header = handle.tell()
    try:
        try:
            proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=handle,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise CheckError(f"cannot execute {cmd[0]}: {exc}") from exc
        except OSError as exc:
            if os.name != "nt":
                raise CheckError(f"cannot execute {cmd[0]}: {exc}") from exc
            try:                                  # a wrapper Windows will only run through cmd
                proc = subprocess.Popen(subprocess.list2cmdline(cmd), cwd=str(cwd), shell=True,
                                        stdout=handle, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL)
            except OSError as inner:
                raise CheckError(f"cannot execute {cmd[0]}: {inner}") from inner
        try:
            code = _wait_with_heartbeat(proc, timeout, loud=loud)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            handle.seek(header)
            partial = handle.read()
            raise CheckError(
                f"{Path(cmd[0]).name} did not finish within {timeout:g}s and was stopped. "
                f"In a big multi-module repo the build alone can take longer: raise "
                f"maven_timeout_seconds in the project profile.md, add maven_args such as "
                f'["-T", "1C"] or ["-o"], or narrow the run to one module\'s class. '
                f"Last output: {partial.strip()[-600:]}") from None
        handle.seek(header)
        return code, handle.read()
    finally:
        handle.close()


JDK_HINTS = (
    (
        "unsupported class file major version",
        "the plugin is older than the JDK that compiled these classes - pin a newer version "
        "under tooling in the project profile.md (or build with an older --release)",
    ),
    (
        "incompatible version",
        "the exec file was written by a different JaCoCo version than the report goal - pin one "
        "version under tooling in the project profile.md and delete target/jacoco.exec",
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


DOUBLE_AGENT = (
    "duplicate class definition for java.lang.$jacoco",
    "duplicate class definition for class java.lang.$jacoco",
    "forked vm terminated without properly saying goodbye",
)


def env_hints(repo: Path) -> dict:
    """What earlier runs LEARNED about this machine's build, per module.

    Not configuration: every value here is a performance hint that the run can
    disprove by itself, and `.test-agent/` is gitignored, so it never travels to
    anybody else. It exists so a repo whose pom really does bind the JaCoCo
    agent stops paying for the doomed first attempt on every single round.
    """
    path = repo / ".test-agent" / "env.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_env_hint(repo: Path, key: str, module: str | None, value) -> None:
    """Remember one such fact. Best effort: a hint that cannot be written costs
    a repeated attempt next time, never a failure."""
    hints = env_hints(repo)
    hints.setdefault(key, {})[module or ""] = value
    path = repo / ".test-agent" / "env.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(hints, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def env_hint(repo: Path, key: str, module: str | None):
    return env_hints(repo).get(key, {}).get(module or "")


def duplicate_agent(output: str) -> bool:
    """Did this build die because TWO JaCoCo agents were on the forked JVM?

    The second premain cannot define its class again, so the VM dies before a
    single test runs and surefire reports it as its own crash. Recognising it
    is what lets the check inject prepare-agent unconditionally and still work
    on a pom that binds it.
    """
    low = output.lower()
    return any(marker in low for marker in DOUBLE_AGENT)


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


# The project's own configuration lives OUTSIDE the shared agent package, so the
# package can be the same in every repository. The first existing directory wins:
# the target layout first, then where it lives while the package is in this repo.
PROJECT_DIRS = (
    Path(".github") / "tc-agent",
    Path(".github") / "agents" / "tc-agent-project",
)
PROFILE_FILE = "profile.md"

_PROFILE_CACHE = {}
_WARNED_TWO_DIRS = set()


def project_dir(repo: Path) -> Path | None:
    """The project's tc-agent directory (profile.md, conventions.md, test-data.md)."""
    found = [Path(repo) / d for d in PROJECT_DIRS if (Path(repo) / d).is_dir()]
    if len(found) > 1 and str(repo) not in _WARNED_TWO_DIRS:
        _WARNED_TWO_DIRS.add(str(repo))
        print(f"WARNING: both {PROJECT_DIRS[0].as_posix()} and {PROJECT_DIRS[1].as_posix()} exist; "
              f"using {PROJECT_DIRS[0].as_posix()}", file=sys.stderr)
    return found[0] if found else None


def project_file(repo: Path, name: str) -> Path | None:
    """A file of the project directory, or None when it (or the directory) is absent."""
    directory = project_dir(repo)
    path = directory / name if directory else None
    return path if path and path.is_file() else None


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
    path = project_file(repo, PROFILE_FILE)
    if path:
        try:
            found = payload(path)
        except CheckError as exc:
            print(f"WARNING: ignoring {path}: {exc}. Falling back to the built-in "
                  f"gates {DEFAULT_GATES} and tool versions {DEFAULT_VERSIONS}.",
                  file=sys.stderr)
            found = {}

    _PROFILE_CACHE[key] = found
    return found


def gate_value(repo: Path, key: str, override=None) -> float:
    if override is not None:
        return float(override)
    gates = profile(repo).get("quality_gates", {})
    return float(gates.get(key, DEFAULT_GATES[key]))


DEFAULT_FRESHNESS_DAYS = 7


DEFAULT_MAX_ROUNDS = 3


def max_rounds(repo: Path) -> int:
    """Generate+review rounds one run may spend (profile `max_rounds`, default 3)."""
    try:
        value = int(profile(repo).get("max_rounds", DEFAULT_MAX_ROUNDS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ROUNDS
    return value if value > 0 else DEFAULT_MAX_ROUNDS


def freshness_days(repo: Path) -> float:
    """Characterization mode refuses to freeze code younger than this (the project profile.md)."""
    value = profile(repo).get("freshness_days", DEFAULT_FRESHNESS_DAYS)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(DEFAULT_FRESHNESS_DAYS)


def instruction_paths(repo: Path) -> list:
    """Extra repo instruction files named in the profile (may live outside .github)."""
    return [str(p) for p in profile(repo).get("instruction_paths", []) or []]


def test_data_paths(repo: Path) -> list:
    """Files with example business values, named in the profile (§test_data_paths)."""
    return [str(p) for p in profile(repo).get("test_data_paths", []) or []]


DEFAULT_PROTECTED = ["master"]


def protected_branches(repo: Path) -> tuple[list, str]:
    """Branches the agent never commits to, and where that list came from.

    The profile's `protected_branches` (globs allowed: `release/*`). Absent or
    empty -> only `master`: it cannot be un-protected by accident.
    """
    value = profile(repo).get("protected_branches") or []
    names = [str(n).strip() for n in value if str(n).strip()] if isinstance(value, list) else []
    return (names, PROFILE_FILE) if names else (list(DEFAULT_PROTECTED), "default")


PLUGIN_ARTIFACT = {"jacoco": "jacoco-maven-plugin", "pit": "pitest-maven"}


def _poms(repo: Path, module: str | None) -> list:
    """Module pom then root pom (the <parent> chain inside the repo, best effort)."""
    out = []
    for pom in (module_dir(repo, module) / "pom.xml", repo / "pom.xml"):
        if pom.exists() and pom not in out:
            out.append(pom)
    return out


def stale_target(repo: Path, module: str | None, classes: Path, source) -> tuple | None:
    """Is the ONE source under test newer than the class it compiles to?

    The decisive question for "auto": coverage and mutation are read from THIS
    class's bytecode and THIS source's line numbers, so this is the file whose
    freshness changes the numbers. A stale collaborator can at worst make a test
    behave like the last build - which shows up as a failing test, not as a
    silently wrong report.
    """
    sources = (module_dir(repo, module) / "src" / "main" / "java").resolve()
    source = Path(source).resolve()
    try:
        rel = source.relative_to(sources)
    except ValueError:
        return None                       # generated, or outside this module
    produced = classes / rel.with_suffix(".class")
    try:
        if source.stat().st_mtime > produced.stat().st_mtime:
            return rel_or_name(repo, source), "newer"
    except FileNotFoundError:
        return rel_or_name(repo, source), "missing"
    return None


def rel_or_name(repo: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return Path(path).name


def describe_stale(stale: tuple | None) -> str:
    """The sentence a stale `(path, reason)` deserves. Empty for None."""
    if not stale:
        return ""
    path, reason = stale
    return (f"{path} is newer than the class it compiles to" if reason == "newer"
            else f"{path} has no compiled class and is newer than the whole build")


JUNIT5_MARKERS = ["jupiter"]
JUNIT4_MARKERS = ["org.junit.Test", "org.junit.Assert", "junit.framework", "@RunWith"]


def junit_in_tests(repo: Path, module: str | None) -> tuple:
    """`(flavor, five, four)` from the imports of the module's EXISTING tests.

    The only fully reliable signal. A pom that declares both JUnit 4 and the
    platform says nothing about which one a new test must use, and surefire does
    not fail a test it cannot run: write a @Test from the wrong version and it
    is silently NOT EXECUTED. What the neighbours import is both the house style
    and proof of what runs here. `(None, 0, 0)` when git cannot answer or the
    module has no tests yet.
    """
    # Scope the grep to the module: git's pathspec wildcard crosses directories,
    # so this is the module's whole subtree and not the other 50k files.
    pathspec = f"{module}/*.java" if module else "*.java"
    five = grep_files(repo, JUNIT5_MARKERS, pathspec)
    four = grep_files(repo, JUNIT4_MARKERS, pathspec)
    if five is None or four is None:
        return None, 0, 0
    root = str(module_dir(repo, module).resolve()) + os.sep

    def mine(files):
        return [f for f in files
                if str(f).startswith(root) and f"{os.sep}src{os.sep}test{os.sep}" in str(f)]

    five, four = mine(five), mine(four)
    if not five and not four:
        return None, 0, 0
    return ("5" if len(five) > len(four) else "4"), len(five), len(four)


BOOT_VERSION = re.compile(
    r"<artifactId>\s*spring-boot-(?:starter-parent|dependencies)\s*</artifactId>\s*"
    r"<version>\s*(\d+)\.(\d+)")


def repo_contract(repo: Path, module: str | None) -> dict:
    """What the Planner's Phase 0 needs, read WITHOUT running maven.

    Static on purpose: an agent that runs `mvn -Dincludes=org.junit.jupiter ...`
    in PowerShell gets the argument split at the dots ("No plugin found for
    prefix '.junit.jupiter'"). Reading the pom text is deterministic and free.

    The JUnit version comes from three sources, in this order: the profile key
    `junit` (you overrode it), the imports of the module's existing tests (what
    demonstrably runs here), and only then the poms.
    """
    text = " ".join(re.sub(r"\s+", " ", p.read_text(encoding="utf-8", errors="replace"))
                    for p in _poms(repo, module))
    jupiter = bool(re.search(r"<artifactId>\s*junit-jupiter[\w-]*\s*</artifactId>", text))
    junit4_dep = bool(re.search(r"<groupId>\s*junit\s*</groupId>", text))
    boot = BOOT_VERSION.search(text)
    # The starter pulls JUnit 5 only from Boot 2.2 on - before that it IS JUnit 4,
    # and with no version in sight it proves nothing either way.
    starter5 = ("spring-boot-starter-test" in text and bool(boot)
                and (int(boot.group(1)), int(boot.group(2))) >= (2, 2))
    if jupiter or starter5:
        junit, source = "5", "pom"
    elif junit4_dep:
        junit, source = "4", "pom"
    else:
        junit, source = None, None

    override = str(profile(repo).get("junit", "") or "")
    from_tests, five, four = junit_in_tests(repo, module)
    if override in ("4", "5"):
        junit, source = override, "profile"
    elif from_tests:
        junit, source = from_tests, f"existing tests ({five} JUnit 5, {four} JUnit 4)"

    jacoco = "pom" if "jacoco-maven-plugin" in text else "cli"
    pit = "pom" if "pitest-maven" in text else "cli"
    return {
        "build": "maven",
        "junit": junit,
        "junit_source": source,
        "junit_mixed": bool(five and four),
        "jacoco": jacoco,
        "jacoco_agent_bound": bool(pom_binds_jacoco_agent(repo, module)),
        "pit": pit,
        "pit_junit5_plugin": "pitest-junit5-plugin" in text,
        "note": "static read of the pom(s) and of what the module's tests import; "
                "dependencies inherited from a parent outside the repo are not seen",
    }


def pom_plugin_version(repo: Path, module: str | None, artifact_id: str) -> str | None:
    """Version declared for a plugin in the module pom or the root pom, `${property}` resolved."""
    pattern = re.compile(
        r"<artifactId>\s*%s\s*</artifactId>\s*<version>\s*([^<\s]+)\s*</version>" % re.escape(artifact_id)
    )
    texts = [re.sub(r"\s+", " ", pom.read_text(encoding="utf-8", errors="replace"))
             for pom in _poms(repo, module)]
    for text in texts:
        match = pattern.search(text)
        if not match:
            continue
        version = match.group(1)
        prop = re.fullmatch(r"\$\{([\w.-]+)\}", version)
        if not prop:
            return version
        for t in texts:                                    # module properties first, then the root's
            name = re.escape(prop.group(1))
            defined = re.search(rf"<{name}>\s*([^<\s$]+)\s*</{name}>", t)
            if defined:
                return defined.group(1)
        return None
    return None


def tool_version(repo: Path, tool: str, override=None, module: str | None = None) -> str:
    """CLI flag > the project profile.md > version declared in the pom > agent default.

    The pom wins over the default on purpose: prepare-agent and report must run
    the same JaCoCo version, otherwise the report goal rejects the exec file.
    """
    if override:
        return str(override)
    tooling = profile(repo).get("tooling", {})
    if f"{tool}_version" in tooling:
        return str(tooling[f"{tool}_version"])
    return pom_plugin_version(repo, module, PLUGIN_ARTIFACT[tool]) or DEFAULT_VERSIONS[tool]


def recent_files(root: Path, pattern: str, since: float, prefer=()) -> list:
    """Files matching a glob that were written by the run we just made.

    Never trust a fixed path for maven output: multi-module layouts, custom
    reportsDirectory and aggregator roots all move it. Search, then filter by
    modification time so stale artefacts from earlier runs cannot be mistaken
    for fresh ones.

    `prefer` holds the conventional places, checked first WITHOUT recursion.
    The fallback walk crosses the whole module - in a big one that is target/
    with its generated sources, classes and test-classes, tens of thousands of
    entries, three times per round. When maven put the file where maven usually
    puts it, that walk never happens.
    """
    for quick in prefer:
        hit = []
        for path in root.glob(quick):
            try:
                if path.stat().st_mtime >= since:
                    hit.append(path)
            except OSError:
                continue
        if hit:
            return sorted(hit)
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


GOAL_BANNER = re.compile(r"^\[INFO\] ---+\s+(\S+?):(?:[\d.]\S*):(\S+)")


def maven_goals_run(output: str) -> list:
    """Every `plugin:goal` maven executed, in order, from its own banners.

    Maven prints no per-goal timings, so this is as close as a log gets to "what
    ate the four minutes": the list says whether a generator, a node build or a
    resource filter ran at all before surefire.
    """
    seen = []
    for line in output.splitlines():
        match = GOAL_BANNER.match(line)
        if match:
            item = f"{match.group(1)}:{match.group(2)}"
            if item not in seen:
                seen.append(item)
    return seen


def trim_log(path: Path, keep: int = 60) -> None:
    """Shrink a green check's maven log to the parts worth reading later.

    Kept: every goal banner (which plugins ran, in order) and the tail with the
    reactor summary and `Total time`. A green check used to DELETE this file,
    which is exactly the one you want when the question is "why did this take
    eight minutes".
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if len(lines) <= keep:
        return
    cut = len(lines) - keep
    goals = [line for line in lines[:cut] if GOAL_BANNER.match(line)]
    head = [f"[tc-agent] green check - this log holds the goals maven ran and its last {keep} "
            f"lines ({len(lines)} while it ran)", ""]
    if goals:
        head += ["[tc-agent] goals before the tail:"] + goals + [""]
    path.write_text("\n".join(head + lines[-keep:]) + "\n", encoding="utf-8")


def fail(message: str) -> int:
    print(f"CHECK_UNAVAILABLE: {message}", file=sys.stderr)
    return 2
