# Generic Naming, Header Filter, and JMeter Version — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `Project_Product_METHOD_segment` naming scheme, the hardcoded New Relic header filter, and the hardcoded JMeter version with configurable equivalents, without changing default output for a caller that still supplies `project`/`product`.

**Architecture:** A new `naming.py` module owns template parsing/validation/rendering. `converter_config.py` grows a `NamingConfig` (naming templates), a new `filters.skip_header_value_contains` list, and `jmeter.version`. `har_requests.process_har_entries` takes a `template_vars: Dict[str, str]` dict instead of `project, product` and renders filenames via `naming.render`. Both CLIs (`har_to_jmx.py`, `build_scenario_jmx.py`) replace positional `project`/`product` with repeatable `--var key=value` flags and validate them up front with `naming.validate_vars` before touching any HAR entries.

**Tech Stack:** Python 3 standard library only (`string.Formatter`, `argparse`, `dataclasses`, `unittest`). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-10-generic-naming-and-filters-design.md`

## Global Constraints

- Python 3 standard library only — no third-party dependencies (spec: Non-goals; existing project-wide rule).
- Default behavior must stay byte-identical to today's output when a caller supplies `project`/`product` via `--var` (or positionally, pre-change) and no config file (spec: Goals).
- Every new CLI failure mode prints one clear message to stderr and exits 1, following the file's existing `print(..., file=sys.stderr); sys.exit(1)` pattern (spec: Error handling). Malformed `--var` (no `=`) is the one exception — it's a standard argparse usage error (exit 2).
- Templates support only plain `{name}` placeholders — no attribute/index access, no positional, no conversion/format specs (spec: `naming.py` section).
- `naming.render`/`naming.validate_vars` reserved-key handling: `har_to_jmx.py` reserves `{"method", "segment"}`; `build_scenario_jmx.py` reserves `{"scenario_name"}` for its scenario template and `{"method", "segment"}` for the fragment template it also renders internally via `process_har_entries` (spec: `naming.py` section, CLI changes section).
- Run `python3 -m unittest discover -s tests` after every task; it must pass with clean output before moving on (project convention, see `CLAUDE.md`).

---

### Task 1: `naming.py` — template parsing, validation, rendering

**Files:**
- Create: `naming.py`
- Modify: `tests/test_harconverter.py` (add imports + `NamingTests` class)

**Interfaces:**
- Consumes: nothing (standalone module, stdlib only).
- Produces:
  - `naming.required_fields(template: str) -> Set[str]`
  - `naming.validate_vars(template: str, provided: Dict[str, str], reserved: Set[str]) -> None` (raises `ValueError`)
  - `naming.render(template: str, **fields: str) -> str`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_harconverter.py`'s import block (top of file, alongside the existing `from har_requests import ...` line):

```python
from naming import render, required_fields, validate_vars
```

Add a new test class, placed after `HarLoadingTests` and before `FilteringAndNamingTests`:

```python
class NamingTests(unittest.TestCase):
    def test_required_fields_returns_placeholder_names(self):
        self.assertEqual(
            required_fields("{project}_{product}_{method}_{segment}"),
            {"project", "product", "method", "segment"},
        )

    def test_required_fields_rejects_attribute_access(self):
        with self.assertRaises(ValueError):
            required_fields("{project.name}")

    def test_required_fields_rejects_format_spec(self):
        with self.assertRaises(ValueError):
            required_fields("{project:>10}")

    def test_required_fields_rejects_positional(self):
        with self.assertRaises(ValueError):
            required_fields("{0}")

    def test_render_substitutes_all_fields(self):
        self.assertEqual(
            render(
                "{project}_{product}_{method}_{segment}",
                project="Abbot",
                product="Merlin",
                method="GET",
                segment="users",
            ),
            "Abbot_Merlin_GET_users",
        )

    def test_validate_vars_raises_on_missing_field(self):
        with self.assertRaises(ValueError) as ctx:
            validate_vars(
                "{project}_{product}_{method}_{segment}",
                {"project": "Abbot"},
                reserved={"method", "segment"},
            )
        self.assertIn("product", str(ctx.exception))

    def test_validate_vars_raises_on_reserved_conflict(self):
        with self.assertRaises(ValueError) as ctx:
            validate_vars("{method}_{segment}", {"method": "GET"}, reserved={"method", "segment"})
        self.assertIn("method", str(ctx.exception))

    def test_validate_vars_passes_when_satisfied(self):
        validate_vars(
            "{project}_{product}_{method}_{segment}",
            {"project": "Abbot", "product": "Merlin"},
            reserved={"method", "segment"},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_harconverter.NamingTests -v`
Expected: `ModuleNotFoundError: No module named 'naming'` (or `ImportError`) — the module doesn't exist yet.

- [ ] **Step 3: Write `naming.py`**

```python
import string
from typing import Dict, Set


def required_fields(template: str) -> Set[str]:
    """
    Field names referenced by a template's {placeholders}. Only plain
    {name} placeholders are supported -- no attribute/index access
    ({a.b}, {a[0]}), no positional ({0}), no conversion/format specs
    ({a!s}, {a:>10}).
    """
    fields: Set[str] = set()
    for _literal_text, field_name, format_spec, conversion in string.Formatter().parse(template):
        if field_name is None:
            continue
        if not field_name.isidentifier() or format_spec or conversion:
            raise ValueError(f"unsupported placeholder in template: {{{field_name}}}")
        fields.add(field_name)
    return fields


def validate_vars(template: str, provided: Dict[str, str], reserved: Set[str]) -> None:
    """
    Raises ValueError if `provided` sets a reserved key, or if `template`
    references a field that is neither in `provided` nor in `reserved`.
    """
    reserved_conflicts = sorted(set(provided) & reserved)
    if reserved_conflicts:
        raise ValueError(f"--var cannot set reserved name(s): {', '.join(reserved_conflicts)}")

    missing = sorted(required_fields(template) - set(provided) - reserved)
    if missing:
        raise ValueError(
            f"template {template!r} is missing value(s) for: {', '.join(missing)}. "
            "Supply them with --var key=value."
        )


def render(template: str, **fields: str) -> str:
    return template.format(**fields)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_harconverter.NamingTests -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: all tests pass (existing tests untouched by this task).

- [ ] **Step 6: Commit**

```bash
git add naming.py tests/test_harconverter.py
git commit -m "feat: add naming.py for template field validation and rendering"
```

---

### Task 2: Config schema — `NamingConfig`, `skip_header_value_contains`, `jmeter.version`

**Files:**
- Modify: `converter_config.py`
- Modify: `tests/test_harconverter.py` (add imports + `ConverterConfigTests` class)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `converter_config.NamingConfig` frozen dataclass: `template: str = "{project}_{product}_{method}_{segment}"`, `scenario_template: str = "{project}_{product}_{scenario_name}"`
  - `converter_config.ConverterConfig.naming: NamingConfig`
  - `converter_config.FilterConfig.skip_header_value_contains: List[str]` (default `[]`, populated with `["nrjs"]` by `default_config()`)
  - `converter_config.JMeterConfig.version: str = "5.6.0"`

- [ ] **Step 1: Write the failing tests**

Add `default_config` to the existing `from converter_config import load_config, merge_host_maps` line in `tests/test_harconverter.py`, making it:

```python
from converter_config import default_config, load_config, merge_host_maps
```

Add a new test class, placed after `NamingTests` and before `FilteringAndNamingTests`:

```python
class ConverterConfigTests(unittest.TestCase):
    def test_default_config_has_expected_naming_and_version_defaults(self):
        config = default_config()
        self.assertEqual(config.naming.template, "{project}_{product}_{method}_{segment}")
        self.assertEqual(config.naming.scenario_template, "{project}_{product}_{scenario_name}")
        self.assertEqual(config.jmeter.version, "5.6.0")
        self.assertIn("nrjs", config.filters.skip_header_value_contains)

    def test_config_json_can_override_naming_and_jmeter_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "naming": {
                            "template": "{method}_{segment}",
                            "scenario_template": "{scenario_name}",
                        },
                        "jmeter": {"version": "5.5.0"},
                        "filters": {"skip_header_value_contains": ["x-debug"]},
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_path)

        self.assertEqual(config.naming.template, "{method}_{segment}")
        self.assertEqual(config.naming.scenario_template, "{scenario_name}")
        self.assertEqual(config.jmeter.version, "5.5.0")
        self.assertIn("x-debug", config.filters.skip_header_value_contains)
        self.assertIn("nrjs", config.filters.skip_header_value_contains)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_harconverter.ConverterConfigTests -v`
Expected: FAIL — `AttributeError: 'ConverterConfig' object has no attribute 'naming'` (or similar for `jmeter.version` / `skip_header_value_contains`).

- [ ] **Step 3: Add `NamingConfig` and extend `FilterConfig`/`JMeterConfig`/`ConverterConfig`**

In `converter_config.py`, after the existing `HeaderMaskRule` dataclass (before `FilterConfig`), add:

```python
@dataclass(frozen=True)
class NamingConfig:
    template: str = "{project}_{product}_{method}_{segment}"
    scenario_template: str = "{project}_{product}_{scenario_name}"
```

In `FilterConfig`, add a new field after `keep_url_contains`:

```python
    keep_url_contains: List[str] = field(default_factory=list)
    skip_header_value_contains: List[str] = field(default_factory=list)
```

In `JMeterConfig`, add a new field:

```python
@dataclass(frozen=True)
class JMeterConfig:
    cookie_manager: bool = False
    cache_manager: bool = False
    http_defaults: bool = False
    http_defaults_protocol: str = "${__P(protocol,https)}"
    http_defaults_domain: str = "${__P(hostName)}"
    http_defaults_port: str = ""
    version: str = "5.6.0"
```

In `ConverterConfig`, add a `naming` field:

```python
@dataclass(frozen=True)
class ConverterConfig:
    filters: FilterConfig
    hosts: Dict[str, str]
    header_masks: List[HeaderMaskRule]
    jmeter: JMeterConfig
    naming: NamingConfig
```

- [ ] **Step 4: Wire the new field into `default_config()` and `merge_config()`**

In `default_config()`, add `skip_header_value_contains=["nrjs"]` to the `FilterConfig(...)` call (after `skip_url_contains=["nrjs", "nr-data.net"],`), and add `naming=NamingConfig(),` after `jmeter=JMeterConfig(),`:

```python
def default_config() -> ConverterConfig:
    return ConverterConfig(
        filters=FilterConfig(
            skip_methods=["OPTIONS"],
            skip_host_contains=list(TRACKER_HOSTS),
            skip_exact_hosts=list(FONT_HOSTS),
            skip_extensions=list(STATIC_EXTENSIONS),
            skip_final_segments=sorted(STATIC_SEGMENTS),
            skip_url_contains=["nrjs", "nr-data.net"],
            skip_header_value_contains=["nrjs"],
            keep_url_contains=[],
        ),
        hosts={},
        header_masks=[
            HeaderMaskRule(
                name="Authorization",
                prefix="Bearer ",
                replacement="Bearer ${TOKEN}",
            )
        ],
        jmeter=JMeterConfig(),
        naming=NamingConfig(),
    )
```

In `merge_config()`, add a `naming` line:

```python
def merge_config(base: ConverterConfig, raw: Dict[str, Any]) -> ConverterConfig:
    return ConverterConfig(
        filters=_merge_filters(base.filters, _object(raw, "filters")),
        hosts=_merge_hosts(base.hosts, _object(raw, "hosts")),
        header_masks=_merge_header_masks(base.header_masks, _object(raw, "headers")),
        jmeter=_merge_jmeter(base.jmeter, _object(raw, "jmeter")),
        naming=_merge_naming(base.naming, _object(raw, "naming")),
    )
```

In `_merge_filters()`, add a `skip_header_value_contains` line (after `keep_url_contains`):

```python
def _merge_filters(base: FilterConfig, raw: Dict[str, Any]) -> FilterConfig:
    return FilterConfig(
        skip_methods=_merged_list(base.skip_methods, raw.get("skip_methods"), upper=True),
        skip_host_contains=_merged_list(base.skip_host_contains, raw.get("skip_host_contains"), lower=True),
        skip_exact_hosts=_merged_list(base.skip_exact_hosts, raw.get("skip_exact_hosts"), lower=True),
        skip_extensions=_merged_list(base.skip_extensions, raw.get("skip_extensions"), lower=True),
        skip_final_segments=_merged_list(base.skip_final_segments, raw.get("skip_final_segments"), lower=True),
        skip_url_contains=_merged_list(base.skip_url_contains, raw.get("skip_url_contains"), lower=True),
        keep_url_contains=_merged_list(base.keep_url_contains, raw.get("keep_url_contains"), lower=True),
        skip_header_value_contains=_merged_list(
            base.skip_header_value_contains, raw.get("skip_header_value_contains"), lower=True
        ),
    )
```

- [ ] **Step 5: Generalize `_string()`'s error-message section and add `_merge_naming()`**

Change `_string()`'s signature to accept a `section` parameter (defaulting to `"jmeter"` so the three existing call sites in `_merge_jmeter` need no changes):

```python
def _string(raw: Dict[str, Any], key: str, default: str, section: str = "jmeter") -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{section}.{key} must be a string")
    return value
```

Add `_merge_jmeter()`'s new `version` field:

```python
def _merge_jmeter(base: JMeterConfig, raw: Dict[str, Any]) -> JMeterConfig:
    return JMeterConfig(
        cookie_manager=_bool(raw, "cookie_manager", base.cookie_manager),
        cache_manager=_bool(raw, "cache_manager", base.cache_manager),
        http_defaults=_bool(raw, "http_defaults", base.http_defaults),
        http_defaults_protocol=_string(raw, "http_defaults_protocol", base.http_defaults_protocol),
        http_defaults_domain=_string(raw, "http_defaults_domain", base.http_defaults_domain),
        http_defaults_port=_string(raw, "http_defaults_port", base.http_defaults_port),
        version=_string(raw, "version", base.version),
    )
```

Add a new `_merge_naming()` function, placed after `_merge_jmeter()`:

```python
def _merge_naming(base: NamingConfig, raw: Dict[str, Any]) -> NamingConfig:
    return NamingConfig(
        template=_string(raw, "template", base.template, section="naming"),
        scenario_template=_string(raw, "scenario_template", base.scenario_template, section="naming"),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_harconverter.ConverterConfigTests -v`
Expected: both tests PASS.

- [ ] **Step 7: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: all tests pass — every existing `ConverterConfig`/`FilterConfig`/`JMeterConfig` construction site (`default_config()`, `merge_config()`) still works since all new fields are additive with defaults.

- [ ] **Step 8: Commit**

```bash
git add converter_config.py tests/test_harconverter.py
git commit -m "feat: add naming, skip_header_value_contains, and jmeter.version config fields"
```

---

### Task 3: Generalize the hardcoded New Relic header filter

**Files:**
- Modify: `har_requests.py:218-220`
- Modify: `tests/test_harconverter.py` (add two tests to `FilteringAndNamingTests`)

**Interfaces:**
- Consumes: `config.filters.skip_header_value_contains: List[str]` (Task 2).
- Produces: `skip_reason()` now returns `"skipped header value substring"` (was `"New Relic header"`) when a header value matches; the match set is config-driven instead of hardcoded `"nrjs"`.

- [ ] **Step 1: Write the failing tests**

Add to `FilteringAndNamingTests` in `tests/test_harconverter.py`, after `test_form_encoded_params_without_text_are_captured_as_body`:

```python
    def test_header_value_filter_skips_matching_requests(self):
        entries = [
            har_entry(
                "https://example.com/api/beacon",
                headers=[{"name": "X-Trace", "value": "nrjs-session-123"}],
            ),
            har_entry("https://example.com/api/users"),
        ]

        processed = process_har_entries(entries, "Project", "Product")

        self.assertEqual([request.url for request in processed.requests], ["https://example.com/api/users"])
        self.assertEqual(processed.skipped[0].reason, "skipped header value substring")

    def test_header_value_filter_is_config_driven(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"filters": {"skip_header_value_contains": ["x-debug-token"]}}),
                encoding="utf-8",
            )
            config = load_config(config_path)

        entries = [
            har_entry(
                "https://example.com/api/beacon",
                headers=[{"name": "X-Debug", "value": "x-debug-token-abc"}],
            ),
            har_entry("https://example.com/api/users"),
        ]
        processed = process_har_entries(entries, "Project", "Product", config)

        self.assertEqual([request.url for request in processed.requests], ["https://example.com/api/users"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_harconverter.FilteringAndNamingTests.test_header_value_filter_skips_matching_requests tests.test_harconverter.FilteringAndNamingTests.test_header_value_filter_is_config_driven -v`
Expected: `test_header_value_filter_skips_matching_requests` FAILs on the reason-string assertion (`AssertionError: 'New Relic header' != 'skipped header value substring'`); `test_header_value_filter_is_config_driven` FAILs because the beacon request isn't filtered at all (custom `x-debug-token` isn't recognized yet).

- [ ] **Step 3: Replace the hardcoded check in `skip_reason()`**

In `har_requests.py`, replace:

```python
    headers = req.get("headers", [])
    if isinstance(headers, list) and any("nrjs" in str(h.get("value", "")).lower() for h in headers if isinstance(h, dict)):
        return "New Relic header"
```

with:

```python
    headers = req.get("headers", [])
    if isinstance(headers, list):
        header_values = [str(h.get("value", "")).lower() for h in headers if isinstance(h, dict)]
        if any(skip in value for value in header_values for skip in config.filters.skip_header_value_contains):
            return "skipped header value substring"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_harconverter.FilteringAndNamingTests -v`
Expected: all tests in the class PASS, including the two new ones.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: all tests pass. (No existing test asserts the literal string `"New Relic header"`, so this rename doesn't break anything else — confirmed by inspection of `tests/test_harconverter.py` before this task.)

- [ ] **Step 6: Commit**

```bash
git add har_requests.py tests/test_harconverter.py
git commit -m "fix: make the New Relic header filter config-driven instead of hardcoded"
```

---

### Task 4: Thread `jmeter.version` through the shared XML scaffold

**Files:**
- Modify: `jmx_xml.py:26-70`
- Modify: `jmx_generator.py:143`
- Modify: `build_scenario_jmx.py` (function signature, `main()`)
- Modify: `tests/test_harconverter.py` (add two tests to `JmxGenerationTests`)

**Interfaces:**
- Consumes: `config.jmeter.version` (Task 2).
- Produces:
  - `jmx_xml.build_test_plan_scaffold(name: str, jmeter_version: str) -> Tuple[ET.Element, ET.Element]` (was `(name: str)`)
  - `build_scenario_jmx.build_scenario_jmx(plan_name: str, include_files: List[str], config: Optional[ConverterConfig] = None) -> str` (was `(plan_name, include_files)`)

- [ ] **Step 1: Write the failing tests**

Add to `JmxGenerationTests` in `tests/test_harconverter.py`, after `test_config_host_mapping_header_mask_and_jmeter_components`:

```python
    def test_default_jmeter_version_is_5_6_0(self):
        xml = build_jmx_xml("Test_GET_users", "GET", "https://api.example.com/users", [], None, {})
        root = ET.fromstring(xml)
        self.assertEqual(root.get("jmeter"), "5.6.0")

    def test_config_can_override_jmeter_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps({"jmeter": {"version": "5.5.0"}}), encoding="utf-8")
            config = load_config(config_path)

        xml = build_jmx_xml("Test_GET_users", "GET", "https://api.example.com/users", [], None, {}, config)
        root = ET.fromstring(xml)
        self.assertEqual(root.get("jmeter"), "5.5.0")

        scenario_xml = build_scenario_jmx("Test_Scenario", [], config)
        scenario_root = ET.fromstring(scenario_xml)
        self.assertEqual(scenario_root.get("jmeter"), "5.5.0")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_harconverter.JmxGenerationTests.test_default_jmeter_version_is_5_6_0 tests.test_harconverter.JmxGenerationTests.test_config_can_override_jmeter_version -v`
Expected: `test_default_jmeter_version_is_5_6_0` PASSes already (5.6.0 is still the hardcoded literal); `test_config_can_override_jmeter_version` FAILs with `AssertionError: '5.6.0' != '5.5.0'` and/or `TypeError: build_scenario_jmx() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Update `jmx_xml.build_test_plan_scaffold`**

In `jmx_xml.py`, change the signature and the literal:

```python
def build_test_plan_scaffold(name: str, jmeter_version: str) -> Tuple[ET.Element, ET.Element]:
    """
    Builds the jmeterTestPlan root through a disabled TestFragmentController,
    shared by fragment (jmx_generator) and scenario (build_scenario_jmx) output.
    Returns (root, fragment_tree); callers append their own children to
    fragment_tree before serializing root with jmx_to_string.
    """
    root = ET.Element("jmeterTestPlan", version="1.2", properties="5.0", jmeter=jmeter_version)
```

(Rest of the function body is unchanged.)

- [ ] **Step 4: Update `jmx_generator.build_jmx_xml`'s call site**

In `jmx_generator.py`, change:

```python
    root, fragment_tree = build_test_plan_scaffold(test_name)
```

to:

```python
    root, fragment_tree = build_test_plan_scaffold(test_name, config.jmeter.version)
```

(`config` is already guaranteed non-`None` at this point — `build_jmx_xml` defaults it to `default_config()` earlier in the function.)

- [ ] **Step 5: Update `build_scenario_jmx.py`**

Add `ConverterConfig` and `default_config` to the existing `from converter_config import load_config` line:

```python
from converter_config import ConverterConfig, default_config, load_config
```

Change the `build_scenario_jmx` function:

```python
def build_scenario_jmx(plan_name: str, include_files: List[str], config: Optional[ConverterConfig] = None) -> str:
    """
    Build a JMX with a Test Plan, disabled Test Fragment, and Include Controllers.
    """
    if config is None:
        config = default_config()

    root, fragment_tree = build_test_plan_scaffold(plan_name, config.jmeter.version)
```

(Rest of the function body — the `for jmx_file in include_files:` loop and `return _jmx_to_string(root)` — is unchanged.)

Add `Optional` to the existing `from typing import List` import:

```python
from typing import List, Optional
```

In `main()`, change the call site:

```python
    output_path.write_text(build_scenario_jmx(plan_name, include_files, config), encoding="utf-8")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_harconverter.JmxGenerationTests -v`
Expected: all tests in the class PASS.

- [ ] **Step 7: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: all tests pass, including `DirectGenerationTests.test_direct_generation_and_scenario_builder_are_parseable`, which calls `build_scenario_jmx("Project_Product_Scenario", ["Project_Product_GET_users.jmx"])` with no `config` argument — still valid since `config` now defaults to `None`.

- [ ] **Step 8: Commit**

```bash
git add jmx_xml.py jmx_generator.py build_scenario_jmx.py tests/test_harconverter.py
git commit -m "feat: make the generated JMX's jmeter version configurable"
```

---

### Task 5: Configurable fragment naming — `process_har_entries`, `generate_jmx_files`, `har_to_jmx.py` CLI

**Files:**
- Modify: `har_requests.py:104` (import), `har_requests.py:129-172` (`process_har_entries`)
- Modify: `jmx_generator.py:206-214` (`generate_jmx_files`)
- Modify: `har_to_jmx.py` (full CLI rewrite)
- Modify: `tests/test_harconverter.py` (update 6 existing call sites, add new tests)

This is the first task that changes `process_har_entries`'s signature, so every existing caller in the test file needs updating in the same task to keep the suite green.

**Interfaces:**
- Consumes: `naming.render`, `naming.validate_vars` (Task 1); `config.naming.template` (Task 2).
- Produces:
  - `har_requests.process_har_entries(entries: Iterable[Any], template_vars: Dict[str, str], config: Any = None) -> ProcessedRequests` (was `(entries, project: str, product: str, config=None)`)
  - `jmx_generator.generate_jmx_files(entries, template_vars: Dict[str, str], host_var_map, out_dir, verbose=False, config=None) -> int` (was `(entries, project, product, host_var_map, out_dir, verbose=False, config=None)`)
  - `har_to_jmx.py` CLI: `har_to_jmx.py har_path [host_mapping] [--var KEY=VALUE ...] [--out-dir DIR] [--config FILE] [--verbose]` (positional `project`/`product` removed)

- [ ] **Step 1: Update `process_har_entries`'s existing call sites and write new failing tests**

In `tests/test_harconverter.py`, update every existing `process_har_entries(...)` call from the 2-positional-arg form to a `template_vars` dict:

In `test_filters_noise_and_keeps_api_requests`, change:
```python
        processed = process_har_entries(entries, "Project", "Product")
```
to:
```python
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"})
```

In `test_naming_helpers_and_collision_suffixes`, change:
```python
        processed = process_har_entries(entries, "Project", "Product")
```
to:
```python
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"})
```

In `test_form_encoded_params_without_text_are_captured_as_body`, change:
```python
        processed = process_har_entries([entry], "Project", "Product")
```
to:
```python
        processed = process_har_entries([entry], {"project": "Project", "product": "Product"})
```

In `test_config_can_extend_filters_and_keep_urls`, change:
```python
        processed = process_har_entries(entries, "Project", "Product", config)
```
to:
```python
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"}, config)
```

In `test_header_value_filter_skips_matching_requests` (added in Task 3), change:
```python
        processed = process_har_entries(entries, "Project", "Product")
```
to:
```python
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"})
```

In `test_header_value_filter_is_config_driven` (added in Task 3), change:
```python
        processed = process_har_entries(entries, "Project", "Product", config)
```
to:
```python
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"}, config)
```

Add two new tests to `FilteringAndNamingTests`, after `test_naming_helpers_and_collision_suffixes`:

```python
    def test_naming_template_is_configurable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"naming": {"template": "{method}_{segment}"}}),
                encoding="utf-8",
            )
            config = load_config(config_path)

        entries = [har_entry("https://example.com/api/users")]
        processed = process_har_entries(entries, {}, config)

        self.assertEqual(processed.requests[0].file_name, "GET_users.jmx")

    def test_process_har_entries_raises_on_missing_template_variable(self):
        entries = [har_entry("https://example.com/api/users")]
        with self.assertRaises(KeyError):
            process_har_entries(entries, {})
```

In `DirectGenerationTests.test_direct_generation_and_scenario_builder_are_parseable`, change:
```python
            count = generate_jmx_files(entries, "Project", "Product", {}, temp_dir)
```
to:
```python
            count = generate_jmx_files(entries, {"project": "Project", "product": "Product"}, {}, temp_dir)
```

- [ ] **Step 2: Run tests to verify the new ones fail and the updated ones fail for the right reason**

Run: `python3 -m unittest discover -s tests`
Expected: many FAILs / ERRORs — `TypeError: process_har_entries() takes from 2 to 3 positional arguments but 4 were given` (or similar) since `process_har_entries`/`generate_jmx_files` haven't changed yet. This confirms the test updates exercise the new call shape.

- [ ] **Step 3: Update `har_requests.process_har_entries`**

Add an import at the top of `har_requests.py` (alongside the existing `from urllib.parse import urlencode, urlparse` line):

```python
from naming import render
```

Change the function signature:

```python
def process_har_entries(entries: Iterable[Any], template_vars: Dict[str, str], config: Any = None) -> ProcessedRequests:
```

Replace the base-name construction line:

```python
        base_name = f"{project}_{product}_{method}_{safe_segment}"
```

with:

```python
        base_name = render(
            config.naming.template,
            **template_vars,
            method=method,
            segment=safe_segment,
        )
```

- [ ] **Step 4: Update `jmx_generator.generate_jmx_files`**

In `jmx_generator.py`, change the signature and internal call:

```python
def generate_jmx_files(
    entries: List[Any],
    template_vars: Dict[str, str],
    host_var_map: Dict[str, str],
    out_dir: Union[str, Path],
    verbose: bool = False,
    config: Optional[ConverterConfig] = None,
) -> int:
    """
    Iterate HAR entries, filter them, build JMX XML, and write files.
    Returns number of generated files.
    """
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if config is None:
        config = default_config()

    processed = process_har_entries(entries, template_vars, config)
```

(Rest of the function is unchanged.)

- [ ] **Step 5: Run tests to verify the library-level tests pass**

Run: `python3 -m unittest tests.test_harconverter.FilteringAndNamingTests tests.test_harconverter.DirectGenerationTests -v`
Expected: all tests PASS. (`CliSmokeTests` will still fail — the CLI itself hasn't been updated yet; that's Steps 6-9.)

- [ ] **Step 6: Rewrite `har_to_jmx.py`'s CLI**

Replace the full contents of `har_to_jmx.py`:

```python
#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Tuple

from converter_config import load_config, merge_host_maps
from har_utils import load_har_entries
from host_mapping import load_host_map
from jmx_generator import generate_jmx_files
from naming import validate_vars


def _parse_var(value: str) -> Tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"--var must be KEY=VALUE, got: {value!r}")
    key, _, val = value.partition("=")
    return key, val


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert HAR requests into individual JMeter fragment JMX files."
    )
    parser.add_argument("har_path", help="HAR file to convert.")
    parser.add_argument(
        "host_mapping",
        nargs="?",
        default="",
        help="Optional CSV file with host,variableName mappings.",
    )
    parser.add_argument(
        "--var",
        action="append",
        type=_parse_var,
        default=[],
        metavar="KEY=VALUE",
        help="Naming template variable, e.g. --var project=Abbot. Repeatable.",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory receiving generated JMX files. Defaults to current directory.",
    )
    parser.add_argument("--config", default="", help="Optional JSON converter configuration file.")
    parser.add_argument("--verbose", action="store_true", help="Print skipped request details.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    har_path = Path(args.har_path)
    out_dir = Path(args.out_dir)

    if not har_path.is_file():
        print(f"File not found: {har_path}", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to load config file {args.config}: {exc}", file=sys.stderr)
        sys.exit(1)

    template_vars = dict(args.var)

    try:
        validate_vars(config.naming.template, template_vars, reserved={"method", "segment"})
    except ValueError as exc:
        print(f"Invalid --var arguments: {exc}", file=sys.stderr)
        sys.exit(1)

    csv_host_map = load_host_map(args.host_mapping)
    if csv_host_map:
        print(f"Loaded {len(csv_host_map)} host mapping entries from {args.host_mapping}")
    host_var_map = merge_host_maps(config.hosts, csv_host_map)

    try:
        entries = load_har_entries(har_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to load HAR file {har_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("No entries found in HAR.")
        sys.exit(0)

    print(f"Generating JMX files into: {out_dir.resolve()}")
    count = generate_jmx_files(
        entries,
        template_vars,
        host_var_map,
        out_dir,
        verbose=args.verbose,
        config=config,
    )

    print(f"\nDone! Generated {count} JMX file(s).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Update `har_to_jmx.py`'s existing CLI smoke-test call sites**

In `tests/test_harconverter.py`'s `CliSmokeTests` class:

In `test_fragment_and_scenario_commands_write_expected_files`, change the `fragments = subprocess.run([...])` argument list:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "Project",
                    "Product",
                    "--out-dir",
                    str(out_dir),
```
to:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                    "--out-dir",
                    str(out_dir),
```
(Leave the `scenario = subprocess.run([...])` call in this same test untouched for now — `build_scenario_jmx.py`'s CLI is updated in Task 6.)

In `test_cli_errors_and_missing_host_mapping_warning`, change the `invalid = subprocess.run([...])` argument list:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(invalid_har),
                    "Project",
                    "Product",
```
to:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(invalid_har),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
```

In the same test, change the `missing_mapping = subprocess.run([...])` argument list:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(valid_har),
                    "Project",
                    "Product",
                    str(missing_csv),
                    "--out-dir",
                    str(out_dir),
```
to:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(valid_har),
                    str(missing_csv),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                    "--out-dir",
                    str(out_dir),
```

In `test_cli_config_works_and_invalid_config_fails`, change the `result = subprocess.run([...])` argument list:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "Project",
                    "Product",
                    "--out-dir",
                    str(out_dir),
                    "--config",
                    str(config_path),
```
to:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                    "--out-dir",
                    str(out_dir),
                    "--config",
                    str(config_path),
```

In the same test, change the `bad_result = subprocess.run([...])` argument list:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "Project",
                    "Product",
                    "--config",
                    str(bad_config_path),
```
to:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                    "--config",
                    str(bad_config_path),
```

In `test_empty_har_is_successful_no_output_case`, change the `result = subprocess.run([...])` argument list:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "Project",
                    "Product",
```
to:
```python
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
```

- [ ] **Step 8: Add a new CLI smoke test for `--var` validation**

Add to `CliSmokeTests`, after `test_empty_har_is_successful_no_output_case`:

```python
    def test_cli_var_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            har_path = temp_path / "recording.har"
            har_path.write_text(
                json.dumps([har_entry("https://example.com/api/users")]),
                encoding="utf-8",
            )

            missing_var = subprocess.run(
                [sys.executable, str(ROOT / "har_to_jmx.py"), str(har_path), "--var", "project=Project"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(missing_var.returncode, 0)
            self.assertIn("Invalid --var arguments", missing_var.stderr)
            self.assertIn("product", missing_var.stderr)

            malformed_var = subprocess.run(
                [sys.executable, str(ROOT / "har_to_jmx.py"), str(har_path), "--var", "project"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(malformed_var.returncode, 0)
            self.assertIn("--var must be KEY=VALUE", malformed_var.stderr)
```

- [ ] **Step 9: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: all tests pass. (`test_fragment_and_scenario_commands_write_expected_files`'s scenario half still uses the old `build_scenario_jmx.py` positional CLI — that continues to work since Task 6 hasn't changed it yet.)

- [ ] **Step 10: Commit**

```bash
git add har_requests.py jmx_generator.py har_to_jmx.py tests/test_harconverter.py
git commit -m "feat: make fragment naming configurable via naming.template and --var"
```

---

### Task 6: Configurable scenario naming — `build_scenario_jmx.py` CLI

**Files:**
- Modify: `build_scenario_jmx.py` (CLI: `parse_args`, `main`)
- Modify: `tests/test_harconverter.py` (update 1 existing call site, add new test)

**Interfaces:**
- Consumes: `naming.render`, `naming.validate_vars` (Task 1); `config.naming.scenario_template` (Task 2); `process_har_entries(entries, template_vars, config)` (Task 5); `build_scenario_jmx(plan_name, include_files, config)` (Task 4).
- Produces: `build_scenario_jmx.py` CLI: `build_scenario_jmx.py har_path scenario_name [--var KEY=VALUE ...] [--out-dir DIR] [--config FILE] [--verbose]` (positional `project`/`product` removed).

- [ ] **Step 1: Update the existing CLI smoke-test call site and write a new failing test**

In `tests/test_harconverter.py`'s `test_fragment_and_scenario_commands_write_expected_files`, change the `scenario = subprocess.run([...])` argument list:
```python
                    sys.executable,
                    str(ROOT / "build_scenario_jmx.py"),
                    str(har_path),
                    "Project",
                    "Product",
                    "Scenario",
                    "--out-dir",
                    str(out_dir),
```
to:
```python
                    sys.executable,
                    str(ROOT / "build_scenario_jmx.py"),
                    str(har_path),
                    "Scenario",
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                    "--out-dir",
                    str(out_dir),
```

Add a new test to `CliSmokeTests`, after `test_cli_var_validation`:

```python
    def test_scenario_cli_var_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            har_path = temp_path / "recording.har"
            har_path.write_text(
                json.dumps([har_entry("https://example.com/api/users")]),
                encoding="utf-8",
            )

            missing_var = subprocess.run(
                [sys.executable, str(ROOT / "build_scenario_jmx.py"), str(har_path), "Scenario"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(missing_var.returncode, 0)
            self.assertIn("Invalid --var arguments", missing_var.stderr)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_harconverter.CliSmokeTests.test_fragment_and_scenario_commands_write_expected_files tests.test_harconverter.CliSmokeTests.test_scenario_cli_var_validation -v`
Expected: both FAIL — `test_fragment_and_scenario_commands_write_expected_files` because `build_scenario_jmx.py` doesn't accept `--var`/doesn't accept a single positional after `har_path` yet (argparse usage error, nonzero exit, `scenario.returncode` assertion fails); `test_scenario_cli_var_validation` because there's no `--var` validation yet, so it doesn't fail the way the test expects (or fails for the wrong reason — the run may succeed or error differently).

- [ ] **Step 3: Rewrite `build_scenario_jmx.py`'s CLI**

Change the existing `from typing import List, Optional` import (from Task 4) to add `Dict` and `Tuple`:

```python
from typing import Dict, List, Optional, Tuple
```

Add a `naming` import:

```python
from naming import render, validate_vars
```

Replace `_parse_var`, `parse_args`, and `main` (the `build_scenario_jmx()` function itself, from Task 4, is unchanged):

```python
def _parse_var(value: str) -> Tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"--var must be KEY=VALUE, got: {value!r}")
    key, _, val = value.partition("=")
    return key, val


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a scenario JMX that includes generated HAR request fragments."
    )
    parser.add_argument("har_path", help="HAR file used to determine scenario order.")
    parser.add_argument("scenario_name", help="Scenario name used in the output JMX filename.")
    parser.add_argument(
        "--var",
        action="append",
        type=_parse_var,
        default=[],
        metavar="KEY=VALUE",
        help="Naming template variable, e.g. --var project=Abbot. Repeatable.",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory containing fragments and receiving the scenario JMX. Defaults to current directory.",
    )
    parser.add_argument("--config", default="", help="Optional JSON converter configuration file.")
    parser.add_argument("--verbose", action="store_true", help="Print skipped request details.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    har_path = Path(args.har_path)
    out_dir = Path(args.out_dir)

    if not har_path.is_file():
        print(f"File not found: {har_path}", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to load config file {args.config}: {exc}", file=sys.stderr)
        sys.exit(1)

    template_vars: Dict[str, str] = dict(args.var)

    try:
        validate_vars(config.naming.template, template_vars, reserved={"method", "segment"})
        validate_vars(config.naming.scenario_template, template_vars, reserved={"scenario_name"})
    except ValueError as exc:
        print(f"Invalid --var arguments: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        entries = load_har_entries(har_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to load HAR file {har_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("No entries found in HAR.")
        sys.exit(0)

    processed = process_har_entries(entries, template_vars, config)

    if args.verbose:
        for skipped in processed.skipped:
            print(f"Skipped #{skipped.entry_index}: {skipped.method} {skipped.url} ({skipped.reason})")

    include_files: List[str] = []
    for request in processed.requests:
        jmx_path = out_dir / request.file_name
        if jmx_path.is_file():
            include_files.append(request.file_name)
        else:
            print(f"WARNING: JMX not found for {request.method} {request.url} -> expected {request.file_name}")

    if not include_files:
        print("No matching JMX files found for HAR entries.")
        sys.exit(0)

    print(f"Will include {len(include_files)} JMX fragments:")
    for include_file in include_files:
        print(f"  {include_file}")

    out_dir.mkdir(parents=True, exist_ok=True)
    plan_name = render(config.naming.scenario_template, **template_vars, scenario_name=args.scenario_name)
    output_path = out_dir / f"{plan_name}.jmx"
    output_path.write_text(build_scenario_jmx(plan_name, include_files, config), encoding="utf-8")

    print(f"\nScenario JMX created: {output_path}")


if __name__ == "__main__":
    main()
```

Note: `validate_vars` is called against *both* `config.naming.template` and `config.naming.scenario_template`, because `process_har_entries` (called a few lines later, reusing the same `template_vars`) renders fragment filenames with `config.naming.template` internally — without this first check, a `naming.template` needing an unsupplied variable would surface as a raw `KeyError` from `process_har_entries` instead of the clean `"Invalid --var arguments"` message.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_harconverter.CliSmokeTests -v`
Expected: all tests in the class PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m unittest discover -s tests`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add build_scenario_jmx.py tests/test_harconverter.py
git commit -m "feat: make scenario naming configurable via naming.scenario_template and --var"
```

---

### Task 7: Documentation — README.md and CLAUDE.md

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: final state of all prior tasks.
- Produces: no code changes — documentation only.

- [ ] **Step 1: Update README's Project Contents table**

In `README.md`, add a row after the `jmx_xml.py` row:

```markdown
| `jmx_xml.py` | Shared JMeter XML element helpers and the TestPlan/TestFragmentController scaffold used by both `jmx_generator.py` and `build_scenario_jmx.py`. |
| `naming.py` | Parses, validates, and renders the `naming.template`/`naming.scenario_template` format strings used for JMX filenames and test names. |
```

- [ ] **Step 2: Update the JMeter version blurb**

Replace:

```markdown
The generated JMX declares:

```xml
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.0">
```

The existing `jmeter.log` shows the files have been opened with Apache JMeter 5.6.3.
```

with:

```markdown
The generated JMX declares:

```xml
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.0">
```

`jmeter="5.6.0"` is the default; override it with `jmeter.version` in a JSON config file.

The existing `jmeter.log` shows the files have been opened with Apache JMeter 5.6.3.
```

- [ ] **Step 3: Rewrite "Generate Request Fragments"**

Replace the entire section (from `## Generate Request Fragments` through the `Generated files are written to the selected output directory.` line, i.e. through the CLI usage, examples, and arguments table) with:

```markdown
## Generate Request Fragments

Run:

```bash
python3 har_to_jmx.py path/to/file.har [host_mapping.csv] [--var key=value ...] [--out-dir output] [--config config.json] [--verbose]
```

Examples:

```bash
python3 har_to_jmx.py login.har --var project=Abbot --var product=Merlin
```

```bash
python3 har_to_jmx.py login.har hosts.csv --var project=Abbot --var product=Merlin
```

```bash
python3 har_to_jmx.py login.har hosts.csv --var project=Abbot --var product=Merlin --out-dir generated --verbose
```

```bash
python3 har_to_jmx.py login.har --var project=Abbot --var product=Merlin --config merlin-config.json --out-dir generated
```

Arguments:

| Argument | Required | Description |
| --- | --- | --- |
| `path/to/file.har` | Yes | HAR file to convert. |
| `host_mapping.csv` | No | Optional CSV file for replacing host values in headers with JMeter properties. |
| `--var key=value` | Depends on `naming.template` | Supplies a naming template variable, e.g. `--var project=Abbot`. Repeatable. The default `naming.template` needs `project` and `product`; a custom template may need different variables, or none. |
| `--out-dir` | No | Output directory for generated JMX files. Defaults to the current directory. |
| `--config` | No | Optional JSON config for project-specific filters, host mappings, header masks, naming, and JMeter options. |
| `--verbose` | No | Prints skipped request details and reasons. |

Generated files are written to the selected output directory. If `naming.template` references a variable that isn't supplied by `--var`, the converter exits with an error listing exactly which variable(s) are missing before touching any HAR entries.
```

- [ ] **Step 4: Rewrite "Fragment Filename Format"**

Replace the `### Fragment Filename Format` section (through the "sanitized for filesystem safety" line, not including the following `### Request Filtering` heading) with:

```markdown
### Fragment Filename Format

Each request fragment's base filename comes from `naming.template` in the config (see [Project-Specific Configuration](#project-specific-configuration)). The default is:

```text
{project}_{product}_{method}_{segment}
```

`method` and `segment` (the sanitized last URL path segment) are computed per-request; every other placeholder must be supplied with `--var`. With the default template:

```text
Abbot_Merlin_GET_recent.jmx
Abbot_Merlin_POST_token.jmx
```

A project without a Project/Product taxonomy can configure a simpler template, e.g. `"naming": {"template": "{method}_{segment}"}`, and run without any `--var` flags:

```text
GET_recent.jmx
POST_token.jmx
```

If multiple valid requests produce the same base filename, the first keeps the original name and later files receive deterministic numeric suffixes:

```text
Abbot_Merlin_GET_users.jmx
Abbot_Merlin_GET_users_2.jmx
Abbot_Merlin_GET_users_3.jmx
```

The scenario generator uses the same shared naming logic, so scenario includes match the generated fragment filenames.

The last path segment is taken from the request URL path:

| URL Path | Last Segment |
| --- | --- |
| `/` | `root` |
| `/api/v1/users` | `users` |
| `/api/v1/users/` | `users` |

The segment is sanitized for filesystem safety by replacing non-alphanumeric runs with `_`. Other template placeholders (like `project`/`product`) are used as supplied via `--var`, unsanitized.
```

- [ ] **Step 5: Rewrite "Generate a Scenario JMX"**

Replace the section (from `## Generate a Scenario JMX` through the `Abbot_Merlin_GET_recent.jmx` example, not including the following `The scenario builder applies...` paragraph) with:

```markdown
## Generate a Scenario JMX

After generating request fragments, run:

```bash
python3 build_scenario_jmx.py path/to/file.har ScenarioName [--var key=value ...] [--out-dir output] [--config config.json] [--verbose]
```

Example:

```bash
python3 build_scenario_jmx.py recent.har Recent_Transmittions --var project=Abbot --var product=Merlin
```

```bash
python3 build_scenario_jmx.py recent.har Recent_Transmittions --var project=Abbot --var product=Merlin --out-dir generated --verbose
```

```bash
python3 build_scenario_jmx.py recent.har Recent_Transmittions --var project=Abbot --var product=Merlin --config merlin-config.json --out-dir generated
```

This creates a file named by `naming.scenario_template` (default `{project}_{product}_{scenario_name}`):

```text
Project_Product_ScenarioName.jmx
```

For example:

```text
Abbot_Merlin_Recent_Transmittions.jmx
```

The scenario file contains:

- a JMeter `TestPlan`
- a disabled `TestFragmentController`
- one `IncludeController` per matching fragment file

Each include points to a generated fragment file, for example:

```text
Abbot_Merlin_GET_recent.jmx
```
```

Then update the immediately following paragraph — change:

```markdown
The scenario builder applies the same shared filtering and filename generation as `har_to_jmx.py`, then checks whether the expected fragment file exists in the selected output directory.
```

to:

```markdown
The scenario builder applies the same shared filtering and filename generation as `har_to_jmx.py` (including `naming.template`, so it needs the same `--var` values used to generate the fragments), then checks whether the expected fragment file exists in the selected output directory.
```

- [ ] **Step 6: Rewrite "Recommended Workflow"**

Replace steps 3 and 4's code blocks — change:

```markdown
3. Generate request fragments:

```bash
python3 har_to_jmx.py recording.har Abbot Merlin hosts.csv
```

4. Generate a scenario file:

```bash
python3 build_scenario_jmx.py recording.har Abbot Merlin ScenarioName
```
```

to:

```markdown
3. Generate request fragments:

```bash
python3 har_to_jmx.py recording.har hosts.csv --var project=Abbot --var product=Merlin
```

4. Generate a scenario file:

```bash
python3 build_scenario_jmx.py recording.har ScenarioName --var project=Abbot --var product=Merlin
```
```

- [ ] **Step 7: Update the "Project-Specific Configuration" example JSON and behavior bullets**

Replace the first (full) example JSON block with:

```json
{
  "naming": {
    "template": "{project}_{product}_{method}_{segment}",
    "scenario_template": "{project}_{product}_{scenario_name}"
  },
  "filters": {
    "skip_methods": ["OPTIONS"],
    "skip_host_contains": ["google-analytics.com", "sentry.io"],
    "skip_exact_hosts": ["fonts.googleapis.com", "fonts.gstatic.com"],
    "skip_extensions": [".js", ".css", ".png"],
    "skip_final_segments": ["static", "assets", "media"],
    "skip_url_contains": ["nrjs", "nr-data.net"],
    "skip_header_value_contains": ["nrjs"],
    "keep_url_contains": ["/api/static-report.js"]
  },
  "hosts": {
    "app.example.com": "hostName",
    "api.example.com": "apiHost"
  },
  "headers": {
    "mask": [
      {
        "name": "Authorization",
        "prefix": "Bearer ",
        "replacement": "Bearer ${TOKEN}"
      },
      {
        "name": "X-Api-Key",
        "prefix": "key-",
        "replacement": "${API_KEY}"
      }
    ]
  },
  "jmeter": {
    "version": "5.6.0",
    "cookie_manager": true,
    "cache_manager": true,
    "http_defaults": true,
    "http_defaults_protocol": "${__P(protocol,https)}",
    "http_defaults_domain": "${__P(hostName)}",
    "http_defaults_port": ""
  }
}
```

Add two bullets to the "Config behavior" list, after the `keep_url_contains` bullet:

```markdown
- `naming.template` controls fragment filenames/test names; `naming.scenario_template` controls the scenario filename. Both accept `{name}`-style placeholders; every placeholder besides the tool-computed ones (`method`/`segment` for `naming.template`, `scenario_name` for `naming.scenario_template`) must be supplied with `--var`.
- `filters.skip_header_value_contains` extends the built-in defaults the same way as the other filter lists, and replaces what used to be a hardcoded "New Relic header" check.
```

- [ ] **Step 8: Update "Current Limitations" and "Testing" bullet lists**

Change the limitations bullet:

```markdown
- Fragment filenames are based on method and last URL path segment, with deterministic suffixes added for collisions.
```

to:

```markdown
- Fragment and scenario filenames are based on the configurable `naming.template`/`naming.scenario_template` (default: method and last URL path segment for fragments), with deterministic suffixes added for collisions on the fragment side.
```

Replace the "Testing" section's bullet list:

```markdown
The tests cover:

- supported HAR input shapes
- request filtering
- project-specific config filtering
- filename collision suffixes
- parseable generated XML
- query parameter and raw body handling
- Authorization masking
- custom header masking
- host mapping substitution
- optional JMeter Cookie Manager, Cache Manager, and HTTP Request Defaults
- CLI smoke behavior
- invalid HAR error handling
```

with:

```markdown
The tests cover:

- supported HAR input shapes
- request filtering
- header-value filtering
- naming template validation and rendering
- project-specific config filtering
- filename collision suffixes
- parseable generated XML
- query parameter and raw body handling
- Authorization masking
- custom header masking
- host mapping substitution
- configurable JMeter version
- optional JMeter Cookie Manager, Cache Manager, and HTTP Request Defaults
- CLI smoke behavior
- invalid HAR error handling
```

- [ ] **Step 9: Update README's Maintenance Notes**

Add a new entry at the end of the `## Maintenance Notes` section:

```markdown
When changing naming template parsing, validation, or rendering, update:

- `naming.py`
```

- [ ] **Step 10: Update CLAUDE.md's Commands section**

Replace:

```markdown
```bash
python3 har_to_jmx.py path/to/file.har Project Product [host_mapping.csv] [--out-dir output] [--config config.json] [--verbose]
python3 build_scenario_jmx.py path/to/file.har Project Product ScenarioName [--out-dir output] [--config config.json] [--verbose]
```
```

with:

```markdown
```bash
python3 har_to_jmx.py path/to/file.har [host_mapping.csv] [--var key=value ...] [--out-dir output] [--config config.json] [--verbose]
python3 build_scenario_jmx.py path/to/file.har ScenarioName [--var key=value ...] [--out-dir output] [--config config.json] [--verbose]
```
```

- [ ] **Step 11: Update CLAUDE.md's Architecture section**

Replace point 2:

```markdown
2. **`converter_config.load_config`** — loads an optional JSON config file and merges it onto `default_config()` (a frozen `ConverterConfig` dataclass tree: `FilterConfig`, `hosts` dict, `header_masks`, `JMeterConfig`). Config merging is additive for list-based filters (extends the built-in defaults) and override-based for scalars/booleans.
```

with:

```markdown
2. **`converter_config.load_config`** — loads an optional JSON config file and merges it onto `default_config()` (a frozen `ConverterConfig` dataclass tree: `FilterConfig`, `hosts` dict, `header_masks`, `JMeterConfig`, `NamingConfig`). Config merging is additive for list-based filters (extends the built-in defaults) and override-based for scalars/booleans.
```

Replace point 3:

```markdown
3. **`har_requests.process_har_entries`** — the shared core: filters entries via `skip_reason()`, de-duplicates `(method, url)` pairs, and produces a `ProcessedRequests(requests, skipped)` with `NormalizedRequest` objects that already carry the computed, collision-safe `file_name`/`test_name` (`Project_Product_METHOD_lastSegment[_N].jmx`). Both CLIs call this same function, which is why fragment filenames and scenario includes always match.
```

with:

```markdown
3. **`har_requests.process_har_entries(entries, template_vars, config)`** — the shared core: filters entries via `skip_reason()`, de-duplicates `(method, url)` pairs, and produces a `ProcessedRequests(requests, skipped)` with `NormalizedRequest` objects that already carry the computed, collision-safe `file_name`/`test_name`. The base name is rendered from `config.naming.template` (default `{project}_{product}_{method}_{segment}`) via `naming.render`, merging the caller-supplied `template_vars` with the two reserved, per-request values (`method`, `segment`) that `--var` may never override. Both CLIs call this same function with the same `template_vars`, which is why fragment filenames and scenario includes always match.
```

Add a new paragraph immediately after the "Divergence point" bullet list, before the existing "Both generators build their XML on top of `jmx_xml.py`..." paragraph:

```markdown
Both CLIs validate `--var` up front with `naming.validate_vars(config.naming.template, template_vars, reserved={"method", "segment"})` before touching any HAR entries — a missing or reserved-conflicting `--var` fails fast with one clear message, never a bare `KeyError` mid-run. `build_scenario_jmx.py` additionally validates `config.naming.scenario_template` against `reserved={"scenario_name"}`, since it renders both the per-fragment filenames (via `process_har_entries`) and its own scenario filename (via `naming.render(config.naming.scenario_template, ...)`).
```

- [ ] **Step 12: Update CLAUDE.md's Maintenance Notes bullet list**

Change:

```markdown
When changing behavior, the README's "Maintenance Notes" table is authoritative:
- Request filtering → `har_requests.py`
- New auth schemes / host substitution → `converter_config.py`, `jmx_generator.py`
- Accepted HAR input shapes → `har_utils.py`
- Host mapping CSV rules → `host_mapping.py`
- Shared TestPlan/TestFragmentController scaffold → `jmx_xml.py`
```

to:

```markdown
When changing behavior, the README's "Maintenance Notes" table is authoritative:
- Request filtering → `har_requests.py`
- New auth schemes / host substitution → `converter_config.py`, `jmx_generator.py`
- Accepted HAR input shapes → `har_utils.py`
- Host mapping CSV rules → `host_mapping.py`
- Shared TestPlan/TestFragmentController scaffold → `jmx_xml.py`
- Naming template parsing/validation/rendering → `naming.py`
```

- [ ] **Step 13: Spot-check the rewritten commands actually work**

Run, from the repo root, using the real `README.md` "Recommended Workflow" example against a throwaway HAR file:

```bash
python3 -c "import json,pathlib; pathlib.Path('/tmp/smoke.har').write_text(json.dumps([{'request': {'url': 'https://example.com/api/users', 'method': 'GET', 'headers': []}}]))"
python3 har_to_jmx.py /tmp/smoke.har --var project=Abbot --var product=Merlin --out-dir /tmp/smoke-out
python3 build_scenario_jmx.py /tmp/smoke.har Recent_Transmittions --var project=Abbot --var product=Merlin --out-dir /tmp/smoke-out
ls /tmp/smoke-out
rm -rf /tmp/smoke.har /tmp/smoke-out
```

Expected: both commands succeed (exit 0); `/tmp/smoke-out` contains `Abbot_Merlin_GET_users.jmx` and `Abbot_Merlin_Recent_Transmittions.jmx`, matching the README's documented filenames.

- [ ] **Step 14: Run the full suite one final time**

Run: `python3 -m unittest discover -s tests`
Expected: all tests pass.

- [ ] **Step 15: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: update README and CLAUDE.md for configurable naming and JMeter version"
```
