# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HARConverter is a dependency-free Python utility that converts browser HAR captures into Apache JMeter `.jmx` files. It has two entry points:

1. `har_to_jmx.py` — generates one reusable JMeter fragment `.jmx` per meaningful HTTP request in a HAR file.
2. `build_scenario_jmx.py` — generates a scenario `.jmx` that includes previously-generated fragments (via `IncludeController`) in HAR recording order.

Only the Python standard library is used — no third-party dependencies, no build step.

## Commands

Run the CLI tools directly with `python3` (or `python` where it points to Python 3):

```bash
python3 har_to_jmx.py path/to/file.har [host_mapping.csv] [--var key=value ...] [--out-dir output] [--config config.json] [--verbose]
python3 build_scenario_jmx.py path/to/file.har ScenarioName [--var key=value ...] [--out-dir output] [--config config.json] [--verbose]
```

Run the full test suite:

```bash
python3 -m unittest discover -s tests
```

Run a single test:

```bash
python3 -m unittest tests.test_harconverter.<TestClassName>.<test_method_name>
```

There is no linter, formatter, or build configured in this repo.

## Architecture

Both CLI entry points (`har_to_jmx.py`, `build_scenario_jmx.py`) wire together the same shared pipeline, in this order:

1. **`har_utils.load_har_entries`** — normalizes the three supported HAR JSON shapes (`{log:{entries}}`, `{entries}`, or a bare list) into a list of entry dicts.
2. **`converter_config.load_config`** — loads an optional JSON config file and merges it onto `default_config()` (a frozen `ConverterConfig` dataclass tree: `FilterConfig`, `hosts` dict, `header_masks`, `JMeterConfig`, `NamingConfig`). Config merging is additive for list-based filters (extends the built-in defaults) and override-based for scalars/booleans.
3. **`har_requests.process_har_entries(entries, template_vars, config)`** — the shared core: filters entries via `skip_reason()`, de-duplicates `(method, url)` pairs, and produces a `ProcessedRequests(requests, skipped)` with `NormalizedRequest` objects that already carry the computed, collision-safe `file_name`/`test_name`. The base name is rendered from `config.naming.template` (default `{project}_{product}_{method}_{segment}`) via `naming.render`, merging the caller-supplied `template_vars` with the two reserved, per-request values (`method`, `segment`) that `--var` may never override. Both CLIs call this same function with the same `template_vars`, which is why fragment filenames and scenario includes always match.
4. Divergence point:
   - `har_to_jmx.py` → `jmx_generator.generate_jmx_files` builds full fragment XML per request (`TestPlan` → disabled `TestFragmentController` → optional `HTTP Request Defaults`/`Cookie Manager`/`Cache Manager` → `HTTPSamplerProxy` + `HeaderManager`) and writes one `.jmx` file per request.
   - `build_scenario_jmx.py` → checks that each expected fragment filename already exists in `--out-dir` (warns and skips if missing) and emits a single scenario `.jmx` with one `IncludeController` per found fragment. It does not read config `jmeter.*` options — those only affect fragment generation.

Both CLIs validate `--var` up front with `naming.validate_vars(config.naming.template, template_vars, reserved={"method", "segment"})` before touching any HAR entries — a missing or reserved-conflicting `--var` fails fast with one clear message, never a bare `KeyError` mid-run. `build_scenario_jmx.py` additionally validates `config.naming.scenario_template` against `reserved={"scenario_name"}`, since it renders both the per-fragment filenames (via `process_har_entries`) and its own scenario filename (via `naming.render(config.naming.scenario_template, ...)`).

Both generators build their XML on top of `jmx_xml.py`, which owns the low-level element helpers (`sub`, `string_prop`, `bool_prop`, `jmx_to_string`) and `build_test_plan_scaffold(name, jmeter_version)` — the shared `jmeterTestPlan` → `TestPlan` → disabled `TestFragmentController` structure every generated file starts with. `jmx_generator.py` and `build_scenario_jmx.py` each append their own children (sampler/header manager vs. `IncludeController`s) to the `fragment_tree` the scaffold returns.

Supporting modules:
- `host_mapping.load_host_map` — parses `host,variableName` CSV rows. CSV entries override config-file `hosts` entries for the same host (see `converter_config.merge_host_maps`), and matching is always case-insensitive.
- Host substitution (CSV + config `hosts`) is applied only to header values during fragment generation (`jmx_generator._normalized_headers`), never to the sampler's `domain`/`protocol`/`port`, which are intentionally left blank so they're supplied later in JMeter (defaults, environment, or `HTTP Request Defaults` if enabled via config).

When changing behavior, the README's "Maintenance Notes" table is authoritative:
- Request filtering → `har_requests.py`
- New auth schemes / host substitution → `converter_config.py`, `jmx_generator.py`
- Accepted HAR input shapes → `har_utils.py`
- Host mapping CSV rules → `host_mapping.py`
- Shared TestPlan/TestFragmentController scaffold → `jmx_xml.py`
- Naming template parsing/validation/rendering → `naming.py`

## Non-source artifacts

`jmeter.log`, `__pycache__/`, and generated `*.jmx` files are runtime/build artifacts (all gitignored) — not source logic, safe to ignore or regenerate.
