#!/usr/bin/env python3
"""derive-state: what should happen to a target, computed from the real world.

Model B keeps no state between runs. Every run starts here and answers one
question from the committed code, the tests, git, coverage and mutations -
never from an artifact an earlier run left behind:

    PLAN      no tests yet, a coverage/mutation gap, or characterization tests
              whose frozen behaviour changed (stale AND red)
    DONE      gates met on the CURRENT code and nothing stale is red
    RED       a test that is not a stale characterization fails: stop, a human acts
    BLOCKED   legacy mode would freeze code that is dirty or too fresh
    ESCALATE  the target cannot be resolved, or a check could not run (exit 2)

It works in tiers, cheapest first, and stops at the first tier that decides:

    tier 0  target        slug -> file, FQCN, module
    tier 1  git + Javadoc discovery, @aiGenerated / @characterizes / @deferred,
                          current sha, dirty, age           (no build)
    tier 2  tests + coverage                                (build)
    tier 3  mutations (PIT)                                 (slow)

A stale characterization test that still PASSES only needs its freeze point
moved (`reseal`); one that FAILS goes to the planner (`recharacterize`).

The run's mode and interactive flag come from <run>/run.json (written by
`tc_orchestrate.py start`). Output: <run>/derive-state.md. This script changes
nothing in the repository.

Usage:
    python tc_derive_state.py <slug> --repo . --run <id|latest>

Exit codes: 0 = derived (whatever the verdict), 2 = could not run at all.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tc_common as c  # noqa: E402
import tc_git as g  # noqa: E402
import tc_javadoc as j  # noqa: E402
from tc_md_payload import load_payload  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
LABEL = "entry"


# ----------------------------------------------------------------- runner ---


class ScriptRunner:
    """Runs the check scripts and returns (exit code, report payload).

    Tests replace this with a fake, so the decision logic is exercised without
    maven.
    """

    def __init__(self, repo: Path, slug: str, run_id: str):
        self.repo, self.slug, self.run_id = repo, slug, run_id

    def _run(self, script: str, report: str, extra: list) -> tuple[int, dict]:
        command = [sys.executable, str(SCRIPTS / script), self.slug, "--repo", str(self.repo),
                   "--run", self.run_id, "--label", LABEL, *extra]
        proc = subprocess.run(command, cwd=str(self.repo), capture_output=True, text=True,
                              errors="replace")
        path = c.run_dir(self.repo, self.slug, self.run_id) / "checks" / report
        try:
            data, _ = load_payload(path)
        except ValueError:
            tail = (proc.stdout + proc.stderr).strip()[-600:]
            data = {"status": "UNAVAILABLE", "reason": f"{script} wrote no readable report: {tail}"}
            return 2, data
        return proc.returncode, data

    def tests(self) -> tuple[int, dict]:
        return self._run("tc_run_tests.py", f"tests-{LABEL}.md", ["--repeat", "1"])

    def coverage(self) -> tuple[int, dict]:
        return self._run("tc_coverage.py", f"coverage-{LABEL}.md", [])

    def mutation(self) -> tuple[int, dict]:
        return self._run("tc_mutation.py", f"mutation-{LABEL}.md", [])


# ----------------------------------------------------------------- tier 1 ---


def normalize_test_id(test: str) -> str:
    """surefire `com.x.FooTest#bar(int)[1]` -> `FooTest#bar`."""
    klass, _, method = test.partition("#")
    simple = klass.split(".")[-1]
    for stop in "([":
        method = method.split(stop)[0]
    return f"{simple}#{method.strip()}"


def tier1(repo: Path, target: c.Target) -> dict:
    classes = c.discover_test_classes(repo, target)
    methods, defects = [], []
    for fqcn, path in classes:
        found, file_defects = j.parse_file(path, g.rel(repo, path))
        methods.extend(found)
        defects.extend(file_defects)
        for m in found:
            defects.extend(f"{m.file}:{m.line} {m.key}: {d}" for d in m.meta.defects)

    current = g.short_sha(repo, target.file)
    dirty = g.is_dirty(repo, target.file)
    age = g.age_days(repo, target.file)

    ai = [m for m in methods if m.meta.ai]
    human = [m for m in methods if not m.meta.ai]
    stale, placeholders = [], []
    for m in ai:
        if m.is_placeholder:
            placeholders.append(m)
        if m.meta.mode == "legacy" and m.meta.characterizes_class == target.cls:
            if dirty or not g.sha_matches(m.meta.characterizes_sha, current):
                stale.append(m)
    return {
        "classes": classes,
        "methods": methods,
        "ai": ai,
        "human": human,
        "placeholders": placeholders,
        "stale": stale,
        "defects": defects,
        "git": {"current_sha": current, "dirty": dirty, "age_days": age,
                "is_repo": g.is_repo(repo)},
    }


# ----------------------------------------------------------------- derive ---


def _gate_summary(data: dict | None, key: str) -> dict | None:
    if not data:
        return None
    out = {"status": data.get("status")}
    for field in (key, "line_ratio", "gate", "scope", "reason"):
        if field in data:
            out[field] = data[field]
    return out


def derive(repo: Path, target_slug: str, run: dict, runner=None,
           freshness_days: float | None = None) -> dict:
    """The whole derivation. `run` is the run.json payload; `runner` runs the checks."""
    repo = Path(repo).resolve()
    mode = run.get("mode", "legacy")
    interactive = bool(run.get("interactive"))
    out = {
        "schema_version": 1,
        "slug": target_slug,
        "mode": mode,
        "interactive": interactive,
        "target": None,
        "git": None,
        "tests": None,
        "reseal": [],
        "recharacterize": [],
        "red": [],
        "compile_errors": [],
        "coverage": None,
        "mutation": None,
        "tiers_run": [],
        "next_action": None,
        "reasons": [],
        "detail": None,
    }

    # tier 0 ------------------------------------------------------------
    out["tiers_run"].append(0)
    try:
        target = c.resolve_target(repo, target_slug)
    except c.TargetError as exc:
        out["next_action"] = "ESCALATE"
        out["reasons"] = [exc.code]
        out["detail"] = str(exc)
        return out
    out["target"] = target.as_dict()

    # tier 1 ------------------------------------------------------------
    out["tiers_run"].append(1)
    t1 = tier1(repo, target)
    out["git"] = t1["git"]
    if not t1["git"]["is_repo"]:
        out["next_action"] = "ESCALATE"
        out["reasons"] = ["NOT_A_GIT_REPOSITORY"]
        out["detail"] = "derive-state needs git to date characterization tests"
        return out
    out["tests"] = {
        "classes": [fq for fq, _ in t1["classes"]],
        "ai": [m.as_dict() for m in t1["ai"] if not m.is_placeholder],
        "placeholders": [m.as_dict() for m in t1["placeholders"]],
        "human_count": len(t1["human"]),
        "stale": [m.key for m in t1["stale"]],
        "metadata_defects": t1["defects"],
    }

    def conclude(action: str, reasons: list, detail: str | None = None) -> dict:
        out["next_action"], out["reasons"], out["detail"] = action, reasons, detail
        if action == "PLAN" and mode == "legacy":
            fresh_limit = freshness_days if freshness_days is not None else c.freshness_days(repo)
            age = t1["git"]["age_days"]
            if t1["git"]["dirty"]:
                out["next_action"] = "BLOCKED"
                out["reasons"] = ["TARGET_DIRTY"] + reasons
                out["detail"] = (f"{target.rel_file} has uncommitted changes. Legacy mode freezes "
                                 f"committed behaviour and records its sha; commit the change first, "
                                 f"or run in spec-driven mode.")
            elif age is None:
                out["next_action"] = "BLOCKED"
                out["reasons"] = ["TARGET_NOT_COMMITTED"] + reasons
                out["detail"] = f"{target.rel_file} has never been committed; there is no sha to freeze."
            elif age < fresh_limit and not interactive:
                out["next_action"] = "BLOCKED"
                out["reasons"] = ["TARGET_TOO_FRESH"] + reasons
                out["detail"] = (f"{target.rel_file} was last committed {age:.1f} days ago "
                                 f"(limit {fresh_limit:g}). Legacy mode would freeze behaviour nobody "
                                 f"has validated yet. Re-run with --interactive, or in spec-driven mode.")
        return out

    if not t1["classes"]:
        return conclude("PLAN", ["NO_TESTS"])

    runner = runner or ScriptRunner(repo, target_slug, run["run_id"])

    # tier 2 ------------------------------------------------------------
    out["tiers_run"].append(2)
    code, tests = runner.tests()
    if code == 2 or tests.get("status") == "UNAVAILABLE":
        return conclude("ESCALATE", ["CHECK_UNAVAILABLE"], f"tests: {tests.get('reason')}")
    if tests.get("status") == "COMPILE_ERROR":
        out["compile_errors"] = tests.get("compiler_errors", [])
        return conclude("RED", ["COMPILE_ERROR"])

    stale_keys = {m.key for m in t1["stale"]}
    failing = {}
    for failure in tests.get("failures", []) or []:
        failing[normalize_test_id(failure.get("test", ""))] = failure
    for key, failure in failing.items():
        if key in stale_keys:
            out["recharacterize"].append({"method": key, "reason": "stale and failing",
                                          "message": (failure.get("message") or "")[:200]})
        else:
            out["red"].append({"test": failure.get("test"), "location": failure.get("location"),
                               "failure_phase": failure.get("failure_phase"),
                               "message": (failure.get("message") or "")[:200]})
    for m in t1["stale"]:
        if m.key in failing:
            continue
        if m.is_placeholder:
            out["recharacterize"].append({"method": m.key, "reason": "stale placeholder: re-evaluate"})
        elif not t1["git"]["dirty"] and t1["git"]["current_sha"]:
            out["reseal"].append({"method": m.key, "file": m.file,
                                  "from": m.meta.characterizes_sha, "to": t1["git"]["current_sha"]})
    if out["red"]:
        return conclude("RED", ["TESTS_FAILING"])

    code, cov = runner.coverage()
    out["coverage"] = _gate_summary(cov, "branch_ratio")
    if cov and cov.get("uncovered"):
        out["coverage"]["uncovered"] = cov["uncovered"]
    if code == 2 or cov.get("status") == "UNAVAILABLE":
        return conclude("ESCALATE", ["CHECK_UNAVAILABLE"], f"coverage: {cov.get('reason')}")
    reasons = []
    if cov.get("status") == "FAILED":
        reasons.append("COVERAGE_GAP")
    if out["recharacterize"]:
        reasons.append("STALE")
    if reasons:
        return conclude("PLAN", reasons)

    # tier 3 ------------------------------------------------------------
    out["tiers_run"].append(3)
    code, mut = runner.mutation()
    out["mutation"] = _gate_summary(mut, "score")
    if mut and mut.get("survivors"):
        out["mutation"]["survivors"] = mut["survivors"]
    if code == 2 or mut.get("status") in ("UNAVAILABLE", "SKIPPED_UNAVAILABLE"):
        return conclude("ESCALATE", ["CHECK_UNAVAILABLE"], f"mutation: {mut.get('reason')}")
    if mut.get("status") == "FAILED":
        return conclude("PLAN", ["MUTATION_GAP"])
    return conclude("DONE", ["GATES_MET"])


# ------------------------------------------------------------------ write ---


def summary_lines(state: dict) -> list:
    lines = [f"next_action: **{state['next_action']}** ({', '.join(state['reasons']) or '-'})"]
    if state.get("detail"):
        lines.append(state["detail"])
    git = state.get("git") or {}
    if git:
        lines.append(f"target sha {git.get('current_sha')}, dirty={git.get('dirty')}, "
                     f"age={git.get('age_days')} days")
    tests = state.get("tests") or {}
    if tests:
        lines.append(f"test classes: {len(tests.get('classes', []))}; AI tests: {len(tests.get('ai', []))}; "
                     f"placeholders: {len(tests.get('placeholders', []))}; human tests: {tests.get('human_count')}")
    for key in ("reseal", "recharacterize", "red"):
        if state.get(key):
            lines.append(f"{key}: {len(state[key])}")
    for gate in ("coverage", "mutation"):
        if state.get(gate):
            lines.append(f"{gate}: {state[gate].get('status')}")
    if tests.get("metadata_defects"):
        lines.append(f"metadata defects: {len(tests['metadata_defects'])}")
    return lines


def write(directory: Path, state: dict) -> Path:
    path = directory / "derive-state.md"
    c.write_container(path, f"derive-state: {state['slug']}", summary_lines(state), state)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("slug")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--run", default="latest")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    try:
        directory = c.run_dir(repo, args.slug, args.run)
        run = c.load_run(directory)
    except (c.CheckError, OSError, json.JSONDecodeError) as exc:
        print(f"CANNOT_RUN: {exc}", file=sys.stderr)
        return 2
    state = derive(repo, args.slug, run)
    path = write(directory, state)
    print(json.dumps({"next_action": state["next_action"], "reasons": state["reasons"],
                      "derive_state": g.rel(repo, path)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
