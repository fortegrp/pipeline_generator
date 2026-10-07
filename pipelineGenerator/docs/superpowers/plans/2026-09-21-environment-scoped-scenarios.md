# Environment-Scoped Scenarios Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Nest scenarios under their environment and replace the manual
pipeline's two independent dropdowns with one dropdown of valid
`"<env>: <scenario>"` pairs, so a mismatched pair can't be selected.

**Spec:** `docs/superpowers/specs/2026-09-21-environment-scoped-scenarios-design.md`

**Shape of the change:** one `RunTarget` list in the generic model, one
`resolve_test_case` bash function, one trigger input per platform. Net
code goes *down*: `InputOption`, `PipelineInput`, `_render_resolvers`,
`_render_slug_resolvers` and `_render_resolver_function` are deleted.

## Ground rules

- Work on a branch (`feat/environment-scoped-scenarios`). It's a breaking
  schema change that touches every fixture, so land it as **one commit
  with the full suite green** — no knowingly red intermediate commits.
- The selector format `f"{env}: {scenario}"` exists only in
  `run_target_selector()` (`generic_model.py`).
- Generated resolvers stay exact-match `if [ "$1" = ... ]`, never `case`.
- `run-summary.json` schema unchanged.

---

## Step 1 — Schema + validator

- [ ] **`config/schema.py`**: drop `"scenarios": []` from `base_config()`'s
  `catalog`; add

  ```python
  CATALOG_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
  ```

- [ ] **`config/validator.py`**: replace the catalog block (from
  `environments = _as_list_of_dicts(...)` through the automated-job ref
  checks) with:

  ```python
  environments = _as_list_of_dicts(catalog.get("environments", []), "catalog.environments", result)
  if not environments:
      result.warnings.append("No environments are defined in catalog.environments.")
  _warn_duplicate_keys(environments, "catalog.environments", result)

  pairs: set[tuple[object, object]] = set()
  for env in environments:
      env_key = env.get("key")
      env_path = f"catalog.environments.{'unknown' if is_placeholder(env_key) else env_key}"
      _check_key_format(env_key, env_path, result)
      if is_placeholder(env.get("identifier")):
          result.warnings.append(f"{env_path}.identifier is missing.")

      scenarios = _as_list_of_dicts(env.get("scenarios", []), f"{env_path}.scenarios", result)
      if not scenarios:
          result.warnings.append(f"{env_path} has no scenarios -- it can never be selected.")
      _warn_duplicate_keys(scenarios, f"{env_path}.scenarios", result)
      for scenario in scenarios:
          scenario_key = scenario.get("key")
          scenario_path = f"{env_path}.scenarios.{'unknown' if is_placeholder(scenario_key) else scenario_key}"
          _check_key_format(scenario_key, scenario_path, result)
          if is_placeholder(scenario.get("identifier")):
              result.warnings.append(f"{scenario_path}.identifier is missing.")
          pairs.add((env_key, scenario_key))

  if not pairs:
      result.warnings.append("No scenarios are defined under catalog.environments[].scenarios.")
      if manual_pipeline.get("enabled"):
          result.warnings.append("Manual pipeline is enabled but there are no environment/scenario pairs.")

  env_keys = {env.get("key") for env in environments}
  for job in automated_jobs:
      if not job.get("enabled", True):
          continue
      name = job.get("name", "unknown")
      if job.get("environment_ref") not in env_keys:
          result.warnings.append(f"Automated job '{name}' references an unknown environment.")
      elif (job.get("environment_ref"), job.get("scenario_ref")) not in pairs:
          result.warnings.append(
              f"Automated job '{name}' references an unknown scenario for environment "
              f"'{job.get('environment_ref')}'."
          )
  ```

  plus two small helpers next to `_as_list_of_dicts`:

  ```python
  def _warn_duplicate_keys(items: list[dict], path: str, result: ValidationResult) -> None:
      counts = Counter(item.get("key") for item in items if not is_placeholder(item.get("key")))
      for key, count in counts.items():
          if count > 1:
              result.warnings.append(
                  f"{path} has {count} entries with the duplicate key '{key}' -- "
                  "only the first is ever reachable; the others are silently unselectable."
              )


  def _check_key_format(key: object, path: str, result: ValidationResult) -> None:
      if not is_placeholder(key) and not re.fullmatch(CATALOG_KEY_PATTERN, str(key)):
          result.errors.append(
              f"{path}.key '{key}' may only contain letters, digits, '_', '.', '-' "
              "and must start with a letter or digit."
          )
  ```

  (`import re`; import `CATALOG_KEY_PATTERN` from `schema`.)

- [ ] **`tests/test_validation.py`**: move every catalog fixture to the
  nested shape. Replace the old flat duplicate-scenario test and add:
  - duplicate scenario key **within** one environment → warning
  - same scenario key in two environments → no duplicate warning
  - environment with `scenarios: []` → `"... has no scenarios"` warning
  - `scenarios` given as a dict → error mentioning
    `catalog.environments.qa.scenarios`
  - automated job with `scenario_ref` that exists only under another
    environment → `"unknown scenario for environment 'staging'"` warning
  - key `"qa: east"` (and `"../x"`) → key-format **error**; key `"qa-east.1"` → no error

## Step 2 — Generic model + context

- [ ] **`generator/generic_model.py`**: delete `InputOption` and
  `PipelineInput`; then:

  ```python
  def run_target_selector(environment_key: str, scenario_key: str) -> str:
      return f"{environment_key}: {scenario_key}"


  @dataclass
  class RunTarget:
      environment_key: str
      environment_identifier: str
      scenario_key: str
      scenario_identifier: str

      @property
      def selector(self) -> str:
          return run_target_selector(self.environment_key, self.scenario_key)


  @dataclass
  class ManualPipelineSpec:
      name: str
      timeout_minutes: int


  @dataclass
  class AutomatedJobSpec:
      name: str
      timeout_minutes: int
      test_case: str
  ```

  and in `GenericPipelinePackage` replace `environments`/`scenarios` with
  `run_targets: list[RunTarget] = field(default_factory=list)`.

- [ ] **`generator/context.py`**: build targets with one walk:

  ```python
  run_targets = [
      RunTarget(
          environment_key=env["key"],
          environment_identifier=env.get("identifier", TODO_VALUE),
          scenario_key=scenario["key"],
          scenario_identifier=scenario.get("identifier", TODO_VALUE),
      )
      for env in config["catalog"]["environments"]
      for scenario in env.get("scenarios", [])
  ]
  ```

  `ManualPipelineSpec(name=..., timeout_minutes=...)` (no `inputs`), and for jobs:

  ```python
  test_case=run_target_selector(job["environment_ref"], job["scenario_ref"]),
  ```

- [ ] **`tests/test_generic_model.py`**: nested fixture; assert
  `package.run_targets[0]` fields and `.selector == "qa: checkout_smoke"`;
  2 envs × mixed scenarios produce selectors in catalog order; missing
  identifier → `TODO_VALUE`; automated job `.test_case == "qa: checkout_smoke"`.

## Step 3 — Generated script

- [ ] **`renderers/scripts.py`**: delete `_render_resolver_function`,
  `_render_resolvers`, `_render_slug_resolvers` and the `InputOption`
  import; add:

  ```python
  def _render_test_case_resolver(package: GenericPipelinePackage) -> str:
      lines = ["resolve_test_case() {"]
      for target in package.run_targets:
          assignments = "; ".join(
              f"{name}={shell_quote(value)}"
              for name, value in (
                  ("environment_key", target.environment_key),
                  ("scenario_key", target.scenario_key),
                  ("environment_identifier", target.environment_identifier),
                  ("scenario_identifier", target.scenario_identifier),
                  ("environment_slug", safe_filename_component(target.environment_key)),
                  ("scenario_slug", safe_filename_component(target.scenario_key)),
              )
          )
          lines.append(f'  if [ "$1" = {shell_quote(target.selector)} ]; then {assignments}; return; fi')
      lines.append('  echo "Unknown test case: $1" >&2')
      lines.append("  exit 1")
      lines.append("}")
      return "\n".join(lines)
  ```

- [ ] In all three tool scripts, replace
  `{_render_resolvers(package)}\n\n{_render_slug_resolvers(package)}` with
  `{_render_test_case_resolver(package)}`.

- [ ] **`_render_arg_parsing`**: parse `--test-case` instead of
  `--environment`/`--scenario`; usage line becomes
  `Usage: $0 --test-case "<environment>: <scenario>"{timeout_usage}`; the
  tail becomes:

  ```bash
    local environment_key="" scenario_key="" environment_identifier="" scenario_identifier=""
    local environment_slug="" scenario_slug=""
    resolve_test_case "$test_case"
  ```

  Called directly, not via `$(...)`: bash's dynamic scoping assigns
  `main`'s locals, and `exit 1` on an unknown value exits the script.

- [ ] In `_render_jmeter_script`, `_render_blazemeter_script`,
  `_render_loadrunner_script`, delete the now-redundant block:

  ```bash
    local environment_slug
    local scenario_slug
    environment_slug="$(resolve_environment_slug "$environment_key")"
    scenario_slug="$(resolve_scenario_slug "$scenario_key")"
  ```

- [ ] **`tests/test_tool_scripts.py`**:
  - Fixture → nested catalog (`qa` with `checkout_smoke`).
  - Replace every `--environment qa --scenario checkout_smoke` argument
    sequence with `--test-case "qa: checkout_smoke"` (search-and-replace;
    review each hit).
  - Resolver tests source the script, call `resolve_test_case '<selector>'`,
    then `echo "$environment_identifier"` / `"$environment_slug"` etc.
    Rewrite these four: exact-match-not-glob (`*` env key must not match
    `staging: checkout_smoke`), adversarial keys (`$(touch …)`, backticks,
    quotes — must match literally, marker file never created), and the two
    hostile-key slug tests (`../../pwn` → slug without `..` or `/`). They
    bypass the validator on purpose — they test the second line of defense.
  - Add: unknown selector (`"qa: nope"`) exits non-zero with
    `Unknown test case` on stderr.
  - Add: same scenario key under two environments resolves to each
    environment's own `scenario_identifier`.
  - Update the BlazeMeter usage-message assertion to the new usage line.
  - `run-summary.json` assertions keep checking separate
    `environment`/`scenario` fields — unchanged.

## Step 4 — Renderers + README

- [ ] **`github_actions.py`** manual workflow: one input, one env var.

  ```python
  options = ", ".join(yaml_dquote(t.selector) for t in package.run_targets)
  ```
  ```yaml
      inputs:
        test_case:
          description: Select environment and scenario
          required: true
          type: choice
          options: [{options}]
  ...
          env:
            TEST_CASE: ${{{{ github.event.inputs.test_case }}}}
          run: >
            ./scripts/run-{package.tool_type}.sh
            --test-case "$TEST_CASE"{timeout_flag}
  ```

  Automated workflow: `--test-case {shell_quote(job.test_case)}{timeout_flag}`.

- [ ] **`azure_devops.py`** manual pipeline: one `testCase` parameter
  (`displayName: Environment and scenario`, `type: string`, `default:`
  first selector or `"TODO"`, `values:` all selectors); step gets
  `env: TEST_CASE: ${{{{ parameters.testCase }}}}` and
  `--test-case "$TEST_CASE"`. Automated job:
  `--test-case {shell_quote(job.test_case)}`.

- [ ] **`jenkins.py`** manual: one `choice(name: 'TEST_CASE', choices:
  [...], description: 'Select environment and scenario')`; `sh` line uses
  `--test-case "$TEST_CASE"`. Automated: `environment { TEST_CASE =
  {groovy_squote(job.test_case)} }` and the same `sh` line.

- [ ] **`readme.py`**: Azure line → "fill in the `testCase` parameter";
  Jenkins line → "choose a test case (environment and scenario)"; the
  fallback line and troubleshooting line → `--test-case` /
  `Unknown test case: ...`.

- [ ] **Renderer tests** (`test_github_actions_renderer.py`,
  `test_azure_devops_renderer.py`, `test_jenkins_renderer.py`,
  `test_readme_renderer.py`): nested fixtures; assert the single input
  lists `"qa: checkout_smoke"`, the env var mapping is `TEST_CASE`, the
  run text has `--test-case "$TEST_CASE"` and no `github.event.inputs` /
  `${{ parameters` / `${params` splice; automated files contain
  `shell_quote("qa: checkout_smoke")` (GitHub/Azure) or the
  `TEST_CASE = '...'` line (Jenkins). Adversarial tests keep their
  hostile `job.name`/pipeline name, but the env key becomes a valid key
  (hostile env keys are now a validator error, covered in Step 1 and the
  script tests). Add one test with 2 envs × 2 scenarios: the dropdown has
  exactly the 3–4 defined pairs, not the cross product.

## Step 5 — Wizard

- [ ] **`wizard/flow.py`**:
  - `_step_catalog` collects only `config["catalog"]["environments"]` via
    `_prompt_environments_section(existing, tool_type)`, which is
    `_prompt_resumable_list("environments", existing, keys, lambda: _prompt_environment_items(tool_type))`.
  - Replace `_prompt_catalog_items`/`_prompt_catalog_section` with:

    ```python
    def _prompt_catalog_items(kind: str, tool_type: str, intro: str) -> list[dict]:
        items: list[dict] = []
        identifier_label = CATALOG_IDENTIFIER_PROMPTS.get(tool_type, {}).get(kind, f"{kind} identifier")
        print(intro)
        while True:
            key = prompt_text(f"{kind} key", allow_blank=True)
            if not key:
                break
            if not re.fullmatch(CATALOG_KEY_PATTERN, key):
                print("  Use letters, digits, '_', '.', '-' only (e.g. qa, checkout_smoke).")
                continue
            identifier = prompt_text(identifier_label, default=TODO_VALUE) or TODO_VALUE
            items.append({"key": key, "identifier": identifier})
        return items


    def _prompt_environment_items(tool_type: str) -> list[dict]:
        environments = _prompt_catalog_items(
            "environment", tool_type, "Enter environments. Leave key blank to finish."
        )
        for environment in environments:
            environment["scenarios"] = _prompt_catalog_items(
                "scenario", tool_type,
                f"Enter scenarios for {environment['key']}. Leave key blank to finish.",
            )
        return environments


    def _prompt_environments_section(existing: list[dict], tool_type: str) -> list[dict]:
        return _prompt_resumable_list(
            "environments", existing, [item["key"] for item in existing],
            lambda: _prompt_environment_items(tool_type),
        )
    ```

    Environments are entered first, then each one's scenarios — no
    second near-identical loop.
  - `_prompt_automated_jobs`: after picking `environment_ref`, offer
    `prompt_choice` only over that environment's scenario keys (fall back
    to `prompt_text(... TODO)` if it has none).
  - `_print_summary`: `Scenarios:` = sum over environments.

- [ ] **Wizard tests** (`test_wizard_resumable_list.py`,
  `test_wizard_end_to_end.py`): nested-flow end-to-end (env → its
  scenarios → next env); invalid key is re-asked; resume keep-as-is keeps
  nested scenarios; automated-job scenario menu lists only the chosen
  environment's scenarios.

## Step 6 — Examples, docs, finish

- [ ] **Examples** — edit by hand:
  - 7 single-environment configs: move the `scenarios:` list under the one
    environment.
  - `github-loadrunner`, `jenkins-loadrunner`: `qa` and `staging` each get
    `checkout_smoke` + `browse_baseline` pointing at their original `.lrs`
    paths; `automated_jobs[0].scenario_ref: checkout_smoke`.
- [ ] `tests/test_generate_assets_regeneration.py`: nested catalog override.
- [ ] Docs: `README.md`, `CLAUDE.md` (`config/`, `wizard/` and
  `scripts.py` paragraphs — single `resolve_test_case`, `--test-case`,
  key format), `docs/pipeline-generator-user-guide.md`,
  `docs/current-state-and-readiness-plan.md`. Then confirm no stale refs:

  ```bash
  grep -rn 'catalog\.scenarios\|--environment\b\|--scenario\b\|resolve_environment_\|resolve_scenario_' \
    README.md CLAUDE.md docs/*.md src tests examples
  ```

  Expected: no output.
- [ ] `CHANGELOG.md` `[Unreleased]`: nested catalog, one combined
  dropdown, `--test-case` CLI, catalog key format rule, breaking with no
  migration shim, `run-summary.json` unchanged.
- [ ] Verify:

  ```bash
  pytest -q
  out="$(mktemp -d)"
  for d in examples/*/; do pipeline-generator generate --config "$d/customer.yaml" --output-dir "$out" || exit 1; done
  for f in "$out"/*/scripts/*.sh; do bash -n "$f" || exit 1; done
  ```

  Open one generated LoadRunner workflow and confirm the dropdown lists
  exactly the 4 defined pairs.
- [ ] Commit (one commit) and stop for review.
