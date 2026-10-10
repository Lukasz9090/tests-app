"""Git facts for the pipeline: the commit a target was last changed in, whether it is
dirty, how old that commit is, changed lines, and the snapshot of files outside src/test.

Every helper returns None / False instead of raising when git cannot answer.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from pathlib import Path

# Two abbreviated shas name the same commit when one is a prefix of the other (>= 7 chars).
MIN_SHA = 7


def git(repo: Path, *args: str) -> tuple[int, str]:
    """Run git in `repo`, returning (exit code, stdout+stderr stripped)."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                              text=True, errors="replace")
    except FileNotFoundError:
        return 127, "git is not installed"
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _out(repo: Path, *args: str) -> str | None:
    code, out = git(repo, *args)
    return out if code == 0 else None


def rel(repo: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def is_repo(repo: Path) -> bool:
    return _out(repo, "rev-parse", "--is-inside-work-tree") == "true"


def short_sha(repo: Path, path: Path) -> str | None:
    """Abbreviated sha of the last commit that touched `path` (None: never committed)."""
    out = _out(repo, "log", "-1", "--format=%h", "--", rel(repo, path))
    return out or None


def is_dirty(repo: Path, path: Path) -> bool:
    """True when the content of `path` differs from HEAD (line endings ignored) or it is untracked.
    """
    target = rel(repo, path)
    code, _ = git(repo, "diff", "--quiet", "--ignore-cr-at-eol", "HEAD", "--", target)
    if code == 1:
        return True
    if code != 0:                       # no HEAD yet (empty repository): plain status
        return bool(_out(repo, "status", "--porcelain", "--", target))
    return bool(_out(repo, "ls-files", "--others", "--exclude-standard", "--", target))


def age_days(repo: Path, path: Path, now: float | None = None) -> float | None:
    """Days since the last commit that touched `path` (None: never committed)."""
    out = _out(repo, "log", "-1", "--format=%ct", "--", rel(repo, path))
    if not out:
        return None
    try:
        stamp = int(out.splitlines()[0])
    except ValueError:
        return None
    return round(((now if now is not None else time.time()) - stamp) / 86400, 2)


def sha_matches(recorded: str | None, current: str | None) -> bool:
    """Do two abbreviated shas name the same commit? Prefix in either direction."""
    if not recorded or not current:
        return False
    a, b = recorded.strip().lower(), current.strip().lower()
    if min(len(a), len(b)) < MIN_SHA:
        return False
    return a.startswith(b) or b.startswith(a)


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)


def changed_lines(repo: Path, path: Path, since: str) -> set | None:
    """Line numbers of `path` at HEAD added or changed since commit `since`; None when git cannot tell.
    """
    code, out = git(repo, "diff", "-U0", "--no-color", "--ignore-cr-at-eol", f"{since}..HEAD", "--",
                    rel(repo, path))
    if code != 0:
        return None
    lines = set()
    for m in HUNK.finditer(out):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        lines.update(range(start, start + count))
    return lines


def is_test_path(name: str) -> bool:
    """A path under some module's src/test/, or the pipeline's own .test-agent/."""
    name = name.replace("\\", "/")
    return "/src/test/" in "/" + name or name.startswith(".test-agent/")


def _names(repo: Path, *args: str) -> list | None:
    try:
        proc = subprocess.run(["git", *args, "-z"], cwd=str(repo), capture_output=True)
    except FileNotFoundError:
        return None
    if proc.returncode != 0:
        return None
    return [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]


def outside_tests_snapshot(repo: Path) -> dict:
    """{file: content hash} of changed or untracked files outside src/test, .test-agent and target/.
    """
    changed = _names(repo, "diff", "--name-only", "HEAD")
    if changed is None:                              # no HEAD yet: every tracked file is new
        changed = _names(repo, "ls-files") or []
    names = changed + (_names(repo, "ls-files", "--others", "--exclude-standard") or [])
    out = {}
    for name in sorted({n for n in names if not is_test_path(n) and "/target/" not in "/" + n}):
        f = Path(repo) / name
        out[name] = (hashlib.sha1(f.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                     if f.is_file() else "deleted")
    return out


def current_branch(repo: Path) -> str | None:
    """Checked-out branch, or None on a detached HEAD."""
    out = _out(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    return out or None


def head_sha(repo: Path) -> str | None:
    return _out(repo, "rev-parse", "--short", "HEAD")


def branch_exists(repo: Path, name: str) -> bool:
    code, _ = git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{name}")
    return code == 0


def staged_files(repo: Path) -> list[str]:
    out = _out(repo, "diff", "--cached", "--name-only")
    return [line for line in (out or "").splitlines() if line.strip()]
