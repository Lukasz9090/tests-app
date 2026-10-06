# tc-agent — project directory of tests-app

This directory holds what belongs to THIS repository; the shared agent package is
`.github/agents/tc-agent/`. Target location: `.github/tc-agent/` — move it with

    git mv .github/agents/tc-agent-project .github/tc-agent

No code change is needed: the scripts look in both places.

- `profile.md` — gates, freshness, rounds, protected branches (scripts read its ```json fence)
- `conventions.md` — optional: this repo's test style, overriding the agent's §B defaults
- `test-data.md` — optional: example business values (a customer id is 9 digits, …)

All keys: `.github/agents/tc-agent/docs/configuration.md`.
