# Environment-Scoped Scenarios Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nest `catalog.scenarios` under their owning `catalog.environments` entry, and collapse the manual pipeline's two independent environment/scenario dropdowns into one dropdown of valid pairs, so an invalid environment+scenario combination is structurally impossible to select.

**Architecture:** The catalog gains one level of nesting (`environments[].scenarios[]`). `context.py` walks that nesting once per config and produces parallel `InputOption` lists all keyed by a single combined string (`"<environment_key>: <scenario_key>"`) instead of two independently-keyed lists. Every consumer downstream — the six generated shell resolver functions, all three CI/CD renderers, and the wizard's automated-job scenario picker — changes to work off that one combined key instead of two separate ones.

**Tech Stack:** Python 3.9+, pytest, PyYAML. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-21-environment-scoped-scenarios-design.md`

## Global Constraints

- No migration shim / dual-schema support for the old flat `catalog.scenarios` — this is a breaking schema change, consistent with every other schema change made this cycle.
- `run-summary.json`'s schema is unchanged: `environment`/`scenario` stay separate fields, populated from the plain raw keys (not slugs, not the combined selector).
- The combined test-case value format is exactly `f"{environment_key}: {scenario_key}"` (colon, one space) everywhere it's produced or consumed — `build_test_case_value()` in `generic_model.py` is the single source of truth for this format; no other code should format it by hand.
- Every new/changed generated-script resolver function keeps the existing exact-match `if [ "$1" = ... ]` pattern (never a `case` statement — `case` patterns are shell globs and a hostile catalog key could otherwise glob-match a pair it wasn't meant to).
- **Expected red tests between tasks.** This change is a breaking, cross-cutting schema change — dozens of test files construct config fixtures that touch `catalog`. Task 1 alone will leave `test_tool_scripts.py`, all three renderer test files, `test_readme_renderer.py`, `test_wizard_*.py`, `test_generate_assets_regeneration.py`, `test_cli.py`, and `test_example_configs.py` failing, because `context.py` changes shape before those files' fixtures are updated. This is expected — each task's own step 4 ("run tests, verify pass") only checks the tests *that task* is responsible for. The full suite is only expected green after Task 5.

---

## Task 1: Config + generator core — schema, validator, generic model, context

**Files:**
- Modify: `src/pipeline_generator/config/schema.py`
- Modify: `src/pipeline_generator/config/validator.py`
- Modify: `src/pipeline_generator/generator/generic_model.py`
- Modify: `src/pipeline_generator/generator/context.py`
- Test: `tests/test_validation.py`
- Test: `tests/test_generic_model.py`

**Interfaces:**
- Produces: `pipeline_generator.generator.generic_model.build_test_case_value(environment_key: str, scenario_key: str) -> str` — used by Task 2 (scripts.py), Task 3 (all three renderers), and nowhere else.
- Produces: `GenericPipelinePackage.environment_keys: list[InputOption]` and `.scenario_keys: list[InputOption]` (new fields) — `.value` is the combined test-case string, `.identifier` is the plain raw key (environment or scenario respectively). Consumed by Task 2's `scripts.py`.
- Produces: `GenericPipelinePackage.environments`/`.scenarios` keep their existing types (`list[InputOption]`) but now both carry the combined test-case string as `.value` (previously each carried its own bare key). Consumed by Task 2 and Task 3.

- [ ] **Step 1: Write the failing tests for the new nested validator behavior**

Replace the full contents of `tests/test_validation.py` with:

```python
from pipeline_generator.config.schema import base_config
from pipeline_generator.config.validator import validate_config


def test_validation_warns_for_incomplete_base_config() -> None:
    result = validate_config(base_config())
    assert not result.errors
    assert result.warnings


def test_validation_warns_when_catalog_identifier_is_missing() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["connection"] = {"test_plan_path": "performance/checkout.jmx"}
    config["catalog"]["environments"] = [
        {"key": "qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
    ]

    result = validate_config(config)

    assert not result.errors
    assert any("catalog.environments.qa.identifier is missing." in warning for warning in result.warnings)


def test_validation_does_not_warn_about_optional_wlrun_path() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-loadrunner-setup"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "loadrunner_professional"
    config["tool"]["connection"] = {}
    config["catalog"]["environments"] = [
        {
            "key": "qa",
            "identifier": "QA",
            "scenarios": [
                {"key": "checkout_smoke", "identifier": "C:\\Scenarios\\checkout_smoke_qa.lrs"}
            ],
        }
    ]

    result = validate_config(config)

    assert not any("wlrun_path" in warning for warning in result.warnings)
    assert not any("controller_host" in warning for warning in result.warnings)


def test_validation_errors_for_unsupported_enum_values() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["setup"]["generation_mode"] = "not_a_real_mode"
    config["cicd"]["type"] = "not_a_real_cicd_platform"
    config["tool"]["type"] = "not_a_real_tool"

    result = validate_config(config)

    assert "Unsupported cicd.type: not_a_real_cicd_platform" in result.errors
    assert "Unsupported tool.type: not_a_real_tool" in result.errors
    assert "Unsupported setup.generation_mode: not_a_real_mode" in result.errors


def test_validation_errors_when_required_field_missing_on_complete_config() -> None:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = ""
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"

    result = validate_config(config)

    assert "setup.id is missing." in result.errors
    assert not any("setup.id is missing." in warning for warning in result.warnings)


def _complete_jmeter_config() -> dict:
    config = base_config()
    config["incomplete"] = False
    config["setup"]["id"] = "example-setup"
    config["cicd"]["type"] = "github_actions"
    config["tool"]["type"] = "jmeter"
    config["tool"]["connection"] = {"test_plan_path": "performance/checkout.jmx"}
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
    ]
    return config


def test_validation_warns_about_unrecognized_pre_run_check() -> None:
    config = _complete_jmeter_config()
    config["pre_run_checks"] = ["verify_scenario_exist"]

    result = validate_config(config)

    assert not result.errors
    assert any("verify_scenario_exist" in warning for warning in result.warnings)


def test_validation_does_not_warn_about_recognized_pre_run_check() -> None:
    config = _complete_jmeter_config()
    config["pre_run_checks"] = ["verify_scenario_exists"]

    result = validate_config(config)

    assert not any("verify_scenario_exists" in warning for warning in result.warnings)


def test_validation_warns_about_duplicate_environment_key() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "env-qa-east", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]},
        {"key": "qa", "identifier": "env-qa-west", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-2"}]},
    ]

    result = validate_config(config)

    assert not result.errors
    assert any("duplicate" in warning.lower() and "qa" in warning for warning in result.warnings)


def test_validation_warns_about_duplicate_scenario_key_within_same_environment() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"] = [
        {
            "key": "qa",
            "identifier": "env-qa",
            "scenarios": [
                {"key": "checkout_smoke", "identifier": "SC-1"},
                {"key": "checkout_smoke", "identifier": "SC-2"},
            ],
        }
    ]

    result = validate_config(config)

    assert any("duplicate" in warning.lower() and "checkout_smoke" in warning for warning in result.warnings)


def test_validation_does_not_warn_about_same_scenario_key_reused_across_environments() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]},
        {
            "key": "staging",
            "identifier": "env-staging",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-2"}],
        },
    ]

    result = validate_config(config)

    assert not any("duplicate" in warning.lower() for warning in result.warnings)


def test_validation_does_not_warn_about_unique_catalog_keys() -> None:
    config = _complete_jmeter_config()

    result = validate_config(config)

    assert not any("duplicate" in warning.lower() for warning in result.warnings)


def test_validation_warns_about_environment_with_no_scenarios() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"].append({"key": "staging", "identifier": "env-staging", "scenarios": []})

    result = validate_config(config)

    assert any("catalog.environments.staging has no scenarios" in warning for warning in result.warnings)


def test_validation_warns_when_nothing_is_enabled() -> None:
    config = _complete_jmeter_config()
    config["manual_pipeline"]["enabled"] = False
    config["automated_jobs"] = []

    result = validate_config(config)

    assert any("no CI/CD pipeline" in warning or "will generate no" in warning for warning in result.warnings)


def test_validation_does_not_warn_when_manual_pipeline_is_enabled() -> None:
    config = _complete_jmeter_config()
    config["manual_pipeline"]["enabled"] = True
    config["automated_jobs"] = []

    result = validate_config(config)

    assert not any("will generate no" in warning for warning in result.warnings)


def test_validation_errors_instead_of_crashing_on_null_section() -> None:
    config = base_config()
    config["manual_pipeline"] = None

    result = validate_config(config)

    assert any("manual_pipeline" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_wrong_type_section() -> None:
    config = base_config()
    config["tool"] = "jmeter"

    result = validate_config(config)

    assert any("tool" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_environments_as_list_of_strings() -> None:
    config = base_config()
    config["catalog"]["environments"] = ["qa", "staging"]

    result = validate_config(config)

    assert any("catalog.environments" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_scenarios_as_dict() -> None:
    config = base_config()
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "QA", "scenarios": {"key": "checkout_smoke"}}
    ]

    result = validate_config(config)

    assert any("catalog.environments.qa.scenarios" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_automated_jobs_as_dict() -> None:
    config = base_config()
    config["automated_jobs"] = {"name": "nightly"}

    result = validate_config(config)

    assert any("automated_jobs" in error for error in result.errors)


def test_validation_errors_instead_of_crashing_on_automated_job_entry_as_string() -> None:
    config = base_config()
    config["automated_jobs"] = ["nightly"]

    result = validate_config(config)

    assert any("automated_jobs" in error for error in result.errors)


def test_validation_still_works_correctly_alongside_malformed_sections() -> None:
    # A malformed section must not stop the rest of validate_config from
    # running -- other real problems (e.g. an unsupported tool.type) should
    # still be reported in the same pass, not swallowed by an early return.
    config = base_config()
    config["incomplete"] = False
    config["manual_pipeline"] = None
    config["cicd"]["type"] = "not_a_real_platform"

    result = validate_config(config)

    assert any("manual_pipeline" in error for error in result.errors)
    assert "Unsupported cicd.type: not_a_real_platform" in result.errors


def test_validation_does_not_warn_when_an_automated_job_is_enabled() -> None:
    config = _complete_jmeter_config()
    config["manual_pipeline"]["enabled"] = False
    config["automated_jobs"] = [
        {"name": "nightly", "environment_ref": "qa", "scenario_ref": "checkout_smoke", "enabled": True}
    ]

    result = validate_config(config)

    assert not any("will generate no" in warning for warning in result.warnings)


def test_validation_warns_about_automated_job_referencing_unknown_environment() -> None:
    config = _complete_jmeter_config()
    config["automated_jobs"] = [
        {"name": "nightly", "environment_ref": "prod", "scenario_ref": "checkout_smoke", "enabled": True}
    ]

    result = validate_config(config)

    assert any("nightly" in warning and "unknown environment" in warning for warning in result.warnings)


def test_validation_warns_about_automated_job_referencing_scenario_from_wrong_environment() -> None:
    config = _complete_jmeter_config()
    config["catalog"]["environments"].append(
        {
            "key": "staging",
            "identifier": "env-staging",
            "scenarios": [{"key": "browse_baseline", "identifier": "SC-9"}],
        }
    )
    config["automated_jobs"] = [
        {"name": "nightly", "environment_ref": "staging", "scenario_ref": "checkout_smoke", "enabled": True}
    ]

    result = validate_config(config)

    assert any(
        "nightly" in warning and "unknown scenario" in warning and "staging" in warning
        for warning in result.warnings
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_validation.py -v`
Expected: FAIL — `catalog.get("scenarios", [])` still exists in `validator.py` so several assertions about nested paths (`catalog.environments.qa.identifier`, `catalog.environments.staging has no scenarios`, `unknown scenario ... staging`) won't be produced yet; `test_validation_errors_instead_of_crashing_on_scenarios_as_dict` will fail because there's no `catalog.environments.qa.scenarios` error path yet.

- [ ] **Step 3: Update `schema.py`'s `base_config()`**

In `src/pipeline_generator/config/schema.py`, change:

```python
        "catalog": {
            "environments": [],
        },
```

(This section currently reads `"environments": [], "scenarios": [],` — drop the `"scenarios": []` key entirely. Nothing else in this file changes.)

- [ ] **Step 4: Rewrite the catalog section of `validator.py`**

In `src/pipeline_generator/config/validator.py`, replace this block:

```python
    environments = _as_list_of_dicts(catalog.get("environments", []), "catalog.environments", result)
    scenarios = _as_list_of_dicts(catalog.get("scenarios", []), "catalog.scenarios", result)
    if not environments:
        result.warnings.append("No environments are defined in catalog.environments.")
    if not scenarios:
        result.warnings.append("No scenarios are defined in catalog.scenarios.")

    env_keys = {item.get("key") for item in environments}
    scenario_keys = {item.get("key") for item in scenarios}

    env_key_counts = Counter(item.get("key") for item in environments if not is_placeholder(item.get("key")))
    for key, count in env_key_counts.items():
        if count > 1:
            result.warnings.append(
                f"catalog.environments has {count} entries with the duplicate key '{key}' -- "
                "only the first is ever reachable; the others are silently unselectable."
            )

    scenario_key_counts = Counter(item.get("key") for item in scenarios if not is_placeholder(item.get("key")))
    for key, count in scenario_key_counts.items():
        if count > 1:
            result.warnings.append(
                f"catalog.scenarios has {count} entries with the duplicate key '{key}' -- "
                "only the first is ever reachable; the others are silently unselectable."
            )

    for item in environments:
        key = item.get("key")
        display_key = "unknown" if is_placeholder(key) else key
        if is_placeholder(item.get("identifier")):
            result.warnings.append(f"catalog.environments.{display_key}.identifier is missing.")

    for item in scenarios:
        key = item.get("key")
        display_key = "unknown" if is_placeholder(key) else key
        if is_placeholder(item.get("identifier")):
            result.warnings.append(f"catalog.scenarios.{display_key}.identifier is missing.")

    if manual_pipeline.get("enabled"):
        if not scenarios or not environments:
            result.warnings.append("Manual pipeline is enabled but environments or scenarios are missing.")

    for job in automated_jobs:
        if not job.get("enabled", True):
            continue
        if job.get("environment_ref") not in env_keys:
            result.warnings.append(
                f"Automated job '{job.get('name', 'unknown')}' references an unknown environment."
            )
        if job.get("scenario_ref") not in scenario_keys:
            result.warnings.append(
                f"Automated job '{job.get('name', 'unknown')}' references an unknown scenario."
            )
```

with:

```python
    environments = _as_list_of_dicts(catalog.get("environments", []), "catalog.environments", result)
    if not environments:
        result.warnings.append("No environments are defined in catalog.environments.")

    env_key_counts = Counter(item.get("key") for item in environments if not is_placeholder(item.get("key")))
    for key, count in env_key_counts.items():
        if count > 1:
            result.warnings.append(
                f"catalog.environments has {count} entries with the duplicate key '{key}' -- "
                "only the first is ever reachable; the others are silently unselectable."
            )

    env_keys = {item.get("key") for item in environments}
    valid_pairs: set[tuple[object, object]] = set()
    total_scenario_count = 0

    for env_item in environments:
        env_key = env_item.get("key")
        display_env_key = "unknown" if is_placeholder(env_key) else env_key
        if is_placeholder(env_item.get("identifier")):
            result.warnings.append(f"catalog.environments.{display_env_key}.identifier is missing.")

        scenarios = _as_list_of_dicts(
            env_item.get("scenarios", []), f"catalog.environments.{display_env_key}.scenarios", result
        )
        if not scenarios:
            result.warnings.append(
                f"catalog.environments.{display_env_key} has no scenarios -- it can never be "
                "selected in the manual pipeline."
            )
        total_scenario_count += len(scenarios)

        scenario_key_counts = Counter(
            item.get("key") for item in scenarios if not is_placeholder(item.get("key"))
        )
        for key, count in scenario_key_counts.items():
            if count > 1:
                result.warnings.append(
                    f"catalog.environments.{display_env_key}.scenarios has {count} entries with the "
                    f"duplicate key '{key}' -- only the first is ever reachable; the others are "
                    "silently unselectable."
                )

        for scenario_item in scenarios:
            scenario_key = scenario_item.get("key")
            display_scenario_key = "unknown" if is_placeholder(scenario_key) else scenario_key
            if is_placeholder(scenario_item.get("identifier")):
                result.warnings.append(
                    f"catalog.environments.{display_env_key}.scenarios.{display_scenario_key}.identifier "
                    "is missing."
                )
            valid_pairs.add((env_key, scenario_key))

    if not total_scenario_count:
        result.warnings.append("No scenarios are defined in catalog.environments[].scenarios.")

    if manual_pipeline.get("enabled"):
        if not valid_pairs:
            result.warnings.append(
                "Manual pipeline is enabled but there are no valid environment/scenario pairs."
            )

    for job in automated_jobs:
        if not job.get("enabled", True):
            continue
        job_environment_ref = job.get("environment_ref")
        job_scenario_ref = job.get("scenario_ref")
        if job_environment_ref not in env_keys:
            result.warnings.append(
                f"Automated job '{job.get('name', 'unknown')}' references an unknown environment."
            )
        elif (job_environment_ref, job_scenario_ref) not in valid_pairs:
            result.warnings.append(
                f"Automated job '{job.get('name', 'unknown')}' references an unknown scenario "
                f"for environment '{job_environment_ref}'."
            )
```

- [ ] **Step 5: Run the validation tests again to verify they pass**

Run: `pytest tests/test_validation.py -v`
Expected: PASS (all tests in this file)

- [ ] **Step 6: Write the failing tests for the new generic-model shape**

Replace the full contents of `tests/test_generic_model.py` with:

```python
from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.generator.generic_model import build_test_case_value


def _config() -> dict:
    return {
        "setup": {"id": "generic-model-test", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {}},
        "catalog": {
            "environments": [
                {
                    "key": "qa",
                    "identifier": "env-qa",
                    "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
                }
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 60},
        "automated_jobs": [
            {
                "name": "nightly",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 45,
            }
        ],
    }


def test_build_test_case_value_combines_environment_and_scenario_keys() -> None:
    assert build_test_case_value("qa", "checkout_smoke") == "qa: checkout_smoke"


def test_build_generic_package_carries_identifiers_and_tool_type() -> None:
    package = build_generic_package(_config())

    assert package.tool_type == "jmeter"
    assert len(package.environments) == 1
    assert package.environments[0].value == "qa: checkout_smoke"
    assert package.environments[0].identifier == "env-qa"
    assert package.scenarios[0].value == "qa: checkout_smoke"
    assert package.scenarios[0].identifier == "SC-1"
    assert package.environment_keys[0].value == "qa: checkout_smoke"
    assert package.environment_keys[0].identifier == "qa"
    assert package.scenario_keys[0].value == "qa: checkout_smoke"
    assert package.scenario_keys[0].identifier == "checkout_smoke"

    job = package.automated_jobs[0]
    assert job.environment_ref == "qa"
    assert job.scenario_ref == "checkout_smoke"


def test_build_generic_package_defaults_missing_identifier_to_todo_placeholder() -> None:
    config = _config()
    del config["catalog"]["environments"][0]["identifier"]

    package = build_generic_package(config)

    assert package.environments[0].identifier == TODO_VALUE


def test_build_generic_package_builds_one_pair_per_environment_scenario_combination() -> None:
    config = _config()
    config["catalog"]["environments"] = [
        {
            "key": "qa",
            "identifier": "env-qa",
            "scenarios": [
                {"key": "checkout_smoke", "identifier": "SC-1"},
                {"key": "browse_baseline", "identifier": "SC-2"},
            ],
        },
        {
            "key": "staging",
            "identifier": "env-staging",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-3"}],
        },
    ]

    package = build_generic_package(config)

    values = [item.value for item in package.environments]
    assert values == ["qa: checkout_smoke", "qa: browse_baseline", "staging: checkout_smoke"]
```

- [ ] **Step 7: Run the tests to verify they fail**

Run: `pytest tests/test_generic_model.py -v`
Expected: FAIL — `build_test_case_value` doesn't exist yet; `build_generic_package` still reads `config["catalog"]["scenarios"]` (a flat top-level key that no longer exists in this fixture), so it will raise `KeyError: 'scenarios'`.

- [ ] **Step 8: Add `build_test_case_value` and the two new fields to `generic_model.py`**

In `src/pipeline_generator/generator/generic_model.py`, add this function right after the imports (before the `InputOption` class):

```python
def build_test_case_value(environment_key: str, scenario_key: str) -> str:
    """The single format used everywhere an environment+scenario pair is
    combined into one selector: the manual pipeline's dropdown value, the
    generated script's --test-case argument, and every resolver function
    keyed by it.
    """
    return f"{environment_key}: {scenario_key}"
```

Then change `GenericPipelinePackage` from:

```python
@dataclass
class GenericPipelinePackage:
    setup_id: str
    cicd_type: str
    tool_type: str
    manual_pipeline: ManualPipelineSpec | None = None
    automated_jobs: list[AutomatedJobSpec] = field(default_factory=list)
    environments: list[InputOption] = field(default_factory=list)
    scenarios: list[InputOption] = field(default_factory=list)
```

to:

```python
@dataclass
class GenericPipelinePackage:
    setup_id: str
    cicd_type: str
    tool_type: str
    manual_pipeline: ManualPipelineSpec | None = None
    automated_jobs: list[AutomatedJobSpec] = field(default_factory=list)
    environments: list[InputOption] = field(default_factory=list)
    scenarios: list[InputOption] = field(default_factory=list)
    environment_keys: list[InputOption] = field(default_factory=list)
    scenario_keys: list[InputOption] = field(default_factory=list)
```

(`InputOption`, `PipelineInput`, `ManualPipelineSpec`, and `AutomatedJobSpec` are otherwise unchanged.)

- [ ] **Step 9: Rewrite `build_generic_package` in `context.py`**

Replace the full contents of `src/pipeline_generator/generator/context.py` with:

```python
from __future__ import annotations

from pipeline_generator.config.placeholders import TODO_VALUE
from pipeline_generator.generator.generic_model import (
    AutomatedJobSpec,
    GenericPipelinePackage,
    InputOption,
    ManualPipelineSpec,
    PipelineInput,
    build_test_case_value,
)


def build_generic_package(config: dict) -> GenericPipelinePackage:
    setup = config["setup"]
    cicd_type = config["cicd"]["type"]
    tool_type = config["tool"]["type"]

    environments: list[InputOption] = []
    scenarios: list[InputOption] = []
    environment_keys: list[InputOption] = []
    scenario_keys: list[InputOption] = []
    for env_item in config["catalog"]["environments"]:
        environment_key = env_item["key"]
        environment_identifier = env_item.get("identifier", TODO_VALUE)
        for scenario_item in env_item.get("scenarios", []):
            scenario_key = scenario_item["key"]
            scenario_identifier = scenario_item.get("identifier", TODO_VALUE)
            test_case_value = build_test_case_value(environment_key, scenario_key)
            environments.append(InputOption(value=test_case_value, identifier=environment_identifier))
            scenarios.append(InputOption(value=test_case_value, identifier=scenario_identifier))
            environment_keys.append(InputOption(value=test_case_value, identifier=environment_key))
            scenario_keys.append(InputOption(value=test_case_value, identifier=scenario_key))

    manual_pipeline = None
    if setup["generation_mode"] in {"manual_only", "both"} and config["manual_pipeline"]["enabled"]:
        manual_pipeline = ManualPipelineSpec(
            name=config["manual_pipeline"]["name"],
            inputs=[
                PipelineInput("test_case", "Test case", "dropdown", environments),
            ],
            timeout_minutes=int(config["manual_pipeline"]["timeout_minutes"]),
        )

    automated_jobs = []
    if setup["generation_mode"] in {"automated_only", "both"}:
        for job in config["automated_jobs"]:
            if not job.get("enabled", True):
                continue
            automated_jobs.append(
                AutomatedJobSpec(
                    name=job["name"],
                    timeout_minutes=int(job.get("timeout_minutes", 240)),
                    environment_ref=job["environment_ref"],
                    scenario_ref=job["scenario_ref"],
                )
            )

    return GenericPipelinePackage(
        setup_id=setup["id"],
        cicd_type=cicd_type,
        tool_type=tool_type,
        manual_pipeline=manual_pipeline,
        automated_jobs=automated_jobs,
        environments=environments,
        scenarios=scenarios,
        environment_keys=environment_keys,
        scenario_keys=scenario_keys,
    )
```

- [ ] **Step 10: Run both test files to verify they pass**

Run: `pytest tests/test_validation.py tests/test_generic_model.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 11: Commit**

```bash
git add src/pipeline_generator/config/schema.py src/pipeline_generator/config/validator.py \
  src/pipeline_generator/generator/generic_model.py src/pipeline_generator/generator/context.py \
  tests/test_validation.py tests/test_generic_model.py
git commit -m "feat: nest catalog scenarios under their owning environment

Scenarios are now scoped to a single environment (catalog.environments[].scenarios[])
instead of a flat, independent top-level list. build_generic_package walks the
nesting and produces environment/scenario InputOption pairs all keyed by one
combined test-case string (build_test_case_value), plus two new raw-key lists
(environment_keys/scenario_keys) for run-summary.json's separate fields.
validate_config's catalog checks move with it: duplicate-scenario-key detection
is now per-environment, and automated job scenario_ref is validated against
its own environment_ref's scenario list rather than a global one.

Note: context.py, scripts.py's resolvers, the three CI/CD renderers, and the
wizard's catalog step all still reference the old flat shape until later tasks
in this plan land -- test_tool_scripts.py, the renderer tests, and the wizard
tests are expected to fail until then."
```

---

## Task 2: Generated script — combined test-case resolvers

**Files:**
- Modify: `src/pipeline_generator/renderers/scripts.py`
- Test: `tests/test_tool_scripts.py`

**Interfaces:**
- Consumes: `GenericPipelinePackage.environments`/`.scenarios`/`.environment_keys`/`.scenario_keys` (from Task 1), `build_test_case_value` (from Task 1, used only in the test file's assertions here — production code in this task doesn't call it directly).
- Produces: generated `scripts/run-<tool_type>.sh` files take `--test-case "<environment: scenario>"` instead of `--environment`/`--scenario`. No other task depends on this file's internals directly, but the renderers built in Task 3 must bake commands that match this exact CLI shape.

- [ ] **Step 1: Update the shared test fixture and imports in `test_tool_scripts.py`**

In `tests/test_tool_scripts.py`, change `_base_config`'s catalog section from:

```python
        "catalog": {
            "environments": [
                {"key": "qa", "identifier": "env-qa"},
                {"key": "staging", "identifier": "env-stg"},
            ],
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
        },
```

to:

```python
        "catalog": {
            "environments": [
                {
                    "key": "qa",
                    "identifier": "env-qa",
                    "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
                },
                {"key": "staging", "identifier": "env-stg", "scenarios": []},
            ],
        },
```

- [ ] **Step 2: Apply the mechanical `--environment`/`--scenario` → `--test-case` replacement**

Nearly every test in this file invokes the generated script (or asserts about it) using the literal pair `"--environment", "qa", "--scenario", "checkout_smoke"` (optionally followed by `, "--timeout-minutes", "N"`, which is untouched by this replacement). Run this from the project root — it rewrites every occurrence of that exact argument sequence, regardless of how it's wrapped across lines:

```bash
python3 - <<'EOF'
import re
import pathlib

path = pathlib.Path("tests/test_tool_scripts.py")
content = path.read_text()
new_content = re.sub(
    r'"--environment",\s*"qa",\s*"--scenario",\s*"checkout_smoke"',
    '"--test-case", "qa: checkout_smoke"',
    content,
)
count = len(re.findall(r'"--environment",\s*"qa",\s*"--scenario",\s*"checkout_smoke"', content))
print(f"replaced {count} occurrences")
path.write_text(new_content)
EOF
```

Expected output: `replaced 17 occurrences`. If the count differs, stop and check what changed before continuing — the remaining steps assume exactly these 17 were mechanical and the rest (below) are hand-edited.

- [ ] **Step 3: Hand-rewrite the eight tests the mechanical pass can't touch**

These reference a bare environment/scenario key directly (not the literal `"qa"`/`"checkout_smoke"` pair), or check exact resolver/usage-message text that changes shape. Find each by name and replace as shown.

**`test_jmeter_resolver_uses_exact_match_not_glob`** — replace the whole function body:

```python
def test_jmeter_resolver_uses_exact_match_not_glob(tmp_path: Path) -> None:
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"] = [
        {
            "key": "*",
            "identifier": "should-not-match",
            "scenarios": [{"key": "checkout_smoke", "identifier": "should-not-match"}],
        },
        {
            "key": "staging",
            "identifier": "env-stg",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
        },
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; resolve_environment_identifier "staging: checkout_smoke"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "env-stg"
```

**`test_resolver_handles_adversarial_catalog_keys`** — replace the whole function body:

```python
def test_resolver_handles_adversarial_catalog_keys(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"
    adversarial_keys = [
        "qa's staging",
        "east us",
        f"$(touch {marker})",
        f"`touch {marker}`",
    ]
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"] = [
        {
            "key": key,
            "identifier": f"env-{i}",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
        }
        for i, key in enumerate(adversarial_keys)
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-jmeter.sh"

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr

    for i, key in enumerate(adversarial_keys):
        test_case = f"{key}: checkout_smoke"
        # shlex.quote here only protects the *test's* shell -c string; it has
        # nothing to do with the production shell_quote already baked into
        # the sourced script. This exercises exactly what the generated
        # `[ "$1" = '...' ]` comparison does with a hostile key -- it must
        # match literally rather than executing $(...) or backticks.
        command = f"source {shlex.quote(str(script_path))}; resolve_environment_identifier {shlex.quote(test_case)}"
        result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"env-{i}"

    assert not marker.exists()
```

**`test_render_blazemeter_script_requires_timeout_minutes_flag`** — within this function, replace these two lines:

```python
    assert 'echo "Usage: $0 --environment <key> --scenario <key> --timeout-minutes <minutes>" >&2' in content
```
becomes
```python
    assert 'echo "Usage: $0 --test-case <environment: scenario> --timeout-minutes <minutes>" >&2' in content
```

and:
```python
        ["bash", "-c", f'source "{script_path}"; main --environment qa --scenario checkout_smoke'],
```
becomes
```python
        ["bash", "-c", f'source "{script_path}"; main --test-case "qa: checkout_smoke"'],
```

**`test_render_blazemeter_script_rejects_non_numeric_timeout`** — within this function, replace:
```python
            f'source "{script_path}"; main --environment qa --scenario checkout_smoke --timeout-minutes abc',
```
with:
```python
            f'source "{script_path}"; main --test-case "qa: checkout_smoke" --timeout-minutes abc',
```

**`test_render_blazemeter_script_sanitizes_results_dir_from_hostile_catalog_key`** — replace the whole function body:

```python
def test_render_blazemeter_script_sanitizes_results_dir_from_hostile_catalog_key(tmp_path: Path) -> None:
    config = _base_config(
        "blazemeter", {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"}
    )
    config["catalog"]["environments"] = [
        {
            "key": "../../pwn",
            "identifier": "Hostile",
            "scenarios": [{"key": "checkout_smoke", "identifier": "1234567"}],
        }
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-blazemeter.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_environment_slug() {" in content

    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; resolve_environment_slug "../../pwn: checkout_smoke"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    slug = result.stdout.strip()
    assert ".." not in slug
    assert "/" not in slug

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr
```

**`test_render_loadrunner_script_sanitizes_results_dir_from_hostile_catalog_key`** — replace the whole function body:

```python
def test_render_loadrunner_script_sanitizes_results_dir_from_hostile_catalog_key(tmp_path: Path) -> None:
    config = _base_config("loadrunner_professional", {"wlrun_path": "wlrun"})
    config["catalog"]["environments"] = [
        {
            "key": "../../pwn",
            "identifier": "Hostile",
            "scenarios": [{"key": "checkout_smoke", "identifier": "C:\\Scenarios\\checkout_smoke.lrs"}],
        }
    ]
    package = build_generic_package(config)

    render_tool_script(config, package, tmp_path)
    script_path = tmp_path / "scripts" / "run-loadrunner_professional.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "resolve_environment_slug() {" in content
    assert "resolve_scenario_slug() {" in content

    # The slug resolver must map the hostile key to a sanitized value at
    # generation time (safe_filename_component == slugify), not pass it
    # through raw -- this is what closes the run-output/../../pwn escape
    # the final review demonstrated.
    result = subprocess.run(
        ["bash", "-c", f'source "{script_path}"; resolve_environment_slug "../../pwn: checkout_smoke"'],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    slug = result.stdout.strip()
    assert ".." not in slug
    assert "/" not in slug

    syntax_check = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert syntax_check.returncode == 0, syntax_check.stderr
```

**`test_render_jmeter_script_rerun_with_different_scenario_uses_separate_dirs`** — within this function, replace:
```python
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["scenarios"] = [
        {"key": "checkout_smoke", "identifier": "SC-1"},
        {"key": "checkout_full", "identifier": "SC-2"},
    ]
```
with:
```python
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"][0]["scenarios"] = [
        {"key": "checkout_smoke", "identifier": "SC-1"},
        {"key": "checkout_full", "identifier": "SC-2"},
    ]
```
and further down in the same function, replace:
```python
    for scenario in ("checkout_smoke", "checkout_full"):
        result = subprocess.run(
            ["bash", str(script_path), "--environment", "qa", "--scenario", scenario],
```
with:
```python
    for scenario in ("checkout_smoke", "checkout_full"):
        result = subprocess.run(
            ["bash", str(script_path), "--test-case", f"qa: {scenario}"],
```

**`test_render_jmeter_script_escapes_embedded_control_characters_in_run_summary`** — within this function, replace:
```python
    hostile_scenario_key = "smoke\ntest\tcase"
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["scenarios"] = [
        {"key": hostile_scenario_key, "identifier": "SC-1"}
    ]
```
with:
```python
    hostile_scenario_key = "smoke\ntest\tcase"
    config = _base_config("jmeter", {"test_plan_path": "plan.jmx", "docker_image": ""})
    config["catalog"]["environments"][0]["scenarios"] = [
        {"key": hostile_scenario_key, "identifier": "SC-1"}
    ]
```
and further down, replace:
```python
    result = subprocess.run(
        ["bash", str(script_path), "--environment", "qa", "--scenario", hostile_scenario_key],
```
with:
```python
    result = subprocess.run(
        ["bash", str(script_path), "--test-case", f"qa: {hostile_scenario_key}"],
```

- [ ] **Step 4: Update the one remaining content-assertion for the 6-resolver script layout**

In `test_render_jmeter_script_with_precheck`, the existing assertions:
```python
    assert "resolve_environment_identifier() {" in content
    assert "resolve_scenario_identifier() {" in content
```
stay as-is (these function names don't change) — no edit needed here. This step is a checkpoint, not a code change: confirm these two lines are still present unmodified before moving on.

- [ ] **Step 5: Run the tests to verify they fail against the current production code**

Run: `pytest tests/test_tool_scripts.py -v`
Expected: FAIL — `render_tool_script` (via `context.py` from Task 1) now produces `InputOption` lists keyed by the combined test-case string, but `scripts.py` hasn't been updated yet, so the generated scripts still parse `--environment`/`--scenario` and resolve by bare key. Most tests should fail with either a script parse/usage error (since the test now passes `--test-case` but the script doesn't recognize that flag) or a resolver returning "Unknown ... key" (since resolvers are still keyed by bare values that no longer exist in the `.value` fields).

- [ ] **Step 6: Rewrite the resolver-building functions in `scripts.py`**

In `src/pipeline_generator/renderers/scripts.py`, replace:

```python
def _render_resolvers(package: GenericPipelinePackage) -> str:
    environment_resolver = _render_resolver_function(
        "resolve_environment_identifier", "environment", package.environments
    )
    scenario_resolver = _render_resolver_function("resolve_scenario_identifier", "scenario", package.scenarios)
    return f"{environment_resolver}\n\n{scenario_resolver}"


def _render_slug_resolvers(package: GenericPipelinePackage) -> str:
    environment_slugs = [
        InputOption(value=item.value, identifier=safe_filename_component(item.value))
        for item in package.environments
    ]
    scenario_slugs = [
        InputOption(value=item.value, identifier=safe_filename_component(item.value))
        for item in package.scenarios
    ]
    environment_slug_resolver = _render_resolver_function(
        "resolve_environment_slug", "environment", environment_slugs
    )
    scenario_slug_resolver = _render_resolver_function("resolve_scenario_slug", "scenario", scenario_slugs)
    return f"{environment_slug_resolver}\n\n{scenario_slug_resolver}"
```

with:

```python
def _render_resolvers(package: GenericPipelinePackage) -> str:
    environment_resolver = _render_resolver_function(
        "resolve_environment_identifier", "test case", package.environments
    )
    scenario_resolver = _render_resolver_function("resolve_scenario_identifier", "test case", package.scenarios)
    environment_key_resolver = _render_resolver_function(
        "resolve_environment_key", "test case", package.environment_keys
    )
    scenario_key_resolver = _render_resolver_function(
        "resolve_scenario_key", "test case", package.scenario_keys
    )
    return (
        f"{environment_resolver}\n\n{scenario_resolver}\n\n"
        f"{environment_key_resolver}\n\n{scenario_key_resolver}"
    )


def _render_slug_resolvers(package: GenericPipelinePackage) -> str:
    environment_slugs = [
        InputOption(value=item.value, identifier=safe_filename_component(item.identifier))
        for item in package.environment_keys
    ]
    scenario_slugs = [
        InputOption(value=item.value, identifier=safe_filename_component(item.identifier))
        for item in package.scenario_keys
    ]
    environment_slug_resolver = _render_resolver_function(
        "resolve_environment_slug", "test case", environment_slugs
    )
    scenario_slug_resolver = _render_resolver_function("resolve_scenario_slug", "test case", scenario_slugs)
    return f"{environment_slug_resolver}\n\n{scenario_slug_resolver}"
```

(`_render_resolver_function` itself is unchanged — it already takes any `list[InputOption]` and a `kind` label for its error message.)

- [ ] **Step 7: Rewrite `_render_arg_parsing`**

In `src/pipeline_generator/renderers/scripts.py`, replace the full body of `_render_arg_parsing`:

```python
def _render_arg_parsing(include_timeout: bool = False) -> str:
    timeout_local = ""
    timeout_case = ""
    timeout_required_check = ""
    timeout_usage = ""
    timeout_numeric_check = ""
    if include_timeout:
        timeout_local = '  local timeout_minutes=""\n'
        timeout_case = '      --timeout-minutes) timeout_minutes="$2"; shift 2 ;;\n'
        timeout_required_check = ' || [ -z "$timeout_minutes" ]'
        timeout_usage = ' --timeout-minutes <minutes>'
        timeout_numeric_check = """
  case "$timeout_minutes" in
    ''|*[!0-9]*)
      echo "ERROR: --timeout-minutes must be a positive integer, got: $timeout_minutes" >&2
      exit 1
      ;;
  esac
"""

    return f"""  local environment_key=""
  local scenario_key=""
{timeout_local}  while [ $# -gt 0 ]; do
    case "$1" in
      --environment) environment_key="$2"; shift 2 ;;
      --scenario) scenario_key="$2"; shift 2 ;;
{timeout_case}      *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
  done

  if [ -z "$environment_key" ] || [ -z "$scenario_key" ]{timeout_required_check}; then
    echo "Usage: $0 --environment <key> --scenario <key>{timeout_usage}" >&2
    exit 1
  fi
{timeout_numeric_check}
  local environment_identifier
  local scenario_identifier
  environment_identifier="$(resolve_environment_identifier "$environment_key")"
  scenario_identifier="$(resolve_scenario_identifier "$scenario_key")"
"""
```

with:

```python
def _render_arg_parsing(include_timeout: bool = False) -> str:
    timeout_local = ""
    timeout_case = ""
    timeout_required_check = ""
    timeout_usage = ""
    timeout_numeric_check = ""
    if include_timeout:
        timeout_local = '  local timeout_minutes=""\n'
        timeout_case = '      --timeout-minutes) timeout_minutes="$2"; shift 2 ;;\n'
        timeout_required_check = ' || [ -z "$timeout_minutes" ]'
        timeout_usage = ' --timeout-minutes <minutes>'
        timeout_numeric_check = """
  case "$timeout_minutes" in
    ''|*[!0-9]*)
      echo "ERROR: --timeout-minutes must be a positive integer, got: $timeout_minutes" >&2
      exit 1
      ;;
  esac
"""

    return f"""  local test_case=""
{timeout_local}  while [ $# -gt 0 ]; do
    case "$1" in
      --test-case) test_case="$2"; shift 2 ;;
{timeout_case}      *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
  done

  if [ -z "$test_case" ]{timeout_required_check}; then
    echo "Usage: $0 --test-case <environment: scenario>{timeout_usage}" >&2
    exit 1
  fi
{timeout_numeric_check}
  local environment_identifier
  local scenario_identifier
  local environment_key
  local scenario_key
  environment_identifier="$(resolve_environment_identifier "$test_case")"
  scenario_identifier="$(resolve_scenario_identifier "$test_case")"
  environment_key="$(resolve_environment_key "$test_case")"
  scenario_key="$(resolve_scenario_key "$test_case")"
"""
```

- [ ] **Step 8: Update the three tool-specific script bodies' slug-resolution call sites**

In `src/pipeline_generator/renderers/scripts.py`, this exact pair of lines appears three times — once each in `_render_jmeter_script`, `_render_blazemeter_script`, and `_render_loadrunner_script`:

```python
  environment_slug="$(resolve_environment_slug "$environment_key")"
  scenario_slug="$(resolve_scenario_slug "$scenario_key")"
```

In all three places, change it to:

```python
  environment_slug="$(resolve_environment_slug "$test_case")"
  scenario_slug="$(resolve_scenario_slug "$test_case")"
```

Nothing else in these three functions changes — `$environment_identifier`, `$scenario_identifier`, `$environment_key`, `$scenario_key`, `$environment_slug`, `$scenario_slug` are all still populated under those exact names, just resolved from `$test_case` instead of two separately-parsed CLI flags.

- [ ] **Step 9: Run the full test file to verify it passes**

Run: `pytest tests/test_tool_scripts.py -v`
Expected: PASS (all tests in this file)

- [ ] **Step 10: Commit**

```bash
git add src/pipeline_generator/renderers/scripts.py tests/test_tool_scripts.py
git commit -m "feat: generated scripts resolve environment+scenario from one --test-case flag

scripts/run-<tool_type>.sh now takes --test-case \"<environment: scenario>\"
instead of separate --environment/--scenario flags. All six resolver
functions (identifier x2, key x2, slug x2) are keyed by that one combined
string, following the same exact-match if-chain pattern the four existing
resolvers already used -- deliberately not a case statement, since case
patterns are shell globs. Renderers (next task) and the readme/wizard tests
still reference the old two-flag shape until their own tasks land."
```

---

## Task 3: CI/CD renderers — one combined dropdown/parameter/choice

**Files:**
- Modify: `src/pipeline_generator/renderers/github_actions.py`
- Modify: `src/pipeline_generator/renderers/azure_devops.py`
- Modify: `src/pipeline_generator/renderers/jenkins.py`
- Test: `tests/test_github_actions_renderer.py`
- Test: `tests/test_azure_devops_renderer.py`
- Test: `tests/test_jenkins_renderer.py`
- Test: `tests/test_readme_renderer.py`

**Interfaces:**
- Consumes: `package.manual_pipeline.inputs[0]` (now the single combined `test_case` `PipelineInput` from Task 1's `context.py` — `inputs[1]` no longer exists), `build_test_case_value` (from Task 1) for formatting automated jobs' baked value.

- [ ] **Step 1: Update `test_readme_renderer.py`'s fixture (no other changes needed in this file)**

In `tests/test_readme_renderer.py`, change `_base_config`'s catalog section from:

```python
        "catalog": {
            "environments": [{"key": "qa", "identifier": "env-qa"}],
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
        },
```

to:

```python
        "catalog": {
            "environments": [
                {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
            ],
        },
```

- [ ] **Step 2: Write the failing tests for GitHub Actions**

Replace the full contents of `tests/test_github_actions_renderer.py` with:

```python
import re
from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.github_actions import render_github_actions
from pipeline_generator.renderers.quoting import shell_quote


def _config() -> dict:
    return {
        "setup": {"id": "gha-test-setup", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [
                {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
        ],
    }


def test_render_github_actions_writes_valid_workflows(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_github_actions(config, package, tmp_path)

    manual_path = tmp_path / ".github" / "workflows" / "performance-manual.yml"
    automated_path = tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)
    assert manual_doc["name"] == "Performance Manual Run"
    assert manual_doc["jobs"]["run-performance-test"]["timeout-minutes"] == 120
    assert '"qa: checkout_smoke"' in manual_text
    # The build-triggerer-controlled input must be delivered via env:, never
    # spliced directly into the run: shell text (workflow_dispatch's `choice`
    # restriction is only enforced by GitHub's UI, not its dispatch API).
    step = manual_doc["jobs"]["run-performance-test"]["steps"][1]
    assert step["env"] == {"TEST_CASE": "${{ github.event.inputs.test_case }}"}
    assert "./scripts/run-jmeter.sh" in manual_text
    assert '--test-case "$TEST_CASE"' in manual_text
    assert "github.event.inputs" not in step["run"]
    assert "pipeline-generator" not in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"]["post-deploy-smoke"]["timeout-minutes"] == 60
    assert "./scripts/run-jmeter.sh" in automated_text
    assert "--test-case 'qa: checkout_smoke'" in automated_text
    assert "pipeline-generator" not in automated_text


def test_render_github_actions_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    nasty_pipeline_name = 'My "Perf" Pipeline: v2'
    config = {
        "setup": {"id": "gha-adversarial", "generation_mode": "both"},
        "cicd": {"type": "github_actions"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [
                {
                    "key": nasty_env_value,
                    "identifier": "env-nasty",
                    "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
                }
            ],
        },
        "manual_pipeline": {"enabled": True, "name": nasty_pipeline_name, "timeout_minutes": 30},
        "automated_jobs": [
            {
                "name": nasty_job_name,
                "enabled": True,
                "environment_ref": nasty_env_value,
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 15,
            }
        ],
    }
    package = build_generic_package(config)

    outputs = render_github_actions(config, package, tmp_path)

    # A hostile job name must never escape the intended output directory or
    # produce filesystem-unsafe filenames.
    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / ".github" / "workflows" / "performance-manual.yml"
    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)  # raises if the escaping broke YAML syntax
    assert manual_doc["name"] == nasty_pipeline_name
    nasty_test_case = f"{nasty_env_value}: checkout_smoke"
    # PyYAML's default resolver reads the bare "on:" key as boolean True.
    assert nasty_test_case in manual_doc[True]["workflow_dispatch"]["inputs"]["test_case"]["options"]

    workflows_dir = tmp_path / ".github" / "workflows"
    automated_files = [p for p in workflows_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    assert automated_doc["name"] == f"Performance Automated Job - {nasty_job_name}"
    job_id = next(iter(automated_doc["jobs"]))
    assert re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", job_id)
    assert shell_quote(nasty_test_case) in automated_text


def test_render_github_actions_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_github_actions(config, package, tmp_path)

    manual_text = (tmp_path / ".github" / "workflows" / "performance-manual.yml").read_text(encoding="utf-8")
    automated_text = (
        tmp_path / ".github" / "workflows" / "performance-automated-post-deploy-smoke.yml"
    ).read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text
```

- [ ] **Step 3: Write the failing tests for Azure DevOps**

Replace the full contents of `tests/test_azure_devops_renderer.py` with:

```python
import re
from pathlib import Path

import yaml

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.azure_devops import render_azure_devops
from pipeline_generator.renderers.quoting import shell_quote


def _config() -> dict:
    return {
        "setup": {"id": "azure-test-setup", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [
                {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
        ],
    }


def test_render_azure_devops_writes_valid_pipelines(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_azure_devops(config, package, tmp_path)

    manual_path = tmp_path / "azure" / "performance-manual.yml"
    automated_path = tmp_path / "azure" / "performance-automated-post-deploy-smoke.yml"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)
    assert manual_doc["jobs"][0]["timeoutInMinutes"] == 120
    assert manual_doc["parameters"][0]["name"] == "testCase"
    assert "qa: checkout_smoke" in manual_text
    # The parameter value must be delivered via env:, never spliced directly
    # into the script: text.
    run_step = manual_doc["jobs"][0]["steps"][1]
    assert run_step["env"] == {"TEST_CASE": "${{ parameters.testCase }}"}
    assert "./scripts/run-jmeter.sh" in manual_text
    assert '--test-case "$TEST_CASE"' in manual_text
    assert "parameters.testCase" not in run_step["script"]
    assert "pipeline-generator" not in manual_text

    automated_text = automated_path.read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)
    assert automated_doc["jobs"][0]["timeoutInMinutes"] == 60
    # job identifiers get hyphens sanitized to underscores.
    assert automated_doc["jobs"][0]["job"] == "post_deploy_smoke"
    assert "./scripts/run-jmeter.sh" in automated_text
    assert "--test-case 'qa: checkout_smoke'" in automated_text
    assert "pipeline-generator" not in automated_text


def test_render_azure_devops_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = 'qa" evil: true'
    nasty_job_name = 'weird "job"; rm -rf / : ../../etc'
    config = {
        "setup": {"id": "azure-adversarial", "generation_mode": "both"},
        "cicd": {"type": "azure_devops"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [
                {
                    "key": nasty_env_value,
                    "identifier": "env-nasty",
                    "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
                }
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [
            {
                "name": nasty_job_name,
                "enabled": True,
                "environment_ref": nasty_env_value,
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 15,
            }
        ],
    }
    package = build_generic_package(config)

    outputs = render_azure_devops(config, package, tmp_path)

    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    manual_path = tmp_path / "azure" / "performance-manual.yml"
    manual_text = manual_path.read_text(encoding="utf-8")
    manual_doc = yaml.safe_load(manual_text)  # raises if the escaping broke YAML syntax
    test_case_param = next(p for p in manual_doc["parameters"] if p["name"] == "testCase")
    nasty_test_case = f"{nasty_env_value}: checkout_smoke"
    assert nasty_test_case in test_case_param["values"]

    azure_dir = tmp_path / "azure"
    automated_files = [p for p in azure_dir.iterdir() if p.name.startswith("performance-automated-")]
    assert len(automated_files) == 1
    automated_text = automated_files[0].read_text(encoding="utf-8")
    automated_doc = yaml.safe_load(automated_text)  # raises if the escaping broke YAML syntax

    job_id = automated_doc["jobs"][0]["job"]
    assert re.match(r"^[A-Za-z0-9_]+$", job_id)
    assert not job_id[0].isdigit()
    assert shell_quote(nasty_test_case) in automated_text


def test_render_azure_devops_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_azure_devops(config, package, tmp_path)

    manual_text = (tmp_path / "azure" / "performance-manual.yml").read_text(encoding="utf-8")
    automated_text = (tmp_path / "azure" / "performance-automated-post-deploy-smoke.yml").read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text
```

- [ ] **Step 4: Write the failing tests for Jenkins**

Replace the full contents of `tests/test_jenkins_renderer.py` with:

```python
from pathlib import Path

from pipeline_generator.generator.context import build_generic_package
from pipeline_generator.renderers.jenkins import render_jenkins
from pipeline_generator.renderers.quoting import groovy_squote


def _config() -> dict:
    return {
        "setup": {"id": "jenkins-test-setup", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [
                {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 120},
        "automated_jobs": [
            {
                "name": "post-deploy-smoke",
                "enabled": True,
                "environment_ref": "qa",
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 60,
            }
        ],
    }


def test_render_jenkins_writes_manual_and_automated_jenkinsfiles(tmp_path: Path) -> None:
    config = _config()
    package = build_generic_package(config)

    outputs = render_jenkins(config, package, tmp_path)

    manual_path = tmp_path / "jenkins" / "Jenkinsfile.performance-manual"
    automated_path = tmp_path / "jenkins" / "Jenkinsfile.performance-automated-post-deploy-smoke"
    assert str(manual_path) in outputs
    assert str(automated_path) in outputs

    manual_content = manual_path.read_text(encoding="utf-8")
    assert "./scripts/run-jmeter.sh" in manual_content
    assert '--test-case "$TEST_CASE"' in manual_content
    assert "'qa: checkout_smoke'," in manual_content
    assert "timeout(time: 120, unit: 'MINUTES')" in manual_content
    assert "pipeline-generator" not in manual_content

    automated_content = automated_path.read_text(encoding="utf-8")
    assert "TEST_CASE = 'qa: checkout_smoke'" in automated_content
    assert './scripts/run-jmeter.sh --test-case "$TEST_CASE"' in automated_content
    assert "timeout(time: 60, unit: 'MINUTES')" in automated_content
    assert "pipeline-generator" not in automated_content


def test_render_jenkins_escapes_adversarial_values(tmp_path: Path) -> None:
    nasty_env_value = "qa'; rm -rf / #"
    nasty_job_name = "weird'job\"; rm -rf / \\ ../../etc"
    config = {
        "setup": {"id": "jenkins-adversarial", "generation_mode": "both"},
        "cicd": {"type": "jenkins"},
        "tool": {"type": "jmeter", "connection": {"test_plan_path": "plan.jmx", "docker_image": ""}},
        "pre_run_checks": [],
        "catalog": {
            "environments": [
                {
                    "key": nasty_env_value,
                    "identifier": "env-nasty",
                    "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
                }
            ],
        },
        "manual_pipeline": {"enabled": True, "name": "Performance Manual Run", "timeout_minutes": 30},
        "automated_jobs": [
            {
                "name": nasty_job_name,
                "enabled": True,
                "environment_ref": nasty_env_value,
                "scenario_ref": "checkout_smoke",
                "timeout_minutes": 15,
            }
        ],
    }
    package = build_generic_package(config)

    outputs = render_jenkins(config, package, tmp_path)

    for output in outputs:
        filename = Path(output).name
        assert "/" not in filename
        assert ".." not in filename
        assert " " not in filename

    nasty_test_case = f"{nasty_env_value}: checkout_smoke"

    manual_path = tmp_path / "jenkins" / "Jenkinsfile.performance-manual"
    manual_content = manual_path.read_text(encoding="utf-8")
    # The hostile combined value must appear only inside a properly escaped
    # single-quoted Groovy string, never able to close the `choice` literal's
    # quote early.
    assert groovy_squote(nasty_test_case) in manual_content
    assert '--test-case "$TEST_CASE"' in manual_content

    jenkins_dir = tmp_path / "jenkins"
    automated_files = [p for p in jenkins_dir.iterdir() if p.name.startswith("Jenkinsfile.performance-automated-")]
    assert len(automated_files) == 1
    automated_content = automated_files[0].read_text(encoding="utf-8")
    # The combined test-case value must be delivered via the environment{}
    # block, Groovy-escaped, never spliced directly into the sh command text.
    assert f"TEST_CASE = {groovy_squote(nasty_test_case)}" in automated_content
    assert './scripts/run-jmeter.sh --test-case "$TEST_CASE"' in automated_content


def test_render_jenkins_includes_timeout_flag_for_blazemeter(tmp_path: Path) -> None:
    config = _config()
    config["tool"] = {
        "type": "blazemeter",
        "connection": {"base_url": "https://a.blazemeter.com", "workspace_id": "12345", "project_id": "67890"},
    }
    package = build_generic_package(config)

    render_jenkins(config, package, tmp_path)

    manual_text = (tmp_path / "jenkins" / "Jenkinsfile.performance-manual").read_text(encoding="utf-8")
    automated_text = (
        tmp_path / "jenkins" / "Jenkinsfile.performance-automated-post-deploy-smoke"
    ).read_text(encoding="utf-8")

    assert "--timeout-minutes 120" in manual_text
    assert "--timeout-minutes 60" in automated_text
```

- [ ] **Step 5: Run all four test files to verify they fail**

Run: `pytest tests/test_readme_renderer.py tests/test_github_actions_renderer.py tests/test_azure_devops_renderer.py tests/test_jenkins_renderer.py -v`
Expected: `test_readme_renderer.py` PASSES already (it only needed the fixture fix, and `render_setup_readme` doesn't touch `inputs[1]`). The three renderer test files FAIL — `_render_manual_workflow`/`_render_manual_pipeline` still index `inputs[1]`, which no longer exists (`IndexError: list index out of range`).

- [ ] **Step 6: Rewrite `github_actions.py`**

In `src/pipeline_generator/renderers/github_actions.py`, add the import:

```python
from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage, build_test_case_value
```

(replaces the current `from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage`)

Replace `_render_manual_workflow`:

```python
def _render_manual_workflow(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    test_case_options = ", ".join(yaml_dquote(item.value) for item in package.manual_pipeline.inputs[0].options)
    timeout = package.manual_pipeline.timeout_minutes
    timeout_flag = blazemeter_timeout_flag(package.tool_type, timeout, separator="\n          ")
    return f"""name: {yaml_dquote(package.manual_pipeline.name)}

on:
  workflow_dispatch:
    inputs:
      test_case:
        description: Select environment and scenario
        required: true
        type: choice
        options: [{test_case_options}]

jobs:
  run-performance-test:
    runs-on: ubuntu-latest
    timeout-minutes: {timeout}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        env:
          TEST_CASE: ${{{{ github.event.inputs.test_case }}}}
        run: >
          ./scripts/run-{package.tool_type}.sh
          --test-case "$TEST_CASE"{timeout_flag}
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: performance-results
          path: run-output/
"""
```

Replace `_render_automated_workflow`:

```python
def _render_automated_workflow(job: AutomatedJobSpec, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    timeout_flag = blazemeter_timeout_flag(tool_type, job.timeout_minutes, separator="\n          ")
    test_case = build_test_case_value(job.environment_ref, job.scenario_ref)
    return f"""name: {yaml_dquote(f"Performance Automated Job - {job.name}")}

on:
  workflow_call:

jobs:
  {job_id}:
    runs-on: ubuntu-latest
    timeout-minutes: {job.timeout_minutes}
    steps:
      - uses: actions/checkout@v4
      - name: Run performance wrapper
        run: >
          ./scripts/run-{tool_type}.sh
          --test-case {shell_quote(test_case)}{timeout_flag}
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: {yaml_dquote(f"performance-results-{job.name}")}
          path: run-output/
"""
```

- [ ] **Step 7: Rewrite `azure_devops.py`**

In `src/pipeline_generator/renderers/azure_devops.py`, add the import:

```python
from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage, build_test_case_value
```

Replace `_render_manual_pipeline`:

```python
def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    test_case_options = package.manual_pipeline.inputs[0].options
    test_case_values = "\n".join(f"      - {yaml_dquote(item.value)}" for item in test_case_options)
    test_case_default = yaml_dquote(test_case_options[0].value if test_case_options else "TODO")
    timeout_flag = blazemeter_timeout_flag(
        package.tool_type, package.manual_pipeline.timeout_minutes, separator="\n          "
    )
    return f"""trigger: none
pr: none

parameters:
  - name: testCase
    displayName: Environment and scenario
    type: string
    default: {test_case_default}
    values:
{test_case_values}

jobs:
  - job: run_performance_test
    timeoutInMinutes: {package.manual_pipeline.timeout_minutes}
    pool:
      vmImage: ubuntu-latest
    steps:
      - checkout: self
      - script: >
          ./scripts/run-{package.tool_type}.sh
          --test-case "$TEST_CASE"{timeout_flag}
        env:
          TEST_CASE: ${{{{ parameters.testCase }}}}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: performance-results
"""
```

Replace `_render_automated_job`:

```python
def _render_automated_job(job: AutomatedJobSpec, tool_type: str) -> str:
    job_id = _safe_job_id(job.name)
    timeout_flag = blazemeter_timeout_flag(tool_type, job.timeout_minutes, separator="\n          ")
    test_case = build_test_case_value(job.environment_ref, job.scenario_ref)
    return f"""parameters: []

jobs:
  - job: {job_id}
    timeoutInMinutes: {job.timeout_minutes}
    pool:
      vmImage: ubuntu-latest
    steps:
      - checkout: self
      - script: >
          ./scripts/run-{tool_type}.sh
          --test-case {shell_quote(test_case)}{timeout_flag}
        displayName: Run performance wrapper
      - task: PublishPipelineArtifact@1
        condition: always()
        inputs:
          targetPath: run-output
          artifact: {yaml_dquote(f"performance-results-{job.name}")}
"""
```

- [ ] **Step 8: Rewrite `jenkins.py`**

In `src/pipeline_generator/renderers/jenkins.py`, add the import:

```python
from pipeline_generator.generator.generic_model import AutomatedJobSpec, GenericPipelinePackage, build_test_case_value
```

Replace `_render_manual_pipeline`:

```python
def _render_manual_pipeline(package: GenericPipelinePackage) -> str:
    assert package.manual_pipeline is not None
    test_case_choices = "\n".join(
        f"                {groovy_squote(item.value)}," for item in package.manual_pipeline.inputs[0].options
    )
    timeout = package.manual_pipeline.timeout_minutes
    timeout_flag = blazemeter_timeout_flag(package.tool_type, timeout)
    return f"""pipeline {{
    agent any
    parameters {{
        choice(
            name: 'TEST_CASE',
            choices: [
{test_case_choices}
            ],
            description: 'Select environment and scenario'
        )
    }}
    options {{
        timeout(time: {timeout}, unit: 'MINUTES')
    }}
    stages {{
        stage('Run performance wrapper') {{
            steps {{
                // Build parameters are exposed as shell environment variables by
                // Jenkins; referencing them here (rather than Groovy-interpolating
                // ${{params.X}} into the command text) avoids splicing a
                // build-triggerer-controlled value directly into the shell script.
                sh './scripts/run-{package.tool_type}.sh --test-case "$TEST_CASE"{timeout_flag}'
            }}
        }}
    }}
    post {{
        always {{
            archiveArtifacts artifacts: 'run-output/**', allowEmptyArchive: true
        }}
    }}
}}
"""
```

Replace `_render_automated_job`:

```python
def _render_automated_job(job: AutomatedJobSpec, tool_type: str) -> str:
    timeout_flag = blazemeter_timeout_flag(tool_type, job.timeout_minutes)
    test_case = build_test_case_value(job.environment_ref, job.scenario_ref)
    return f"""pipeline {{
    agent any
    environment {{
        TEST_CASE = {groovy_squote(test_case)}
    }}
    options {{
        timeout(time: {job.timeout_minutes}, unit: 'MINUTES')
    }}
    stages {{
        stage('Run performance wrapper') {{
            steps {{
                sh './scripts/run-{tool_type}.sh --test-case "$TEST_CASE"{timeout_flag}'
            }}
        }}
    }}
    post {{
        always {{
            archiveArtifacts artifacts: 'run-output/**', allowEmptyArchive: true
        }}
    }}
}}
"""
```

- [ ] **Step 9: Run all four test files to verify they pass**

Run: `pytest tests/test_readme_renderer.py tests/test_github_actions_renderer.py tests/test_azure_devops_renderer.py tests/test_jenkins_renderer.py -v`
Expected: PASS (all tests in all four files)

- [ ] **Step 10: Commit**

```bash
git add src/pipeline_generator/renderers/github_actions.py src/pipeline_generator/renderers/azure_devops.py \
  src/pipeline_generator/renderers/jenkins.py tests/test_github_actions_renderer.py \
  tests/test_azure_devops_renderer.py tests/test_jenkins_renderer.py tests/test_readme_renderer.py
git commit -m "feat: one combined test-case dropdown/parameter/choice per CI/CD platform

All three renderers previously built two independent environment/scenario
trigger inputs (workflow_dispatch inputs, Azure parameters, Jenkins choice
parameters), which meant any combination was selectable regardless of
whether it was ever defined in the catalog. Each renderer now builds one
input listing only the valid pairs (inputs[0] only -- inputs[1] no longer
exists on ManualPipelineSpec), and bakes automated jobs' fixed pair via
the same build_test_case_value format used everywhere else.

Wizard tests are still on the old flat catalog shape until the next task."
```

---

## Task 4: Wizard flow — nested environment/scenario collection

**Files:**
- Modify: `src/pipeline_generator/wizard/flow.py`
- Test: `tests/test_wizard_resumable_list.py`
- Test: `tests/test_wizard_end_to_end.py`

**Interfaces:**
- Consumes: `CATALOG_IDENTIFIER_PROMPTS` (existing, unchanged), the resumable-list pattern (existing, unchanged).
- Produces: `_prompt_environments_section(existing: list[dict], tool_type: str) -> list[dict]` replaces `_prompt_catalog_section`/`_prompt_catalog_items` (removed — nothing else in the codebase calls them). `_prompt_automated_jobs(config: dict) -> list[dict]` keeps its existing name and signature but now filters scenario choices to the chosen environment.

- [ ] **Step 1: Write the failing tests for the nested environment/scenario wizard flow**

Replace the full contents of `tests/test_wizard_resumable_list.py` with:

```python
import pytest

from pipeline_generator.wizard.flow import (
    _prompt_automated_jobs,
    _prompt_automated_jobs_section,
    _prompt_environments_section,
)


def test_prompt_environments_section_keep_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["1"])  # "keep as-is" is option 1
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
    ]
    result = _prompt_environments_section(existing, "jmeter")

    assert result is existing


def test_prompt_environments_section_start_over(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(
        [
            "3",  # "start over"
            "staging",  # new environment key
            "env-staging",  # environment identifier
            "checkout_smoke",  # scenario key
            "SC-2",  # scenario identifier
            "",  # blank scenario key ends this environment's scenarios
            "",  # blank environment key ends environment collection
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
    ]
    result = _prompt_environments_section(existing, "jmeter")

    assert result == [
        {
            "key": "staging",
            "identifier": "env-staging",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-2"}],
        }
    ]


def test_prompt_environments_section_add_more(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(
        [
            "2",  # "add more"
            "staging",
            "env-staging",
            "checkout_smoke",
            "SC-2",
            "",  # blank scenario key ends this environment's scenarios
            "",  # blank environment key ends environment collection
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing = [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
    ]
    result = _prompt_environments_section(existing, "jmeter")

    assert result == [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]},
        {
            "key": "staging",
            "identifier": "env-staging",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-2"}],
        },
    ]


def test_prompt_environments_section_no_existing_declines_adding(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["n"])  # "Add environments now?" -> no
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    result = _prompt_environments_section([], "jmeter")

    assert result == []


def test_prompt_environments_section_identifier_labels_are_tool_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []
    responses = iter(
        [
            "y",  # "Add environments now?"
            "qa",  # environment key
            "env-qa",  # environment identifier
            "checkout_smoke",  # scenario key
            "C:\\Scenarios\\checkout_smoke_qa.lrs",  # scenario identifier
            "",  # blank scenario key ends this environment's scenarios
            "",  # blank environment key ends environment collection
        ]
    )

    def fake_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr("builtins.input", fake_input)

    _prompt_environments_section([], "loadrunner_professional")

    assert any("not used by the generated script for LoadRunner" in p for p in prompts)
    assert any("Path to the .lrs scenario file LoadRunner should run" in p for p in prompts)


def test_prompt_automated_jobs_section_keep_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = iter(["1"])  # "keep as-is"
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    existing_job = {
        "name": "nightly",
        "enabled": True,
        "environment_ref": "qa",
        "scenario_ref": "checkout_smoke",
        "timeout_minutes": 240,
    }
    config = {
        "automated_jobs": [existing_job],
        "catalog": {"environments": []},
    }
    result = _prompt_automated_jobs_section(config)

    assert result == [existing_job]


def test_prompt_automated_jobs_offers_only_scenarios_from_chosen_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = {
        "catalog": {
            "environments": [
                {
                    "key": "qa",
                    "identifier": "env-qa",
                    "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
                },
                {
                    "key": "staging",
                    "identifier": "env-staging",
                    "scenarios": [{"key": "browse_baseline", "identifier": "SC-2"}],
                },
            ]
        }
    }
    responses = iter(
        [
            "nightly-load",  # automated job name
            "2",  # environment key -> staging (second option)
            "1",  # scenario key -> only option offered for staging
            "",  # timeout -> default 240
            "",  # blank name ends automated job collection
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(responses))

    jobs = _prompt_automated_jobs(config)

    assert jobs == [
        {
            "name": "nightly-load",
            "enabled": True,
            "environment_ref": "staging",
            "scenario_ref": "browse_baseline",
            "timeout_minutes": 240,
        }
    ]
    printed = capsys.readouterr().out
    assert "browse_baseline" in printed
    assert "checkout_smoke" not in printed
```

- [ ] **Step 2: Write the failing test for the full wizard flow**

In `tests/test_wizard_end_to_end.py`, replace the `responses` list inside `test_run_wizard_full_flow_produces_expected_config` from:

```python
    responses = iter(
        [
            "",  # generation mode -> default both
            "",  # cicd platform -> default github_actions
            "3",  # performance tool -> jmeter
            "performance/checkout.jmx",  # jmeter test plan path
            "",  # docker image -> blank (uses default)
            "",  # manual pipeline name -> default
            "",  # manual pipeline timeout -> default 240
            "y",  # add environments now?
            "qa",  # environment key
            "env-qa",  # environment identifier
            "",  # blank key ends environment collection
            "y",  # add scenarios now?
            "checkout_smoke",  # scenario key
            "SC-1",  # scenario identifier
            "",  # blank key ends scenario collection
            "y",  # add automated jobs now?
            "nightly-load",  # automated job name
            "",  # environment ref -> default qa
            "",  # scenario ref -> default checkout_smoke
            "",  # timeout -> default 240
            "",  # blank name ends automated job collection
            "1",  # pre-run checks -> select option 1 (verify_scenario_exists)
        ]
    )
```

to:

```python
    responses = iter(
        [
            "",  # generation mode -> default both
            "",  # cicd platform -> default github_actions
            "3",  # performance tool -> jmeter
            "performance/checkout.jmx",  # jmeter test plan path
            "",  # docker image -> blank (uses default)
            "",  # manual pipeline name -> default
            "",  # manual pipeline timeout -> default 240
            "y",  # add environments now?
            "qa",  # environment key
            "env-qa",  # environment identifier
            "checkout_smoke",  # scenario key (nested under qa)
            "SC-1",  # scenario identifier
            "",  # blank scenario key ends this environment's scenario collection
            "",  # blank environment key ends environment collection
            "y",  # add automated jobs now?
            "nightly-load",  # automated job name
            "",  # environment ref -> default qa
            "",  # scenario ref -> default checkout_smoke
            "",  # timeout -> default 240
            "",  # blank name ends automated job collection
            "1",  # pre-run checks -> select option 1 (verify_scenario_exists)
        ]
    )
```

Then replace these two assertion lines:

```python
    assert config["catalog"]["environments"] == [{"key": "qa", "identifier": "env-qa"}]
    assert config["catalog"]["scenarios"] == [{"key": "checkout_smoke", "identifier": "SC-1"}]
```

with:

```python
    assert config["catalog"]["environments"] == [
        {
            "key": "qa",
            "identifier": "env-qa",
            "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}],
        }
    ]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_wizard_resumable_list.py tests/test_wizard_end_to_end.py -v`
Expected: FAIL — `_prompt_environments_section` doesn't exist yet (`ImportError`); the end-to-end test's response sequence doesn't match the current wizard's separate "Add scenarios now?" prompt, so responses get consumed out of order.

- [ ] **Step 4: Replace the catalog-prompting functions in `wizard/flow.py`**

In `src/pipeline_generator/wizard/flow.py`, replace `_step_catalog`:

```python
def _step_catalog(config: dict, output_path: Path) -> None:
    _section(5, "Environments and scenarios")
    tool_type = config["tool"]["type"]
    config["catalog"]["environments"] = _prompt_catalog_section(
        "environment", config["catalog"]["environments"], tool_type
    )
    config["catalog"]["scenarios"] = _prompt_catalog_section(
        "scenario", config["catalog"]["scenarios"], tool_type
    )
    save_config(output_path, config)
```

with:

```python
def _step_catalog(config: dict, output_path: Path) -> None:
    _section(5, "Environments and scenarios")
    tool_type = config["tool"]["type"]
    config["catalog"]["environments"] = _prompt_environments_section(
        config["catalog"]["environments"], tool_type
    )
    save_config(output_path, config)
```

Replace `_prompt_catalog_items` and `_prompt_catalog_section`:

```python
def _prompt_catalog_items(kind: str, tool_type: str) -> list[dict]:
    items: list[dict] = []
    identifier_label = CATALOG_IDENTIFIER_PROMPTS.get(tool_type, {}).get(kind, f"{kind} remote identifier")
    print(f"Enter {kind}s. Leave key blank to finish.")
    while True:
        key = prompt_text(f"{kind} key", allow_blank=True)
        if not key:
            break
        identifier = prompt_text(identifier_label, default=TODO_VALUE) or TODO_VALUE
        items.append({"key": key, "identifier": identifier})
    return items
```

and

```python
def _prompt_catalog_section(kind: str, existing: list[dict], tool_type: str) -> list[dict]:
    return _prompt_resumable_list(
        f"{kind}s", existing, [item["key"] for item in existing], lambda: _prompt_catalog_items(kind, tool_type)
    )
```

with:

```python
def _prompt_scenario_items(tool_type: str) -> list[dict]:
    items: list[dict] = []
    identifier_label = CATALOG_IDENTIFIER_PROMPTS.get(tool_type, {}).get("scenario", "scenario remote identifier")
    print("Enter scenarios for this environment. Leave key blank to finish.")
    while True:
        key = prompt_text("scenario key", allow_blank=True)
        if not key:
            break
        identifier = prompt_text(identifier_label, default=TODO_VALUE) or TODO_VALUE
        items.append({"key": key, "identifier": identifier})
    return items


def _prompt_environment_items(tool_type: str) -> list[dict]:
    items: list[dict] = []
    identifier_label = CATALOG_IDENTIFIER_PROMPTS.get(tool_type, {}).get(
        "environment", "environment remote identifier"
    )
    print("Enter environments. Leave key blank to finish.")
    while True:
        key = prompt_text("environment key", allow_blank=True)
        if not key:
            break
        identifier = prompt_text(identifier_label, default=TODO_VALUE) or TODO_VALUE
        scenarios = _prompt_scenario_items(tool_type)
        items.append({"key": key, "identifier": identifier, "scenarios": scenarios})
    return items


def _prompt_environments_section(existing: list[dict], tool_type: str) -> list[dict]:
    return _prompt_resumable_list(
        "environments", existing, [item["key"] for item in existing], lambda: _prompt_environment_items(tool_type)
    )
```

(`_prompt_resumable_list` itself is unchanged — it's generic over any `list[dict]`.)

- [ ] **Step 5: Update `_prompt_automated_jobs` to scope scenario choices to the chosen environment**

In `src/pipeline_generator/wizard/flow.py`, replace:

```python
def _prompt_automated_jobs(config: dict) -> list[dict]:
    jobs: list[dict] = []
    environment_keys = [item["key"] for item in config["catalog"]["environments"]]
    scenario_keys = [item["key"] for item in config["catalog"]["scenarios"]]
    print("Enter automated jobs. Leave name blank to finish.")
    while True:
        name = prompt_text("Automated job name", allow_blank=True)
        if not name:
            break
        if environment_keys:
            environment_ref = prompt_choice("Environment key", environment_keys, default=environment_keys[0])
        else:
            environment_ref = prompt_text("Environment key", default=TODO_VALUE) or TODO_VALUE
        if scenario_keys:
            scenario_ref = prompt_choice("Scenario key", scenario_keys, default=scenario_keys[0])
        else:
            scenario_ref = prompt_text("Scenario key", default=TODO_VALUE) or TODO_VALUE
        timeout_minutes = prompt_positive_int("Timeout minutes", default=240)
        jobs.append(
            {
                "name": name,
                "enabled": True,
                "environment_ref": environment_ref,
                "scenario_ref": scenario_ref,
                "timeout_minutes": timeout_minutes,
            }
        )
    return jobs
```

with:

```python
def _prompt_automated_jobs(config: dict) -> list[dict]:
    jobs: list[dict] = []
    environments = config["catalog"]["environments"]
    environment_keys = [item["key"] for item in environments]
    print("Enter automated jobs. Leave name blank to finish.")
    while True:
        name = prompt_text("Automated job name", allow_blank=True)
        if not name:
            break
        if environment_keys:
            environment_ref = prompt_choice("Environment key", environment_keys, default=environment_keys[0])
        else:
            environment_ref = prompt_text("Environment key", default=TODO_VALUE) or TODO_VALUE
        environment_entry = next((item for item in environments if item["key"] == environment_ref), None)
        scenario_keys = [item["key"] for item in environment_entry["scenarios"]] if environment_entry else []
        if scenario_keys:
            scenario_ref = prompt_choice("Scenario key", scenario_keys, default=scenario_keys[0])
        else:
            scenario_ref = prompt_text("Scenario key", default=TODO_VALUE) or TODO_VALUE
        timeout_minutes = prompt_positive_int("Timeout minutes", default=240)
        jobs.append(
            {
                "name": name,
                "enabled": True,
                "environment_ref": environment_ref,
                "scenario_ref": scenario_ref,
                "timeout_minutes": timeout_minutes,
            }
        )
    return jobs
```

- [ ] **Step 6: Update `_print_summary`'s scenario count**

In `src/pipeline_generator/wizard/flow.py`, replace:

```python
def _print_summary(config: dict) -> None:
    setup = config["setup"]
    print("\nSetup summary")
    print(f"  ID: {setup['id']}")
    print(f"  CI/CD: {config['cicd']['type']}")
    print(f"  Tool: {config['tool']['type']}")
    print(f"  Manual pipeline: {'enabled' if config['manual_pipeline']['enabled'] else 'disabled'}")
    print(f"  Environments: {len(config['catalog']['environments'])}")
    print(f"  Scenarios: {len(config['catalog']['scenarios'])}")
    print(f"  Automated jobs: {len(config['automated_jobs'])}")
```

with:

```python
def _print_summary(config: dict) -> None:
    setup = config["setup"]
    environments = config["catalog"]["environments"]
    scenario_count = sum(len(item.get("scenarios", [])) for item in environments)
    print("\nSetup summary")
    print(f"  ID: {setup['id']}")
    print(f"  CI/CD: {config['cicd']['type']}")
    print(f"  Tool: {config['tool']['type']}")
    print(f"  Manual pipeline: {'enabled' if config['manual_pipeline']['enabled'] else 'disabled'}")
    print(f"  Environments: {len(environments)}")
    print(f"  Scenarios: {scenario_count}")
    print(f"  Automated jobs: {len(config['automated_jobs'])}")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/test_wizard_resumable_list.py tests/test_wizard_end_to_end.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 8: Commit**

```bash
git add src/pipeline_generator/wizard/flow.py tests/test_wizard_resumable_list.py tests/test_wizard_end_to_end.py
git commit -m "feat: wizard collects each environment's scenarios inline

Step 5 no longer asks 'Add scenarios now?' as a separate flat pass --
adding a new environment immediately continues into collecting its
scenarios before moving to the next environment. Automated job scenario
choices (Step 6) are now filtered to whichever environment was picked,
instead of offering every scenario across every environment."
```

---

## Task 5: Examples migration + full regression pass + docs

**Files:**
- Modify: `examples/*/customer.yaml` (all 9)
- Modify: `tests/test_generate_assets_regeneration.py`
- Modify: `README.md`, `CLAUDE.md`, `docs/pipeline-generator-user-guide.md`, `docs/current-state-and-readiness-plan.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1-4. No new interfaces produced — this task makes the whole suite (`pytest`, no path filter) green.

- [ ] **Step 1: Fix `test_generate_assets_regeneration.py`'s catalog override**

In `tests/test_generate_assets_regeneration.py`, replace:

```python
    config["catalog"]["environments"] = [{"key": "qa", "identifier": "env-qa"}]
    config["catalog"]["scenarios"] = [{"key": "checkout_smoke", "identifier": "SC-1"}]
```

with:

```python
    config["catalog"]["environments"] = [
        {"key": "qa", "identifier": "env-qa", "scenarios": [{"key": "checkout_smoke", "identifier": "SC-1"}]}
    ]
```

- [ ] **Step 2: Run the full suite to see exactly what's still broken**

Run: `pytest -q`
Expected: FAIL — only `tests/test_example_configs.py` and `tests/test_cli.py` should still be failing at this point (both depend on the 9 example YAML files, not yet migrated). Everything else from Tasks 1-4 should already be green. If anything else is still red, stop and diagnose before continuing — it means an earlier task's step was missed.

- [ ] **Step 3: Migrate all 9 example configs to the nested catalog shape**

Run this from the project root:

```bash
python3 - <<'EOF'
import yaml
import glob

# For the two multi-environment LoadRunner examples: map each old
# per-environment-suffixed scenario key to (new shared key, owning environment).
LOADRUNNER_SCENARIO_MAP = {
    "checkout_smoke_qa": ("checkout_smoke", "qa"),
    "checkout_smoke_staging": ("checkout_smoke", "staging"),
    "browse_baseline_qa": ("browse_baseline", "qa"),
    "browse_baseline_staging": ("browse_baseline", "staging"),
}

for path in sorted(glob.glob("examples/*/customer.yaml")):
    with open(path) as f:
        data = yaml.safe_load(f)

    old_environments = data["catalog"]["environments"]
    old_scenarios = data["catalog"].pop("scenarios")

    if len(old_environments) == 1:
        # Single environment: nest every scenario under it directly, keys unchanged.
        old_environments[0]["scenarios"] = old_scenarios
    else:
        # Multi-environment (the two LoadRunner matrix examples): consolidate
        # each old per-environment-suffixed scenario key into a shared key
        # nested under its owning environment.
        by_env = {env["key"]: env for env in old_environments}
        for env in old_environments:
            env["scenarios"] = []
        for scenario in old_scenarios:
            new_key, env_key = LOADRUNNER_SCENARIO_MAP[scenario["key"]]
            by_env[env_key]["scenarios"].append({"key": new_key, "identifier": scenario["identifier"]})
        for job in data.get("automated_jobs", []):
            old_ref = job["scenario_ref"]
            if old_ref in LOADRUNNER_SCENARIO_MAP:
                job["scenario_ref"] = LOADRUNNER_SCENARIO_MAP[old_ref][0]

    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=False)
    print(f"migrated {path}")
EOF
```

Expected output: 9 lines, one `migrated examples/.../customer.yaml` per file.

- [ ] **Step 4: Manually verify the two LoadRunner matrix examples**

Run: `cat examples/github-loadrunner/customer.yaml examples/jenkins-loadrunner/customer.yaml`

Confirm each shows two environments (`qa`, `staging`), each with two nested scenarios (`checkout_smoke`, `browse_baseline`), each scenario's `identifier` pointing at the correct original `.lrs` path (`checkout_smoke_qa.lrs` under `qa`'s `checkout_smoke`, `checkout_smoke_staging.lrs` under `staging`'s `checkout_smoke`, etc.), and the `automated_jobs[0].scenario_ref` reading `checkout_smoke` (not `checkout_smoke_qa`).

- [ ] **Step 5: Run the full suite to verify everything passes**

Run: `pytest -q`
Expected: PASS (entire suite, no failures)

- [ ] **Step 6: Update docs**

In `README.md`:
- Find the wizard walkthrough / config-shape example YAML block(s) showing `catalog.environments`/`catalog.scenarios` as two separate top-level lists. Update them to the nested shape, matching the style already used elsewhere in this file (e.g. the LoadRunner example under "Config Shape").
- Update the "Interactive Wizard" section's description of Step 5/6 to mention that adding an environment now immediately collects its scenarios, and that automated job scenario choices are scoped to the chosen environment.

In `CLAUDE.md`:
- Update the `catalog`/wizard description under the `config/` and `wizard/` bullets to describe the nested `environments[].scenarios[]` shape instead of two flat lists.
- Update the `scripts.py:render_tool_script` paragraph to describe the `--test-case` CLI flag and the six combined-key resolver functions instead of `--environment`/`--scenario` and four independently-keyed ones.

In `docs/pipeline-generator-user-guide.md`:
- Update Step 5's description (the "Environments and scenarios" section) to describe the nested collection flow.
- Update Step 6's description to note scenario choices are scoped to the chosen environment.
- Update every `catalog:` YAML example block to the nested shape.
- Update any prose describing `scripts/run-<tool_type>.sh --environment/--scenario` to `--test-case`.

In `docs/current-state-and-readiness-plan.md`:
- Update the `catalog` description and any `scripts/run-<tool_type>.sh` invocation examples to match the new nested shape and `--test-case` flag.

For each of these four files, after editing, run:

```bash
grep -rn "catalog\[.scenarios.\]\|catalog\.scenarios\|--environment \"\$ENVIRONMENT\"\|--scenario \"\$SCENARIO\"" README.md CLAUDE.md docs/pipeline-generator-user-guide.md docs/current-state-and-readiness-plan.md
```

Expected: no output (any match means a stale reference to the old flat shape or old CLI flags was missed).

- [ ] **Step 7: Add a CHANGELOG entry**

In `CHANGELOG.md`, add to the top of the `## [Unreleased]` section:

```markdown
- `catalog.scenarios` is removed as a flat top-level list; scenarios now
  nest under their owning environment (`catalog.environments[].scenarios[]`).
  A scenario key only needs to be unique within its environment, so the
  same key can mean something different per environment (e.g. `checkout_smoke`
  under both `qa` and `staging`, each with its own identifier) -- retiring
  the `_qa`/`_staging` suffix workaround the examples previously needed.
  The manual pipeline's generated trigger UI collapses from two independent
  environment/scenario dropdowns into one dropdown listing only valid pairs,
  so a mismatched combination (e.g. a QA-only LoadRunner scenario run
  against `staging`) is no longer selectable at all. `scripts/run-<tool_type>.sh`
  takes `--test-case "<environment>: <scenario>"` instead of separate
  `--environment`/`--scenario` flags; `run-summary.json`'s schema is
  unchanged. This is a breaking schema change with no migration shim --
  existing `customer.yaml` files need their `catalog` section rewritten by
  hand to the nested shape.
```

- [ ] **Step 8: Run the full suite one more time, then commit**

Run: `pytest -q`
Expected: PASS (entire suite)

```bash
git add examples/ tests/test_generate_assets_regeneration.py README.md CLAUDE.md \
  docs/pipeline-generator-user-guide.md docs/current-state-and-readiness-plan.md CHANGELOG.md
git commit -m "docs: migrate example configs and docs to nested catalog shape

All 9 example customer.yaml files rewritten to catalog.environments[].scenarios[].
The two LoadRunner examples (github-loadrunner, jenkins-loadrunner) consolidate
their 2x2 environment x scenario matrix down to two shared scenario keys
(checkout_smoke, browse_baseline) nested per environment, retiring the
_qa/_staging suffix naming workaround this whole redesign exists to replace.
README, CLAUDE.md, and the user guide updated to match; full test suite green."
```

---

## Self-Review Notes

- **Spec coverage:** Section A (schema) → Task 1. Section B (wizard) → Task 4. Section C (script mechanism) → Task 2. Section D listed as "generated script" is the same as Section C in the spec numbering — covered. Section E (renderers) → Task 3. Section F (validation) → Task 1. "Known limitation" (combined-value collision) — no task needed, it's an accepted limitation, not a requirement to implement. "Migration" → Task 5. "Testing" section's bullet list maps one-to-one onto the Test file lists in each task above.
- **Placeholder scan:** no TBD/TODO markers; every step shows full before/after code rather than describing changes in prose only.
- **Type consistency:** `build_test_case_value(environment_key: str, scenario_key: str) -> str` is defined once in Task 1 Step 8 and its exact name/signature is reused verbatim in Task 2 (test assertions only), Task 3 (both renderer production code and tests), and referenced in the Global Constraints section. `GenericPipelinePackage.environment_keys`/`.scenario_keys` defined in Task 1 Step 8, consumed in Task 2 Step 6 with matching field names. `_prompt_environments_section`/`_prompt_environment_items`/`_prompt_scenario_items` names introduced in Task 4 Step 4 are consistent between the production-code step and the Step 1 test file that imports them.
