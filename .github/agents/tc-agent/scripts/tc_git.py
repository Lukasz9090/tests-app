"""Git facts for the pipeline: the version of the code a test froze, and whether
the code has moved since.

Model B keeps no state between runs. What a characterization test froze is
recorded in the test itself (`tc-agent-characterizes: <Class>@<sha>`), and this module
answers the only questions that record needs: which commit last touched the
target, is the target dirty, how old is that commit, and does a recorded sha
still name it.

Standard library only. Every helper degrades to None/False instead of raising
when the directory is not a git checkout; callers decide what that means.
"""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

# `%h` grows with the repository (core.abbrev), so a sha written today may be
# shorter or longer than the one computed next month. Two abbreviations name the
# same commit when one is a prefix of the other; below 7 characters that stops
# being a safe assumption.
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
    """True when `path` has staged, unstaged or untracked changes."""
    out = _out(repo, "status", "--porcelain", "--", rel(repo, path))
    return bool(out)


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
    """Line numbers of `path` (as it is at HEAD) added or changed since commit `since`.

    None when the diff cannot be computed (unknown sha, not a repo).
    """
    code, out = git(repo, "diff", "-U0", "--no-color", f"{since}..HEAD", "--", rel(repo, path))
    if code != 0:
        return None
    lines = set()
    for m in HUNK.finditer(out):
        start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
        lines.update(range(start, start + count))
    return lines


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


def changed(repo: Path, path: Path) -> bool:
    """Same as is_dirty; named for the commit step, where it means 'has something to add'."""
    return is_dirty(repo, path)
