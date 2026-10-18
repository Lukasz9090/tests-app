"""Shared helpers of the pipeline scripts: run directories, target resolution,
test discovery, the project profile, maven invocation and pom facts.

Exit codes of every check script:
  0 - check ran, gate satisfied
  1 - check ran, gate NOT satisfied
  2 - check could not run (environment / tooling)
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
# Versions that read the newest class files (JaCoCo 0.8.15: Java 26); `tooling` overrides them.
DEFAULT_VERSIONS = {"jacoco": "0.8.15", "pit": "1.25.9"}


class CheckError(Exception):
    """Environment/tooling failure. Callers map this to exit code 2."""


# --------------------------------------------------------------------- io ---


def payload(path: Path) -> dict:
    """The artifact's json payload; a missing or malformed artifact raises CheckError."""
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
    """Every tracked and untracked file of `start`'s repository (cached); None when git cannot answer.
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
    """Files of that suffix under `root`, matched by string prefix."""
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
    """Every .java file under these roots, from git's index unless `use_git` is False."""
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
    """Slug (`Class`, `Class.method` or a .java path) -> Target; TARGET_NOT_FOUND / TARGET_AMBIGUOUS
    otherwise.
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
    """Files that use any of these words (one git grep, untracked files included); None when git
    cannot.
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
    """Does this test source run `cls`, rather than only mock it?"""
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
    """Test classes that run the target and those that only mock it: ([(fqcn, path)], [fqcn])."""
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
    """Write a Markdown container: title, summary bullets and one json fence."""
    lines = [f"# {title}", ""]
    lines += [f"- {item}" for item in summary]
    lines += ["", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_xml(path: Path):
    """Parse a report XML without its DOCTYPE; an empty or broken file raises CheckError."""
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
    """Is that process still running?"""
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
    """Did maven fail because the module's own dependencies are not installed?"""
    low = (output or "").lower()
    return any(marker in low for marker in UNRESOLVED_DEPENDENCY)


def maven_also_make(repo: Path) -> str | bool:
    """When to add `-am`: profile `maven_also_make` true / false, default "auto"."""
    value = profile(repo).get("maven_also_make", "auto")
    if isinstance(value, bool):
        return value
    return "auto"


def maven_skip_main_compile(repo: Path) -> str | bool:
    """Whether a check may skip compiling src/main: true, false, "strict" or "auto" (default)."""
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
    """The first out-of-date source of the module as `(path, "newer" | "missing")`, or None."""
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
    """Run the lean plugin goals instead of the `test` phase (profile `maven_goals_only`, default
    true).
    """
    value = profile(repo).get("maven_goals_only", True)
    return bool(value)


# testResources: tests may read resources from the classpath.
LEAN_GOALS = ["resources:testResources", "compiler:testCompile", "surefire:test"]


def maven_lifecycle(repo: Path, skip_main: bool) -> list:
    """The lean goals when src/main is not compiled and goals are allowed, else the `test` phase."""
    return list(LEAN_GOALS) if (skip_main and maven_goals_only(repo)) else ["test"]


def flaky_repeat(repo: Path) -> int:
    """How many times a check runs a suite that did not fail (profile `flaky_repeat`, default 1)."""
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
    """Whether checks may re-resolve SNAPSHOT dependencies (profile, default false: `-nsu`)."""
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
    """Wait for the process, printing a heartbeat once a minute."""
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
    """Run a command with its output in a file (or `log_path`); returns (returncode, output). A timeout
    kills the process tree.
    """
    cmd = [str(part) for part in cmd]
    loud = bool(cmd) and Path(cmd[0]).stem == "mvn"
    if loud:
        cmd = [_resolve(cmd[0]), *cmd[1:]]
        print(f"$ {' '.join(cmd)}", file=sys.stderr, flush=True)
    # With log_path the output goes straight into the run's log, so it survives a kill.
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
    """The real failure out of maven's output, with a hint for known JDK / JaCoCo errors."""
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
    """A pom whose surefire <argLine> drops @{argLine} (the JaCoCo agent), or None."""
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
    """What earlier runs learned about this machine's build, per module (`.test-agent/env.json`)."""
    path = repo / ".test-agent" / "env.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_env_hint(repo: Path, key: str, module: str | None, value) -> None:
    """Remember one hint; a hint that cannot be written is ignored."""
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
    """Did the forked JVM die from two JaCoCo agents?"""
    low = output.lower()
    return any(marker in low for marker in DOUBLE_AGENT)


def pom_binds_jacoco_agent(repo: Path, module: str | None) -> Path | None:
    """The pom that binds jacoco's prepare-agent itself, or None."""
    for pom in (module_dir(repo, module) / "pom.xml", repo / "pom.xml"):
        if not pom.exists():
            continue
        text = re.sub(r"\s+", " ", pom.read_text(encoding="utf-8", errors="replace"))
        if "jacoco-maven-plugin" in text and "prepare-agent" in text:
            return pom
    return None


def module_for_target(repo: Path, target_file: Path) -> str | None:
    """The Maven module of the target: its nearest directory with a pom.xml (None = the root)."""
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


# The project's configuration, outside the shared package.
PROJECT_DIR = Path(".github") / "agents" / "tc-agent-project"
PROFILE_FILE = "profile.md"

_PROFILE_CACHE = {}


def project_file(repo: Path, name: str) -> Path | None:
    """A file of the project directory (profile.md, conventions.md, test-data.md), or None."""
    path = Path(repo) / PROJECT_DIR / name
    return path if path.is_file() else None


def profile(repo: Path) -> dict:
    """The project profile.md payload (cached); a malformed one falls back to the defaults with a
    warning.
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


DEFAULT_PROTECTED = ["master", "main"]


def protected_branches(repo: Path) -> tuple[list, str]:
    """Branches the agent never commits to (globs allowed) and their source; default master and main.
    """
    value = profile(repo).get("protected_branches") or []
    names = [str(n).strip() for n in value if str(n).strip()] if isinstance(value, list) else []
    return (names, PROFILE_FILE) if names else (list(DEFAULT_PROTECTED), "default")


PLUGIN_ARTIFACT = {"jacoco": "jacoco-maven-plugin", "pit": "pitest-maven"}


def _poms(repo: Path, module: str | None) -> list:
    """Module pom, then root pom."""
    out = []
    for pom in (module_dir(repo, module) / "pom.xml", repo / "pom.xml"):
        if pom.exists() and pom not in out:
            out.append(pom)
    return out


def stale_target(repo: Path, module: str | None, classes: Path, source) -> tuple | None:
    """Is the source under test newer than its class file? `(path, reason)` or None."""
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
    """`(flavor, five, four)` from the imports of the module's existing tests; (None, 0, 0) without
    tests.
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
    """Build, JUnit, JaCoCo and PIT facts of the module, read from the poms and tests without maven.
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
    """Tool version: CLI flag > profile `tooling` > pom > agent default."""
    if override:
        return str(override)
    tooling = profile(repo).get("tooling", {})
    if f"{tool}_version" in tooling:
        return str(tooling[f"{tool}_version"])
    return pom_plugin_version(repo, module, PLUGIN_ARTIFACT[tool]) or DEFAULT_VERSIONS[tool]


def recent_files(root: Path, pattern: str, since: float, prefer=()) -> list:
    """Files matching a glob written since `since`; the `prefer` paths are checked before a walk."""
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
    """Every `plugin:goal` maven executed, in order, from its banners."""
    seen = []
    for line in output.splitlines():
        match = GOAL_BANNER.match(line)
        if match:
            item = f"{match.group(1)}:{match.group(2)}"
            if item not in seen:
                seen.append(item)
    return seen


def trim_log(path: Path, keep: int = 60) -> None:
    """Shrink a green check's maven log to its goal banners and last `keep` lines."""
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
