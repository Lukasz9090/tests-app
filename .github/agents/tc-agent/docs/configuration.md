# tc-agent — project configuration

Everything that belongs to ONE repository lives in its project directory, outside
the shared agent package:

    .github/tc-agent/                 target location
    .github/agents/tc-agent-project/  current location (moves with one `git mv`)

The first one that exists is used. Files, all optional:

| file | what it holds | read by |
|---|---|---|
| `profile.md` | one ```json fence: gates, freshness, maven, junit, `max_rounds`, `protected_branches`, extra paths | the scripts |
| `conventions.md` | this repo's test style (overrides the agent's §B defaults, never §A) | the context pack → REPO CONVENTIONS, first source |
| `test-data.md` | example business values of this system | the context pack → TEST DATA |

Without a project directory the agent runs on its built-in defaults. A `profile.md` the
schema rejects (an unknown or misspelled key included) stops `start` with `INVALID_PROFILE`.

## profile.md keys

**Max rounds** (`max_rounds`, default 3): reviews one run may have; every review closes a
round, also the first one of a new plan version. `--max-rounds` overrides it for one run.

**Protected branches** (`protected_branches`, default `["master", "main"]`): branches
`finish --commit` never commits to; globs allowed (`release/*`). On such a branch,
or a detached HEAD, it creates `tc-agent/<slug>/<run-id>` instead. An empty list
still protects `master` and `main`.

**Quality gates** are the thresholds `tc_coverage.py` and `tc_mutation.py` must reach
for the target scope — the class, or the single method when the plan names one.
Raise them deliberately; the Reviewer may never lower one to reach ACCEPT.

**Freshness** (`freshness_days`): characterization mode without `--interactive` refuses to
freeze a target whose last commit is younger than this many days — nobody has
validated that behavior yet, so a green characterization test would certify a
possible bug. derive-state reports such a run as BLOCKED. Default 7.

**Flakiness** (`flaky_repeat`, default 1): a GREEN suite is run once. Running
it again costs a whole build and proves little - a flake that passes twice is
accepted anyway. A suite that FAILED is repeated automatically, because that is
the run which separates a real failure from a flake; what fails in both is a
defect, what fails in one lands in `flaky`. Raise this only for a module whose
tests touch time, ordering or shared state.

**Repo instructions** (`instruction_paths`, optional): extra instruction files the
context pack puts into REPO CONVENTIONS, relative to the repo root and allowed
outside `.github` (e.g. `docs/code-conventions.instruction.md`). Files under
`.github/copilot-instructions.md`, `.github/instructions/*.instructions.md` and
`AGENTS.md` are picked up without being listed. Repo instructions tune style
only; they never override `conventions.md` §A.

**Test data** (`test_data_paths`, optional): files that list the example business
values of this system - a customer id is 9 digits, an account number looks like
this, these transfer types are plain strings rather than an enum. The context
pack includes them verbatim and the planner reads them before it asks anybody,
so the same answers are not repeated run after run. One markdown file is enough; a single run
can point at one with `--test-data <path>` instead, in any mode. Nothing is
guessed from file names - a file is used because somebody named it here or on
the command line. In an `interactive` run with no such file, the planner offers
to take one or to walk through a few questions.

**JUnit version** (`junit`, optional, `"4"` or `"5"`): normally nothing to set.
The agent reads the version from what the module's EXISTING tests import, and
from the poms only when the module has none. That order matters, because a pom
proves little: `spring-boot-starter-test` is JUnit 4 before Boot 2.2 and JUnit 5
after it, a repo can declare the platform while every test still runs on JUnit
4, and surefire does not fail a test of the wrong version - it silently does not
run it, which arrives as "surefire ran 0 tests". Set this key when the detection
is wrong anyway: a module mid-migration, or JUnit inherited from a parent pom
outside the repo. `derive-state.md` says which source was used
(`repo.junit_source`), and the context pack repeats it on the TEST FRAMEWORK
line.

**Maven** (`maven_timeout_seconds`, `maven_also_make`, `maven_args`, all
optional): one maven call may take 600 seconds by default; past that the check
stops with a clear error instead of hanging, and every command is echoed to
stderr so a long build shows what it is doing. The low limit is deliberate - a
check that needs more than ten minutes makes the whole pipeline unusable, and
the answer is a faster build, not a longer wait.

In a large reactor the cost is `-am`: it rebuilds every module the target
depends on, which turns a two-minute job into sixteen. So the default is
`"auto"` - the test run builds only the target's module, and adds `-am` only
when maven reports that the dependencies are missing. A small repo therefore
still works with no setup (the first run pays for one full build), and a big one
does not rebuild the world every time.

Two ways to take over that decision:

    "maven_also_make": true        # always rebuild the dependencies
    "maven_also_make": false       # never; you keep them installed yourself

For `false`, and to make `"auto"` fast from the first run, install them once:

    mvn -DskipTests install -pl <module> -am     # again after a dependency changes

`maven_args` carries the rest of what makes such a build bearable: `["-T",
"1C"]` to build in parallel, `["-o"]` offline, `["-DskipITs"]` to leave
integration tests out, `["-Dthreads=4"]` for PIT, which mutates in one thread by default.

SNAPSHOTs are never re-resolved: every call carries `-nsu`. A run measures the
code in THIS working tree, so a colleague's newer snapshot landing between two
checks would mean the coverage and the mutation numbers came from different
dependencies - and maven's daily metadata refresh is a round trip to the
repository per sibling SNAPSHOT, which is most of the "Downloading from ..."
you see on the first run of a morning. `maven_snapshot_updates: true` gives
maven its usual behavior back.

**Plugins that have nothing to do with a unit test** - an OpenAPI or Swagger
generator writing a frontend client, a node/npm build, a license or
git-describe stamper - cost minutes per check and produce nothing the test
needs. The default `maven_goals_only` already removes ALL of them, so there is
normally nothing to do here. Only a repo that had to set `maven_goals_only:
false` switches them off one by one in `maven_args`; the property is per plugin,
so read the pom and use its own skip:

    ["-Dcodegen.skip=true"]            # openapi-generator / swagger-codegen
    ["-Dskip.npm=true", "-Dskip.installnodenpm=true"]   # frontend-maven-plugin
    ["-Dmaven.gitcommitid.skip=true"]  # git-commit-id-plugin
    ["-P!generate-client"]             # a generator that lives in a profile

A plugin with no skip property of its own can only be avoided by the lean
path.

`-Dmaven.main.skip` stops the compiler, not the lifecycle: a generator bound to
`generate-sources` still runs on every check. So the checks do not ask for the
phase at all. They run the goals:

    resources:testResources  compiler:testCompile  surefire:test

The test resources are copied, the test sources the agent just wrote are
compiled, the tests run - and nothing else. No OpenAPI client for the frontend,
no node build, no stampers, and no plugin downloads for any of them. This is
what an IDE does when you hit "run test".

It applies only when `src/main` is not being compiled anyway (above), which is
the same thing as saying `target/` is in step with the code - so the production
classes and any GENERATED sources are already there and compiled. A module whose
generator writes Java is therefore fine: those classes sit in `target/classes`
like any other. They go stale only if the spec they are generated from changes,
and then the class under test is stale too, which brings the compile back.

The fallback covers the rest: if the goals fail, or run NOTHING - a surefire
configured inside a pom `<execution>` ignores a CLI invocation of its goal and
exits 0 without a single report - the check pays for the full `test` phase once
and says so in the log. A repo that must always run the phase:

    "maven_goals_only": false

The other half of the cost is compiling `src/main` before every check. During a
run the production code never changes - the agent only writes under `src/test`, and any
other change stops the run - so in a module with annotation processors or
generated sources you would pay for a full rebuild each time for nothing.

`maven_skip_main_compile` decides this, and its default `"auto"` needs no
configuration. The question it asks is about the CLASS UNDER TEST: is that
source newer than the class file it produces? That is the bytecode JaCoCo and
PIT read and those are the line numbers the report is written against, so that
is the file whose freshness changes the numbers. Newer means compile (and it
says this can take minutes); not newer means run against
`<module>/target/classes` and the whole compile disappears. Building in your IDE
counts - IntelliJ writes to the same directory.

A DIFFERENT source in the module being stale is only reported, not acted on. In
a repo that is pulled or branched daily something always is, and rebuilding 6500
files because of a file this measurement never reads is how every check came to
cost minutes. The risk taken is small and visible: a stale collaborator can make
a test behave like the last build, which surfaces as a failing test rather than
as a quietly wrong report. `"strict"` restores the module-wide question.

    "maven_skip_main_compile": "strict"  # any stale source rebuilds

A source with no class of its own name does not count as newer by itself. Such
files are normal - a package-private type named differently from its file, a
source the compiler plugin excludes - and taking them as proof of a stale build
would force a full rebuild forever. They are compared with the newest build
output instead: older means the last build already saw the file.

    "maven_skip_main_compile": true    # always reuse; only warn when stale
    "maven_skip_main_compile": false   # always compile, as maven would

**JaCoCo and PIT do not have to be in the pom.** Every check calls their goals
by full coordinates, and `prepare-agent` is injected on every run - including
when the pom binds it, because a pom execution sitting in an inactive profile
reads as "bound" while no agent ever attaches, and an empty exec file is a dead
run. If the pom's execution does fire on top of ours, the forked VM dies with
two agents; the check recognises that, re-runs once without its own goal, says
so, and REMEMBERS it in `.test-agent/env.json`, so the next round goes straight
to the working command. That file is a cache, not configuration: it is
gitignored, and the moment the pom's agent stops attaching anything the run
takes the agent back and forgets the hint. The exception that pom alone can solve: on JUnit 5, PIT needs
`pitest-junit5-plugin` as a plugin dependency - the CLI cannot add it.

**Tooling** (`jacoco_version`, `pit_version`) is normally absent. A version resolves as
CLI flag → this file → the version declared in the pom (a `${property}` resolved from
`<properties>`) → the agent default, so a value here OVERRIDES the pom; prepare-agent
and the report goal must run the same JaCoCo version. Add a `tooling` block only when
the pom declares no version, or when its version cannot read the class files of the JDK in use.
