import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from build_scenario_jmx import build_scenario_jmx
from converter_config import default_config, load_config, merge_host_maps
from har_requests import extract_last_segment, process_har_entries, slugify
from har_utils import load_har_entries
from jmx_generator import build_jmx_xml, generate_jmx_files
from naming import render, required_fields, validate_vars


ROOT = Path(__file__).resolve().parents[1]


def har_entry(url, method="GET", headers=None, body=None):
    request = {
        "url": url,
        "method": method,
        "headers": headers or [],
    }
    if body is not None:
        request["postData"] = {"text": body}
    return {"request": request}


def prop_text(root, name):
    for element in root.iter():
        if element.get("name") == name:
            return element.text or ""
    return None


def props_text(root, name):
    return [element.text or "" for element in root.iter() if element.get("name") == name]


class HarLoadingTests(unittest.TestCase):
    def test_load_supported_har_shapes(self):
        shapes = [
            {"log": {"entries": [har_entry("https://example.com/api")]}},
            {"entries": [har_entry("https://example.com/api")]},
            [har_entry("https://example.com/api")],
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            for index, shape in enumerate(shapes):
                path = Path(temp_dir) / f"{index}.har"
                path.write_text(json.dumps(shape), encoding="utf-8")
                self.assertEqual(len(load_har_entries(path)), 1)

    def test_unsupported_har_shape_returns_empty_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "badshape.har"
            path.write_text(json.dumps({"log": {}}), encoding="utf-8")
            self.assertEqual(load_har_entries(path), [])


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


class FilteringAndNamingTests(unittest.TestCase):
    def test_filters_noise_and_keeps_api_requests(self):
        entries = [
            har_entry("https://example.com/api/users"),
            har_entry("https://example.com/api/preflight", method="OPTIONS"),
            har_entry("https://example.com/assets/app.js"),
            har_entry("https://example.com/static"),
            har_entry("https://fonts.googleapis.com/css?family=Roboto"),
            har_entry("https://google-analytics.com/collect"),
            har_entry("https://example.com/nrjs/foo"),
            har_entry("https://example.com/api/users"),
        ]

        processed = process_har_entries(entries, {"project": "Project", "product": "Product"})

        self.assertEqual([request.url for request in processed.requests], ["https://example.com/api/users"])
        self.assertEqual(len(processed.skipped), 7)

    def test_naming_helpers_and_collision_suffixes(self):
        self.assertEqual(extract_last_segment("/"), "root")
        self.assertEqual(extract_last_segment("/api/v1/users/"), "users")
        self.assertEqual(slugify("recent items.json"), "recent_items_json")

        entries = [
            har_entry("https://example.com/api/users?id=1"),
            har_entry("https://example.com/other/users?id=2"),
        ]
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"})

        self.assertEqual(
            [request.file_name for request in processed.requests],
            ["Project_Product_GET_users.jmx", "Project_Product_GET_users_2.jmx"],
        )

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

    def test_form_encoded_params_without_text_are_captured_as_body(self):
        entry = {
            "request": {
                "url": "https://example.com/api/login",
                "method": "POST",
                "headers": [],
                "postData": {
                    "mimeType": "application/x-www-form-urlencoded",
                    "params": [
                        {"name": "username", "value": "alice"},
                        {"name": "password", "value": "s3cr3t!"},
                    ],
                },
            }
        }

        processed = process_har_entries([entry], {"project": "Project", "product": "Product"})

        self.assertEqual(len(processed.requests), 1)
        self.assertEqual(processed.requests[0].body, "username=alice&password=s3cr3t%21")

    def test_header_value_filter_skips_matching_requests(self):
        entries = [
            har_entry(
                "https://example.com/api/beacon",
                headers=[{"name": "X-Trace", "value": "nrjs-session-123"}],
            ),
            har_entry("https://example.com/api/users"),
        ]

        processed = process_har_entries(entries, {"project": "Project", "product": "Product"})

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
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"}, config)

        self.assertEqual([request.url for request in processed.requests], ["https://example.com/api/users"])

    def test_config_can_extend_filters_and_keep_urls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "filters": {
                            "skip_methods": ["TRACE"],
                            "skip_host_contains": ["telemetry.example.com"],
                            "skip_extensions": [".data"],
                            "keep_url_contains": ["/api/static-report.js"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_path)

        entries = [
            har_entry("https://example.com/api/static-report.js"),
            har_entry("https://telemetry.example.com/api/users"),
            har_entry("https://example.com/api/users.data"),
            har_entry("https://example.com/api/trace", method="TRACE"),
        ]
        processed = process_har_entries(entries, {"project": "Project", "product": "Product"}, config)

        self.assertEqual(
            [request.url for request in processed.requests],
            ["https://example.com/api/static-report.js"],
        )
        self.assertEqual(len(processed.skipped), 3)


class JmxGenerationTests(unittest.TestCase):
    def test_generated_xml_is_parseable_and_preserves_request_details(self):
        xml = build_jmx_xml(
            "Test_GET_users",
            "GET",
            "https://api.example.com/users?active=true&empty=",
            [
                {"name": ":authority", "value": "api.example.com"},
                {"name": "Authorization", "value": "Bearer secret-token"},
                {"name": "Origin", "value": "https://Q1EU-MERLIN.MERLIN.NET"},
            ],
            None,
            {"q1eu-merlin.merlin.net": "hostName"},
        )
        root = ET.fromstring(xml)

        self.assertEqual(prop_text(root, "HTTPSampler.path"), "/users")
        self.assertEqual(prop_text(root, "HTTPSampler.method"), "GET")
        self.assertEqual(prop_text(root, "HTTPSampler.postBodyRaw"), "false")
        self.assertEqual(prop_text(root, "HTTPSampler.domain"), "")
        self.assertEqual(prop_text(root, "HTTPSampler.protocol"), "")
        self.assertEqual(prop_text(root, "HTTPSampler.port"), "")

        values = props_text(root, "Header.value")
        names = props_text(root, "Header.name")
        self.assertNotIn(":authority", names)
        self.assertIn("Bearer ${TOKEN}", values)
        self.assertIn("https://${__P(hostName)}", values)
        self.assertIn("active", props_text(root, "Argument.name"))
        self.assertIn("true", props_text(root, "Argument.value"))
        self.assertIn("", props_text(root, "Argument.value"))

    def test_body_requests_use_raw_post_body(self):
        xml = build_jmx_xml(
            "Test_POST_token",
            "POST",
            "https://api.example.com/token?client=a",
            [],
            '{"grant_type":"client_credentials"}',
            {},
        )
        root = ET.fromstring(xml)

        self.assertEqual(prop_text(root, "HTTPSampler.path"), "/token?client=a")
        self.assertEqual(prop_text(root, "HTTPSampler.postBodyRaw"), "true")
        self.assertIn('{"grant_type":"client_credentials"}', props_text(root, "Argument.value"))

    def test_config_host_mapping_header_mask_and_jmeter_components(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "hosts": {"config.example.com": "configHost"},
                        "headers": {
                            "mask": [
                                {
                                    "name": "X-Api-Key",
                                    "prefix": "key-",
                                    "replacement": "${API_KEY}",
                                }
                            ]
                        },
                        "jmeter": {
                            "cookie_manager": True,
                            "cache_manager": True,
                            "http_defaults": True,
                            "http_defaults_protocol": "${__P(protocol,http)}",
                            "http_defaults_domain": "${__P(appHost)}",
                            "http_defaults_port": "${__P(port,8080)}",
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_path)

        host_map = merge_host_maps(config.hosts, {"config.example.com": "csvHost"})
        xml = build_jmx_xml(
            "Test_GET_users",
            "GET",
            "https://api.example.com/users",
            [
                {"name": "X-Api-Key", "value": "key-secret"},
                {"name": "Referer", "value": "https://config.example.com/home"},
            ],
            None,
            host_map,
            config,
        )
        root = ET.fromstring(xml)

        self.assertEqual(prop_text(root, "HTTPSampler.protocol"), "${__P(protocol,http)}")
        self.assertEqual(prop_text(root, "HTTPSampler.domain"), "${__P(appHost)}")
        self.assertEqual(prop_text(root, "HTTPSampler.port"), "${__P(port,8080)}")
        self.assertIsNotNone(root.find(".//CookieManager"))
        self.assertIsNotNone(root.find(".//CacheManager"))
        self.assertIsNotNone(root.find(".//ConfigTestElement"))
        self.assertIn("${API_KEY}", props_text(root, "Header.value"))
        self.assertIn("https://${__P(csvHost)}/home", props_text(root, "Header.value"))

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


class CliSmokeTests(unittest.TestCase):
    def test_fragment_and_scenario_commands_write_expected_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            har_path = temp_path / "recording.har"
            out_dir = temp_path / "out"
            har_path.write_text(
                json.dumps(
                    {
                        "log": {
                            "entries": [
                                har_entry("https://example.com/api/users?id=1"),
                                har_entry("https://example.com/other/users?id=2"),
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            fragments = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                    "--out-dir",
                    str(out_dir),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(fragments.returncode, 0, fragments.stderr)
            self.assertTrue((out_dir / "Project_Product_GET_users.jmx").is_file())
            self.assertTrue((out_dir / "Project_Product_GET_users_2.jmx").is_file())

            scenario = subprocess.run(
                [
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
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(scenario.returncode, 0, scenario.stderr)
            scenario_path = out_dir / "Project_Product_Scenario.jmx"
            self.assertTrue(scenario_path.is_file())
            scenario_root = ET.fromstring(scenario_path.read_text(encoding="utf-8"))
            includes = props_text(scenario_root, "IncludeController.includepath")
            self.assertEqual(
                includes,
                ["Project_Product_GET_users.jmx", "Project_Product_GET_users_2.jmx"],
            )

    def test_cli_errors_and_missing_host_mapping_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            invalid_har = temp_path / "invalid.har"
            invalid_har.write_text("{not json", encoding="utf-8")

            invalid = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(invalid_har),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("Failed to load HAR file", invalid.stderr)

            valid_har = temp_path / "valid.har"
            out_dir = temp_path / "out"
            valid_har.write_text(json.dumps([har_entry("https://example.com/api/users")]), encoding="utf-8")
            missing_csv = temp_path / "missing.csv"

            missing_mapping = subprocess.run(
                [
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
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(missing_mapping.returncode, 0, missing_mapping.stderr)
            self.assertIn("WARNING: host mapping file not found", missing_mapping.stdout)
            self.assertTrue((out_dir / "Project_Product_GET_users.jmx").is_file())

    def test_cli_config_works_and_invalid_config_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            har_path = temp_path / "recording.har"
            out_dir = temp_path / "out"
            config_path = temp_path / "config.json"
            bad_config_path = temp_path / "bad_config.json"
            har_path.write_text(
                json.dumps([har_entry("https://example.com/api/static-report.js")]),
                encoding="utf-8",
            )
            config_path.write_text(
                json.dumps({"filters": {"keep_url_contains": ["/api/static-report.js"]}}),
                encoding="utf-8",
            )
            bad_config_path.write_text("{not json", encoding="utf-8")

            result = subprocess.run(
                [
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
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((out_dir / "Project_Product_GET_static_report_js.jmx").is_file())

            bad_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                    "--config",
                    str(bad_config_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(bad_result.returncode, 0)
            self.assertIn("Failed to load config file", bad_result.stderr)

    def test_empty_har_is_successful_no_output_case(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            har_path = Path(temp_dir) / "empty.har"
            har_path.write_text(json.dumps({"entries": []}), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "har_to_jmx.py"),
                    str(har_path),
                    "--var",
                    "project=Project",
                    "--var",
                    "product=Product",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("No entries found in HAR.", result.stdout)

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

    def test_scenario_cli_var_validation_catches_fragment_template_only(self):
        # naming.scenario_template here needs nothing beyond the reserved
        # scenario_name, so only the fragment-template (naming.template)
        # validate_vars call can catch the missing "project" var. This
        # guards against the two validate_vars calls in main() being
        # collapsed into one, which would let this slip through as a raw
        # KeyError from process_har_entries instead of a clean CLI error.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            har_path = temp_path / "recording.har"
            har_path.write_text(
                json.dumps([har_entry("https://example.com/api/users")]),
                encoding="utf-8",
            )
            config_path = temp_path / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "naming": {
                            "template": "{project}_{method}_{segment}",
                            "scenario_template": "{scenario_name}",
                        }
                    }
                ),
                encoding="utf-8",
            )

            missing_fragment_var = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "build_scenario_jmx.py"),
                    str(har_path),
                    "Scenario",
                    "--config",
                    str(config_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(missing_fragment_var.returncode, 0)
            self.assertIn("Invalid --var arguments", missing_fragment_var.stderr)
            self.assertIn("project", missing_fragment_var.stderr)


class DirectGenerationTests(unittest.TestCase):
    def test_direct_generation_and_scenario_builder_are_parseable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            entries = [har_entry("https://example.com/api/users")]
            count = generate_jmx_files(entries, {"project": "Project", "product": "Product"}, {}, temp_dir)
            self.assertEqual(count, 1)
            fragment_path = Path(temp_dir) / "Project_Product_GET_users.jmx"
            ET.fromstring(fragment_path.read_text(encoding="utf-8"))

        scenario_xml = build_scenario_jmx("Project_Product_Scenario", ["Project_Product_GET_users.jmx"])
        ET.fromstring(scenario_xml)


if __name__ == "__main__":
    unittest.main()
