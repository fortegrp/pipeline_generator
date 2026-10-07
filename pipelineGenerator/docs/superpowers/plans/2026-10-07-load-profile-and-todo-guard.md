# Load Profile + TODO Guard Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add test parameters (test type label, users, ramp-up, duration,
throughput) from wizard to config to pipeline inputs to tool script, and
make every generated script stop immediately with a clear message when
a value it needs is still `TODO`.

**Spec:** `docs/superpowers/specs/2026-10-07-load-profile-and-todo-guard-design.md`

## Ground rules

- Branch `feat/load-profile`; land as **one commit with the full suite
  green**.
- Load values reach scripts only as `--flag "$ENV_VAR"`, never spliced
  into command text (same rule as environment/scenario today).
- LoadRunner gets `test_type` only, never the four numeric values.
- Field list lives in one place: `LOAD_PROFILE_FIELDS` in `schema.py`.

---

## Step 1 — Schema

- [ ] **`config/schema.py`**:

  ```python
  LOAD_PROFILE_FIELDS = ("users", "ramp_up_seconds", "duration_minutes", "throughput_rps")
  LOAD_PROFILE_MINIMUMS = {"users": 1, "ramp_up_seconds": 0, "duration_minutes": 1, "throughput_rps": 0}
  LOAD_PROFILE_TOOLS = ("jmeter", "blazemeter")
  LOAD_PROFILE_LABELS = {
      "test_type": "Test type label (e.g. load, stress, soak, spike)",
      "users": "Number of users",
      "ramp_up_seconds": "Ramp-up (seconds)",
      "duration_minutes": "Duration at full load (minutes)",
      "throughput_rps": "Target throughput (requests/second, 0 = no cap)",
  }
  ```

  The labels are shared by the wizard prompts and the manual pipelines'
  input descriptions.

  and in `base_config()`:

  ```python
  "load_profile": {
      "test_type": "load",
      **{name: TODO_VALUE for name in LOAD_PROFILE_FIELDS},
  },
  ```

## Step 2 — Validator

- [ ] **`config/validator.py`**, after the connection checks:

  ```python
  load_profile = _as_dict(config.get("load_profile", {}), "load_profile", result)
  if tool_type in LOAD_PROFILE_TOOLS:
      for name in LOAD_PROFILE_FIELDS:
          value = load_profile.get(name)
          if is_placeholder(value):
              result.warnings.append(f"load_profile.{name} is missing.")
          elif not _is_int_at_least(value, LOAD_PROFILE_MINIMUMS[name]):
              result.errors.append(
                  f"load_profile.{name} must be a whole number >= {LOAD_PROFILE_MINIMUMS[name]}, got: {value!r}"
              )
      _warn_timeouts_shorter_than_test(load_profile, manual_pipeline, automated_jobs, result)
  ```

  with helpers:

  ```python
  def _is_int_at_least(value: object, minimum: int) -> bool:
      return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


  def _warn_timeouts_shorter_than_test(load_profile, manual_pipeline, automated_jobs, result) -> None:
      ramp_up, duration = load_profile.get("ramp_up_seconds"), load_profile.get("duration_minutes")
      if not (_is_int_at_least(ramp_up, 0) and _is_int_at_least(duration, 1)):
          return
      test_minutes = ramp_up / 60 + duration
      timeouts = []
      if manual_pipeline.get("enabled"):
          timeouts.append(("manual_pipeline", manual_pipeline.get("timeout_minutes")))
      timeouts += [
          (f"automated job '{job.get('name', 'unknown')}'", job.get("timeout_minutes", 240))
          for job in automated_jobs if job.get("enabled", True)
      ]
      for label, timeout in timeouts:
          if isinstance(timeout, int) and timeout <= test_minutes:
              result.warnings.append(
                  f"{label} timeout ({timeout} min) is not longer than ramp-up + duration "
                  f"({test_minutes:g} min) -- the CI job would be killed before the test finishes."
              )
  ```

- [ ] **`tests/test_validation.py`**: add to `_complete_jmeter_config()` a
  filled `load_profile` (`users: 10, ramp_up_seconds: 30,
  duration_minutes: 5, throughput_rps: 0`), then add:
  - JMeter/BlazeMeter with `users: TODO` → warning `load_profile.users is missing.`
  - LoadRunner with all four TODO → no `load_profile` warning
  - `users: 0`, `users: "ten"`, `users: True` → error
  - `throughput_rps: 0`, `ramp_up_seconds: 0` → no error
  - `timeout_minutes: 5` with ramp 60s + 5 min → timeout warning; `timeout_minutes: 10` → none
  - `test_type` missing → no warning

## Step 3 — Generic model + context

- [ ] **`generator/generic_model.py`**:

  ```python
  @dataclass
  class LoadInput:
      name: str      # config field name, e.g. "ramp_up_seconds"
      default: str   # config value as text, or "TODO" ("" allowed for test_type)

      @property
      def flag(self) -> str:
          return "--" + self.name.replace("_", "-")

      @property
      def env_var(self) -> str:
          return self.name.upper()
  ```

  and on `GenericPipelinePackage`:
  `load_inputs: list[LoadInput] = field(default_factory=list)`.

- [ ] **`generator/context.py`**:

  ```python
  load_profile = config.get("load_profile", {})
  names = ("test_type", *LOAD_PROFILE_FIELDS) if tool_type in LOAD_PROFILE_TOOLS else ("test_type",)
  load_inputs = [LoadInput(name, _load_default(load_profile, name)) for name in names]
  ```

  ```python
  def _load_default(load_profile: dict, name: str) -> str:
      value = load_profile.get(name)
      if value is None or value == "":
          return "" if name == "test_type" else TODO_VALUE
      return str(value)  # not `or`: throughput_rps / ramp_up_seconds may legitimately be 0
  ```

  Pass `load_inputs=load_inputs` to `GenericPipelinePackage`.

- [ ] **`tests/test_generic_model.py`**: JMeter config → five inputs in
  order `test_type, users, ramp_up_seconds, duration_minutes,
  throughput_rps` with string defaults; LoadRunner → only `test_type`;
  missing `users` → `"TODO"`; `throughput_rps: 0` → `"0"` (not TODO); `flag`/`env_var` for `ramp_up_seconds` are
  `--ramp-up-seconds`/`RAMP_UP_SECONDS`.

## Step 4 — Generated scripts

All in **`renderers/scripts.py`**.

- [ ] **Shared guard helpers**, emitted into every script next to `json_escape`:

  ```python
  def _render_guard_helpers() -> str:
      return """require_value() {
    if [ -z "$2" ] || [ "$2" = "TODO" ]; then
      echo "ERROR: $1 is not set (still TODO). Fill it in customer.yaml and regenerate, or pass it as a flag." >&2
      exit 1
    fi
  }

  require_number() {
    require_value "$1" "$2"
    case "$2" in
      *[!0-9]*) echo "ERROR: $1 must be a whole number, got: $2" >&2; exit 1 ;;
    esac
  }"""
  ```

- [ ] **`_render_arg_parsing(include_timeout, load_inputs)`**: for each
  `LoadInput`, add before the `while` loop
  `local {name}={shell_quote(default)}` and inside the `case`
  `      {flag}) {name}="$2"; shift 2 ;;`. Append the flags to the usage
  line as optional: ` [--users N] [--ramp-up-seconds N] ... [--test-type LABEL]`.
  After the existing timeout check, emit `require_number "load_profile.{name}" "${name}"`
  for every input except `test_type`. All three tool renderers pass
  `package.load_inputs`.

- [ ] **Value guard per tool**, inserted right after each tool's
  connection `local`s and before its first pre-run check:
  - JMeter:
    ```bash
    require_value "tool.connection.test_plan_path" "$test_plan_path"
    require_value "catalog environment identifier for $environment_key" "$environment_identifier"
    require_value "catalog scenario identifier for $scenario_key" "$scenario_identifier"
    ```
  - BlazeMeter: `base_url`, `workspace_id`, `project_id` (as
    `tool.connection.<name>`) and the scenario identifier. Place it
    **before** the `jq`/API-key checks so a TODO config is reported
    first.
  - LoadRunner: the scenario identifier.

- [ ] **JMeter**: append to the `docker run ... jmeter` line, after
  `-Jscenario=...`:

  ```bash
      -Jtest_type="$test_type" -Jusers="$users" -Jramp_up_seconds="$ramp_up_seconds" \\
      -Jduration_seconds="$((duration_minutes * 60))" \\
      -Jthroughput_rps="$throughput_rps" -Jthroughput_per_minute="$((throughput_rps * 60))"
  ```

- [ ] **BlazeMeter**: before the `POST .../start` call:

  ```bash
    # Applies the load profile to the BlazeMeter test. Field names are our
    # best understanding of API v4 -- verify against a live account. This
    # persists on the test in BlazeMeter, not just for this run.
    local throughput_json=""
    if [ "$throughput_rps" -gt 0 ]; then
      throughput_json=", \\"throughput\\": $throughput_rps"
    fi
    local overrides
    overrides="$(printf '{{"overrideExecutions": [{{"concurrency": %s, "rampUp": "%ss", "holdFor": "%sm"%s}}]}}' \\
      "$users" "$ramp_up_seconds" "$duration_minutes" "$throughput_json")"
    if ! curl -sf -o /dev/null -u "$BLAZEMETER_API_KEY_ID:$BLAZEMETER_API_KEY_SECRET" \\
      -X PATCH -H "Content-Type: application/json" -d "$overrides" \\
      "$base_url/api/v4/tests/$scenario_identifier"; then
      echo "ERROR: failed to apply load profile to BlazeMeter test $scenario_identifier" >&2
      exit 1
    fi
  ```

  Built with `printf`, not `jq`: every value is already
  `require_number`-checked, and the test suite's fake `jq` only knows
  the script's existing filters.

- [ ] **`run-summary.json`**: `_render_summary_write(tool_type, load_inputs)`
  appends `"test_type": "%s"` (through `json_escape`) for every tool,
  plus `"users": %s, "ramp_up_seconds": %s, "duration_minutes": %s,
  "throughput_rps": %s` (raw numbers, already validated) when those inputs
  exist.

- [ ] **`tests/test_tool_scripts.py`**:
  - `_base_config` gets `load_profile: {test_type: load, users: 10,
    ramp_up_seconds: 30, duration_minutes: 5, throughput_rps: 2}` so
    existing end-to-end tests keep passing the guard.
  - The existing JMeter fake-`docker` test asserts the args contain
    `-Jusers=10 -Jramp_up_seconds=30 -Jduration_seconds=300
    -Jthroughput_rps=2 -Jthroughput_per_minute=120 -Jtest_type=load`.
  - `--users 50` override → `-Jusers=50`; `--users abc` → exit 1, `must
    be a whole number`.
  - BlazeMeter: fake `curl` logs its args to a file; assert a `-X PATCH`
    call carrying `"concurrency": 10, "rampUp": "30s", "holdFor": "5m",
    "throughput": 2` happens before `/start`; with `throughput_rps: 0` the
    body has no `throughput`.
  - TODO guard, one test per tool: a `TODO` value (`users` for JMeter,
    `project_id` for BlazeMeter, scenario identifier for LoadRunner) →
    exit 1, stderr names the config path, fake tool never invoked (log
    file absent), no `run-summary.json`.
  - `run-summary.json` contains `test_type` for all tools and the four
    numbers for JMeter/BlazeMeter only.
  - LoadRunner usage line has `--test-type` and no `--users`.

## Step 5 — Pipelines

- [ ] **`renderers/quoting.py`**, next to `blazemeter_timeout_flag`:

  ```python
  def load_flags(load_inputs: list[LoadInput], separator: str = " ") -> str:
      return "".join(f'{separator}{item.flag} "${item.env_var}"' for item in load_inputs)
  ```

- [ ] **GitHub Actions** (`_render_manual_workflow` only): one input per
  `LoadInput` under `workflow_dispatch.inputs`:

  ```yaml
        {name}:
          description: {yaml_dquote(label)}
          required: false
          type: string
          default: {yaml_dquote(default)}
  ```

  one `env:` line per input
  (`{ENV_VAR}: ${{{{ github.event.inputs.{name} }}}}`), and
  `{load_flags(package.load_inputs, separator="\n          ")}` before
  `{timeout_flag}`. `description:` is `LOAD_PROFILE_LABELS[name]`.

- [ ] **Azure DevOps** (manual only): one `parameters` entry per input
  (`type: string`, `default:` quoted value), one `env:` line
  (`{ENV_VAR}: ${{{{ parameters.{name} }}}}`), same `load_flags`.

- [ ] **Jenkins** (manual only): one
  `string(name: '{ENV_VAR}', defaultValue: {groovy_squote(default)}, description: '...')`
  per input inside `parameters {}`, and `load_flags(package.load_inputs)`
  in the `sh` line (Jenkins exposes parameters as env vars).

- [ ] Automated jobs: **no change** — scripts use their baked defaults.

- [ ] **Renderer tests** (all three): JMeter manual pipeline has the five
  inputs with config defaults and the five env mappings; run text contains
  `--users "$USERS"` and no `inputs.users` / `parameters.users` /
  `params.USERS` splice; LoadRunner manual pipeline has only `test_type`;
  automated pipelines contain no `--users`; a `TODO` default renders as
  `"TODO"`. Generated YAML still parses (`yaml.safe_load`).

## Step 6 — Wizard

- [ ] **`wizard/prompts.py`**:

  ```python
  def prompt_int_or_todo(label: str, default: object, minimum: int) -> int | str:
      while True:
          value = input(f"{label} [{default}]: ").strip()
          if not value:
              return default
          if value.upper() == TODO_VALUE:
              return TODO_VALUE
          if value.isdigit() and int(value) >= minimum:
              return int(value)
          print(f"Enter a whole number >= {minimum}, or TODO if you don't know yet.")
  ```

- [ ] **`wizard/flow.py`**: new step after `_step_connection`; bump
  `TOTAL_STEPS` to 8 and renumber later `_section(...)` calls.

  ```python
  def _step_load_profile(config: dict, output_path: Path) -> None:
      _section(4, "Test parameters")
      profile = config["load_profile"]
      print("Test type is a label passed to your test script and recorded in run-summary.json -- "
            "it doesn't change how the test runs.")
      profile["test_type"] = prompt_text(LOAD_PROFILE_LABELS["test_type"],
                                         default=profile.get("test_type") or "load")
      if config["tool"]["type"] not in LOAD_PROFILE_TOOLS:
          print("Users, ramp-up, duration and throughput come from the LoadRunner scenario (.lrs) itself.")
      else:
          for name in LOAD_PROFILE_FIELDS:
              profile[name] = prompt_int_or_todo(LOAD_PROFILE_LABELS[name], profile.get(name, TODO_VALUE),
                                                 LOAD_PROFILE_MINIMUMS[name])
      save_config(output_path, config)
  ```

- [ ] **`_is_incomplete`**: also return `True` when
  `validate_config(config).warnings` is non-empty. Today a config with a
  TODO `test_plan_path` is saved as `incomplete: false`, so `generate`
  refuses it — the opposite of "unknown values still give you a
  pipeline". With this, any TODO keeps the config a draft, `generate`
  still produces the package, and the script's guard stops the run with
  the exact field to fill.

- [ ] **Wizard tests**: JMeter flow asks the four questions (blank keeps
  default, `todo` → `TODO`, `-1`/`abc` re-asked); LoadRunner flow asks
  only test type; resume shows existing values as defaults; a config
  with a TODO load value ends `incomplete: true`; a fully filled one ends
  `incomplete: false`. Update existing end-to-end response sequences for
  the new step.

## Step 7 — README, examples, docs

- [ ] **`renderers/readme.py`**:
  - "Load Profile" section listing each `load_inputs` value.
  - JMeter: "Wire your .jmx to these properties" listing
    `${__P(users,1)}`, `${__P(ramp_up_seconds,0)}`,
    `${__P(duration_seconds,60)}` (Thread Group, "Specify thread
    lifetime"), `${__P(throughput_per_minute,0)}` (Constant Throughput
    Timer), `${__P(test_type)}`.
  - LoadRunner: "Load shape comes from the .lrs scenario."
  - "Remaining TODOs": one line per `load_inputs` item whose default is `TODO`.
  - Tests in `test_readme_renderer.py` for each of the above.
- [ ] **Examples**: JMeter and BlazeMeter configs get a filled
  `load_profile` (e.g. `test_type: load, users: 20, ramp_up_seconds: 60,
  duration_minutes: 10, throughput_rps: 0`) with timeouts already longer
  than that; LoadRunner configs get `load_profile: {test_type: load}`.
- [ ] **Docs**: `README.md` (config shape, wizard steps), `CLAUDE.md`
  (`config/`, `wizard/`, `scripts.py` paragraphs: load flags, guard,
  `run-summary.json` fields), `docs/pipeline-generator-user-guide.md`,
  `docs/current-state-and-readiness-plan.md`.
- [ ] **`CHANGELOG.md`** `[Unreleased]`: load profile (fields, units, LR
  exclusion), manual-pipeline override inputs, TODO guard, wizard drafts
  now stay `incomplete: true` while any TODO remains, additive
  `run-summary.json` fields, BlazeMeter PATCH persists on the test.

## Step 8 — Verify and commit

- [ ] Run:

  ```bash
  pytest -q
  out="$(mktemp -d)"
  for d in examples/*/; do pipeline-generator generate --config "$d/customer.yaml" --output-dir "$out" || exit 1; done
  for f in "$out"/*/scripts/*.sh; do bash -n "$f" || exit 1; done
  ```

- [ ] Manual check: generate a JMeter example, run its script with a
  fake `docker` on `PATH` and confirm the `-J` properties; set
  `users: TODO`, regenerate, run, and confirm the one-line error.
- [ ] One commit; stop for review.
