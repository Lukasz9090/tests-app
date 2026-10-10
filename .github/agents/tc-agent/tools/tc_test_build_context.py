#!/usr/bin/env python3
"""Tests for the context pack's REPO CONVENTIONS section — DEV TOOL, not runtime.

The agent's own conventions travel with the agent (references/conventions.md); the
repository can only tune style, and it does so through instruction files the
pack injects. Covered: which files are picked up and in what order, `applyTo`
filtering (match, no match, no front-matter, brace globs, `**`), extra paths
from the profile (also outside .github), the "none found" line, the precedence
header, and the per-test-class counts of AI-generated methods and placeholders.

Usage:
    python .github/agents/tc-agent/tools/tc_test_build_context.py [--verbose]
Exit codes: 0 all passed, 1 a case failed, 2 the harness could not run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from tc_testkit import TC, FixtureRepo, ai_test, expect, expect_true, human_test, run_all  # noqa: E402
    import tc_build_context as bc  # noqa: E402
    import tc_common as c  # noqa: E402
except ImportError as exc:  # pragma: no cover
    print(f"CANNOT_RUN: {exc}", file=sys.stderr)
    sys.exit(2)


def build(repo: FixtureRepo) -> str:
    directory = c.runs_root(repo.root, "OrderService") / "r1"
    directory.mkdir(parents=True, exist_ok=True)
    c.save_run(directory, {"run_id": "r1", "slug": "OrderService"})
    proc = subprocess.run([sys.executable, str(TC / "scripts" / "tc_build_context.py"), "OrderService",
                           "--repo", str(repo.root), "--run", "r1"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout + proc.stderr)
    return (directory / "context-pack.md").read_text(encoding="utf-8")


def section(pack: str) -> str:
    start = pack.index("## REPO CONVENTIONS")
    return pack[start:pack.index("## TARGET")]


def test_glob():
    rx = bc.glob_regex
    expect("** matches deep", bool(rx("src/test/**").match("src/test/java/com/acme/X.java")), True)
    expect("**/ matches zero dirs", bool(rx("**/*Test.java").match("XTest.java")), True)
    expect("* stays in one segment", bool(rx("src/*.java").match("src/a/b.java")), False)
    expect("braces", bool(rx("**/*.{java,kt}").match("a/b.kt")), True)


def test_none_found():
    with FixtureRepo() as repo:
        pack = build(repo)
        expect_true("names the test framework from the pom",
                    "TEST FRAMEWORK: JUnit" in pack or "TEST FRAMEWORK: unknown" in pack)
        expect_true("says agent defaults apply", "none found — agent defaults (conventions.md §B) apply" in pack)
        expect_true("precedence header always present", "pipeline integrity" in section(pack))


def test_target_survives_huge_repo_instructions():
    """Instructions and test data can never push the target out of its own pack."""
    with FixtureRepo() as repo:
        for k in range(40):                                      # 40 x 4k fill the 150k budget
            repo.write(f".github/instructions/r{k:02}.instructions.md", "Rule.\n" * 650)
        repo.write_test("OrderServiceTest", *(human_test(f"human{i}") for i in range(200)))
        pack = build(repo)
        expect_true("TARGET is there", "## TARGET: src/main/java/com/acme/OrderService.java" in pack)
        manifest = pack[pack.index("## MANIFEST"):].split("## NOTES")[0]
        expect_true("the manifest lists the target", "OrderService.java" in manifest)
        expect_true("an omitted file is a NOTE, not a manifest entry",
                    "OrderServiceTest.java" not in manifest and "BUDGET: omitted" in pack)


def test_test_data_files_are_included():
    with FixtureRepo() as repo:
        repo.write("docs/test-data.md",
                   "customer id: 9 digits, e.g. 123456789\ntransfer type: ELIXIR | SORBNET\n")
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "test_data_paths": ["docs/test-data.md"]}\n```\n')
        c._PROFILE_CACHE.clear()
        pack = build(repo)
        expect_true("section is there", "## TEST DATA (repo-provided example business values)" in pack)
        expect_true("file content is included", "9 digits, e.g. 123456789" in pack)
        expect_true("says how to use it", "take the SHAPE" in pack)
        c._PROFILE_CACHE.clear()


def test_data_examples_come_from_the_whole_test_tree():
    """The shape of a customerId lives in another class's test - the pack must show it."""
    with FixtureRepo() as repo:
        repo.write("src/main/java/com/acme/CreateOrderRequest.java",
                   "package com.acme;\n\npublic record CreateOrderRequest(String customerId, int amount, String id) {}\n")
        repo.write(repo.target_path, "package com.acme;\n\npublic class OrderService {\n"
                   "    public int place(CreateOrderRequest request, String productCode) { return 1; }\n}\n")
        repo.write("src/test/java/com/acme/CustomerServiceTest.java",
                   "class CustomerServiceTest {\n"
                   "    String customerId = \"123456789\";\n"
                   "    void a() { req.customerId(\"987654321\"); }\n"
                   "    void b() { assertThat(r.customerId()).isEqualTo(\"555000111\"); }\n"
                   "    void c() { x.customerId(\"111111111\"); }\n"
                   "    void e() { y.customerId(\"222222222\"); }\n"
                   "    void d() { z.customerId(\"333333333\"); }\n"
                   "    String id = \"77\"; String productCode = \"AGD-01\";\n}\n")
        repo.write("src/test/resources/customer.json", '{"customerId": "444444444"}\n')
        pack = build(repo)
        expect_true("section is there", "## DATA EXAMPLES" in pack)
        sec = pack[pack.index("## DATA EXAMPLES"):pack.index("## REPO CONVENTIONS")]
        expect_true("value from another class's test", "123456789" in sec and "CustomerServiceTest.java:2" in sec)
        expect_true("a target parameter counts too", "AGD-01" in sec)
        expect("assertion lines are left out", "555000111" in sec, False)
        expect("at most 3 examples per name", sum(v in sec for v in ("123456789", "987654321", "111111111",
                                                                      "222222222", "333333333", "444444444")), 3)
        expect("a generic name like id is not asked", "\nid\n" in sec, False)
    with FixtureRepo() as repo:
        expect("no tests -> no section", "## DATA EXAMPLES" in build(repo), False)


def test_spec_is_in_the_pack_of_a_spec_driven_run():
    with FixtureRepo() as repo:
        repo.write("docs/order-spec.md", "# Orders\n\n## R1 Amount\nAn amount must be positive.\n")
        directory = c.runs_root(repo.root, "OrderService") / "r1"
        directory.mkdir(parents=True, exist_ok=True)
        c.save_run(directory, {"run_id": "r1", "slug": "OrderService", "mode": "spec-driven",
                               "spec": "docs/order-spec.md"})
        subprocess.run([sys.executable, str(TC / "scripts" / "tc_build_context.py"), "OrderService",
                        "--repo", str(repo.root), "--run", "r1"], capture_output=True, text=True, check=True)
        pack = (directory / "context-pack.md").read_text(encoding="utf-8")
        expect_true("SPEC section with the text", "## SPEC: docs/order-spec.md" in pack and "must be positive" in pack)
        expect_true("before the target", pack.index("## SPEC:") < pack.index("## TARGET"))
    with FixtureRepo() as repo:
        expect("no spec -> no section", "## SPEC:" in build(repo), False)


def test_multi_module_repository():
    """Project directory at the repo root, target in one module, the data shape in another."""
    with FixtureRepo() as repo:
        repo.write("pom.xml", "<project><modelVersion>4.0.0</modelVersion><groupId>x</groupId>"
                              "<artifactId>root</artifactId><version>1</version><packaging>pom</packaging>"
                              "<modules><module>payments</module><module>customers</module></modules></project>\n")
        for module in ("payments", "customers"):
            repo.write(f"{module}/pom.xml", f"<project><modelVersion>4.0.0</modelVersion><groupId>x</groupId>"
                                            f"<artifactId>{module}</artifactId><version>1</version></project>\n")
        repo.write("payments/src/main/java/com/acme/pay/PaymentService.java",
                   "package com.acme.pay;\n\npublic class PaymentService {\n"
                   "    public int pay(String customerId, int amount) { return amount; }\n}\n")
        repo.write("customers/src/test/java/com/acme/cust/CustomerServiceTest.java",
                   "class CustomerServiceTest {\n    String customerId = \"123456789\";\n}\n")
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "freshness_days": 2}\n```\n')
        repo.commit("modules", days_ago=20)
        c._PROFILE_CACHE.clear()
        target = c.resolve_target(repo.root, "PaymentService")
        expect("target resolved in its module", target.module, "payments")
        expect("project profile read at the repo root", c.freshness_days(repo.root), 2.0)
        directory = c.runs_root(repo.root, "PaymentService") / "r1"
        directory.mkdir(parents=True, exist_ok=True)
        c.save_run(directory, {"run_id": "r1", "slug": "PaymentService"})
        subprocess.run([sys.executable, str(TC / "scripts" / "tc_build_context.py"), "PaymentService",
                        "--repo", str(repo.root), "--run", "r1"], capture_output=True, text=True, check=True)
        pack = (directory / "context-pack.md").read_text(encoding="utf-8")
        expect_true("shape from the other module's test",
                    "customers/src/test/java/com/acme/cust/CustomerServiceTest.java:2" in pack)
        c._PROFILE_CACHE.clear()


def test_source_blocks_carry_the_files_line_numbers():
    """A ref copied from the pack must name the same line in the file."""
    with FixtureRepo() as repo:
        repo.write("docs/test-data.md", "customer id: 9 digits\n" * 30)    # pushes TARGET down the pack
        repo.write(".github/agents/tc-agent-project/test-data.md", "x\n" * 30)
        c._PROFILE_CACHE.clear()
        pack = build(repo)
        source = (repo.root / repo.target_path).read_text(encoding="utf-8").splitlines()
        number = next(i for i, line in enumerate(source, 1) if "throw new IllegalArgumentException" in line)
        block = pack[pack.index("## TARGET"):]
        expect_true("the throw is shown with its line in the file",
                    f"{number}  {source[number - 1]}" in block)
        expect_true("and the pack says how to cite", "LINE NUMBERS:" in pack)
        expect("numbered code is never fenced as java", "```java" in pack, False)
        c._PROFILE_CACHE.clear()


def test_project_test_data_is_included_without_listing_it():
    with FixtureRepo() as repo:
        repo.write(".github/agents/tc-agent-project/test-data.md", "account number: PL + 26 digits\n")
        c._PROFILE_CACHE.clear()
        pack = build(repo)
        expect_true("project test-data.md is in TEST DATA", "PL + 26 digits" in pack)
        expect_true("labelled as the project's file", "(project test-data.md)" in pack)


def test_project_directory_resolution():
    with FixtureRepo() as repo:
        expect("no project directory", (c.project_dir(repo.root), c.profile(repo.root)), (None, {}))
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "freshness_days": 3}\n```\n')
        c._PROFILE_CACHE.clear()
        expect("current location", c.freshness_days(repo.root), 3.0)
        repo.git("add", ".github")
        repo.commit("project directory")
        repo.git("mv", ".github/agents/tc-agent-project", ".github/tc-agent")
        c._PROFILE_CACHE.clear()
        expect("after git mv to the target location", (c.project_dir(repo.root).as_posix().endswith(".github/tc-agent"),
               c.freshness_days(repo.root)), (True, 3.0))
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "freshness_days": 9}\n```\n')
        c._PROFILE_CACHE.clear()
        expect("both present: .github/tc-agent wins", c.freshness_days(repo.root), 3.0)
        repo.write(".github/agents/tc-agent/references/tc-project-profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "freshness_days": 1}\n```\n')
        c._PROFILE_CACHE.clear()
        expect("the old profile location is not read", c.freshness_days(repo.root), 3.0)
        c._PROFILE_CACHE.clear()


def test_only_files_that_use_the_target_are_packed():
    """git grep shortlists them; an unrelated test must not enter the pack."""
    with FixtureRepo() as repo:
        repo.write("src/test/java/com/acme/OrderServiceTest.java",
                   "package com.acme;\nimport org.junit.jupiter.api.Test;\n"
                   "class OrderServiceTest { @Test void a() { new OrderService(); } }\n")
        repo.write("src/test/java/com/acme/OrderBuilder.java",
                   "package com.acme;\nclass OrderBuilder { OrderService s; }\n")
        repo.write("src/test/java/com/acme/NoiseTest.java",
                   "package com.acme;\nimport org.junit.jupiter.api.Test;\n"
                   "class NoiseTest { @Test void a() {} }\n")
        c._GIT_INDEX_CACHE.clear()
        pack = build(repo)
        expect_true("the target's test is there", "OrderServiceTest.java" in pack)
        expect_true("its builder is there", "OrderBuilder.java" in pack)
        expect_true("an unrelated test is not", "NoiseTest.java" not in pack)
        c._GIT_INDEX_CACHE.clear()


def test_generated_sources_and_external_types():
    """An OpenAPI-style client generated into target/ is API the target calls."""
    with FixtureRepo() as repo:
        repo.write("target/generated-sources/openapi/com/acme/api/DictClient.java",
                   "package com.acme.api;\npublic class DictClient {\n"
                   "    public DictResponse fetch(String key) { return null; }\n}\n")
        repo.write(repo.target_path,
                   "package com.acme;\n"
                   "import com.acme.api.DictClient;\n"
                   "import com.thirdparty.sdk.PaymentGateway;\n"
                   "public class OrderService {\n"
                   "    public int create(int amount) { return amount; }\n}\n")
        pack = build(repo)
        expect_true("generated client is in the pack", "DictClient.java" in pack)
        expect_true("labelled as build output", "GENERATED SOURCE" in pack)
        expect_true("jar-only type is named", "com.thirdparty.sdk.PaymentGateway" in pack)
        expect_true("and is not a reason to defer",
                    "NOT a reason to defer" in pack)


def test_pickup_and_applyto():
    with FixtureRepo() as repo:
        repo.write(".github/copilot-instructions.md", "Use British spelling.")
        repo.write(".github/instructions/testing.instructions.md",
                   '---\napplyTo: "src/test/**"\n---\nName tests method_expected_condition.')
        repo.write(".github/instructions/frontend.instructions.md",
                   '---\napplyTo: "web/**/*.ts"\n---\nFRONTEND ONLY')
        repo.write(".github/instructions/general.instructions.md", "No front-matter: always.")
        repo.write("AGENTS.md", "Agent notes for humans.\n")
        repo.write(".github/agents/tc-agent-project/conventions.md", "Project style: BDDMockito.")
        repo.write("docs/code-conventions.instruction.md", "Outside .github.")
        repo.write(".github/agents/tc-agent-project/profile.md",
                   '# p\n\n```json\n{"schema_version": 1, "instruction_paths": ["docs/code-conventions.instruction.md"]}\n```\n')
        c._PROFILE_CACHE.clear()
        pack = build(repo)
        sec = section(pack)
        expect_true("copilot-instructions", "Use British spelling." in sec)
        expect_true("applyTo matching the planned test file", "method_expected_condition" in sec)
        expect_true("no front-matter applies", "No front-matter: always." in sec)
        expect("applyTo not matching is left out", "FRONTEND ONLY" in pack, False)
        expect_true("AGENTS.md", "Agent notes for humans." in sec)
        expect_true("project conventions.md", "Project style: BDDMockito." in sec)
        expect_true("profile instruction_paths outside .github", "Outside .github." in sec)
        order = [sec.index(x) for x in ("conventions.md (project conventions)", "copilot-instructions.md (",
                                        "general.instructions.md (",
                                        "testing.instructions.md (", "AGENTS.md (", "code-conventions")]
        expect("documented order", order, sorted(order))


def test_existing_test_counts():
    with FixtureRepo() as repo:
        sha = repo.sha()
        repo.write_test("OrderServiceTest", ai_test("a", sha), ai_test("b", sha, deferred="why"), human_test("c"))
        pack = build(repo)
        expect_true("counts in the EXISTING TEST header",
                    "3 test methods: 1 AI-generated, 1 placeholders, 1 human" in pack)


if __name__ == "__main__":
    sys.exit(run_all(globals(), "BUILD_CONTEXT_OK"))
