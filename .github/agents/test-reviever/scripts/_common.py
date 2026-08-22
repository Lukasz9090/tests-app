"""Shared helpers for the test-reviewer check scripts.

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
from pathlib import Path

JSON_FENCE = re.compile(r"```json\s*\n(.*?)\n```", re.S)
PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
VERSION_SUFFIX = re.compile(r"-v(\d+)(?:-r(\d+))?\.md$")

DEFAULT_GATES = {
    "branch_coverage_target_scope": 0.80,
    "mutation_score_target_scope": 0.70,
}
DEFAULT_VERSIONS = {"jacoco": "0.8.12", "pit": "1.17.4"}


class CheckError(Exception):
    """Environment/tooling failure. Callers map this to exit code 2."""


# --------------------------------------------------------------------- io ---


def payload(path: Path) -> dict:
    """Extract the single ```json fence that carries an artifact's contract."""
    if not path.exists():
        raise CheckError(f"missing artifact: {path}")
    blocks = JSON_FENCE.findall(path.read_text(encoding="utf-8", errors="replace"))
    if len(blocks) != 1:
        raise CheckError(
            f"INVALID_ARTIFACT {path}: expected exactly one ```json fence, found {len(blocks)}"
        )
    try:
        return json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise CheckError(f"INVALID_ARTIFACT {path}: {exc}") from exc


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
    pattern = f"generation-report-v{plan_version}*.md"
    path = latest(plans_dir(repo, slug).glob(pattern))
    if path is None:
        raise CheckError(f"no generation report for plan v{plan_version} in {plans_dir(repo, slug)}")
    return path, payload(path)


def write_container(path: Path, title: str, summary: list, data: dict) -> None:
    """Markdown container: title + human summary + exactly one json fence (D19)."""
    lines = [f"# {title}", ""]
    lines += [f"- {item}" for item in summary]
    lines += ["", "```json", json.dumps(data, indent=2, ensure_ascii=False), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ------------------------------------------------------------------ maven ---


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


def module_args(module: str | None, also_make: bool = False) -> list:
    if not module:
        return []
    args = ["-pl", module]
    if also_make:
        args.append("-am")
    return args


def module_dir(repo: Path, module: str | None) -> Path:
    return repo / module if module else repo


def resolve_module(plan: dict, override: str | None) -> str | None:
    """--module wins; otherwise best-effort read of context.notes written by the Planner."""
    if override:
        return override
    for note in plan.get("context", {}).get("notes", []) or []:
        match = re.search(r"module[\s:=]+([\w\-./]+)", str(note), re.I)
        if match:
            candidate = match.group(1).strip().rstrip("/")
            if candidate not in ("", ".", "./"):
                return candidate
    return None


# ---------------------------------------------------------------- profile ---


def profile(repo: Path) -> dict:
    path = repo / ".test-agent" / "project-profile.md"
    if not path.exists():
        return {}
    try:
        return payload(path)
    except CheckError:
        return {}


def gate_value(repo: Path, key: str, override=None) -> float:
    if override is not None:
        return float(override)
    gates = profile(repo).get("quality_gates", {})
    return float(gates.get(key, DEFAULT_GATES[key]))


def tool_version(repo: Path, tool: str, override=None) -> str:
    if override:
        return str(override)
    tooling = profile(repo).get("tooling", {})
    return str(tooling.get(f"{tool}_version", DEFAULT_VERSIONS[tool]))


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