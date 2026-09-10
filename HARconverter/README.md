# HARConverter

HARConverter is a Python utility for converting browser HAR captures into Apache JMeter `.jmx` files.

The project currently supports two related workflows:

1. Generate one reusable JMeter fragment per meaningful HTTP request in a HAR file.
2. Generate a scenario JMX file that includes those fragments in the same order as the HAR recording.

The converter is designed for application and API traffic. By default, it filters out common browser noise such as static assets, fonts, analytics, tracking, monitoring, favicon requests, duplicate requests, and CORS preflight requests. For different web applications, the default behavior can be extended with a project-specific JSON config file.

## Project Contents

| File | Purpose |
| --- | --- |
| `har_to_jmx.py` | Main CLI entry point for converting a HAR file into individual JMeter fragment `.jmx` files. |
| `jmx_generator.py` | Core generation logic. Filters HAR requests and builds JMeter XML. |
| `build_scenario_jmx.py` | Builds a higher-level JMeter scenario `.jmx` that includes previously generated fragment files. |
| `jmx_xml.py` | Shared JMeter XML element helpers and the TestPlan/TestFragmentController scaffold used by both `jmx_generator.py` and `build_scenario_jmx.py`. |
| `converter_config.py` | Loads and merges optional JSON config for project-specific behavior. |
| `har_requests.py` | Shared request filtering, normalization, de-duplication, and collision-safe filename generation. |
| `har_utils.py` | Loads HAR entries from supported HAR JSON shapes. |
| `host_mapping.py` | Loads hostname-to-JMeter-property mappings from CSV. |
| `hosts.csv` | Current sample/configured host mapping file. |
| `tests/` | Standard-library regression tests for loading, filtering, naming, XML generation, and CLI smoke behavior. |
| `jmeter.log` | Runtime log produced by Apache JMeter. Not part of the converter logic. |
| `__pycache__/` | Python bytecode cache generated automatically by Python. Not part of the source logic. |

## Requirements

- Python 3
- Apache JMeter, for opening or running generated `.jmx` files

The Python scripts only use the Python standard library. No third-party Python dependencies are required.

All examples below use `python3`. On systems where `python` points to Python 3, `python` can be used instead.

The generated JMX declares:

```xml
<jmeterTestPlan version="1.2" properties="5.0" jmeter="5.6.0">
```

The existing `jmeter.log` shows the files have been opened with Apache JMeter 5.6.3.

## Input HAR Format

`har_utils.py` accepts these HAR shapes:

```json
{ "log": { "entries": [...] } }
```

```json
{ "entries": [...] }
```

```json
[
  { "request": {} }
]
```

Each entry should contain a HAR-style `request` object with fields such as:

- `url`
- `method`
- `headers`
- `postData`

Entries without an HTTP or HTTPS URL are ignored.

## Host Mapping CSV

Host mappings are optional. They are loaded from a CSV file with this format:

```csv
host,variableName
```

The current `hosts.csv` contains:

```csv
q1eu-merlin.merlin.net,hostName
q1mrb2ceu.b2clogin.com,ADHost
q1euapim.merlin.net,apiHost
```

Blank lines and lines starting with `#` are ignored.

Host matching is case-insensitive. When a mapped host appears in a header value, the generator replaces it with a JMeter property expression:

```text
${__P(variableName)}
```

For example:

```text
q1eu-merlin.merlin.net
```

becomes:

```text
${__P(hostName)}
```

## Generate Request Fragments

Run:

```bash
python3 har_to_jmx.py path/to/file.har Project Product [host_mapping.csv] [--out-dir output] [--config config.json] [--verbose]
```

Examples:

```bash
python3 har_to_jmx.py login.har Abbot Merlin
```

```bash
python3 har_to_jmx.py login.har Abbot Merlin hosts.csv
```

```bash
python3 har_to_jmx.py login.har Abbot Merlin hosts.csv --out-dir generated --verbose
```

```bash
python3 har_to_jmx.py login.har Abbot Merlin --config merlin-config.json --out-dir generated
```

Arguments:

| Argument | Required | Description |
| --- | --- | --- |
| `path/to/file.har` | Yes | HAR file to convert. |
| `Project` | Yes | Project name used in generated JMX filenames and test names. |
| `Product` | Yes | Product name used in generated JMX filenames and test names. |
| `host_mapping.csv` | No | Optional CSV file for replacing host values in headers with JMeter properties. |
| `--out-dir` | No | Output directory for generated JMX files. Defaults to the current directory. |
| `--config` | No | Optional JSON config for project-specific filters, host mappings, header masks, and JMeter options. |
| `--verbose` | No | Prints skipped request details and reasons. |

Generated files are written to the selected output directory.

### Fragment Filename Format

Each request fragment is named:

```text
Project_Product_METHOD_lastPathSegment.jmx
```

For example:

```text
Abbot_Merlin_GET_recent.jmx
Abbot_Merlin_POST_token.jmx
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

The segment is sanitized for filesystem safety by replacing non-alphanumeric runs with `_`.

### Request Filtering

`har_requests.py` contains the shared filtering logic used by both fragment generation and scenario generation. Without a config file, it skips:

- URLs that do not start with `http://` or `https://`
- `OPTIONS` requests
- duplicate `(method, url)` pairs
- `favicon.ico`
- static asset extensions:
  - `.js`
  - `.css`
  - `.woff`
  - `.woff2`
  - `.ttf`
  - `.otf`
  - `.png`
  - `.jpg`
  - `.jpeg`
  - `.svg`
  - `.gif`
  - `.ico`
  - `.map`
  - `.webp`
  - `.bmp`
  - `.mp4`
  - `.webm`
  - `.avi`
  - `.mov`
  - `.mp3`
  - `.wav`
- paths whose final segment is a static asset folder or asset type:
  - `js`
  - `css`
  - `fonts`
  - `font`
  - `images`
  - `img`
  - `static`
  - `assets`
  - `media`
  - `woff`
  - `woff2`
  - `ttf`
  - `otf`
  - `png`
  - `jpg`
  - `jpeg`
  - `svg`
  - `gif`
  - `ico`
  - `map`
  - `webp`
- font hosts:
  - `fonts.googleapis.com`
  - `fonts.gstatic.com`
- analytics, tracking, monitoring, and RUM hosts containing:
  - `google-analytics.com`
  - `googletagmanager.com`
  - `doubleclick.net`
  - `googlesyndication.com`
  - `hotjar.com`
  - `mixpanel.com`
  - `segment.io`
  - `segment.com`
  - `sentry.io`
  - `datadoghq.com`
  - `datadoghq.eu`
  - `browser-intake-datadoghq.com`
  - `app-measurement.com`
  - `amplitude.com`
  - `nr-data.net`
  - `js-agent.newrelic.com`
  - `logrocket.io`
  - `bugsnag.com`
  - `rollbar.com`
- URLs containing `nrjs` or `nr-data.net`
- requests whose header values contain `nrjs`

## Generated Fragment Structure

By default, each generated fragment contains:

- a JMeter `TestPlan`
- a disabled `TestFragmentController`
- one `HTTPSamplerProxy`
- one `HeaderManager`

The sampler has:

- request method set from the HAR request
- request path set from the HAR URL
- query arguments extracted when there is no request body
- raw post body enabled when `postData.text` exists
- redirects disabled
- keep-alive enabled

The sampler intentionally leaves these fields empty:

- `HTTPSampler.domain`
- `HTTPSampler.port`
- `HTTPSampler.protocol`

This means the default fragment does not hard-code target protocol, host, or port in the sampler. Those values are expected to be supplied elsewhere in the JMeter test plan, environment, defaults, or related configuration.

When enabled through JSON config, fragments can also include:

- `HTTP Request Defaults`
- `HTTP Cookie Manager`
- `HTTP Cache Manager`

These optional elements are disabled by default so existing output stays minimal and backward compatible.

## Header Handling

Headers are copied from the HAR request into the generated `HeaderManager`.

Special cases:

- HTTP/2 pseudo headers, such as `:authority`, are skipped.
- `Authorization: Bearer <token>` is masked by default as:

```text
Bearer ${TOKEN}
```

- additional header masking rules can be added through JSON config.
- mapped hosts in header values are replaced with JMeter property expressions.

All XML text is escaped before being written to the JMX file.

## Query Parameters and Request Bodies

For requests without a body:

- query parameters are parsed from the URL
- the sampler path excludes the query string
- parameters are added as JMeter HTTP arguments

For requests with `postData.text`:

- the request body is written as a raw HTTP argument
- `HTTPSampler.postBodyRaw` is set to `true`
- the sampler path keeps the query string if one exists

## Generate a Scenario JMX

After generating request fragments, run:

```bash
python3 build_scenario_jmx.py path/to/file.har Project Product ScenarioName [--out-dir output] [--config config.json] [--verbose]
```

Example:

```bash
python3 build_scenario_jmx.py recent.har Abbot Merlin Recent_Transmittions
```

```bash
python3 build_scenario_jmx.py recent.har Abbot Merlin Recent_Transmittions --out-dir generated --verbose
```

```bash
python3 build_scenario_jmx.py recent.har Abbot Merlin Recent_Transmittions --config merlin-config.json --out-dir generated
```

This creates:

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

The scenario builder applies the same shared filtering and filename generation as `har_to_jmx.py`, then checks whether the expected fragment file exists in the selected output directory.

If an expected fragment file is missing, it prints a warning:

```text
WARNING: JMX not found for METHOD URL -> expected file.jmx
```

If no matching fragments are found, no scenario file is generated.

## Recommended Workflow

1. Export a HAR file from the browser developer tools.
2. Put the HAR file in this folder or reference it by path.
3. Generate request fragments:

```bash
python3 har_to_jmx.py recording.har Abbot Merlin hosts.csv
```

4. Generate a scenario file:

```bash
python3 build_scenario_jmx.py recording.har Abbot Merlin ScenarioName
```

5. Open the scenario `.jmx` in Apache JMeter.
6. Configure protocol, host, port, authentication token, thread groups, timers, assertions, and any environment-specific properties required by the test.

## Project-Specific Configuration

The generator can be customized with an optional dependency-free JSON config file. If no config is provided, the built-in defaults preserve the original behavior.

Example:

```json
{
  "filters": {
    "skip_methods": ["OPTIONS"],
    "skip_host_contains": ["google-analytics.com", "sentry.io"],
    "skip_exact_hosts": ["fonts.googleapis.com", "fonts.gstatic.com"],
    "skip_extensions": [".js", ".css", ".png"],
    "skip_final_segments": ["static", "assets", "media"],
    "skip_url_contains": ["nrjs", "nr-data.net"],
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
    "cookie_manager": true,
    "cache_manager": true,
    "http_defaults": true,
    "http_defaults_protocol": "${__P(protocol,https)}",
    "http_defaults_domain": "${__P(hostName)}",
    "http_defaults_port": ""
  }
}
```

Config behavior:

- `filters` values extend the built-in defaults.
- `keep_url_contains` preserves matching HTTP/HTTPS requests even if another skip rule would normally remove them.
- invalid or non-HTTP URLs are always skipped.
- duplicate `(method, url)` pairs are always skipped.
- `hosts` replaces matching host values in headers with JMeter property expressions.
- `hosts.csv` remains supported and overrides config host mappings when both define the same host.
- `headers.mask` can add custom header masking rules.
- `jmeter` options are disabled by default and only appear in generated fragments when enabled.

Minimal config for an app that needs static-looking API endpoints:

```json
{
  "filters": {
    "keep_url_contains": ["/api/static-report.js", "/download/report.css"]
  }
}
```

Minimal config for an app with custom auth and JMeter defaults:

```json
{
  "headers": {
    "mask": [
      {
        "name": "X-Session-Token",
        "replacement": "${SESSION_TOKEN}"
      }
    ]
  },
  "hosts": {
    "qa-app.example.com": "hostName"
  },
  "jmeter": {
    "http_defaults": true,
    "cookie_manager": true,
    "http_defaults_domain": "${__P(hostName)}"
  }
}
```

## Current Limitations

- The converter does not create a full executable load test plan with thread groups.
- It does not add timers, assertions, extractors, correlation rules, or login/session handling.
- Sampler `domain`, `protocol`, and `port` are intentionally empty by default.
- HTTP Request Defaults, Cookie Manager, and Cache Manager can be enabled through JSON config, but advanced JMeter behavior still needs manual review.
- Host mapping is currently applied only to header values, not to sampler domain fields.
- Authorization Bearer masking is the default; other header masking rules can be added with JSON config.
- Fragment filenames are based on method and last URL path segment, with deterministic suffixes added for collisions.
- Generated `.jmx` files are written into the selected output directory.
- The project has automated regression tests, but it does not currently validate generated files by opening them in JMeter.

## Testing

Run the standard-library test suite with:

```bash
python3 -m unittest discover -s tests
```

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

## Runtime and Generated Artifacts

These files/directories are not source logic:

- `jmeter.log`
- `__pycache__/`
- generated `.jmx` files

They can be regenerated by running Python or opening files in JMeter.

## Maintenance Notes

When changing request filtering, update:

- `har_requests.py`

When adding support for new authentication schemes or host substitutions, start in:

- `converter_config.py`
- `jmx_generator.py`

When changing accepted HAR input shapes, update:

- `har_utils.py`

When changing host mapping CSV rules, update:

- `host_mapping.py`

When changing the shared JMeter TestPlan/TestFragmentController scaffold used by both fragment and scenario output, update:

- `jmx_xml.py`
