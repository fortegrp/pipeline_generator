# Design: generic naming, filters, and JMeter version

Status: approved for implementation planning
Branch: `converter_improvement`

## Problem

HARConverter currently bakes a few decisions into code rather than config:

1. Every generated request fragment and scenario file is named
   `Project_Product_METHOD_segment` / `Project_Product_ScenarioName`, with
   `project` and `product` as two required positional CLI arguments. A team
   without that two-level taxonomy, or one that wants a different naming
   scheme, has no way to change it short of editing the source.
2. `har_requests.skip_reason()` unconditionally skips any request whose URL
   or header value contains `"nrjs"`, with the reason string `"New Relic
   header"`. This is the one filter that isn't config-driven the way every
   other default filter (tracker hosts, static extensions, etc.) already is.
3. Generated JMX always declares `jmeter="5.6.0"` as a literal in
   `jmx_xml.build_test_plan_scaffold()`.

This is the first of two planned changes (the second being auto-correlation,
designed separately). It intentionally does not touch the default noise
filters (fonts/analytics/static-asset skipping) or add support for
non-HAR input formats — both were explicitly ruled out of scope during
brainstorming.

This is a breaking change to the CLI (`project`/`product` positional args
are removed) and to `har_requests.process_har_entries` /
`jmx_generator.generate_jmx_files`'s signatures. Nothing external depends
on today's positional args, so no compatibility shim is provided.

## Goals

- Naming (fragment filenames/test names, scenario filenames) is driven by a
  configurable template string, not a hardcoded `Project_Product_...` format.
- The New Relic header check becomes a normal, overridable default filter
  like every other tracker/host/extension list.
- The JMeter version declared in generated XML is configurable.
- Fail fast, with one clear error, when required naming inputs are missing —
  never a bare `KeyError` mid-run.

## Non-goals

- Changing the default noise-filtering behavior for fonts/analytics/static
  assets (explicitly kept as-is).
- Supporting HAR-alternative input formats (Postman, etc.).
- Auto-correlation (separate design).

## New module: `naming.py`

A small module owning template parsing, validation, and rendering — kept
separate from `har_requests.py` (filtering) and `converter_config.py`
(config loading) so each module keeps one job.

```python
def required_fields(template: str) -> Set[str]:
    """Field names referenced by a template's {placeholders}."""

def validate_vars(template: str, provided: Dict[str, str], reserved: Set[str]) -> None:
    """
    Raises ValueError if:
    - provided defines a key in `reserved` (reserved keys are supplied by
      the tool itself, never by --var), or
    - template references a field that is neither in `provided` nor in
      `reserved`.
    ValueError message lists every offending key, not just the first.
    """

def render(template: str, **fields: str) -> str:
    """template.format(**fields); fields is the union of provided vars and
    reserved/computed values."""
```

Templates are restricted to plain `{name}` placeholders — no attribute
access (`{a.b}`), indexing (`{a[0]}`), positional (`{0}`), or format specs
(`{a:>10}`). `required_fields` rejects anything else with a `ValueError`
naming the offending placeholder; this keeps validation and rendering
simple and matches every realistic naming template.

**Reserved keys** are values the tool computes/supplies itself and that
`--var` may never override:
- Fragment naming (`har_to_jmx.py`): `{"method", "segment"}` — computed
  per-request from the HAR entry.
- Scenario naming (`build_scenario_jmx.py`): `{"scenario_name"}` — supplied
  by its own dedicated positional CLI arg.

If `--var` tries to set a reserved key, `validate_vars` raises `ValueError`
naming it (e.g. `"--var cannot set reserved name(s): method"`).

## Config schema additions (`converter_config.py`)

```json
{
  "naming": {
    "template": "{project}_{product}_{method}_{segment}",
    "scenario_template": "{project}_{product}_{scenario_name}"
  },
  "filters": {
    "skip_header_value_contains": ["nrjs"]
  },
  "jmeter": {
    "version": "5.6.0"
  }
}
```

- New `NamingConfig` frozen dataclass: `template: str`, `scenario_template: str`,
  with the defaults shown above (byte-identical output to today when no
  config/`--var` is supplied and the caller passes `project`/`product`
  vars, matching current CLI usage).
- `ConverterConfig` gains `naming: NamingConfig`.
- `FilterConfig` gains `skip_header_value_contains: List[str]`, default
  `["nrjs"]` — chosen over removing it from defaults entirely so existing
  users see no behavior change out of the box; it's just no longer special
  cased in code.
- `JMeterConfig` gains `version: str`, default `"5.6.0"`.
- `merge_config()` gets a `_merge_naming()` helper (same override-scalar
  pattern as `_merge_jmeter`) and `_merge_filters()` gets one more
  `_merged_list(...)` line for `skip_header_value_contains`.

## `har_requests.py` changes

- `skip_reason()`: replace the hardcoded block

  ```python
  headers = req.get("headers", [])
  if isinstance(headers, list) and any("nrjs" in str(h.get("value", "")).lower() for h in headers if isinstance(h, dict)):
      return "New Relic header"
  ```

  with a check against `config.filters.skip_header_value_contains`,
  reason string `"skipped header value substring"` (matches the existing
  `"skipped URL substring"` naming style).

- `process_har_entries(entries, template_vars, config=None)` replaces the
  `project: str, product: str` params with `template_vars: Dict[str, str]`.
  Per entry, `base_name` becomes:

  ```python
  base_name = naming.render(
      config.naming.template,
      **template_vars,
      method=method,
      segment=safe_segment,
  )
  ```

  The existing collision-suffix counter logic (keyed on the rendered
  `base_name`) is unchanged. Per-request `.format()` failures (e.g. a
  segment value that happens to contain `{`) are not expected since
  `segment` only ever contains `slugify()` output (`[A-Za-z0-9_]`), so no
  new per-request error handling is added — template validity against
  `template_vars` is checked once, up front, by the CLI (see below), not
  per-request.

## `jmx_xml.py` / `jmx_generator.py` changes

- `build_test_plan_scaffold(name: str, jmeter_version: str)` — version is
  no longer a literal inside the function.
- `build_jmx_xml(...)` (already receives `config`) passes
  `config.jmeter.version` through.
- `build_scenario_jmx.build_scenario_jmx(plan_name, include_files, config=None)`
  gains a `config` parameter (defaulting via `converter_config.default_config()`
  when `None`, matching `build_jmx_xml`'s existing pattern) purely so it can
  pass `config.jmeter.version` to the scaffold — it does not otherwise use
  `config`. `main()` is updated to pass the already-loaded `config` through.

## CLI changes

**`har_to_jmx.py`**
- Removes positional `project`, `product`.
- Adds `--var KEY=VALUE` (`action="append"`, default `[]`), repeatable.
  Splits on the first `=` only, so values may contain `=`. A value with no
  `=` is a parse error (`argparse.ArgumentTypeError`, standard argparse
  usage-error exit).
- Remaining positionals/flags unchanged: `har_path`, optional
  `host_mapping`, `--out-dir`, `--config`, `--verbose`.
- Before loading HAR entries: build `template_vars` from `--var` (last
  occurrence of a repeated key wins), then call
  `naming.validate_vars(config.naming.template, template_vars, reserved={"method", "segment"})`.
  On `ValueError`, print `f"Invalid --var arguments: {exc}"` to stderr and
  exit 1 — same pattern as the existing config/HAR-load error handling.

**`build_scenario_jmx.py`**
- Removes positional `project`, `product`; keeps `scenario_name` as its
  sole required positional (nothing else is unique to this CLI).
- Adds the same repeatable `--var KEY=VALUE`.
- Validates `config.naming.scenario_template` against
  `template_vars ∪ {"scenario_name"}` with `reserved={"scenario_name"}`
  the same way as above.
- `plan_name` is now
  `naming.render(config.naming.scenario_template, **template_vars, scenario_name=args.scenario_name)`
  instead of the current `f"{args.project}_{args.product}_{args.scenario_name}"`.

## Example usage after this change

```bash
python3 har_to_jmx.py login.har --var project=Abbot --var product=Merlin hosts.csv
python3 build_scenario_jmx.py recording.har Recent_Transmittions --var project=Abbot --var product=Merlin
```

A team with a flat naming scheme could instead configure:

```json
{ "naming": { "template": "{method}_{segment}", "scenario_template": "{scenario_name}" } }
```

and run `har_to_jmx.py login.har --config flat.json` with no `--var` at all.

## Error handling

All new failure modes follow the file's existing pattern (`print(..., file=sys.stderr); sys.exit(1)`):
- Malformed `--var` (no `=`): argparse usage error (standard argparse exit 2).
- Missing template variable(s): one message listing every missing key.
- `--var` setting a reserved key: one message listing every offending key.
- Template using a disallowed placeholder form (`{a.b}`, `{0}`, etc.):
  surfaced the same way, from `naming.required_fields`.

## Testing

Existing tests calling `process_har_entries`/`generate_jmx_files`
positionally with `"Project", "Product"` are updated to pass
`{"project": "Project", "product": "Product"}`.

New coverage:
- `naming.py`: `required_fields` on a template with multiple/repeated
  placeholders; `render` happy path; `validate_vars` missing-key and
  reserved-key-conflict cases; rejection of `{a.b}`/`{0}`/`{a:>10}` forms.
- `har_requests`: custom `naming.template` changes output filenames;
  collision suffixes still work with a custom template; header-value
  filtering via `skip_header_value_contains` (replacing the old
  "New Relic header" test with a generic one, plus a config-extended
  case).
- `jmx_generator`/`build_scenario_jmx`: `jmeter.version` override reflected
  in the generated `jmeterTestPlan` element.
- CLI smoke tests: `--var` flags produce the same output as today's
  positional-arg smoke test; missing `--var` for a required template
  field exits 1 with the expected stderr message; malformed `--var`
  (no `=`) exits with a usage error.

## Documentation

`README.md` and `CLAUDE.md` need their CLI examples, config schema section,
and "Fragment Filename Format" section updated to the `--var`-based
invocation and the new `naming` config block.
