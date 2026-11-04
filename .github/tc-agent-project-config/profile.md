# tc-agent project profile — tests-app

Read by the tc-agent scripts: only the ```json fence below is parsed. Every key is
described in `.github/agents/tc-agent/docs/configuration.md`.

```json
{
  "schema_version": 1,
  "quality_gates": {
    "branch_coverage_target_scope": 0.80,
    "mutation_score_target_scope": 0.70
  },
  "freshness_days": 7,
  "max_rounds": 3,
  "protected_branches": ["master"]
}
```
